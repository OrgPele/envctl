from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
import subprocess
from typing import Any, Callable, Mapping

from envctl_engine.actions.action_command_support import (
    build_action_env,
    build_action_extra_env,
    build_action_replacements,
)
from envctl_engine.actions.action_target_support import ActionCommandResolution, action_target_identity
from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.runtime_context import (
    resolve_process_runtime,
    resolve_state_repository,
    run_dir_path,
    save_resume_state,
)
from envctl_engine.shared.artifact_names import project_command_artifact_path
from envctl_engine.test_output.parser_base import strip_ansi


def action_replacements(
    *,
    runtime: Any,
    targets: list[object],
    target: object | None,
) -> dict[str, str]:
    return build_action_replacements(
        repo_root=runtime.config.base_dir,
        targets=targets,
        target=target,
    )


def action_env(
    *,
    runtime: Any,
    command_name: str,
    targets: list[object],
    route: Route | None,
    target: object | None,
    extra: Mapping[str, str] | None = None,
    process_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    route_mode = getattr(route, "mode", None)
    state = runtime.load_existing_state(mode=route_mode) if isinstance(route_mode, str) else None
    run_id = getattr(state, "run_id", None)
    state_repository = resolve_state_repository(runtime)
    tree_diffs_root = state_repository.tree_diffs_dir_path(run_id)  # type: ignore[attr-defined]
    return build_action_env(
        process_env=os.environ if process_env is None else process_env,
        runtime_env=runtime.env,
        repo_root=runtime.config.base_dir,
        runtime_root=state_repository.runtime_root,  # type: ignore[attr-defined]
        run_id=run_id,
        tree_diffs_root=tree_diffs_root,
        command_name=command_name,
        targets=targets,
        route=route,
        target=target,
        extra=extra,
    )


def action_extra_env(route: Route) -> dict[str, str]:
    return build_action_extra_env(route)


def test_action_extra_env(
    *,
    runtime: Any,
    route: Route | None,
    target: object | None,
    suite_source: str,
    project_context_builder: Callable[..., object],
) -> dict[str, str]:
    normalized_source = str(suite_source or "").strip().lower()
    if normalized_source not in {"backend_pytest", "root_unittest"}:
        return {}
    if target is None:
        return {}
    identity = action_target_identity(target)
    if identity is None:
        return {}
    state = runtime.load_existing_state(mode=getattr(route, "mode", None))
    if state is None:
        return {}
    requirements_map = getattr(state, "requirements", None)
    if not isinstance(requirements_map, dict):
        return {}
    requirements = requirements_map.get(identity.name)
    if requirements is None:
        return {}
    context = project_context_builder(
        project_name=identity.name,
        project_root=identity.root,
        requirements=requirements,
    )
    projector = getattr(runtime.raw_runtime, "_project_service_env", None)
    if not callable(projector):
        return {}
    projected = projector(context, requirements=requirements, route=route, service_name="backend")
    if not isinstance(projected, dict):
        return {}
    return {str(key): str(value) for key, value in projected.items() if isinstance(key, str) and value is not None}


def migrate_action_env(
    *,
    runtime: Any,
    targets: list[object],
    route: Route | None,
    target: object | None,
    migrate_env_contracts: dict[str, dict[str, object]],
    base_env_builder: Callable[..., dict[str, str]],
    backend_cwd: Callable[[Path], Path],
    requirements_for_target: Callable[..., object | None],
    project_context_builder: Callable[..., object],
    contract_context_builder: Callable[..., object],
    resolve_backend_env_contract: Callable[..., object],
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    env = base_env_builder(
        "migrate",
        targets,
        route=route,
        target=target,
        extra=extra,
    )
    if target is None:
        return env

    identity = action_target_identity(target)
    if identity is None:
        return env
    project_name = identity.name
    target_root = identity.root
    resolved_backend_cwd = backend_cwd(target_root)
    runtime_raw = runtime.raw_runtime
    context = contract_context_builder(project_name=project_name, target_root=target_root)

    projected_env: dict[str, str] = {}
    requirements = requirements_for_target(route=route, project_name=project_name)
    if requirements is not None:
        project_context = project_context_builder(
            project_name=project_name,
            project_root=target_root,
            requirements=requirements,
        )
        projector = getattr(runtime_raw, "_project_service_env_internal", None)
        if callable(projector):
            projected_candidate = projector(project_context, requirements=requirements, route=route)
            if isinstance(projected_candidate, dict):
                projected_env = {
                    str(key): str(value)
                    for key, value in projected_candidate.items()
                    if isinstance(key, str) and isinstance(value, str)
                }

    contract = resolve_backend_env_contract(
        runtime_raw,
        context=context,
        backend_cwd=resolved_backend_cwd,
        base_env=env,
        projected_env=projected_env,
    )
    migrate_env_contracts[project_name] = {
        "env_file_path": str(contract.env_file_path) if contract.env_file_path is not None else None,
        "env_file_source": contract.env_file_source,
        "override_requested": contract.override_requested,
        "override_resolution": contract.override_resolution,
        "override_authoritative": contract.override_authoritative,
        "scrubbed_keys": list(contract.scrubbed_keys),
        "projected_keys": list(contract.projected_keys),
    }
    return contract.env


def run_project_action(
    *,
    runtime: Any,
    route: Route,
    targets: list[object],
    command_name: str,
    env_key: str,
    default_command: list[str] | None,
    default_cwd: Path,
    default_append_project_path: bool,
    extra_env: Mapping[str, str],
    action_replacements_builder: Callable[..., dict[str, str]],
    action_env_builder: Callable[..., dict[str, str]],
    emit_status: Callable[[str], None],
    success_handler: Callable[..., object] | None,
    failure_handler: Callable[..., object] | None,
    stdout_is_live_terminal: Callable[[], bool],
    execute_targeted_action_fn: Callable[..., int],
) -> int:
    raw = runtime.env.get(env_key)
    interactive_command = bool(route.flags.get("interactive_command"))
    command_extra_env = dict(extra_env)
    if raw is None and default_command is None:
        print(f"No {command_name} command configured. Set {env_key} or add repo utility script.")
        return 1

    process_runtime = resolve_process_runtime(runtime)
    stream_review_output = bool(
        command_name == "review"
        and not interactive_command
        and stdout_is_live_terminal()
        and hasattr(process_runtime, "run_streaming")
    )
    if stream_review_output:
        command_extra_env["ENVCTL_ACTION_FORCE_RICH"] = "1"

    def resolve_command(context: object) -> ActionCommandResolution:
        target = getattr(context, "target_obj")
        target_root = Path(str(getattr(context, "root")))
        replacements = action_replacements_builder(targets, target=target)
        if raw is not None:
            try:
                command = runtime.split_command(raw, replacements=replacements)
            except RuntimeError as exc:
                return ActionCommandResolution(command=None, cwd=None, error=str(exc))
            return ActionCommandResolution(command=command, cwd=target_root)

        command: list[str] = []
        for token in list(default_command or []):
            value = str(token)
            for key, replacement in replacements.items():
                value = value.replace(f"{{{key}}}", replacement)
            command.append(value)
        if default_append_project_path:
            command.append(str(target_root))
        return ActionCommandResolution(command=command, cwd=default_cwd)

    def build_env(context: object) -> dict[str, str]:
        return action_env_builder(
            command_name,
            targets,
            route=route,
            target=getattr(context, "target_obj"),
            extra=command_extra_env,
        )

    def process_run(command: list[str], cwd: Path, env: Mapping[str, str]) -> subprocess.CompletedProcess[str]:
        if stream_review_output:
            completed = process_runtime.run_streaming(  # type: ignore[attr-defined]
                command,
                cwd=cwd,
                env=dict(env),
                timeout=300.0,
                show_spinner=False,
                echo_output=True,
            )
            return subprocess.CompletedProcess(
                args=command,
                returncode=completed.returncode,
                stdout="" if completed.returncode == 0 else str(completed.stdout or ""),
                stderr=str(getattr(completed, "stderr", "") or ""),
            )
        return process_runtime.run(
            command,
            cwd=cwd,
            env=dict(env),
            timeout=300.0,
        )

    return execute_targeted_action_fn(
        targets=targets,
        command_name=command_name,
        interactive_command=interactive_command,
        resolve_command=resolve_command,
        build_env=build_env,
        process_run=process_run,
        emit_status=emit_status,
        interactive_print_failures=(not interactive_command) or command_name in {"pr", "review"},
        emit_success_output=not stream_review_output,
        on_success=success_handler,
        on_failure=failure_handler,
    )


def build_project_action_success_handler(
    *,
    command_name: str,
    mode: str,
    interactive_command: bool,
    clear_dashboard_pr_cache: Callable[[], None],
    project_action_success_status_fn: Callable[..., str],
    review_success_artifact_paths_fn: Callable[..., dict[str, object]],
    persist_project_action_result_fn: Callable[..., None],
    first_output_line_fn: Callable[[object], str],
    emit_status: Callable[[str], None],
) -> Callable[[object, Any], None]:
    def handle_success(context: object, completed: Any) -> None:
        clear_dashboard_pr_cache()
        status = project_action_success_status_fn(command_name=command_name, completed=completed)
        extra_entry: dict[str, object] | None = None
        if command_name == "review" and status == "success":
            extra_entry = review_success_artifact_paths_fn(
                stdout=getattr(completed, "stdout", ""),
                stderr=getattr(completed, "stderr", ""),
            )
        persist_project_action_result_fn(
            command_name=command_name,
            mode=mode,
            project_name=str(getattr(context, "name")),
            status=status,
            error_output="",
            extra_entry=extra_entry,
        )
        if command_name != "pr" or not interactive_command or status != "success":
            return
        url = first_output_line_fn(getattr(completed, "stdout", ""))
        if url:
            emit_status(f"PR created: {url}")

    return handle_success


def build_project_action_failure_handler(
    *,
    command_name: str,
    mode: str,
    persist_project_action_result_fn: Callable[..., None],
) -> Callable[[object, str], None]:
    def handle_failure(context: object, error_output: str) -> None:
        persist_project_action_result_fn(
            command_name=command_name,
            mode=mode,
            project_name=str(getattr(context, "name")),
            status="failed",
            error_output=error_output,
        )

    return handle_failure


def review_success_artifact_paths(*, stdout: object, stderr: object) -> dict[str, object]:
    output_parts = [str(stdout or ""), str(stderr or "")]
    cleaned = strip_ansi("\n".join(part for part in output_parts if str(part or "").strip()))
    lines = [line.rstrip() for line in cleaned.splitlines()]
    label_map = {
        "output directory": "output_dir",
        "summary file": "summary_path",
        "full review bundle": "bundle_path",
    }
    parsed: dict[str, object] = {}
    for index, raw_line in enumerate(lines):
        label = raw_line.strip().lower()
        key = label_map.get(label)
        if not key:
            continue
        for follow_line in lines[index + 1 :]:
            candidate = follow_line.strip()
            if not candidate:
                continue
            parsed[key] = candidate
            break
    return parsed


def write_project_action_failure_report(
    runtime: Any,
    *,
    run_id: str,
    project_name: str,
    command_name: str,
    output: str,
) -> Path:
    results_root = run_dir_path(runtime, run_id)
    results_root.mkdir(parents=True, exist_ok=True)
    report_path = project_command_artifact_path(results_root, project_name=project_name, command_name=command_name)
    report_path.write_text((output or "Command failed.").rstrip() + "\n", encoding="utf-8")
    return report_path


def first_output_line(output: object) -> str:
    for raw in str(output or "").splitlines():
        text = raw.strip()
        if text:
            return text
    return ""


def project_action_success_status(*, command_name: str, completed: Any) -> str:
    if command_name != "pr":
        return "success"
    output = strip_ansi(str(getattr(completed, "stdout", "") or ""))
    first_line = first_output_line(output)
    if first_line.startswith("Skipping ") and "detached HEAD" in output:
        return "skipped"
    return "success"


def persist_project_action_result(
    *,
    runtime: Any,
    command_name: str,
    mode: str,
    project_name: str,
    status: str,
    error_output: str,
    migrate_env_contracts: Mapping[str, Mapping[str, object]],
    failure_summary_lines: Callable[..., list[str]],
    failure_headline: Callable[[str], str],
    runtime_map_builder: Callable[..., object],
    extra_entry: Mapping[str, object] | None = None,
) -> None:
    state = runtime.load_existing_state(mode=mode)
    if state is None:
        return
    metadata_raw = state.metadata.get("project_action_reports")
    metadata = dict(metadata_raw) if isinstance(metadata_raw, dict) else {}
    project_raw = metadata.get(project_name)
    project_metadata = dict(project_raw) if isinstance(project_raw, dict) else {}
    entry: dict[str, object] = {
        "status": status,
        "updated_at": datetime.now(tz=UTC).isoformat(),
    }
    migrate_env_metadata = dict(migrate_env_contracts.get(project_name, {})) if command_name == "migrate" else None
    if migrate_env_metadata:
        entry["backend_env"] = migrate_env_metadata
    if isinstance(extra_entry, Mapping):
        entry.update({str(key): value for key, value in extra_entry.items()})
    if status == "failed":
        clean_output = strip_ansi(str(error_output or "")).strip()
        summary_lines = failure_summary_lines(
            command_name=command_name,
            error_output=clean_output,
            migrate_env_metadata=migrate_env_metadata,
        )
        summary_text = "\n".join(summary_lines).strip() or "Command failed."
        report_path = write_project_action_failure_report(
            runtime,
            run_id=state.run_id,
            project_name=project_name,
            command_name=command_name,
            output=clean_output,
        )
        if command_name == "migrate":
            headline = failure_headline(clean_output)
            if headline:
                entry["headline"] = headline
        entry["summary"] = summary_text
        entry["report_path"] = str(report_path)
    project_metadata[command_name] = entry
    metadata[project_name] = project_metadata
    state.metadata["project_action_reports"] = metadata
    save_resume_state(
        runtime,
        state=state,
        runtime_map_builder=runtime_map_builder,
    )
