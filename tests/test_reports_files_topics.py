import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from telethon import functions, types

from codex_telegram_reports.attachments import attachment_path, list_deliverables, stage_file
from codex_telegram_reports.compact import compact
from codex_telegram_reports.project_context import build_snapshot
from codex_telegram_reports.project_reader import ProjectReader
from codex_telegram_reports.service import Service
from codex_telegram_reports.store import Store
from codex_telegram_reports.telegram import Transport
from test_reports_context import git, repo


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_TELEGRAM_REPORTS_HOME", str(tmp_path / "private"))
    root = repo(tmp_path)
    store = Store(tmp_path / "state.db")
    store.reporting_mode("all")
    result = store.report(str(root), "thread", "task", "Task", "progress", "Ready")
    store.bind_topic(result["project_id"], 50)
    store.sent(store.pending_delivery()["id"], 100)
    yield store, root
    store.close()


def ingest(store, body, message=101, reply=100, topic=50, sender=7):
    store.ingest(-123, [{"id": message, "sender_id": sender, "topic_id": topic,
                        "text": body, "reply_to": reply}], {7})
    return store.pending_question()


@pytest.mark.asyncio
async def test_requested_file_is_immutable_and_keeps_reply_and_retry_id(setup):
    store, root = setup
    (root / "build").mkdir()
    path = root / "build/app.apk"
    original = b"PK\x00test-build"
    path.write_bytes(original)
    ingest(store, '/file "build/app.apk"')
    worker = Service(store, None, None, {"allowed_user_ids": [7]})
    await worker.answer_one()
    store.sent(store.pending_delivery()["id"], 102)
    delivery = store.pending_delivery()
    path.write_bytes(b"new version")
    assert attachment_path(delivery["file_digest"]).read_bytes() == original
    assert delivery["reply_to"] == 101
    assert store.pending_feedback()["desired"] == "shown"
    calls, uploads = [], []
    class Client:
        async def upload_file(self, stream, **kwargs):
            uploads.append(stream.read())
            return types.InputFile(123, 1, "app.apk", "checksum")
        async def __call__(self, request):
            calls.append(request)
            if len(calls) == 1:
                raise ConnectionError("lost ack")
            return SimpleNamespace(updates=[types.UpdateMessageID(103, request.random_id)])
    transport = Transport(Client(), types.InputPeerChannel(1, 2))
    with pytest.raises(ConnectionError):
        await transport.send(delivery, 50)
    store.delivery_failed(delivery["id"], "ConnectionError", 0)
    assert await transport.send(store.pending_delivery(), 50) == 103
    assert all(isinstance(r, functions.messages.SendMediaRequest) for r in calls)
    assert calls[0].random_id == calls[1].random_id
    assert calls[1].reply_to.reply_to_msg_id == 101 and calls[1].reply_to.top_msg_id == 50
    assert uploads == [original, original]
    store.sent(delivery["id"], 103)
    assert store.pending_feedback()["desired"] == "cleared"


def test_mcp_file_deduplication_and_restart(setup, tmp_path):
    store, root = setup
    (root / "readme.txt").write_text("hello")
    first = store.send_file(str(root), "thread", "task", "readme.txt", event_key="one")
    second = store.send_file(str(root), "thread", "task", "readme.txt", event_key="one")
    assert second["duplicate"] and second["report_id"] == first["report_id"]
    assert store.db.execute("SELECT count(*) FROM attachments").fetchone()[0] == 1
    reopened = Store(tmp_path / "state.db")
    try:
        assert reopened.health()["pending_messages"] == 2
        reopened.sent(reopened.pending_delivery()["id"], 102)
        assert reopened.pending_delivery()["file_name"] == "readme.txt"
    finally:
        reopened.close()


def test_file_queue_rolls_back_atomically_on_attachment_failure(setup, monkeypatch):
    store, root = setup
    (root / "readme.txt").write_text("hello")
    def fail(*args, **kwargs):
        raise RuntimeError("storage failure")
    monkeypatch.setattr(store, "_attach", fail)
    with pytest.raises(RuntimeError):
        store.send_file(str(root), "thread", "task", "readme.txt")
    assert store.health()["pending_messages"] == 0
    assert store.db.execute("SELECT count(*) FROM reports").fetchone()[0] == 1


@pytest.mark.parametrize("name", ["../outside.txt", ".env", "secret.txt", "state.db", ".git/config", "keys/key.pem"])
def test_excluded_files_never_staged(setup, name):
    _, root = setup
    with pytest.raises((ValueError, OSError)):
        stage_file(root, name)


def test_links_size_and_text_redaction(setup, tmp_path, monkeypatch):
    from codex_telegram_reports import attachments
    _, root = setup
    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    (root / "link.txt").symlink_to(outside)
    os.link(outside, root / "hard.txt")
    (root / "parent").symlink_to(tmp_path, target_is_directory=True)
    for name in ["link.txt", "hard.txt", "parent/outside.txt", str(outside)]:
        with pytest.raises((OSError, ValueError)):
            stage_file(root, name)
    (root / "settings.txt").write_text("api_key=NEVER_SEND\nordinary = 42")
    item = stage_file(root, "settings.txt")
    assert item["sanitized"] and b"NEVER_SEND" not in attachment_path(item["digest"]).read_bytes()
    monkeypatch.setattr(attachments, "MAX_ATTACHMENT", 10)
    (root / "large.apk").write_bytes(b"a" * 11)
    with pytest.raises(ValueError, match="2000 MiB"):
        stage_file(root, "large.apk")


def test_large_build_is_staged_with_bounded_memory(setup):
    import tracemalloc
    _, root = setup
    with (root / "large.apk").open("wb") as stream:
        stream.truncate(64 * 1024 * 1024)
    tracemalloc.start()
    try:
        item = stage_file(root, "large.apk")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert item["size"] == 64 * 1024 * 1024
    assert peak < 8 * 1024 * 1024


@pytest.mark.asyncio
async def test_natural_file_request_and_no_unrequested_upload(setup):
    store, root = setup
    (root / "app.apk").write_bytes(b"PK\x00build")
    class Model:
        async def answer(self, context, text):
            return {"text": "Готовая сборка.", "files": ["app.apk"]}
    worker = Service(store, None, Model(), {"allowed_user_ids": [7]})
    ingest(store, "Пришли APK")
    await worker.answer_one()
    assert store.db.execute("SELECT count(*) FROM attachments").fetchone()[0] == 1
    ingest(store, "Что изменилось?", message=102)
    await worker.answer_one()
    assert store.db.execute("SELECT count(*) FROM attachments").fetchone()[0] == 1
    ingest(store, "/file app.apk", message=103, sender=8)
    assert store.pending_question() is None
    ingest(store, "Дай краткий ответ", message=104)
    await worker.answer_one()
    assert store.db.execute("SELECT count(*) FROM attachments").fetchone()[0] == 1


def test_artifact_listing_includes_ignored_build_without_reading_it(setup, tmp_path):
    _, root = setup
    (root / "build").mkdir()
    (root / "build/app.apk").write_bytes(b"PK\x00binary")
    (root / ".gitignore").write_text("build/\n")
    (root / ".env").write_text("never")
    metadata = build_snapshot(root, root, tmp_path / "snapshot")
    metadata["deliverables"] = list_deliverables(root)
    (tmp_path / "snapshot/manifest.json").write_text(json.dumps(metadata))
    reader = ProjectReader(tmp_path / "snapshot")
    assert reader.list_files("*.apk", deliverable=True)["files"] == ["build/app.apk"]
    assert ".env" not in reader.list_files(deliverable=True)["files"]
    with pytest.raises(ValueError):
        reader.read_file("build/app.apk")


def test_compact_preserves_outcome_checks_blockers_and_full_report(setup):
    store, root = setup
    original = "Добавлена отправка файлов.\n" + "Описание внутреннего устройства.\n" * 80 + "Тесты: 90 passed.\nОсталось проверить доставку.\nРиск: Mac должен работать."
    result = compact(original)
    assert len(result) < len(original)
    for line in ["Добавлена отправка файлов.", "Тесты: 90 passed.", "Осталось проверить доставку.", "Риск: Mac должен работать.", "/full"]:
        assert line in result
    r = store.report(str(root), "thread", "task", "Summary", "completed", original)
    store.sent(store.pending_delivery()["id"], 102)
    question = ingest(store, "/full", message=103, reply=102)
    assert store.full_text(question) == original
    store.answer(question, original, shorten=True)
    store.sent(store.pending_delivery()["id"], 104)
    assert store.full_text(ingest(store, "/full", message=105, reply=104)) == original


@pytest.mark.asyncio
async def test_separate_topics_keep_old_history_and_actual_checkout(setup, tmp_path):
    store, root = setup
    work = tmp_path / "clients"
    git(root, "worktree", "add", str(work))
    (work / "subdir").mkdir()
    old = store.register(str(root))
    assert store.register(str(work))["id"] == old["id"]
    integration = store.separate_topic(str(root), "Telega · integration")
    clients = store.separate_topic(str(work), "Telega · clients")
    assert integration["id"] == old["id"] and integration["topic_id"] == 50
    assert clients["id"] != old["id"]
    assert store.register(str(work / "subdir"))["id"] == clients["id"]
    report = store.report(str(work), "client-thread", "client-task", "Clients", "progress", "Client changes")
    assert report["project_id"] == clients["id"]
    store.bind_topic(clients["id"], 60)
    store.sent(store.pending_delivery()["id"], 110)
    q = ingest(store, "What changed?", message=111, reply=110, topic=60)
    context = store.context(q)
    assert context["_workspace"] == str(work)
    assert context["_project_root"] == str(root)
    build_snapshot(context["_workspace"], context["_project_root"], tmp_path / "snapshot")
    assert all(r["thread_id"] == "client-thread" for r in context["reports"])
    assert store.project(old["id"])["topic_id"] == 50
    calls = []
    async def client(request):
        calls.append(request)
        return True
    transport = Transport(client, types.InputPeerChannel(1, 2))
    assert await transport.ensure_topic(integration) == 50
    assert isinstance(calls[0], functions.messages.EditForumTopicRequest)
    assert calls[0].title == "Telega · integration"


def test_split_worktree_does_not_enable_disabled_repository(setup, tmp_path):
    store, root = setup
    work = tmp_path / "server"
    git(root, "worktree", "add", str(work))
    store.set_project_enabled(str(root), False)
    project = store.separate_topic(str(work), "Telega · server")
    assert not project["enabled"] and project["opted"] == 0
    assert not store.report(str(work), "t", "a", "No", "progress", "No")["queued"]
