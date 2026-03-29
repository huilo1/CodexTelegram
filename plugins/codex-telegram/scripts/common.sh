#!/usr/bin/env bash
set -euo pipefail

plugin_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
default_app_root="$(cd "$plugin_root/../.." && pwd)"
app_root="${CODEX_TELEGRAM_APP_ROOT:-$default_app_root}"

if [[ ! -f "$app_root/pyproject.toml" ]]; then
  echo "Invalid CODEX_TELEGRAM_APP_ROOT: $app_root" >&2
  echo "Expected a CodexTelegram project root with pyproject.toml" >&2
  exit 1
fi
