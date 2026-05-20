from __future__ import annotations

# ruff: noqa: F401,F403,F405
import json
import os
import re
import shlex
import shutil
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
    if launch_config.cli != "codex":
        runtime._emit("planning.agent_launch.failed", reason="unsupported_omx_cli", **base_payload)
        return PlanAgentLaunchResult(status="failed", reason="unsupported_omx_cli")
    repo_root = Path(runtime.config.base_dir).resolve()
    attach_via = "switch-client" if str(getattr(runtime, "env", {}).get("TMUX", "")).strip() else "attach-session"
    route_flags = getattr(route, "flags", {}) or {}
    create_new_session = bool(route_flags.get("new_session"))
    existing_attach_target = _find_existing_omx_attach_target(
        runtime,
        repo_root=repo_root,
        created_worktrees=created_worktrees,
    )
    if existing_attach_target is not None:
        if not create_new_session and _should_prompt_existing_tmux_session(
            runtime,
            prompt_on_existing=prompt_on_existing,
        ):
            action = _prompt_existing_tmux_session_action(
                runtime,
                attach_target=existing_attach_target,
            )
            if action == "attach":
                runtime._emit(
                    "planning.agent_launch.skipped",
                    reason="existing_omx_session_attach",
                    session_name=existing_attach_target.session_name,
                    attach_command=" ".join(existing_attach_target.attach_command),
                    **base_payload,
                )
                return PlanAgentLaunchResult(
                    status="failed",
                    reason="existing_omx_session_attach",
                    outcomes=(),
                    attach_target=existing_attach_target,
                )
            create_new_session = True
        attach_command = " ".join(existing_attach_target.attach_command)
        if not create_new_session:
            reason = f"An OMX-managed tmux session already exists for this plan. Attach with: {attach_command}"
            runtime._emit(
                "planning.agent_launch.skipped",
                reason="existing_omx_session",
                session_name=existing_attach_target.session_name,
                attach_command=attach_command,
                **base_payload,
            )
            return PlanAgentLaunchResult(
                status="failed",
                reason=reason,
                outcomes=(),
                attach_target=PlanAgentAttachTarget(
                    repo_root=existing_attach_target.repo_root,
                    session_name=existing_attach_target.session_name,
                    window_name=existing_attach_target.window_name,
                    attach_via=existing_attach_target.attach_via,
                    attach_command=existing_attach_target.attach_command,
                    new_session_command=_new_session_command_for_route(
                        runtime,
                        route=route,
                        launch_config=launch_config,
                        created_worktrees=created_worktrees,
                    ),
                ),
            )
    runtime._emit(
        "planning.agent_launch.evaluate",
        reason="ready",
        preset=launch_config.preset,
        **base_payload,
    )
    runtime._emit(
        "planning.agent_launch.workflow_selected",
        warning=launch_config.codex_cycles_warning,
        **base_payload,
    )
    outcomes: list[PlanAgentLaunchOutcome] = []
    first_attach_target: PlanAgentAttachTarget | None = None
    for worktree in created_worktrees:
        previous_session_id = _read_omx_session_id(runtime, worktree)
        previous_session_ids = _read_omx_session_ids(runtime, worktree)
        previous_tmux_session_names = (
            tuple(session_name for session_name, _pane_id in _find_omx_tmux_panes_for_worktree(runtime, worktree))
            if create_new_session
            else ()
        )
        spawn_error = _spawn_omx_session_for_worktree(runtime, launch_config=launch_config, worktree=worktree)
        if spawn_error is not None:
            runtime._emit(
                "planning.agent_launch.failed",
                reason="omx_spawn_failed",
                worktree=worktree.name,
                error=spawn_error,
                transport="omx",
            )
            outcomes.append(
                PlanAgentLaunchOutcome(
                    worktree_name=worktree.name,
                    worktree_root=worktree.root,
                    surface_id=None,
                    status="failed",
                    reason=spawn_error,
                )
            )
            continue
        attach_target = _wait_for_omx_attach_target(
            runtime,
            repo_root=repo_root,
            worktree=worktree,
            previous_session_id=previous_session_id,
            previous_session_ids=previous_session_ids,
            previous_tmux_session_names=previous_tmux_session_names,
            attach_via=attach_via,
        )
        if attach_target is None:
            diagnostics = _omx_attach_discovery_diagnostics(runtime, worktree)
            runtime._emit(
                "planning.agent_launch.failed",
                reason="omx_session_unavailable",
                worktree=worktree.name,
                transport="omx",
                **diagnostics,
            )
            outcomes.append(
                PlanAgentLaunchOutcome(
                    worktree_name=worktree.name,
                    worktree_root=worktree.root,
                    surface_id=None,
                    status="failed",
                    reason="omx_session_unavailable",
                )
            )
            continue
        error = run_tmux_existing_session_workflow(
            runtime,
            session_name=attach_target.session_name,
            window_name=attach_target.window_name,
            launch_config=launch_config,
            workflow=workflow,
            worktree=worktree,
        )
        if error is not None:
            runtime._emit(
                "planning.agent_launch.failed",
                reason="bootstrap_failed",
                session_name=attach_target.session_name,
                window_name=attach_target.window_name,
                worktree=worktree.name,
                error=error,
                transport="omx",
            )
            outcomes.append(
                PlanAgentLaunchOutcome(
                    worktree_name=worktree.name,
                    worktree_root=worktree.root,
                    surface_id=None,
                    status="failed",
                    reason=error,
                )
            )
            continue
        validation = validate_plan_agent_attach_target(
            runtime,
            attach_target,
            worktree=worktree,
            transport="omx",
            phase="post_workflow_queue",
        )
        if not validation.ok:
            runtime._emit(
                "planning.agent_launch.failed",
                reason=validation.reason,
                session_name=attach_target.session_name,
                window_name=attach_target.window_name,
                worktree=worktree.name,
                transport="omx",
            )
            outcomes.append(
                PlanAgentLaunchOutcome(
                    worktree_name=worktree.name,
                    worktree_root=worktree.root,
                    surface_id=None,
                    status="failed",
                    reason=validation.reason,
                )
            )
            continue
        _mark_worktree_plan_agent_launch(
            worktree,
            status="launched",
            transport="omx",
            session_name=attach_target.session_name,
        )
        runtime._emit(
            "planning.agent_launch.surface_created",
            session_name=attach_target.session_name,
            window_name=attach_target.window_name,
            worktree=worktree.name,
            source="omx_session",
            transport="omx",
        )
        runtime._emit(
            "planning.agent_launch.command_sent",
            session_name=attach_target.session_name,
            window_name=attach_target.window_name,
            worktree=worktree.name,
            preset=launch_config.preset,
            workflow_mode=workflow.mode,
            codex_cycles=workflow.codex_cycles,
            transport="omx",
        )
        outcomes.append(
            PlanAgentLaunchOutcome(
                worktree_name=worktree.name,
                worktree_root=worktree.root,
                surface_id=None,
                status="launched",
            )
        )
        if first_attach_target is None:
            first_attach_target = attach_target
    _persist_runtime_events_snapshot(runtime)
    launched = [item for item in outcomes if item.status == "launched"]
    failed = [item for item in outcomes if item.status == "failed"]
    attach_target = first_attach_target or existing_attach_target
    if failed and launched:
        details = _summarize_failed_launch_outcomes(failed)
        suffix = f" Details: {details}." if details else ""
        _print_launch_summary(
            f"Plan agent launch finished with partial success: launched {len(launched)}, failed {len(failed)}.{suffix}"
        )
        recovery_command = _plan_agent_recovery_command_text(
            plan_agent_native_recovery_command(
                runtime,
                route=route,
                launch_config=launch_config,
                created_worktrees=created_worktrees,
            )
        )
        if recovery_command:
            _print_launch_summary(f"recovery: {recovery_command}")
        return PlanAgentLaunchResult(
            status="partial",
            reason="partial_failure",
            outcomes=tuple(outcomes),
            attach_target=attach_target,
        )
    if failed:
        details = _summarize_failed_launch_outcomes(failed)
        suffix = f" Details: {details}." if details else ""
        _print_launch_summary(f"Plan agent launch failed for {len(failed)} worktree(s).{suffix}")
        recovery_command = _plan_agent_recovery_command_text(
            plan_agent_native_recovery_command(
                runtime,
                route=route,
                launch_config=launch_config,
                created_worktrees=created_worktrees,
            )
        )
        if recovery_command:
            _print_launch_summary(f"recovery: {recovery_command}")
        return PlanAgentLaunchResult(status="failed", reason="launch_failed", outcomes=tuple(outcomes))
    _print_launch_summary(f"Plan agent launch prepared {len(launched)} OMX-managed tmux session(s).")
    return PlanAgentLaunchResult(
        status="launched",
        reason="launched",
        outcomes=tuple(outcomes),
        attach_target=attach_target,
    )


def _cleanup_stale_omx_tmux_locks(runtime: Any, *, worktree_root: Path, omx_root: Path | None = None) -> None:
    roots = [Path(worktree_root).resolve()]
    if omx_root is not None:
        resolved_omx_root = Path(omx_root).expanduser().resolve(strict=False)
        if resolved_omx_root not in roots:
            roots.insert(0, resolved_omx_root)
    removed_roots: list[str] = []
    for root in roots:
        if _cleanup_stale_omx_tmux_locks_under_root(root):
            removed_roots.append(str(root))
    if removed_roots:
        runtime._emit(
            "planning.agent_launch.omx_lock_cleanup",
            worktree=str(Path(worktree_root).resolve()),
            transport="omx",
        )


def _cleanup_stale_omx_tmux_locks_under_root(root: Path) -> bool:
    lock_root = Path(root).resolve() / _OMX_TMUX_EXTENDED_KEYS_RELATIVE_PATH
    if not lock_root.is_dir():
        return False
    removed_any = False
    now = time.time()
    for child in lock_root.iterdir():
        if not child.name.endswith('.lock'):
            continue
        try:
            age_seconds = max(0.0, now - child.stat().st_mtime)
        except OSError:
            continue
        if age_seconds < _OMX_TMUX_LOCK_STALE_SECONDS:
            continue
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
            removed_any = True
            continue
        try:
            child.unlink()
        except OSError:
            continue
        removed_any = True
    return removed_any


def _utc_timestamp_from_epoch(value: float | None = None) -> str:
    timestamp = time.time() if value is None else value
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(timestamp))


def _bounded_process_output_excerpt(value: object) -> str:
    return str(value or "")[:_OMX_SPAWN_OUTPUT_EXCERPT_CHARS]


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
    return {
        "pid": getattr(process, "pid", None),
        "command": list(command),
        "popen_command": list(popen_command),
        "worktree": worktree.name,
        "worktree_root": str(Path(worktree.root).resolve(strict=False)),
        "omx_root": str(Path(omx_root).resolve(strict=False)),
        "transport": "omx",
        "madmax": bool(madmax),
        "started_at": started_at,
        "phase": "spawn",
    }


def _retained_omx_spawn_process(record: object) -> object:
    return getattr(record, "process", record)


def _retained_omx_spawn_returncode(record: object) -> object:
    process = _retained_omx_spawn_process(record)
    poll = getattr(process, "poll", None)
    try:
        return poll() if callable(poll) else getattr(process, "returncode", None)
    except Exception:
        return None


def _retained_omx_spawn_event_payload(
    record: object,
    *,
    session_name: str,
    worktree: CreatedPlanWorktree | None,
    returncode: object,
) -> dict[str, object]:
    process = _retained_omx_spawn_process(record)
    record_worktree_root = getattr(record, "worktree_root", None)
    if record_worktree_root is None and worktree is not None:
        record_worktree_root = worktree.root
    record_omx_root = getattr(record, "omx_root", None)
    if record_omx_root is None and worktree is not None:
        record_omx_root = _deterministic_omx_root_for_worktree(worktree)
    command = getattr(record, "command", None) or getattr(process, "args", None) or ()
    popen_command = getattr(record, "popen_command", None) or getattr(process, "args", None) or ()
    payload: dict[str, object] = {
        "pid": getattr(process, "pid", None),
        "returncode": returncode,
        "session_name": session_name,
        "command": [str(part) for part in command],
        "popen_command": [str(part) for part in popen_command],
        "worktree": str(getattr(record, "worktree_name", "") or getattr(worktree, "name", "") or "") or None,
        "transport": "omx",
    }
    if record_worktree_root is not None:
        payload["worktree_root"] = str(Path(record_worktree_root).resolve(strict=False))
    if record_omx_root is not None:
        payload["omx_root"] = str(Path(record_omx_root).resolve(strict=False))
    if getattr(record, "started_at", ""):
        payload["started_at"] = str(getattr(record, "started_at"))
    if hasattr(record, "madmax"):
        payload["madmax"] = bool(getattr(record, "madmax"))
    return payload


def _deterministic_omx_root_for_worktree(worktree: CreatedPlanWorktree) -> Path:
    token = _sanitize_omx_tmux_token(worktree.name)
    return Path(worktree.root).resolve() / ".envctl-state" / "omx" / token


def _omx_spawn_failure_text(*, returncode: object, stdout: str, stderr: str) -> str:
    for stream in (stderr, stdout):
        lines = [line.strip() for line in str(stream or "").splitlines() if line.strip()]
        if lines:
            return lines[0]
    normalized_code = "" if returncode is None else str(returncode).strip()
    if normalized_code:
        return f"omx exited with status {normalized_code}"
    return "omx exited before creating a managed session"


def _omx_attach_target_state_check(
    runtime: Any,
    *,
    session_name: str,
    worktree: CreatedPlanWorktree | None,
) -> tuple[bool | None, dict[str, object]]:
    if worktree is None:
        return None, {}
    records = _omx_session_records_for_worktree(runtime, worktree)
    if not records:
        return None, {}
    current_candidates: list[str] = []
    wrong_worktree_candidates: list[str] = []
    records_checked = 0
    wrong_worktree_records = 0
    for record in records:
        candidates = [candidate for candidate in _omx_payload_candidates(record, worktree) if candidate]
        if not candidates:
            continue
        records_checked += 1
        if _record_cwd_matches_worktree(record, worktree):
            for candidate in candidates:
                if candidate not in current_candidates:
                    current_candidates.append(candidate)
        else:
            wrong_worktree_records += 1
            for candidate in candidates:
                if candidate not in wrong_worktree_candidates:
                    wrong_worktree_candidates.append(candidate)
    diagnostics: dict[str, object] = {
        "omx_session_candidates": current_candidates,
        "omx_wrong_worktree_candidates": wrong_worktree_candidates,
        "omx_session_records_checked": records_checked,
        "omx_wrong_worktree_records": wrong_worktree_records,
    }
    if current_candidates:
        return (session_name in current_candidates), diagnostics
    if session_name in wrong_worktree_candidates:
        return False, diagnostics
    return None, diagnostics


def validate_plan_agent_attach_target(
    runtime: Any,
    attach_target: PlanAgentAttachTarget | None,
    *,
    worktree: CreatedPlanWorktree | None = None,
    transport: str = "",
    phase: str = "handoff",
) -> PlanAgentAttachValidation:
    session_name = str(getattr(attach_target, "session_name", "") or "").strip() if attach_target else ""
    attach_command = " ".join(
        str(part).strip()
        for part in (getattr(attach_target, "attach_command", ()) if attach_target is not None else ())
        if str(part).strip()
    )
    worktree_root = Path(getattr(worktree, "root", "") or "") if worktree is not None else None
    worktree_name = str(getattr(worktree, "name", "") or "").strip() if worktree is not None else ""
    payload = {
        "session_name": session_name or None,
        "attach_command": attach_command or None,
        "worktree": worktree_name or None,
        "worktree_root": str(worktree_root.resolve(strict=False)) if worktree_root is not None else None,
        "transport": str(transport or "").strip() or None,
        "phase": str(phase or "").strip() or None,
    }
    if not session_name:
        reason = "omx_session_unavailable" if str(transport).strip().lower() == "omx" else "attach_target_unavailable"
        runtime._emit("planning.agent_launch.attach_validation.failed", reason=reason, **payload)
        return PlanAgentAttachValidation(False, reason, session_name=session_name, attach_command=attach_command)
    if worktree_root is not None and not worktree_root.is_dir():
        reason = "worktree_removed_after_launch"
        runtime._emit("planning.agent_launch.worktree_missing_after_launch", reason=reason, **payload)
        runtime._emit("planning.agent_launch.attach_validation.failed", reason=reason, **payload)
        return PlanAgentAttachValidation(False, reason, session_name=session_name, attach_command=attach_command)
    try:
        session_exists = _tmux_session_exists(runtime, session_name)
    except OSError:
        session_exists = False
    if not session_exists:
        reason = "omx_attach_target_stale" if str(transport).strip().lower() == "omx" else "attach_target_stale"
        runtime._emit("planning.agent_launch.attach_validation.failed", reason=reason, **payload)
        return PlanAgentAttachValidation(False, reason, session_name=session_name, attach_command=attach_command)
    try:
        pane_ok, pane_id = _tmux_display_message_succeeds(runtime, session_name)
    except OSError:
        pane_ok, pane_id = False, ""
    if not pane_ok:
        reason = "omx_session_unavailable" if str(transport).strip().lower() == "omx" else "attach_target_unavailable"
        runtime._emit("planning.agent_launch.attach_validation.failed", reason=reason, **payload)
        return PlanAgentAttachValidation(False, reason, session_name=session_name, attach_command=attach_command)
    if str(transport).strip().lower() == "omx":
        state_ok, state_diagnostics = _omx_attach_target_state_check(
            runtime,
            session_name=session_name,
            worktree=worktree,
        )
        if state_ok is False:
            reason = "omx_attach_target_stale"
            runtime._emit(
                "planning.agent_launch.attach_validation.failed",
                reason=reason,
                **payload,
                **state_diagnostics,
            )
            return PlanAgentAttachValidation(False, reason, session_name=session_name, attach_command=attach_command)
        exit_reason = _omx_late_spawn_exit_reason(runtime, session_name=session_name, worktree=worktree)
        if exit_reason:
            runtime._emit("planning.agent_launch.attach_validation.failed", reason=exit_reason, **payload)
            return PlanAgentAttachValidation(
                False,
                exit_reason,
                session_name=session_name,
                attach_command=attach_command,
            )
    runtime._emit("planning.agent_launch.attach_validation.ok", pane_id=pane_id, **payload)
    return PlanAgentAttachValidation(True, "ok", session_name=session_name, attach_command=attach_command)


def _omx_late_spawn_exit_reason(
    runtime: Any,
    *,
    session_name: str,
    worktree: CreatedPlanWorktree | None,
) -> str | None:
    retained = getattr(runtime, "_omx_spawn_processes", None)
    if not isinstance(retained, list):
        return None
    still_running: list[object] = []
    exited = False
    for record in retained:
        returncode = _retained_omx_spawn_returncode(record)
        if returncode is None:
            still_running.append(record)
            continue
        exited = True
        runtime._emit(
            "planning.agent_launch.omx_spawn.exited_early",
            **_retained_omx_spawn_event_payload(
                record,
                session_name=session_name,
                worktree=worktree,
                returncode=returncode,
            ),
        )
    retained[:] = still_running
    return "omx_session_exited" if exited else None


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
    return Path(omx_root).expanduser().resolve(strict=False) / _OMX_SESSION_STATE_RELATIVE_PATH


def _omx_session_state_path(worktree_root: Path) -> Path:
    return _omx_session_state_path_for_root(Path(worktree_root).resolve())


def _read_omx_session_payload_from_path(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _read_omx_session_payload(worktree_root: Path) -> dict[str, object] | None:
    return _read_omx_session_payload_from_path(_omx_session_state_path(worktree_root))


def _read_omx_session_payload_from_root(omx_root: Path) -> dict[str, object] | None:
    return _read_omx_session_payload_from_path(_omx_session_state_path_for_root(omx_root))


def _omx_session_records_for_worktree(runtime: Any, worktree: CreatedPlanWorktree) -> list[_OmxSessionRecord]:
    roots = [
        _omx_runtime_root_for_worktree(runtime, worktree),
        Path(worktree.root).expanduser().resolve(strict=False),
    ]
    records: list[_OmxSessionRecord] = []
    seen_paths: set[Path] = set()
    for root in roots:
        state_path = _omx_session_state_path_for_root(root)
        if state_path in seen_paths:
            continue
        seen_paths.add(state_path)
        payload = _read_omx_session_payload_from_path(state_path)
        if payload is None:
            continue
        records.append(_OmxSessionRecord(omx_root=root, state_path=state_path, payload=payload))
    return records


def _record_cwd_matches_worktree(record: _OmxSessionRecord, worktree: CreatedPlanWorktree) -> bool:
    raw_cwd = record.payload.get("cwd")
    if not isinstance(raw_cwd, str) or not raw_cwd.strip():
        return True
    candidate = Path(raw_cwd).expanduser().resolve(strict=False)
    return candidate == Path(worktree.root).expanduser().resolve(strict=False)


def _read_omx_session_payload_for_worktree(runtime: Any, worktree: CreatedPlanWorktree) -> dict[str, object] | None:
    for record in _omx_session_records_for_worktree(runtime, worktree):
        if _record_cwd_matches_worktree(record, worktree):
            return record.payload
    return None


def _read_omx_session_id(runtime: Any, worktree: CreatedPlanWorktree) -> str:
    payload = _read_omx_session_payload_for_worktree(runtime, worktree) or {}
    value = payload.get("session_id")
    return str(value).strip() if isinstance(value, str) else ""


def _read_omx_session_ids(runtime: Any, worktree: CreatedPlanWorktree) -> tuple[str, ...]:
    values: list[str] = []
    for record in _omx_session_records_for_worktree(runtime, worktree):
        if not _record_cwd_matches_worktree(record, worktree):
            continue
        value = record.payload.get("session_id")
        session_id = str(value).strip() if isinstance(value, str) else ""
        if session_id and session_id not in values:
            values.append(session_id)
    return tuple(values)


def _omx_payload_candidates(record: _OmxSessionRecord, worktree: CreatedPlanWorktree) -> list[str]:
    session_id = str(record.payload.get("session_id") or "").strip()
    if not session_id:
        return []
    candidates: list[str] = []
    native_session_id = str(record.payload.get("native_session_id") or "").strip()
    if native_session_id:
        candidates.append(native_session_id)
    candidates.append(_omx_tmux_session_name(worktree.root, session_id))
    return candidates


def _previous_omx_tmux_session_names_for_worktree(
    runtime: Any,
    worktree: CreatedPlanWorktree,
    *,
    previous_session_id: str = "",
    previous_session_ids: tuple[str, ...] = (),
) -> tuple[str, ...]:
    previous = {str(value).strip() for value in previous_session_ids if str(value).strip()}
    if str(previous_session_id).strip():
        previous.add(str(previous_session_id).strip())
    if not previous:
        return ()
    names: list[str] = []
    for record in _omx_session_records_for_worktree(runtime, worktree):
        if not _record_cwd_matches_worktree(record, worktree):
            continue
        session_id = str(record.payload.get("session_id") or "").strip()
        if session_id not in previous:
            continue
        for candidate in _omx_payload_candidates(record, worktree):
            if candidate and candidate not in names:
                names.append(candidate)
    return tuple(names)


def _combined_omx_tmux_exclusions(*groups: tuple[str, ...]) -> tuple[str, ...]:
    names: list[str] = []
    for group in groups:
        for value in group:
            name = str(value).strip()
            if name and name not in names:
                names.append(name)
    return tuple(names)


def _omx_worktree_tmux_prefixes(worktree: CreatedPlanWorktree) -> tuple[str, ...]:
    prefixes = [f"omx-{_omx_tmux_dir_token(worktree.root)}-"]
    name_prefix = f"omx-{_sanitize_omx_tmux_token(worktree.name)}-"
    if name_prefix not in prefixes:
        prefixes.append(name_prefix)
    return tuple(prefixes)


def _find_omx_tmux_panes_for_worktree(runtime: Any, worktree: CreatedPlanWorktree) -> list[tuple[str, str]]:
    separator_pane = "|||ENVCTL_TMUX_PANE|||"
    separator_path = "|||ENVCTL_TMUX_PATH|||"
    result = _run_tmux_probe(
        runtime,
        (
            "tmux",
            "list-panes",
            "-a",
            "-F",
            f"#{{session_name}}{separator_pane}#{{pane_id}}{separator_path}#{{pane_current_path}}",
        ),
        cwd=Path(runtime.config.base_dir).resolve(),
    )
    if result.returncode != 0:
        return []
    target = Path(worktree.root).expanduser().resolve(strict=False)
    prefixes = _omx_worktree_tmux_prefixes(worktree)
    matches: list[tuple[str, str]] = []
    for raw_line in str(getattr(result, "stdout", "")).splitlines():
        session_name, pane_separator, rest = raw_line.partition(separator_pane)
        pane_id, path_separator, raw_path = rest.partition(separator_path)
        if not pane_separator or not path_separator:
            continue
        session_name = session_name.strip()
        pane_id = pane_id.strip()
        normalized_path = raw_path.strip()
        if not session_name or not pane_id or not normalized_path:
            continue
        if not any(session_name.startswith(prefix) for prefix in prefixes):
            continue
        candidate = Path(normalized_path).expanduser().resolve(strict=False)
        if candidate == target or target in candidate.parents:
            matches.append((session_name, pane_id))
    return matches


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
    if not _record_cwd_matches_worktree(record, worktree):
        return None
    session_id = str(record.payload.get("session_id") or "").strip()
    if not session_id:
        return None
    previous = {str(value).strip() for value in previous_session_ids if str(value).strip()}
    if str(previous_session_id).strip():
        previous.add(str(previous_session_id).strip())
    if session_id in previous:
        return None
    for candidate in _omx_payload_candidates(record, worktree):
        if candidates_checked is not None and candidate not in candidates_checked:
            candidates_checked.append(candidate)
        if not candidate or not _tmux_session_exists(runtime, candidate):
            continue
        return PlanAgentAttachTarget(
            repo_root=repo_root,
            session_name=candidate,
            window_name=_tmux_active_pane_id(runtime, candidate),
            attach_via=attach_via,
            attach_command=_guidance_attach_command(candidate),
        )
    excluded = {str(value).strip() for value in excluded_session_names if str(value).strip()}
    for session_name, pane_id in _find_omx_tmux_panes_for_worktree(runtime, worktree):
        if candidates_checked is not None and session_name not in candidates_checked:
            candidates_checked.append(session_name)
        if session_name in excluded:
            continue
        return PlanAgentAttachTarget(
            repo_root=repo_root,
            session_name=session_name,
            window_name=pane_id,
            attach_via=attach_via,
            attach_command=_guidance_attach_command(session_name),
        )
    return None


def _attach_target_from_omx_tmux_pane_fallback(
    runtime: Any,
    *,
    repo_root: Path,
    worktree: CreatedPlanWorktree,
    attach_via: str,
    candidates_checked: list[str] | None = None,
    excluded_session_names: tuple[str, ...] = (),
) -> PlanAgentAttachTarget | None:
    excluded = {str(value).strip() for value in excluded_session_names if str(value).strip()}
    for session_name, pane_id in _find_omx_tmux_panes_for_worktree(runtime, worktree):
        if candidates_checked is not None and session_name not in candidates_checked:
            candidates_checked.append(session_name)
        if session_name in excluded:
            continue
        return PlanAgentAttachTarget(
            repo_root=repo_root,
            session_name=session_name,
            window_name=pane_id,
            attach_via=attach_via,
            attach_command=_guidance_attach_command(session_name),
        )
    return None


def _omx_attach_discovery_diagnostics(runtime: Any, worktree: CreatedPlanWorktree) -> dict[str, object]:
    selected_root = _omx_runtime_root_for_worktree(runtime, worktree)
    selected_state_path = _omx_session_state_path_for_root(selected_root)
    records = _omx_session_records_for_worktree(runtime, worktree)
    payload = records[0].payload if records else {}
    session_id = str(payload.get("session_id") or "").strip() if isinstance(payload, dict) else ""
    candidates: list[str] = []
    for record in records:
        if not _record_cwd_matches_worktree(record, worktree):
            continue
        for candidate in _omx_payload_candidates(record, worktree):
            if candidate not in candidates:
                candidates.append(candidate)
    panes = _find_omx_tmux_panes_for_worktree(runtime, worktree)
    for session_name, _pane_id in panes:
        if session_name not in candidates:
            candidates.append(session_name)
    return {
        "omx_root": str(selected_root),
        "omx_roots": [str(selected_root), str(Path(worktree.root).resolve())],
        "session_state_exists": selected_state_path.is_file(),
        "session_id_present": bool(session_id),
        "tmux_candidates_checked": candidates,
        "worktree_panes_found": len(panes),
    }


def _sanitize_omx_tmux_token(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(value).strip().lower()).strip("-")
    return cleaned or "unknown"


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
    env = dict(os.environ)
    env.update(dict(getattr(runtime, "env", {})))
    home = str(env.get("HOME") or "").strip()
    if home and not str(env.get("CODEX_HOME") or "").strip():
        codex_home = Path(home).expanduser() / ".codex"
        if codex_home.exists():
            env["CODEX_HOME"] = str(codex_home)
    env.pop("TMUX", None)
    env.pop("TMUX_PANE", None)
    return env


def _retain_omx_spawn_process(runtime: Any, record: object) -> None:
    retained = getattr(runtime, "_omx_spawn_processes", None)
    if not isinstance(retained, list):
        retained = []
        try:
            setattr(runtime, "_omx_spawn_processes", retained)
        except Exception:
            return
    retained[:] = [item for item in retained if _retained_omx_spawn_returncode(item) is None]
    retained.append(record)


def _find_existing_omx_attach_target(
    runtime: Any,
    *,
    repo_root: Path,
    created_worktrees: tuple[CreatedPlanWorktree, ...],
) -> PlanAgentAttachTarget | None:
    attach_via = "attach-session"
    for worktree in created_worktrees:
        for record in _omx_session_records_for_worktree(runtime, worktree):
            attach_target = _attach_target_from_omx_record(
                runtime,
                repo_root=repo_root,
                worktree=worktree,
                record=record,
                attach_via=attach_via,
            )
            if attach_target is not None:
                return attach_target
        attach_target = _attach_target_from_omx_tmux_pane_fallback(
            runtime,
            repo_root=repo_root,
            worktree=worktree,
            attach_via=attach_via,
        )
        if attach_target is not None:
            return attach_target
    return None


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
    deadline = time.monotonic() + _OMX_SESSION_READY_TIMEOUT_SECONDS
    previous = str(previous_session_id).strip()
    excluded_session_names = _combined_omx_tmux_exclusions(
        _previous_omx_tmux_session_names_for_worktree(
            runtime,
            worktree,
            previous_session_id=previous,
            previous_session_ids=previous_session_ids,
        ),
        previous_tmux_session_names,
    )
    while time.monotonic() < deadline:
        for record in _omx_session_records_for_worktree(runtime, worktree):
            attach_target = _attach_target_from_omx_record(
                runtime,
                repo_root=repo_root,
                worktree=worktree,
                record=record,
                attach_via=attach_via,
                previous_session_id=previous,
                previous_session_ids=previous_session_ids,
                excluded_session_names=excluded_session_names,
            )
            if attach_target is not None:
                return attach_target
        attach_target = _attach_target_from_omx_tmux_pane_fallback(
            runtime,
            repo_root=repo_root,
            worktree=worktree,
            attach_via=attach_via,
            excluded_session_names=excluded_session_names,
        )
        if attach_target is not None:
            return attach_target
        time.sleep(_OMX_SESSION_READY_POLL_INTERVAL_SECONDS)
    return None


def _spawn_omx_session_for_worktree(
    runtime: Any,
    *,
    launch_config: PlanAgentLaunchConfig,
    worktree: CreatedPlanWorktree,
) -> str | None:
    omx_root = _omx_runtime_root_for_worktree(runtime, worktree)
    try:
        omx_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return str(exc)
    _cleanup_stale_omx_tmux_locks(runtime, worktree_root=worktree.root, omx_root=omx_root)
    cli_command = shlex.split(launch_config.cli_command) if str(launch_config.cli_command).strip() else []
    wants_bypass = any(token == _CODEX_BYPASS_FLAGS for token in cli_command[1:])
    command = ["omx", "--tmux"]
    if wants_bypass:
        command.append("--madmax")
    popen_command = ["script", "-qfc", shlex.join(command), "/dev/null"]
    env = _omx_launch_env(runtime)
    env["OMX_ROOT"] = str(omx_root)
    env["OMX_LAUNCH_POLICY"] = "detached-tmux"
    if launch_config.omx_workflow == "team":
        env["OMX_TEAM_WORKER_LAUNCH_ARGS"] = _CODEX_BYPASS_FLAGS
    runtime._emit(
        "planning.agent_launch.omx_state_root_selected",
        worktree=worktree.name,
        omx_root=str(omx_root),
        transport="omx",
    )
    started_at = _utc_timestamp_from_epoch()
    try:
        process = subprocess.Popen(
            popen_command,
            cwd=str(Path(worktree.root).resolve()),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except OSError as exc:
        return str(exc)
    spawn_payload = _omx_spawn_metadata_payload(
        process=process,
        command=tuple(command),
        popen_command=tuple(popen_command),
        worktree=worktree,
        omx_root=omx_root,
        started_at=started_at,
        madmax=wants_bypass,
    )
    runtime._emit("planning.agent_launch.omx_spawn.started", **spawn_payload)
    if process.poll() is not None:
        if _read_omx_session_id(runtime, worktree):
            return None
        try:
            stdout, stderr = process.communicate(timeout=0.5)
        except TypeError:
            stdout, stderr = process.communicate()
        except Exception:
            stdout, stderr = "", ""
        error = _omx_spawn_failure_text(
            returncode=getattr(process, "returncode", None),
            stdout=stdout,
            stderr=stderr,
        )
        runtime._emit(
            "planning.agent_launch.omx_spawn.failed",
            **spawn_payload,
            returncode=getattr(process, "returncode", None),
            error=error,
            stdout_excerpt=_bounded_process_output_excerpt(stdout),
            stderr_excerpt=_bounded_process_output_excerpt(stderr),
        )
        return error
    process_stdout = getattr(process, "stdout", None)
    if process_stdout is not None:
        process_stdout.close()
    process_stderr = getattr(process, "stderr", None)
    if process_stderr is not None:
        process_stderr.close()
    _retain_omx_spawn_process(
        runtime,
        _OmxSpawnProcessRecord(
            process=process,
            command=tuple(command),
            popen_command=tuple(popen_command),
            worktree_name=worktree.name,
            worktree_root=Path(worktree.root).resolve(strict=False),
            omx_root=Path(omx_root).resolve(strict=False),
            started_at=started_at,
            madmax=wants_bypass,
        ),
    )
    return None


__all__ = tuple(name for name in globals() if not name.startswith("__"))
