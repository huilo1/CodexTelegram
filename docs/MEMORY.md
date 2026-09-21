## Owner acceptance and publication — 21 September 2026

The owner reports that basic checks work and explicitly authorized committing and
pushing the current implementation to origin/main. Include the reports plugin,
marketplace entry, setup/release scripts, tests and documentation; these had not
yet been committed. Latest observed automated result: 95 tests passed. No GitHub
tag or release was requested. Earlier notes about uncommitted work describe the
state before this publication step.

## Hook cache removal follow-up — 21 September 2026

Stop in an already-open conversation failed after plugin reinstall deleted its old
version's scripts/run.py. Restored bootstrap-only compatibility files, changed all
four hook commands to Python -I inline stable-runtime bootstrap (no PLUGIN_ROOT),
and made setup.py preserve old launcher paths around codex plugin add. New tests
exercise each hook without plugin cache and with hostile cwd/PYTHONPATH; 95 pass.
Installed plugin 0.2.0+codex.20260921091508. Runtime modules were unchanged in this follow-up;
setup's attempted dependency download failed because the network was unreachable,
so the existing healthy runtime was retained and plugin-only reinstall completed
locally with legacy launchers restored. Old active launcher and new installed hook
both executed successfully. Codex hooks/list marks new commands trustStatus=modified;
the owner must confirm the four changed handlers through /hooks for new conversations.
Existing conversation bootstrap is restored. Do not claim updated hooks are trusted.

## Files, concise reports and Telega topics — 21 September 2026

Installed 0.2.0+codex.20260921091036; 90 tests pass. New telegram_send_file MCP and /file in
Telegram queue immutable attachments with stable random IDs; natural-language
requests use a structured responder result and the private file index. Owner ACL,
actual checkout, excluded secret paths, no links, bounded size and text redaction
apply. Binary artifacts/archives are not internally sanitized. Limits: 2000 MiB
binary, 8 MiB UTF-8; attachments persist privately after delivery. Upload worker is
separate from receive/feedback loops. Small document delivered in the live group;
64 MiB staging memory tested, maximum-size network transfer not tested.

Store workspace_topics explicitly maps Telega-work integration/clients/server to
Telega · integration/clients/server. Integration kept its topic/history; old reports
were not moved. Ordinary worktrees still share a repository topic. New conversations
are needed for existing MCP processes to load routing/tools; launcher scripts unchanged.
Long reports get extractive previews, full public text remains for /full. Tests,
blockers and limitations have a soft length budget; no semantic-completeness guarantee.
No commit/push/release in this task. Existing unrelated working changes were preserved.

# Project Memory

## GitHub distribution preparation — 20 September 2026

Current plugin: 0.2.0+codex.20260920151932, 74 tests pass. Owner explicitly forbids
sharing our Telegram API ID/hash. Distribution is BYO credentials only: local
configure-api/onboard asks each user to register their own API application.
No app credentials, session, invite or ready-made config ship in the source/ZIP.

New setup.py handles runtime, onboarding, local repo marketplace and plugin install.
Existing same-source personal installs are preserved to avoid duplicate hooks.
Fresh stores default selected; legacy stores with projects preserve all. Explicit
project enable/disable overrides the default. Current owner's all-project setup
and existing sessions remain working after the verified setup.py --update.

Runtime now uses ~/.codex-telegram-reports/venv -> runtimes/<id>; the previous real
venv was preserved as runtimes/legacy-*. install.py --rollback restores runtime
only. Do not delete these directories while old questions/processes may use them.
Doctor checks Codex auth/version, service heartbeat, Telegram receive and optional
local MCP handshake without printing secrets. Four report hooks remain trusted
in all three existing projects; no trust config change was needed.

README is now the reports entry point; legacy instructions moved to docs/LEGACY_BOT.md.
The repository marketplace local-dev includes both plugins and is configured.
The owner still runs reports@personal, not a duplicate reports@local-dev install.
MIT applies to the new plugin directory only. Release ZIP/checksum in dist; CI,
privacy/security docs and release instructions prepared. No commit/push/release yet.
Secret scan found no high-confidence or exact local API ID/hash/invite matches in
publishable worktree/history. Clean isolated runtime/MCP tested; new-person Telegram
onboarding and second Mac/Python 3.11 still need acceptance testing.

## Current direction — 20 September 2026

Follow-up: the owner confirmed deeper code Q&A works in Telegram. MCP startup in
Kir failed because legacy .mcp.json passed `${PLUGIN_ROOT}` literally; actual
App Server stderr showed Kir/${PLUGIN_ROOT}/scripts/run.py missing. A direct
launcher test had hidden this by substituting the path in the test. The manifest
now bootstraps the installed private runtime directly with Python -I; tests execute
the exact manifest command from a sibling directory, including spaces and a
hostile PYTHONPATH/module shadow. Hooks keep their supported shell PLUGIN_ROOT.

Question receipt feedback: durable question_feedback rows are inserted atomically
with accepted questions. A separate worker marks the topic read and sets 👀; it
clears the reaction only when every answer part has a Telegram message_id.
Retries are idempotent and persist across restart; model latency doesn't block
receipts for later questions. Invalid/disabled reactions leave read receipts and
answer delivery working; unauthorized/unknown-topic messages receive no feedback.
Verified: 62 tests; actual App Server startup from Kir exposes all four MCP tools
with no toolsError; real Telegram confirms topic read_inbox_max_id and own 👀 reaction.
Temporary live-test reaction was restored. Current installed plugin version is
0.2.0+codex.20260920143024; source/runtime match and hooks trusted in Kir/Telega/
CodexTelegram. Updated service is running. Existing Codex conversations need a
new session to pick up the corrected MCP manifest.

QR login added after code delivery still failed: `onboard --qr`, `login --qr`,
or `/qr` inside the number/code prompt. Uses Telethon qr_login/wait/recreate;
wait is registered before showing the token. Local browser HTML with inline SVG
refreshes automatically, mode 0600; token image is cleared on success, cancellation,
expiry or 2FA. Scan using the dedicated account in Telegram's Devices menu.
No reuse or logout of the Telega session. Live QR login was confirmed by the owner
and by doctor after onboarding.

Onboarding follow-up: the first phone/code attempt did not receive a visible code
and crashed after empty code entry. Fixed in `auth.py`: empty input stays local,
actual Telegram delivery type is shown, invalid/expired codes and 2FA passwords
can be retried, `/resend` respects server timeout/next_type and rotates the hash,
`/cancel` and RPC failures exit without a traceback. Existing Telegram sessions
are not logged out or reused. Nine auth regression tests cover these branches.

The owner requested a reporting plugin, separate from the legacy remote-control
bot below. Implementation is in `plugins/codex-telegram-reports`; plan and research
are in `docs/REPORTS_PLAN.md`. Owner decisions: dedicated Telegram USER account,
phone/code login locally in Terminal, all projects automatically, start/meaningful
progress/blockers/final, private forum for the owner only. One topic per project;
Telegram may ask status questions but cannot start or modify development tasks.

Runtime is installed in `~/.codex-telegram-reports/venv`, data in the parent private
directory. Only API ID/hash imported from `../Telega/.env`; its sessions and other
secrets were not copied. Do not print or commit secret values. Personal marketplace
is `~/.agents/plugins/marketplace.json`, source link `~/plugins/codex-telegram-reports`
points at the plugin in this repository. Codex hooks need trusted hashes matching
the currently installed plugin version. Use the plugin-creator cachebuster/reinstall
workflow, then verify `hooks/list`; do not silently assume old hashes remain valid.

Onboarding Terminal was opened with `codex-telegram-reports onboard`. The wizard
logs in, asks for the owner's PERSONAL @username, creates/reuses the private forum,
produces a join-request link, and installs the launchd service. It only approves
the configured owner ID. Live QR login, private group setup and launchd service are
now confirmed; heartbeat is fresh. The owner's requested test report was sent by
the normal outbox worker to the newly created CodexTelegram topic (topic_id 3,
message_id 4), with zero retries/errors and an empty queue afterward. The saved
invite link was given to the owner, who must open it with their personal account.
Owner membership and four delivered Q&A replies are now confirmed by the queue.
Run `doctor` to check
current local state without secrets; do not create a second group or reauthorize.

Q&A now combines delivered reports, explicit task notes (`telegram_task_context`),
same-task follow-up history and a sanitized text snapshot of the actual worktree.
Reports store their checkout; questions retain a selected report through reply
chains, including replies to service answers. Without reply, selection is the
latest delivered report at ingestion. Legacy reports explicitly fall back to the
project root. Never silently substitute another checkout for a removed worktree.

Ephemeral Codex exec has shell/plugins/apps/browser/agents disabled and a PreToolUse
guard allowing only six private project_reader MCP tools. App Server supplies its
exact trusted hash per invocation, without global config changes or trust bypass.
`features.code_mode_host=true` is required by this CLI/model to dispatch MCP calls,
even with code_mode/code_mode_only false. The host does not enable general shell.
The guard was verified by temporarily enabling exec in a fixture: pwd was blocked.

Python diagnostics use `codex sandbox -P <unique profile> --include-managed-config`:
read sanitized snapshot/Python runtime, write only scratch, no network/host secrets.
Environment is cleared, Python runs -I -S -B; hard limits restrict CPU, file size,
file descriptors and process creation. macOS rejects lowering RLIMIT_AS here, so
the trusted parent samples RSS with a 512 MiB threshold (not a hard memory quota).
Live tests cover project/snapshot writes, outside reads, TCP/Unix sockets, child
processes and signals to an external fixture. Scripts are enabled only on macOS;
unsupported systems retain read/search and never fall back to unsandboxed execution.

52 tests passed after this change. A real Codex answer cited project_reader.py and
used sandboxed AST analysis to count its functions. A real request to modify a
fixture and start an app was refused; the fixture stayed unchanged.
Git diff/status collection also disables clean/process filters; log signature
programs are disabled. A fixture with malicious filter commands did not run them.
launchd installation now retries transient bootstrap error 5 after bootout.
Installed plugin: 0.2.0+codex.20260920141729, runtime/source match, service restarted,
all four hooks trusted in CodexTelegram/Telega/Kir. Completion report delivered
as message_id 14 with zero retries; queue empty and heartbeat fresh.

The legacy implementation below remains intact and is not launched by the new plugin.

## Goal

Implement a Codex analogue of `claude-code-telegram`: a Telegram bot that lets one approved Telegram chat drive local development through the `codex` CLI.

## What Was Implemented

- Python package `codex_telegram`
- Telegram polling bot using `python-telegram-bot`
- Persistent per-chat session store in `.codex-telegram/state.json`
- Codex integration through `codex exec --json`
- Session continuation through `codex exec resume`
- Safe directory changes constrained by `CODEX_ALLOWED_ROOT`
- Commands:
  - `/start`
  - `/help`
  - `/new`
  - `/status`
  - `/pwd`
  - `/cd <dir>`
  - `/cancel`
- Progress message updates from Codex JSON events
- Quiet Telegram UX: one acceptance message plus one loader GIF, then final result
- Timeout support via `CODEX_TIMEOUT_SECONDS`
- Cancellation support that terminates the running Codex subprocess
- Explicit warning reply for wrong `TELEGRAM_CHAT_ID`
- Runtime logging to `CODEX_LOG_FILE`
- Example `systemd` unit in `ops/codex-telegram.service.example`
- Repo-local Codex plugin in `plugins/codex-telegram`
- Bundled `systemd` user service template for persistent background running

## Important Design Decisions

- First version is intentionally a focused MVP, not a full clone of the Claude project.
- One approved Telegram chat is supported, controlled by `TELEGRAM_CHAT_ID`.
- Codex session continuity is tracked by stored `thread_id`.
- Changing working directory resets the stored `thread_id` because Codex sessions are workspace-bound.
- Approval prompts are not supported interactively through Telegram, so the implementation avoids flows that require them.

## Files To Know

- `src/codex_telegram/main.py`: CLI entrypoint
- `src/codex_telegram/bot.py`: Telegram handlers and runtime behavior
- `src/codex_telegram/codex_runner.py`: subprocess adapter for `codex exec` and `resume`
- `src/codex_telegram/config.py`: environment-driven settings
- `src/codex_telegram/session_store.py`: persisted chat state
- `src/codex_telegram/safety.py`: path restriction logic
- `README.md`: setup and operator instructions

## Validation Already Done

- `uv run --with pytest --with pytest-asyncio pytest -q`
- `python3 -m compileall src`
- Manual Codex runner verification:
  - first `codex exec`
  - second `codex exec resume`
  - confirmed same `thread_id` reused
- Telegram connectivity verification:
  - `getMe` succeeded
- polling bot started successfully
- Timeout and cancellation handler branches covered by tests in `tests/test_bot_runtime.py`

## Known Operational Facts

- Telegram bot only responds while the local process is running.
- Current operator mistake that already happened once: message was sent while the bot process was not running.
- Real secrets are stored only in local `.env`; do not duplicate them into docs.
- `workspace-write` sandbox blocks network for Codex shell commands in this setup. Networked Telegram tasks require `CODEX_SANDBOX=danger-full-access`.

## Next Logical Enhancements

- Add richer progress streaming instead of only replacing one progress message
- Add optional multi-chat or user allowlist support
- Add export/import or pinned startup prompt for better Telegram-side continuity
