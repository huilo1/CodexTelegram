"""Build a bounded, sanitized snapshot of the task's actual checkout."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import selectors
import shutil
import signal
import stat
import subprocess
import time

from .config import project_root, redact

MAX_FILE = 512 * 1024
MAX_TOTAL = 24 * 1024 * 1024
MAX_FILES = 4000
SKIP_DIRS = {".git", ".hg", ".svn", ".codex", ".agents", ".ssh", ".aws", ".azure", ".config",
             ".venv", "venv", "env", "node_modules", "vendor", "__pycache__", ".next", "dist", "build",
             ".cache", ".terraform", "secrets", "credentials", ".codex-telegram", ".codex-telegram-reports"}
SECRET_NAME = re.compile(r"(?i)(^\.env(?:\.|$)|\.env$|^id_(rsa|ed25519|ecdsa)|credentials|secrets?|token|password|auth\.json|\.npmrc$|\.pypirc$|\.netrc$|login-qr)")
SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".session", ".sqlite", ".sqlite3", ".db"}


def clean_env():
    # No inherited API credentials, agents, PYTHONPATH, Git overrides or shell startup.
    return {"PATH": "/usr/bin:/bin:/opt/homebrew/bin:/usr/local/bin", "LANG": "en_US.UTF-8",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}


def bounded_run(args, *, cwd, env=None, timeout=10, limit=64000, memory_limit=None):
    """Drain output incrementally; kill the entire child group on size/time limits."""
    proc = subprocess.Popen(args, cwd=cwd, env=env or clean_env(), stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    chunks, size, reason = [], 0, None
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while selector.get_map():
                if time.monotonic() >= deadline:
                    reason = "time limit"
                    break
                if memory_limit is not None:
                    # macOS does not support lowering RLIMIT_AS for this Python runtime.
                    # Bound resident memory from the trusted parent (a sampled limit).
                    usage = subprocess.run(["/bin/ps", "-o", "rss=", "-g", str(proc.pid)],
                                           capture_output=True, text=True, timeout=2)
                    if sum(int(x) for x in usage.stdout.split()) * 1024 > memory_limit:
                        reason = "memory limit"
                        break
                for key, _ in selector.select(min(.2, max(0, deadline-time.monotonic()))):
                    data = os.read(key.fileobj.fileno(), 8192)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    remaining = limit-size
                    chunks.append(data[:remaining])
                    size += len(data)
                    if size > limit:
                        reason = "output limit"
                        break
                if reason:
                    break
        if not reason:
            try:
                proc.wait(timeout=max(.01, deadline-time.monotonic()))
            except subprocess.TimeoutExpired:
                reason = "time limit"
    finally:
        # Also reap descendants retaining pipes or surviving their parent.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        proc.stdout.close()
    return {"returncode": proc.returncode, "output": b"".join(chunks).decode("utf-8", "replace"), "limited": reason}


def git(root, *args, limit=200000):
    binary = shutil.which("git", path=clean_env()["PATH"])
    if not binary:
        raise ValueError("Git unavailable")
    env = clean_env()
    if "diff" in args or "status" in args:
        # --no-textconv does not disable clean/process filters used while Git reads
        # working-tree files. Override each configured filter without shell parsing.
        filters = git(root, "config", "--null", "--name-only", "--get-regexp", r"^filter\..*\.(clean|smudge|process|required)$", limit=16000)
        if filters["limited"] or filters["returncode"] not in (0, 1):
            raise ValueError("Cannot disable repository filters")
        keys = [key for key in filters["output"].split("\0") if key]
        env["GIT_CONFIG_COUNT"] = str(len(keys))
        for index, key in enumerate(keys):
            env[f"GIT_CONFIG_KEY_{index}"] = key
            env[f"GIT_CONFIG_VALUE_{index}"] = "false" if key.endswith(".required") else ""
    result = bounded_run([binary, "--no-pager", "--no-optional-locks", "--literal-pathspecs", "-c", "core.fsmonitor=false",
                          "-c", "core.hooksPath=/dev/null", "-c", "core.quotePath=false",
                          "-c", "log.showSignature=false",
                          "-c", "core.attributesFile=/dev/null", "-C", str(root), *args],
                         cwd=root, env=env, limit=limit)
    return result


def allowed_path(name):
    p = PurePosixPath(name)
    return bool(name and not p.is_absolute() and all(part not in {".", ".."} for part in p.parts)
                and not any(part.lower() in SKIP_DIRS or SECRET_NAME.search(part) for part in p.parts)
                and p.suffix.lower() not in SECRET_SUFFIXES
                and not any(ord(c) < 32 for c in name))


def safe_text(root, name):
    """Open each component relative to an fd: no symlinks, devices or hard links."""
    if not allowed_path(name):
        raise ValueError("Excluded file")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parts = PurePosixPath(name).parts
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(file_fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_FILE:
                raise ValueError("Not an eligible source file")
            data = stream.read(MAX_FILE+1)
            after = os.fstat(stream.fileno())
            if len(data) > MAX_FILE or b"\0" in data or info.st_mtime_ns != after.st_mtime_ns:
                raise ValueError("Binary, oversized or changing file")
        text = data.decode("utf-8")
        # Preserve line numbers even when a multiline key must be removed.
        text = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
                      lambda m: "[скрыт ключ]" + "\n"*m[0].count("\n"), text, flags=re.S)
        return redact(text)
    finally:
        os.close(fd)


def build_snapshot(workspace, expected_project, destination):
    deadline = time.monotonic() + 25
    root = Path(workspace).resolve(strict=True)
    if project_root(str(root)) != str(Path(expected_project).resolve(strict=True)):
        raise ValueError("Checkout no longer belongs to this project")
    destination.mkdir(mode=0o700)
    source = destination / "source"
    source.mkdir(mode=0o700)
    listed = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard", limit=2*1024*1024)
    is_git = listed["returncode"] == 0 and not listed["limited"]
    if is_git:
        names = sorted(set(listed["output"].split("\0")) - {""})
    else:
        if (root / ".git").exists() or listed["limited"]:
            raise ValueError("Cannot safely enumerate checkout")
        names = []
        for folder, dirs, files in os.walk(root, followlinks=False):
            relative = Path(folder).relative_to(root)
            dirs[:] = sorted(d for d in dirs if allowed_path((relative/d).as_posix()) and not (Path(folder)/d).is_symlink())
            names.extend((relative/f).as_posix() for f in sorted(files))
            if len(names) > MAX_FILES*3:
                break
    included, skipped, size = [], 0, 0
    for name in names:
        if len(included) >= MAX_FILES or size >= MAX_TOTAL or time.monotonic() > deadline:
            break
        try:
            content = safe_text(root, name)
        except (OSError, ValueError, UnicodeError):
            skipped += 1
            continue
        data = content.encode("utf-8")
        if size + len(data) > MAX_TOTAL:
            skipped += 1
            continue
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.write_bytes(data)
        target.chmod(0o400)
        size += len(data)
        included.append({"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    metadata = {"captured_at": datetime.now(timezone.utc).isoformat(), "checkout": root.name,
                "files": included, "omitted_files": len(names)-len(included),
                "limitations": "Sanitized text snapshot, including eligible uncommitted files; ignored, secret, binary and oversized files omitted. Capture is not an atomic filesystem snapshot.",
                "environment": {"system": platform.system(), "release": platform.release(),
                                "machine": platform.machine(), "analysis_python": platform.python_version()}}
    if is_git:
        status_result = git(root, "-c", "status.renames=false", "status", "--porcelain=v1", "-z", "--untracked-files=all", limit=200000)
        changes = []
        if not status_result["returncode"] and not status_result["limited"]:
            for entry in status_result["output"].split("\0"):
                if len(entry) > 3 and allowed_path(entry[3:]):
                    changes.append({"path": entry[3:], "status": entry[:2]})
        metadata["changed_files"] = changes[:250]
        metadata["status_truncated"] = bool(status_result["limited"] or len(changes)>250)
        metadata["status_legend"] = "Git porcelain: ?? untracked; first column index, second working tree; M modified, A added, D deleted. Diff does not contain untracked/deleted file bodies."
        for key, args in {"head": ("rev-parse", "HEAD"), "branch": ("branch", "--show-current"),
                          "recent_commits": ("log", "-8", "--format=%h %ad %s", "--date=iso-strict")}.items():
            result = git(root, *args, limit=16000)
            metadata[key] = redact(result["output"]) if not result["returncode"] else "unavailable"
        paths = [item["path"] for item in included]
        # Diff only eligible files, never excluded .env/keys, and disable repository diff commands.
        chunks = []
        remaining = 120000
        for start in range(0, len(paths), 100):
            if time.monotonic() > deadline:
                metadata["diff_truncated"] = True
                break
            result = git(root, "diff", "--no-ext-diff", "--no-textconv", "--no-renames", "HEAD", "--",
                         *paths[start:start+100], limit=remaining)
            if result["returncode"] and not result["limited"]:
                break  # Unborn repository: source snapshot is still useful.
            chunks.append(redact(result["output"]))
            remaining -= len(result["output"].encode("utf-8"))
            if result["limited"] or remaining <= 0:
                metadata["diff_truncated"] = True
                break
        (destination / "changes.diff").write_text("\n".join(chunks))
    (destination / "manifest.json").write_text(json.dumps(metadata, ensure_ascii=False))
    return metadata
