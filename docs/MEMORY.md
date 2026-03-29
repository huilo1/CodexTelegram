# Project Memory

## Goal

Implement a Codex analogue of `claude-code-telegram`: a Telegram bot that lets one approved Telegram chat drive local development through the `codex` CLI.

## What Was Implemented

- Python package `codex_telegram`
- Telegram polling bot using `python-telegram-bot`
- Persistent per-chat session store in `.codex-telegram/state.json`
- Codex integration through `codex exec --json`
- Session continuation through `codex exec resume`
- Safe directory changes constrained by `CODEX_ALLOWED_ROOT`
- Commands:
  - `/start`
  - `/help`
  - `/new`
  - `/status`
  - `/pwd`
  - `/cd <dir>`
  - `/cancel`
- Progress message updates from Codex JSON events
- Quiet Telegram UX: one acceptance message plus one loader GIF, then final result
- Timeout support via `CODEX_TIMEOUT_SECONDS`
- Cancellation support that terminates the running Codex subprocess
- Explicit warning reply for wrong `TELEGRAM_CHAT_ID`
- Runtime logging to `CODEX_LOG_FILE`
- Example `systemd` unit in `ops/codex-telegram.service.example`
- Repo-local Codex plugin in `plugins/codex-telegram`
- Bundled `systemd` user service template for persistent background running

## Important Design Decisions

- First version is intentionally a focused MVP, not a full clone of the Claude project.
- One approved Telegram chat is supported, controlled by `TELEGRAM_CHAT_ID`.
- Codex session continuity is tracked by stored `thread_id`.
- Changing working directory resets the stored `thread_id` because Codex sessions are workspace-bound.
- Approval prompts are not supported interactively through Telegram, so the implementation avoids flows that require them.

## Files To Know

- `src/codex_telegram/main.py`: CLI entrypoint
- `src/codex_telegram/bot.py`: Telegram handlers and runtime behavior
- `src/codex_telegram/codex_runner.py`: subprocess adapter for `codex exec` and `resume`
- `src/codex_telegram/config.py`: environment-driven settings
- `src/codex_telegram/session_store.py`: persisted chat state
- `src/codex_telegram/safety.py`: path restriction logic
- `README.md`: setup and operator instructions

## Validation Already Done

- `uv run --with pytest --with pytest-asyncio pytest -q`
- `python3 -m compileall src`
- Manual Codex runner verification:
  - first `codex exec`
  - second `codex exec resume`
  - confirmed same `thread_id` reused
- Telegram connectivity verification:
  - `getMe` succeeded
- polling bot started successfully
- Timeout and cancellation handler branches covered by tests in `tests/test_bot_runtime.py`

## Known Operational Facts

- Telegram bot only responds while the local process is running.
- Current operator mistake that already happened once: message was sent while the bot process was not running.
- Real secrets are stored only in local `.env`; do not duplicate them into docs.
- `workspace-write` sandbox blocks network for Codex shell commands in this setup. Networked Telegram tasks require `CODEX_SANDBOX=danger-full-access`.

## Next Logical Enhancements

- Add richer progress streaming instead of only replacing one progress message
- Add optional multi-chat or user allowlist support
- Add export/import or pinned startup prompt for better Telegram-side continuity
