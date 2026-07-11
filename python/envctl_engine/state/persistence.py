from __future__ import annotations

import fcntl
import errno
import os
import re
import stat
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


_ATOMIC_TEMP_TOKEN = re.compile(r"[a-z0-9_]{8}")


def atomic_write_text(path: Path, text: str) -> None:
    """Replace a UTF-8 text file without exposing a partially written value."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(text)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
        fsync_directory(path.parent)
    except BaseException:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def scavenge_atomic_write_temps(path: Path) -> int:
    """Remove crash leftovers for one exact atomic-write target.

    The caller must already hold the exclusive lock that serializes writes to
    ``path``. Scanning is deliberately target-local: retired runtime history
    can be unbounded, and unrelated ``*.tmp`` files must never be touched.
    Directory and entry symlinks are not followed.
    """

    parent = path.parent
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_fd = os.open(parent, flags)
    removed = 0
    expected_prefix = f".{path.name}."
    try:
        if not stat.S_ISDIR(os.fstat(directory_fd).st_mode):
            raise OSError(f"Atomic-write parent is not a real directory: {parent}")
        with os.scandir(directory_fd) as entries:
            for entry in entries:
                name = entry.name
                if not name.startswith(expected_prefix) or not name.endswith(".tmp"):
                    continue
                token = name[len(expected_prefix) : -len(".tmp")]
                if _ATOMIC_TEMP_TOKEN.fullmatch(token) is None:
                    continue
                try:
                    metadata = entry.stat(follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if not stat.S_ISREG(metadata.st_mode):
                    continue
                try:
                    os.unlink(name, dir_fd=directory_fd)
                except FileNotFoundError:
                    continue
                removed += 1
        if removed:
            fsync_directory(parent)
        return removed
    finally:
        os.close(directory_fd)


def durable_mkdir(path: Path) -> None:
    """Create a directory chain and durably publish every new directory entry."""

    missing: list[Path] = []
    cursor = path
    while not cursor.exists():
        missing.append(cursor)
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    if cursor.is_symlink() or not cursor.is_dir():
        raise OSError(f"Directory ancestor is not a real directory: {cursor}")
    for directory in reversed(missing):
        try:
            directory.mkdir()
        except FileExistsError:
            if directory.is_symlink() or not directory.is_dir():
                raise
        if directory.is_symlink() or not directory.is_dir():
            raise OSError(f"Created path is not a real directory: {directory}")
        fsync_directory(directory)
        fsync_directory(directory.parent)


def require_path_component(value: object, *, label: str) -> str:
    """Return a single portable path component or reject ambiguous traversal input."""

    raw = str(value)
    if (
        not raw
        or raw != raw.strip()
        or raw in {".", ".."}
        or "/" in raw
        or "\\" in raw
        or "\0" in raw
        or Path(raw).is_absolute()
    ):
        raise ValueError(f"{label} must be a non-empty path component")
    return raw


def fsync_directory(path: Path) -> None:
    """Durably publish directory entry changes without following a replaced symlink."""

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_fd = os.open(path, flags)
    try:
        if not stat.S_ISDIR(os.fstat(directory_fd).st_mode):
            raise OSError(f"Path is not a real directory: {path}")
        try:
            os.fsync(directory_fd)
        except OSError as exc:
            if exc.errno not in {errno.EBADF, errno.EINVAL, errno.ENOTSUP, errno.EROFS}:
                raise
    finally:
        os.close(directory_fd)


@contextmanager
def advisory_file_lock(
    path: Path,
    *,
    exclusive: bool,
    timeout_seconds: float | None = None,
) -> Iterator[None]:
    """Hold a process-safe advisory lock backed by a stable lock-file inode."""

    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        lock_file = os.fdopen(descriptor, "a+b")
    except BaseException:
        os.close(descriptor)
        raise
    with lock_file:
        if not stat.S_ISREG(os.fstat(lock_file.fileno()).st_mode):
            raise OSError(f"Lock path is not a regular file: {path}")
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        if timeout_seconds is None:
            fcntl.flock(lock_file.fileno(), operation)
        else:
            deadline = time.monotonic() + max(0.0, timeout_seconds)
            while True:
                try:
                    fcntl.flock(lock_file.fileno(), operation | fcntl.LOCK_NB)
                    break
                except BlockingIOError as exc:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Timed out acquiring lock: {path}") from exc
                    time.sleep(0.01)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


__all__ = [
    "advisory_file_lock",
    "atomic_write_text",
    "durable_mkdir",
    "fsync_directory",
    "require_path_component",
    "scavenge_atomic_write_temps",
]
