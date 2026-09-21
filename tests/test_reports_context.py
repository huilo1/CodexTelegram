import asyncio
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
from types import SimpleNamespace

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from codex_telegram_reports.deny_tools import decision
from codex_telegram_reports.project_context import build_snapshot, bounded_run, clean_env
from codex_telegram_reports.project_reader import ProjectReader, TOOL_NAMES
from codex_telegram_reports.store import Store


def git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, check=True).stdout.strip()


def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init")
    git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-m", "Initial")
    return root


def test_snapshot_excludes_secrets_ignored_binary_and_path_escapes(tmp_path):
    root = repo(tmp_path)
    (root/"main.py").write_text("def answer():\n    return 42\n")
    (root/".env").write_text("INTERNAL=NEVER_COPY")
    git(root, "add", ".env")  # Even tracked environment files are excluded.
    (root/".gitignore").write_text("private.txt\n")
    (root/"private.txt").write_text("NEVER_COPY")
    (root/"binary.bin").write_bytes(b"\x00NEVER_COPY")
    outside = tmp_path/"outside.txt"
    outside.write_text("NEVER_COPY")
    (root/"link.txt").symlink_to(outside)
    os.link(outside, root/"hard.txt")
    (root/"external").symlink_to(tmp_path, target_is_directory=True)
    (root/"settings.txt").write_text('api_key="NEVER_COPY"\n')
    metadata = build_snapshot(root, root, tmp_path/"snapshot")
    reader = ProjectReader(tmp_path/"snapshot")
    assert "main.py" in reader.paths
    assert {"path": "main.py", "status": "??"} in metadata["changed_files"]
    assert not any(item["path"] == ".env" for item in metadata["changed_files"])
    assert not {".env", "private.txt", "binary.bin", "link.txt", "hard.txt"} & reader.paths
    for p in (tmp_path/"snapshot").rglob("*"):
        if p.is_file():
            assert "NEVER_COPY" not in p.read_text()
    assert metadata["omitted_files"] >= 5
    assert reader.search("return 42")["matches"][0]["line"] == 2
    for name in ("../outside.txt", str(outside), ".env", "main.py/../.env"):
        with pytest.raises(ValueError):
            reader.read_file(name)


def test_diff_has_staged_and_unstaged_changes_and_never_runs_external_diff(tmp_path):
    root = repo(tmp_path)
    (root/"main.py").write_text("original = 1\n")
    git(root, "add", "main.py")
    git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "Source")
    (root/"main.py").write_text("staged = 2\n")
    git(root, "add", "main.py")
    (root/"main.py").write_text("unstaged = 3\n")
    marker = tmp_path/"external-executed"
    git(root, "config", "diff.external", "touch " + str(marker))
    (root/".gitattributes").write_text("main.py filter=probe\n")
    git(root, "config", "filter.probe.clean", "touch " + str(marker))
    git(root, "config", "filter.probe.process", "touch " + str(marker))
    git(root, "config", "filter.probe.required", "true")
    build_snapshot(root, root, tmp_path/"snapshot")
    text = ProjectReader(tmp_path/"snapshot").changes()["diff"]
    assert "-original = 1" in text and "+unstaged = 3" in text
    assert not marker.exists()


def test_reply_chain_keeps_original_task_and_worktree(tmp_path):
    root = repo(tmp_path)
    work = tmp_path/"work"
    git(root, "worktree", "add", str(work))
    store = Store(tmp_path/"state.db")
    store.reporting_mode("all")
    try:
        one = store.report(str(work), "thread-a", "task-a", "Worktree task", "progress", "First")
        store.bind_topic(one["project_id"], 50)
        store.sent(store.pending_delivery()["id"], 100)
        store.task_context(str(work), "thread-a", "task-a", {"goal": "Explain code", "decisions": "Use a snapshot"})
        store.report(str(root), "thread-b", "task-b", "Main task", "progress", "Second")
        store.sent(store.pending_delivery()["id"], 101)
        store.ingest(-100123, [{"id": 102, "sender_id": 7, "text": "Why?", "topic_id": 50, "reply_to": 100}], {7})
        question = store.pending_question()
        context = store.context(question)
        assert context["_workspace"] == str(work)
        assert context["task_context"]["goal"] == "Explain code"
        assert context["reply_report"]["task_id"] == "task-a"
        store.answer(question, "Because of isolation")
        store.sent(store.pending_delivery()["id"], 103)
        store.ingest(-100123, [{"id": 104, "sender_id": 7, "text": "And then?", "topic_id": 50, "reply_to": 103}], {7})
        context = store.context(store.pending_question())
        assert context["_workspace"] == str(work)
        assert context["previous_questions"] == [{"body": "Why?", "answer": "Because of isolation"}]
        store.answer(store.pending_question(), "Next step")
        store.ingest(-100123, [{"id": 105, "sender_id": 7, "text": "Current?", "topic_id": 50}], {7})
        context = store.context(store.pending_question())
        assert context["reply_report"]["task_id"] == "task-b"
        assert not context["previous_questions"]
    finally:
        store.close()


def test_snapshot_rejects_another_project(tmp_path):
    a, b = tmp_path/"a", tmp_path/"b"
    a.mkdir(); b.mkdir()
    with pytest.raises(ValueError, match="belongs"):
        build_snapshot(a, b, tmp_path/"snapshot")


def test_tool_guard_rejects_general_execution_and_similar_mcp_names():
    for name in TOOL_NAMES:
        assert decision({"tool_name": "mcp__project_reader__"+name}) == {}
    for name in ("exec_command", "apply_patch", "mcp__project_reader__run_shell", "mcp__evil__read_file", "functions.exec", None):
        assert decision({"tool_name": name})["decision"] == "block"


@pytest.mark.asyncio
async def test_snapshot_mcp_real_transport(tmp_path):
    root = tmp_path/"repo"; root.mkdir()
    (root/"main.py").write_text("RESULT = 42\n")
    build_snapshot(root, root, tmp_path/"snapshot")
    params = StdioServerParameters(command=sys.executable, args=["-m", "codex_telegram_reports.project_reader", str(tmp_path/"snapshot"), "codex"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            assert {t.name for t in (await session.list_tools()).tools} == set(TOOL_NAMES)
            answer = await session.call_tool("read_file", {"path": "main.py"})
            assert "42" in answer.content[0].text
            assert (await session.call_tool("read_file", {"path": "../outside"})).isError


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("codex"), reason="Live macOS sandbox check")
def test_diagnostic_sandbox_enforces_real_boundaries(tmp_path, monkeypatch):
    root = tmp_path/"repo"; root.mkdir()
    (root/"main.py").write_text("def answer():\n    return 42\n")
    outside = tmp_path/"outside.txt"; outside.write_text("NEVER_LEAK")
    monkeypatch.setenv("PRIVATE_TEST_CREDENTIAL", "NEVER_LEAK")
    build_snapshot(root, root, tmp_path/"snapshot")
    reader = ProjectReader(tmp_path/"snapshot", shutil.which("codex"))
    victim = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"], start_new_session=True)
    socket_dir = tempfile.TemporaryDirectory(prefix="telegram-test-", dir="/tmp")
    socket_path = str(Path(socket_dir.name)/"probe.sock")
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(socket_path)
    listener.listen(1)
    try:
        code = """import ast, os, socket, subprocess
tree = ast.parse((PROJECT/'main.py').read_text())
print([node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)])
(SCRATCH/'result.txt').write_text('diagnostic only')
print('scratch_ok')
assert 'PRIVATE_TEST_CREDENTIAL' not in os.environ
actions = {
 'write_snapshot': lambda: (PROJECT/'main.py').write_text('wrong'),
 'read_outside': lambda: pathlib.Path(OUTSIDE).read_text(),
 'write_project': lambda: pathlib.Path(ORIGINAL).write_text('wrong'),
 'tcp': lambda: socket.create_connection(('127.0.0.1',9),timeout=1),
 'unix': lambda: socket.socket(socket.AF_UNIX).connect(SOCKET_PATH),
 'spawn': lambda: subprocess.run(['/bin/echo','SPAWNED']),
 'signal': lambda: os.kill(VICTIM,15),
}
for name, action in actions.items():
 try:
  action(); print(name+':ALLOWED')
 except OSError as error:
  print(name+':'+type(error).__name__)
"""
        code = "import pathlib\nOUTSIDE="+repr(str(outside))+"\nORIGINAL="+repr(str(root/"main.py"))+"\nVICTIM="+str(victim.pid)+"\nSOCKET_PATH="+repr(socket_path)+"\n"+code
        result = reader.run_python(code)
        assert result["returncode"] == 0, result
        assert "['answer']" in result["output"] and "scratch_ok" in result["output"]
        assert "ALLOWED" not in result["output"] and "NEVER_LEAK" not in result["output"]
        for name in ("write_snapshot", "read_outside", "write_project", "tcp", "unix", "signal"):
            assert name+":PermissionError" in result["output"], result
        assert victim.poll() is None
        assert (root/"main.py").read_text() == "def answer():\n    return 42\n"
        result = reader.run_python("print('a'*100000)")
        assert result["limited"] == "output limit"
    finally:
        victim.terminate(); victim.wait()
        listener.close(); socket_dir.cleanup()


def test_bounded_runner_kills_long_running_process(tmp_path):
    result = bounded_run([sys.executable, "-c", "import time;time.sleep(60)"], cwd=tmp_path, timeout=.1)
    assert result["limited"] == "time limit"


def test_service_update_retries_transient_launchd_bootstrap(tmp_path, monkeypatch):
    from codex_telegram_reports import cli
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    monkeypatch.setattr(cli.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(cli, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)
    calls = []
    def run(args, **kwargs):
        calls.append(args[1])
        return SimpleNamespace(returncode=5 if calls == ["bootout", "bootstrap"] else 0)
    monkeypatch.setattr(cli.subprocess, "run", run)
    cli.launchd("install")
    assert calls == ["bootout", "bootstrap", "bootstrap"]
