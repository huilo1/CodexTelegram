import importlib.util
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
from types import SimpleNamespace

import pytest

from codex_telegram_reports import cli, diagnostics
from codex_telegram_reports.config import load_config, save_config
from codex_telegram_reports.hooks import handle
from codex_telegram_reports.store import Store


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def private_home(tmp_path, monkeypatch):
    path = tmp_path/"private home"
    monkeypatch.setenv("CODEX_TELEGRAM_REPORTS_HOME", str(path))
    return path


def test_api_setup_requires_own_keys_retries_and_never_echoes_hash(private_home, monkeypatch, capsys):
    values = iter(["", "12345"])
    secret = "abcdef"*5+"ab"
    hashes = iter(["wrong", secret])
    monkeypatch.setattr("builtins.input", lambda _: next(values))
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: next(hashes))
    cli.configure_api()
    assert load_config()["api_id"] == 12345
    assert load_config()["api_hash"] == secret
    assert secret not in capsys.readouterr().out
    assert (private_home/"config.json").stat().st_mode & 0o777 == 0o600
    assert private_home.stat().st_mode & 0o777 == 0o700
    # Re-running setup never asks for or replaces existing credentials.
    cli.configure_api()
    assert load_config()["api_hash"] == secret


def test_cancel_does_not_save_credentials(private_home, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "/cancel")
    with pytest.raises(ValueError):
        cli.configure_api()
    assert not (private_home/"config.json").exists()


def test_fresh_install_does_not_report_until_project_selected(private_home, tmp_path):
    store = Store()
    try:
        event = dict(cwd=str(tmp_path), session_id="s", turn_id="t", hook_event_name="UserPromptSubmit")
        assert handle(event, store, {}) == {}
        assert store.health()["pending_messages"] == 0
        store.set_project_enabled(str(tmp_path), True)
        assert handle(event, store, {})["hookSpecificOutput"]
        assert store.health()["pending_messages"] == 1
    finally:
        store.close()


def test_modes_preserve_explicit_project_overrides(private_home, tmp_path):
    a, b, c = (tmp_path/n for n in ("a", "b", "c"))
    for p in (a, b, c):
        p.mkdir()
    store = Store()
    try:
        store.reporting_mode("all")
        store.register(str(a))
        store.set_project_enabled(str(b), False)
        store.set_project_enabled(str(c), True)
        store.reporting_mode("selected")
        assert [store.register(str(p))["enabled"] for p in (a,b,c)] == [0,0,1]
        store.reporting_mode("all")
        assert [store.register(str(p))["enabled"] for p in (a,b,c)] == [1,0,1]
    finally:
        store.close()


def test_legacy_database_keeps_all_projects_on_upgrade(private_home, tmp_path):
    store = Store()
    store.reporting_mode("all")
    store.register(str(tmp_path))
    with store.db:
        store.db.execute("DELETE FROM meta WHERE key='reporting_mode'")
        store.db.execute("ALTER TABLE projects DROP COLUMN opted")
    store.close()
    store = Store()
    try:
        assert store.get_meta("reporting_mode") == "all"
        new = tmp_path/"another"; new.mkdir()
        assert store.register(str(new))["enabled"] == 1
    finally:
        store.close()


def test_disabling_project_holds_delivery_questions_and_inflight_answer(private_home, tmp_path):
    store = Store()
    try:
        store.set_project_enabled(str(tmp_path), True)
        report = store.report(str(tmp_path), "s", "t", "Title", "progress", "Report")
        store.bind_topic(report["project_id"], 20)
        store.ingest(10,[dict(id=21,sender_id=7,text="Status?",topic_id=20)],{7})
        question = store.pending_question()
        store.set_project_enabled(str(tmp_path), False)
        assert store.pending_delivery() is None
        assert store.pending_question() is None
        assert store.pending_feedback() is None
        store.answer(question, "Answer from an already running model")
        assert store.db.execute("SELECT answer FROM questions").fetchone()[0] is None
        store.set_project_enabled(str(tmp_path), True)
        assert store.pending_delivery() and store.pending_question()
    finally:
        store.close()


def test_onboarding_does_not_change_existing_owner_selection(private_home, tmp_path, monkeypatch):
    save_config(dict(group_id=42))
    store = Store(); store.reporting_mode("all"); store.close()
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("existing setup should not prompt"))
    cli.configure_reporting()
    store = Store()
    try:
        assert store.register(str(tmp_path))["enabled"] == 1
    finally:
        store.close()


def test_doctor_reports_missing_setup_without_secrets(private_home, monkeypatch):
    secret = "private-diagnostic-fixture"
    save_config(dict(api_id=123, api_hash=secret))
    monkeypatch.setattr(diagnostics.shutil, "which", lambda _: None)
    result = diagnostics.diagnose()
    assert not result["ready"]
    assert secret not in json.dumps(result)
    assert not next(c for c in result["checks"] if c["name"] == "service")["ok"]


def installer():
    spec = importlib.util.spec_from_file_location("reports_install_test", ROOT/"plugins/codex-telegram-reports/scripts/install.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_staged_install_failure_keeps_active_runtime(private_home, monkeypatch):
    module = installer()
    old = private_home/"venv"; old.mkdir(parents=True)
    (old/"marker").write_text("keep")
    monkeypatch.setattr(module.sys, "platform", "darwin")
    monkeypatch.setattr(module.venv, "create", lambda p, **kw: p.mkdir())
    def fail(*args, **kw):
        raise subprocess.CalledProcessError(1, ["pip"])
    monkeypatch.setattr(module.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        module.install()
    assert (old/"marker").read_text() == "keep"
    assert not old.is_symlink()


def test_legacy_runtime_switch_and_rollback_preserve_data(private_home, monkeypatch):
    module = installer()
    (private_home/"runtimes").mkdir(parents=True)
    old = private_home/"venv"; (old/"bin").mkdir(parents=True)
    (old/"bin/python").write_text("original")
    config = private_home/"config.json"; config.write_text('{"keep":true}')
    new = private_home/"runtimes/new"; (new/"bin").mkdir(parents=True)
    (new/"bin/python").write_text("new")
    previous = module.switch(private_home,new)
    module.replace_state(private_home,previous,new)
    monkeypatch.setattr(module.sys,"platform","darwin")
    monkeypatch.setattr(module,"owns_service",lambda _:False)
    module.install(rollback=True)
    assert (private_home/"venv/bin/python").read_text() == "original"
    assert config.read_text() == '{"keep":true}'


def test_runtime_lock_refuses_concurrent_session_writer(private_home):
    module = installer()
    private_home.mkdir()
    with module.exclusive(private_home/"service.lock"):
        with pytest.raises(RuntimeError):
            with module.exclusive(private_home/"service.lock"):
                pytest.fail("lock should prevent concurrent access")


def test_setup_reuses_personal_source_and_refuses_duplicate_hooks(monkeypatch):
    scripts = ROOT/"plugins/codex-telegram-reports/scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("reports_setup_test", scripts/"setup.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    entry = dict(name="codex-telegram-reports",marketplaceName="personal",
                 source=dict(source="local",path=str(scripts.parent)))
    assert module.installation_marketplace({"installed":[]},"local-dev") == "local-dev"
    assert module.installation_marketplace({"installed":[entry]},"local-dev") == "personal"
    with pytest.raises(RuntimeError):
        module.installation_marketplace({"installed":[entry,entry]},"local-dev")
    with pytest.raises(RuntimeError):
        module.installation_marketplace({"plugins":[]},"local-dev")
    entry["source"] = {"source":"local","path":"/another/checkout"}
    with pytest.raises(RuntimeError):
        module.installation_marketplace({"installed":[entry]},"local-dev")


@pytest.mark.parametrize("event_name", ["SessionStart", "UserPromptSubmit", "Stop", "Interrupt"])
def test_hook_bootstrap_works_without_plugin_cache(private_home, tmp_path, event_name):
    private_home.mkdir()
    (private_home / "venv").symlink_to(Path(sys.prefix), target_is_directory=True)
    project = tmp_path / "project with spaces"
    project.mkdir()
    (project / "pathlib.py").write_text("raise RuntimeError('project shadow')")
    store = Store(private_home / "reports.sqlite3")
    store.reporting_mode("all")
    store.close()
    config = json.loads((ROOT / "plugins/codex-telegram-reports/hooks/hooks.json").read_text())
    command = config["hooks"][event_name][0]["hooks"][0]["command"]
    event = {"hook_event_name": event_name, "cwd": str(project), "session_id": "smoke-thread",
             "turn_id": "smoke-turn", "last_assistant_message": "Public final smoke test"}
    env = dict(os.environ, PLUGIN_ROOT=str(tmp_path / "removed plugin cache"), PYTHONPATH=str(project))
    env.pop("CODEX_TELEGRAM_REPORTER_CHILD", None)
    result = subprocess.run(["/bin/sh", "-c", command], input=json.dumps(event), text=True,
                            capture_output=True, cwd=project, env=env, check=True, timeout=10)
    response = json.loads(result.stdout)
    if event_name in {"SessionStart", "UserPromptSubmit"}:
        assert response["hookSpecificOutput"]["hookEventName"] == event_name
    store = Store(private_home / "reports.sqlite3")
    try:
        assert store.health()["pending_messages"] == (0 if event_name == "SessionStart" else 1)
    finally:
        store.close()


def test_update_restores_only_old_bootstraps_after_cache_removal(tmp_path, monkeypatch):
    scripts = ROOT / "plugins/codex-telegram-reports/scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("reports_setup_bridges_test", scripts / "setup.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    cache = tmp_path / "plugins/cache/personal/codex-telegram-reports"
    old = cache / "old/scripts/run.py"
    old.parent.mkdir(parents=True)
    old.write_text("old bootstrap")
    launchers = module.existing_hook_launchers("personal")
    shutil.rmtree(cache)
    fresh = cache / "new/scripts/run.py"
    fresh.parent.mkdir(parents=True)
    fresh.write_text("new bootstrap")
    module.restore_hook_launchers(launchers)
    assert old.read_bytes() == (scripts / "run.py").read_bytes()
    assert fresh.read_text() == "new bootstrap"
    assert not (old.parent.parent / "hooks").exists()
