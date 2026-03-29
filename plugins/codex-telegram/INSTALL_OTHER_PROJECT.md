# Use In Another Project

This plugin can be connected to another repository without copying the full Telegram bot runtime into that repository.

## Option A: Reuse The Existing CodexTelegram Runtime

Recommended when you already keep the runtime in one central repo.

### 1. Copy the plugin folder into the target project

Copy:

- `plugins/codex-telegram`

into the target repository at:

- `<target-repo>/plugins/codex-telegram`

### 2. Add a marketplace entry in the target project

Create or update:

- `<target-repo>/.agents/plugins/marketplace.json`

with:

```json
{
  "name": "local-dev",
  "interface": {
    "displayName": "Local Dev Plugins"
  },
  "plugins": [
    {
      "name": "codex-telegram",
      "source": {
        "source": "local",
        "path": "./plugins/codex-telegram"
      },
      "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL"
      },
      "category": "Productivity"
    }
  ]
}
```

### 3. Point the plugin at the real runtime repo

Before using the helper scripts, export:

```bash
export CODEX_TELEGRAM_APP_ROOT=/absolute/path/to/CodexTelegram
```

That path must contain:

- `pyproject.toml`
- `.env`
- `src/codex_telegram`

### 4. Run the helper scripts from the target project

```bash
./plugins/codex-telegram/scripts/install.sh
./plugins/codex-telegram/scripts/start.sh
./plugins/codex-telegram/scripts/status.sh
```

## Option B: Vendor The Full Runtime Into The Target Project

If you want the target repo to be fully self-contained:

1. Copy the whole `CodexTelegram` runtime into that target repo.
2. Keep the plugin at `./plugins/codex-telegram`.
3. Do not set `CODEX_TELEGRAM_APP_ROOT`; the helper scripts will use the local repo root by default.

## Notes

- The target project still needs a valid `.env` for the Telegram bot runtime.
- For networked tasks, use `CODEX_SANDBOX=danger-full-access`.
- If the Telegram thread needs a fresh Codex context, use `/new`.
