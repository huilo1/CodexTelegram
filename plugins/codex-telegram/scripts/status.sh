#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
cd "$app_root"

echo "Processes:"
if tracked_pid="$(get_tracked_bot_pid)"; then
  ps -fp "$tracked_pid"
else
  rm -f "$pid_file"
  mapfile -t all_pids < <(pgrep -af "$process_pattern" || true)
  if [[ "${#all_pids[@]}" -gt 0 ]]; then
    echo "Tracked PID missing, but found running bot process:"
    printf '%s\n' "${all_pids[@]}"
  else
    echo "Not running."
  fi
fi

echo
echo "Launcher log:"
tail -n 20 "$launcher_log" 2>/dev/null || echo "No launcher log yet."

echo
echo "Recent log:"
tail -n 20 .codex-telegram/bot.log 2>/dev/null || echo "No bot log yet."
