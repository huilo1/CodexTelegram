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

is_bot_pid() {
  local pid="${1:-}"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" >/dev/null 2>&1 || return 1

  local args
  args="$(ps -p "$pid" -o args= 2>/dev/null || true)"
  [[ -n "$args" ]] || return 1
  [[ "$args" =~ $process_pattern ]]
}

read_pid_file() {
  [[ -f "$pid_file" ]] || return 1

  local pid
  pid="$(<"$pid_file")"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  printf '%s\n' "$pid"
}

get_tracked_bot_pid() {
  local pid
  pid="$(read_pid_file 2>/dev/null || true)"
  if [[ -n "$pid" ]] && is_bot_pid "$pid"; then
    printf '%s\n' "$pid"
    return 0
  fi
  return 1
}
