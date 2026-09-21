"""Content-free diagnostics. Never print credentials, reports, or Codex login output."""
from __future__ import annotations

import asyncio
from importlib.metadata import version
import os
import re
import shutil
import subprocess
import sys
import time

from .config import data_dir, load_config
from .store import Store


async def probe_mcp():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable,
        args=["-I", "-m", "codex_telegram_reports.cli", "mcp"],
        env={**os.environ, "CODEX_TELEGRAM_REPORTER_CHILD": "1"})
    async with asyncio.timeout(15):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = {tool.name for tool in (await session.list_tools()).tools}
                return names == {"telegram_report", "telegram_task_context", "telegram_register_project", "telegram_reporting_status", "telegram_send_file"}


def diagnose(check_mcp=False):
    config = load_config()
    checks = []

    def add(name, ok, detail):
        checks.append(dict(name=name, ok=bool(ok), detail=detail))

    add("platform", sys.platform == "darwin", "macOS beta; Linux/Windows не проверены")
    add("python", sys.version_info >= (3, 11), ".".join(map(str, sys.version_info[:3])))
    add("telegram_api", config.get("api_id") and config.get("api_hash"), "configure-api: собственные реквизиты пользователя")
    add("telegram_session", config.get("account_id") and (data_dir()/"telegram-user.session").exists(), "onboard --qr: авторизация отдельного аккаунта")
    add("telegram_group", config.get("group_id") and len(config.get("allowed_user_ids", [])) == 1, "setup-group: закрытая группа с одним владельцем")
    codex = shutil.which(config.get("codex_binary", "codex"))
    add("codex_binary", codex, "Codex CLI найден" if codex else "Установите Codex CLI и повторите setup")
    if codex:
        try:
            result = subprocess.run([codex, "--version"], capture_output=True, text=True, timeout=10)
            match = re.search(r"\b(\d+)\.(\d+)\.(\d+)\b", result.stdout)
            compatible = match and tuple(map(int, match.groups())) >= (0, 155, 1)
            add("codex_version", compatible, (match.group(0) if match else "не определена") + "; проверено с 0.155.1")
            login = subprocess.run([codex, "login", "status"], capture_output=True, timeout=10)
            add("codex_auth", login.returncode == 0, "Для входа выполните codex login; вывод авторизации скрыт")
        except (OSError, subprocess.SubprocessError) as exc:
            add("codex_check", False, type(exc).__name__)
    store = Store()
    try:
        queue = store.health()
        heartbeat = queue["last_service_heartbeat"]
        add("service", heartbeat and time.time()-heartbeat < 30, "service install: heartbeat должен быть моложе 30 секунд")
        received = store.get_meta("telegram_last_receive")
        add("telegram_connection", received and time.time()-received < 90, "Успешное чтение группы за последние 90 секунд")
        error = store.get_meta("telegram_receive_error")
        if error:
            add("telegram_receive", False, error)
    finally:
        store.close()
    if check_mcp:
        try:
            add("mcp", asyncio.run(probe_mcp()), "initialize и инструменты отчётов/файлов")
        except Exception as exc:
            add("mcp", False, type(exc).__name__)
    return dict(version=version("codex-telegram-reports"), ready=all(c["ok"] for c in checks), checks=checks, queue=queue)
