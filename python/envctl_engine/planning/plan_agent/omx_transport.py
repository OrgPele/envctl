from __future__ import annotations

# ruff: noqa: F401,F403,F405
import json
import subprocess
import threading
import time
from importlib import resources
from pathlib import Path
from typing import Any, Literal, Mapping

from envctl_engine.planning import planning_feature_name
from envctl_engine.config import EngineConfig, _apply_plan_agent_aliases
from envctl_engine.runtime.codex_tmux_support import (
    _attach_interactive,
    _completed_process_error_text as _tmux_completed_process_error_text,
    _run_probe as _run_tmux_probe,
    _sanitize_name as _sanitize_tmux_name,
    _tmux_session_exists,
)
from envctl_engine.runtime.prompt_install_support import (
    resolve_codex_direct_prompt_body,
    resolve_opencode_direct_prompt_body,
)
from envctl_engine.state.models import RunState
from envctl_engine.shared.parsing import parse_bool, parse_int_or_none

from envctl_engine.planning.plan_agent.constants import *
from envctl_engine.planning.plan_agent.models import *
from envctl_engine.planning.plan_agent.config import *
from envctl_engine.planning.plan_agent.workflow import *
from envctl_engine.planning.plan_agent.terminal_screen import *
from envctl_engine.planning.plan_agent.recovery import *
from envctl_engine.planning.plan_agent.tmux_session import *
from envctl_engine.planning.plan_agent import omx_attach_support
from envctl_engine.planning.plan_agent import omx_launch_support
from envctl_engine.planning.plan_agent import omx_lock_support
from envctl_engine.planning.plan_agent import omx_spawn_support
from envctl_engine.planning.plan_agent import omx_validation_support


def _launch_plan_agent_omx_terminals(
    runtime: Any,
    *,
    route: object,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    created_worktrees: tuple[CreatedPlanWorktree, ...],
    base_payload: Mapping[str, object],
    prompt_on_existing: bool,
    run_tmux_existing_session_workflow: Any,
) -> PlanAgentLaunchResult:
    return omx_launch_support.launch_omx_terminals(
        runtime,
        route=route,
        launch_config=launch_config,
        workflow=workflow,
        created_worktrees=created_worktrees,
        base_payload=base_payload,
        prompt_on_existing=prompt_on_existing,
        find_existing_attach_target_fn=_find_existing_omx_attach_target,
        should_prompt_existing_session_fn=_should_prompt_existing_tmux_session,
        prompt_existing_session_action_fn=_prompt_existing_tmux_session_action,
        new_session_command_for_route_fn=_new_session_command_for_route,
        read_omx_session_id_fn=_read_omx_session_id,
        read_omx_session_ids_fn=_read_omx_session_ids,
        find_omx_tmux_panes_for_worktree_fn=_find_omx_tmux_panes_for_worktree,
        spawn_omx_session_for_worktree_fn=_spawn_omx_session_for_worktree,
        wait_for_omx_attach_target_fn=_wait_for_omx_attach_target,
        attach_discovery_diagnostics_fn=_omx_attach_discovery_diagnostics,
        run_tmux_existing_session_workflow_fn=run_tmux_existing_session_workflow,
        validate_plan_agent_attach_target_fn=validate_plan_agent_attach_target,
        mark_worktree_plan_agent_launch_fn=_mark_worktree_plan_agent_launch,
        persist_runtime_events_snapshot_fn=_persist_runtime_events_snapshot,
        summarize_failed_launch_outcomes_fn=_summarize_failed_launch_outcomes,
        print_launch_summary_fn=_print_launch_summary,
        plan_agent_native_recovery_command_fn=plan_agent_native_recovery_command,
        plan_agent_recovery_command_text_fn=_plan_agent_recovery_command_text,
    )


def _cleanup_stale_omx_tmux_locks(runtime: Any, *, worktree_root: Path, omx_root: Path | None = None) -> None:
    return omx_lock_support.cleanup_stale_omx_tmux_locks(runtime, worktree_root=worktree_root, omx_root=omx_root)


def _cleanup_stale_omx_tmux_locks_under_root(root: Path) -> bool:
    return omx_lock_support.cleanup_stale_omx_tmux_locks_under_root(root)


def _utc_timestamp_from_epoch(value: float | None = None) -> str:
    return omx_spawn_support.utc_timestamp_from_epoch(value)


def _bounded_process_output_excerpt(value: object) -> str:
    return omx_spawn_support.bounded_process_output_excerpt(value)


def _omx_spawn_metadata_payload(
    *,
    process: object,
    command: tuple[str, ...],
    popen_command: tuple[str, ...],
    worktree: CreatedPlanWorktree,
    omx_root: Path,
    started_at: str,
    madmax: bool,
) -> dict[str, object]:
    return omx_spawn_support.omx_spawn_metadata_payload(
        process=process,
        command=command,
        popen_command=popen_command,
        worktree=worktree,
        omx_root=omx_root,
        started_at=started_at,
        madmax=madmax,
    )


def _retained_omx_spawn_process(record: object) -> object:
    return omx_spawn_support.retained_omx_spawn_process(record)


def _retained_omx_spawn_returncode(record: object) -> object:
    return omx_spawn_support.retained_omx_spawn_returncode(record)


def _retained_omx_spawn_event_payload(
    record: object,
    *,
    session_name: str,
    worktree: CreatedPlanWorktree | None,
    returncode: object,
) -> dict[str, object]:
    return omx_spawn_support.retained_omx_spawn_event_payload(
        record,
        session_name=session_name,
        worktree=worktree,
        returncode=returncode,
    )


def _deterministic_omx_root_for_worktree(worktree: CreatedPlanWorktree) -> Path:
    return omx_spawn_support.deterministic_omx_root_for_worktree(worktree)


def _omx_spawn_failure_text(*, returncode: object, stdout: str, stderr: str) -> str:
    return omx_spawn_support.omx_spawn_failure_text(returncode=returncode, stdout=stdout, stderr=stderr)


def _omx_attach_target_state_check(
    runtime: Any,
    *,
    session_name: str,
    worktree: CreatedPlanWorktree | None,
) -> tuple[bool | None, dict[str, object]]:
    return omx_attach_support.attach_target_state_check(
        session_name=session_name,
        worktree=worktree,
        records=_omx_session_records_for_worktree(runtime, worktree) if worktree is not None else (),
        omx_payload_candidates_fn=_omx_payload_candidates,
    )


def validate_plan_agent_attach_target(
    runtime: Any,
    attach_target: PlanAgentAttachTarget | None,
    *,
    worktree: CreatedPlanWorktree | None = None,
    transport: str = "",
    phase: str = "handoff",
) -> PlanAgentAttachValidation:
    return omx_validation_support.validate_omx_attach_target(
        runtime,
        attach_target,
        worktree=worktree,
        transport=transport,
        phase=phase,
        tmux_session_exists_fn=_tmux_session_exists,
        tmux_display_message_succeeds_fn=_tmux_display_message_succeeds,
        attach_target_state_check_fn=_omx_attach_target_state_check,
        omx_late_spawn_exit_reason_fn=_omx_late_spawn_exit_reason,
    )


def _omx_late_spawn_exit_reason(
    runtime: Any,
    *,
    session_name: str,
    worktree: CreatedPlanWorktree | None,
) -> str | None:
    return omx_validation_support.omx_late_spawn_exit_reason(
        runtime,
        session_name=session_name,
        worktree=worktree,
        retained_returncode_fn=_retained_omx_spawn_returncode,
        retained_event_payload_fn=_retained_omx_spawn_event_payload,
    )


def _mark_worktree_plan_agent_launch(
    worktree: CreatedPlanWorktree,
    *,
    status: str,
    transport: str,
    session_name: str,
) -> None:
    path = Path(worktree.root) / _WORKTREE_PROVENANCE_PATH
    if not path.is_file():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(payload, dict):
        return
    payload["fresh_ai_launch_status"] = str(status or "").strip() or "launched"
    normalized_transport = str(transport or "").strip().lower()
    if normalized_transport:
        payload["launch_transport"] = normalized_transport
    normalized_session = str(session_name or "").strip()
    if normalized_session:
        payload["session_name"] = normalized_session
    payload["launch_recorded_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        return


def _omx_runtime_root_for_worktree(runtime: Any, worktree: CreatedPlanWorktree) -> Path:
    _ = runtime
    return _deterministic_omx_root_for_worktree(worktree)


def _omx_session_state_path_for_root(omx_root: Path) -> Path:
    return omx_attach_support.omx_session_state_path_for_root(omx_root)


def _omx_session_state_path(worktree_root: Path) -> Path:
    return omx_attach_support.omx_session_state_path(worktree_root)


def _read_omx_session_payload_from_path(path: Path) -> dict[str, object] | None:
    return omx_attach_support.read_omx_session_payload_from_path(path)


def _read_omx_session_payload(worktree_root: Path) -> dict[str, object] | None:
    return omx_attach_support.read_omx_session_payload(worktree_root)


def _read_omx_session_payload_from_root(omx_root: Path) -> dict[str, object] | None:
    return omx_attach_support.read_omx_session_payload_from_root(omx_root)


def _omx_session_records_for_worktree(runtime: Any, worktree: CreatedPlanWorktree) -> list[_OmxSessionRecord]:
    return omx_attach_support.omx_session_records_for_worktree(
        runtime,
        worktree,
        omx_runtime_root_for_worktree_fn=_omx_runtime_root_for_worktree,
    )


def _record_cwd_matches_worktree(record: _OmxSessionRecord, worktree: CreatedPlanWorktree) -> bool:
    return omx_attach_support.record_cwd_matches_worktree(record, worktree)


def _read_omx_session_payload_for_worktree(runtime: Any, worktree: CreatedPlanWorktree) -> dict[str, object] | None:
    return omx_attach_support.read_omx_session_payload_for_worktree(
        records=_omx_session_records_for_worktree(runtime, worktree),
        worktree=worktree,
    )


def _read_omx_session_id(runtime: Any, worktree: CreatedPlanWorktree) -> str:
    return omx_attach_support.read_omx_session_id(
        records=_omx_session_records_for_worktree(runtime, worktree),
        worktree=worktree,
    )


def _read_omx_session_ids(runtime: Any, worktree: CreatedPlanWorktree) -> tuple[str, ...]:
    return omx_attach_support.read_omx_session_ids(
        records=_omx_session_records_for_worktree(runtime, worktree),
        worktree=worktree,
    )


def _omx_payload_candidates(record: _OmxSessionRecord, worktree: CreatedPlanWorktree) -> list[str]:
    return omx_attach_support.omx_payload_candidates(
        record,
        worktree,
        omx_tmux_session_name_fn=_omx_tmux_session_name,
    )


def _previous_omx_tmux_session_names_for_worktree(
    runtime: Any,
    worktree: CreatedPlanWorktree,
    *,
    previous_session_id: str = "",
    previous_session_ids: tuple[str, ...] = (),
) -> tuple[str, ...]:
    return omx_attach_support.previous_omx_tmux_session_names_for_worktree(
        _omx_session_records_for_worktree(runtime, worktree),
        worktree,
        omx_payload_candidates_fn=_omx_payload_candidates,
        previous_session_id=previous_session_id,
        previous_session_ids=previous_session_ids,
    )


def _combined_omx_tmux_exclusions(*groups: tuple[str, ...]) -> tuple[str, ...]:
    return omx_attach_support.combined_omx_tmux_exclusions(*groups)


def _omx_worktree_tmux_prefixes(worktree: CreatedPlanWorktree) -> tuple[str, ...]:
    return omx_attach_support.omx_worktree_tmux_prefixes(
        worktree,
        omx_tmux_dir_token_fn=_omx_tmux_dir_token,
        sanitize_omx_tmux_token_fn=_sanitize_omx_tmux_token,
    )


def _find_omx_tmux_panes_for_worktree(runtime: Any, worktree: CreatedPlanWorktree) -> list[tuple[str, str]]:
    return omx_attach_support.find_omx_tmux_panes_for_worktree(
        runtime,
        worktree,
        run_tmux_probe_fn=_run_tmux_probe,
        omx_worktree_tmux_prefixes_fn=_omx_worktree_tmux_prefixes,
    )


def _attach_target_from_omx_record(
    runtime: Any,
    *,
    repo_root: Path,
    worktree: CreatedPlanWorktree,
    record: _OmxSessionRecord,
    attach_via: str,
    previous_session_id: str = "",
    previous_session_ids: tuple[str, ...] = (),
    candidates_checked: list[str] | None = None,
    excluded_session_names: tuple[str, ...] = (),
) -> PlanAgentAttachTarget | None:
    return omx_attach_support.attach_target_from_omx_record(
        runtime,
        repo_root=repo_root,
        worktree=worktree,
        record=record,
        attach_via=attach_via,
        omx_payload_candidates_fn=_omx_payload_candidates,
        find_omx_tmux_panes_for_worktree_fn=_find_omx_tmux_panes_for_worktree,
        tmux_session_exists_fn=_tmux_session_exists,
        tmux_active_pane_id_fn=_tmux_active_pane_id,
        guidance_attach_command_fn=_guidance_attach_command,
        previous_session_id=previous_session_id,
        previous_session_ids=previous_session_ids,
        candidates_checked=candidates_checked,
        excluded_session_names=excluded_session_names,
    )


def _attach_target_from_omx_tmux_pane_fallback(
    runtime: Any,
    *,
    repo_root: Path,
    worktree: CreatedPlanWorktree,
    attach_via: str,
    candidates_checked: list[str] | None = None,
    excluded_session_names: tuple[str, ...] = (),
) -> PlanAgentAttachTarget | None:
    return omx_attach_support.attach_target_from_omx_tmux_pane_fallback(
        runtime,
        repo_root=repo_root,
        worktree=worktree,
        attach_via=attach_via,
        find_omx_tmux_panes_for_worktree_fn=_find_omx_tmux_panes_for_worktree,
        guidance_attach_command_fn=_guidance_attach_command,
        candidates_checked=candidates_checked,
        excluded_session_names=excluded_session_names,
    )


def _omx_attach_discovery_diagnostics(runtime: Any, worktree: CreatedPlanWorktree) -> dict[str, object]:
    return omx_attach_support.attach_discovery_diagnostics(
        runtime,
        worktree,
        omx_runtime_root_for_worktree_fn=_omx_runtime_root_for_worktree,
        find_omx_tmux_panes_for_worktree_fn=_find_omx_tmux_panes_for_worktree,
        omx_payload_candidates_fn=_omx_payload_candidates,
    )


def _sanitize_omx_tmux_token(value: str) -> str:
    return omx_spawn_support.sanitize_omx_tmux_token(value)


def _git_branch_name(cwd: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(cwd),
        env=dict(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=2.0,
    )
    if result.returncode != 0:
        return None
    branch = str(result.stdout).strip()
    return branch or None


def _omx_tmux_dir_token(worktree_root: Path) -> str:
    cwd = Path(worktree_root).resolve()
    parent_path = cwd.parent
    parent_dir = parent_path.name
    dir_name = cwd.name
    grandparent_path = parent_path.parent
    grandparent_dir = grandparent_path.name
    if parent_dir.endswith(".omx-worktrees"):
        repo_dir = parent_dir[: -len(".omx-worktrees")]
    elif parent_dir == "worktrees" and grandparent_dir == ".omx":
        repo_dir = grandparent_path.parent.name
    else:
        repo_dir = None
    return _sanitize_omx_tmux_token(f"{repo_dir}-{dir_name}") if repo_dir else _sanitize_omx_tmux_token(dir_name)


def _omx_tmux_session_name(worktree_root: Path, session_id: str) -> str:
    cwd = Path(worktree_root).resolve()
    dir_token = _omx_tmux_dir_token(cwd)
    branch_token = _sanitize_omx_tmux_token(_git_branch_name(cwd) or "detached")
    session_token = _sanitize_omx_tmux_token(str(session_id).replace("omx-", "", 1))
    prefix = f"omx-{dir_token}-{branch_token}"
    name = f"{prefix}-{session_token}"
    if len(name) <= 120:
        return name
    prefix_budget = max(4, 120 - len(session_token) - 1)
    trimmed_prefix = prefix[:prefix_budget].rstrip("-")
    return f"{trimmed_prefix}-{session_token}"[:120]


def _omx_launch_env(runtime: Any) -> dict[str, str]:
    return omx_spawn_support.omx_launch_env(runtime)


def _retain_omx_spawn_process(runtime: Any, record: object) -> None:
    omx_spawn_support.retain_omx_spawn_process(runtime, record)


def _find_existing_omx_attach_target(
    runtime: Any,
    *,
    repo_root: Path,
    created_worktrees: tuple[CreatedPlanWorktree, ...],
) -> PlanAgentAttachTarget | None:
    return omx_attach_support.find_existing_omx_attach_target(
        runtime,
        repo_root=repo_root,
        created_worktrees=created_worktrees,
        omx_session_records_for_worktree_fn=_omx_session_records_for_worktree,
        attach_target_from_omx_record_fn=_attach_target_from_omx_record,
        attach_target_from_pane_fallback_fn=_attach_target_from_omx_tmux_pane_fallback,
    )


def _wait_for_omx_attach_target(
    runtime: Any,
    *,
    repo_root: Path,
    worktree: CreatedPlanWorktree,
    previous_session_id: str,
    previous_session_ids: tuple[str, ...] = (),
    previous_tmux_session_names: tuple[str, ...] = (),
    attach_via: str,
) -> PlanAgentAttachTarget | None:
    return omx_attach_support.wait_for_omx_attach_target(
        runtime,
        repo_root=repo_root,
        worktree=worktree,
        previous_session_id=previous_session_id,
        previous_session_ids=previous_session_ids,
        previous_tmux_session_names=previous_tmux_session_names,
        attach_via=attach_via,
        session_ready_timeout_seconds=_OMX_SESSION_READY_TIMEOUT_SECONDS,
        session_ready_poll_interval_seconds=_OMX_SESSION_READY_POLL_INTERVAL_SECONDS,
        previous_session_names_fn=_previous_omx_tmux_session_names_for_worktree,
        combined_exclusions_fn=_combined_omx_tmux_exclusions,
        omx_session_records_for_worktree_fn=_omx_session_records_for_worktree,
        attach_target_from_omx_record_fn=_attach_target_from_omx_record,
        attach_target_from_pane_fallback_fn=_attach_target_from_omx_tmux_pane_fallback,
        monotonic_fn=time.monotonic,
        sleep_fn=time.sleep,
    )


def _spawn_omx_session_for_worktree(
    runtime: Any,
    *,
    launch_config: PlanAgentLaunchConfig,
    worktree: CreatedPlanWorktree,
) -> str | None:
    return omx_spawn_support.spawn_omx_session_for_worktree(
        runtime,
        launch_config=launch_config,
        worktree=worktree,
        omx_runtime_root_for_worktree_fn=_omx_runtime_root_for_worktree,
        cleanup_stale_locks_fn=_cleanup_stale_omx_tmux_locks,
        omx_launch_env_fn=_omx_launch_env,
        utc_timestamp_from_epoch_fn=_utc_timestamp_from_epoch,
        read_omx_session_id_fn=_read_omx_session_id,
        retain_omx_spawn_process_fn=_retain_omx_spawn_process,
        popen_factory=subprocess.Popen,
    )


__all__ = tuple(name for name in globals() if not name.startswith("__"))
