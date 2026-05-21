from __future__ import annotations

import os
from typing import Any, Callable


def ensure_legacy_lock_view(runtime: Any) -> None:
    scoped_locks = runtime.runtime_root / "locks"
    scoped_locks.mkdir(parents=True, exist_ok=True)
    legacy_locks = runtime.runtime_legacy_root / "locks"
    if legacy_locks.is_symlink():
        if legacy_locks.resolve(strict=False) == scoped_locks.resolve(strict=False):
            return
        try:
            legacy_locks.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            return
    if legacy_locks.exists():
        return
    try:
        legacy_locks.symlink_to(scoped_locks, target_is_directory=True)
    except FileExistsError:
        return
    except OSError:
        if os.path.lexists(legacy_locks):
            return
        try:
            legacy_locks.mkdir(parents=True, exist_ok=True)
        except FileExistsError:
            return


def add_emit_listener(runtime: Any, listener: Callable[[str, dict[str, object]], None]) -> Callable[[], None]:
    runtime._emit_listeners.append(listener)

    def remove() -> None:
        try:
            runtime._emit_listeners.remove(listener)
        except ValueError:
            return

    return remove


def reset_project_startup_warnings(runtime: Any) -> None:
    with runtime._startup_warnings_lock:
        runtime._startup_warnings_by_project = {}


def record_project_startup_warning(runtime: Any, project: str, message: str) -> None:
    project_name = str(project).strip()
    warning_text = str(message).strip()
    if not project_name or not warning_text:
        return
    with runtime._startup_warnings_lock:
        runtime._startup_warnings_by_project.setdefault(project_name, []).append(warning_text)


def consume_project_startup_warnings(runtime: Any, project: str) -> list[str]:
    project_name = str(project).strip()
    if not project_name:
        return []
    with runtime._startup_warnings_lock:
        warnings = list(runtime._startup_warnings_by_project.pop(project_name, []))
    return warnings
