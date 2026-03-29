#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

stopped_any=0

if tracked_pid="$(get_tracked_bot_pid)"; then
  kill "$tracked_pid" >/dev/null 2>&1 || true
  stopped_any=1
else
  rm -f "$pid_file"
fi

mapfile -t stray_pids < <(pgrep -f "$process_pattern" || true)
if [[ "${#stray_pids[@]}" -gt 0 ]]; then
  kill "${stray_pids[@]}" >/dev/null 2>&1 || true
  stopped_any=1
fi

for _ in {1..10}; do
  mapfile -t remaining_pids < <(pgrep -f "$process_pattern" || true)
  if [[ "${#remaining_pids[@]}" -eq 0 ]]; then
    rm -f "$pid_file"
    if [[ "$stopped_any" -eq 1 ]]; then
      echo "Stopped Codex Telegram bot."
    else
      echo "Codex Telegram bot is not running."
    fi
    exit 0
  fi
  sleep 1
done

mapfile -t remaining_pids < <(pgrep -f "$process_pattern" || true)
if [[ "${#remaining_pids[@]}" -gt 0 ]]; then
  kill -9 "${remaining_pids[@]}" >/dev/null 2>&1 || true
fi
rm -f "$pid_file"
if [[ "$stopped_any" -eq 1 ]]; then
  echo "Stopped Codex Telegram bot."
else
  echo "Codex Telegram bot is not running."
fi
