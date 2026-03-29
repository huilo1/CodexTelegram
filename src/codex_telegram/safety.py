from __future__ import annotations

from pathlib import Path


def resolve_within_root(root: Path, current_cwd: Path, requested: str) -> Path:
    base = current_cwd if not requested.startswith("/") else root
    candidate = (base / requested).expanduser().resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("Path escapes CODEX_ALLOWED_ROOT")
    if not candidate.exists():
        raise ValueError(f"Path does not exist: {candidate}")
    if not candidate.is_dir():
        raise ValueError(f"Path is not a directory: {candidate}")
    return candidate
