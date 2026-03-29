#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
cd "$app_root"

echo "Processes:"
if tracked_pid="$(get_tracked_bot_pid)"; then
  ps -fp "$tracked_pid"
else
  rm -f "$pid_file"
  echo "Not running."
fi

mapfile -t all_pids < <(pgrep -af "$process_pattern" || true)
if [[ "${#all_pids[@]}" -gt 1 ]]; then
  echo
  echo "Duplicate local bot processes detected:"
  printf '%s\n' "${all_pids[@]}"
fi

echo
echo "Launcher log:"
tail -n 20 "$launcher_log" 2>/dev/null || echo "No launcher log yet."

echo
echo "Recent log:"
tail -n 20 .codex-telegram/bot.log 2>/dev/null || echo "No bot log yet."
