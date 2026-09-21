#!/usr/bin/env python3
"""Build before switching runtimes. Keep the previous environment for rollback."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time
import uuid
import venv

ROOT = Path(__file__).resolve().parents[1]


def home_path():
    return Path(os.environ.get("CODEX_TELEGRAM_REPORTS_HOME", "~/.codex-telegram-reports")).expanduser().absolute()


def runtime(python, *args, **kwargs):
    return subprocess.run([str(python), "-I", "-m", "codex_telegram_reports.cli", *args], check=True, **kwargs)


@contextmanager
def exclusive(path, timeout=0):
    import fcntl
    with path.open("a") as lock:
        deadline = time.monotonic()+timeout
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Another installer or report service is running; stop it and retry.") from None
                time.sleep(.1)
        yield


def switch(home, target):
    active = home/"venv"
    previous = active.resolve() if active.exists() else None
    if active.exists() and not active.is_symlink():
        previous = home/"runtimes"/("legacy-"+uuid.uuid4().hex[:12])
        active.rename(previous)
    link = home/(".runtime-"+uuid.uuid4().hex)
    try:
        link.symlink_to(target, target_is_directory=True)
        link.replace(active)
    except BaseException:
        link.unlink(missing_ok=True)
        if previous and not active.exists() and not active.is_symlink():
            previous.rename(active)
        raise
    return previous


def owns_service(home):
    path = Path.home()/"Library/LaunchAgents/org.codex.telegram-reports.plist"
    if not path.exists():
        return False
    payload = plistlib.loads(path.read_bytes())
    configured = payload.get("EnvironmentVariables", {}).get("CODEX_TELEGRAM_REPORTS_HOME")
    return bool(configured and Path(configured).resolve() == home.resolve())


def replace_state(home, previous, current):
    temp = home/"runtime-install.tmp"
    temp.write_text(json.dumps({"previous": str(previous) if previous else None, "current": str(current)}, indent=2)+"\n")
    temp.replace(home/"runtime-install.json")


def install(rollback=False):
    if sys.version_info < (3, 11):
        raise RuntimeError("Python 3.11+ is required. Run this script with python3.11 or newer.")
    if sys.platform != "darwin":
        raise RuntimeError("This installer supports the macOS beta only.")
    os.umask(0o077)
    home = home_path()
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    home.chmod(0o700)
    (home/"runtimes").mkdir(exist_ok=True)
    with exclusive(home/"install.lock"):
        if rollback:
            state = json.loads((home/"runtime-install.json").read_text())
            target = Path(state.get("previous") or "")
            if not target.is_absolute() or not target.is_relative_to(home/"runtimes") or not (target/"bin/python").is_file():
                raise RuntimeError("No previous runtime is available.")
        else:
            target = home/"runtimes"/uuid.uuid4().hex
            print("Preparing an isolated runtime; the active service stays available.", flush=True)
            venv.create(target, with_pip=True)
            python = target/"bin/python"
            subprocess.run([str(python), "-I", "-m", "pip", "install", "--quiet", "-r", str(ROOT/"requirements.lock")], check=True)
            subprocess.run([str(python), "-I", "-m", "pip", "install", "--quiet", "--no-deps", str(ROOT)], check=True)
            subprocess.run([str(python), "-I", "-m", "pip", "check"], check=True)
            subprocess.run([str(python), "-I", "-c", "from codex_telegram_reports import cli, mcp_server, responder, project_reader"], check=True)
            (target/"plugin-version.txt").write_text(json.loads((ROOT/".codex-plugin/plugin.json").read_text())["version"]+"\n")
        service_running = owns_service(home) and subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/org.codex.telegram-reports"], capture_output=True).returncode == 0
        if service_running:
            runtime(home/"venv/bin/python", "service", "stop")
        previous = None
        try:
            with exclusive(home/"service.lock", timeout=10):
                previous = switch(home, target)
                replace_state(home, previous, target)
            if service_running:
                runtime(home/"venv/bin/python", "service", "install")
        except BaseException:
            if previous:
                switch(home, previous)
                replace_state(home, target, previous)
            if service_running:
                runtime(home/"venv/bin/python", "service", "install")
            raise
    print("Runtime ready. Settings, session and report history preserved.")
    return home/"venv/bin/python"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rollback", action="store_true", help="Restore the preceding runtime; does not revert plugin cache or database")
    args = parser.parse_args()
    try:
        install(args.rollback)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Installation failed ({type(exc).__name__}): {exc}\n")


if __name__ == "__main__":
    main()
