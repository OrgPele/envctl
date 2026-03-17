from __future__ import annotations

import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from envctl_engine.config import EngineConfig
from envctl_engine.shared.parsing import parse_bool

_SUPPORTED_PLAN_AGENT_CLIS = frozenset({"codex", "opencode"})
_DEFAULT_PRESET = "implement_plan"
_DEFAULT_SHELL = "zsh"
_SURFACE_READY_DELAY_SECONDS = 0.15
_CLI_READY_DELAY_SECONDS = 0.35


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
    payload = {
        "enabled": launch_config.enabled,
        "cli": launch_config.cli,
        "preset": launch_config.preset,
        "shell": launch_config.shell,
        "require_cmux_context": launch_config.require_cmux_context,
        "workspace_id": _resolve_workspace_id(runtime, launch_config),
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
    if launch_config.require_cmux_context and not payload["workspace_id"]:
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
    workspace_id = _resolve_workspace_id(runtime, launch_config)
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
    runtime._emit(
        "planning.agent_launch.surface_created",
        workspace_id=workspace_id,
        surface_id=surface_id,
        worktree=worktree.name,
    )
    commands = [
        ["cmux", "rename-tab", "--workspace", workspace_id, "--surface", surface_id, worktree.name],
        ["cmux", "respawn-pane", "--workspace", workspace_id, "--surface", surface_id, "--command", launch_config.shell],
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
    typed_steps = [
        shlex.quote(str(worktree.root)),
        launch_config.cli_command,
        _slash_command(launch_config.preset),
    ]
    send_errors = [
        _send_surface_text(runtime, workspace_id=workspace_id, surface_id=surface_id, text=f"cd {typed_steps[0]}"),
        _send_surface_key(runtime, workspace_id=workspace_id, surface_id=surface_id, key="enter"),
        _send_surface_text(runtime, workspace_id=workspace_id, surface_id=surface_id, text=typed_steps[1]),
        _send_surface_key(runtime, workspace_id=workspace_id, surface_id=surface_id, key="enter"),
    ]
    for error in send_errors:
        if error is not None:
            return PlanAgentLaunchOutcome(
                worktree_name=worktree.name,
                worktree_root=worktree.root,
                surface_id=surface_id,
                status="failed",
                reason=error,
            )
    time.sleep(_CLI_READY_DELAY_SECONDS)
    final_errors = [
        _send_surface_text(runtime, workspace_id=workspace_id, surface_id=surface_id, text=typed_steps[2]),
        _send_surface_key(runtime, workspace_id=workspace_id, surface_id=surface_id, key="enter"),
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


def _surface_id_from_output(raw: str) -> str | None:
    for token in raw.replace("\n", " ").split():
        normalized = token.strip()
        if normalized.startswith("surface:"):
            return normalized
    return None


def _resolve_workspace_id(runtime: Any, launch_config: PlanAgentLaunchConfig) -> str | None:
    if launch_config.cmux_workspace:
        return launch_config.cmux_workspace
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


def _send_surface_text(runtime: Any, *, workspace_id: str, surface_id: str, text: str) -> str | None:
    return _run_cmux_command(
        runtime,
        ["cmux", "send", "--workspace", workspace_id, "--surface", surface_id, text],
    )


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


def _slash_command(preset: str) -> str:
    normalized = str(preset).strip()
    return normalized if normalized.startswith("/") else f"/{normalized}"


def _print_launch_summary(message: str) -> None:
    print(message)
