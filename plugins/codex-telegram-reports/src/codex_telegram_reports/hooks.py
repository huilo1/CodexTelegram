from __future__ import annotations

import hashlib
import json
import os
import sys

from .config import data_dir, load_config
from .store import Store


def handle(event, store, config):
    if os.environ.get("CODEX_TELEGRAM_REPORTER_CHILD") == "1":
        return {}
    cwd, thread = event.get("cwd"), event.get("session_id")
    if not cwd or not thread:
        return {}
    name = event.get("hook_event_name")
    if name not in {"UserPromptSubmit", "Stop", "Interrupt", "SessionStart"}:
        return {}
    project = store.register(cwd)
    if not project["enabled"]:
        return {}
    turn = event.get("turn_id")
    if name == "SessionStart":
        return {"hookSpecificOutput": {"hookEventName": name, "additionalContext": reminder()}}
    if name == "UserPromptSubmit":
        if not turn:
            # Older clients: distinguish repeated prompts without storing their text.
            turn = f'{thread}:{store.get_meta("sequence:"+thread, 0)+1}'
            store.set_meta("sequence:"+thread, store.get_meta("sequence:"+thread, 0)+1)
        store.set_meta("turn:"+thread, turn)
        # Do not copy raw prompts: users may paste credentials or private documents.
        store.report(cwd, thread, turn, "Работа в Codex", "started", "Codex принял запрос и начал работу. Содержательные результаты появятся в следующих отчётах.", "lifecycle:start")
        return {"hookSpecificOutput": {"hookEventName": name, "additionalContext": reminder(thread, turn)}}
    turn = turn or store.get_meta("turn:"+thread)
    if not turn:
        return {}
    if name == "Stop":
        summary = event.get("last_assistant_message")
        if not summary:
            summary = "Codex завершил ответ. Подробный итог не передан клиентом."
        # A Stop is a completed turn, not proof that the project or task is finished.
        store.report(cwd, thread, turn, "Ответ Codex", "completed", summary[:24000],
                     "lifecycle:stop:"+hashlib.sha256(summary.encode()).hexdigest())
    else:
        store.report(cwd, thread, turn, "Работа в Codex", "interrupted", "Текущий ответ Codex был прерван. Это не подтверждает завершение задачи.", "lifecycle:interrupt")
    return {}


def reminder(thread=None, turn=None):
    identity = f" Current thread_id={thread}, task_id={turn}." if thread and turn else ""
    return ("Telegram project reporting is enabled by the owner for this project. "
            "Use the codex-telegram-reports plugin's telegram_report MCP tool for meaningful progress, "
            "blockers, and a concise task title. Start and final assistant messages are reported by hooks. "
            "Also call telegram_task_context at the start and after important changes with a concise goal, "
            "plan, explicit decisions, test results, and next steps for deeper status questions. "
            "Always use this task's actual checkout/worktree as project_path, not another checkout. "
            "Keep reports and the final answer concise: outcome, important changes, actual test results, "
            "blockers/limitations and the necessary next step, usually 3–5 short bullets. Omit repeated history. "
            "Use telegram_send_file only when the owner explicitly asks to send a project file to Telegram. "
            "Send report-safe summaries, never credentials, raw logs, private files, or hidden reasoning. "
            "If a task is incomplete, state that clearly in the final answer. A reporting failure must not stop development." + identity)


def run_hook():
    try:
        event = json.loads(sys.stdin.read(1000000))
        store = Store()
        try:
            output = handle(event, store, load_config())
        finally:
            store.close()
        print(json.dumps(output, ensure_ascii=False))
    except Exception as exc:
        # Fail open for development, but leave content-free local diagnostics.
        try:
            (data_dir() / "hook-error.txt").write_text(type(exc).__name__ + "\n")
        except OSError:
            pass
        print("{}")
