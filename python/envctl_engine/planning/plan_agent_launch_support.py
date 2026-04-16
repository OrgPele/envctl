from __future__ import annotations
import json
import re
import shlex
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

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
    codex_preset_uses_direct_submission,
    resolve_codex_direct_prompt_body,
    resolve_opencode_direct_prompt_body,
)
from envctl_engine.shared.parsing import parse_bool, parse_int_or_none

_SUPPORTED_PLAN_AGENT_CLIS = frozenset({"codex", "opencode"})
_CODEX_BYPASS_FLAGS = "--dangerously-bypass-approvals-and-sandbox"
_PROMPT_SHAPING_COMMAND_TOKEN_RE = re.compile(r"^/[A-Za-z][A-Za-z0-9:_-]*$")
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
_TMUX_WINDOW_READY_TIMEOUT_SECONDS = 1.0
_TMUX_WINDOW_READY_POLL_INTERVAL_SECONDS = 0.05
_CODEX_QUEUE_READY_TIMEOUT_SECONDS = 10.0
_CODEX_QUEUE_READY_POLL_INTERVAL_SECONDS = 0.1
_PLAN_AGENT_TAB_TITLE_MAX_LEN = 36
_LOW_SIGNAL_TAB_TITLE_WORDS = frozenset({"and", "origin"})
_PLAN_AGENT_WORKFLOW_SINGLE_PROMPT = "single_prompt"
_PLAN_AGENT_WORKFLOW_CODEX_CYCLES = "codex_cycles"
_PLAN_AGENT_CODEX_CYCLE_CAP = 10
_REVIEW_WORKTREE_PRESET = "review_worktree_imp"
_WORKTREE_PROVENANCE_PATH = Path(".envctl-state") / "worktree-provenance.json"
_PLANNING_ROOT = Path("todo") / "plans"
_DONE_PLANNING_ROOT = Path("todo") / "done"
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
_CODEX_QUEUE_READY_HINT = "tab to queue message"
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
    cli: str = ""


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
    transport: Literal["cmux", "tmux"]
    cli: str
    cli_command: str
    preset: str
    codex_cycles: int
    codex_cycles_warning: str | None
    shell: str
    require_cmux_context: bool
    cmux_workspace: str
    direct_prompt_enabled: bool
    ulw_loop_prefix: bool
    ulw_suffix: bool


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
    attach_target: PlanAgentAttachTarget | None = None


@dataclass(slots=True, frozen=True)
class PlanAgentAttachTarget:
    repo_root: Path
    session_name: str
    window_name: str
    attach_via: str
    attach_command: tuple[str, ...]
    new_session_command: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class AgentTerminalLaunchResult:
    status: str
    reason: str
    surface_id: str | None = None


@dataclass(slots=True, frozen=True)
class ReviewAgentLaunchReadiness:
    ready: bool
    reason: str
    cli: str
    missing: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class _WorkspaceLaunchTarget:
    workspace_id: str
    created: bool
    starter_surface_id: str | None = None
    starter_surface_probe_result: str = "not_attempted"


@dataclass(slots=True, frozen=True)
class _PlanAgentWorkflowStep:
    kind: str
    text: str


@dataclass(slots=True, frozen=True)
class _PlanAgentWorkflow:
    mode: str
    codex_cycles: int
    steps: tuple[_PlanAgentWorkflowStep, ...]


def _finalization_instruction_text() -> str:
    return _slash_command("codex", "finalize_task")


def _first_cycle_completion_instruction_text() -> str:
    return "When the current implementation pass finishes, commit the work, push the branch, and open or update the PR."


def _intermediate_cycle_completion_instruction_text() -> str:
    return "When the current implementation pass finishes, commit the work and push the branch."


def _parse_codex_cycles(raw: object) -> tuple[int, str | None]:
    normalized = str(raw or "").strip()
    if not normalized:
        return 0, None
    value = parse_int_or_none(normalized)
    if value is None:
        return 0, "invalid_codex_cycles"
    if value < 0:
        return 0, "invalid_codex_cycles"
    if value > _PLAN_AGENT_CODEX_CYCLE_CAP:
        return _PLAN_AGENT_CODEX_CYCLE_CAP, "bounded_codex_cycles"
    return value, None


def _workflow_mode_for_launch_config(launch_config: PlanAgentLaunchConfig) -> str:
    if launch_config.cli == "codex" and launch_config.codex_cycles > 0:
        return _PLAN_AGENT_WORKFLOW_CODEX_CYCLES
    return _PLAN_AGENT_WORKFLOW_SINGLE_PROMPT


def _uses_direct_submission(*, cli: str, direct_prompt_enabled: bool) -> bool:
    normalized_cli = str(cli).strip().lower()
    if normalized_cli == "codex":
        return True
    return normalized_cli == "opencode" and direct_prompt_enabled


def _build_plan_agent_workflow(*, cli: str, preset: str, codex_cycles: int, direct_prompt_enabled: bool = False) -> _PlanAgentWorkflow:
    normalized_cli = str(cli).strip().lower()
    bounded_cycles = max(0, min(int(codex_cycles), _PLAN_AGENT_CODEX_CYCLE_CAP))
    if _uses_direct_submission(cli=normalized_cli, direct_prompt_enabled=direct_prompt_enabled):
        initial_step = _PlanAgentWorkflowStep(kind="submit_direct_prompt", text=str(preset).strip())
    else:
        initial_step = _PlanAgentWorkflowStep(kind="submit_prompt", text=_slash_command(cli, preset))
    if normalized_cli != "codex" or bounded_cycles <= 0:
        return _PlanAgentWorkflow(
            mode=_PLAN_AGENT_WORKFLOW_SINGLE_PROMPT,
            codex_cycles=bounded_cycles,
            steps=(initial_step,),
        )
    steps = [_PlanAgentWorkflowStep(kind="submit_direct_prompt", text="implement_task")]
    for cycle in range(1, bounded_cycles + 1):
        if cycle == bounded_cycles:
            steps.append(_PlanAgentWorkflowStep(kind="queue_direct_prompt", text="finalize_task"))
            continue
        if cycle == 1:
            completion_text = _first_cycle_completion_instruction_text()
        else:
            completion_text = _intermediate_cycle_completion_instruction_text()
        steps.append(_PlanAgentWorkflowStep(kind="queue_message", text=completion_text))
        steps.append(_PlanAgentWorkflowStep(kind="queue_direct_prompt", text="continue_task"))
        steps.append(_PlanAgentWorkflowStep(kind="queue_direct_prompt", text="implement_task"))
    return _PlanAgentWorkflow(
        mode=_PLAN_AGENT_WORKFLOW_CODEX_CYCLES,
        codex_cycles=bounded_cycles,
        steps=tuple(steps),
    )


def resolve_plan_agent_launch_config(
    config: EngineConfig,
    env: dict[str, str] | None = None,
    *,
    route: object | None = None,
) -> PlanAgentLaunchConfig:
    env_map = dict(env or {})
    _apply_plan_agent_aliases(env_map, explicit_values=env_map)
    route_flags = getattr(route, "flags", {}) or {}
    transport: Literal["cmux", "tmux"] = "tmux" if bool(route_flags.get("tmux")) else "cmux"
    cli = str(
        "opencode"
        if bool(route_flags.get("opencode"))
        else (
            "codex"
            if bool(route_flags.get("codex"))
            else (
            env_map.get("ENVCTL_PLAN_AGENT_CLI")
            or config.raw.get("ENVCTL_PLAN_AGENT_CLI")
            or "codex"
            )
        )
    ).strip().lower() or "codex"
    cli_command = str(
        env_map.get("ENVCTL_PLAN_AGENT_CLI_CMD")
        or config.raw.get("ENVCTL_PLAN_AGENT_CLI_CMD")
        or _default_plan_agent_cli_command(cli)
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
    codex_cycles, codex_cycles_warning = _parse_codex_cycles(
        env_map.get("ENVCTL_PLAN_AGENT_CODEX_CYCLES")
        or config.raw.get("ENVCTL_PLAN_AGENT_CODEX_CYCLES")
        or ""
    )
    enabled = parse_bool(
        env_map.get("ENVCTL_PLAN_AGENT_TERMINALS_ENABLE")
        or config.raw.get("ENVCTL_PLAN_AGENT_TERMINALS_ENABLE"),
        False,
    ) or bool(cmux_workspace) or transport == "tmux"
    direct_prompt_enabled = parse_bool(
        env_map.get("ENVCTL_PLAN_AGENT_DIRECT_PROMPT")
        or config.raw.get("ENVCTL_PLAN_AGENT_DIRECT_PROMPT"),
        True if (transport == "tmux" and cli == "opencode") else False,
    )
    ulw_loop_prefix = parse_bool(
        env_map.get("ENVCTL_PLAN_AGENT_ULW_LOOP_PREFIX")
        or config.raw.get("ENVCTL_PLAN_AGENT_ULW_LOOP_PREFIX"),
        False,
    )
    ulw_suffix = parse_bool(
        env_map.get("ENVCTL_PLAN_AGENT_APPEND_ULW")
        or config.raw.get("ENVCTL_PLAN_AGENT_APPEND_ULW"),
        False,
    )
    return PlanAgentLaunchConfig(
        enabled=enabled,
        transport=transport,
        cli=cli,
        cli_command=cli_command,
        preset=preset,
        codex_cycles=codex_cycles,
        codex_cycles_warning=codex_cycles_warning,
        shell=shell,
        require_cmux_context=parse_bool(
            env_map.get("ENVCTL_PLAN_AGENT_REQUIRE_CMUX_CONTEXT")
            or config.raw.get("ENVCTL_PLAN_AGENT_REQUIRE_CMUX_CONTEXT"),
            True,
        ),
        cmux_workspace=cmux_workspace,
        direct_prompt_enabled=direct_prompt_enabled,
        ulw_loop_prefix=ulw_loop_prefix,
        ulw_suffix=ulw_suffix,
    )


def _default_plan_agent_cli_command(cli: str) -> str:
    normalized = str(cli).strip().lower()
    if normalized == "codex":
        return f"codex {_CODEX_BYPASS_FLAGS}"
    return normalized or "codex"


def plan_agent_launch_prereq_commands(
    config: EngineConfig,
    env: dict[str, str] | None = None,
    *,
    route: object | None = None,
) -> tuple[str, ...]:
    launch_config = resolve_plan_agent_launch_config(config, env, route=route)
    if not launch_config.enabled:
        return ()
    cli_executable = _command_executable(launch_config.cli_command)
    launcher = "tmux" if launch_config.transport == "tmux" else "cmux"
    if not cli_executable:
        return (launcher,)
    return (launcher, cli_executable)


def inspect_plan_agent_launch(runtime: Any, *, route: object) -> dict[str, object]:
    launch_config = resolve_plan_agent_launch_config(runtime.config, getattr(runtime, "env", {}), route=route)
    workflow = _build_plan_agent_workflow(
        cli=launch_config.cli,
        preset=launch_config.preset,
        codex_cycles=launch_config.codex_cycles,
        direct_prompt_enabled=launch_config.direct_prompt_enabled,
    )
    workspace_id = None if launch_config.transport == "tmux" else _resolve_workspace_id(runtime, launch_config)
    target_workspace = None if launch_config.transport == "tmux" else (launch_config.cmux_workspace or _default_target_workspace_title(runtime, launch_config))
    payload: dict[str, object] = {
        "enabled": launch_config.enabled,
        "transport": launch_config.transport,
        "cli": launch_config.cli,
        "preset": launch_config.preset,
        "workflow_mode": workflow.mode,
        "codex_cycles": launch_config.codex_cycles,
        "workflow_warning": launch_config.codex_cycles_warning,
        "shell": launch_config.shell,
        "direct_prompt_enabled": launch_config.direct_prompt_enabled,
        "ulw_loop_prefix": launch_config.ulw_loop_prefix,
        "ulw_suffix": launch_config.ulw_suffix,
        "require_cmux_context": launch_config.require_cmux_context,
        "workspace_id": workspace_id,
        "configured_workspace": target_workspace or None,
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
    if _missing_required_cmux_context(runtime, launch_config):
        payload["reason"] = "missing_cmux_context"
        return payload
    payload["reason"] = "awaiting_new_worktrees"
    return payload


def review_agent_launch_readiness(runtime: Any) -> ReviewAgentLaunchReadiness:
    launch_config = resolve_plan_agent_launch_config(runtime.config, getattr(runtime, "env", {}))
    missing_commands = tuple(_missing_launch_commands(runtime, launch_config))
    if missing_commands:
        return ReviewAgentLaunchReadiness(
            ready=False,
            reason="missing_executables",
            cli=launch_config.cli,
            missing=missing_commands,
        )
    if launch_config.cmux_workspace:
        return ReviewAgentLaunchReadiness(ready=True, reason="ready", cli=launch_config.cli)
    if _default_target_workspace_title(runtime, launch_config, workspace_mode="reviews"):
        return ReviewAgentLaunchReadiness(ready=True, reason="ready", cli=launch_config.cli)
    reason = "missing_cmux_context" if _missing_required_cmux_context(runtime, launch_config) else "workspace_unavailable"
    return ReviewAgentLaunchReadiness(ready=False, reason=reason, cli=launch_config.cli)


def launch_review_agent_terminal(
    runtime: Any,
    *,
    repo_root: Path,
    project_name: str,
    project_root: Path,
    review_bundle_path: Path | None = None,
) -> AgentTerminalLaunchResult:
    launch_config = resolve_plan_agent_launch_config(runtime.config, getattr(runtime, "env", {}))
    missing_commands = _missing_launch_commands(runtime, launch_config)
    if missing_commands:
        runtime._emit(
            "dashboard.review_tab.failed",
            reason="missing_executables",
            project=project_name,
            cli=launch_config.cli,
            missing=missing_commands,
        )
        return AgentTerminalLaunchResult(status="failed", reason="missing_executables")
    workspace_target = _ensure_workspace_id(
        runtime,
        launch_config,
        workspace_mode="reviews",
        event_prefix="dashboard.review_tab",
    )
    if workspace_target is None:
        reason = "missing_cmux_context" if _missing_required_cmux_context(runtime, launch_config) else "workspace_unavailable"
        runtime._emit(
            "dashboard.review_tab.failed",
            reason=reason,
            project=project_name,
            cli=launch_config.cli,
        )
        return AgentTerminalLaunchResult(status="failed", reason=reason)
    workspace_id = workspace_target.workspace_id
    surface_id, create_error = _create_surface(runtime, workspace_id=workspace_id)
    if create_error or surface_id is None:
        runtime._emit(
            "dashboard.review_tab.failed",
            reason="surface_create_failed",
            project=project_name,
            workspace_id=workspace_id,
            error=create_error,
            cli=launch_config.cli,
        )
        return AgentTerminalLaunchResult(status="failed", reason=create_error or "surface_create_failed")
    runtime._emit(
        "dashboard.review_tab.surface_created",
        project=project_name,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cli=launch_config.cli,
    )
    _start_background_review_surface_bootstrap(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        launch_config=launch_config,
        repo_root=repo_root,
        project_name=project_name,
        project_root=project_root,
        review_bundle_path=review_bundle_path,
    )
    runtime._emit(
        "dashboard.review_tab.launched",
        project=project_name,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cli=launch_config.cli,
    )
    _print_launch_summary(f"Opened origin review tab for {project_name}.")
    return AgentTerminalLaunchResult(status="launched", reason="launched", surface_id=surface_id)


def launch_plan_agent_terminals(
    runtime: Any,
    *,
    route: object,
    created_worktrees: tuple[CreatedPlanWorktree, ...],
) -> PlanAgentLaunchResult:
    launch_config = resolve_plan_agent_launch_config(runtime.config, getattr(runtime, "env", {}), route=route)
    workflow = _build_plan_agent_workflow(
        cli=launch_config.cli,
        preset=launch_config.preset,
        codex_cycles=launch_config.codex_cycles,
        direct_prompt_enabled=launch_config.direct_prompt_enabled,
    )
    base_payload = {
        "enabled": launch_config.enabled,
        "cli": launch_config.cli,
        "created_worktree_count": len(created_worktrees),
        "workflow_mode": workflow.mode,
        "codex_cycles": launch_config.codex_cycles,
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
    if launch_config.transport == "cmux" and _missing_required_cmux_context(runtime, launch_config):
        _print_launch_summary(
            f"Plan agent launch skipped: no active cmux workspace context found. "
            f"Fix by setting ENVCTL_PLAN_AGENT_CMUX_WORKSPACE=<workspace-id>, "
            f"setting ENVCTL_PLAN_AGENT_REQUIRE_CMUX_CONTEXT=false, "
            f"or running envctl from within an active cmux session."
        )
        runtime._emit("planning.agent_launch.skipped", reason="missing_cmux_context", **base_payload)
        return PlanAgentLaunchResult(status="skipped", reason="missing_cmux_context")
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
    if launch_config.transport == "tmux":
        return _launch_plan_agent_tmux_terminals(
            runtime,
            route=route,
            launch_config=launch_config,
            workflow=workflow,
            created_worktrees=created_worktrees,
            base_payload=base_payload,
            prompt_on_existing=not bool(getattr(route, "flags", {}).get("batch")),
        )

    workspace_target = _ensure_workspace_id(runtime, launch_config)
    target_workspace = launch_config.cmux_workspace
    if workspace_target is None and not target_workspace:
        target_workspace = _default_target_workspace_title(runtime, launch_config)
    if workspace_target is None and target_workspace:
        _print_launch_summary("Plan agent launch failed: unable to resolve or create the configured cmux workspace.")
        return PlanAgentLaunchResult(status="failed", reason="workspace_unavailable")
    if workspace_target is None:
        _print_launch_summary("Plan agent launch skipped: current cmux workspace context is unavailable.")
        runtime._emit("planning.agent_launch.skipped", reason="missing_cmux_context", **base_payload)
        return PlanAgentLaunchResult(status="skipped", reason="missing_cmux_context")

    workspace_id = workspace_target.workspace_id
    runtime._emit(
        "planning.agent_launch.evaluate",
        reason="ready",
        workspace_id=workspace_id,
        preset=launch_config.preset,
        **base_payload,
    )
    runtime._emit(
        "planning.agent_launch.workflow_selected",
        workspace_id=workspace_id,
        warning=launch_config.codex_cycles_warning,
        **base_payload,
    )
    if workflow.mode == _PLAN_AGENT_WORKFLOW_CODEX_CYCLES:
        _print_launch_summary(
            f"Plan agent launch queued Codex cycle workflow (cycles={workflow.codex_cycles}) for {len(created_worktrees)} surface(s)."
        )
    if (
        workspace_target.created
        and workspace_target.starter_surface_id is None
        and workspace_target.starter_surface_probe_result in {"none", "ambiguous", "probe_failed"}
    ):
        runtime._emit(
            "planning.agent_launch.surface_fallback",
            workspace_id=workspace_id,
            reason=workspace_target.starter_surface_probe_result,
        )
    outcomes: list[PlanAgentLaunchOutcome] = []
    starter_surface_id = workspace_target.starter_surface_id
    for worktree in created_worktrees:
        outcome = _launch_single_worktree(
            runtime,
            workspace_id=workspace_id,
            launch_config=launch_config,
            worktree=worktree,
            starter_surface_id=starter_surface_id,
        )
        outcomes.append(outcome)
        starter_surface_id = None

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


def _launch_plan_agent_tmux_terminals(
    runtime: Any,
    *,
    route: object,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    created_worktrees: tuple[CreatedPlanWorktree, ...],
    base_payload: dict[str, object],
    prompt_on_existing: bool,
) -> PlanAgentLaunchResult:
    repo_root = Path(runtime.config.base_dir).resolve()
    attach_via = "switch-client" if str(getattr(runtime, "env", {}).get("TMUX", "")).strip() else "attach-session"
    route_flags = getattr(route, "flags", {}) or {}
    create_new_session = bool(route_flags.get("tmux_new_session"))
    existing_attach_target = _find_existing_tmux_attach_target(
        runtime,
        repo_root=repo_root,
        created_worktrees=created_worktrees,
        cli=launch_config.cli,
    )
    if existing_attach_target is not None:
        if not create_new_session and _should_prompt_existing_tmux_session(runtime, prompt_on_existing=prompt_on_existing):
            action = _prompt_existing_tmux_session_action(runtime, attach_target=existing_attach_target)
            if action == "attach":
                runtime._emit(
                    "planning.agent_launch.skipped",
                    reason="existing_tmux_session_attach",
                    session_name=existing_attach_target.session_name,
                    attach_command=" ".join(existing_attach_target.attach_command),
                    **base_payload,
                )
                return PlanAgentLaunchResult(
                    status="failed",
                    reason="existing_tmux_session_attach",
                    outcomes=(),
                    attach_target=existing_attach_target,
                )
            create_new_session = True
        attach_command = " ".join(existing_attach_target.attach_command)
        if not create_new_session:
            reason = f"An envctl tmux session already exists for this plan. Attach with: {attach_command}"
            runtime._emit(
                "planning.agent_launch.skipped",
                reason="existing_tmux_session",
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
        session_name = _tmux_session_name_for_worktree(repo_root, worktree, cli=launch_config.cli)
        if create_new_session:
            session_name = _next_available_tmux_session_name(runtime, session_name)
        window_name = _tmux_window_name_for_worktree(worktree)
        outcome = _launch_single_tmux_worktree(
            runtime,
            session_name=session_name,
            window_name=window_name,
            launch_config=launch_config,
            workflow=workflow,
            worktree=worktree,
        )
        outcomes.append(outcome)
        if first_attach_target is None and outcome.status == "launched":
            first_attach_target = PlanAgentAttachTarget(
                repo_root=repo_root,
                session_name=session_name,
                window_name=window_name,
                attach_via=attach_via,
                attach_command=("tmux", attach_via, "-t", session_name),
            )
    launched = [item for item in outcomes if item.status == "launched"]
    failed = [item for item in outcomes if item.status == "failed"]
    attach_target = first_attach_target or existing_attach_target
    if failed and launched:
        _print_launch_summary(
            f"Plan agent launch finished with partial success: launched {len(launched)}, failed {len(failed)}."
        )
        return PlanAgentLaunchResult(
            status="partial",
            reason="partial_failure",
            outcomes=tuple(outcomes),
            attach_target=attach_target,
        )
    if failed:
        _print_launch_summary(f"Plan agent launch failed for {len(failed)} worktree(s).")
        return PlanAgentLaunchResult(status="failed", reason="launch_failed", outcomes=tuple(outcomes))
    _print_launch_summary(f"Plan agent launch prepared {len(launched)} tmux session(s).")
    return PlanAgentLaunchResult(
        status="launched",
        reason="launched",
        outcomes=tuple(outcomes),
        attach_target=attach_target,
    )


def _launch_single_worktree(
    runtime: Any,
    *,
    workspace_id: str,
    launch_config: PlanAgentLaunchConfig,
    worktree: CreatedPlanWorktree,
    starter_surface_id: str | None = None,
) -> PlanAgentLaunchOutcome:
    surface_source = "starter_reused" if starter_surface_id else "new_surface"
    if starter_surface_id:
        surface_id = starter_surface_id
        create_error = None
    else:
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
        source=surface_source,
    )
    _start_background_surface_bootstrap(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        launch_config=launch_config,
        worktree=worktree,
    )
    return PlanAgentLaunchOutcome(
        worktree_name=worktree.name,
        worktree_root=worktree.root,
        surface_id=surface_id,
        status="launched",
    )


def _tmux_session_name_for_worktree(repo_root: Path, worktree: CreatedPlanWorktree, *, cli: str) -> str:
    worktree_root = Path(worktree.root).resolve()
    relative = worktree_root.relative_to(repo_root)
    relative_slug = _sanitize_tmux_name(str(relative), fallback=worktree.name)
    cli_slug = _sanitize_tmux_name(str(cli).strip().lower(), fallback="cli")
    return _sanitize_tmux_name(f"envctl-{repo_root.name}-{relative_slug}-{cli_slug}", fallback="envctl-worktree")


def _next_available_tmux_session_name(runtime: Any, session_name: str) -> str:
    if not _tmux_session_exists(runtime, session_name):
        return session_name
    index = 2
    while True:
        candidate = _sanitize_tmux_name(f"{session_name}-{index}", fallback=session_name)
        if not _tmux_session_exists(runtime, candidate):
            return candidate
        index += 1


def _should_prompt_existing_tmux_session(runtime: Any, *, prompt_on_existing: bool) -> bool:
    if not prompt_on_existing:
        return False
    can_interactive_tty = getattr(runtime, "_can_interactive_tty", None)
    if callable(can_interactive_tty):
        try:
            return bool(can_interactive_tty())
        except Exception:
            return False
    return False


def _prompt_existing_tmux_session_action(runtime: Any, *, attach_target: PlanAgentAttachTarget) -> Literal["attach", "new"]:
    prompt = (
        f"An envctl tmux session already exists for this plan/workspace ({attach_target.session_name}). "
        f"Attach to it? (Y/n): "
    )
    read_interactive = getattr(runtime, "_read_interactive_command_line", None)
    if callable(read_interactive):
        try:
            response = str(read_interactive(prompt)).strip().lower()
        except Exception:
            return "attach"
        if response in {"", "y", "yes"}:
            return "attach"
        if response in {"n", "no"}:
            return "new"
        return "attach"
    confirm = getattr(runtime, "_prompt_yes_no", None)
    if callable(confirm):
        try:
            return "attach" if bool(confirm(prompt)) else "new"
        except TypeError:
            return "attach" if bool(confirm(title="Attach existing session?", prompt=prompt)) else "new"
    return "new"


def _new_session_command_for_route(
    runtime: Any,
    *,
    route: object,
    launch_config: PlanAgentLaunchConfig,
    created_worktrees: tuple[CreatedPlanWorktree, ...],
) -> tuple[str, ...]:
    selector = ""
    route_passthrough = list(getattr(route, "passthrough_args", []) or [])
    if route_passthrough:
        selector = str(route_passthrough[0]).strip()
    route_projects = list(getattr(route, "projects", []) or [])
    if not selector and route_projects:
        selector = str(route_projects[0]).strip()
    if not selector and created_worktrees:
        plan_file = str(created_worktrees[0].plan_file or "").strip()
        if plan_file:
            selector = plan_file.removesuffix(".md")
    if not selector:
        return ()
    command = [
        "ENVCTL_USE_REPO_WRAPPER=1",
        str(Path(runtime.config.base_dir).resolve() / "bin" / "envctl"),
        "--plan",
        selector,
        "--tmux",
    ]
    if launch_config.cli == "opencode":
        command.append("--opencode")
    elif launch_config.cli == "codex":
        command.append("--codex")
    command.append("--tmux-new-session")
    command.append("--headless")
    return tuple(command)


def _launch_single_tmux_worktree(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    worktree: CreatedPlanWorktree,
) -> PlanAgentLaunchOutcome:
    create_error = _ensure_tmux_window(
        runtime,
        session_name=session_name,
        window_name=window_name,
        launch_config=launch_config,
        worktree=worktree,
    )
    if create_error is not None:
        runtime._emit(
            "planning.agent_launch.failed",
            reason="window_create_failed",
            session_name=session_name,
            window_name=window_name,
            worktree=worktree.name,
            error=create_error,
            transport="tmux",
        )
        return PlanAgentLaunchOutcome(
            worktree_name=worktree.name,
            worktree_root=worktree.root,
            surface_id=None,
            status="failed",
            reason=create_error,
        )
    runtime._emit(
        "planning.agent_launch.surface_created",
        session_name=session_name,
        window_name=window_name,
        worktree=worktree.name,
        source="tmux_window",
        transport="tmux",
    )
    error = _run_tmux_worktree_bootstrap(
        runtime,
        session_name=session_name,
        window_name=window_name,
        launch_config=launch_config,
        workflow=workflow,
        worktree=worktree,
    )
    if error is not None:
        runtime._emit(
            "planning.agent_launch.failed",
            reason="bootstrap_failed",
            session_name=session_name,
            window_name=window_name,
            worktree=worktree.name,
            error=error,
            transport="tmux",
        )
        return PlanAgentLaunchOutcome(
            worktree_name=worktree.name,
            worktree_root=worktree.root,
            surface_id=None,
            status="failed",
            reason=error,
        )
    runtime._emit(
        "planning.agent_launch.command_sent",
        session_name=session_name,
        window_name=window_name,
        worktree=worktree.name,
        preset=launch_config.preset,
        workflow_mode=workflow.mode,
        codex_cycles=workflow.codex_cycles,
        transport="tmux",
    )
    _persist_runtime_events_snapshot(runtime)
    return PlanAgentLaunchOutcome(
        worktree_name=worktree.name,
        worktree_root=worktree.root,
        surface_id=None,
        status="launched",
    )


def _tmux_window_name_for_worktree(worktree: CreatedPlanWorktree) -> str:
    return _sanitize_tmux_name(_tab_title_for_worktree(worktree.name), fallback="implementation")


def _tmux_target(session_name: str, window_name: str) -> str:
    return f"{session_name}:{window_name}"


def _ensure_tmux_window(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    launch_config: PlanAgentLaunchConfig,
    worktree: CreatedPlanWorktree,
) -> str | None:
    cwd = Path(worktree.root).resolve()
    shell_command = launch_config.shell
    if _tmux_session_exists(runtime, session_name):
        command = (
            "tmux",
            "new-window",
            "-d",
            "-t",
            session_name,
            "-n",
            window_name,
            "-c",
            str(cwd),
            shell_command,
        )
    else:
        command = (
            "tmux",
            "new-session",
            "-d",
            "-s",
            session_name,
            "-n",
            window_name,
            "-c",
            str(cwd),
            shell_command,
        )
    result = _run_tmux_probe(runtime, command, cwd=Path(runtime.config.base_dir).resolve())
    if result.returncode == 0:
        wait_error = _wait_for_tmux_window_ready(runtime, session_name=session_name, window_name=window_name)
        if wait_error is None:
            return None
        return wait_error
    return _tmux_completed_process_error_text(result)


def _wait_for_tmux_window_ready(runtime: Any, *, session_name: str, window_name: str) -> str | None:
    deadline = time.monotonic() + _TMUX_WINDOW_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if _tmux_window_exists(runtime, session_name=session_name, window_name=window_name):
            return None
        time.sleep(_TMUX_WINDOW_READY_POLL_INTERVAL_SECONDS)
    return f"tmux_window_unavailable: can't find window: {window_name}"


def _tmux_window_exists(runtime: Any, *, session_name: str, window_name: str) -> bool:
    result = _run_tmux_probe(
        runtime,
        ("tmux", "list-windows", "-t", session_name, "-F", "#{window_name}"),
        cwd=Path(runtime.config.base_dir).resolve(),
    )
    if result.returncode != 0:
        return False
    windows = {str(line).strip() for line in str(getattr(result, "stdout", "")).splitlines() if str(line).strip()}
    return window_name in windows


def _resolve_tmux_attach_target(
    runtime: Any,
    *,
    repo_root: Path,
    session_name: str,
    window_name: str | None,
    attach_via: str,
    created_worktrees: tuple[CreatedPlanWorktree, ...],
    cli: str,
) -> PlanAgentAttachTarget | None:
    existing_attach_target = _find_existing_tmux_attach_target(
        runtime,
        repo_root=repo_root,
        created_worktrees=created_worktrees,
        cli=cli,
    )
    if existing_attach_target is not None:
        return existing_attach_target
    if not _tmux_session_exists(runtime, session_name):
        return None
    if window_name and not _tmux_window_exists(runtime, session_name=session_name, window_name=window_name):
        return None
    return PlanAgentAttachTarget(
        repo_root=repo_root,
        session_name=session_name,
        window_name=window_name or "",
        attach_via=attach_via,
        attach_command=("tmux", attach_via, "-t", session_name),
    )


def _find_existing_tmux_attach_target(
    runtime: Any,
    *,
    repo_root: Path,
    created_worktrees: tuple[CreatedPlanWorktree, ...],
    cli: str,
) -> PlanAgentAttachTarget | None:
    separator = "|||ENVCTL_TMUX_PATH|||"
    targets = [Path(worktree.root).expanduser().resolve(strict=False) for worktree in created_worktrees]
    attach_by_root = {
        Path(worktree.root).expanduser().resolve(strict=False): PlanAgentAttachTarget(
            repo_root=repo_root,
            session_name=_tmux_session_name_for_worktree(repo_root, worktree, cli=cli),
            window_name=_tmux_window_name_for_worktree(worktree),
            attach_via="attach-session",
            attach_command=("tmux", "attach-session", "-t", _tmux_session_name_for_worktree(repo_root, worktree, cli=cli)),
        )
        for worktree in created_worktrees
    }
    if not targets:
        return None
    for target in targets:
        attach_target = attach_by_root[target]
        session_name = attach_target.session_name
        if not _tmux_session_exists(runtime, session_name):
            continue
        windows_result = _run_tmux_probe(
            runtime,
            ("tmux", "list-windows", "-t", session_name, "-F", f"#{{window_name}}{separator}#{{pane_current_path}}"),
            cwd=Path(runtime.config.base_dir).resolve(),
        )
        if windows_result.returncode != 0:
            continue
        for raw_line in str(getattr(windows_result, "stdout", "")).splitlines():
            window, _, raw_path = raw_line.partition(separator)
            window_name = window.strip()
            normalized_path = raw_path.strip()
            if not window_name or not normalized_path:
                continue
            candidate = Path(normalized_path).expanduser().resolve(strict=False)
            if candidate == target or target in candidate.parents:
                return PlanAgentAttachTarget(
                    repo_root=repo_root,
                    session_name=session_name,
                    window_name=window_name,
                    attach_via="attach-session",
                    attach_command=("tmux", "attach-session", "-t", session_name),
                )
    return None


def _run_tmux_command(
    runtime: Any,
    command: tuple[str, ...],
    *,
    emit_failure_event: bool = True,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    result = _run_tmux_probe(runtime, command, cwd=Path(runtime.config.base_dir).resolve())
    if result.returncode == 0:
        return None
    error = _tmux_completed_process_error_text(result)
    if emit_failure_event:
        runtime._emit(failure_event, reason="tmux_command_failed", command=command[1], error=error)
    return error


def _send_tmux_text(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    text: str,
    emit_failure_event: bool = True,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    return _run_tmux_command(
        runtime,
        ("tmux", "send-keys", "-t", _tmux_target(session_name, window_name), "-l", text),
        emit_failure_event=emit_failure_event,
        failure_event=failure_event,
    )


def _send_tmux_key(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    key: str,
    emit_failure_event: bool = True,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    key_name = {"enter": "Enter"}.get(str(key).strip().lower(), key)
    return _run_tmux_command(
        runtime,
        ("tmux", "send-keys", "-t", _tmux_target(session_name, window_name), key_name),
        emit_failure_event=emit_failure_event,
        failure_event=failure_event,
    )


def _read_tmux_screen(runtime: Any, *, session_name: str, window_name: str) -> str:
    target = _tmux_target(session_name, window_name)
    for command in (("tmux", "capture-pane", "-p", "-a", "-t", target), ("tmux", "capture-pane", "-p", "-t", target)):
        result = _run_tmux_probe(runtime, command, cwd=Path(runtime.config.base_dir).resolve())
        if result.returncode == 0:
            return str(getattr(result, "stdout", ""))
    return ""


def _launch_tmux_cli_bootstrap_commands(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    cwd: Path,
    cli_command: str,
    failure_event: str = "planning.agent_launch.failed",
) -> list[str | None]:
    typed_root = shlex.quote(str(cwd))
    emit_failure_event = failure_event == "planning.agent_launch.failed"
    return [
        _send_tmux_text(runtime, session_name=session_name, window_name=window_name, text=f"cd {typed_root}", emit_failure_event=emit_failure_event, failure_event=failure_event),
        _send_tmux_key(runtime, session_name=session_name, window_name=window_name, key="enter", emit_failure_event=emit_failure_event, failure_event=failure_event),
        _send_tmux_text(runtime, session_name=session_name, window_name=window_name, text=cli_command, emit_failure_event=emit_failure_event, failure_event=failure_event),
        _send_tmux_key(runtime, session_name=session_name, window_name=window_name, key="enter", emit_failure_event=emit_failure_event, failure_event=failure_event),
    ]


def _wait_for_tmux_cli_ready(runtime: Any, *, session_name: str, window_name: str, cli: str) -> None:
    normalized_cli = str(cli).strip().lower()
    timeout_seconds = _cli_ready_delay_seconds(normalized_cli)
    if normalized_cli not in {"codex", "opencode"}:
        time.sleep(timeout_seconds)
        return
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        screen = _read_tmux_screen(runtime, session_name=session_name, window_name=window_name)
        if _screen_looks_ready(normalized_cli, screen):
            return
        time.sleep(_CLI_READY_POLL_INTERVAL_SECONDS)


def _send_tmux_prompt(runtime: Any, *, session_name: str, window_name: str, text: str) -> str | None:
    target = _tmux_target(session_name, window_name)
    load_result = subprocess.run(
        ["tmux", "load-buffer", "-t", target, "-"],
        input=text,
        capture_output=True,
        text=True,
        cwd=Path(runtime.config.base_dir).resolve(),
        env=dict(getattr(runtime, "env", {})),
        timeout=10.0,
    )
    if load_result.returncode != 0:
        error = (load_result.stderr or "").strip()[:200]
        runtime._emit("planning.agent_launch.failed", reason="tmux_load_buffer_failed", error=error)
        return f"tmux_load_buffer_failed: {error}"
    paste_result = subprocess.run(
        ["tmux", "paste-buffer", "-dpr", "-t", target],
        capture_output=True,
        text=True,
        cwd=Path(runtime.config.base_dir).resolve(),
        env=dict(getattr(runtime, "env", {})),
        timeout=10.0,
    )
    if paste_result.returncode != 0:
        error = (paste_result.stderr or "").strip()[:200]
        runtime._emit("planning.agent_launch.failed", reason="tmux_paste_buffer_failed", error=error)
        return f"tmux_paste_buffer_failed: {error}"
    return None


def _submit_tmux_prompt_workflow_step(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    prompt_text: str,
    cli: str = "",
) -> str | None:
    paste_error = _send_tmux_prompt(runtime, session_name=session_name, window_name=window_name, text=prompt_text)
    if paste_error is not None:
        return paste_error
    if str(cli).strip().lower() == "opencode":
        time.sleep(1.0)
    return _send_tmux_key(runtime, session_name=session_name, window_name=window_name, key="enter")


def _run_tmux_worktree_bootstrap(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    worktree: CreatedPlanWorktree,
) -> str | None:
    send_errors = _launch_tmux_cli_bootstrap_commands(
        runtime,
        session_name=session_name,
        window_name=window_name,
        cwd=worktree.root,
        cli_command=launch_config.cli_command,
    )
    for error in send_errors:
        if error is not None:
            return error
    _wait_for_tmux_cli_ready(runtime, session_name=session_name, window_name=window_name, cli=launch_config.cli)
    prompt_text, resolution_error = _workflow_step_prompt_text(
        runtime,
        launch_config=launch_config,
        cli=launch_config.cli,
        step=workflow.steps[0],
    )
    if resolution_error is not None:
        return resolution_error
    return _submit_tmux_prompt_workflow_step(
        runtime,
        session_name=session_name,
        window_name=window_name,
        prompt_text=prompt_text,
        cli=launch_config.cli,
    )


def attach_plan_agent_terminal(runtime: Any, attach_target: PlanAgentAttachTarget) -> int:
    if attach_target.attach_via == "switch-client":
        result = _run_tmux_probe(runtime, attach_target.attach_command, cwd=attach_target.repo_root)
        if result.returncode != 0:
            print(_tmux_completed_process_error_text(result), file=sys.stderr)
            return 1
        return 0
    return _attach_interactive(runtime, attach_target.attach_command, cwd=attach_target.repo_root)


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


def _start_background_surface_bootstrap(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    launch_config: PlanAgentLaunchConfig,
    worktree: CreatedPlanWorktree,
) -> None:
    thread = threading.Thread(
        target=_complete_surface_bootstrap,
        kwargs={
            "runtime": runtime,
            "workspace_id": workspace_id,
            "surface_id": surface_id,
            "launch_config": launch_config,
            "worktree": worktree,
        },
        name=f"envctl-plan-agent-{worktree.name}",
        daemon=False,
    )
    thread.start()


def _start_background_review_surface_bootstrap(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    launch_config: PlanAgentLaunchConfig,
    repo_root: Path,
    project_name: str,
    project_root: Path,
    review_bundle_path: Path | None,
) -> None:
    thread = threading.Thread(
        target=_complete_review_surface_bootstrap,
        kwargs={
            "runtime": runtime,
            "workspace_id": workspace_id,
            "surface_id": surface_id,
            "launch_config": launch_config,
            "repo_root": repo_root,
            "project_name": project_name,
            "project_root": project_root,
            "review_bundle_path": review_bundle_path,
        },
        name=f"envctl-review-agent-{project_name}",
        daemon=False,
    )
    thread.start()


def _complete_surface_bootstrap(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    launch_config: PlanAgentLaunchConfig,
    worktree: CreatedPlanWorktree,
) -> None:
    workflow = _build_plan_agent_workflow(
        cli=launch_config.cli,
        preset=launch_config.preset,
        codex_cycles=launch_config.codex_cycles,
    )
    try:
        error = _run_surface_bootstrap(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            launch_config=launch_config,
            worktree=worktree,
        )
        if error is None:
            runtime._emit(
                "planning.agent_launch.command_sent",
                workspace_id=workspace_id,
                surface_id=surface_id,
                worktree=worktree.name,
                preset=launch_config.preset,
                workflow_mode=workflow.mode,
                codex_cycles=workflow.codex_cycles,
            )
            return
        runtime._emit(
            "planning.agent_launch.failed",
            reason="bootstrap_failed",
            workspace_id=workspace_id,
            surface_id=surface_id,
            worktree=worktree.name,
            error=error,
        )
    finally:
        _persist_runtime_events_snapshot(runtime)


def _complete_review_surface_bootstrap(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    launch_config: PlanAgentLaunchConfig,
    repo_root: Path,
    project_name: str,
    project_root: Path,
    review_bundle_path: Path | None,
) -> None:
    try:
        error = _run_review_surface_bootstrap(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            launch_config=launch_config,
            repo_root=repo_root,
            project_name=project_name,
            project_root=project_root,
            review_bundle_path=review_bundle_path,
        )
        if error is None:
            runtime._emit(
                "dashboard.review_tab.command_sent",
                workspace_id=workspace_id,
                surface_id=surface_id,
                project=project_name,
                cli=launch_config.cli,
                preset=_REVIEW_WORKTREE_PRESET,
            )
            return
        runtime._emit(
            "dashboard.review_tab.failed",
            reason="bootstrap_failed",
            workspace_id=workspace_id,
            surface_id=surface_id,
            project=project_name,
            cli=launch_config.cli,
            error=error,
        )
    finally:
        _persist_runtime_events_snapshot(runtime)


def _run_surface_bootstrap(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    launch_config: PlanAgentLaunchConfig,
    worktree: CreatedPlanWorktree,
) -> str | None:
    workflow = _build_plan_agent_workflow(
        cli=launch_config.cli,
        preset=launch_config.preset,
        codex_cycles=launch_config.codex_cycles,
    )
    error = _prepare_surface(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        tab_title=_tab_title_for_worktree(worktree.name),
        shell_command=_surface_respawn_command(launch_config, worktree),
    )
    if error is not None:
        return error
    send_errors = _launch_cli_bootstrap_commands(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cwd=worktree.root,
        cli_command=launch_config.cli_command,
    )
    for error in send_errors:
        if error is not None:
            return error
    _wait_for_cli_ready(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cli=launch_config.cli,
    )
    initial_step = workflow.steps[0]
    prompt_text, resolution_error = _workflow_step_prompt_text(
        runtime,
        launch_config=launch_config,
        cli=launch_config.cli,
        step=initial_step,
    )
    if resolution_error is not None:
        return resolution_error
    if initial_step.kind == "submit_direct_prompt":
        submit_error = _submit_direct_prompt_workflow_step(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            prompt_text=prompt_text,
        )
    else:
        submit_error = _submit_prompt_workflow_step(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            cli=launch_config.cli,
            prompt_text=prompt_text,
        )
    if submit_error is not None:
        return submit_error
    queued_steps = workflow.steps[1:]
    if queued_steps and launch_config.cli == "codex":
        queue_error_reason = _queue_codex_workflow_steps(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            worktree=worktree,
            workflow=workflow,
            queued_steps=queued_steps,
            launch_config=launch_config,
            cli=launch_config.cli,
        )
        if queue_error_reason is not None:
            runtime._emit(
                "planning.agent_launch.workflow_queue_failed",
                workspace_id=workspace_id,
                surface_id=surface_id,
                worktree=worktree.name,
                cli=launch_config.cli,
                workflow_mode=workflow.mode,
                codex_cycles=workflow.codex_cycles,
                reason=queue_error_reason,
            )
            runtime._emit(
                "planning.agent_launch.workflow_fallback",
                workspace_id=workspace_id,
                surface_id=surface_id,
                worktree=worktree.name,
                cli=launch_config.cli,
                workflow_mode=workflow.mode,
                codex_cycles=workflow.codex_cycles,
                reason=queue_error_reason,
            )
            return None
    return None


def _run_review_surface_bootstrap(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    launch_config: PlanAgentLaunchConfig,
    repo_root: Path,
    project_name: str,
    project_root: Path,
    review_bundle_path: Path | None,
) -> str | None:
    error = _prepare_surface(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        tab_title=_tab_title_for_worktree(project_name),
        shell_command=launch_config.shell,
        failure_event="dashboard.review_tab.failed",
    )
    if error is not None:
        return error
    send_errors = _launch_cli_bootstrap_commands(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cwd=repo_root,
        cli_command=launch_config.cli_command,
        failure_event="dashboard.review_tab.failed",
    )
    for send_error in send_errors:
        if send_error is not None:
            return send_error
    _wait_for_cli_ready(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cli=launch_config.cli,
    )
    review_arguments = _review_prompt_arguments(
        project_name=project_name,
        project_root=project_root,
        review_bundle_path=review_bundle_path,
        original_plan_path=_review_original_plan_path(project_name, project_root, repo_root=repo_root),
    )
    prompt_text, resolution_error = _resolve_preset_submission_text(
        runtime,
        launch_config=launch_config,
        cli=launch_config.cli,
        preset=_REVIEW_WORKTREE_PRESET,
        arguments=review_arguments,
    )
    if resolution_error is not None:
        return resolution_error
    if _uses_direct_submission(cli=launch_config.cli, direct_prompt_enabled=launch_config.direct_prompt_enabled):
        return _submit_direct_prompt_workflow_step(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            prompt_text=prompt_text,
            failure_event="dashboard.review_tab.failed",
        )
    return _submit_prompt_workflow_step(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cli=launch_config.cli,
        prompt_text=prompt_text,
        failure_event="dashboard.review_tab.failed",
    )


def _workflow_step_prompt_text(
    runtime: Any,
    *,
    launch_config: PlanAgentLaunchConfig,
    cli: str,
    step: _PlanAgentWorkflowStep,
) -> tuple[str, str | None]:
    if step.kind not in {"submit_direct_prompt", "queue_direct_prompt"}:
        return step.text, None
    return _resolve_preset_submission_text(runtime, launch_config=launch_config, cli=cli, preset=step.text)


def _shape_prompt_text(
    text: str,
    *,
    direct_prompt: bool,
    ulw_loop_prefix: bool,
    ulw_suffix: bool,
) -> tuple[str, str | None]:
    shaped = str(text)
    stripped = shaped.strip()
    if ulw_loop_prefix:
        if not direct_prompt:
            return "", "prompt_resolution_failed: ulw_loop_prefix_requires_direct_prompt"
        slash_command_tokens = [
            token
            for token in str(stripped).split()
            if _PROMPT_SHAPING_COMMAND_TOKEN_RE.fullmatch(token)
        ]
        if any(token != "/ulw_loop" for token in slash_command_tokens):
            return "", "prompt_resolution_failed: multiple_slash_commands_not_allowed"
        if not stripped.startswith("/ulw_loop"):
            shaped = f"/ulw_loop {stripped}" if stripped else "/ulw_loop"
            stripped = shaped.strip()
    if ulw_suffix and not stripped.endswith(" ulw") and stripped != "ulw":
        shaped = f"{shaped.rstrip()} ulw" if shaped.rstrip() else "ulw"
    return shaped, None


def _resolve_preset_submission_text(
    runtime: Any,
    *,
    launch_config: PlanAgentLaunchConfig,
    cli: str,
    preset: str,
    arguments: str = "",
) -> tuple[str, str | None]:
    normalized_cli = str(cli).strip().lower()
    direct_prompt = _uses_direct_submission(cli=normalized_cli, direct_prompt_enabled=launch_config.direct_prompt_enabled)
    try:
        if not direct_prompt:
            resolved = _slash_command(cli, preset, arguments=arguments)
        elif normalized_cli == "codex":
            resolved = resolve_codex_direct_prompt_body(
                preset=preset,
                env=getattr(runtime, "env", {}),
                arguments=arguments,
            )
        elif normalized_cli == "opencode":
            resolved = resolve_opencode_direct_prompt_body(
                preset=preset,
                env=getattr(runtime, "env", {}),
                arguments=arguments,
            )
        else:
            resolved = _slash_command(cli, preset, arguments=arguments)
    except (LookupError, OSError, ValueError) as exc:
        return "", f"prompt_resolution_failed: {exc}"
    return _shape_prompt_text(
        resolved,
        direct_prompt=direct_prompt,
        ulw_loop_prefix=launch_config.ulw_loop_prefix,
        ulw_suffix=launch_config.ulw_suffix,
    )


def _prepare_surface(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    tab_title: str,
    shell_command: str,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    commands = [
        ["cmux", "rename-tab", "--workspace", workspace_id, "--surface", surface_id, tab_title],
        ["cmux", "respawn-pane", "--workspace", workspace_id, "--surface", surface_id, "--command", shell_command],
    ]
    for command in commands:
        error = _run_cmux_command(runtime, command, failure_event=failure_event)
        if error is not None:
            return error
    time.sleep(_SURFACE_READY_DELAY_SECONDS)
    return None


def _submit_prompt_workflow_step(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    cli: str,
    prompt_text: str,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    failure_kwargs = {} if failure_event == "planning.agent_launch.failed" else {"failure_event": failure_event}
    final_errors = [
        _send_prompt_text(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            cli=cli,
            text=prompt_text,
            **failure_kwargs,
        ),
        _send_surface_key(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            key="ctrl+e",
            failure_event=failure_event,
        ),
    ]
    for error in final_errors:
        if error is not None:
            return error
    _wait_for_prompt_picker_ready(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cli=cli,
        prompt_text=prompt_text,
    )
    submit_error = _send_surface_key(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        key="enter",
        failure_event=failure_event,
    )
    if submit_error is not None:
        return submit_error
    _wait_for_prompt_submit_ready(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cli=cli,
        prompt_text=prompt_text,
    )
    return _send_surface_key(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        key="enter",
        failure_event=failure_event,
    )


def _submit_direct_prompt_workflow_step(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    prompt_text: str,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    paste_error = _paste_surface_text(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        text=prompt_text,
        failure_event=failure_event,
    )
    if paste_error is not None:
        return paste_error
    return _send_surface_key(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        key="enter",
        failure_event=failure_event,
    )


def _queue_codex_workflow_steps(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    worktree: CreatedPlanWorktree,
    workflow: _PlanAgentWorkflow,
    queued_steps: tuple[_PlanAgentWorkflowStep, ...],
    launch_config: PlanAgentLaunchConfig,
    cli: str,
) -> str | None:
    for step in queued_steps:
        queued_text, resolution_error = _workflow_step_prompt_text(
            runtime,
            launch_config=launch_config,
            cli=cli,
            step=step,
        )
        if resolution_error is not None:
            return "queue_prompt_resolution_failed"
        if step.kind == "queue_direct_prompt":
            send_error = _paste_surface_text(
                runtime,
                workspace_id=workspace_id,
                surface_id=surface_id,
                text=queued_text,
                emit_failure_event=False,
            )
        else:
            send_error = _send_surface_text(
                runtime,
                workspace_id=workspace_id,
                surface_id=surface_id,
                text=queued_text,
                emit_failure_event=False,
            )
        if send_error is not None:
            return "queue_send_failed"
        if not _queue_codex_message(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            text=queued_text,
            require_text_match=True,
        ):
            return "queue_not_ready"
    runtime._emit(
        "planning.agent_launch.workflow_queued",
        workspace_id=workspace_id,
        surface_id=surface_id,
        worktree=worktree.name,
        cli=cli,
        workflow_mode=workflow.mode,
        codex_cycles=workflow.codex_cycles,
        queued_steps=len(queued_steps),
    )
    return None


def _wait_for_codex_queue_ready(runtime: Any, *, workspace_id: str, surface_id: str) -> bool:
    deadline = time.monotonic() + _CODEX_QUEUE_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        screen = _read_surface_screen(runtime, workspace_id=workspace_id, surface_id=surface_id)
        if _codex_queue_screen_looks_ready(screen):
            return True
        time.sleep(_CODEX_QUEUE_READY_POLL_INTERVAL_SECONDS)
    return False


def _codex_queue_screen_looks_ready(screen: str) -> bool:
    cleaned = _strip_ansi_sequences(screen)
    if not cleaned.strip():
        return True
    return _screen_looks_ready("codex", cleaned)


def _queue_codex_message(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    text: str,
    require_text_match: bool = True,
) -> bool:
    deadline = time.monotonic() + _CODEX_QUEUE_READY_TIMEOUT_SECONDS
    normalized_text = str(text).strip()
    picker_submitted = False
    tab_sent = False
    while time.monotonic() < deadline:
        screen = _read_surface_screen(runtime, workspace_id=workspace_id, surface_id=surface_id)
        if (
            normalized_text.startswith("/")
            and not picker_submitted
            and _prompt_picker_screen_looks_ready("codex", screen, normalized_text)
        ):
            submit_error = _send_surface_key(
                runtime,
                workspace_id=workspace_id,
                surface_id=surface_id,
                key="enter",
                emit_failure_event=False,
            )
            if submit_error is not None:
                return False
            picker_submitted = True
            time.sleep(_CODEX_QUEUE_READY_POLL_INTERVAL_SECONDS)
            continue
        if _codex_queue_message_needs_tab(screen, text, require_text_match=require_text_match):
            tab_error = _send_surface_key(
                runtime,
                workspace_id=workspace_id,
                surface_id=surface_id,
                key="tab",
                emit_failure_event=False,
            )
            if tab_error is not None:
                return False
            tab_sent = True
            time.sleep(_CODEX_QUEUE_READY_POLL_INTERVAL_SECONDS)
            continue
        if tab_sent:
            return True
        time.sleep(_CODEX_QUEUE_READY_POLL_INTERVAL_SECONDS)
    return False


def _codex_queue_message_needs_tab(screen: str, text: str, *, require_text_match: bool = True) -> bool:
    normalized_screen = _normalized_screen_text(screen)
    if not normalized_screen:
        return False
    if _CODEX_QUEUE_READY_HINT not in normalized_screen:
        return False
    normalized_text = _normalized_screen_text(text)
    if not normalized_text:
        return False
    if normalized_text in normalized_screen:
        return True
    if not require_text_match:
        return False
    first_visible_line = next((line.strip() for line in str(text).splitlines() if line.strip()), "")
    if not first_visible_line:
        return False
    return _normalized_screen_text(first_visible_line) in normalized_screen


def _surface_respawn_command(launch_config: PlanAgentLaunchConfig, worktree: CreatedPlanWorktree) -> str:
    _ = worktree
    return launch_config.shell


def _tab_title_for_worktree(name: str) -> str:
    normalized = str(name).strip()
    if not normalized:
        return "implementation"
    parts = [part.strip() for part in normalized.split("_") if str(part).strip()]
    if len(parts) < 4:
        return normalized
    tail_parts: list[str] = []
    for part in reversed(parts[1:]):
        if len(tail_parts) >= 3:
            break
        if part in _LOW_SIGNAL_TAB_TITLE_WORDS:
            continue
        tail_parts.append(part)
    tail_parts.reverse()
    candidate = "_".join([parts[0], *tail_parts]) if tail_parts else normalized
    if len(candidate) <= _PLAN_AGENT_TAB_TITLE_MAX_LEN:
        return candidate
    fallback_tail = tail_parts[-2:] if tail_parts else parts[-2:]
    fallback = "_".join([parts[0], *fallback_tail])
    return fallback or candidate or normalized


def _launch_cli_bootstrap_commands(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    cwd: Path,
    cli_command: str,
    failure_event: str = "planning.agent_launch.failed",
) -> list[str | None]:
    typed_root = shlex.quote(str(cwd))
    failure_kwargs = {} if failure_event == "planning.agent_launch.failed" else {"failure_event": failure_event}
    return [
        _send_surface_text(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            text=f"cd {typed_root}",
            failure_event=failure_event,
        ),
        _send_surface_key(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            key="enter",
            failure_event=failure_event,
        ),
        _send_surface_text(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            text=cli_command,
            failure_event=failure_event,
        ),
        _send_surface_key(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            key="enter",
            failure_event=failure_event,
        ),
    ]


def _surface_id_from_output(raw: str) -> str | None:
    for token in raw.replace("\n", " ").split():
        normalized = token.strip()
        if normalized.startswith("surface:"):
            return normalized
    return None


def _resolve_workspace_id(
    runtime: Any,
    launch_config: PlanAgentLaunchConfig,
    *,
    workspace_mode: Literal["implementation", "current", "reviews"] = "implementation",
) -> str | None:
    if launch_config.cmux_workspace:
        return _resolve_configured_workspace_id(runtime, launch_config.cmux_workspace)
    _, target_ref = _default_workspace_target(runtime, launch_config, workspace_mode=workspace_mode)
    return target_ref


def _ensure_workspace_id(
    runtime: Any,
    launch_config: PlanAgentLaunchConfig,
    *,
    workspace_mode: Literal["implementation", "current", "reviews"] = "implementation",
    event_prefix: str = "planning.agent_launch",
) -> _WorkspaceLaunchTarget | None:
    if launch_config.cmux_workspace:
        return _ensure_configured_workspace_id(runtime, launch_config.cmux_workspace, event_prefix=event_prefix)
    target_title, resolved = _default_workspace_target(runtime, launch_config, workspace_mode=workspace_mode)
    if not target_title:
        return None
    if resolved:
        return _WorkspaceLaunchTarget(workspace_id=resolved, created=False)
    created_target, error = _create_named_workspace(runtime, title=target_title, event_prefix=event_prefix)
    if error is not None:
        runtime._emit(f"{event_prefix}.failed", reason="workspace_create_failed", workspace=target_title, error=error)
        return None
    return created_target


def _default_target_workspace_title(
    runtime: Any,
    launch_config: PlanAgentLaunchConfig,
    *,
    workspace_mode: Literal["implementation", "current", "reviews"] = "implementation",
) -> str | None:
    current_title, _ = _default_workspace_target(runtime, launch_config, workspace_mode=workspace_mode)
    return current_title


def _default_workspace_target(
    runtime: Any,
    launch_config: PlanAgentLaunchConfig,
    *,
    workspace_mode: Literal["implementation", "current", "reviews"] = "implementation",
) -> tuple[str | None, str | None]:
    if _missing_required_cmux_context(runtime, launch_config):
        return None, None
    entries = _list_workspaces(runtime)
    current_title = _current_workspace_title(
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


def _review_prompt_arguments(
    *,
    project_name: str,
    project_root: Path,
    review_bundle_path: Path | None,
    original_plan_path: Path | None,
) -> str:
    parts = [f'Project: {project_name}']
    if review_bundle_path is not None:
        parts.append(f'Review bundle: "{review_bundle_path}"')
    parts.append(f'Worktree directory: "{project_root}"')
    if original_plan_path is not None:
        parts.append(f'Original plan file: "{original_plan_path}"')
    return "\n".join(str(part).strip() for part in parts if str(part).strip())


def _review_original_plan_path(project_name: str, project_root: Path, *, repo_root: Path) -> Path | None:
    root = Path(project_root)
    provenance_path = root / _WORKTREE_PROVENANCE_PATH
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        provenance = {}
    recorded_plan = str(provenance.get("plan_file", "")).strip()
    resolved = _resolve_recorded_plan_file(Path(repo_root), recorded_plan)
    if resolved is not None:
        return resolved
    return _infer_plan_file_from_feature(Path(repo_root), feature_name=_feature_name_from_project_name(project_name))


def _resolve_recorded_plan_file(repo_root: Path, recorded_plan: str) -> Path | None:
    normalized_plan = str(recorded_plan or "").strip()
    if not normalized_plan:
        return None
    normalized = Path(normalized_plan.replace("\\", "/").lstrip("./"))
    for root in (_PLANNING_ROOT, _DONE_PLANNING_ROOT):
        candidate = repo_root / root / normalized
        if candidate.is_file():
            return candidate.resolve()
    return None


def _feature_name_from_project_name(project_name: str) -> str:
    normalized = str(project_name).strip()
    return re.sub(r"-\d+$", "", normalized)


def _infer_plan_file_from_feature(repo_root: Path, *, feature_name: str) -> Path | None:
    normalized_feature = str(feature_name).strip()
    if not normalized_feature:
        return None
    matches: list[Path] = []
    for planning_root in (_PLANNING_ROOT, _DONE_PLANNING_ROOT):
        root = repo_root / planning_root
        if not root.is_dir():
            continue
        for candidate in sorted(root.glob("*/*.md")):
            if candidate.name == "README.md":
                continue
            relative = candidate.relative_to(root)
            if planning_feature_name(str(relative).replace("\\", "/")) != normalized_feature:
                continue
            matches.append(candidate.resolve())
    if len(matches) == 1:
        return matches[0]
    return None


def _active_plan_selector_for_path(*, repo_root: Path, plan_path: Path) -> str | None:
    planning_root = repo_root / _PLANNING_ROOT
    try:
        selector = str(plan_path.relative_to(planning_root)).replace("\\", "/")
    except ValueError:
        return None
    selector = selector.strip()
    if not selector:
        return None
    return selector


def resolve_plan_agent_launch_command(*, project_name: str, project_root: Path, repo_root: Path) -> str | None:
    plan_path = _review_original_plan_path(project_name, project_root, repo_root=repo_root)
    if plan_path is None:
        return None
    selector = _active_plan_selector_for_path(repo_root=repo_root, plan_path=plan_path)
    if not selector:
        return None
    return f"envctl --plan {shlex.quote(selector)} --tmux"


def _missing_required_cmux_context(runtime: Any, launch_config: PlanAgentLaunchConfig) -> bool:
    if launch_config.cmux_workspace:
        return False
    if not launch_config.require_cmux_context:
        return False
    return not str(getattr(runtime, "env", {}).get("CMUX_WORKSPACE_ID", "")).strip()


def _current_workspace_title(
    runtime: Any,
    *,
    require_cmux_context: bool,
    workspace_entries: tuple[tuple[str, str], ...] | None = None,
) -> str | None:
    entries = workspace_entries if workspace_entries is not None else _list_workspaces(runtime)
    env_workspace = str(getattr(runtime, "env", {}).get("CMUX_WORKSPACE_ID", "")).strip()
    if env_workspace:
        for workspace_ref, workspace_title in entries:
            if workspace_ref == env_workspace:
                return workspace_title
        identified_ref = _identify_workspace_ref(runtime)
        if identified_ref:
            for workspace_ref, workspace_title in entries:
                if workspace_ref == identified_ref:
                    return workspace_title
        return None
    if not require_cmux_context:
        if entries:
            return entries[0][1]
        current_ref = _current_workspace_ref(runtime, require_cmux_context=False)
        if not current_ref:
            return None
        for workspace_ref, workspace_title in entries:
            if workspace_ref == current_ref:
                return workspace_title
    return None


def _current_workspace_ref(runtime: Any, *, require_cmux_context: bool) -> str | None:
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


def _identify_workspace_ref(runtime: Any) -> str | None:
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
    return _workspace_ref_from_identify_output(str(getattr(result, "stdout", "")))


def _workspace_ref_from_identify_output(raw: str) -> str | None:
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


def _resolve_configured_workspace_id(runtime: Any, configured: str) -> str | None:
    normalized = str(configured).strip()
    if not normalized:
        return None
    if _looks_like_workspace_handle(normalized):
        return normalized
    resolved = _resolve_workspace_ref_by_title(runtime, normalized)
    return resolved


def _ensure_configured_workspace_id(
    runtime: Any,
    configured: str,
    *,
    event_prefix: str = "planning.agent_launch",
) -> _WorkspaceLaunchTarget | None:
    normalized = str(configured).strip()
    if not normalized:
        return None
    if _looks_like_workspace_handle(normalized):
        return _WorkspaceLaunchTarget(workspace_id=normalized, created=False)
    resolved = _resolve_workspace_ref_by_title(runtime, normalized)
    if resolved:
        return _WorkspaceLaunchTarget(workspace_id=resolved, created=False)
    created_target, error = _create_named_workspace(runtime, title=normalized, event_prefix=event_prefix)
    if error is not None:
        runtime._emit(f"{event_prefix}.failed", reason="workspace_create_failed", workspace=normalized, error=error)
        return None
    return created_target


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
    for workspace_ref, workspace_title in _list_workspaces(runtime):
        if workspace_title == str(title).strip():
            return workspace_ref
    return None


def _list_workspaces(runtime: Any) -> tuple[tuple[str, str], ...]:
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
    return _workspace_entries_from_list_output(str(getattr(result, "stdout", "")))


def _workspace_entries_from_list_output(raw: str) -> tuple[tuple[str, str], ...]:
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


def _surface_ids_from_list_output(raw: str) -> tuple[str, ...]:
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


def _list_workspace_surfaces(runtime: Any, *, workspace_id: str) -> tuple[str, ...] | None:
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
    return _surface_ids_from_list_output(str(getattr(result, "stdout", "")))


def _starter_surface_for_new_workspace(runtime: Any, *, workspace_id: str) -> tuple[str | None, str, int | None]:
    surface_ids = _list_workspace_surfaces(runtime, workspace_id=workspace_id)
    if surface_ids is None:
        return None, "probe_failed", None
    if len(surface_ids) == 1:
        return surface_ids[0], "single", 1
    if not surface_ids:
        return None, "none", 0
    return None, "ambiguous", len(surface_ids)


def _create_named_workspace(
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
    runtime._emit(f"{event_prefix}.workspace_created", workspace_id=workspace_ref, title=title)
    starter_surface_id, probe_result, surface_count = _starter_surface_for_new_workspace(runtime, workspace_id=workspace_ref)
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


def _workspace_ref_from_command_output(raw: str) -> str | None:
    for token in raw.replace("\n", " ").split():
        normalized = token.strip()
        if normalized.startswith("workspace:"):
            return normalized
    return None


def _send_surface_text(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    text: str,
    emit_failure_event: bool = True,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    return _run_cmux_command(
        runtime,
        ["cmux", "send", "--workspace", workspace_id, "--surface", surface_id, text],
        emit_failure_event=emit_failure_event,
        failure_event=failure_event,
    )


def _paste_surface_text(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    text: str,
    emit_failure_event: bool = True,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    buffer_name = f"envctl-{str(surface_id).replace(':', '-')}"
    set_error = _run_cmux_command(
        runtime,
        ["cmux", "set-buffer", "--name", buffer_name, text],
        emit_failure_event=emit_failure_event,
        failure_event=failure_event,
    )
    if set_error is not None:
        return set_error
    return _run_cmux_command(
        runtime,
        ["cmux", "paste-buffer", "--name", buffer_name, "--workspace", workspace_id, "--surface", surface_id],
        emit_failure_event=emit_failure_event,
        failure_event=failure_event,
    )


def _send_prompt_text(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    cli: str,
    text: str,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    _ = cli
    if failure_event == "planning.agent_launch.failed":
        return _send_surface_text(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            text=text,
        )
    return _send_surface_text(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        text=text,
        failure_event=failure_event,
    )


def _send_surface_key(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    key: str,
    emit_failure_event: bool = True,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    return _run_cmux_command(
        runtime,
        ["cmux", "send-key", "--workspace", workspace_id, "--surface", surface_id, key],
        emit_failure_event=emit_failure_event,
        failure_event=failure_event,
    )


def _run_cmux_command(
    runtime: Any,
    command: list[str],
    *,
    emit_failure_event: bool = True,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    result = runtime.process_runner.run(
        command,
        cwd=runtime.config.base_dir,
        env=getattr(runtime, "env", {}),
        timeout=10.0,
    )
    if getattr(result, "returncode", 1) == 0:
        return None
    error = _completed_process_error_text(result)
    if emit_failure_event:
        runtime._emit(failure_event, reason="cmux_command_failed", command=command[1], error=error)
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
    required = ["tmux" if launch_config.transport == "tmux" else "cmux"]
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
    prompt_lines = [line.strip().lower() for line in str(prompt_text).splitlines() if line.strip()]
    if not prompt_lines:
        return True
    matched_lines = sum(1 for line in prompt_lines if line in lower_text)
    if matched_lines != len(prompt_lines):
        return False
    if len(prompt_lines) == 1:
        return lower_text.count(prompt_lines[0]) == 1
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


def _normalized_screen_text(raw: str) -> str:
    cleaned = _strip_ansi_sequences(raw).lower()
    return " ".join(cleaned.split())


def _slash_command(cli: str, preset: str, *, arguments: str = "") -> str:
    normalized = str(preset).strip()
    if not normalized:
        normalized = _DEFAULT_PRESET
    trimmed = normalized[1:] if normalized.startswith("/") else normalized
    if str(cli).strip().lower() == "codex":
        if trimmed.startswith("prompts:"):
            command = f"/{trimmed}"
        else:
            command = f"/prompts:{trimmed}"
    else:
        command = normalized if normalized.startswith("/") else f"/{normalized}"
    extra = str(arguments).strip()
    if not extra:
        return command
    return f"{command} {extra}"


def _print_launch_summary(message: str) -> None:
    print(message)


def _persist_runtime_events_snapshot(runtime: Any) -> None:
    persist = getattr(runtime, "_persist_events_snapshot", None)
    if not callable(persist):
        return
    try:
        persist()
    except Exception:
        return
