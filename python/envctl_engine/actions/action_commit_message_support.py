from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
from typing import Any

from envctl_engine.actions.action_pr_message_support import normalize_text_block, read_text


COMMIT_MESSAGE_MAX_CHARS = 16_000
ENVCTL_COMMIT_LEDGER_NAME = ".envctl-commit-message.md"
ENVCTL_COMMIT_POINTER_MARKER = "### Envctl pointer ###"


@dataclass(frozen=True, slots=True)
class CommitMessageResolution:
    commit_message: str = ""
    message_file: str = ""
    error: str | None = None
    ledger_path: Path | None = None

    def as_legacy_tuple(self) -> tuple[str, str, str | None, Path | None]:
        return self.commit_message, self.message_file, self.error, self.ledger_path


def resolve_commit_message_request(context: Any) -> CommitMessageResolution:
    commit_message = str(context.env.get("ENVCTL_COMMIT_MESSAGE", "")).strip()
    commit_message_file = str(context.env.get("ENVCTL_COMMIT_MESSAGE_FILE", "")).strip()
    if commit_message:
        return CommitMessageResolution(commit_message=commit_message)
    if commit_message_file:
        path = Path(commit_message_file)
        if path.is_file() and file_has_text(path):
            return CommitMessageResolution(message_file=str(path))
        return CommitMessageResolution(error=f"Commit message file is missing or empty: {commit_message_file}")

    ledger_path = context.project_root / ENVCTL_COMMIT_LEDGER_NAME
    payload, error = read_commit_ledger_segment(ledger_path)
    if error:
        return CommitMessageResolution(error=error, ledger_path=ledger_path)
    return CommitMessageResolution(message_file=str(write_commit_message_file(payload)), ledger_path=ledger_path)


def resolve_commit_message(context: Any, *, branch: str) -> tuple[str, str, str | None, Path | None]:
    del branch
    return resolve_commit_message_request(context).as_legacy_tuple()


def read_commit_ledger_segment(path: Path) -> tuple[str, str | None]:
    if not path.exists():
        atomic_write(path, f"# Envctl Commit Log\n\n{ENVCTL_COMMIT_POINTER_MARKER}\n")

    text = read_text(path)
    marker_count = text.count(ENVCTL_COMMIT_POINTER_MARKER)
    if marker_count == 0:
        payload = normalize_text_block(text)
        if not payload:
            return "", (
                f"Envctl commit log is empty in {path}. Provide --commit-message, "
                f"--commit-message-file, or append a new summary to {path}."
            )
        return _trim_commit_message(payload), None
    if marker_count > 1:
        return "", f"Envctl commit log is malformed: {path} contains multiple pointer markers."

    _before, after = text.split(ENVCTL_COMMIT_POINTER_MARKER, 1)
    payload = normalize_text_block(after)
    if not payload:
        return "", (
            f"Envctl commit log is empty after the pointer in {path}. Provide --commit-message, "
            f"--commit-message-file, or append a new summary to {path}."
        )
    return _trim_commit_message(payload), None


def advance_commit_ledger_pointer(path: Path) -> str | None:
    if not path.exists():
        return f"Envctl commit log disappeared before pointer advance: {path}"
    text = read_text(path)
    marker_count = text.count(ENVCTL_COMMIT_POINTER_MARKER)
    if marker_count == 0:
        archived = normalize_text_block(text)
        updated = f"{archived}\n\n{ENVCTL_COMMIT_POINTER_MARKER}\n" if archived else f"{ENVCTL_COMMIT_POINTER_MARKER}\n"
        try:
            atomic_write(path, updated)
        except OSError as exc:
            return f"Failed to advance envctl commit log pointer in {path}: {exc}"
        return None
    if marker_count > 1:
        return f"Envctl commit log is malformed during pointer advance: {path} contains multiple pointer markers."
    before, after = text.split(ENVCTL_COMMIT_POINTER_MARKER, 1)
    archived_before = normalize_text_block(before)
    payload = normalize_text_block(after)
    parts = [part for part in (archived_before, payload) if part]
    archived = "\n\n".join(parts).strip()
    updated = f"{archived}\n\n{ENVCTL_COMMIT_POINTER_MARKER}\n" if archived else f"{ENVCTL_COMMIT_POINTER_MARKER}\n"
    try:
        atomic_write(path, updated)
    except OSError as exc:
        return f"Failed to advance envctl commit log pointer in {path}: {exc}"
    return None


def write_commit_message_file(message: str) -> Path:
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        delete=False,
        suffix=".envctl-commit-message.txt",
    ) as handle:
        handle.write(message)
        return Path(handle.name)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        Path(temp_name).replace(path)
    finally:
        try:
            if Path(temp_name).exists():
                Path(temp_name).unlink()
        except OSError:
            pass


def file_has_text(path: Path) -> bool:
    try:
        return bool(path.read_text(encoding="utf-8").strip())
    except OSError:
        return False


def _trim_commit_message(message: str) -> str:
    return message[:COMMIT_MESSAGE_MAX_CHARS].rstrip() or message


__all__ = [
    "COMMIT_MESSAGE_MAX_CHARS",
    "CommitMessageResolution",
    "ENVCTL_COMMIT_LEDGER_NAME",
    "ENVCTL_COMMIT_POINTER_MARKER",
    "advance_commit_ledger_pointer",
    "atomic_write",
    "file_has_text",
    "read_commit_ledger_segment",
    "resolve_commit_message",
    "resolve_commit_message_request",
    "write_commit_message_file",
]
