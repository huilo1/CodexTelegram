from pathlib import Path

from codex_telegram.session_store import SessionStore


def test_session_store_roundtrip(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "state.json")
    session = store.load(1, tmp_path)
    session.thread_id = "thread-123"
    store.save(session)

    restored = store.load(1, tmp_path)
    assert restored.thread_id == "thread-123"
    assert restored.cwd == str(tmp_path)
