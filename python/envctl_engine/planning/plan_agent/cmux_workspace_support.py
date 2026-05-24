from __future__ import annotations

import json
import re
from typing import Any, Literal

from envctl_engine.planning.plan_agent.config import PlanAgentLaunchConfig
from envctl_engine.planning.plan_agent.models import _WorkspaceLaunchTarget


def surface_id_from_output(raw: str) -> str | None:
    for token in raw.replace("\n", " ").split():
        normalized = token.strip()
        if normalized.startswith("surface:"):
            return normalized
    return None


def resolve_workspace_id(
    runtime: Any,
    launch_config: PlanAgentLaunchConfig,
    *,
    workspace_mode: Literal["implementation", "current", "reviews"] = "implementation",
) -> str | None:
    if launch_config.cmux_workspace:
        return resolve_configured_workspace_id(runtime, launch_config.cmux_workspace)
    _, target_ref = default_workspace_target(runtime, launch_config, workspace_mode=workspace_mode)
    return target_ref


def ensure_workspace_id(
    runtime: Any,
    launch_config: PlanAgentLaunchConfig,
    *,
    workspace_mode: Literal["implementation", "current", "reviews"] = "implementation",
    event_prefix: str = "planning.agent_launch",
) -> _WorkspaceLaunchTarget | None:
    if launch_config.cmux_workspace:
        return ensure_configured_workspace_id(runtime, launch_config.cmux_workspace, event_prefix=event_prefix)
    target_title, resolved = default_workspace_target(runtime, launch_config, workspace_mode=workspace_mode)
    if not target_title:
        return None
    if resolved:
        return _WorkspaceLaunchTarget(workspace_id=resolved, created=False)
    created_target, error = create_named_workspace(runtime, title=target_title, event_prefix=event_prefix)
    if error is not None:
        runtime._emit(f"{event_prefix}.failed", reason="workspace_create_failed", workspace=target_title, error=error)
        return None
    return created_target


def default_target_workspace_title(
    runtime: Any,
    launch_config: PlanAgentLaunchConfig,
    *,
    workspace_mode: Literal["implementation", "current", "reviews"] = "implementation",
) -> str | None:
    current_title, _ = default_workspace_target(runtime, launch_config, workspace_mode=workspace_mode)
    return current_title


def default_workspace_target(
    runtime: Any,
    launch_config: PlanAgentLaunchConfig,
    *,
    workspace_mode: Literal["implementation", "current", "reviews"] = "implementation",
) -> tuple[str | None, str | None]:
    if missing_required_cmux_context(runtime, launch_config):
        return None, None
    entries = list_workspaces(runtime)
    current_title = current_workspace_title(
        runtime,
        require_cmux_context=launch_config.require_cmux_context,
        workspace_entries=entries,
    )
    if not current_title:
        return None, None
    if workspace_mode == "current":
        target_title = current_title
    else:
        suffix = " reviews" if workspace_mode == "reviews" else " implementation"
        target_title = current_title if current_title.endswith(suffix) else f"{current_title}{suffix}"
    for workspace_ref, workspace_title in entries:
        if workspace_title == target_title:
            return target_title, workspace_ref
    return target_title, None


def missing_required_cmux_context(runtime: Any, launch_config: PlanAgentLaunchConfig) -> bool:
    if launch_config.cmux_workspace:
        return False
    if not launch_config.require_cmux_context:
        return False
    return not str(getattr(runtime, "env", {}).get("CMUX_WORKSPACE_ID", "")).strip()


def current_workspace_title(
    runtime: Any,
    *,
    require_cmux_context: bool,
    workspace_entries: tuple[tuple[str, str], ...] | None = None,
) -> str | None:
    entries = workspace_entries if workspace_entries is not None else list_workspaces(runtime)
    env_workspace = str(getattr(runtime, "env", {}).get("CMUX_WORKSPACE_ID", "")).strip()
    if env_workspace:
        for workspace_ref, workspace_title in entries:
            if workspace_ref == env_workspace:
                return workspace_title
        identified_ref = identify_workspace_ref(runtime)
        if identified_ref:
            for workspace_ref, workspace_title in entries:
                if workspace_ref == identified_ref:
                    return workspace_title
        return None
    if not require_cmux_context:
        if entries:
            return entries[0][1]
        current_ref = current_workspace_ref(runtime, require_cmux_context=False)
        if not current_ref:
            return None
        for workspace_ref, workspace_title in entries:
            if workspace_ref == current_ref:
                return workspace_title
    return None


def current_workspace_ref(runtime: Any, *, require_cmux_context: bool) -> str | None:
    env_workspace = str(getattr(runtime, "env", {}).get("CMUX_WORKSPACE_ID", "")).strip()
    if env_workspace:
        return env_workspace
    if require_cmux_context:
        return None
    try:
        result = runtime.process_runner.run(
            ["cmux", "current-workspace"],
            cwd=runtime.config.base_dir,
            env=getattr(runtime, "env", {}),
            timeout=10.0,
        )
    except OSError:
        return None
    if getattr(result, "returncode", 1) != 0:
        return None
    return str(getattr(result, "stdout", "")).strip() or None


def identify_workspace_ref(runtime: Any) -> str | None:
    try:
        result = runtime.process_runner.run(
            ["cmux", "identify"],
            cwd=runtime.config.base_dir,
            env=getattr(runtime, "env", {}),
            timeout=10.0,
        )
    except OSError:
        return None
    if getattr(result, "returncode", 1) != 0:
        return None
    return workspace_ref_from_identify_output(str(getattr(result, "stdout", "")))


def workspace_ref_from_identify_output(raw: str) -> str | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    for key in ("caller", "focused"):
        entry = payload.get(key)
        if not isinstance(entry, dict):
            continue
        workspace_ref = str(entry.get("workspace_ref", "")).strip()
        if workspace_ref:
            return workspace_ref
    return None


def resolve_configured_workspace_id(runtime: Any, configured: str) -> str | None:
    normalized = str(configured).strip()
    if not normalized:
        return None
    if looks_like_workspace_handle(normalized):
        return normalized
    resolved = resolve_workspace_ref_by_title(runtime, normalized)
    return resolved


def ensure_configured_workspace_id(
    runtime: Any,
    configured: str,
    *,
    event_prefix: str = "planning.agent_launch",
) -> _WorkspaceLaunchTarget | None:
    normalized = str(configured).strip()
    if not normalized:
        return None
    if looks_like_workspace_handle(normalized):
        return _WorkspaceLaunchTarget(workspace_id=normalized, created=False)
    resolved = resolve_workspace_ref_by_title(runtime, normalized)
    if resolved:
        return _WorkspaceLaunchTarget(workspace_id=resolved, created=False)
    created_target, error = create_named_workspace(runtime, title=normalized, event_prefix=event_prefix)
    if error is not None:
        runtime._emit(f"{event_prefix}.failed", reason="workspace_create_failed", workspace=normalized, error=error)
        return None
    return created_target


def looks_like_workspace_handle(value: str) -> bool:
    normalized = str(value).strip()
    if not normalized:
        return False
    if normalized.startswith("workspace:"):
        return True
    if normalized.isdigit():
        return True
    return bool(
        re.fullmatch(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
            normalized,
        )
    )


def resolve_workspace_ref_by_title(runtime: Any, title: str) -> str | None:
    for workspace_ref, workspace_title in list_workspaces(runtime):
        if workspace_title == str(title).strip():
            return workspace_ref
    return None


def list_workspaces(runtime: Any) -> tuple[tuple[str, str], ...]:
    try:
        result = runtime.process_runner.run(
            ["cmux", "list-workspaces"],
            cwd=runtime.config.base_dir,
            env=getattr(runtime, "env", {}),
            timeout=10.0,
        )
    except OSError:
        return ()
    if getattr(result, "returncode", 1) != 0:
        return ()
    return workspace_entries_from_list_output(str(getattr(result, "stdout", "")))


def workspace_entries_from_list_output(raw: str) -> tuple[tuple[str, str], ...]:
    entries: list[tuple[str, str]] = []
    pattern = re.compile(r"^\s*(?:\*\s+)?(workspace:\S+)\s+(.*?)(?:\s+\[[^\]]+\])?\s*$")
    for line in raw.splitlines():
        match = pattern.match(line)
        if match is None:
            continue
        workspace_ref = str(match.group(1) or "").strip()
        workspace_title = str(match.group(2) or "").strip()
        if workspace_ref and workspace_title:
            entries.append((workspace_ref, workspace_title))
    return tuple(entries)


def surface_ids_from_list_output(raw: str) -> tuple[str, ...]:
    surface_ids: list[str] = []
    seen: set[str] = set()
    for token in raw.replace("\n", " ").split():
        normalized = token.strip()
        if not re.fullmatch(r"surface:\d+", normalized):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        surface_ids.append(normalized)
    return tuple(surface_ids)


def list_workspace_surfaces(runtime: Any, *, workspace_id: str) -> tuple[str, ...] | None:
    try:
        result = runtime.process_runner.run(
            ["cmux", "list-pane-surfaces", "--workspace", workspace_id],
            cwd=runtime.config.base_dir,
            env=getattr(runtime, "env", {}),
            timeout=10.0,
        )
    except OSError:
        return None
    if getattr(result, "returncode", 1) != 0:
        return None
    return surface_ids_from_list_output(str(getattr(result, "stdout", "")))


def starter_surface_for_new_workspace(runtime: Any, *, workspace_id: str) -> tuple[str | None, str, int | None]:
    surface_ids = list_workspace_surfaces(runtime, workspace_id=workspace_id)
    if surface_ids is None:
        return None, "probe_failed", None
    if len(surface_ids) == 1:
        return surface_ids[0], "single", 1
    if not surface_ids:
        return None, "none", 0
    return None, "ambiguous", len(surface_ids)


def create_named_workspace(
    runtime: Any,
    *,
    title: str,
    event_prefix: str = "planning.agent_launch",
) -> tuple[_WorkspaceLaunchTarget | None, str | None]:
    create_result = runtime.process_runner.run(
        ["cmux", "new-workspace", "--cwd", str(runtime.config.base_dir)],
        cwd=runtime.config.base_dir,
        env=getattr(runtime, "env", {}),
        timeout=10.0,
    )
    if getattr(create_result, "returncode", 1) != 0:
        return None, completed_process_error_text(create_result)
    workspace_ref = workspace_ref_from_command_output(str(getattr(create_result, "stdout", "")))
    if workspace_ref is None:
        current_result = runtime.process_runner.run(
            ["cmux", "current-workspace"],
            cwd=runtime.config.base_dir,
            env=getattr(runtime, "env", {}),
            timeout=10.0,
        )
        if getattr(current_result, "returncode", 1) != 0:
            return None, completed_process_error_text(current_result)
        workspace_ref = str(getattr(current_result, "stdout", "")).strip() or None
    if workspace_ref is None:
        return None, "workspace_create_failed"
    rename_result = runtime.process_runner.run(
        ["cmux", "rename-workspace", "--workspace", workspace_ref, title],
        cwd=runtime.config.base_dir,
        env=getattr(runtime, "env", {}),
        timeout=10.0,
    )
    if getattr(rename_result, "returncode", 1) != 0:
        return None, completed_process_error_text(rename_result)
    runtime._emit(f"{event_prefix}.workspace_created", workspace_id=workspace_ref, title=title)
    starter_surface_id, probe_result, surface_count = starter_surface_for_new_workspace(
        runtime,
        workspace_id=workspace_ref,
    )
    probe_payload: dict[str, object] = {
        "workspace_id": workspace_ref,
        "result": probe_result,
    }
    if surface_count is not None:
        probe_payload["surface_count"] = surface_count
    if starter_surface_id is not None:
        probe_payload["surface_id"] = starter_surface_id
    runtime._emit(f"{event_prefix}.workspace_surface_probe", **probe_payload)
    return (
        _WorkspaceLaunchTarget(
            workspace_id=workspace_ref,
            created=True,
            starter_surface_id=starter_surface_id,
            starter_surface_probe_result=probe_result,
        ),
        None,
    )


def workspace_ref_from_command_output(raw: str) -> str | None:
    for token in raw.replace("\n", " ").split():
        normalized = token.strip()
        if normalized.startswith("workspace:"):
            return normalized
    return None


def completed_process_error_text(result: object) -> str:
    stderr = str(getattr(result, "stderr", "")).strip()
    stdout = str(getattr(result, "stdout", "")).strip()
    if stderr:
        return stderr
    if stdout:
        return stdout
    return f"exit:{getattr(result, 'returncode', 1)}"
