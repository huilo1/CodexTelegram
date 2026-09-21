#!/usr/bin/env python3
"""Stable launcher used from a Codex plugin cache; never assumes a repository cwd."""
import os
from pathlib import Path
import sys

home = Path(os.environ.get("CODEX_TELEGRAM_REPORTS_HOME", "~/.codex-telegram-reports")).expanduser()
python = home / "venv" / "bin" / "python"
if not python.exists():
    if sys.argv[1:] == ["hook"]:
        print("{}")
        sys.exit(0)
    sys.exit(f"Install the report runtime first: python3 {Path(__file__).with_name('install.py')}")
os.execv(str(python), [str(python), "-I", "-m", "codex_telegram_reports.cli", *sys.argv[1:]])
