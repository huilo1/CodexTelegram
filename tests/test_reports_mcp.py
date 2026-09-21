import os
import sys
import json
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from codex_telegram_reports.store import Store


@pytest.mark.asyncio
async def test_real_mcp_handshake_and_queue(tmp_path):
    env = dict(os.environ, CODEX_TELEGRAM_REPORTS_HOME=str(tmp_path / "data"))
    data = tmp_path / "data"
    data.mkdir()
    store = Store(data/"reports.sqlite3")
    store.reporting_mode("all")
    store.close()
    params = StdioServerParameters(command=sys.executable, args=["-m", "codex_telegram_reports.cli", "mcp"], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert {x.name for x in tools.tools} == {"telegram_report", "telegram_reporting_status", "telegram_register_project", "telegram_task_context", "telegram_send_file"}
            report = await session.call_tool("telegram_report", {
                "project_path": str(tmp_path), "thread_id": "test", "task_id": "task",
                "title": "MCP test", "state": "progress", "summary": "Verified the MCP transport"})
            assert not report.isError
            assert json.loads(report.content[0].text)["queued"]
            status = await session.call_tool("telegram_reporting_status", {})
            assert json.loads(status.content[0].text)["pending_messages"] == 1
            context = await session.call_tool("telegram_task_context", {
                "project_path": str(tmp_path), "thread_id": "test", "task_id": "task",
                "goal": "Useful questions", "checks": "MCP transport verified"})
            assert not context.isError
            assert json.loads(context.content[0].text)["saved"]
            (tmp_path / "artifact.txt").write_text("Public test artifact")
            attachment = await session.call_tool("telegram_send_file", {
                "project_path": str(tmp_path), "thread_id": "test", "task_id": "task",
                "file_path": "artifact.txt", "event_key": "artifact"})
            assert not attachment.isError
            assert json.loads(attachment.content[0].text)["queued"]


@pytest.mark.asyncio
async def test_manifest_launcher_from_another_project_with_spaces(tmp_path):
    """Execute the exact .mcp.json command, without manually expanding placeholders."""
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root/"plugins/codex-telegram-reports/.mcp.json").read_text())["mcpServers"]["telegram-reports"]
    data = tmp_path/"report runtime"; data.mkdir()
    (data/"venv").symlink_to(Path(sys.prefix), target_is_directory=True)
    project = tmp_path/"neighbour project"; project.mkdir()
    # A project module or injected PYTHONPATH must not break the installed runtime.
    (project/"typing.py").write_text("raise RuntimeError('project shadow imported')\n")
    env = dict(os.environ, CODEX_TELEGRAM_REPORTS_HOME=str(data), PYTHONPATH=str(project))
    params = StdioServerParameters(command=config["command"], args=config["args"], cwd=str(project), env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            names = {t.name for t in (await session.list_tools()).tools}
            assert "telegram_report" in names and "telegram_task_context" in names
            status = await session.call_tool("telegram_reporting_status", {})
            assert not status.isError
            assert json.loads(status.content[0].text)["pending_messages"] == 0
