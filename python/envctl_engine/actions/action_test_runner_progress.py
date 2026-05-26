from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import threading
from typing import Any, Callable

__all__ = [
    "LiveTestProgressReporter",
    "ParallelTestProgressCallbacks",
    "ParallelTestProgressConfig",
    "ParallelTestProgressState",
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


def _spinner_counts_text(current: int, total: int | None, *, parsed: object | None) -> str:
    failed = min(max(live_failed_count(parsed), 0), max(int(current), 0))
    passed = max(0, int(current) - failed)
    if total is None:
        return f"{int(current)} complete • {passed} passed, {failed} failed"
    return f"{int(current)}/{int(total)} complete • {passed} passed, {failed} failed"


@dataclass
class LiveTestProgressReporter:
    __test__ = False

    label: str
    emit_status: Callable[[str], None]
    parsed_provider: Callable[[], object | None]
    spinner_progress: Callable[[str], None] | None = None
    _last_snapshot: tuple[object, ...] | None = None
    _current: int | None = None
    _total: int | None = None
    _running_started: bool = False

    def emit(self, current: int, total: int) -> None:
        merged_current = self._current
        merged_total = self._total

        if current < 0:
            if self._running_started:
                return
            snapshot = ("collecting", total)
            if self._last_snapshot == snapshot:
                return
            self._last_snapshot = snapshot
            self._total = total
            self.emit_status(format_live_collection_status(self.label, total))
            self._emit_spinner_progress(f"{total} discovered")
            return

        self._running_started = True
        if total <= 0:
            merged_current = max(int(merged_current or 0), int(current))
            self._current = merged_current
            snapshot = ("running", merged_current, 0)
            if self._last_snapshot == snapshot:
                return
            self._last_snapshot = snapshot
            parsed = self.parsed_provider()
            self.emit_status(format_live_progress_status_without_total(self.label, int(merged_current), parsed=parsed))
            self._emit_spinner_progress(_spinner_counts_text(int(merged_current), None, parsed=parsed))
            return

        if int(current) == 0 and merged_current is not None and int(merged_current) > 0:
            merged_total = int(total)
            self._total = merged_total
            snapshot = ("running", int(merged_current), merged_total)
            if self._last_snapshot == snapshot:
                return
            self._last_snapshot = snapshot
            parsed = self.parsed_provider()
            self.emit_status(
                format_live_progress_status_with_counts(
                    self.label,
                    int(merged_current),
                    merged_total,
                    parsed=parsed,
                )
            )
            self._emit_spinner_progress(_spinner_counts_text(int(merged_current), merged_total, parsed=parsed))
            return

        merged_current = max(int(merged_current or 0), int(current))
        merged_total = int(total)
        self._current = merged_current
        self._total = merged_total
        snapshot = ("running", merged_current, merged_total)
        if self._last_snapshot == snapshot:
            return
        self._last_snapshot = snapshot
        parsed = self.parsed_provider()
        self.emit_status(
            format_live_progress_status_with_counts(
                self.label,
                merged_current,
                merged_total,
                parsed=parsed,
            )
        )
        self._emit_spinner_progress(_spinner_counts_text(merged_current, merged_total, parsed=parsed))

    def _emit_spinner_progress(self, status_text: str) -> None:
        if callable(self.spinner_progress):
            self.spinner_progress(status_text)


@dataclass
class ParallelTestProgressConfig:
    enabled: bool
    total_suites: int
    max_workers: int
    multi_project: bool
    failed_only: bool


@dataclass
class ParallelTestProgressCallbacks:
    emit_status_callback: Callable[[str], None] | None = field(default=None, repr=False)
    suite_display_name: Callable[..., str] | None = field(default=None, repr=False)


@dataclass
class ParallelTestProgressState:
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _queued: int = 0
    _running: int = field(default=0, init=False)
    _finished: int = field(default=0, init=False)
    _running_labels: set[str] = field(default_factory=set, init=False)
    _done_labels: deque[str] = field(default_factory=lambda: deque(maxlen=4), init=False)


@dataclass(init=False)
class ParallelTestProgressTracker:
    __test__ = False

    config: ParallelTestProgressConfig
    callbacks: ParallelTestProgressCallbacks
    state: ParallelTestProgressState

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
        self.config = ParallelTestProgressConfig(
            enabled=bool(enabled),
            total_suites=int(total_suites),
            max_workers=int(max_workers),
            multi_project=bool(multi_project),
            failed_only=bool(failed_only),
        )
        self.callbacks = ParallelTestProgressCallbacks(
            emit_status_callback=emit_status,
            suite_display_name=suite_display_name,
        )
        self.state = ParallelTestProgressState(_queued=int(total_suites))

    def mark_running(self, execution: Any) -> None:
        if not self.config.enabled:
            return
        with self.state._lock:
            self.state._queued = max(0, self.state._queued - 1)
            self.state._running += 1
            self.state._running_labels.add(self._descriptor(execution))
            self._emit_status_locked(phase="running", execution=execution)

    def mark_finished(self, execution: Any, *, success: bool) -> None:
        if not self.config.enabled:
            return
        with self.state._lock:
            descriptor = self._descriptor(execution)
            self.state._running = max(0, self.state._running - 1)
            self.state._finished += 1
            self.state._running_labels.discard(descriptor)
            done_status = "PASS" if success else "FAIL"
            self.state._done_labels.append(f"{descriptor} ({done_status})")
            self.state._queued = max(
                0,
                self.config.total_suites - self.state._running - self.state._finished,
            )
            self._emit_status_locked(phase="completed", execution=execution)

    def emit_status(self, *, phase: str, execution: Any | None = None) -> None:
        if not self.config.enabled:
            return
        with self.state._lock:
            self._emit_status_locked(phase=phase, execution=execution)

    def _emit_status_locked(self, *, phase: str, execution: Any | None = None) -> None:
        emit_status = self.callbacks.emit_status_callback
        if not callable(emit_status):
            return
        prefix = (
            f"Tests progress: running {self.state._running}/{self.config.max_workers}, "
            f"finished {self.state._finished}/{self.config.total_suites}, "
            f"queued {self.state._queued}"
        )
        running_labels_sorted = sorted(str(label) for label in self.state._running_labels)
        done_labels_list = [str(label) for label in self.state._done_labels]
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
        resolver = self.callbacks.suite_display_name
        if callable(resolver):
            suite_label = str(resolver(source, failed_only=self.config.failed_only))
        else:
            suite_label = source
        project_name = str(getattr(execution, "project_name", ""))
        return f"{project_name} / {suite_label}" if self.config.multi_project else suite_label
