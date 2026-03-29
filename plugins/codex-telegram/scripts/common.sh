#!/usr/bin/env bash
set -euo pipefail

plugin_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
default_app_root="$(cd "$plugin_root/../.." && pwd)"
app_root="${CODEX_TELEGRAM_APP_ROOT:-$default_app_root}"
runtime_dir="$app_root/.codex-telegram"
pid_file="$runtime_dir/bot.pid"
launcher_log="$runtime_dir/launcher.log"
process_pattern='codex-telegram-bot( |$)'

if [[ ! -f "$app_root/pyproject.toml" || ! -d "$app_root/src/codex_telegram" ]]; then
  echo "Invalid CODEX_TELEGRAM_APP_ROOT: $app_root" >&2
  echo "Expected a CodexTelegram project root with pyproject.toml and src/codex_telegram" >&2
  exit 1
fi

mkdir -p "$runtime_dir"
