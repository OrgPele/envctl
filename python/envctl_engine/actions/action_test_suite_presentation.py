from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any, ClassVar, Sequence

from envctl_engine.test_output.symbols import format_duration
from envctl_engine.ui.path_links import render_path_for_terminal


def render_command(command: list[str]) -> str:
    return " ".join(str(part) for part in command)


@dataclass(slots=True)
class TestSuitePresenter:
    __test__: ClassVar[bool] = False

    orchestrator: Any
    execution_specs: Sequence[Any]
    failed_only: bool
    interactive_command: bool
    parallel: bool
    multi_project: bool
    use_suite_spinner_group: bool
    progress_tracker: Any
    suite_spinner_group: Any
    events: Any

    def failure_label(self, execution: Any) -> str:
        return f"{execution.project_name}:{execution.spec.source} [{execution.index}/{len(self.execution_specs)}]"

    def announce_suite_start(self, execution: Any, *, suite_label: str, resolved_source: str) -> None:
        index = execution.index
        spec = execution.spec
        project_name = execution.project_name
        status = self.orchestrator._test_execution_status(
            spec.command,
            args=execution.args,
            source=resolved_source,
            cwd=spec.cwd,
        )
        if self.multi_project:
            status = f"{project_name}: {status}"
        status += f" [{index}/{len(self.execution_specs)}]" if len(self.execution_specs) > 1 else ""
        if not self.use_suite_spinner_group:
            self.orchestrator._emit_status(status)
        if self.interactive_command:
            started_label = f"{project_name} / {suite_label}" if self.multi_project else suite_label
            if not self.use_suite_spinner_group:
                index_text = self.orchestrator._colorize(f"[{index}/{len(self.execution_specs)}]", fg="yellow")
                suite_text = self.orchestrator._colorize(started_label, fg="cyan", bold=True)
                state_text = self.orchestrator._colorize("started", fg="blue")
                print(f"  - {index_text} {suite_text} {state_text}")
                command_text = self.orchestrator._colorize(
                    render_command([*spec.command, *execution.args]), fg="gray"
                )
                cwd_text = self.orchestrator._colorize(
                    render_path_for_terminal(
                        str(Path(spec.cwd).resolve()),
                        env=getattr(self.orchestrator.runtime, "env", {}),
                        stream=sys.stdout,
                    ),
                    fg="gray",
                )
                print(f"      command: {command_text}")
                print(f"      cwd: {cwd_text}")

    def emit_suite_summary(self, execution: Any, parsed: Any) -> None:
        if parsed is None:
            return
        counts_detected = bool(getattr(parsed, "counts_detected", False))
        if not (self.interactive_command and self.parallel and self.multi_project):
            if counts_detected:
                self.orchestrator._emit_status(
                    f"{execution.project_name} / {execution.spec.source} summary: "
                    f"{parsed.passed} passed, {parsed.failed} failed, {parsed.skipped} skipped"
                )
            else:
                self.orchestrator._emit_status(
                    f"{execution.project_name} / {execution.spec.source} summary: no parsed test counts"
                )
        self.events.emit_summary(execution, parsed=parsed)

    def print_interactive_suite_finish(
        self,
        execution: Any,
        *,
        suite_label: str,
        completed: Any,
        parsed: Any,
        duration_ms: float,
    ) -> None:
        if not (self.interactive_command and not self.use_suite_spinner_group):
            return
        suite_status = "passed" if completed.returncode == 0 else "failed"
        finished_label = f"{execution.project_name} / {suite_label}" if self.multi_project else suite_label
        counts_suffix = ""
        counts_detected = bool(getattr(parsed, "counts_detected", False)) if parsed is not None else False
        if parsed is not None and counts_detected:
            counts_suffix = f" • {parsed.passed} passed, {parsed.failed} failed, {parsed.skipped} skipped"
        icon = (
            self.orchestrator._colorize("✓", fg="green", bold=True)
            if completed.returncode == 0
            else self.orchestrator._colorize("✗", fg="red", bold=True)
        )
        index_text = self.orchestrator._colorize(f"[{execution.index}/{len(self.execution_specs)}]", fg="yellow")
        suite_text = self.orchestrator._colorize(finished_label, fg="cyan", bold=True)
        status_text = self.orchestrator._colorize(
            suite_status,
            fg=("green" if completed.returncode == 0 else "red"),
            bold=True,
        )
        print(
            f"  - {icon} {index_text} {suite_text} {status_text} "
            f"({format_duration(duration_ms / 1000.0)}){counts_suffix}"
        )
        if completed.returncode == 0 and parsed is not None and not counts_detected:
            print("      note: test command completed, but envctl could not extract test counts from the output.")

    def mark_finished(self, execution: Any, *, completed: Any, parsed: Any, duration_ms: float) -> None:
        if self.use_suite_spinner_group:
            self.suite_spinner_group.mark_finished(
                execution,
                success=completed.returncode == 0,
                duration_text=format_duration(max(duration_ms / 1000.0, 0.0)),
                parsed=parsed,
            )
        else:
            self.progress_tracker.mark_finished(execution, success=completed.returncode == 0)
