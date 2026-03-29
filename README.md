# Codex Telegram Bot

Telegram bot that gives one approved chat remote access to the local `codex` CLI. It is modeled after `claude-code-telegram`, but built around `codex exec` and persisted Codex thread IDs.

## What This Project Ships

- Standalone Telegram bot runtime in `src/codex_telegram`
- Repo-local Codex plugin in `plugins/codex-telegram`
- Helper scripts for install/start/stop/status
- `systemd` example service for persistent background operation

## Scope of this implementation

- Plain-text Telegram chat interface for Codex
- Persistent `thread_id` per chat using `codex exec resume`
- Safe directory switching inside a single approved root
- One acceptance message plus GIF loader while the task runs
- Minimal command surface for manual operation: `/start`, `/help`, `/new`, `/status`, `/pwd`, `/cd`, `/cancel`

## Requirements

- Python 3.11+
- `codex` CLI installed and already authenticated
- Telegram bot token from `@BotFather`
- Target Telegram `chat_id`

## Setup

```bash
cp .env.example .env
```

Create a Telegram bot token with `@BotFather`:

1. Open Telegram and start a chat with `@BotFather`
2. Run `/newbot`
3. Choose a bot name
4. Choose a unique bot username ending in `bot`
5. Copy the token returned by BotFather
6. Put that value into `TELEGRAM_BOT_TOKEN` inside `.env`

To find your private `chat_id`, send any message to the bot after it starts, then inspect the latest update with:

```bash
curl "https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates"
```

Use the numeric `message.chat.id` value as `TELEGRAM_CHAT_ID`.

Fill at least:

```bash
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
CODEX_ALLOWED_ROOT=/absolute/path/to/workspace
CODEX_DEFAULT_CWD=/absolute/path/to/workspace
```

Install and run:

```bash
uv venv
source .venv/bin/activate
uv pip install -e '.[dev]'
codex-telegram-bot
```

Or run without activation:

```bash
uv run codex-telegram-bot
```

For a persistent background service, use [ops/codex-telegram.service.example](/home/angel/projects/CodexTelegram/ops/codex-telegram.service.example) as a `systemd` template.

## Plugin Usage

This repository already includes a local Codex plugin wrapper:

- [plugins/codex-telegram](/home/angel/projects/CodexTelegram/plugins/codex-telegram)

Plugin metadata lives in:

- [plugin.json](/home/angel/projects/CodexTelegram/plugins/codex-telegram/.codex-plugin/plugin.json)
- [marketplace.json](/home/angel/projects/CodexTelegram/.agents/plugins/marketplace.json)

The plugin includes helper scripts:

```bash
./plugins/codex-telegram/scripts/install.sh
./plugins/codex-telegram/scripts/start.sh
./plugins/codex-telegram/scripts/status.sh
./plugins/codex-telegram/scripts/stop.sh
```

If you want to use this plugin from another repository, see:

- [plugins/codex-telegram/INSTALL_OTHER_PROJECT.md](/home/angel/projects/CodexTelegram/plugins/codex-telegram/INSTALL_OTHER_PROJECT.md)

## Run as a user service

For persistent operation, install the provided `systemd` user unit:

```bash
mkdir -p ~/.config/systemd/user
cp ops/codex-telegram.service.example ~/.config/systemd/user/codex-telegram.service
systemctl --user daemon-reload
systemctl --user enable --now codex-telegram.service
```

Useful commands:

```bash
systemctl --user status codex-telegram.service
journalctl --user -u codex-telegram.service -f
systemctl --user restart codex-telegram.service
```

If the bot must survive reboots even before you log in interactively, enable lingering once:

```bash
loginctl enable-linger "$USER"
```

The bundled unit assumes the repository lives at `~/projects/CodexTelegram` and uses `.venv/bin/codex-telegram-bot` with `--env-file .env`. Adjust `WorkingDirectory` and `ExecStart` if your checkout lives elsewhere.

## Publish Checklist

Before pushing this repository publicly:

- rotate the Telegram bot token because it was shared in chat during setup
- confirm `.env` is ignored and not committed
- replace placeholder author URLs or metadata if needed
- verify the plugin README and `INSTALL_OTHER_PROJECT.md` match the intended public usage model

## Notes

- `/cd <dir>` resets the saved Codex thread because a Codex session is tied to its working directory.
- `/cancel` stops the current Codex task for the configured chat.
- The bot rejects messages from chats other than `TELEGRAM_CHAT_ID`.
- If `TELEGRAM_CHAT_ID` is wrong, the bot now replies with an explicit configuration warning instead of failing silently.
- `CODEX_ENABLE_WEB_SEARCH=true` enables live web search for Codex if your local CLI/config supports it.
- `CODEX_SANDBOX=workspace-write` blocks network for shell commands; if Telegram tasks need downloads, HTTP requests, package installs, or git over network, use `CODEX_SANDBOX=danger-full-access` and start a new bot session.
- The default loader GIF is `https://media.giphy.com/media/pY8jLmZw0ElqvVeRH4/giphy.gif`. Replace it with `CODEX_LOADER_GIF_URL` if needed.
- Runtime logs are written both to stdout and `CODEX_LOG_FILE`.
- Project memory for future Telegram sessions is stored in `docs/MEMORY.md` and `docs/TELEGRAM_HANDOFF.md`.
- Repo-local plugin packaging now lives in `plugins/codex-telegram` with marketplace entry in `.agents/plugins/marketplace.json`.
