"""Bounded, immutable copies of explicitly requested project files."""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import time

from .config import data_dir, project_root, redact
from .project_context import SECRET_NAME, SECRET_SUFFIXES, SKIP_DIRS

# Telegram's default upload ceiling: 4000 parts of 512 KiB.
MAX_ATTACHMENT = 2000 * 1024 * 1024
MAX_TEXT = 8 * 1024 * 1024
BINARY_SUFFIXES = {".apk", ".aab", ".ipa", ".dmg", ".pkg", ".zip", ".gz", ".tar", ".7z",
                   ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".mov",
                   ".mp3", ".wav", ".xlsx", ".docx", ".pptx"}
EXCLUDED_DIRS = SKIP_DIRS - {"build", "dist"}
FILE_REQUEST = re.compile(r"(?i)пришл|пришли|отправ|вышл|скин|скача|дай\b|дайте\b|передай|attach|send|download|give\b|/file\b")
FILE_OBJECT = re.compile(r"(?i)файл|сборк|архив|установщик|документ|картин|изображен|отч[её]т|исходник|"
                         r"file|build|archive|installer|document|image|report|readme|apk|dmg|pdf|ipa|"
                         r"[\w-]+\.[a-z0-9]{1,8}\b")


def wants_file(text):
    return bool(FILE_REQUEST.search(text) and (FILE_OBJECT.search(text) or text.lstrip().startswith('/file')))


def eligible_path(name):
    p = PurePosixPath(name)
    return bool(name and not p.is_absolute() and ".." not in p.parts
                and not any(ord(c) < 32 for c in name)
                and not any(part.lower() in EXCLUDED_DIRS or SECRET_NAME.search(part) for part in p.parts)
                and not any(part.startswith(".") and part != ".workspace" for part in p.parts)
                and p.suffix.lower() not in SECRET_SUFFIXES
                and not any(part in {"profiles", "cache", "tmp"} for part in p.parts))


def selected_workspace(context):
    root = Path(context["_workspace"]).resolve(strict=True)
    if project_root(str(root)) != str(Path(context["_project_root"]).resolve(strict=True)):
        raise ValueError("Рабочая копия больше не принадлежит проекту.")
    return root


def relative_file(root, name):
    path = Path(name)
    if path.is_absolute():
        try:
            name = path.relative_to(root).as_posix()
        except ValueError:
            raise ValueError("Файл должен находиться в рабочей копии выбранной задачи.") from None
    if not eligible_path(name):
        raise ValueError("Этот путь исключён: служебные файлы, ключи и базы не отправляются.")
    return name


@contextmanager
def open_requested(root, name):
    """Walk with directory fds so path races cannot escape into host files."""
    name = relative_file(root, name)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parts = PurePosixPath(name).parts
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(file_fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise ValueError("Можно отправить только обычный файл без ссылок.")
            binary = Path(name).suffix.lower() in BINARY_SUFFIXES
            limit = MAX_ATTACHMENT if binary else MAX_TEXT
            if before.st_size > limit:
                raise ValueError("Лимит: 2000 MiB для вложений, 8 MiB для текста.")
            yield name, stream, binary, limit
            after = os.fstat(stream.fileno())
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ValueError("Файл меняется или превышает лимит; повторите после записи.")
    finally:
        os.close(fd)


def stage_file(root, name):
    digest, size, sanitized = hashlib.sha256(), 0, False
    folder = data_dir() / "attachments"
    folder.mkdir(mode=0o700, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=folder, delete=False) as stream:
        temp = Path(stream.name)
        try:
            with open_requested(root, name) as (name, source, binary, limit):
                if binary:
                    while chunk := source.read(1024 * 1024):
                        size += len(chunk)
                        if size > limit:
                            raise ValueError("Файл вырос сверх лимита.")
                        digest.update(chunk)
                        stream.write(chunk)
                else:
                    content = source.read(limit + 1)
                    if len(content) > limit:
                        raise ValueError("Файл вырос сверх лимита.")
                    try:
                        text = content.decode("utf-8")
                    except UnicodeError:
                        raise ValueError("Этот бинарный формат не поддерживается.") from None
                    if "\0" in text:
                        raise ValueError("Этот бинарный формат не поддерживается.")
                    clean = redact(text).encode("utf-8")
                    sanitized = clean != content
                    size = len(clean)
                    digest.update(clean)
                    stream.write(clean)
            stream.flush()
            os.fsync(stream.fileno())
            temp.chmod(0o600)
            temp.replace(folder / digest.hexdigest())
        finally:
            temp.unlink(missing_ok=True)
    return {"digest": digest.hexdigest(), "name": Path(name).name, "size": size, "sanitized": sanitized}


def attachment_path(digest):
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("Invalid attachment identity")
    return data_dir() / "attachments" / digest


def list_deliverables(root):
    """Names only, including build outputs ignored by Git. Never read file contents."""
    result, examined, deadline = [], 0, time.monotonic() + 3
    for folder, dirs, files in os.walk(root, followlinks=False):
        relative = Path(folder).relative_to(root)
        dirs[:] = sorted((d for d in dirs if eligible_path((relative/d).as_posix()) and not (Path(folder)/d).is_symlink()),
                         key=lambda d: (d not in {".workspace", "artifacts", "build", "dist", "reports"}, d))
        for filename in sorted(files):
            examined += 1
            if examined > 20000 or len(result) >= 2000 or time.monotonic() > deadline:
                return {"files": result, "truncated": True}
            name = (relative/filename).as_posix()
            if not eligible_path(name):
                continue
            # Normal sources are already listed in the sanitized snapshot. Reserve
            # this bounded index for binaries and generated outputs, not thousands
            # of source files that would hide an APK near the end of the walk.
            if Path(name).suffix.lower() not in BINARY_SUFFIXES and not set(PurePosixPath(name).parts) & {"artifacts", "build", "dist", "reports"}:
                continue
            try:
                info = (Path(folder)/filename).lstat()
            except OSError:
                continue
            if stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= MAX_ATTACHMENT:
                result.append({"path": name, "bytes": info.st_size})
    return {"files": result, "truncated": False}
