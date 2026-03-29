#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
cd "$app_root"

mapfile -t existing_pids < <(pgrep -f "$process_pattern" || true)
if tracked_pid="$(get_tracked_bot_pid)"; then
  echo "Codex Telegram bot is already running."
  exit 0
fi
if [[ "${#existing_pids[@]}" -gt 0 ]]; then
  echo "Found existing Codex Telegram process(es): ${existing_pids[*]}"
  echo "Use ./plugins/codex-telegram/scripts/stop.sh first if you want a clean restart."
  exit 0
fi

if command -v setsid >/dev/null 2>&1; then
  setsid "$app_root/.venv/bin/codex-telegram-bot" --env-file "$app_root/.env" \
    </dev/null >>"$launcher_log" 2>&1 &
else
  nohup "$app_root/.venv/bin/codex-telegram-bot" --env-file "$app_root/.env" \
    </dev/null >>"$launcher_log" 2>&1 &
fi
pid=$!
echo "$pid" > "$pid_file"
sleep 2

if ! is_bot_pid "$pid"; then
  echo "Codex Telegram bot failed to stay running." >&2
  rm -f "$pid_file"
  echo >&2
  echo "Launcher log:" >&2
  tail -n 20 "$launcher_log" >&2 || true
  echo >&2
  echo "Bot log:" >&2
  tail -n 20 "$runtime_dir/bot.log" >&2 || true
  exit 1
fi

echo "Started Codex Telegram bot."
"$plugin_root/scripts/status.sh"
