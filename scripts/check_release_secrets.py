#!/usr/bin/env python3
"""Check publishable files/history without printing matching secret values."""
import argparse
import json
from pathlib import Path
import re
import subprocess

PATTERNS = {
    "telegram-bot-token": rb"\b[0-9]{7,12}:[A-Za-z0-9_-]{30,}\b",
    "api-key": rb"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{24,}\b",
    "private-key": rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    "telegram-api-hash": rb"(?i)(?:api_hash|TELEGRAM_API_HASH)[\s\x22\x27:=]+[a-f0-9]{32}",
    "private-invite": rb"https://t\.me/\+[A-Za-z0-9_-]{12,}",
}


def findings(path, data, known=()):
    rules = [name for name, pattern in PATTERNS.items() if re.search(pattern, data)]
    if any(value and value in data for value in known):
        rules.append("local-credential-value")
    name = Path(path).name
    if name == ".env" or name.endswith((".session", ".session-journal", ".sqlite3")):
        rules.append("private-state-file")
    return {"file": path, "rules": rules} if rules else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--local-config", type=Path, help="Also detect exact local API ID/hash, session string, and invite values; never prints values")
    args = parser.parse_args()
    known = []
    if args.local_config:
        config = json.loads(args.local_config.read_text())
        known = [str(config[k]).encode() for k in ("api_id", "api_hash", "session_string", "invite_link") if config.get(k)]
    paths = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"]).decode().split("\0")
    result = []
    for path in sorted(set(filter(None, paths))):
        p = Path(path)
        if p.is_symlink():
            result.append({"file":path,"rules":["symlink-review-required"]})
        elif p.is_file():
            finding = findings(path,p.read_bytes(),known)
            if finding:
                result.append(finding)
    if args.history:
        for entry in subprocess.check_output(["git", "rev-list", "--objects", "--all"]).decode().splitlines():
            oid, _, path = entry.partition(" ")
            if not path or subprocess.check_output(["git", "cat-file", "-t", oid]).strip() != b"blob":
                continue
            finding = findings(path, subprocess.check_output(["git", "cat-file", "blob", oid]), known)
            if finding:
                result.append({**finding,"object":oid[:12]})
    print(json.dumps({"findings":result,"scope":"worktree and history" if args.history else "worktree",
                      "note":"Heuristic check, not a guarantee that arbitrary secrets are absent."},indent=2))
    raise SystemExit(bool(result))


if __name__ == "__main__":
    main()
