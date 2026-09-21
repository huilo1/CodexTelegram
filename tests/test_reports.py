from __future__ import annotations

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from codex_telegram_reports.config import redact, split_text, project_root
from codex_telegram_reports.hooks import handle
from codex_telegram_reports.responder import command
from codex_telegram_reports.service import Service
from codex_telegram_reports.store import Store
from codex_telegram_reports.telegram import Transport, incoming


@pytest.fixture
def store(tmp_path):
    result = Store(tmp_path / "reports.sqlite3")
    result.reporting_mode("all")
    yield result
    result.close()


def report(store, path, task="task1", thread="thread1", **kw):
    return store.report(str(path), thread, task, "Исправить поиск", kw.get("state", "progress"), kw.get("summary", "Проверены сценарии поиска"), kw.get("key"))


def delivered(store, path):
    result = report(store, path)
    store.bind_topic(result["project_id"], 50)
    store.sent(store.pending_delivery()["id"], 100)
    return result


def question(store, text="Что осталось?", sender=7, topic=50, message_id=101, reply_to=100):
    store.ingest(-100123, [{"id": message_id, "sender_id": sender, "out": False, "text": text, "topic_id": topic, "reply_to": reply_to}], {7})
    return store.pending_question()


def test_project_has_many_tasks_and_duplicate_retry_survives_restart(store, tmp_path):
    first = report(store, tmp_path, key="event")
    report(store, tmp_path, key="event")
    report(store, tmp_path, task="task2", key="event")
    assert len(store.projects()) == 1
    assert store.db.execute("SELECT count(*) FROM reports").fetchone()[0] == 2
    second = Store(tmp_path / "reports.sqlite3")
    try:
        assert report(second, tmp_path, key="event")["report_id"] == first["report_id"]
        assert second.pending_delivery()["random_id"] == store.pending_delivery()["random_id"]
    finally:
        second.close()


def test_worktrees_share_project(tmp_path):
    root = tmp_path / "repo"; root.mkdir()
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-m", "Initial"], check=True, capture_output=True)
    work = tmp_path / "work"
    subprocess.run(["git", "-C", str(root), "worktree", "add", str(work)], check=True, capture_output=True)
    assert project_root(str(work)) == str(root.resolve())


def test_same_names_in_different_directories_stay_separate(store, tmp_path):
    a, b = tmp_path / "a" / "app", tmp_path / "b" / "app"
    a.mkdir(parents=True); b.mkdir(parents=True)
    assert report(store, a)["project_id"] != report(store, b)["project_id"]


def test_acl_unknown_topics_duplicates_and_cursor_are_atomic(store, tmp_path):
    delivered(store, tmp_path)
    assert question(store, sender=8) is None
    assert question(store, topic=999, message_id=102) is None
    question(store, message_id=103)
    question(store, message_id=103)
    assert store.db.execute("SELECT count(*) FROM questions").fetchone()[0] == 1
    assert store.get_meta("cursor:-100123") == 103


def test_context_excludes_undelivered_and_other_projects(store, tmp_path):
    delivered(store, tmp_path)
    report(store, tmp_path, summary="SECRET_UNDELIVERED")
    another = tmp_path / "other"; another.mkdir()
    report(store, another, summary="OTHER_PROJECT")
    payload = json.dumps(store.context(question(store)))
    assert "SECRET_UNDELIVERED" not in payload
    assert "OTHER_PROJECT" not in payload
    assert store.context(store.pending_question())["reply_report"]["task_id"] == "task1"


def test_unicode_chunks_redaction(store, tmp_path):
    text = "😀" * 4000
    parts = split_text(text)
    assert "".join(parts) == text
    assert all(len(x.encode("utf-16-le")) // 2 <= 3500 for x in parts)
    assert "supersecret" not in redact("password=supersecret")
    assert "supersecret" not in redact('TELEGRAM_API_HASH="supersecret"')
    assert "supersecret" not in redact('"api_key": "supersecret"')
    assert "supersecret" not in redact('Authorization: Bearer supersecret')
    report(store, tmp_path, summary=text)
    assert store.db.execute("SELECT count(*) FROM outbox").fetchone()[0] == 1
    assert store.db.execute("SELECT summary FROM reports").fetchone()[0] == text
    assert "/full" in store.pending_delivery()["body"]


def test_hooks_do_not_copy_prompt_and_do_not_start_child_reports(store, tmp_path, monkeypatch):
    event = {"hook_event_name": "UserPromptSubmit", "cwd": str(tmp_path), "session_id": "thread", "turn_id": "turn", "prompt": "api_key=NEVER_EXPORT_THIS"}
    result = handle(event, store, {})
    assert "turn" in result["hookSpecificOutput"]["additionalContext"]
    assert "NEVER_EXPORT_THIS" not in store.pending_delivery()["body"]
    handle(event, store, {})
    assert store.health()["pending_messages"] == 1
    monkeypatch.setenv("CODEX_TELEGRAM_REPORTER_CHILD", "1")
    event["turn_id"] = "another"
    assert handle(event, store, {}) == {}
    assert store.health()["pending_messages"] == 1


class FakeTransport:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    async def ensure_topic(self, project):
        return 50

    async def send(self, delivery, topic_id):
        self.sent.append((delivery["random_id"], topic_id, delivery["reply_to"]))
        if self.fail:
            self.fail = False
            raise ConnectionError("Lost ACK")
        return 100 + len(self.sent)


class FakeResponder:
    def __init__(self):
        self.calls = []

    async def answer(self, context, text):
        self.calls.append((context, text))
        return "Осталась проверка доставки."


@pytest.mark.asyncio
async def test_retry_keeps_random_id_and_topic(store, tmp_path):
    report(store, tmp_path)
    transport = FakeTransport(fail=True)
    service = Service(store, transport, FakeResponder(), {"allowed_user_ids": [7]})
    await service.deliver_one()
    assert store.health()["pending_messages"] == 1
    with store.db:
        store.db.execute("UPDATE outbox SET retry_at=0")
    await service.deliver_one()
    assert transport.sent[0] == transport.sent[1]
    assert store.health()["pending_messages"] == 0


@pytest.mark.asyncio
async def test_questions_answer_in_same_topic_and_reply_to_question(store, tmp_path):
    delivered(store, tmp_path)
    question(store)
    responder = FakeResponder()
    service = Service(store, FakeTransport(), responder, {"allowed_user_ids": [7]})
    await service.answer_one()
    assert len(responder.calls) == 1
    assert store.pending_delivery()["reply_to"] == 101
    assert store.pending_question() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["/new build an app", "/exec rm -rf anything", "/approve", "/side change code"])
async def test_development_commands_never_invoke_codex(store, tmp_path, text):
    delivered(store, tmp_path); question(store, text)
    responder = FakeResponder()
    await Service(store, FakeTransport(), responder, {"allowed_user_ids": [7]}).answer_one()
    assert not responder.calls
    assert "только отчёты" in store.pending_delivery()["body"]


@pytest.mark.asyncio
async def test_status_works_without_model(store, tmp_path):
    delivered(store, tmp_path); question(store, "/status")
    responder = FakeResponder()
    await Service(store, FakeTransport(), responder, {"allowed_user_ids": [7]}).answer_one()
    assert not responder.calls
    assert "Проверены" in store.pending_delivery()["body"]


@pytest.mark.asyncio
async def test_error_answer_does_not_leak_diagnostics(store, tmp_path):
    class Broken:
        async def answer(self, *args):
            raise RuntimeError("api_key=SECRET")
    delivered(store, tmp_path); question(store)
    await Service(store, FakeTransport(), Broken(), {"allowed_user_ids": [7]}).answer_one()
    assert "SECRET" not in store.pending_delivery()["body"]


def test_nested_topic_reply_routing():
    msg = SimpleNamespace(id=8, sender_id=7, out=False, message="question", reply_to=SimpleNamespace(forum_topic=True, reply_to_top_id=50, reply_to_msg_id=77))
    assert incoming(msg)["topic_id"] == 50
    assert incoming(msg)["reply_to"] == 77
    msg.reply_to.reply_to_top_id = None
    msg.reply_to.reply_to_msg_id = 50
    assert incoming(msg)["topic_id"] == 50


def test_responder_is_ephemeral_isolated_and_has_tool_guard(tmp_path):
    args = command("codex", tmp_path, tmp_path / "instructions", tmp_path / "answer")
    assert "--ignore-user-config" in args
    assert "--ephemeral" in args
    assert "--dangerously-bypass-hook-trust" not in args
    assert "read-only" in args
    assert 'approval_policy="never"' in args
    assert "features.plugins=false" in args
    assert "features.shell_tool=false" in args
    assert any(x.startswith("hooks.PreToolUse=") and "deny_tools.py" in x for x in args)
    assert "resume" not in args and "fork" not in args


@pytest.mark.asyncio
async def test_transport_uses_current_telegram_schema():
    from telethon import types, functions
    requests = []
    async def client(request):
        requests.append(request)
        return SimpleNamespace(updates=[types.UpdateMessageID(id=55, random_id=request.random_id)])
    transport = Transport(client, types.InputPeerChannel(123, 456))
    topic = await transport.ensure_topic({"topic_id": None, "name": "Demo", "topic_random_id": 999})
    assert topic == 55
    assert isinstance(requests[0], functions.messages.CreateForumTopicRequest)
    message_id = await transport.send({"reply_to": 60, "body": "Hello", "random_id": 1000}, 55)
    assert message_id == 55
    assert requests[1].reply_to.top_msg_id == 55
    assert requests[1].reply_to.reply_to_msg_id == 60
