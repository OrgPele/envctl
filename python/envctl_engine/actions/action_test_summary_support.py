from __future__ import annotations

from pathlib import Path

from envctl_engine.actions.action_test_summary_artifacts import (
    _project_roots_from_outcomes,
    _project_roots_from_targets,
    new_test_results_run_dir_path,
    persist_test_summary_artifacts,
    persist_test_summary_artifacts_for_orchestrator,
    short_failed_summary_path,
    write_failed_tests_summary,
)
from envctl_engine.actions.action_test_summary_collection import (
    collect_failed_test_manifest_entries,
    collect_failed_tests,
    collect_generic_suite_failures,
    collect_suite_failure_contexts,
    resolve_failed_test_error,
    suite_display_name,
)
from envctl_engine.actions.action_test_summary_display import (
    print_test_suite_overview,
    print_test_suite_overview_for_orchestrator,
)
from envctl_engine.actions.action_test_summary_formatting import (
    captured_output_blocks,
    compact_summary_line,
    exception_body_block,
    exception_context_markers,
    format_summary_error_lines,
    is_captured_output_header,
    is_exception_context_marker,
    is_exception_start,
    is_user_code_frame,
    looks_like_terminal_chrome,
    structured_summary_lines,
    user_code_frame_blocks,
)
from envctl_engine.actions.action_test_summary_git import default_git_state_components


def write_failed_tests_summary_for_orchestrator(
    orchestrator: object,
    *,
    run_dir: Path,
    project_name: str,
    project_root: Path,
    outcomes: list[dict[str, object]],
    previous_entry: dict[str, object] | None = None,
) -> dict[str, object]:
    return write_failed_tests_summary(
        run_dir=run_dir,
        project_name=project_name,
        project_root=project_root,
        outcomes=outcomes,
        previous_entry=previous_entry,
        short_failed_summary_path=short_failed_summary_path,
        format_summary_error_lines=format_summary_error_lines,
        git_state_components=default_git_state_components,
    )


__all__ = [
    "_project_roots_from_outcomes",
    "_project_roots_from_targets",
    "captured_output_blocks",
    "collect_failed_test_manifest_entries",
    "collect_failed_tests",
    "collect_generic_suite_failures",
    "collect_suite_failure_contexts",
    "compact_summary_line",
    "default_git_state_components",
    "exception_body_block",
    "exception_context_markers",
    "format_summary_error_lines",
    "is_captured_output_header",
    "is_exception_context_marker",
    "is_exception_start",
    "is_user_code_frame",
    "looks_like_terminal_chrome",
    "new_test_results_run_dir_path",
    "persist_test_summary_artifacts",
    "persist_test_summary_artifacts_for_orchestrator",
    "print_test_suite_overview",
    "print_test_suite_overview_for_orchestrator",
    "resolve_failed_test_error",
    "short_failed_summary_path",
    "structured_summary_lines",
    "suite_display_name",
    "user_code_frame_blocks",
    "write_failed_tests_summary",
    "write_failed_tests_summary_for_orchestrator",
]
