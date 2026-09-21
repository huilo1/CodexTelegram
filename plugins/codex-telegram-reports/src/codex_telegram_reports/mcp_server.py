from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP

from .store import Store

mcp = FastMCP("codex-telegram-reports", instructions="Publish project development reports. This server never accepts development tasks from Telegram.")


@mcp.tool()
def telegram_report(project_path: str, thread_id: str, task_id: str, title: str,
                    state: Literal["started", "progress", "blocked", "completed", "failed", "interrupted"],
                    summary: str, event_key: str | None = None) -> dict:
    """Queue a concise report to this project's Telegram topic. Include actual thread/task ids.

    Only projects enabled by the owner can send reports. Never include credentials, private file contents,
    raw tool logs, or hidden reasoning. queued means persisted locally, not delivered.
    Use the same event_key when retrying an identical event.
    """
    store = Store()
    try:
        result = store.report(project_path, thread_id, task_id, title, state, summary, event_key)
        if result["queued"]:
            result["delivery"] = "pending; background service delivers to Telegram"
        return result
    finally:
        store.close()


@mcp.tool()
def telegram_reporting_status() -> dict:
    """Read the local report queue and service heartbeat. Does not contact Telegram."""
    store = Store()
    try:
        return store.health()
    finally:
        store.close()


@mcp.tool()
def telegram_send_file(project_path: str, thread_id: str, task_id: str, file_path: str,
                       caption: str = "", event_key: str | None = None) -> dict:
    """Queue a project file as a Telegram document ONLY when the user requests sending it.

    Use the actual checkout. file_path may be relative to it or absolute inside it.
    Up to 2000 MiB for supported documents/builds, 8 MiB for UTF-8 text. Known secret
    paths, databases and links are excluded; text is redacted. Binary contents are
    not sanitized: choose only the artifact the owner requested. No automatic uploads.
    queued means persisted locally, not delivered. Use a stable event_key for retries.
    """
    store = Store()
    try:
        return store.send_file(project_path, thread_id, task_id, file_path, caption, event_key)
    finally:
        store.close()


@mcp.tool()
def telegram_register_project(project_path: str, display_name: str | None = None) -> dict:
    """Register a project for a single forum topic. Hooks also do this automatically."""
    store = Store()
    try:
        p = store.register(project_path, display_name)
        return {"project_id": p["id"], "name": p["name"], "topic_id": p["topic_id"], "enabled": bool(p["enabled"])}
    finally:
        store.close()


@mcp.tool()
def telegram_task_context(project_path: str, thread_id: str, task_id: str, goal: str,
                          plan: str = "", decisions: str = "", checks: str = "", next_steps: str = "") -> dict:
    """Save concise context for deeper Telegram questions without sending an extra report.

    Use the actual task checkout and IDs. Replace the full context when it changes.
    Include explicit public decisions and observed test results, never hidden reasoning,
    credentials, raw prompts or tool logs. This does not start or modify development.
    """
    store = Store()
    try:
        return store.task_context(project_path, thread_id, task_id,
                                  dict(goal=goal, plan=plan, decisions=decisions, checks=checks, next_steps=next_steps))
    finally:
        store.close()


def run_mcp():
    mcp.run(transport="stdio")
