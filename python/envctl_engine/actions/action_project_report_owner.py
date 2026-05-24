from __future__ import annotations

from typing import Any, Callable, Mapping

from envctl_engine.actions.project_action_support import (
    build_project_action_failure_handler,
    build_project_action_success_handler,
    first_output_line,
    persist_project_action_result,
    project_action_success_status,
    review_success_artifact_paths,
)
from envctl_engine.state.runtime_map import build_runtime_map
from envctl_engine.actions.action_migrate_support import (
    migrate_failure_headline,
    project_action_failure_summary_lines,
)


def project_action_success_handler(
    orchestrator: Any,
    command_name: str,
    mode: str,
    interactive_command: bool,
) -> Callable[[object, Any], None] | None:
    return build_project_action_success_handler(
        command_name=command_name,
        mode=mode,
        interactive_command=interactive_command,
        clear_dashboard_pr_cache=orchestrator._clear_dashboard_pr_cache,
        project_action_success_status_fn=project_action_success_status,
        review_success_artifact_paths_fn=review_success_artifact_paths,
        persist_project_action_result_fn=lambda **kwargs: persist_project_action_result_with_owner(
            orchestrator,
            **kwargs,
        ),
        first_output_line_fn=first_output_line,
        emit_status=orchestrator._emit_status,
    )


def project_action_failure_handler(
    orchestrator: Any,
    command_name: str,
    mode: str,
) -> Callable[[object, str], None]:
    return build_project_action_failure_handler(
        command_name=command_name,
        mode=mode,
        persist_project_action_result_fn=lambda **kwargs: persist_project_action_result_with_owner(
            orchestrator,
            **kwargs,
        ),
    )


def persist_project_action_result_with_owner(
    orchestrator: Any,
    *,
    command_name: str,
    mode: str,
    project_name: str,
    status: str,
    error_output: str,
    extra_entry: Mapping[str, object] | None = None,
) -> None:
    persist_project_action_result(
        runtime=orchestrator.runtime,
        command_name=command_name,
        mode=mode,
        project_name=project_name,
        status=status,
        error_output=error_output,
        migrate_env_contracts=orchestrator._migrate_env_contracts,
        failure_summary_lines=project_action_failure_summary_lines,
        failure_headline=migrate_failure_headline,
        runtime_map_builder=build_runtime_map,
        extra_entry=extra_entry,
    )
