# Changelog

## Unreleased

- Hook bootstrap uses the stable runtime directly; updates retain legacy launchers
  so conversations opened before an update can finish their reporting hooks.

- Requested project files via Telegram `/file`, natural-language requests and
  `telegram_send_file`; immutable durable uploads with stable retry IDs.
- Concise report previews and answers; original public text available with `/full`.
- Explicit workspace topic routes for Telega clients/server/integration; existing
  topic history and reply context preserved.

## 0.2.0 — macOS beta

- Dedicated Telegram user account, private forum and one topic per project.
- Automatic start/final reports through trusted Codex hooks; progress/blockers
  and explicit task context through MCP.
- Read-only status questions using reports, task history, sanitized code snapshots
  and sandboxed Python diagnostics. No remote development commands.
- Immediate 👀 acknowledgement independent of model response time.
- QR or phone/code login with retries and local 2FA input.
- GitHub setup wizard requiring each user's own Telegram API ID/hash.
- Project selection, service/MCP diagnostics, test delivery, logout and uninstall.
- Pinned runtime dependencies, staged runtime replacement and runtime rollback.

Compatibility: macOS, Python 3.11+, Codex CLI 0.155.1 tested. Linux/Windows are not
supported by the installer. Codex hook trust is confirmed by each user separately.
