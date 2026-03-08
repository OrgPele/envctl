from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
import re
import time
from pathlib import Path
from typing import Iterator

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]


_SENSITIVE_KEY_PATTERN = re.compile(r"(TOKEN|SECRET|PASSWORD|KEY|AUTH|COOKIE|SESSION|PRIVATE)", re.IGNORECASE)
_SENSITIVE_PAIR_PATTERN = re.compile(
    r"(?P<prefix>\b)(?P<key>[A-Za-z0-9_\-]*?(?:TOKEN|SECRET|PASSWORD|KEY|AUTH|COOKIE|SESSION|PRIVATE)[A-Za-z0-9_\-]*)\s*(?P<sep>[:=])\s*(?P<value>[^\s]+)",
    re.IGNORECASE,
)
_URL_CREDENTIALS_PATTERN = re.compile(r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*://)(?P<creds>[^@/\s]+)@")


def hash_value(value: str, salt: str) -> str:
    payload = f"{salt}:{value}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def hash_command(command: str, salt: str) -> tuple[str, int]:
    normalized = command.strip()
    return hash_value(normalized, salt), len(normalized)


def scrub_sensitive_text(text: str) -> str:
    if not text:
        return text
    scrubbed = _URL_CREDENTIALS_PATTERN.sub(r"\g<scheme><redacted>@", text)

    def replace_pair(match: re.Match[str]) -> str:
        key = match.group("key")
        sep = match.group("sep")
        return f"{key}{sep}<redacted>"

    scrubbed = _SENSITIVE_PAIR_PATTERN.sub(replace_pair, scrubbed)
    if _SENSITIVE_KEY_PATTERN.search(scrubbed):
        scrubbed = _SENSITIVE_KEY_PATTERN.sub("<redacted>", scrubbed)
    return scrubbed


@contextmanager
def file_lock(path: Path, *, timeout: float) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fcntl is None:
        yield
        return
    start = time.monotonic()
    handle = path.open("a+", encoding="utf-8")
    try:
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() - start >= timeout:
                    raise TimeoutError(f"Timed out acquiring lock: {path}")
                time.sleep(0.05)
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()
        try:
            if path.exists() and path.stat().st_size == 0:
                path.unlink()
        except OSError:
            pass


def debug_env_value(env: dict[str, str], key: str) -> str | None:
    raw = env.get(key)
    if raw is None:
        raw = os.environ.get(key)
    return raw
