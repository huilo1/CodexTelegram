---
name: codex-telegram
description: Operate and maintain the repo-local Telegram bridge for the Codex CLI. Use when setting up the bot, starting/stopping it, checking logs, or explaining how the Telegram workflow works.
---

# Codex Telegram

This plugin wraps the `CodexTelegram` repository itself by default, but it can also be reused from another project if `CODEX_TELEGRAM_APP_ROOT` points to the real app root.

## When To Use

- The user wants to install or run the Telegram bridge
- The user wants to inspect bot logs or process state
- The user wants to reconfigure Telegram token, chat ID, sandbox, or loader GIF
- The user wants to understand the Telegram-to-Codex architecture

## Important Paths

- Default project root: `../../..`
- Config file: `$CODEX_TELEGRAM_APP_ROOT/.env` or `../../../.env`
- Main docs: `$CODEX_TELEGRAM_APP_ROOT/README.md`
- Memory: `$CODEX_TELEGRAM_APP_ROOT/docs/MEMORY.md`
- Telegram handoff: `$CODEX_TELEGRAM_APP_ROOT/docs/TELEGRAM_HANDOFF.md`
- Log file default: `$CODEX_TELEGRAM_APP_ROOT/.codex-telegram/bot.log`

## Common Commands

Run from project root unless noted otherwise.

If the plugin was copied into another repository, first export:

```bash
export CODEX_TELEGRAM_APP_ROOT=/absolute/path/to/CodexTelegram
```

### Install dependencies

```bash
./plugins/codex-telegram/scripts/install.sh
```

### Start bot

```bash
./plugins/codex-telegram/scripts/start.sh
```

### Stop bot

```bash
./plugins/codex-telegram/scripts/stop.sh
```

### Status

```bash
./plugins/codex-telegram/scripts/status.sh
```

## Operator Notes

- The Telegram bot only works while the local process is running.
- For networked tasks, `CODEX_SANDBOX` should be `danger-full-access`.
- If Telegram and the main Codex chat need shared context, bootstrap from:
  - `docs/MEMORY.md`
  - `docs/TELEGRAM_HANDOFF.md`
- If the current Telegram session is confused, use `/new`.
- If a task is stuck, use `/cancel`.

## Recommended First Step

When asked to operate this plugin:

1. Read `../../../docs/MEMORY.md`.
2. Read `../../../docs/TELEGRAM_HANDOFF.md`.
3. Confirm whether the bot process is already running with `./plugins/codex-telegram/scripts/status.sh`.
