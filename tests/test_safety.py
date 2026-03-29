from pathlib import Path

import pytest

from codex_telegram.safety import resolve_within_root


def test_resolve_within_root_accepts_child(tmp_path: Path) -> None:
    child = tmp_path / "child"
    child.mkdir()
    resolved = resolve_within_root(tmp_path, tmp_path, "child")
    assert resolved == child


def test_resolve_within_root_blocks_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes"):
        resolve_within_root(tmp_path, tmp_path, "../outside")
