from pathlib import Path

from codex_telegram.codex_runner import CodexRunner
from codex_telegram.config import Settings
from codex_telegram.session_store import ChatSession


def build_settings(tmp_path: Path, enable_web_search: bool = False) -> Settings:
    return Settings(
        TELEGRAM_BOT_TOKEN="test-token",
        TELEGRAM_CHAT_ID=1,
        CODEX_ALLOWED_ROOT=tmp_path,
        CODEX_DEFAULT_CWD=tmp_path,
        CODEX_STORE_PATH=tmp_path / "state.json",
        CODEX_ENABLE_WEB_SEARCH=enable_web_search,
    )


def test_build_command_places_global_search_flag_before_exec(tmp_path: Path) -> None:
    runner = CodexRunner(build_settings(tmp_path, enable_web_search=True))
    session = ChatSession(chat_id=1, cwd=str(tmp_path), thread_id=None)

    command = runner._build_command(session)

    assert command[:3] == ["codex", "--search", "exec"]
    assert "--json" in command
    assert "--cd" in command


def test_build_command_resume_keeps_search_flag_before_exec(tmp_path: Path) -> None:
    runner = CodexRunner(build_settings(tmp_path, enable_web_search=True))
    session = ChatSession(chat_id=1, cwd=str(tmp_path), thread_id="thread-123")

    command = runner._build_command(session)

    assert command[:3] == ["codex", "--search", "exec"]
    assert command[3] == "resume"
    assert "thread-123" in command
