#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
cd "$app_root"

uv venv
uv pip install -e '.[dev]'

echo "Installed CodexTelegram dependencies in $app_root/.venv"
