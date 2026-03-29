#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
cd "$app_root"

if pgrep -af 'codex-telegram-bot|python.*codex_telegram' >/dev/null 2>&1; then
  echo "Codex Telegram bot is already running."
  exit 0
fi

nohup "$app_root/.venv/bin/codex-telegram-bot" > /dev/null 2>&1 &
sleep 1

echo "Started Codex Telegram bot."
"$plugin_root/scripts/status.sh"
