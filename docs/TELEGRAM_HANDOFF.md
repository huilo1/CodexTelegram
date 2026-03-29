# Telegram Handoff

Use this file when starting work from Telegram and the bot lacks the context from the main Codex conversation.

## Project Intent

This repository contains a Telegram bridge for the local `codex` CLI. It should behave like a lightweight Codex-oriented version of `claude-code-telegram`.

## Current State

- Bot is implemented and starts successfully.
- It supports one approved private Telegram chat.
- It persists the Codex `thread_id` between messages.
- It can reset thread state with `/new`.
- It can switch directories within the approved root using `/cd`.
- It can cancel long-running tasks with `/cancel`.
- While a task runs, it should now show a single acceptance message and a loader GIF instead of noisy progress edits.
- There is now a repo-local plugin wrapper in `plugins/codex-telegram` with helper scripts for install/start/stop/status.
- A `systemd` user unit template is available in `deploy/systemd/codex-telegram.service`.

## Operator Model

- Telegram and the original Codex chat do not share context automatically.
- The Telegram bot only continues the Codex thread it created itself.
- If a task depends on decisions made in the main Codex chat, restate them explicitly in Telegram or refer to this file and `docs/MEMORY.md`.

## Working Conventions

- Keep work inside `CODEX_ALLOWED_ROOT`.
- Prefer minimal, testable edits.
- After code changes, run relevant verification where possible.
- If changing directories with `/cd`, remember that the Codex thread is reset by design.

## Recommended Bootstrap Prompt For Telegram

When starting a new Telegram session, send a message like:

`Read docs/MEMORY.md and docs/TELEGRAM_HANDOFF.md, summarize current architecture, then wait for the next task.`

## If Something Looks Broken

- Check whether the local bot process is running.
- If using `systemd`, check `systemctl --user status codex-telegram.service` and `journalctl --user -u codex-telegram.service -f`.
- Check whether `TELEGRAM_CHAT_ID` matches the actual private chat.
- Check `.codex-telegram/state.json` for current saved `cwd` and `thread_id`.
- If a task is stuck, use `/cancel`.
- If session continuity is wrong, use `/new`.
- If the task needs network access and Codex says the sandbox has no network, switch the bot config to `CODEX_SANDBOX=danger-full-access` and reset the saved thread.
