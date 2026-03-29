import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_telegram.bot import CodexTelegramBot
from codex_telegram.codex_runner import CodexRunResult
from codex_telegram.config import Settings


class FakeProgressMessage:
    def __init__(self) -> None:
        self.edits: list[str] = []
        self.deleted = False

    async def edit_text(self, text: str, parse_mode=None) -> None:
        self.edits.append(text)

    async def delete(self) -> None:
        self.deleted = True


class FakeMessage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.replies: list[str] = []
        self.text_messages: list[FakeProgressMessage] = []
        self.animation_messages: list[FakeProgressMessage] = []

    async def reply_text(self, text: str, parse_mode=None):
        self.replies.append(text)
        progress = FakeProgressMessage()
        self.text_messages.append(progress)
        return progress

    async def reply_animation(self, animation: str):
        progress = FakeProgressMessage()
        self.animation_messages.append(progress)
        return progress

    async def reply_html(self, text: str) -> None:
        self.replies.append(text)


class FakeBotApi:
    def __init__(self) -> None:
        self.chat_actions: list[tuple[int, object]] = []

    async def send_chat_action(self, chat_id: int, action) -> None:
        self.chat_actions.append((chat_id, action))


def build_settings(tmp_path: Path, timeout_seconds: int = 1) -> Settings:
    return Settings(
        TELEGRAM_BOT_TOKEN="test-token",
        TELEGRAM_CHAT_ID=1,
        CODEX_ALLOWED_ROOT=tmp_path,
        CODEX_DEFAULT_CWD=tmp_path,
        CODEX_STORE_PATH=tmp_path / "state.json",
        CODEX_TIMEOUT_SECONDS=timeout_seconds,
    )


def build_update(message: FakeMessage):
    chat = SimpleNamespace(id=1)
    return SimpleNamespace(
        effective_chat=chat,
        effective_message=message,
    )


def build_context():
    return SimpleNamespace(args=[], bot=FakeBotApi())


@pytest.mark.asyncio
async def test_handle_message_reports_timeout(tmp_path: Path) -> None:
    bot = CodexTelegramBot(build_settings(tmp_path, timeout_seconds=0))
    message = FakeMessage("do something slow")
    update = build_update(message)
    context = build_context()

    async def slow_run(session, prompt, on_progress=None):
        await asyncio.sleep(0.01)
        return CodexRunResult(thread_id="thread-timeout", messages=["late reply"])

    bot.runner.run = slow_run

    await bot.handle_message(update, context)

    assert message.replies[0] == "Task accepted. Working on it now."
    assert message.text_messages[0].edits[-1] == "Task timed out."
    assert message.animation_messages[0].deleted is True
    assert f"Codex timed out after {bot.settings.codex_timeout_seconds} seconds." in message.replies
    saved_session = bot.store.load(1, tmp_path)
    assert saved_session.thread_id is None


@pytest.mark.asyncio
async def test_handle_cancel_stops_running_task(tmp_path: Path) -> None:
    bot = CodexTelegramBot(build_settings(tmp_path, timeout_seconds=30))
    message = FakeMessage("run until cancelled")
    update = build_update(message)
    context = build_context()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def cancellable_run(session, prompt, on_progress=None):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    bot.runner.run = cancellable_run

    task = asyncio.create_task(bot.handle_message(update, context))
    await started.wait()

    cancel_message = FakeMessage("/cancel")
    cancel_update = build_update(cancel_message)
    await bot.handle_cancel(cancel_update, context)
    await task

    assert cancelled.is_set()
    assert "Cancellation requested. Waiting for Codex to stop." in cancel_message.replies
    assert message.text_messages[0].edits[-1] == "Task cancelled."
    assert message.animation_messages[0].deleted is True
    assert "Codex task cancelled." in message.replies
    assert 1 not in bot._active_chats
    assert 1 not in bot._active_tasks
