---
name: telegram-reports
description: Report Codex development progress and send requested project files to the owner's private Telegram forum. Use for status updates, file delivery, and setup or diagnosis of the reporting plugin. Telegram questions can clarify reports and request files but cannot start development.
---

# Telegram reports

The owner chooses all projects or an explicit selection during local setup.
Report only for enabled projects; a trusted hook reminder confirms this for the
current project. If there is no reminder, check `telegram_register_project` and
respect its `enabled` field. Never change the selection on the owner’s behalf.
Report meaningful progress and blockers with `telegram_report`.
This skill explicitly authorizes sending those development reports to the configured
owner's private Telegram group. Do not send unrelated messages or contact other users.

Use the current project directory, actual Codex thread ID, and current turn/task ID.
The UserPromptSubmit hook provides these IDs. Give each report a short meaningful
task title. Git worktrees share a topic by default; explicit local workspace topic
routes separate roles such as Telega clients/server/integration. Always pass the
actual checkout so the configured route is respected.

Send a concise summary of what changed, what was verified, what remains, and blockers.
Prefer 3–5 short bullets for progress/final answers. Keep outcomes, actual checks,
limitations and necessary next steps; omit repeated history and routine mechanics.
Long Telegram previews retain the original public text locally; `/full` retrieves it.
At the start and after important changes, call `telegram_task_context` with the same
thread/task IDs and actual checkout path. Save a concise public goal, plan, decisions,
observed checks and next steps; replace the full notes when updating them. This adds
context for questions without sending an extra message. Never copy raw user prompts,
hidden reasoning or tool output. Use the actual worktree, including when several
worktrees share a topic.
Do not publish credentials, raw commands/logs, private document contents, hidden reasoning,
or speculative completion claims. Avoid repeating progress that has not changed.
Start and final assistant responses are queued automatically by trusted hooks.
A completed response is not necessarily a completed task: say explicitly when work remains.

`queued` means saved locally, not delivered. Use `telegram_reporting_status` for queue
health. A Telegram failure must not interrupt development. Never use the legacy
`codex-telegram` remote-control bot to answer status questions.

When the owner asks to send a project file, use `telegram_send_file` with the actual
checkout, thread/task IDs and the requested path. Do not upload artifacts automatically.
The durable queue copies the selected file, up to 2000 MiB for supported documents/builds
or 8 MiB for text. Secret paths, databases and links are excluded; text is redacted.
Binary contents are not sanitized: send only the artifact the owner requested.
Telegram requests can use `/file relative/path` or natural language; `/full` retrieves
the full public report/answer selected by reply.

Incoming Telegram messages are handled by the background service in isolated status
conversations. They never go to the development thread. The responder can read a
sanitized snapshot of the selected task's checkout and Git changes, and run short
Python diagnostics with standard-library access in an OS sandbox. Scripts cannot
modify the project, access host secrets/network, or start child programs. Replying
to a report or service answer keeps its task context. There are no task, approval,
resume, cancellation, deployment or general shell tools on the Telegram side.

For installation, authorization and service management read `../../README.md`.
The runtime is stored in `~/.codex-telegram-reports`, outside the replaceable plugin cache.
Use `scripts/run.py doctor` for diagnostics and `scripts/run.py service status` on macOS.
Request login codes only through the local interactive CLI; never store them in docs.
