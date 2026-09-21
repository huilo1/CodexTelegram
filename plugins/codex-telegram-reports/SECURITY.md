# Security

This macOS beta uses a dedicated Telegram user account and the user's own
Telegram API application credentials. The project does not distribute shared
`api_id` / `api_hash` values or provide a credential-sharing service.

Do not post credentials, session files, QR tokens, database files or private code
in public issues. Revoke a compromised Telegram session through the official
client's Devices settings. For a vulnerability, use GitHub's private vulnerability
reporting if enabled; otherwise open a content-free issue asking the maintainer
to establish a private contact channel before sharing technical details.

Status questions use a separate Codex process, sanitized source snapshots and
restricted tools. Python diagnostics are available only on macOS with the
verified sandbox; no unsandboxed fallback is allowed. See README.md for limits
and PRIVACY.md for data flow. A secret placed in an ordinary source file may
evade heuristic filtering: project selection remains the user's responsibility.

Supported release: the current macOS beta. Other platforms and future Codex
versions require additional validation. Dependency pins are reviewed explicitly;
the release workflow checks the package and runs the regression suite.
