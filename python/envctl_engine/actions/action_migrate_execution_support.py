from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from envctl_engine.actions.actions_analysis import default_migrate_command
from envctl_engine.actions.action_target_support import ActionCommandResolution
from envctl_engine.runtime.command_router import Route
from envctl_engine.test_output.parser_base import strip_ansi


def run_migrate_action_with_owner(
    orchestrator: Any,
    route: Route,
    targets: list[object],
    *,
    extra_env: Mapping[str, str],
) -> int:
    interactive_command = bool(route.flags.get("interactive_command"))
    return run_migrate_action(
        runtime=orchestrator.runtime,
        route=route,
        targets=targets,
        extra_env=extra_env,
        action_replacements_builder=orchestrator.action_replacements,
        migrate_action_env_builder=orchestrator.migrate_action_env,
        success_handler=orchestrator._project_action_success_handler("migrate", route.mode, interactive_command),
        failure_handler=orchestrator._project_action_failure_handler("migrate", route.mode),
        emit_status=orchestrator._emit_status,
        failure_summary_lines=orchestrator._project_action_failure_summary_lines,
        failure_headline=orchestrator._migrate_failure_headline,
        print_result_summary=orchestrator._print_migrate_result_summary,
        set_deferred_output=lambda callback: setattr(orchestrator, "_deferred_post_action_output", callback),
        execute_targeted_action_fn=orchestrator.execute_targeted_action_fn,
        migrate_env_contracts=orchestrator._migrate_env_contracts,
    )


def run_migrate_action(
    *,
    runtime: Any,
    route: Route,
    targets: list[object],
    extra_env: Mapping[str, str],
    action_replacements_builder: Callable[..., dict[str, str]],
    migrate_action_env_builder: Callable[..., dict[str, str]],
    success_handler: Callable[..., object] | None,
    failure_handler: Callable[..., object] | None,
    emit_status: Callable[[str], None],
    failure_summary_lines: Callable[..., list[str]],
    failure_headline: Callable[[str], str],
    print_result_summary: Callable[..., None],
    set_deferred_output: Callable[[Callable[[], None]], None],
    execute_targeted_action_fn: Callable[..., int],
    migrate_env_contracts: Mapping[str, Mapping[str, object]] | None = None,
    default_migrate_command_builder: Callable[[Path], Any] = default_migrate_command,
) -> int:
    raw = runtime.env.get("ENVCTL_ACTION_MIGRATE_CMD")
    interactive_command = bool(route.flags.get("interactive_command"))
    observed_outcomes: dict[str, dict[str, object]] = {}
    migrate_env_contracts = migrate_env_contracts or {}

    def resolve_command(context: object) -> ActionCommandResolution:
        target = getattr(context, "target_obj")
        target_root = Path(str(getattr(context, "root")))
        if raw is not None:
            replacements = action_replacements_builder(targets, target=target)
            try:
                command = runtime.split_command(raw, replacements=replacements)
            except RuntimeError as exc:
                return ActionCommandResolution(command=None, cwd=None, error=str(exc))
            return ActionCommandResolution(command=command, cwd=target_root)
        resolution = default_migrate_command_builder(target_root)
        return ActionCommandResolution(
            command=resolution.command,
            cwd=resolution.cwd,
            error=resolution.error,
        )

    def handle_success(context: object, completed: Any) -> None:
        observed_outcomes[getattr(context, "name")] = {"status": "success"}
        if success_handler is not None:
            success_handler(context, completed)

    def handle_failure(context: object, error_output: str) -> None:
        project_name = str(getattr(context, "name"))
        clean_output = strip_ansi(str(error_output or "")).strip()
        migrate_env_metadata = dict(migrate_env_contracts.get(project_name, {}))
        summary_lines = failure_summary_lines(
            command_name="migrate",
            error_output=clean_output,
            migrate_env_metadata=migrate_env_metadata if migrate_env_metadata else None,
        )
        observed_outcomes[project_name] = {
            "status": "failed",
            "headline": failure_headline(clean_output),
            "summary": "\n".join(summary_lines).strip(),
        }
        if migrate_env_metadata:
            observed_outcomes[project_name]["backend_env"] = migrate_env_metadata
        if failure_handler is not None:
            failure_handler(context, error_output)

    code = execute_targeted_action_fn(
        targets=targets,
        command_name="migrate",
        interactive_command=interactive_command,
        resolve_command=resolve_command,
        build_env=lambda context: migrate_action_env_builder(
            targets=targets,
            route=route,
            target=getattr(context, "target_obj"),
            extra=extra_env,
        ),
        process_run=lambda command, cwd, env: runtime.process_runner.run(
            command,
            cwd=cwd,
            env=dict(env),
            timeout=300.0,
        ),
        emit_status=emit_status,
        interactive_print_failures=False,
        on_success=handle_success,
        on_failure=handle_failure,
        failure_status_formatter=lambda context, error: (
            f"migrate failed for {getattr(context, 'name')}: {failure_headline(error)}"
        ),
        print_noninteractive_failures=False,
        print_noninteractive_successes=False,
    )
    if not interactive_command:
        target_names = [
            str(getattr(target, "name", "")).strip()
            for target in targets
            if str(getattr(target, "name", "")).strip()
        ]
        set_deferred_output(
            lambda: print_result_summary(
                mode=route.mode,
                project_names=target_names,
                fallback_entries=observed_outcomes,
            )
        )
    return code
