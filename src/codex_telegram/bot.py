from __future__ import annotations

import asyncio
import contextlib
import html
import logging
import time
from pathlib import Path

from telegram import Message, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .codex_runner import CodexRunner
from .config import Settings
from .safety import resolve_within_root
from .session_store import SessionStore

LOGGER = logging.getLogger(__name__)


class CodexTelegramBot:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store = SessionStore(settings.store_path)
        self.runner = CodexRunner(settings)
        self._active_chats: set[int] = set()
        self._active_tasks: dict[int, asyncio.Task] = {}

    async def start(self) -> None:
        application = (
            Application.builder()
            .token(self.settings.telegram_bot_token)
            .concurrent_updates(True)
            .build()
        )
        application.bot_data["service"] = self
        application.add_handler(CommandHandler("start", self.handle_start))
        application.add_handler(CommandHandler("help", self.handle_help))
        application.add_handler(CommandHandler("new", self.handle_new))
        application.add_handler(CommandHandler("status", self.handle_status))
        application.add_handler(CommandHandler("pwd", self.handle_pwd))
        application.add_handler(CommandHandler("cd", self.handle_cd))
        application.add_handler(CommandHandler("cancel", self.handle_cancel))
        application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )
        await application.initialize()
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        LOGGER.info("Bot started")
        try:
            await asyncio.Event().wait()
        finally:
            await application.updater.stop()
            await application.stop()
            await application.shutdown()

    async def handle_start(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        if not await self._ensure_allowed(update):
            return
        session = self.store.load(update.effective_chat.id, self.settings.codex_default_cwd)
        text = (
            "Codex Telegram is ready.\n\n"
            f"Current directory: <code>{html.escape(session.cwd)}</code>\n"
            "Commands: /new, /status, /pwd, /cd &lt;dir&gt;"
        )
        await update.effective_message.reply_html(text)

    async def handle_help(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        if not await self._ensure_allowed(update):
            return
        await update.effective_message.reply_text(
            "Send a plain text task and I will forward it to Codex.\n"
            "/new resets the persisted Codex thread.\n"
            "/status shows the current thread and directory.\n"
            "/cd <dir> moves within CODEX_ALLOWED_ROOT.\n"
            "/cancel stops the current Codex task.\n"
            "/pwd prints the current directory."
        )

    async def handle_new(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        if not await self._ensure_allowed(update):
            return
        session = self.store.reset(
            update.effective_chat.id,
            self.settings.codex_default_cwd,
        )
        await update.effective_message.reply_html(
            "Started a new Codex thread.\n"
            f"Current directory: <code>{html.escape(session.cwd)}</code>"
        )

    async def handle_status(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        if not await self._ensure_allowed(update):
            return
        session = self.store.load(update.effective_chat.id, self.settings.codex_default_cwd)
        busy = "yes" if update.effective_chat.id in self._active_chats else "no"
        await update.effective_message.reply_html(
            f"Chat: <code>{update.effective_chat.id}</code>\n"
            f"CWD: <code>{html.escape(session.cwd)}</code>\n"
            f"Thread: <code>{html.escape(session.thread_id or 'none')}</code>\n"
            f"Busy: <code>{busy}</code>"
        )

    async def handle_pwd(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        if not await self._ensure_allowed(update):
            return
        session = self.store.load(update.effective_chat.id, self.settings.codex_default_cwd)
        await update.effective_message.reply_html(
            f"<code>{html.escape(session.cwd)}</code>"
        )

    async def handle_cd(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        if not await self._ensure_allowed(update):
            return
        args = context.args or []
        if not args:
            await update.effective_message.reply_text("Usage: /cd <directory>")
            return
        session = self.store.load(update.effective_chat.id, self.settings.codex_default_cwd)
        try:
            target = resolve_within_root(
                self.settings.codex_allowed_root,
                Path(session.cwd),
                " ".join(args),
            )
        except ValueError as error:
            await update.effective_message.reply_text(str(error))
            return
        session.cwd = str(target)
        session.thread_id = None
        self.store.save(session)
        await update.effective_message.reply_html(
            "Working directory updated.\n"
            f"<code>{html.escape(session.cwd)}</code>\n"
            "Thread reset because Codex sessions are tied to the workspace."
        )

    async def handle_cancel(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        if not await self._ensure_allowed(update):
            return
        chat_id = update.effective_chat.id
        task = self._active_tasks.get(chat_id)
        if task is None or task.done():
            await update.effective_message.reply_text("No running Codex task for this chat.")
            return
        task.cancel()
        await update.effective_message.reply_text("Cancellation requested. Waiting for Codex to stop.")

    async def handle_message(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        if not await self._ensure_allowed(update):
            return
        message = update.effective_message
        chat_id = update.effective_chat.id
        if chat_id in self._active_chats:
            await message.reply_text(
                "Another task is still running for this chat. Use /cancel if it is stuck."
            )
            return
        prompt = (message.text or "").strip()
        if not prompt:
            return

        self._active_chats.add(chat_id)
        session = self.store.load(chat_id, self.settings.codex_default_cwd)
        accepted_message = await message.reply_text(
            "Task accepted. Working on it now."
        )
        loader_message = await self._send_loader(message)
        current_task = asyncio.current_task()
        if current_task is not None:
            self._active_tasks[chat_id] = current_task
        last_typing_at = 0.0

        async def on_progress(text: str) -> None:
            nonlocal last_typing_at
            now = time.monotonic()
            if now - last_typing_at < 4:
                return
            last_typing_at = now
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

        try:
            result = await asyncio.wait_for(
                self.runner.run(session, prompt, on_progress=on_progress),
                timeout=self.settings.codex_timeout_seconds,
            )
            session.thread_id = result.thread_id
            session.last_prompt = prompt
            self.store.save(session)
            await self._finish_loader(accepted_message, loader_message, "Task completed.")
            await self._send_long_message(message, result.final_text)
        except asyncio.TimeoutError:
            LOGGER.exception("Codex request timed out")
            await self._finish_loader(
                accepted_message,
                loader_message,
                "Task timed out.",
            )
            await message.reply_text(
                f"Codex timed out after {self.settings.codex_timeout_seconds} seconds."
            )
        except asyncio.CancelledError:
            LOGGER.warning("Codex request cancelled")
            await self._finish_loader(
                accepted_message,
                loader_message,
                "Task cancelled.",
            )
            await message.reply_text("Codex task cancelled.")
        except Exception as error:
            LOGGER.exception("Codex request failed")
            await self._finish_loader(
                accepted_message,
                loader_message,
                "Task failed.",
            )
            await message.reply_text(f"Codex request failed: {error}")
        finally:
            self._active_chats.discard(chat_id)
            self._active_tasks.pop(chat_id, None)

    async def _send_loader(self, message: Message) -> Message | None:
        with contextlib.suppress(Exception):
            return await message.reply_animation(
                animation=self.settings.codex_loader_gif_url,
            )
        LOGGER.debug("Failed to send loader animation", exc_info=True)
        return None

    async def _finish_loader(
        self,
        accepted_message: Message,
        loader_message: Message | None,
        status_text: str,
    ) -> None:
        with contextlib.suppress(Exception):
            await accepted_message.edit_text(status_text)
        if loader_message is not None:
            with contextlib.suppress(Exception):
                await loader_message.delete()

    async def _send_long_message(self, message, text: str) -> None:
        chunks = _split_message(text)
        for chunk in chunks:
            await message.reply_text(chunk, parse_mode=None)

    async def _ensure_allowed(self, update: Update) -> bool:
        chat = update.effective_chat
        if chat is None or chat.id != self.settings.telegram_chat_id:
            LOGGER.warning("Rejected update from chat %s", getattr(chat, "id", None))
            if update.effective_message is not None:
                with contextlib.suppress(Exception):
                    await update.effective_message.reply_text(
                        "This bot is locked to a different Telegram chat. "
                        "Check TELEGRAM_CHAT_ID in the bot configuration."
                    )
            return False
        return True


def _split_message(text: str, limit: int = 4000) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = text
    while len(current) > limit:
        split_at = current.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = limit
        chunks.append(current[:split_at].strip())
        current = current[split_at:].strip()
    if current:
        chunks.append(current)
    return chunks
