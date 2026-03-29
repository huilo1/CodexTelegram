# Codex Telegram Plugin

Repo-local Codex plugin wrapping the `CodexTelegram` project in this repository.

## What It Provides

- Metadata for local plugin discovery
- A skill with setup and operating instructions
- Helper scripts to install dependencies and run the Telegram bot

## Plugin Root

This plugin lives at:

- `plugins/codex-telegram`

It operates on the main project root two directories above the plugin folder.

If you copy this plugin into another project, point it at the real app root with:

```bash
export CODEX_TELEGRAM_APP_ROOT=/absolute/path/to/CodexTelegram
```

## Main Project

The actual bot implementation lives in:

- `src/codex_telegram`

Operator docs and project memory live in:

- `README.md`
- `docs/MEMORY.md`
- `docs/TELEGRAM_HANDOFF.md`

## Helper Scripts

- `scripts/install.sh`
- `scripts/start.sh`
- `scripts/stop.sh`
- `scripts/status.sh`
- `scripts/common.sh`

## Reusing In Another Project

You can reuse this plugin in another repository by copying `plugins/codex-telegram` and then setting `CODEX_TELEGRAM_APP_ROOT` to the actual `CodexTelegram` runtime repository before running the helper scripts.
