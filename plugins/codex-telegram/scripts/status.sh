#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
cd "$app_root"

echo "Processes:"
pgrep -af 'codex-telegram-bot|python.*codex_telegram' || true

echo
echo "Recent log:"
tail -n 20 .codex-telegram/bot.log 2>/dev/null || echo "No bot log yet."
