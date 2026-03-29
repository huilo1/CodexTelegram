#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

if ! pgrep -af 'codex-telegram-bot|python.*codex_telegram' >/dev/null 2>&1; then
  echo "Codex Telegram bot is not running."
  exit 0
fi

pkill -f 'codex-telegram-bot|python.*codex_telegram'
echo "Stopped Codex Telegram bot."
