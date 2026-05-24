from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time
from typing import Any, Callable

__all__ = ["TestSuiteInterruptRegistry"]


@dataclass
class TestSuiteInterruptRegistry:
    __test__ = False

    runtime: Any
    emit_status: Callable[[str], None]
    execution_mode: str
    monotonic_fn: Callable[[], float] = time.monotonic
    sleep_fn: Callable[[float], None] = time.sleep
    interrupt_received: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _active_suites: dict[int, dict[str, object]] = field(default_factory=dict, init=False)
    _termination_results: dict[int, bool] = field(default_factory=dict, init=False)

    @property
    def active_suite_count(self) -> int:
        with self._lock:
            return len(self._active_suites)

    def clear_by_index(self, suite_index: int, *, pid: int | None = None) -> None:
        with self._lock:
            current = self._active_suites.get(suite_index)
            if not isinstance(current, dict):
                return
            current_pid = int(current.get("pid", 0) or 0)
            if pid is not None and current_pid != int(pid):
                return
            self._active_suites.pop(suite_index, None)

    def terminate_pid(self, pid: int) -> bool:
        if pid <= 0:
            return True
        with self._lock:
            if pid in self._termination_results:
                return self._termination_results[pid]

        process_runner = getattr(self.runtime, "process_runner", None)
        terminator = getattr(process_runner, "terminate_process_group", None)
        if not callable(terminator):
            terminator = getattr(process_runner, "terminate", None)

        result = False
        if callable(terminator):
            result = bool(terminator(pid, term_timeout=2.0, kill_timeout=1.0))

        with self._lock:
            self._termination_results[pid] = result
        return result

    def register_started_suite(self, execution: Any, pid: int) -> None:
        normalized_pid = int(pid or 0)
        if normalized_pid <= 0:
            return
        suite_index = int(getattr(execution, "index", 0) or 0)
        suite_entry = {
            "index": suite_index,
            "suite": str(getattr(execution.spec, "source", "")),
            "project_name": str(getattr(execution, "project_name", "")),
            "pid": normalized_pid,
        }
        with self._lock:
            self._active_suites[suite_index] = suite_entry
        if self.interrupt_received and self.terminate_pid(normalized_pid):
            self.clear_by_index(suite_index, pid=normalized_pid)

    def cleanup_interrupted_suites(self, *, queued_cancelled: int) -> None:
        self.interrupt_received = True
        cleanup_started = self.monotonic_fn()
        self.emit_status("Interrupt received, stopping active test suites...")
        with self._lock:
            active_snapshot = [dict(entry) for entry in self._active_suites.values()]

        self.runtime._emit(
            "test.interrupt.received",
            active_suites=len(active_snapshot),
            queued_cancelled=queued_cancelled,
            mode=self.execution_mode,
        )

        signaled_pids: set[int] = set()
        survivors: set[int] = set()
        for pass_index in range(2):
            if pass_index > 0:
                self.sleep_fn(0.05)
            with self._lock:
                pending_entries = [dict(entry) for entry in self._active_suites.values()]
            for entry in pending_entries:
                pid = int(entry.get("pid", 0) or 0)
                if pid <= 0 or pid in signaled_pids:
                    continue
                signaled_pids.add(pid)
                if self.terminate_pid(pid):
                    self.clear_by_index(int(entry.get("index", 0) or 0), pid=pid)
                else:
                    survivors.add(pid)

        with self._lock:
            for entry in self._active_suites.values():
                pid = int(entry.get("pid", 0) or 0)
                if pid > 0:
                    survivors.add(pid)

        self.runtime._emit(
            "test.interrupt.cleanup",
            active_suites=len(active_snapshot),
            queued_cancelled=queued_cancelled,
            signaled_pids=sorted(signaled_pids),
            survivors=len(survivors),
            cleanup_duration_ms=round((self.monotonic_fn() - cleanup_started) * 1000.0, 1),
        )
