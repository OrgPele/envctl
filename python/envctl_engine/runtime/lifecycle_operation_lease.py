from __future__ import annotations

import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from envctl_engine.state.persistence import advisory_file_lock


_OPERATION_OWNER_ATTR = "_lifecycle_operation_owner"
_OPERATION_DEPTH_ATTR = "_lifecycle_operation_depth"
_OPERATION_LEASE_ATTR = "_lifecycle_operation_lease"


class _LifecycleOperationLease:
    def __init__(self, manager: Any) -> None:
        self._manager = manager
        self.released = False

    def release(self) -> None:
        if self.released:
            return
        self.released = True
        self._manager.__exit__(None, None, None)


def run_exclusive_lifecycle_operation(
    runtime: Any,
    *,
    command: str,
    operation: Callable[[], int],
) -> int:
    owner = os.getpid(), threading.get_ident()
    current_owner = getattr(runtime, _OPERATION_OWNER_ATTR, None)
    current_depth = int(getattr(runtime, _OPERATION_DEPTH_ATTR, 0) or 0)
    if current_owner == owner and current_depth > 0:
        setattr(runtime, _OPERATION_DEPTH_ATTR, current_depth + 1)
        try:
            return operation()
        finally:
            if getattr(runtime, _OPERATION_OWNER_ATTR, None) == owner:
                setattr(runtime, _OPERATION_DEPTH_ATTR, current_depth)

    lock_path = _operation_lock_path(runtime)
    manager = advisory_file_lock(lock_path, exclusive=True, timeout_seconds=0.0)
    try:
        manager.__enter__()
    except TimeoutError:
        runtime._emit("lifecycle.operation.busy", command=command, lock_path=str(lock_path))
        print("Another envctl lifecycle operation is already active for this repository.")
        return 1

    lease = _LifecycleOperationLease(manager)
    setattr(runtime, _OPERATION_OWNER_ATTR, owner)
    setattr(runtime, _OPERATION_DEPTH_ATTR, 1)
    setattr(runtime, _OPERATION_LEASE_ATTR, lease)
    try:
        return operation()
    finally:
        if getattr(runtime, _OPERATION_LEASE_ATTR, None) is lease:
            _clear_runtime_lease(runtime)
        lease.release()


def release_lifecycle_operation(runtime: Any) -> bool:
    """Release a committed lifecycle mutation before entering an interactive wait."""

    owner = os.getpid(), threading.get_ident()
    if getattr(runtime, _OPERATION_OWNER_ATTR, None) != owner:
        return False
    lease = getattr(runtime, _OPERATION_LEASE_ATTR, None)
    if not isinstance(lease, _LifecycleOperationLease):
        return False
    _clear_runtime_lease(runtime)
    lease.release()
    return True


def lifecycle_operation_active(runtime: Any) -> bool:
    """Return whether this thread still owns an unreleased lifecycle lease."""

    owner = os.getpid(), threading.get_ident()
    lease = getattr(runtime, _OPERATION_LEASE_ATTR, None)
    return (
        getattr(runtime, _OPERATION_OWNER_ATTR, None) == owner
        and int(getattr(runtime, _OPERATION_DEPTH_ATTR, 0) or 0) > 0
        and isinstance(lease, _LifecycleOperationLease)
        and not lease.released
    )


def _clear_runtime_lease(runtime: Any) -> None:
    setattr(runtime, _OPERATION_DEPTH_ATTR, 0)
    setattr(runtime, _OPERATION_OWNER_ATTR, None)
    setattr(runtime, _OPERATION_LEASE_ATTR, None)


def _operation_lock_path(runtime: Any) -> Path:
    repository = getattr(runtime, "state_repository", None)
    repository_lock_path = getattr(repository, "lifecycle_operation_lock_path", None)
    if callable(repository_lock_path):
        return Path(repository_lock_path())
    root = getattr(repository, "runtime_root", None)
    if root is None:
        root = getattr(runtime, "runtime_root")
    root_path = Path(root).expanduser().absolute()
    if root_path.is_symlink():
        raise RuntimeError(f"runtime_root changed identity or became a symlink: {root_path}")
    return root_path.resolve(strict=False) / ".lifecycle_operation.lock"


__all__ = [
    "lifecycle_operation_active",
    "release_lifecycle_operation",
    "run_exclusive_lifecycle_operation",
]
