from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar


@dataclass(frozen=True, slots=True)
class TestSuiteEventEmitter:
    __test__: ClassVar[bool] = False

    runtime: Any
    total: int

    def emit_start(self, execution: Any, *, command: list[str]) -> None:
        self.runtime._emit(  # type: ignore[attr-defined]
            "test.suite.start",
            suite=execution.spec.source,
            index=execution.index,
            total=self.total,
            command=command,
            cwd=str(execution.spec.cwd),
            project=execution.project_name,
            project_root=str(execution.project_root),
        )

    def emit_summary(self, execution: Any, *, parsed: Any) -> None:
        counts_detected = bool(getattr(parsed, "counts_detected", False))
        self.runtime._emit(  # type: ignore[attr-defined]
            "test.suite.summary",
            suite=execution.spec.source,
            index=execution.index,
            total=self.total,
            project=execution.project_name,
            project_root=str(execution.project_root),
            counts_detected=counts_detected,
            passed=(parsed.passed if counts_detected else None),
            failed=(parsed.failed if counts_detected else None),
            skipped=(parsed.skipped if counts_detected else None),
            errors=(parsed.errors if counts_detected else None),
            total_tests=(parsed.total if counts_detected else None),
        )

    def emit_finish(self, execution: Any, *, command: list[str], completed: Any, duration_ms: float) -> None:
        self.runtime._emit(  # type: ignore[attr-defined]
            "test.suite.finish",
            suite=execution.spec.source,
            index=execution.index,
            total=self.total,
            command=command,
            cwd=str(execution.spec.cwd),
            returncode=completed.returncode,
            duration_ms=duration_ms,
            project=execution.project_name,
            project_root=str(execution.project_root),
        )


def suite_cwd(execution: Any) -> Path:
    return Path(execution.spec.cwd)
