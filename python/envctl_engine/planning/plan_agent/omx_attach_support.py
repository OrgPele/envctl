from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from envctl_engine.planning.plan_agent.constants import _OMX_SESSION_STATE_RELATIVE_PATH
from envctl_engine.planning.plan_agent.models import (
    CreatedPlanWorktree,
    PlanAgentAttachTarget,
    _OmxSessionRecord,
)


OmxRuntimeRootForWorktreeFn = Callable[..., Path]
RunTmuxProbeFn = Callable[..., Any]
OmxWorktreeTmuxPrefixesFn = Callable[[CreatedPlanWorktree], tuple[str, ...]]
OmxPayloadCandidatesFn = Callable[[_OmxSessionRecord, CreatedPlanWorktree], list[str]]
FindOmxTmuxPanesForWorktreeFn = Callable[..., list[tuple[str, str]]]
TmuxSessionExistsFn = Callable[..., bool]
TmuxActivePaneIdFn = Callable[..., str]
GuidanceAttachCommandFn = Callable[[str], tuple[str, ...]]
AttachTargetFromRecordFn = Callable[..., PlanAgentAttachTarget | None]
AttachTargetFromPaneFallbackFn = Callable[..., PlanAgentAttachTarget | None]
CombinedExclusionsFn = Callable[..., tuple[str, ...]]
PreviousSessionNamesFn = Callable[..., tuple[str, ...]]
SleepFn = Callable[[float], None]
MonotonicFn = Callable[[], float]


def omx_session_state_path_for_root(omx_root: Path) -> Path:
    return Path(omx_root).expanduser().resolve(strict=False) / _OMX_SESSION_STATE_RELATIVE_PATH


def omx_session_state_path(worktree_root: Path) -> Path:
    return omx_session_state_path_for_root(Path(worktree_root).resolve())


def read_omx_session_payload_from_path(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def read_omx_session_payload(worktree_root: Path) -> dict[str, object] | None:
    return read_omx_session_payload_from_path(omx_session_state_path(worktree_root))


def read_omx_session_payload_from_root(omx_root: Path) -> dict[str, object] | None:
    return read_omx_session_payload_from_path(omx_session_state_path_for_root(omx_root))


def omx_session_records_for_worktree(
    runtime: Any,
    worktree: CreatedPlanWorktree,
    *,
    omx_runtime_root_for_worktree_fn: OmxRuntimeRootForWorktreeFn,
) -> list[_OmxSessionRecord]:
    roots = [
        omx_runtime_root_for_worktree_fn(runtime, worktree),
        Path(worktree.root).expanduser().resolve(strict=False),
    ]
    records: list[_OmxSessionRecord] = []
    seen_paths: set[Path] = set()
    for root in roots:
        state_path = omx_session_state_path_for_root(root)
        if state_path in seen_paths:
            continue
        seen_paths.add(state_path)
        payload = read_omx_session_payload_from_path(state_path)
        if payload is None:
            continue
        records.append(_OmxSessionRecord(omx_root=root, state_path=state_path, payload=payload))
    return records


def record_cwd_matches_worktree(record: _OmxSessionRecord, worktree: CreatedPlanWorktree) -> bool:
    raw_cwd = record.payload.get("cwd")
    if not isinstance(raw_cwd, str) or not raw_cwd.strip():
        return True
    candidate = Path(raw_cwd).expanduser().resolve(strict=False)
    return candidate == Path(worktree.root).expanduser().resolve(strict=False)


def read_omx_session_payload_for_worktree(
    *,
    records: Sequence[_OmxSessionRecord],
    worktree: CreatedPlanWorktree,
) -> dict[str, object] | None:
    for record in records:
        if record_cwd_matches_worktree(record, worktree):
            return record.payload
    return None


def read_omx_session_id(
    *,
    records: Sequence[_OmxSessionRecord],
    worktree: CreatedPlanWorktree,
) -> str:
    payload = read_omx_session_payload_for_worktree(records=records, worktree=worktree) or {}
    value = payload.get("session_id")
    return str(value).strip() if isinstance(value, str) else ""


def read_omx_session_ids(
    *,
    records: Sequence[_OmxSessionRecord],
    worktree: CreatedPlanWorktree,
) -> tuple[str, ...]:
    values: list[str] = []
    for record in records:
        if not record_cwd_matches_worktree(record, worktree):
            continue
        value = record.payload.get("session_id")
        session_id = str(value).strip() if isinstance(value, str) else ""
        if session_id and session_id not in values:
            values.append(session_id)
    return tuple(values)


def omx_payload_candidates(
    record: _OmxSessionRecord,
    worktree: CreatedPlanWorktree,
    *,
    omx_tmux_session_name_fn: Callable[[Path, str], str],
) -> list[str]:
    session_id = str(record.payload.get("session_id") or "").strip()
    if not session_id:
        return []
    candidates: list[str] = []
    native_session_id = str(record.payload.get("native_session_id") or "").strip()
    if native_session_id:
        candidates.append(native_session_id)
    candidates.append(omx_tmux_session_name_fn(worktree.root, session_id))
    return candidates


def previous_omx_tmux_session_names_for_worktree(
    records: Sequence[_OmxSessionRecord],
    worktree: CreatedPlanWorktree,
    *,
    omx_payload_candidates_fn: OmxPayloadCandidatesFn,
    previous_session_id: str = "",
    previous_session_ids: tuple[str, ...] = (),
) -> tuple[str, ...]:
    previous = {str(value).strip() for value in previous_session_ids if str(value).strip()}
    if str(previous_session_id).strip():
        previous.add(str(previous_session_id).strip())
    if not previous:
        return ()
    names: list[str] = []
    for record in records:
        if not record_cwd_matches_worktree(record, worktree):
            continue
        session_id = str(record.payload.get("session_id") or "").strip()
        if session_id not in previous:
            continue
        for candidate in omx_payload_candidates_fn(record, worktree):
            if candidate and candidate not in names:
                names.append(candidate)
    return tuple(names)


def combined_omx_tmux_exclusions(*groups: tuple[str, ...]) -> tuple[str, ...]:
    names: list[str] = []
    for group in groups:
        for value in group:
            name = str(value).strip()
            if name and name not in names:
                names.append(name)
    return tuple(names)


def omx_worktree_tmux_prefixes(
    worktree: CreatedPlanWorktree,
    *,
    omx_tmux_dir_token_fn: Callable[[Path], str],
    sanitize_omx_tmux_token_fn: Callable[[str], str],
) -> tuple[str, ...]:
    prefixes = [f"omx-{omx_tmux_dir_token_fn(worktree.root)}-"]
    name_prefix = f"omx-{sanitize_omx_tmux_token_fn(worktree.name)}-"
    if name_prefix not in prefixes:
        prefixes.append(name_prefix)
    return tuple(prefixes)


def find_omx_tmux_panes_for_worktree(
    runtime: Any,
    worktree: CreatedPlanWorktree,
    *,
    run_tmux_probe_fn: RunTmuxProbeFn,
    omx_worktree_tmux_prefixes_fn: OmxWorktreeTmuxPrefixesFn,
) -> list[tuple[str, str]]:
    separator_pane = "|||ENVCTL_TMUX_PANE|||"
    separator_path = "|||ENVCTL_TMUX_PATH|||"
    result = run_tmux_probe_fn(
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
    prefixes = omx_worktree_tmux_prefixes_fn(worktree)
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


def attach_target_from_omx_record(
    runtime: Any,
    *,
    repo_root: Path,
    worktree: CreatedPlanWorktree,
    record: _OmxSessionRecord,
    attach_via: str,
    omx_payload_candidates_fn: OmxPayloadCandidatesFn,
    find_omx_tmux_panes_for_worktree_fn: FindOmxTmuxPanesForWorktreeFn,
    tmux_session_exists_fn: TmuxSessionExistsFn,
    tmux_active_pane_id_fn: TmuxActivePaneIdFn,
    guidance_attach_command_fn: GuidanceAttachCommandFn,
    previous_session_id: str = "",
    previous_session_ids: tuple[str, ...] = (),
    candidates_checked: list[str] | None = None,
    excluded_session_names: tuple[str, ...] = (),
) -> PlanAgentAttachTarget | None:
    if not record_cwd_matches_worktree(record, worktree):
        return None
    session_id = str(record.payload.get("session_id") or "").strip()
    if not session_id:
        return None
    previous = {str(value).strip() for value in previous_session_ids if str(value).strip()}
    if str(previous_session_id).strip():
        previous.add(str(previous_session_id).strip())
    if session_id in previous:
        return None
    for candidate in omx_payload_candidates_fn(record, worktree):
        if candidates_checked is not None and candidate not in candidates_checked:
            candidates_checked.append(candidate)
        if not candidate or not tmux_session_exists_fn(runtime, candidate):
            continue
        return PlanAgentAttachTarget(
            repo_root=repo_root,
            session_name=candidate,
            window_name=tmux_active_pane_id_fn(runtime, candidate),
            attach_via=attach_via,
            attach_command=guidance_attach_command_fn(candidate),
        )
    excluded = {str(value).strip() for value in excluded_session_names if str(value).strip()}
    for session_name, pane_id in find_omx_tmux_panes_for_worktree_fn(runtime, worktree):
        if candidates_checked is not None and session_name not in candidates_checked:
            candidates_checked.append(session_name)
        if session_name in excluded:
            continue
        return PlanAgentAttachTarget(
            repo_root=repo_root,
            session_name=session_name,
            window_name=pane_id,
            attach_via=attach_via,
            attach_command=guidance_attach_command_fn(session_name),
        )
    return None


def attach_target_from_omx_tmux_pane_fallback(
    runtime: Any,
    *,
    repo_root: Path,
    worktree: CreatedPlanWorktree,
    attach_via: str,
    find_omx_tmux_panes_for_worktree_fn: FindOmxTmuxPanesForWorktreeFn,
    guidance_attach_command_fn: GuidanceAttachCommandFn,
    candidates_checked: list[str] | None = None,
    excluded_session_names: tuple[str, ...] = (),
) -> PlanAgentAttachTarget | None:
    excluded = {str(value).strip() for value in excluded_session_names if str(value).strip()}
    for session_name, pane_id in find_omx_tmux_panes_for_worktree_fn(runtime, worktree):
        if candidates_checked is not None and session_name not in candidates_checked:
            candidates_checked.append(session_name)
        if session_name in excluded:
            continue
        return PlanAgentAttachTarget(
            repo_root=repo_root,
            session_name=session_name,
            window_name=pane_id,
            attach_via=attach_via,
            attach_command=guidance_attach_command_fn(session_name),
        )
    return None


def attach_target_state_check(
    *,
    session_name: str,
    worktree: CreatedPlanWorktree | None,
    records: Sequence[_OmxSessionRecord],
    omx_payload_candidates_fn: OmxPayloadCandidatesFn,
) -> tuple[bool | None, dict[str, object]]:
    if worktree is None:
        return None, {}
    if not records:
        return None, {}
    current_candidates: list[str] = []
    wrong_worktree_candidates: list[str] = []
    records_checked = 0
    wrong_worktree_records = 0
    for record in records:
        candidates = [candidate for candidate in omx_payload_candidates_fn(record, worktree) if candidate]
        if not candidates:
            continue
        records_checked += 1
        if record_cwd_matches_worktree(record, worktree):
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


def attach_discovery_diagnostics(
    runtime: Any,
    worktree: CreatedPlanWorktree,
    *,
    omx_runtime_root_for_worktree_fn: OmxRuntimeRootForWorktreeFn,
    find_omx_tmux_panes_for_worktree_fn: FindOmxTmuxPanesForWorktreeFn,
    omx_payload_candidates_fn: OmxPayloadCandidatesFn,
) -> dict[str, object]:
    selected_root = omx_runtime_root_for_worktree_fn(runtime, worktree)
    selected_state_path = omx_session_state_path_for_root(selected_root)
    records = omx_session_records_for_worktree(
        runtime,
        worktree,
        omx_runtime_root_for_worktree_fn=omx_runtime_root_for_worktree_fn,
    )
    payload = records[0].payload if records else {}
    session_id = str(payload.get("session_id") or "").strip() if isinstance(payload, dict) else ""
    candidates: list[str] = []
    for record in records:
        if not record_cwd_matches_worktree(record, worktree):
            continue
        for candidate in omx_payload_candidates_fn(record, worktree):
            if candidate not in candidates:
                candidates.append(candidate)
    panes = find_omx_tmux_panes_for_worktree_fn(runtime, worktree)
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


def find_existing_omx_attach_target(
    runtime: Any,
    *,
    repo_root: Path,
    created_worktrees: tuple[CreatedPlanWorktree, ...],
    omx_session_records_for_worktree_fn: Callable[..., list[_OmxSessionRecord]],
    attach_target_from_omx_record_fn: AttachTargetFromRecordFn,
    attach_target_from_pane_fallback_fn: AttachTargetFromPaneFallbackFn,
) -> PlanAgentAttachTarget | None:
    attach_via = "attach-session"
    for worktree in created_worktrees:
        for record in omx_session_records_for_worktree_fn(runtime, worktree):
            attach_target = attach_target_from_omx_record_fn(
                runtime,
                repo_root=repo_root,
                worktree=worktree,
                record=record,
                attach_via=attach_via,
            )
            if attach_target is not None:
                return attach_target
        attach_target = attach_target_from_pane_fallback_fn(
            runtime,
            repo_root=repo_root,
            worktree=worktree,
            attach_via=attach_via,
        )
        if attach_target is not None:
            return attach_target
    return None


def wait_for_omx_attach_target(
    runtime: Any,
    *,
    repo_root: Path,
    worktree: CreatedPlanWorktree,
    previous_session_id: str,
    previous_session_ids: tuple[str, ...] = (),
    previous_tmux_session_names: tuple[str, ...] = (),
    attach_via: str,
    session_ready_timeout_seconds: float,
    session_ready_poll_interval_seconds: float,
    previous_session_names_fn: PreviousSessionNamesFn,
    combined_exclusions_fn: CombinedExclusionsFn,
    omx_session_records_for_worktree_fn: Callable[..., list[_OmxSessionRecord]],
    attach_target_from_omx_record_fn: AttachTargetFromRecordFn,
    attach_target_from_pane_fallback_fn: AttachTargetFromPaneFallbackFn,
    monotonic_fn: MonotonicFn = time.monotonic,
    sleep_fn: SleepFn = time.sleep,
) -> PlanAgentAttachTarget | None:
    deadline = monotonic_fn() + session_ready_timeout_seconds
    previous = str(previous_session_id).strip()
    excluded_session_names = combined_exclusions_fn(
        previous_session_names_fn(
            runtime,
            worktree,
            previous_session_id=previous,
            previous_session_ids=previous_session_ids,
        ),
        previous_tmux_session_names,
    )

    def _discover_attach_target() -> PlanAgentAttachTarget | None:
        for record in omx_session_records_for_worktree_fn(runtime, worktree):
            attach_target = attach_target_from_omx_record_fn(
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
        attach_target = attach_target_from_pane_fallback_fn(
            runtime,
            repo_root=repo_root,
            worktree=worktree,
            attach_via=attach_via,
            excluded_session_names=excluded_session_names,
        )
        if attach_target is not None:
            return attach_target
        return None

    while monotonic_fn() < deadline:
        attach_target = _discover_attach_target()
        if attach_target is not None:
            return attach_target
        sleep_fn(session_ready_poll_interval_seconds)
    return _discover_attach_target()
