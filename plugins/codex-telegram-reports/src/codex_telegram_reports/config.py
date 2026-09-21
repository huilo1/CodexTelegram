from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path


def data_dir() -> Path:
    path = Path(os.environ.get("CODEX_TELEGRAM_REPORTS_HOME", "~/.codex-telegram-reports")).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def load_config() -> dict:
    path = data_dir() / "config.json"
    return json.loads(path.read_text()) if path.exists() else {}


def save_config(config: dict) -> None:
    path = data_dir() / "config.json"
    temp = path.with_suffix(".tmp")
    with open(temp, "w", opener=lambda p, f: os.open(p, f, 0o600)) as stream:
        json.dump(config, stream, indent=2)
        stream.write("\n")
    temp.chmod(0o600)
    temp.replace(path)


def project_root(cwd: str) -> str:
    path = Path(cwd).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise ValueError("Project must be a directory")
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, timeout=3, check=True,
        )
        common = Path(result.stdout.strip()).resolve()
        if common.name == ".git":
            return str(common.parent)
    except (OSError, subprocess.SubprocessError):
        pass
    return str(path)


def workspace_root(cwd: str) -> str:
    """Keep the actual checkout, unlike project_root which groups worktrees."""
    path = Path(cwd).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise ValueError("Workspace must be a directory")
    try:
        result = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"],
                                capture_output=True, text=True, check=True, timeout=3)
        return str(Path(result.stdout.strip()).resolve(strict=True))
    except (OSError, subprocess.SubprocessError):
        return str(path)


def redact(text: str) -> str:
    """Best-effort defense; producers must still send only report-safe summaries."""
    text = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", "[скрыт ключ]", text, flags=re.S)
    text = re.sub(r"(?i)\b(?:sk-[\w-]{12,}|\d{6,12}:[A-Za-z0-9_-]{25,})\b", "[скрыт ключ]", text)
    text = re.sub(
        r'''(?im)\b([\w-]*(?:api[_-]?key|api[_-]?hash|password|passwd|secret|token|authorization)[\w-]*)["']?\s*[:=]\s*(?:Bearer\s+)?(?:"[^"\n]*"|'[^'\n]*'|[^\s,;]+)''',
        r"\1=[скрыто]", text)
    return text.replace("\x00", "")


def split_text(text: str, limit: int = 3500) -> list[str]:
    # Telegram limits use UTF-16 code units. An emoji occupies two.
    parts, chunk, length = [], [], 0
    for char in text:
        width = len(char.encode("utf-16-le")) // 2
        if length + width > limit:
            parts.append("".join(chunk))
            chunk, length = [], 0
        chunk.append(char)
        length += width
    if chunk:
        parts.append("".join(chunk))
    return parts
