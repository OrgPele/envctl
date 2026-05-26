from __future__ import annotations

from pathlib import Path
from typing import Any


STARTUP_PROGRESS_TOKENS = (
    "Waiting for application startup",
    "Running upgrade",
    "alembic.runtime.migration",
    "db.migrations.startup.start",
    "db.migrations.startup",
)

STARTUP_COMPLETE_TOKENS = (
    "Application startup complete",
    "Uvicorn running on",
    "app.startup.complete",
)

STARTUP_FAILURE_TOKENS = (
    "Traceback",
    "ERROR",
    "Error",
    "Exception",
    "ModuleNotFoundError",
    "ImportError",
    "No module named",
    "Address already in use",
    "address already in use",
)


def command_result_error_text(*, result: object) -> str:
    stderr = str(getattr(result, "stderr", "") or "").strip()
    stdout = str(getattr(result, "stdout", "") or "").strip()
    if stderr:
        return stderr.splitlines()[-1]
    if stdout:
        return stdout.splitlines()[-1]
    return f"exit:{getattr(result, 'returncode', 'unknown')}"


def service_listener_failure_detail(runtime: Any, *, log_path: str | None, pid: int | None) -> str | None:
    parts: list[str] = []
    if isinstance(pid, int) and pid > 0:
        try:
            if not bool(runtime.process_runner.is_pid_running(pid)):
                parts.append(f"process {pid} exited")
        except Exception:  # noqa: BLE001
            pass
    if isinstance(log_path, str) and log_path.strip():
        parts.append(f"log_path: {log_path}")
    progress_hint = tail_log_startup_progress_line(log_path)
    if progress_hint:
        parts.append(f"startup still in progress: {progress_hint}")
        log_hint = None
    else:
        log_hint = tail_log_error_line(log_path)
    if log_hint:
        parts.append(f"log: {log_hint}")
    if not parts:
        return None
    return "; ".join(parts)


def tail_log_error_line(log_path: str | None, *, max_chars: int = 240) -> str | None:
    lines = _tail_candidate_lines(log_path)
    if not lines:
        return None

    priority_tokens = (
        "ModuleNotFoundError",
        "ImportError",
        "Traceback",
        "ERROR",
        "Error",
        "Exception",
        "No module named",
    )
    selected = lines[-1]
    for line in reversed(lines):
        if any(token in line for token in priority_tokens):
            selected = line
            break
    if len(selected) > max_chars:
        return selected[: max_chars - 3] + "..."
    return selected


def tail_log_startup_progress_line(log_path: str | None, *, max_chars: int = 240) -> str | None:
    lines = _tail_candidate_lines(log_path)
    if not lines:
        return None
    for line in reversed(lines):
        if any(token in line for token in STARTUP_FAILURE_TOKENS):
            return None
        if any(token in line for token in STARTUP_COMPLETE_TOKENS):
            return None
        if any(token in line for token in STARTUP_PROGRESS_TOKENS):
            return line[: max_chars - 3] + "..." if len(line) > max_chars else line
    return None


def _tail_candidate_lines(log_path: str | None) -> list[str]:
    if not log_path:
        return []
    path = Path(log_path)
    if not path.is_file():
        return []
    try:
        return [
            line.strip()
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip()
        ]
    except OSError:
        return []
