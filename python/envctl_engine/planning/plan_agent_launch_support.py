from __future__ import annotations

import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from envctl_engine.config import EngineConfig
from envctl_engine.shared.parsing import parse_bool

_SUPPORTED_PLAN_AGENT_CLIS = frozenset({"codex", "opencode"})
_DEFAULT_PRESET = "implement_task"
_DEFAULT_SHELL = "zsh"
_SURFACE_READY_DELAY_SECONDS = 0.15
_DEFAULT_CLI_READY_DELAY_SECONDS = 0.35
_CLI_READY_DELAY_SECONDS_BY_CLI = {
    "codex": 5.0,
    "opencode": 5.0,
}
_CLI_READY_POLL_INTERVAL_SECONDS = 0.1
_READ_SCREEN_LINE_COUNT = 80
_PROMPT_PRE_SUBMIT_DELAY_SECONDS = 0.3
_PROMPT_SUBMIT_READY_DELAY_SECONDS = 0.15
_PROMPT_SUBMIT_READY_TIMEOUT_SECONDS = 1.0
_PROMPT_SUBMIT_READY_POLL_INTERVAL_SECONDS = 0.1
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_CODEX_READY_PROMPT_RE = re.compile(r"^[ \t]*[>›][ \t]*.*$")
_CODEX_LOADING_MARKERS = (
    "booting mcp server",
    "starting mcp server",
    "model:     loading",
    "model: loading",
)
_CODEX_READY_MARKERS = (
    "openai codex",
    "model:",
    "directory:",
)
_OPENCODE_READY_PROMPT_RE = re.compile(r"^[ \t]*[>›❯»][ \t]*.*$")
_OPENCODE_LOADING_MARKERS = (
    "loading",
    "starting",
    "initializing",
    "please wait",
)
_OPENCODE_READY_MARKERS = (
    "ask anything",
    "ctrl+p commands",
    "/status",
)


@dataclass(slots=True, frozen=True)
class CreatedPlanWorktree:
    name: str
    root: Path
    plan_file: str


@dataclass(slots=True)
class PlanWorktreeSyncResult:
    raw_projects: list[tuple[str, Path]]
    created_worktrees: tuple[CreatedPlanWorktree, ...] = ()
    removed_worktrees: tuple[str, ...] = ()
    archived_plan_files: tuple[str, ...] = ()
    error: str | None = None

    def __iter__(self):
        yield self.raw_projects
        yield self.error


@dataclass(slots=True)
class PlanSelectionResult:
    raw_projects: list[tuple[str, Path]]
    selected_contexts: list[Any]
    created_worktrees: tuple[CreatedPlanWorktree, ...] = ()
    error: str | None = None


@dataclass(slots=True, frozen=True)
class PlanAgentLaunchConfig:
    enabled: bool
    cli: str
    cli_command: str
    preset: str
    shell: str
    require_cmux_context: bool
    cmux_workspace: str


@dataclass(slots=True, frozen=True)
class PlanAgentLaunchOutcome:
    worktree_name: str
    worktree_root: Path
    surface_id: str | None
    status: str
    reason: str | None = None


@dataclass(slots=True)
class PlanAgentLaunchResult:
    status: str
    reason: str
    outcomes: tuple[PlanAgentLaunchOutcome, ...] = ()


def resolve_plan_agent_launch_config(config: EngineConfig, env: dict[str, str] | None = None) -> PlanAgentLaunchConfig:
    env_map = dict(env or {})
    cli = str(
        env_map.get("ENVCTL_PLAN_AGENT_CLI")
        or config.raw.get("ENVCTL_PLAN_AGENT_CLI")
        or "codex"
    ).strip().lower() or "codex"
    cli_command = str(
        env_map.get("ENVCTL_PLAN_AGENT_CLI_CMD")
        or config.raw.get("ENVCTL_PLAN_AGENT_CLI_CMD")
        or cli
    ).strip() or cli
    preset = str(
        env_map.get("ENVCTL_PLAN_AGENT_PRESET")
        or config.raw.get("ENVCTL_PLAN_AGENT_PRESET")
        or _DEFAULT_PRESET
    ).strip() or _DEFAULT_PRESET
    shell = str(
        env_map.get("ENVCTL_PLAN_AGENT_SHELL")
        or config.raw.get("ENVCTL_PLAN_AGENT_SHELL")
        or _DEFAULT_SHELL
    ).strip() or _DEFAULT_SHELL
    cmux_workspace = str(
        env_map.get("ENVCTL_PLAN_AGENT_CMUX_WORKSPACE")
        or config.raw.get("ENVCTL_PLAN_AGENT_CMUX_WORKSPACE")
        or ""
    ).strip()
    enabled = parse_bool(
        env_map.get("ENVCTL_PLAN_AGENT_TERMINALS_ENABLE")
        or config.raw.get("ENVCTL_PLAN_AGENT_TERMINALS_ENABLE"),
        False,
    ) or bool(cmux_workspace)
    return PlanAgentLaunchConfig(
        enabled=enabled,
        cli=cli,
        cli_command=cli_command,
        preset=preset,
        shell=shell,
        require_cmux_context=parse_bool(
            env_map.get("ENVCTL_PLAN_AGENT_REQUIRE_CMUX_CONTEXT")
            or config.raw.get("ENVCTL_PLAN_AGENT_REQUIRE_CMUX_CONTEXT"),
            True,
        ),
        cmux_workspace=cmux_workspace,
    )


def plan_agent_launch_prereq_commands(
    config: EngineConfig,
    env: dict[str, str] | None = None,
) -> tuple[str, ...]:
    launch_config = resolve_plan_agent_launch_config(config, env)
    if not launch_config.enabled:
        return ()
    cli_executable = _command_executable(launch_config.cli_command)
    if not cli_executable:
        return ("cmux",)
    return ("cmux", cli_executable)


def inspect_plan_agent_launch(runtime: Any, *, route: object) -> dict[str, object]:
    launch_config = resolve_plan_agent_launch_config(runtime.config, getattr(runtime, "env", {}))
    workspace_id = _resolve_workspace_id(runtime, launch_config)
    payload: dict[str, object] = {
        "enabled": launch_config.enabled,
        "cli": launch_config.cli,
        "preset": launch_config.preset,
        "shell": launch_config.shell,
        "require_cmux_context": launch_config.require_cmux_context,
        "workspace_id": workspace_id,
        "configured_workspace": launch_config.cmux_workspace or None,
        "reason": "disabled",
    }
    if str(getattr(route, "command", "")).strip() != "plan":
        payload["reason"] = "not_plan_command"
        return payload
    if bool(getattr(route, "flags", {}).get("planning_prs")):
        payload["reason"] = "planning_prs_only"
        return payload
    if not launch_config.enabled:
        return payload
    if launch_config.cmux_workspace:
        payload["reason"] = "awaiting_new_worktrees"
        return payload
    if launch_config.require_cmux_context and not workspace_id:
        payload["reason"] = "missing_cmux_context"
        return payload
    payload["reason"] = "awaiting_new_worktrees"
    return payload


def launch_plan_agent_terminals(
    runtime: Any,
    *,
    route: object,
    created_worktrees: tuple[CreatedPlanWorktree, ...],
) -> PlanAgentLaunchResult:
    launch_config = resolve_plan_agent_launch_config(runtime.config, getattr(runtime, "env", {}))
    base_payload = {
        "enabled": launch_config.enabled,
        "cli": launch_config.cli,
        "created_worktree_count": len(created_worktrees),
    }
    if str(getattr(route, "command", "")).strip() != "plan" or bool(getattr(route, "flags", {}).get("planning_prs")):
        runtime._emit("planning.agent_launch.skipped", reason="inapplicable_route", **base_payload)
        return PlanAgentLaunchResult(status="skipped", reason="inapplicable_route")
    if not launch_config.enabled:
        runtime._emit("planning.agent_launch.skipped", reason="disabled", **base_payload)
        return PlanAgentLaunchResult(status="skipped", reason="disabled")
    if not created_worktrees:
        _print_launch_summary("Plan agent launch skipped: no new worktrees were created.")
        runtime._emit("planning.agent_launch.skipped", reason="no_new_worktrees", **base_payload)
        return PlanAgentLaunchResult(status="skipped", reason="no_new_worktrees")
    missing_commands = _missing_launch_commands(runtime, launch_config)
    if missing_commands:
        message = f"Plan agent launch skipped: missing required executables: {', '.join(missing_commands)}."
        _print_launch_summary(message)
        runtime._emit(
            "planning.agent_launch.failed",
            reason="missing_executables",
            missing=missing_commands,
            **base_payload,
        )
        return PlanAgentLaunchResult(status="failed", reason="missing_executables")
    workspace_id = _ensure_workspace_id(runtime, launch_config)
    if not workspace_id and launch_config.cmux_workspace:
        _print_launch_summary("Plan agent launch failed: unable to resolve or create the configured cmux workspace.")
        return PlanAgentLaunchResult(status="failed", reason="workspace_unavailable")
    if not workspace_id:
        _print_launch_summary("Plan agent launch skipped: current cmux workspace context is unavailable.")
        runtime._emit("planning.agent_launch.skipped", reason="missing_cmux_context", **base_payload)
        return PlanAgentLaunchResult(status="skipped", reason="missing_cmux_context")

    runtime._emit(
        "planning.agent_launch.evaluate",
        reason="ready",
        workspace_id=workspace_id,
        preset=launch_config.preset,
        **base_payload,
    )
    outcomes: list[PlanAgentLaunchOutcome] = []
    for worktree in created_worktrees:
        outcome = _launch_single_worktree(runtime, workspace_id=workspace_id, launch_config=launch_config, worktree=worktree)
        outcomes.append(outcome)

    launched = [item for item in outcomes if item.status == "launched"]
    failed = [item for item in outcomes if item.status == "failed"]
    if failed and launched:
        _print_launch_summary(
            f"Plan agent launch finished with partial success: launched {len(launched)}, failed {len(failed)}."
        )
        return PlanAgentLaunchResult(status="partial", reason="partial_failure", outcomes=tuple(outcomes))
    if failed:
        _print_launch_summary(f"Plan agent launch failed for {len(failed)} worktree(s).")
        return PlanAgentLaunchResult(status="failed", reason="launch_failed", outcomes=tuple(outcomes))
    _print_launch_summary(f"Plan agent launch opened {len(launched)} cmux surface(s).")
    return PlanAgentLaunchResult(status="launched", reason="launched", outcomes=tuple(outcomes))


def _launch_single_worktree(
    runtime: Any,
    *,
    workspace_id: str,
    launch_config: PlanAgentLaunchConfig,
    worktree: CreatedPlanWorktree,
) -> PlanAgentLaunchOutcome:
    surface_id, create_error = _create_surface(runtime, workspace_id=workspace_id)
    if create_error or surface_id is None:
        runtime._emit(
            "planning.agent_launch.failed",
            reason="surface_create_failed",
            workspace_id=workspace_id,
            worktree=worktree.name,
            error=create_error,
        )
        return PlanAgentLaunchOutcome(
            worktree_name=worktree.name,
            worktree_root=worktree.root,
            surface_id=None,
            status="failed",
            reason=create_error or "surface_create_failed",
        )
    _best_effort_restore_caller_focus(runtime, workspace_id=workspace_id, surface_id=surface_id)
    runtime._emit(
        "planning.agent_launch.surface_created",
        workspace_id=workspace_id,
        surface_id=surface_id,
        worktree=worktree.name,
    )
    respawn_command = _surface_respawn_command(launch_config, worktree)
    commands = [
        ["cmux", "rename-tab", "--workspace", workspace_id, "--surface", surface_id, worktree.name],
        ["cmux", "respawn-pane", "--workspace", workspace_id, "--surface", surface_id, "--command", respawn_command],
    ]
    for command in commands:
        error = _run_cmux_command(runtime, command)
        if error is not None:
            return PlanAgentLaunchOutcome(
                worktree_name=worktree.name,
                worktree_root=worktree.root,
                surface_id=surface_id,
                status="failed",
                reason=error,
            )
    time.sleep(_SURFACE_READY_DELAY_SECONDS)
    typed_steps = [_slash_command(launch_config.cli, launch_config.preset)]
    send_errors = _launch_cli_bootstrap_commands(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        launch_config=launch_config,
        worktree=worktree,
    )
    for error in send_errors:
        if error is not None:
            return PlanAgentLaunchOutcome(
                worktree_name=worktree.name,
                worktree_root=worktree.root,
                surface_id=surface_id,
                status="failed",
                reason=error,
            )
    _wait_for_cli_ready(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cli=launch_config.cli,
    )
    final_errors = [
        _send_prompt_text(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            cli=launch_config.cli,
            text=typed_steps[0],
        ),
        _send_surface_key(runtime, workspace_id=workspace_id, surface_id=surface_id, key="ctrl+e"),
    ]
    for error in final_errors:
        if error is not None:
            return PlanAgentLaunchOutcome(
                worktree_name=worktree.name,
                worktree_root=worktree.root,
                surface_id=surface_id,
                status="failed",
                reason=error,
            )
    _wait_for_prompt_picker_ready(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cli=launch_config.cli,
        prompt_text=typed_steps[0],
    )
    submit_error = _send_surface_key(runtime, workspace_id=workspace_id, surface_id=surface_id, key="enter")
    if submit_error is not None:
        return PlanAgentLaunchOutcome(
            worktree_name=worktree.name,
            worktree_root=worktree.root,
            surface_id=surface_id,
            status="failed",
            reason=submit_error,
        )
    _wait_for_prompt_submit_ready(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cli=launch_config.cli,
        prompt_text=typed_steps[0],
    )
    confirm_error = _send_surface_key(runtime, workspace_id=workspace_id, surface_id=surface_id, key="enter")
    if confirm_error is not None:
        return PlanAgentLaunchOutcome(
            worktree_name=worktree.name,
            worktree_root=worktree.root,
            surface_id=surface_id,
            status="failed",
            reason=confirm_error,
        )
    _best_effort_restore_caller_focus(runtime, workspace_id=workspace_id, surface_id=surface_id)
    runtime._emit(
        "planning.agent_launch.command_sent",
        workspace_id=workspace_id,
        surface_id=surface_id,
        worktree=worktree.name,
        preset=launch_config.preset,
    )
    return PlanAgentLaunchOutcome(
        worktree_name=worktree.name,
        worktree_root=worktree.root,
        surface_id=surface_id,
        status="launched",
    )


def _create_surface(runtime: Any, *, workspace_id: str) -> tuple[str | None, str | None]:
    result = runtime.process_runner.run(
        ["cmux", "new-surface", "--workspace", workspace_id],
        cwd=runtime.config.base_dir,
        env=getattr(runtime, "env", {}),
        timeout=10.0,
    )
    if getattr(result, "returncode", 1) != 0:
        return None, _completed_process_error_text(result)
    return _surface_id_from_output(str(getattr(result, "stdout", ""))), None


def _best_effort_restore_caller_focus(runtime: Any, *, workspace_id: str, surface_id: str) -> None:
    env = getattr(runtime, "env", {})
    caller_workspace = str(env.get("CMUX_WORKSPACE_ID", "")).strip() if isinstance(env, dict) else ""
    caller_surface = str(env.get("CMUX_SURFACE_ID", "")).strip() if isinstance(env, dict) else ""
    if caller_workspace and caller_surface and caller_workspace == workspace_id:
        _run_cmux_command_allow_failure(
            runtime,
            [
                "cmux",
                "move-surface",
                "--surface",
                caller_surface,
                "--before",
                surface_id,
                "--workspace",
                workspace_id,
                "--focus",
                "true",
            ],
            reason="focus_restore_failed",
        )
        return
    if caller_workspace and caller_workspace != workspace_id:
        _run_cmux_command_allow_failure(
            runtime,
            ["cmux", "select-workspace", "--workspace", caller_workspace],
            reason="focus_restore_failed",
        )


def _surface_respawn_command(launch_config: PlanAgentLaunchConfig, worktree: CreatedPlanWorktree) -> str:
    _ = worktree
    return launch_config.shell


def _launch_cli_bootstrap_commands(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    launch_config: PlanAgentLaunchConfig,
    worktree: CreatedPlanWorktree,
) -> list[str | None]:
    typed_root = shlex.quote(str(worktree.root))
    return [
        _send_surface_text(runtime, workspace_id=workspace_id, surface_id=surface_id, text=f"cd {typed_root}"),
        _send_surface_key(runtime, workspace_id=workspace_id, surface_id=surface_id, key="enter"),
        _send_surface_text(runtime, workspace_id=workspace_id, surface_id=surface_id, text=launch_config.cli_command),
        _send_surface_key(runtime, workspace_id=workspace_id, surface_id=surface_id, key="enter"),
    ]


def _surface_id_from_output(raw: str) -> str | None:
    for token in raw.replace("\n", " ").split():
        normalized = token.strip()
        if normalized.startswith("surface:"):
            return normalized
    return None


def _resolve_workspace_id(runtime: Any, launch_config: PlanAgentLaunchConfig) -> str | None:
    if launch_config.cmux_workspace:
        return _resolve_configured_workspace_id(runtime, launch_config.cmux_workspace)
    env_workspace = str(getattr(runtime, "env", {}).get("CMUX_WORKSPACE_ID", "")).strip()
    if env_workspace:
        return env_workspace
    if launch_config.require_cmux_context:
        return None
    result = runtime.process_runner.run(
        ["cmux", "current-workspace"],
        cwd=runtime.config.base_dir,
        env=getattr(runtime, "env", {}),
        timeout=10.0,
    )
    if getattr(result, "returncode", 1) != 0:
        return None
    return str(getattr(result, "stdout", "")).strip() or None


def _ensure_workspace_id(runtime: Any, launch_config: PlanAgentLaunchConfig) -> str | None:
    if launch_config.cmux_workspace:
        return _ensure_configured_workspace_id(runtime, launch_config.cmux_workspace)
    return _resolve_workspace_id(runtime, launch_config)


def _resolve_configured_workspace_id(runtime: Any, configured: str) -> str | None:
    normalized = str(configured).strip()
    if not normalized:
        return None
    if _looks_like_workspace_handle(normalized):
        return normalized
    resolved = _resolve_workspace_ref_by_title(runtime, normalized)
    return resolved


def _ensure_configured_workspace_id(runtime: Any, configured: str) -> str | None:
    normalized = str(configured).strip()
    if not normalized:
        return None
    if _looks_like_workspace_handle(normalized):
        return normalized
    resolved = _resolve_workspace_ref_by_title(runtime, normalized)
    if resolved:
        return resolved
    created_ref, error = _create_named_workspace(runtime, title=normalized)
    if error is not None:
        runtime._emit("planning.agent_launch.failed", reason="workspace_create_failed", workspace=normalized, error=error)
        return None
    return created_ref


def _looks_like_workspace_handle(value: str) -> bool:
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


def _resolve_workspace_ref_by_title(runtime: Any, title: str) -> str | None:
    result = runtime.process_runner.run(
        ["cmux", "list-workspaces"],
        cwd=runtime.config.base_dir,
        env=getattr(runtime, "env", {}),
        timeout=10.0,
    )
    if getattr(result, "returncode", 1) != 0:
        return None
    return _workspace_ref_from_list_output(str(getattr(result, "stdout", "")), title=title)


def _workspace_ref_from_list_output(raw: str, *, title: str) -> str | None:
    target = str(title).strip()
    if not target:
        return None
    pattern = re.compile(r"^\s*(?:\*\s+)?(workspace:\S+)\s+(.*?)(?:\s+\[[^\]]+\])?\s*$")
    for line in raw.splitlines():
        match = pattern.match(line)
        if match is None:
            continue
        workspace_ref = str(match.group(1) or "").strip()
        workspace_title = str(match.group(2) or "").strip()
        if workspace_title == target and workspace_ref:
            return workspace_ref
    return None


def _create_named_workspace(runtime: Any, *, title: str) -> tuple[str | None, str | None]:
    create_result = runtime.process_runner.run(
        ["cmux", "new-workspace", "--cwd", str(runtime.config.base_dir)],
        cwd=runtime.config.base_dir,
        env=getattr(runtime, "env", {}),
        timeout=10.0,
    )
    if getattr(create_result, "returncode", 1) != 0:
        return None, _completed_process_error_text(create_result)
    workspace_ref = _workspace_ref_from_command_output(str(getattr(create_result, "stdout", "")))
    if workspace_ref is None:
        current_result = runtime.process_runner.run(
            ["cmux", "current-workspace"],
            cwd=runtime.config.base_dir,
            env=getattr(runtime, "env", {}),
            timeout=10.0,
        )
        if getattr(current_result, "returncode", 1) != 0:
            return None, _completed_process_error_text(current_result)
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
        return None, _completed_process_error_text(rename_result)
    runtime._emit("planning.agent_launch.workspace_created", workspace_id=workspace_ref, title=title)
    return workspace_ref, None


def _workspace_ref_from_command_output(raw: str) -> str | None:
    for token in raw.replace("\n", " ").split():
        normalized = token.strip()
        if normalized.startswith("workspace:"):
            return normalized
    return None


def _send_surface_text(runtime: Any, *, workspace_id: str, surface_id: str, text: str) -> str | None:
    return _run_cmux_command(
        runtime,
        ["cmux", "send", "--workspace", workspace_id, "--surface", surface_id, text],
    )


def _send_prompt_text(runtime: Any, *, workspace_id: str, surface_id: str, cli: str, text: str) -> str | None:
    _ = cli
    return _send_surface_text(runtime, workspace_id=workspace_id, surface_id=surface_id, text=text)


def _send_surface_key(runtime: Any, *, workspace_id: str, surface_id: str, key: str) -> str | None:
    return _run_cmux_command(
        runtime,
        ["cmux", "send-key", "--workspace", workspace_id, "--surface", surface_id, key],
    )


def _run_cmux_command(runtime: Any, command: list[str]) -> str | None:
    result = runtime.process_runner.run(
        command,
        cwd=runtime.config.base_dir,
        env=getattr(runtime, "env", {}),
        timeout=10.0,
    )
    if getattr(result, "returncode", 1) == 0:
        return None
    error = _completed_process_error_text(result)
    runtime._emit("planning.agent_launch.failed", reason="cmux_command_failed", command=command[1], error=error)
    return error


def _run_cmux_command_allow_failure(runtime: Any, command: list[str], *, reason: str) -> None:
    result = runtime.process_runner.run(
        command,
        cwd=runtime.config.base_dir,
        env=getattr(runtime, "env", {}),
        timeout=10.0,
    )
    if getattr(result, "returncode", 1) == 0:
        return
    runtime._emit(
        "planning.agent_launch.notice",
        reason=reason,
        command=command[1],
        error=_completed_process_error_text(result),
    )


def _completed_process_error_text(result: object) -> str:
    stderr = str(getattr(result, "stderr", "")).strip()
    stdout = str(getattr(result, "stdout", "")).strip()
    if stderr:
        return stderr
    if stdout:
        return stdout
    return f"exit:{getattr(result, 'returncode', 1)}"


def _command_executable(raw_command: str) -> str | None:
    try:
        parsed = shlex.split(raw_command)
    except ValueError:
        return None
    if not parsed:
        return None
    return str(parsed[0]).strip() or None


def _missing_launch_commands(runtime: Any, launch_config: PlanAgentLaunchConfig) -> list[str]:
    required = ["cmux"]
    cli_executable = _command_executable(launch_config.cli_command)
    shell_executable = _command_executable(launch_config.shell)
    if cli_executable:
        required.append(cli_executable)
    if shell_executable:
        required.append(shell_executable)
    if launch_config.cli not in _SUPPORTED_PLAN_AGENT_CLIS and not _command_executable(launch_config.cli_command):
        required.append(launch_config.cli)
    missing: list[str] = []
    for command in required:
        if command in missing:
            continue
        if runtime._command_exists(command):
            continue
        missing.append(command)
    return missing


def _cli_ready_delay_seconds(cli: str) -> float:
    normalized = str(cli).strip().lower()
    return float(_CLI_READY_DELAY_SECONDS_BY_CLI.get(normalized, _DEFAULT_CLI_READY_DELAY_SECONDS))


def _wait_for_cli_ready(runtime: Any, *, workspace_id: str, surface_id: str, cli: str) -> None:
    normalized_cli = str(cli).strip().lower()
    timeout_seconds = _cli_ready_delay_seconds(normalized_cli)
    if normalized_cli not in {"codex", "opencode"}:
        time.sleep(timeout_seconds)
        return
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        screen = _read_surface_screen(runtime, workspace_id=workspace_id, surface_id=surface_id)
        if _screen_looks_ready(normalized_cli, screen):
            return
        time.sleep(_CLI_READY_POLL_INTERVAL_SECONDS)


def _read_surface_screen(runtime: Any, *, workspace_id: str, surface_id: str) -> str:
    result = runtime.process_runner.run(
        [
            "cmux",
            "read-screen",
            "--workspace",
            workspace_id,
            "--surface",
            surface_id,
            "--lines",
            str(_READ_SCREEN_LINE_COUNT),
        ],
        cwd=runtime.config.base_dir,
        env=getattr(runtime, "env", {}),
        timeout=10.0,
    )
    if getattr(result, "returncode", 1) != 0:
        return ""
    return str(getattr(result, "stdout", ""))


def _wait_for_prompt_submit_ready(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    cli: str,
    prompt_text: str,
) -> None:
    normalized_cli = str(cli).strip().lower()
    if normalized_cli != "opencode":
        if normalized_cli != "codex":
            time.sleep(_PROMPT_SUBMIT_READY_DELAY_SECONDS)
            return
    deadline = time.monotonic() + _PROMPT_SUBMIT_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        screen = _read_surface_screen(runtime, workspace_id=workspace_id, surface_id=surface_id)
        if _prompt_submit_screen_looks_ready(normalized_cli, screen, prompt_text):
            return
        time.sleep(_PROMPT_SUBMIT_READY_POLL_INTERVAL_SECONDS)


def _wait_for_prompt_picker_ready(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    cli: str,
    prompt_text: str,
) -> None:
    normalized_cli = str(cli).strip().lower()
    if normalized_cli not in {"codex", "opencode"}:
        time.sleep(_PROMPT_PRE_SUBMIT_DELAY_SECONDS)
        return
    deadline = time.monotonic() + _PROMPT_SUBMIT_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        screen = _read_surface_screen(runtime, workspace_id=workspace_id, surface_id=surface_id)
        if _prompt_picker_screen_looks_ready(normalized_cli, screen, prompt_text):
            return
        time.sleep(_PROMPT_SUBMIT_READY_POLL_INTERVAL_SECONDS)


def _prompt_picker_screen_looks_ready(cli: str, screen: str, prompt_text: str) -> bool:
    normalized_cli = str(cli).strip().lower()
    if normalized_cli not in {"codex", "opencode"}:
        return True
    cleaned = _strip_ansi_sequences(screen)
    lower_text = cleaned.lower()
    if "unrecognized command" in lower_text or "no matching items" in lower_text:
        return False
    normalized_prompt = str(prompt_text).strip().lower()
    if not normalized_prompt:
        return False
    return lower_text.count(normalized_prompt) > 1


def _prompt_submit_screen_looks_ready(cli: str, screen: str, prompt_text: str) -> bool:
    normalized_cli = str(cli).strip().lower()
    if normalized_cli not in {"codex", "opencode"}:
        return True
    cleaned = _strip_ansi_sequences(screen)
    lower_text = cleaned.lower()
    if "no matching items" in lower_text:
        return False
    normalized_prompt = str(prompt_text).strip().lower()
    if not normalized_prompt:
        return True
    if lower_text.count(normalized_prompt) != 1:
        return False
    return True


def _screen_looks_ready(cli: str, screen: str) -> bool:
    normalized_cli = str(cli).strip().lower()
    cleaned = _strip_ansi_sequences(screen)
    if normalized_cli == "codex":
        lower_text = cleaned.lower()
        if any(marker in lower_text for marker in _CODEX_LOADING_MARKERS):
            return False
        if not all(marker in lower_text for marker in _CODEX_READY_MARKERS):
            return False
        lines = [line.rstrip() for line in cleaned.splitlines() if line.strip()]
        for line in lines[-6:]:
            if _CODEX_READY_PROMPT_RE.match(line):
                return True
        return False
    if normalized_cli != "opencode":
        return False
    lower_text = cleaned.lower()
    if any(marker in lower_text for marker in _OPENCODE_LOADING_MARKERS):
        return False
    if all(marker in lower_text for marker in _OPENCODE_READY_MARKERS):
        return True
    lines = [line.rstrip() for line in cleaned.splitlines() if line.strip()]
    for line in lines[-6:]:
        if _OPENCODE_READY_PROMPT_RE.match(line):
            return True
    return False


def _strip_ansi_sequences(raw: str) -> str:
    return _ANSI_ESCAPE_RE.sub("", str(raw or "")).replace("\r", "")


def _slash_command(cli: str, preset: str) -> str:
    normalized = str(preset).strip()
    if not normalized:
        normalized = _DEFAULT_PRESET
    trimmed = normalized[1:] if normalized.startswith("/") else normalized
    if str(cli).strip().lower() == "codex":
        if trimmed.startswith("prompts:"):
            return f"/{trimmed}"
        return f"/prompts:{trimmed}"
    return normalized if normalized.startswith("/") else f"/{normalized}"


def _print_launch_summary(message: str) -> None:
    print(message)
