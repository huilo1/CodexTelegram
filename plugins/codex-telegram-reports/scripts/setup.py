#!/usr/bin/env python3
"""Install/update from a reviewed Git checkout, then configure the user's own accounts."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from install import ROOT, home_path, install, runtime


def preflight():
    if sys.platform != "darwin" or sys.version_info < (3, 11):
        raise RuntimeError("Для беты нужны macOS и Python 3.11+.")
    codex = shutil.which("codex")
    if not codex:
        raise RuntimeError("Установите Codex CLI и выполните codex login.")
    result = subprocess.run([codex, "--version"], capture_output=True, text=True, check=True, timeout=10)
    match = re.search(r"\b(\d+)\.(\d+)\.(\d+)\b", result.stdout)
    if not match or tuple(map(int, match.groups())) < (0, 155, 1):
        raise RuntimeError("Нужен Codex CLI 0.155.1 или новее; бета проверена с 0.155.1.")
    result = subprocess.run([codex, "login", "status"], capture_output=True, timeout=10)
    if result.returncode:
        raise RuntimeError("Выполните codex login, затем запустите мастер повторно.")
    subprocess.run([codex, "plugin", "add", "--help"], check=True, capture_output=True, timeout=10)
    return codex


def installation_marketplace(inventory, default):
    if not isinstance(inventory, dict) or not isinstance(inventory.get("installed"), list):
        raise RuntimeError("Неизвестный формат codex plugin list; обновите плагин для этой версии Codex.")
    matches = [entry for entry in inventory["installed"] if entry.get("name") == "codex-telegram-reports"]
    if len(matches) > 1:
        raise RuntimeError("Установлено несколько копий reports. Оставьте одну через codex plugin remove.")
    if not matches:
        return default
    entry = matches[0]
    source = entry.get("source", {})
    if source.get("source") != "local" or Path(source.get("path", "")).resolve() != ROOT.resolve():
        raise RuntimeError("Плагин установлен из другого источника. Обновляйте из его checkout или удалите старую копию через codex plugin remove; данные сохранятся.")
    name = entry.get("marketplaceName", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise RuntimeError("Invalid installed marketplace name.")
    return name


def existing_hook_launchers(marketplace):
    """Keep bootstrap-only bridges for conversations with old cached hook commands.

    Codex may delete prior version directories on plugin add. New hook definitions
    use the stable runtime directly, but an open conversation retains its old path.
    """
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home()/".codex"))).expanduser()
    cache = codex_home/"plugins/cache"/marketplace/"codex-telegram-reports"
    return [path for path in cache.glob("*/scripts/run.py") if path.is_file() and not path.is_symlink()]


def restore_hook_launchers(paths):
    bootstrap = (ROOT/"scripts/run.py").read_bytes()
    for path in paths:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(bootstrap)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="Update from this checkout without repeating account login")
    parser.add_argument("--qr", action="store_true", help="Use QR for first-time Telegram login")
    args = parser.parse_args()
    try:
        codex = preflight()
        repo = ROOT.parents[1]
        catalog = json.loads((repo/".agents/plugins/marketplace.json").read_text())
        name = catalog["name"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise RuntimeError("Invalid marketplace name.")
        config_path = home_path()/"config.json"
        config = json.loads(config_path.read_text()) if config_path.exists() else {}
        if args.update and not config.get("group_id"):
            raise RuntimeError("Первую настройку выполните без --update.")
        # Detect another installed source before adding a second copy of its hooks.
        inventory = subprocess.run([codex, "plugin", "list", "--json"], capture_output=True, text=True, check=True, timeout=30)
        selected_marketplace = installation_marketplace(json.loads(inventory.stdout), name)
        python = install()
        if not config.get("group_id"):
            runtime(python, "onboard", *(["--qr"] if args.qr else []))
        else:
            if config.get("logged_out"):
                runtime(python, "login", *(["--qr"] if args.qr else []))
            runtime(python, "service", "install")
        # Runtime and consent are ready before any reporting hooks become active.
        if selected_marketplace == name:
            subprocess.run([codex, "plugin", "marketplace", "add", str(repo)], check=True)
        launchers = existing_hook_launchers(selected_marketplace)
        try:
            subprocess.run([codex, "plugin", "add", f"codex-telegram-reports@{selected_marketplace}"], check=True)
        finally:
            restore_hook_launchers(launchers)
        print("Откройте НОВЫЙ разговор Codex и проверьте /hooks: SessionStart, UserPromptSubmit, Stop, Interrupt.")
        print("Доверие обработчикам подтверждается вами в Codex; мастер его не меняет.")
        print("Проверка: python3 plugins/codex-telegram-reports/scripts/run.py doctor --mcp")
        if not args.update and input("Отправить тестовый отчёт в вашу группу? [y/N]: ").strip().lower() in {"y", "yes", "д", "да"}:
            runtime(python, "test-report")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Настройка не завершена ({type(exc).__name__}): {exc}\nПовторный запуск сохраняет аккаунт и историю.\n")
    except (KeyboardInterrupt, EOFError):
        parser.exit(1, "Настройка прервана; её можно продолжить повторным запуском.\n")


if __name__ == "__main__":
    main()
