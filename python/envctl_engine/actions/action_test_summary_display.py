from __future__ import annotations

from typing import Callable
import sys

from typing import Protocol

from envctl_engine.actions.action_test_summary_collection import summary_float, summary_int, suite_display_name
from envctl_engine.test_output.symbols import format_duration
from envctl_engine.ui.path_links import render_path_for_terminal


def print_test_suite_overview(
    outcomes: list[dict[str, object]],
    *,
    summary_metadata: dict[str, dict[str, object]] | None = None,
    env: dict[str, str] | None = None,
    colorize: Callable[..., str],
) -> None:
    if not outcomes:
        return
    print("")
    print(colorize("======================================================================", fg="cyan"))
    print(colorize("Test Suite Summary", fg="cyan", bold=True))
    print(colorize("======================================================================", fg="cyan"))
    project_labels = {
        str(item.get("project_name", "")).strip() for item in outcomes if str(item.get("project_name", "")).strip()
    }
    multi_project = len(project_labels) > 1
    total_passed = 0
    total_failed = 0
    total_skipped = 0
    total_known = 0
    total_duration = 0.0
    grouped_outcomes: dict[str, list[dict[str, object]]] = {}
    for item in sorted(
        outcomes,
        key=lambda value: (
            str(value.get("project_name", "")).lower(),
            summary_int(value.get("index")),
        ),
    ):
        project_name = str(item.get("project_name", "")).strip() or "Main"
        grouped_outcomes.setdefault(project_name, []).append(item)

    for project_name, project_items in grouped_outcomes.items():
        if multi_project:
            print(colorize(project_name, fg="blue", bold=True))
        for item in project_items:
            source = str(item.get("suite", "suite"))
            label = suite_display_name(source, failed_only=bool(item.get("failed_only", False)))
            label_rendered = colorize(label, fg="cyan", bold=True)
            if multi_project:
                label_rendered = f"  {label_rendered}"
            returncode = summary_int(item.get("returncode"), default=1)
            parsed = item.get("parsed")
            parsed_total = summary_int(getattr(parsed, "total", 0)) if parsed is not None else 0
            counts_detected = bool(getattr(parsed, "counts_detected", False)) if parsed is not None else False
            passed = summary_int(getattr(parsed, "passed", 0)) if parsed is not None else 0
            failed = summary_int(getattr(parsed, "failed", 0)) if parsed is not None else 0
            skipped = summary_int(getattr(parsed, "skipped", 0)) if parsed is not None else 0
            duration_ms = summary_float(item.get("duration_ms"))
            duration_text = format_duration(max(duration_ms / 1000.0, 0.0))

            icon = colorize("✓", fg="green", bold=True) if returncode == 0 else colorize("✗", fg="red", bold=True)
            if counts_detected:
                total_passed += passed
                total_failed += failed
                total_skipped += skipped
                total_known += parsed_total
                total_duration += max(duration_ms / 1000.0, 0.0)
                passed_text = colorize(f"{passed} passed", fg="green")
                failed_text = colorize(f"{failed} failed", fg="red")
                skipped_text = colorize(f"{skipped} skipped", fg="yellow")
                print(
                    f"{icon} {label_rendered}: {passed_text}, {failed_text}, {skipped_text}"
                    f" (total {parsed_total}, duration {duration_text})"
                )
            else:
                total_duration += max(duration_ms / 1000.0, 0.0)
                if returncode == 0:
                    print(
                        f"{icon} {label_rendered}: "
                        f"{colorize('completed', fg='green', bold=True)} "
                        f"(no parsed test counts, duration {duration_text})"
                    )
                else:
                    print(
                        f"{icon} {label_rendered}: "
                        f"{colorize('failed', fg='red', bold=True)} "
                        f"(no parsed test counts, duration {duration_text})"
                    )
        summary_entry = summary_metadata.get(project_name) if isinstance(summary_metadata, dict) else None
        if isinstance(summary_entry, dict) and str(summary_entry.get("status", "")).strip().lower() == "failed":
            summary_path = str(
                summary_entry.get("short_summary_path") or summary_entry.get("summary_path") or ""
            ).strip()
            if summary_path:
                prefix = "  " if multi_project else ""
                label = colorize("failure summary:", fg="gray")
                print(f"{prefix}{label}")
                summary_env = dict(env or {})
                hyperlink_mode = str(summary_env.get("ENVCTL_UI_HYPERLINK_MODE", "")).strip().lower()
                if hyperlink_mode not in {"off", "false", "no", "0"}:
                    summary_env["ENVCTL_UI_HYPERLINK_MODE"] = "on"
                rendered_path = render_path_for_terminal(summary_path, env=summary_env, stream=sys.stdout)
                print(f"{prefix}{rendered_path}")
        if multi_project:
            print("")

    if total_known > 0:
        overall_prefix = colorize("Overall:", fg="cyan", bold=True)
        overall_passed = colorize(f"{total_passed} passed", fg="green")
        overall_failed = colorize(f"{total_failed} failed", fg="red")
        overall_skipped = colorize(f"{total_skipped} skipped", fg="yellow")
        print(
            f"{overall_prefix} {overall_passed}, {overall_failed}, {overall_skipped}"
            f" (total {total_known}, duration {format_duration(total_duration)})"
        )
    print(colorize("======================================================================", fg="cyan"))


class TestSuiteOverviewOrchestrator(Protocol):
    @property
    def runtime(self) -> object: ...

    def _colorize(self, text: str, **kwargs: object) -> str: ...


def print_test_suite_overview_for_orchestrator(
    orchestrator: TestSuiteOverviewOrchestrator,
    outcomes: list[dict[str, object]],
    *,
    summary_metadata: dict[str, dict[str, object]] | None = None,
) -> None:
    print_test_suite_overview(
        outcomes,
        summary_metadata=summary_metadata,
        env=dict(getattr(orchestrator.runtime, "env", {})),
        colorize=orchestrator._colorize,
    )
