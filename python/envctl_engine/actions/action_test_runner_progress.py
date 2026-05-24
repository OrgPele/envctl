from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import threading
from typing import Any, Callable

__all__ = [
    "ParallelTestProgressTracker",
    "format_live_collection_status",
    "format_live_progress_status",
    "format_live_progress_status_with_counts",
    "format_live_progress_status_without_total",
    "live_failed_count",
]


def live_failed_count(parsed: object | None) -> int:
    if parsed is None:
        return 0
    failed = int(getattr(parsed, "failed", 0) or 0)
    errors = int(getattr(parsed, "errors", 0) or 0)
    failed_tests = len(getattr(parsed, "failed_tests", ()) or ())
    return max(failed + errors, failed_tests + errors)


def format_live_progress_status(label: str, current: int, total: int) -> str:
    return f"Running {label}... {current}/{total} tests complete"


def format_live_progress_status_without_total(label: str, current: int, *, parsed: object | None) -> str:
    failed = min(max(live_failed_count(parsed), 0), max(current, 0))
    passed = max(0, int(current) - failed)
    return f"Running {label}... {current} tests complete • {passed} passed, {failed} failed"


def format_live_collection_status(label: str, discovered: int) -> str:
    return f"Collecting {label} tests... {discovered} discovered"


def format_live_progress_status_with_counts(label: str, current: int, total: int, *, parsed: object | None) -> str:
    failed = min(max(live_failed_count(parsed), 0), max(current, 0))
    passed = max(0, int(current) - failed)
    return f"{format_live_progress_status(label, current, total)} • {passed} passed, {failed} failed"


def _render_labels(labels: list[str], *, max_items: int) -> str:
    if not labels:
        return "-"
    visible = labels[:max_items]
    if len(labels) > max_items:
        visible.append(f"+{len(labels) - max_items} more")
    return ", ".join(visible)


@dataclass
class ParallelTestProgressTracker:
    __test__ = False

    enabled: bool
    total_suites: int
    max_workers: int
    multi_project: bool
    failed_only: bool
    emit_status_callback: Callable[[str], None] | None = field(default=None, repr=False)
    suite_display_name: Callable[[str, bool], str] | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _queued: int = field(init=False)
    _running: int = field(default=0, init=False)
    _finished: int = field(default=0, init=False)
    _running_labels: set[str] = field(default_factory=set, init=False)
    _done_labels: deque[str] = field(default_factory=lambda: deque(maxlen=4), init=False)

    def __init__(
        self,
        *,
        enabled: bool,
        total_suites: int,
        max_workers: int,
        multi_project: bool,
        failed_only: bool,
        emit_status: Callable[[str], None],
        suite_display_name: Callable[..., str],
    ) -> None:
        self.enabled = bool(enabled)
        self.total_suites = int(total_suites)
        self.max_workers = int(max_workers)
        self.multi_project = bool(multi_project)
        self.failed_only = bool(failed_only)
        self.emit_status_callback = emit_status
        self.suite_display_name = suite_display_name
        self._lock = threading.Lock()
        self._queued = int(total_suites)
        self._running = 0
        self._finished = 0
        self._running_labels = set()
        self._done_labels = deque(maxlen=4)

    def mark_running(self, execution: Any) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._queued = max(0, self._queued - 1)
            self._running += 1
            self._running_labels.add(self._descriptor(execution))
            self._emit_status_locked(phase="running", execution=execution)

    def mark_finished(self, execution: Any, *, success: bool) -> None:
        if not self.enabled:
            return
        with self._lock:
            descriptor = self._descriptor(execution)
            self._running = max(0, self._running - 1)
            self._finished += 1
            self._running_labels.discard(descriptor)
            done_status = "PASS" if success else "FAIL"
            self._done_labels.append(f"{descriptor} ({done_status})")
            self._queued = max(0, self.total_suites - self._running - self._finished)
            self._emit_status_locked(phase="completed", execution=execution)

    def emit_status(self, *, phase: str, execution: Any | None = None) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._emit_status_locked(phase=phase, execution=execution)

    def _emit_status_locked(self, *, phase: str, execution: Any | None = None) -> None:
        emit_status = self.emit_status_callback
        if not callable(emit_status):
            return
        prefix = (
            f"Tests progress: running {self._running}/{self.max_workers}, "
            f"finished {self._finished}/{self.total_suites}, "
            f"queued {self._queued}"
        )
        running_labels_sorted = sorted(str(label) for label in self._running_labels)
        done_labels_list = [str(label) for label in self._done_labels]
        details = (
            f" • running: {_render_labels(running_labels_sorted, max_items=3)}"
            f" • done: {_render_labels(done_labels_list, max_items=3)}"
        )
        if execution is None:
            emit_status(f"{prefix}{details}")
            return
        emit_status(f"{prefix} • {phase}: {self._descriptor(execution)}{details}")

    def _descriptor(self, execution: Any) -> str:
        source = str(getattr(execution.spec, "source", ""))
        resolver = self.suite_display_name
        if callable(resolver):
            suite_label = str(resolver(source, failed_only=self.failed_only))
        else:
            suite_label = source
        project_name = str(getattr(execution, "project_name", ""))
        return f"{project_name} / {suite_label}" if self.multi_project else suite_label
