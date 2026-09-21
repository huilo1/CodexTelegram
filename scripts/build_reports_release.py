#!/usr/bin/env python3
"""Build a source-only reports plugin ZIP; never includes local state or legacy code."""
import hashlib
import json
from pathlib import Path
import re
import zipfile

from check_release_secrets import findings

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT/"plugins/codex-telegram-reports"


def main():
    manifest = json.loads((PLUGIN/".codex-plugin/plugin.json").read_text())
    version = manifest["version"]
    if not re.fullmatch(r"[A-Za-z0-9.+-]+",version):
        raise ValueError("Invalid release version")
    payloads = {}
    for path in sorted(PLUGIN.rglob("*")):
        if path.is_symlink():
            raise ValueError("Release source contains a symlink")
        relative = path.relative_to(ROOT)
        if not path.is_file() or any(p in {"__pycache__", ".venv", "dist"} for p in relative.parts):
            continue
        if path.suffix not in {".py", ".md", ".json", ".toml", ".lock", ".example"} and path.name != "LICENSE":
            raise ValueError(f"Unexpected release file: {relative}")
        payloads[str(relative)] = path.read_bytes()
    for name in ("README.md", "docs/RELEASING_REPORTS.md", "docs/LEGACY_BOT.md"):
        payloads[name] = (ROOT/name).read_bytes()
    catalog = json.loads((ROOT/".agents/plugins/marketplace.json").read_text())
    catalog["plugins"] = [p for p in catalog["plugins"] if p["name"] == manifest["name"]]
    if len(catalog["plugins"]) != 1:
        raise ValueError("Reports plugin missing from marketplace")
    payloads[".agents/plugins/marketplace.json"] = (json.dumps(catalog,indent=2)+"\n").encode()
    for name, data in payloads.items():
        finding = findings(name,data)
        if finding:
            raise ValueError(f"Release secret check failed: {finding}")
    output = ROOT/"dist"; output.mkdir(exist_ok=True)
    archive = output/f"codex-telegram-reports-{version}.zip"
    with zipfile.ZipFile(archive,"w",compression=zipfile.ZIP_DEFLATED) as bundle:
        for name,data in sorted(payloads.items()):
            info = zipfile.ZipInfo("CodexTelegram/"+name, date_time=(2026,9,20,0,0,0))
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info,data)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n")
    print(f"Built {archive.name}: {len(payloads)} files. SHA-256 {digest}")


if __name__ == "__main__":
    main()
