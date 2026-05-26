from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from envctl_engine.actions.action_test_runner_failures import (
    format_failure_output_for_artifact,
    summarize_failure_output,
)


@dataclass(slots=True)
class TestSuiteOutcomeRecorder:
    __test__: ClassVar[bool] = False

    failed_only: bool
    outcomes: list[dict[str, object]] = field(default_factory=list)

    def record(
        self,
        execution: Any,
        *,
        command: list[str],
        completed: Any,
        parsed: Any,
        duration_ms: float,
    ) -> None:
        failed = int(getattr(completed, "returncode", 1)) != 0
        self.outcomes.append(
            {
                "suite": execution.spec.source,
                "index": execution.index,
                "project_name": execution.project_name,
                "project_root": str(execution.project_root),
                "command": command,
                "cwd": str(execution.spec.cwd),
                "returncode": completed.returncode,
                "duration_ms": duration_ms,
                "parsed": parsed,
                "failed_only": self.failed_only,
                "failure_summary": self._failure_summary(completed) if failed else "",
                "failure_details": self._failure_details(completed) if failed else "",
            }
        )

    @staticmethod
    def _failure_summary(completed: Any) -> str:
        return summarize_failure_output(
            stdout=getattr(completed, "stdout", ""),
            stderr=getattr(completed, "stderr", ""),
            returncode=int(getattr(completed, "returncode", 1)),
        )

    @staticmethod
    def _failure_details(completed: Any) -> str:
        return format_failure_output_for_artifact(
            stdout=getattr(completed, "stdout", ""),
            stderr=getattr(completed, "stderr", ""),
            returncode=int(getattr(completed, "returncode", 1)),
        )


def test_failure_summary(completed: Any) -> str:
    return TestSuiteOutcomeRecorder._failure_summary(completed)
