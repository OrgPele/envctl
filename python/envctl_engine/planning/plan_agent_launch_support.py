from __future__ import annotations
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Literal, Mapping

from envctl_engine.planning import planning_feature_name
from envctl_engine.config import EngineConfig, _apply_plan_agent_aliases
from envctl_engine.debug.debug_utils import scrub_sensitive_text
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

_SUPPORTED_PLAN_AGENT_CLIS = frozenset({"codex", "opencode"})
_CODEX_BYPASS_FLAGS = "--dangerously-bypass-approvals-and-sandbox"
_PROMPT_SHAPING_COMMAND_TOKEN_RE = re.compile(r"^/[A-Za-z][A-Za-z0-9:_-]*$")
_DEFAULT_PRESET = "implement_task"
_DEFAULT_SHELL = "zsh"
_SURFACE_READY_DELAY_SECONDS = 0.15
_DEFAULT_CLI_READY_DELAY_SECONDS = 0.35
_CLI_READY_DELAY_SECONDS_BY_CLI = {
    "codex": 5.0,
    "opencode": 60.0,
}
_CLI_READY_POLL_INTERVAL_SECONDS = 0.1
_READ_SCREEN_LINE_COUNT = 80
_PROMPT_PRE_SUBMIT_DELAY_SECONDS = 0.3
_PROMPT_SUBMIT_READY_DELAY_SECONDS = 0.15
_PROMPT_SUBMIT_READY_TIMEOUT_SECONDS = 1.0
_PROMPT_SUBMIT_READY_POLL_INTERVAL_SECONDS = 0.1
_TMUX_WINDOW_READY_TIMEOUT_SECONDS = 1.0
_TMUX_WINDOW_READY_POLL_INTERVAL_SECONDS = 0.05
_OMX_SESSION_READY_TIMEOUT_SECONDS = 12.0
_OMX_SESSION_READY_POLL_INTERVAL_SECONDS = 0.1
_OMX_SESSION_STATE_RELATIVE_PATH = Path(".omx") / "state" / "session.json"
_OMX_TMUX_EXTENDED_KEYS_RELATIVE_PATH = Path(".omx") / "state" / "tmux-extended-keys"
_OMX_TMUX_LOCK_STALE_SECONDS = 30.0
_OMX_SPAWN_OUTPUT_EXCERPT_CHARS = 1000
_CODEX_QUEUE_READY_TIMEOUT_SECONDS = 10.0
_CODEX_QUEUE_READY_POLL_INTERVAL_SECONDS = 0.1
_CODEX_QUEUE_MAX_TAB_ATTEMPTS = 2
_PLAN_AGENT_TAB_TITLE_MAX_LEN = 36
_LOW_SIGNAL_TAB_TITLE_WORDS = frozenset({"and", "origin"})
_PLAN_AGENT_WORKFLOW_SINGLE_PROMPT = "single_prompt"
_PLAN_AGENT_WORKFLOW_CODEX_CYCLES = "codex_cycles"
_OMX_WORKFLOW_KEYWORDS = frozenset({"ultragoal", "ralph", "team"})
_PROMPT_TEMPLATE_PACKAGE = "envctl_engine.runtime.prompt_templates"
_FINALIZATION_INSTRUCTION_TEMPLATE = "_plan_agent_finalization_instruction"
_FIRST_CYCLE_COMPLETION_TEMPLATE = "_plan_agent_first_cycle_completion"
_INTERMEDIATE_CYCLE_COMPLETION_TEMPLATE = "_plan_agent_intermediate_cycle_completion"
_BROWSER_E2E_FOLLOWUP_TEMPLATE = "_plan_agent_browser_e2e_followup"
_PR_REVIEW_COMMENTS_FOLLOWUP_TEMPLATE = "_plan_agent_pr_review_comments_followup"
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
_CODEX_QUEUE_CONFIRMED_MARKERS = (
    "queued follow-up",
    "queued follow-up messages",
    "follow-up inputs",
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
_AI_CLI_SHELL_FAILURE_MARKERS = (
    "command not found",
    "not recognized",
    "no such file",
    "traceback",
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
    transport: Literal["cmux", "tmux", "omx"]
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
    browser_e2e_followup_enable: bool = True
    pr_review_comments_followup_enable: bool = True
    omx_workflow: Literal["", "ultragoal", "ralph", "team"] = ""
    codex_goal_enable: bool = True


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
class PlanAgentAttachValidation:
    ok: bool
    reason: str
    session_name: str = ""
    attach_command: str = ""


@dataclass(slots=True, frozen=True)
class AgentTerminalLaunchResult:
    status: str
    reason: str
    surface_id: str | None = None


@dataclass(slots=True, frozen=True)
class AiCliReadyResult:
    ready: bool
    reason: str
    screen_excerpt: str = ""


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


@dataclass(slots=True, frozen=True)
class _OmxSessionRecord:
    omx_root: Path
    state_path: Path
    payload: dict[str, object]


@dataclass(slots=True, frozen=True)
class _OmxSpawnProcessRecord:
    process: object
    command: tuple[str, ...]
    popen_command: tuple[str, ...]
    worktree_name: str
    worktree_root: Path
    omx_root: Path
    started_at: str
    madmax: bool


class _QueueFailure(str):
    step_index: int | None
    step_kind: str | None

    def __new__(cls, reason: str, *, step_index: int | None = None, step_kind: str | None = None) -> "_QueueFailure":
        obj = str.__new__(cls, reason)
        obj.step_index = step_index
        obj.step_kind = step_kind
        return obj


def _finalization_instruction_text() -> str:
    return _load_plan_agent_followup_prompt(_FINALIZATION_INSTRUCTION_TEMPLATE)


def _first_cycle_completion_instruction_text() -> str:
    return _load_plan_agent_followup_prompt(_FIRST_CYCLE_COMPLETION_TEMPLATE)


def _intermediate_cycle_completion_instruction_text() -> str:
    return _load_plan_agent_followup_prompt(_INTERMEDIATE_CYCLE_COMPLETION_TEMPLATE)


def _browser_e2e_instruction_text() -> str:
    return _load_plan_agent_followup_prompt(_BROWSER_E2E_FOLLOWUP_TEMPLATE)


def _pr_review_comments_instruction_text() -> str:
    return _load_plan_agent_followup_prompt(_PR_REVIEW_COMMENTS_FOLLOWUP_TEMPLATE)


def _load_plan_agent_followup_prompt(name: str) -> str:
    template_name = f"{str(name).strip()}.md"
    template_file = resources.files(_PROMPT_TEMPLATE_PACKAGE).joinpath(template_name)
    if not template_file.is_file():
        raise LookupError(f"Missing plan-agent follow-up prompt template: {template_name}")
    body = template_file.read_text(encoding="utf-8").strip()
    if not body:
        raise ValueError(f"Plan-agent follow-up prompt template is empty: {template_name}")
    return body


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
    if _codex_tui_queue_workflow_supported(launch_config) and launch_config.codex_cycles > 0:
        return _PLAN_AGENT_WORKFLOW_CODEX_CYCLES
    return _PLAN_AGENT_WORKFLOW_SINGLE_PROMPT


def _codex_tui_queue_workflow_supported(launch_config: PlanAgentLaunchConfig) -> bool:
    return launch_config.cli == "codex" and launch_config.transport in {"cmux", "tmux", "omx"}


def _uses_direct_submission(*, cli: str, direct_prompt_enabled: bool) -> bool:
    normalized_cli = str(cli).strip().lower()
    if normalized_cli == "codex":
        return True
    return normalized_cli == "opencode" and direct_prompt_enabled


def _build_plan_agent_workflow(
    *,
    cli: str,
    preset: str,
    codex_cycles: int,
    direct_prompt_enabled: bool = False,
    browser_e2e_followup_enable: bool = True,
    pr_review_comments_followup_enable: bool = True,
) -> _PlanAgentWorkflow:
    normalized_cli = str(cli).strip().lower()
    bounded_cycles = max(0, min(int(codex_cycles), _PLAN_AGENT_CODEX_CYCLE_CAP))
    if _uses_direct_submission(cli=normalized_cli, direct_prompt_enabled=direct_prompt_enabled):
        initial_step = _PlanAgentWorkflowStep(kind="submit_direct_prompt", text=str(preset).strip())
    else:
        initial_step = _PlanAgentWorkflowStep(kind="submit_prompt", text=_slash_command(cli, preset))
    if normalized_cli != "codex" or bounded_cycles <= 0:
        steps = [initial_step]
        if normalized_cli == "codex":
            if browser_e2e_followup_enable:
                steps.append(_PlanAgentWorkflowStep(kind="queue_message", text=_browser_e2e_instruction_text()))
            if pr_review_comments_followup_enable:
                steps.append(
                    _PlanAgentWorkflowStep(kind="queue_message", text=_pr_review_comments_instruction_text())
                )
        return _PlanAgentWorkflow(
            mode=_PLAN_AGENT_WORKFLOW_SINGLE_PROMPT,
            codex_cycles=bounded_cycles,
            steps=tuple(steps),
        )
    steps = [_PlanAgentWorkflowStep(kind="submit_direct_prompt", text="implement_task")]
    for cycle in range(1, bounded_cycles + 1):
        if cycle == bounded_cycles:
            steps.append(_PlanAgentWorkflowStep(kind="queue_direct_prompt", text="finalize_task"))
            if browser_e2e_followup_enable:
                steps.append(_PlanAgentWorkflowStep(kind="queue_message", text=_browser_e2e_instruction_text()))
            if pr_review_comments_followup_enable:
                steps.append(
                    _PlanAgentWorkflowStep(kind="queue_message", text=_pr_review_comments_instruction_text())
                )
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
    opencode_launch_requested = bool(route_flags.get("opencode"))
    transport: Literal["cmux", "tmux", "omx"] = (
        "omx"
        if bool(route_flags.get("omx"))
        else ("tmux" if bool(route_flags.get("tmux")) or opencode_launch_requested else "cmux")
    )
    cli = str(
        "opencode"
        if bool(route_flags.get("opencode"))
        else (
            "codex"
            if bool(route_flags.get("codex")) or transport == "omx"
            else (
            env_map.get("ENVCTL_PLAN_AGENT_CLI")
            or config.raw.get("ENVCTL_PLAN_AGENT_CLI")
            or "codex"
            )
        )
    ).strip().lower() or "codex"
    codex_yolo_enabled = parse_bool(
        env_map.get("ENVCTL_PLAN_AGENT_CODEX_YOLO")
        or config.raw.get("ENVCTL_PLAN_AGENT_CODEX_YOLO"),
        True,
    )
    cli_command = str(
        env_map.get("ENVCTL_PLAN_AGENT_CLI_CMD")
        or config.raw.get("ENVCTL_PLAN_AGENT_CLI_CMD")
        or _default_plan_agent_cli_command(cli, codex_yolo_enabled=codex_yolo_enabled)
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
    ) or bool(cmux_workspace) or transport in {"tmux", "omx"}
    direct_prompt_enabled = parse_bool(
        env_map.get("ENVCTL_PLAN_AGENT_DIRECT_PROMPT")
        or config.raw.get("ENVCTL_PLAN_AGENT_DIRECT_PROMPT"),
        True if (transport == "tmux" and cli == "opencode") else False,
    )
    ulw_loop_prefix = parse_bool(
        env_map.get("ENVCTL_PLAN_AGENT_ULW_LOOP_PREFIX")
        or config.raw.get("ENVCTL_PLAN_AGENT_ULW_LOOP_PREFIX"),
        True if (transport == "tmux" and cli == "opencode" and direct_prompt_enabled) else False,
    )
    ulw_suffix = parse_bool(
        env_map.get("ENVCTL_PLAN_AGENT_APPEND_ULW")
        or config.raw.get("ENVCTL_PLAN_AGENT_APPEND_ULW"),
        False,
    )
    if bool(route_flags.get("ulw")):
        ulw_loop_prefix = True
        if transport == "tmux" and cli == "opencode":
            direct_prompt_enabled = True
    omx_workflow: Literal["", "ultragoal", "ralph", "team"] = ""
    if bool(route_flags.get("ultragoal")):
        omx_workflow = "ultragoal"
    elif bool(route_flags.get("ralph")):
        omx_workflow = "ralph"
    elif bool(route_flags.get("team")):
        omx_workflow = "team"
    goal_enabled = False
    if cli == "codex":
        goal_enabled = parse_bool(
            env_map.get("ENVCTL_PLAN_AGENT_CODEX_GOAL_ENABLE")
            or config.raw.get("ENVCTL_PLAN_AGENT_CODEX_GOAL_ENABLE"),
            True,
        )
        if bool(route_flags.get("goal")) or bool(route_flags.get("codex_goal")):
            goal_enabled = True
        if bool(route_flags.get("no_goal")) or bool(route_flags.get("no_codex_goal")):
            goal_enabled = False
    return PlanAgentLaunchConfig(
        enabled=enabled,
        transport=transport,
        cli=cli,
        cli_command=cli_command,
        preset=preset,
        codex_cycles=codex_cycles,
        codex_cycles_warning=codex_cycles_warning,
        browser_e2e_followup_enable=parse_bool(
            env_map.get("ENVCTL_PLAN_AGENT_BROWSER_E2E_ENABLE")
            or config.raw.get("ENVCTL_PLAN_AGENT_BROWSER_E2E_ENABLE"),
            True,
        ),
        pr_review_comments_followup_enable=parse_bool(
            env_map.get("ENVCTL_PLAN_AGENT_PR_REVIEW_COMMENTS_ENABLE")
            or config.raw.get("ENVCTL_PLAN_AGENT_PR_REVIEW_COMMENTS_ENABLE"),
            True,
        ),
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
        omx_workflow=omx_workflow,
        codex_goal_enable=goal_enabled,
    )


def _default_plan_agent_cli_command(cli: str, *, codex_yolo_enabled: bool = True) -> str:
    normalized = str(cli).strip().lower()
    if normalized == "codex":
        if codex_yolo_enabled:
            return f"codex {_CODEX_BYPASS_FLAGS}"
        return "codex"
    return normalized or "codex"


def _route_requests_ulw(route: object | None) -> bool:
    return bool(getattr(route, "flags", {}).get("ulw"))


def _ulw_route_supported(*, launch_config: PlanAgentLaunchConfig) -> bool:
    return launch_config.transport == "tmux" and launch_config.cli == "opencode"


def _guidance_attach_command(session_name: str) -> tuple[str, ...]:
    return ("tmux", "attach", "-t", session_name)


def plan_agent_launch_prereq_commands(
    config: EngineConfig,
    env: dict[str, str] | None = None,
    *,
    route: object | None = None,
) -> tuple[str, ...]:
    launch_config = resolve_plan_agent_launch_config(config, env, route=route)
    if not launch_config.enabled:
        return ()
    if launch_config.transport == "omx":
        return ("omx", "tmux", "script", "codex")
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
        browser_e2e_followup_enable=launch_config.browser_e2e_followup_enable,
        pr_review_comments_followup_enable=launch_config.pr_review_comments_followup_enable,
    )
    workspace_id = None if launch_config.transport == "tmux" else _resolve_workspace_id(runtime, launch_config)
    target_workspace = (
        None
        if launch_config.transport == "tmux"
        else (launch_config.cmux_workspace or _default_target_workspace_title(runtime, launch_config))
    )
    payload: dict[str, object] = {
        "enabled": launch_config.enabled,
        "transport": launch_config.transport,
        "cli": launch_config.cli,
        "preset": launch_config.preset,
        "workflow_mode": workflow.mode,
        "codex_cycles": launch_config.codex_cycles,
        "omx_workflow": launch_config.omx_workflow or None,
        "workflow_warning": launch_config.codex_cycles_warning,
        "codex_goal_enable": launch_config.codex_goal_enable,
        "shell": launch_config.shell,
        "direct_prompt_enabled": launch_config.direct_prompt_enabled,
        "ulw_loop_prefix": launch_config.ulw_loop_prefix,
        "ulw_suffix": launch_config.ulw_suffix,
        "browser_e2e_followup_enable": launch_config.browser_e2e_followup_enable,
        "pr_review_comments_followup_enable": launch_config.pr_review_comments_followup_enable,
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
    if launch_config.transport == "omx" and launch_config.cli != "codex":
        payload["reason"] = "unsupported_omx_cli"
        return payload
    if _route_requests_ulw(route) and not _ulw_route_supported(launch_config=launch_config):
        payload["reason"] = "unsupported_ulw_flag"
        return payload
    if launch_config.transport == "cmux" and _missing_required_cmux_context(runtime, launch_config):
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
    reason = (
        "missing_cmux_context"
        if _missing_required_cmux_context(runtime, launch_config)
        else "workspace_unavailable"
    )
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
        reason = (
            "missing_cmux_context"
            if _missing_required_cmux_context(runtime, launch_config)
            else "workspace_unavailable"
        )
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
        browser_e2e_followup_enable=launch_config.browser_e2e_followup_enable,
        pr_review_comments_followup_enable=launch_config.pr_review_comments_followup_enable,
    )
    base_payload = {
        "enabled": launch_config.enabled,
        "cli": launch_config.cli,
        "created_worktree_count": len(created_worktrees),
        "workflow_mode": workflow.mode,
        "codex_cycles": launch_config.codex_cycles,
        "codex_goal_enable": launch_config.codex_goal_enable,
        "browser_e2e_followup_enable": launch_config.browser_e2e_followup_enable,
        "pr_review_comments_followup_enable": launch_config.pr_review_comments_followup_enable,
    }
    if str(getattr(route, "command", "")).strip() != "plan" or bool(getattr(route, "flags", {}).get("planning_prs")):
        runtime._emit("planning.agent_launch.skipped", reason="inapplicable_route", **base_payload)
        return PlanAgentLaunchResult(status="skipped", reason="inapplicable_route")
    if not launch_config.enabled:
        runtime._emit("planning.agent_launch.skipped", reason="disabled", **base_payload)
        return PlanAgentLaunchResult(status="skipped", reason="disabled")
    if _route_requests_ulw(route) and not _ulw_route_supported(launch_config=launch_config):
        _print_launch_summary("Plan agent launch skipped: --ulw requires --tmux --opencode.")
        runtime._emit("planning.agent_launch.failed", reason="unsupported_ulw_flag", **base_payload)
        return PlanAgentLaunchResult(status="failed", reason="unsupported_ulw_flag")
    if not created_worktrees:
        _print_launch_summary("Plan agent launch skipped: no new worktrees were created.")
        runtime._emit("planning.agent_launch.skipped", reason="no_new_worktrees", **base_payload)
        return PlanAgentLaunchResult(status="skipped", reason="no_new_worktrees")
    if launch_config.transport == "cmux" and _missing_required_cmux_context(runtime, launch_config):
        _print_launch_summary(
            "Plan agent launch skipped: no active cmux workspace context found. "
            "Fix by setting ENVCTL_PLAN_AGENT_CMUX_WORKSPACE=<workspace-id>, "
            "setting ENVCTL_PLAN_AGENT_REQUIRE_CMUX_CONTEXT=false, "
            "or running envctl from within an active cmux session."
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
    if launch_config.transport == "omx":
        return _launch_plan_agent_omx_terminals(
            runtime,
            route=route,
            launch_config=launch_config,
            workflow=workflow,
            created_worktrees=created_worktrees,
            base_payload=base_payload,
            prompt_on_existing=not bool(getattr(route, "flags", {}).get("batch")),
        )
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
            "Plan agent launch queued Codex cycle workflow "
            f"(cycles={workflow.codex_cycles}) for {len(created_worktrees)} surface(s)."
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
    base_payload: Mapping[str, object],
    prompt_on_existing: bool,
) -> PlanAgentLaunchResult:
    repo_root = Path(runtime.config.base_dir).resolve()
    attach_via = "switch-client" if str(getattr(runtime, "env", {}).get("TMUX", "")).strip() else "attach-session"
    route_flags = getattr(route, "flags", {}) or {}
    create_new_session = bool(route_flags.get("tmux_new_session"))
    prompt_existing_possible = not create_new_session and _should_prompt_existing_tmux_session(
        runtime,
        prompt_on_existing=prompt_on_existing,
    )
    existing_attach_target = _find_existing_tmux_attach_target(
        runtime,
        repo_root=repo_root,
        created_worktrees=created_worktrees,
        cli=launch_config.cli,
    )
    unhealthy_existing_reason = str(getattr(runtime, "_last_unhealthy_existing_tmux_session_reason", "") or "")
    unhealthy_existing_outcomes = tuple(getattr(runtime, "_last_unhealthy_existing_tmux_session_outcomes", ()) or ())
    if hasattr(runtime, "_last_unhealthy_existing_tmux_session_reason"):
        try:
            delattr(runtime, "_last_unhealthy_existing_tmux_session_reason")
        except AttributeError:
            pass
    if hasattr(runtime, "_last_unhealthy_existing_tmux_session_outcomes"):
        try:
            delattr(runtime, "_last_unhealthy_existing_tmux_session_outcomes")
        except AttributeError:
            pass
    if existing_attach_target is None and unhealthy_existing_reason:
        return PlanAgentLaunchResult(
            status="failed",
            reason=unhealthy_existing_reason,
            outcomes=unhealthy_existing_outcomes,
            attach_target=None,
        )
    if existing_attach_target is not None:
        if prompt_existing_possible:
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
                attach_command=_guidance_attach_command(session_name),
            )
    launched = [item for item in outcomes if item.status == "launched"]
    failed = [item for item in outcomes if item.status == "failed"]
    attach_target = first_attach_target or existing_attach_target
    if failed and launched:
        details = _summarize_failed_launch_outcomes(failed)
        suffix = f" Details: {details}." if details else ""
        _print_launch_summary(
            f"Plan agent launch finished with partial success: launched {len(launched)}, failed {len(failed)}.{suffix}"
        )
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
        return PlanAgentLaunchResult(status="failed", reason="launch_failed", outcomes=tuple(outcomes))
    _print_launch_summary(f"Plan agent launch prepared {len(launched)} tmux session(s).")
    return PlanAgentLaunchResult(
        status="launched",
        reason="launched",
        outcomes=tuple(outcomes),
        attach_target=attach_target,
    )


def _launch_plan_agent_omx_terminals(
    runtime: Any,
    *,
    route: object,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    created_worktrees: tuple[CreatedPlanWorktree, ...],
    base_payload: Mapping[str, object],
    prompt_on_existing: bool,
) -> PlanAgentLaunchResult:
    if launch_config.cli != "codex":
        runtime._emit("planning.agent_launch.failed", reason="unsupported_omx_cli", **base_payload)
        return PlanAgentLaunchResult(status="failed", reason="unsupported_omx_cli")
    repo_root = Path(runtime.config.base_dir).resolve()
    attach_via = "switch-client" if str(getattr(runtime, "env", {}).get("TMUX", "")).strip() else "attach-session"
    route_flags = getattr(route, "flags", {}) or {}
    create_new_session = bool(route_flags.get("tmux_new_session"))
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
            action = _prompt_existing_tmux_session_action(runtime, attach_target=existing_attach_target)
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
        error = _run_tmux_existing_session_workflow(
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


def _prompt_existing_tmux_session_action(
    runtime: Any,
    *,
    attach_target: PlanAgentAttachTarget,
) -> Literal["attach", "new"]:
    prompt = (
        f"An envctl tmux session already exists for this plan/workspace ({attach_target.session_name}). "
        f"Attach to it? (Y=attach / n=create new session): "
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


def _plan_selector_for_route(route: object, created_worktrees: tuple[CreatedPlanWorktree, ...]) -> str:
    route_passthrough = list(getattr(route, "passthrough_args", []) or [])
    if route_passthrough:
        selector = str(route_passthrough[0]).strip()
        if selector:
            return selector
    route_projects = list(getattr(route, "projects", []) or [])
    if route_projects:
        selector = str(route_projects[0]).strip()
        if selector:
            return selector
    if created_worktrees:
        plan_file = str(created_worktrees[0].plan_file or "").strip()
        if plan_file:
            return plan_file.removesuffix(".md")
    return ""


def plan_agent_native_recovery_command(
    runtime: Any,
    *,
    route: object,
    launch_config: PlanAgentLaunchConfig,
    created_worktrees: tuple[CreatedPlanWorktree, ...],
) -> tuple[str, ...]:
    selector = _plan_selector_for_route(route, created_worktrees)
    if not selector:
        return ()
    command: list[str] = []
    if launch_config.codex_cycles > 0:
        command.append(f"ENVCTL_PLAN_AGENT_CODEX_CYCLES={launch_config.codex_cycles}")
    command.extend(
        [
            "ENVCTL_USE_REPO_WRAPPER=1",
            str(Path(runtime.config.base_dir).resolve() / "bin" / "envctl"),
            "--plan",
            selector,
            "--tmux",
        ]
    )
    if launch_config.cli == "opencode":
        command.append("--opencode")
    elif launch_config.cli == "codex":
        command.append("--codex")
    route_flags = getattr(route, "flags", {}) or {}
    scope_token_by_value = {
        "backend": "--backend",
        "frontend": "--frontend",
        "fullstack": "--fullstack",
        "dependencies": "--dependencies",
        "entire-system": "--entire-system",
    }
    scope_token = scope_token_by_value.get(str(route_flags.get("runtime_scope") or ""))
    if scope_token:
        command.append(scope_token)
    launch_backend = route_flags.get("launch_backend")
    launch_frontend = route_flags.get("launch_frontend")
    launch_dependencies = route_flags.get("launch_dependencies")
    if launch_backend is False and launch_frontend is False and launch_dependencies is False:
        command.append("--no-infra")
    elif launch_backend is True and launch_frontend is False and launch_dependencies is False:
        command.append("--only-backend")
    elif launch_backend is False and launch_frontend is True and launch_dependencies is False:
        command.append("--only-frontend")
    elif launch_dependencies is False:
        command.append("--no-deps")
    dependency_scope = str(route_flags.get("dependency_scope") or "").strip()
    if dependency_scope == "shared":
        command.append("--shared-deps")
    elif dependency_scope == "isolated":
        command.append("--isolated-deps")
    if bool(route_flags.get("batch") or route_flags.get("default_headless")):
        command.append("--headless")
    command.append("--tmux-new-session")
    return tuple(command)


def _plan_agent_recovery_command_text(command: tuple[str, ...]) -> str:
    return shlex.join(command) if command else ""


def _new_session_command_for_route(
    runtime: Any,
    *,
    route: object,
    launch_config: PlanAgentLaunchConfig,
    created_worktrees: tuple[CreatedPlanWorktree, ...],
) -> tuple[str, ...]:
    selector = _plan_selector_for_route(route, created_worktrees)
    if not selector:
        return ()
    command = [
        "ENVCTL_USE_REPO_WRAPPER=1",
        str(Path(runtime.config.base_dir).resolve() / "bin" / "envctl"),
        "--plan",
        selector,
        "--omx" if launch_config.transport == "omx" else "--tmux",
    ]
    if launch_config.cli == "opencode":
        command.append("--opencode")
    elif launch_config.cli == "codex":
        command.append("--codex")
    route_flags = getattr(route, "flags", {}) or {}
    workflow_tokens = (("ultragoal", "--ultragoal"), ("ralph", "--ralph"), ("team", "--team"), ("ulw", "--ulw"))
    for flag_name, token in workflow_tokens:
        if bool(route_flags.get(flag_name)):
            command.append(token)
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
    normalized_window = str(window_name).strip()
    if normalized_window.startswith("%"):
        return normalized_window
    if not normalized_window:
        return session_name
    return f"{session_name}:{normalized_window}"


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
        option_error = _enable_tmux_mouse_scrollback(runtime, session_name=session_name)
        if option_error is not None:
            return option_error
        wait_error = _wait_for_tmux_window_ready(runtime, session_name=session_name, window_name=window_name)
        if wait_error is None:
            return None
        return wait_error
    return _tmux_completed_process_error_text(result)


def _enable_tmux_mouse_scrollback(runtime: Any, *, session_name: str) -> str | None:
    result = _run_tmux_probe(
        runtime,
        ("tmux", "set-option", "-t", session_name, "mouse", "on"),
        cwd=Path(runtime.config.base_dir).resolve(),
    )
    if result.returncode == 0:
        return None
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
        attach_command=_guidance_attach_command(session_name),
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
            attach_command=_guidance_attach_command(_tmux_session_name_for_worktree(repo_root, worktree, cli=cli)),
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
                health = _existing_tmux_session_health(
                    runtime,
                    session_name=session_name,
                    window_name=window_name,
                    cli=cli,
                )
                if not health.ready:
                    reason = f"existing_{str(cli).strip().lower() or 'ai'}_session_unhealthy"
                    detail = _format_ai_cli_ready_failure(
                        AiCliReadyResult(ready=False, reason=reason, screen_excerpt=health.screen_excerpt)
                    )
                    setattr(runtime, "_last_unhealthy_existing_tmux_session_reason", reason)
                    setattr(
                        runtime,
                        "_last_unhealthy_existing_tmux_session_outcomes",
                        (
                            PlanAgentLaunchOutcome(
                                worktree_name=next(
                                    (
                                        worktree.name
                                        for worktree in created_worktrees
                                        if Path(worktree.root).expanduser().resolve(strict=False) == target
                                    ),
                                    "",
                                ),
                                worktree_root=target,
                                surface_id=None,
                                status="failed",
                                reason=detail,
                            ),
                        ),
                    )
                    runtime._emit(
                        "planning.agent_launch.existing_session_unhealthy",
                        session_name=session_name,
                        window_name=window_name,
                        cli=cli,
                        reason=detail,
                    )
                    continue
                return PlanAgentAttachTarget(
                    repo_root=repo_root,
                    session_name=session_name,
                    window_name=window_name,
                    attach_via="attach-session",
                    attach_command=_guidance_attach_command(session_name),
                )
    return None


def _existing_tmux_session_looks_healthy(runtime: Any, *, session_name: str, window_name: str, cli: str) -> bool:
    return _existing_tmux_session_health(
        runtime,
        session_name=session_name,
        window_name=window_name,
        cli=cli,
    ).ready


def _existing_tmux_session_health(runtime: Any, *, session_name: str, window_name: str, cli: str) -> AiCliReadyResult:
    normalized_cli = str(cli).strip().lower()
    if normalized_cli not in {"opencode", "codex"}:
        return AiCliReadyResult(ready=True, reason="health_check_not_required")
    screen = _read_tmux_screen(runtime, session_name=session_name, window_name=window_name)
    if not str(screen or "").strip():
        return AiCliReadyResult(ready=False, reason=f"existing_{normalized_cli}_session_empty", screen_excerpt="")
    if _screen_looks_ready(normalized_cli, screen) or _screen_looks_active(normalized_cli, screen):
        return AiCliReadyResult(ready=True, reason="healthy", screen_excerpt=_screen_excerpt(screen))
    return AiCliReadyResult(
        ready=False,
        reason=f"existing_{normalized_cli}_session_unhealthy",
        screen_excerpt=_screen_excerpt(screen),
    )


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


def _run_tmux_existing_session_workflow(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    worktree: CreatedPlanWorktree,
) -> str | None:
    ready_result = _wait_for_tmux_cli_ready(
        runtime,
        session_name=session_name,
        window_name=window_name,
        cli=launch_config.cli,
    )
    if ready_result is not None and not ready_result.ready:
        return _format_ai_cli_ready_failure(ready_result)
    goal_error = _maybe_submit_tmux_codex_goal(
        runtime,
        session_name=session_name,
        window_name=window_name,
        launch_config=launch_config,
        workflow=workflow,
        worktree=worktree,
        transport="omx",
    )
    if goal_error is not None and goal_error != "codex_goal_ready_timeout":
        return goal_error
    if goal_error is None and launch_config.codex_goal_enable and launch_config.cli == "codex":
        ready_result = _wait_for_tmux_cli_ready(
            runtime,
            session_name=session_name,
            window_name=window_name,
            cli=launch_config.cli,
        )
        if ready_result is not None and not ready_result.ready:
            return _format_ai_cli_ready_failure(ready_result)
    prompt_text, resolution_error = _workflow_step_prompt_text(
        runtime,
        launch_config=launch_config,
        cli=launch_config.cli,
        step=workflow.steps[0],
        worktree=worktree,
    )
    if resolution_error is not None:
        return resolution_error
    prompt_text = _wrap_omx_initial_prompt_for_workflow(prompt_text, workflow=launch_config.omx_workflow)
    submit_error = _submit_tmux_prompt_workflow_step(
        runtime,
        session_name=session_name,
        window_name=window_name,
        prompt_text=prompt_text,
        cli=launch_config.cli,
    )
    if submit_error is not None:
        return submit_error
    queued_steps = workflow.steps[1:]
    if queued_steps and launch_config.cli == "codex":
        queue_error_reason = _queue_tmux_codex_workflow_steps(
            runtime,
            session_name=session_name,
            window_name=window_name,
            worktree=worktree,
            workflow=workflow,
            queued_steps=queued_steps,
            launch_config=launch_config,
            cli=launch_config.cli,
            transport="omx",
        )
        if queue_error_reason is not None:
            failure_context = _queue_failure_event_context(queue_error_reason)
            runtime._emit(
                "planning.agent_launch.workflow_queue_failed",
                session_name=session_name,
                window_name=window_name,
                worktree=worktree.name,
                cli=launch_config.cli,
                workflow_mode=workflow.mode,
                codex_cycles=workflow.codex_cycles,
                reason=queue_error_reason,
                transport="omx",
                **failure_context,
            )
            runtime._emit(
                "planning.agent_launch.workflow_fallback",
                session_name=session_name,
                window_name=window_name,
                worktree=worktree.name,
                cli=launch_config.cli,
                workflow_mode=workflow.mode,
                codex_cycles=workflow.codex_cycles,
                reason=queue_error_reason,
                transport="omx",
                **failure_context,
            )
            return None
    return None


def _codex_goal_text_for_worktree(
    *,
    worktree: CreatedPlanWorktree,
    preset: str,
    workflow_mode: str,
    omx_workflow: str,
) -> str:
    plan_selector = str(worktree.plan_file or "").strip() or str(worktree.name).strip() or "selected plan"
    lines = [
        f"Implement the envctl plan-agent task for {plan_selector} in this worktree.",
        "Authoritative source: MAIN_TASK.md in the current worktree.",
        f"Initial preset: {str(preset).strip() or _DEFAULT_PRESET}.",
        f"Workflow mode: {str(workflow_mode).strip() or _PLAN_AGENT_WORKFLOW_SINGLE_PROMPT}.",
    ]
    normalized_omx = str(omx_workflow or "").strip().lower()
    if normalized_omx:
        lines.append(f"OMX workflow: ${normalized_omx}; keep its completion contract active after this goal frame.")
    lines.append("Complete the implementation, run relevant tests, commit, and open/update the PR when green.")
    return " ".join(lines)


def _emit_codex_goal_event(
    runtime: Any,
    event: str,
    *,
    cli: str,
    workflow: _PlanAgentWorkflow,
    transport: str,
    worktree: CreatedPlanWorktree,
    reason: str | None = None,
    **target: object,
) -> None:
    payload: dict[str, object] = {
        **target,
        "worktree": worktree.name,
        "cli": cli,
        "workflow_mode": workflow.mode,
        "codex_cycles": workflow.codex_cycles,
        "transport": transport,
    }
    if reason is not None:
        payload["reason"] = reason
    runtime._emit(event, **payload)


def _maybe_submit_tmux_codex_goal(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    worktree: CreatedPlanWorktree,
    transport: str,
) -> str | None:
    if launch_config.cli != "codex" or not launch_config.codex_goal_enable:
        return None
    goal_text = _codex_goal_text_for_worktree(
        worktree=worktree,
        preset=launch_config.preset,
        workflow_mode=workflow.mode,
        omx_workflow=launch_config.omx_workflow,
    )
    error = _submit_tmux_codex_goal(
        runtime,
        session_name=session_name,
        window_name=window_name,
        goal_text=goal_text,
    )
    if error is None:
        _emit_codex_goal_event(
            runtime,
            "planning.agent_launch.codex_goal_submitted",
            session_name=session_name,
            window_name=window_name,
            cli=launch_config.cli,
            workflow=workflow,
            transport=transport,
            worktree=worktree,
        )
        return None
    if error == "codex_goal_ready_timeout":
        _emit_codex_goal_event(
            runtime,
            "planning.agent_launch.codex_goal_fallback",
            session_name=session_name,
            window_name=window_name,
            cli=launch_config.cli,
            workflow=workflow,
            transport=transport,
            worktree=worktree,
            reason=error,
        )
        return error
    return error


def _submit_tmux_codex_goal(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    goal_text: str,
) -> str | None:
    submit_error = _submit_tmux_prompt_workflow_step(
        runtime,
        session_name=session_name,
        window_name=window_name,
        prompt_text=f"/goal {goal_text}",
        cli="codex",
    )
    if submit_error is not None:
        return submit_error
    if not _wait_for_tmux_prompt_ready_after_goal(runtime, session_name=session_name, window_name=window_name):
        return "codex_goal_ready_timeout"
    return None


def _wait_for_tmux_prompt_ready_after_goal(runtime: Any, *, session_name: str, window_name: str) -> bool:
    deadline = time.monotonic() + _PROMPT_SUBMIT_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        screen = _read_tmux_screen(runtime, session_name=session_name, window_name=window_name)
        if _screen_looks_ready("codex", screen):
            return True
        time.sleep(_PROMPT_SUBMIT_READY_POLL_INTERVAL_SECONDS)
    return False


def _wrap_omx_initial_prompt_for_workflow(text: str, *, workflow: str) -> str:
    normalized_workflow = str(workflow or "").strip().lower()
    if normalized_workflow not in _OMX_WORKFLOW_KEYWORDS:
        return text
    stripped = str(text).lstrip()
    prefix = f"${normalized_workflow}"
    if stripped == prefix or stripped.startswith(f"{prefix} ") or stripped.startswith(f"{prefix}\n"):
        return text
    return f"{prefix}\n\n{text}"


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
    if not _tmux_session_exists(runtime, session_name):
        reason = "omx_attach_target_stale" if str(transport).strip().lower() == "omx" else "attach_target_stale"
        runtime._emit("planning.agent_launch.attach_validation.failed", reason=reason, **payload)
        return PlanAgentAttachValidation(False, reason, session_name=session_name, attach_command=attach_command)
    pane_ok, pane_id = _tmux_display_message_succeeds(runtime, session_name)
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


def _tmux_display_message_succeeds(runtime: Any, session_name: str) -> tuple[bool, str]:
    result = _run_tmux_probe(
        runtime,
        ("tmux", "display-message", "-p", "-t", session_name, "#{pane_id}"),
        cwd=Path(runtime.config.base_dir).resolve(),
    )
    if result.returncode != 0:
        return False, ""
    return True, str(getattr(result, "stdout", "")).strip()


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


def _summarize_failed_launch_outcomes(outcomes: list[PlanAgentLaunchOutcome], *, limit: int = 2) -> str:
    details: list[str] = []
    for item in outcomes[:limit]:
        reason = str(item.reason or "").strip()
        if not reason:
            continue
        details.append(f"{item.worktree_name}: {reason}")
    if not details:
        return ""
    suffix = "" if len(outcomes) <= limit else f"; +{len(outcomes) - limit} more"
    return "; ".join(details) + suffix


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
        _send_tmux_text(
            runtime,
            session_name=session_name,
            window_name=window_name,
            text=f"cd {typed_root}",
            emit_failure_event=emit_failure_event,
            failure_event=failure_event,
        ),
        _send_tmux_key(
            runtime,
            session_name=session_name,
            window_name=window_name,
            key="enter",
            emit_failure_event=emit_failure_event,
            failure_event=failure_event,
        ),
        _send_tmux_text(
            runtime,
            session_name=session_name,
            window_name=window_name,
            text=cli_command,
            emit_failure_event=emit_failure_event,
            failure_event=failure_event,
        ),
        _send_tmux_key(
            runtime,
            session_name=session_name,
            window_name=window_name,
            key="enter",
            emit_failure_event=emit_failure_event,
            failure_event=failure_event,
        ),
    ]


def _wait_for_tmux_cli_ready(runtime: Any, *, session_name: str, window_name: str, cli: str) -> AiCliReadyResult:
    normalized_cli = str(cli).strip().lower()
    timeout_seconds = _cli_ready_delay_seconds(normalized_cli)
    if normalized_cli not in {"codex", "opencode"}:
        time.sleep(timeout_seconds)
        return AiCliReadyResult(ready=True, reason="unsupported_cli_assumed_ready")
    deadline = time.monotonic() + timeout_seconds
    last_screen = ""
    while time.monotonic() < deadline:
        last_screen = _read_tmux_screen(runtime, session_name=session_name, window_name=window_name)
        if _screen_looks_ready(normalized_cli, last_screen):
            return AiCliReadyResult(ready=True, reason="ready", screen_excerpt=_screen_excerpt(last_screen))
        time.sleep(_CLI_READY_POLL_INTERVAL_SECONDS)
    return AiCliReadyResult(
        ready=False,
        reason=f"{normalized_cli}_ready_timeout",
        screen_excerpt=_screen_excerpt(last_screen),
    )


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
    enter_error = _send_tmux_key(runtime, session_name=session_name, window_name=window_name, key="enter")
    if enter_error is not None:
        return enter_error
    accepted = _wait_for_tmux_prompt_accepted(
        runtime,
        session_name=session_name,
        window_name=window_name,
        cli=cli,
        prompt_text=prompt_text,
    )
    if not accepted.ready:
        return _format_ai_cli_ready_failure(accepted)
    return None


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
    ready_result = _wait_for_tmux_cli_ready(
        runtime,
        session_name=session_name,
        window_name=window_name,
        cli=launch_config.cli,
    )
    if ready_result is not None and not ready_result.ready:
        return _format_ai_cli_ready_failure(ready_result)
    goal_error = _maybe_submit_tmux_codex_goal(
        runtime,
        session_name=session_name,
        window_name=window_name,
        launch_config=launch_config,
        workflow=workflow,
        worktree=worktree,
        transport="tmux",
    )
    if goal_error is not None and goal_error != "codex_goal_ready_timeout":
        return goal_error
    if goal_error is None and launch_config.codex_goal_enable and launch_config.cli == "codex":
        ready_result = _wait_for_tmux_cli_ready(
            runtime,
            session_name=session_name,
            window_name=window_name,
            cli=launch_config.cli,
        )
        if ready_result is not None and not ready_result.ready:
            return _format_ai_cli_ready_failure(ready_result)
    prompt_text, resolution_error = _workflow_step_prompt_text(
        runtime,
        launch_config=launch_config,
        cli=launch_config.cli,
        step=workflow.steps[0],
        worktree=worktree,
    )
    if resolution_error is not None:
        return resolution_error
    submit_error = _submit_tmux_prompt_workflow_step(
        runtime,
        session_name=session_name,
        window_name=window_name,
        prompt_text=prompt_text,
        cli=launch_config.cli,
    )
    if submit_error is not None:
        return submit_error
    queued_steps = workflow.steps[1:]
    if queued_steps and launch_config.cli == "codex":
        queue_error_reason = _queue_tmux_codex_workflow_steps(
            runtime,
            session_name=session_name,
            window_name=window_name,
            worktree=worktree,
            workflow=workflow,
            queued_steps=queued_steps,
            launch_config=launch_config,
            cli=launch_config.cli,
            transport="tmux",
        )
        if queue_error_reason is not None:
            failure_context = _queue_failure_event_context(queue_error_reason)
            runtime._emit(
                "planning.agent_launch.workflow_queue_failed",
                session_name=session_name,
                window_name=window_name,
                worktree=worktree.name,
                cli=launch_config.cli,
                workflow_mode=workflow.mode,
                codex_cycles=workflow.codex_cycles,
                reason=queue_error_reason,
                transport="tmux",
                **failure_context,
            )
            runtime._emit(
                "planning.agent_launch.workflow_fallback",
                session_name=session_name,
                window_name=window_name,
                worktree=worktree.name,
                cli=launch_config.cli,
                workflow_mode=workflow.mode,
                codex_cycles=workflow.codex_cycles,
                reason=queue_error_reason,
                transport="tmux",
                **failure_context,
            )
            return None
    return None


def _queue_tmux_codex_workflow_steps(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    worktree: CreatedPlanWorktree,
    workflow: _PlanAgentWorkflow,
    queued_steps: tuple[_PlanAgentWorkflowStep, ...],
    launch_config: PlanAgentLaunchConfig,
    cli: str,
    transport: str = "tmux",
) -> str | None:
    for step_index, step in enumerate(queued_steps):
        queued_text, resolution_error = _workflow_step_prompt_text(
            runtime,
            launch_config=launch_config,
            cli=cli,
            step=step,
            worktree=worktree,
        )
        if resolution_error is not None:
            return _QueueFailure("queue_prompt_resolution_failed", step_index=step_index, step_kind=step.kind)
        send_error = _send_tmux_prompt(
            runtime,
            session_name=session_name,
            window_name=window_name,
            text=queued_text,
        )
        if send_error is not None:
            return _QueueFailure("queue_send_failed", step_index=step_index, step_kind=step.kind)
        if not _queue_tmux_codex_message(
            runtime,
            session_name=session_name,
            window_name=window_name,
            text=queued_text,
            require_text_match=False,
        ):
            return _QueueFailure("queue_not_ready", step_index=step_index, step_kind=step.kind)
    runtime._emit(
        "planning.agent_launch.workflow_queued",
        session_name=session_name,
        window_name=window_name,
        worktree=worktree.name,
        cli=cli,
        workflow_mode=workflow.mode,
        codex_cycles=workflow.codex_cycles,
        queued_steps=len(queued_steps),
        queued_steps_confirmed=len(queued_steps),
        transport=transport,
    )
    return None


def _queue_tmux_codex_message(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    text: str,
    require_text_match: bool = True,
) -> bool:
    deadline = time.monotonic() + _CODEX_QUEUE_READY_TIMEOUT_SECONDS
    tab_attempts = 0
    while time.monotonic() < deadline:
        screen = _read_tmux_screen(runtime, session_name=session_name, window_name=window_name)
        if tab_attempts > 0 and _codex_queue_screen_confirms_queued(
            screen,
            text,
            require_text_match=require_text_match,
        ):
            return True
        if _codex_queue_message_needs_tab(screen, text, require_text_match=require_text_match):
            if tab_attempts >= _CODEX_QUEUE_MAX_TAB_ATTEMPTS:
                return False
            tab_error = _send_tmux_key(
                runtime,
                session_name=session_name,
                window_name=window_name,
                key="tab",
                emit_failure_event=False,
            )
            if tab_error is not None:
                return False
            tab_attempts += 1
            time.sleep(_CODEX_QUEUE_READY_POLL_INTERVAL_SECONDS)
            continue
        time.sleep(_CODEX_QUEUE_READY_POLL_INTERVAL_SECONDS)
    return False


def _queue_failure_event_context(reason: str) -> dict[str, object]:
    context: dict[str, object] = {}
    step_index = getattr(reason, "step_index", None)
    if step_index is not None:
        context["queue_failed_step_index"] = step_index
    step_kind = getattr(reason, "step_kind", None)
    if step_kind:
        context["queue_failed_step_kind"] = step_kind
    return context


def attach_plan_agent_terminal(runtime: Any, attach_target: PlanAgentAttachTarget) -> int:
    if attach_target.attach_via == "switch-client":
        result = _run_tmux_probe(
            runtime,
            ("tmux", "switch-client", "-t", attach_target.session_name),
            cwd=attach_target.repo_root,
        )
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
        direct_prompt_enabled=launch_config.direct_prompt_enabled,
        browser_e2e_followup_enable=launch_config.browser_e2e_followup_enable,
        pr_review_comments_followup_enable=launch_config.pr_review_comments_followup_enable,
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
        direct_prompt_enabled=launch_config.direct_prompt_enabled,
        browser_e2e_followup_enable=launch_config.browser_e2e_followup_enable,
        pr_review_comments_followup_enable=launch_config.pr_review_comments_followup_enable,
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
    goal_error = _maybe_submit_surface_codex_goal(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        launch_config=launch_config,
        workflow=workflow,
        worktree=worktree,
    )
    if goal_error is not None and goal_error != "codex_goal_ready_timeout":
        return goal_error
    if goal_error is None and launch_config.codex_goal_enable and launch_config.cli == "codex":
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
        worktree=worktree,
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
            failure_context = _queue_failure_event_context(queue_error_reason)
            runtime._emit(
                "planning.agent_launch.workflow_queue_failed",
                workspace_id=workspace_id,
                surface_id=surface_id,
                worktree=worktree.name,
                cli=launch_config.cli,
                workflow_mode=workflow.mode,
                codex_cycles=workflow.codex_cycles,
                reason=queue_error_reason,
                transport="cmux",
                **failure_context,
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
                transport="cmux",
                **failure_context,
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


def _maybe_submit_surface_codex_goal(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    worktree: CreatedPlanWorktree,
) -> str | None:
    if launch_config.cli != "codex" or not launch_config.codex_goal_enable:
        return None
    goal_text = _codex_goal_text_for_worktree(
        worktree=worktree,
        preset=launch_config.preset,
        workflow_mode=workflow.mode,
        omx_workflow=launch_config.omx_workflow,
    )
    error = _submit_surface_codex_goal(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        goal_text=goal_text,
    )
    if error is None:
        _emit_codex_goal_event(
            runtime,
            "planning.agent_launch.codex_goal_submitted",
            workspace_id=workspace_id,
            surface_id=surface_id,
            cli=launch_config.cli,
            workflow=workflow,
            transport="cmux",
            worktree=worktree,
        )
        return None
    if error == "codex_goal_ready_timeout":
        _emit_codex_goal_event(
            runtime,
            "planning.agent_launch.codex_goal_fallback",
            workspace_id=workspace_id,
            surface_id=surface_id,
            cli=launch_config.cli,
            workflow=workflow,
            transport="cmux",
            worktree=worktree,
            reason=error,
        )
        return error
    return error


def _submit_surface_codex_goal(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    goal_text: str,
) -> str | None:
    submit_error = _submit_direct_prompt_workflow_step(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        prompt_text=f"/goal {goal_text}",
    )
    if submit_error is not None:
        return submit_error
    if not _wait_for_codex_queue_ready(runtime, workspace_id=workspace_id, surface_id=surface_id):
        return "codex_goal_ready_timeout"
    return None


def _workflow_step_prompt_text(
    runtime: Any,
    *,
    launch_config: PlanAgentLaunchConfig,
    cli: str,
    step: _PlanAgentWorkflowStep,
    worktree: CreatedPlanWorktree | None = None,
) -> tuple[str, str | None]:
    if step.kind not in {"submit_direct_prompt", "queue_direct_prompt"}:
        return _shape_queue_message_text(runtime, step.text, worktree=worktree), None
    return _resolve_preset_submission_text(
        runtime,
        launch_config=launch_config,
        cli=cli,
        preset=step.text,
        worktree=worktree,
    )


def _shape_queue_message_text(runtime: Any, text: str, *, worktree: CreatedPlanWorktree | None = None) -> str:
    if str(text).strip() != _browser_e2e_instruction_text().strip():
        return text
    sections = [
        section
        for section in (
            _original_task_source_prompt_section(runtime, worktree=worktree),
            _runtime_addresses_prompt_section(runtime, worktree=worktree),
        )
        if section
    ]
    if not sections:
        return text
    return f"{str(text).rstrip()}\n\n" + "\n\n".join(sections) + "\n"


def _original_task_source_prompt_section(
    runtime: Any,
    *,
    worktree: CreatedPlanWorktree | None,
) -> str:
    if worktree is None:
        return ""
    plan_path = _original_plan_file_path(runtime, str(worktree.plan_file or ""))
    main_task_path = Path(worktree.root) / "MAIN_TASK.md"
    lines = [
        "## Original task source for E2E validation",
        "MAIN_TASK.md may be rewritten by cycle prompts. Use this original plan file before the current "
        "MAIN_TASK.md when validating the end-to-end requirement.",
    ]
    if plan_path is not None:
        lines.append(f'- Original plan file: "{plan_path}"')
    lines.append(f'- Seeded worktree task file: "{main_task_path}"')
    return "\n".join(lines)


def _original_plan_file_path(runtime: Any, plan_file: str) -> Path | None:
    normalized = str(plan_file or "").strip()
    if not normalized:
        return None
    raw_path = Path(normalized).expanduser()
    if raw_path.is_absolute():
        return raw_path
    planning_dir = Path(getattr(getattr(runtime, "config", None), "planning_dir", "todo/plans"))
    return (planning_dir / raw_path).resolve()


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
        if any(token != "/ulw-loop" for token in slash_command_tokens):
            return "", "prompt_resolution_failed: multiple_slash_commands_not_allowed"
        if not stripped.startswith("/ulw-loop"):
            shaped = f"/ulw-loop {stripped}" if stripped else "/ulw-loop"
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
    worktree: CreatedPlanWorktree | None = None,
) -> tuple[str, str | None]:
    normalized_cli = str(cli).strip().lower()
    direct_prompt = _uses_direct_submission(
        cli=normalized_cli,
        direct_prompt_enabled=launch_config.direct_prompt_enabled,
    )
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
    if direct_prompt:
        resolved = _append_runtime_addresses_for_preset(
            runtime,
            preset=preset,
            prompt_text=resolved,
            worktree=worktree,
        )
    return _shape_prompt_text(
        resolved,
        direct_prompt=direct_prompt,
        ulw_loop_prefix=launch_config.ulw_loop_prefix,
        ulw_suffix=launch_config.ulw_suffix,
    )


def _append_runtime_addresses_for_preset(
    runtime: Any,
    *,
    preset: str,
    prompt_text: str,
    worktree: CreatedPlanWorktree | None = None,
) -> str:
    if str(preset).strip() != "implement_task":
        return prompt_text
    context = _runtime_addresses_prompt_section(runtime, worktree=worktree)
    if not context:
        return prompt_text
    return f"{prompt_text.rstrip()}\n\n{context}\n"


def _runtime_addresses_prompt_section(runtime: Any, *, worktree: CreatedPlanWorktree | None = None) -> str:
    state = _latest_runtime_state(runtime)
    if state is None:
        return ""
    lines = [
        "## Current envctl runtime addresses",
        "Use these currently known localhost addresses when validating or debugging. "
        "They are generated from saved envctl runtime state; verify them again if you restart services.",
    ]
    dependency_lines = _dependency_address_lines(state, worktree=worktree)
    service_lines = _service_address_lines(state, worktree=worktree)
    if dependency_lines:
        lines.append("Dependencies:")
        lines.extend(f"- {line}" for line in dependency_lines)
    if service_lines:
        lines.append("Backend/frontend:")
        lines.extend(f"- {line}" for line in service_lines)
    if len(lines) == 2:
        return ""
    return "\n".join(lines)


def _latest_runtime_state(runtime: Any) -> RunState | None:
    state_repository = getattr(runtime, "state_repository", None)
    if state_repository is not None and hasattr(state_repository, "load_latest"):
        try:
            state = state_repository.load_latest()
        except Exception:
            state = None
        if isinstance(state, RunState):
            return state
    try_loader = getattr(runtime, "_try_load_existing_state", None)
    if callable(try_loader):
        for mode in ("trees", "main"):
            try:
                state = try_loader(mode=mode, strict_mode_match=True)
            except Exception:
                state = None
            if isinstance(state, RunState):
                return state
    return None


def _dependency_address_lines(state: RunState, *, worktree: CreatedPlanWorktree | None = None) -> list[str]:
    rows: list[str] = []
    seen: set[tuple[str, int]] = set()
    for project_name, requirements in state.requirements.items():
        if not _state_project_matches_worktree(project_name, worktree):
            continue
        for dependency_id in ("postgres", "redis", "supabase", "n8n"):
            component = requirements.component(dependency_id)
            if not bool(component.get("enabled", False)):
                continue
            port = _component_port(component)
            if port is None:
                continue
            key = (dependency_id, port)
            if key in seen:
                continue
            seen.add(key)
            address = _dependency_address(dependency_id, port)
            rows.append(f"{_dependency_label(dependency_id)} ({project_name}): {address}")
    return rows


def _service_address_lines(state: RunState, *, worktree: CreatedPlanWorktree | None = None) -> list[str]:
    rows: list[str] = []
    for service in state.services.values():
        if not _state_service_matches_worktree(service, worktree):
            continue
        service_type = str(service.type or "").strip().lower()
        if service_type not in {"backend", "frontend"}:
            continue
        port = service.actual_port or service.requested_port
        if port is None:
            continue
        label = "Backend" if service_type == "backend" else "Frontend"
        rows.append(f"{label} ({service.name}): http://localhost:{int(port)}")
    return rows


def _state_project_matches_worktree(project_name: object, worktree: CreatedPlanWorktree | None) -> bool:
    if worktree is None:
        return True
    normalized_project = str(project_name or "").strip().casefold()
    normalized_worktree = str(worktree.name or "").strip().casefold()
    if normalized_project == normalized_worktree:
        return True
    return bool(normalized_project and normalized_worktree.startswith(f"{normalized_project}-"))


def _state_service_matches_worktree(service: object, worktree: CreatedPlanWorktree | None) -> bool:
    if worktree is None:
        return True
    service_name = str(getattr(service, "name", "") or "").strip()
    worktree_name = str(worktree.name or "").strip()
    if worktree_name and service_name.casefold().startswith(f"{worktree_name.casefold()} "):
        return True
    cwd_raw = str(getattr(service, "cwd", "") or "").strip()
    if not cwd_raw:
        return False
    try:
        cwd = Path(cwd_raw).expanduser().resolve(strict=False)
        root = Path(worktree.root).expanduser().resolve(strict=False)
    except OSError:
        return False
    return cwd == root or root in cwd.parents


def _component_port(component: Mapping[str, object]) -> int | None:
    for key in ("final", "actual", "requested"):
        port = _int_or_none(component.get(key))
        if port is not None and port > 0:
            return port
    resources = component.get("resources")
    if isinstance(resources, Mapping):
        port = _int_or_none(resources.get("primary"))
        if port is not None and port > 0:
            return port
    return None


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _dependency_label(dependency_id: str) -> str:
    return {"postgres": "Postgres", "redis": "Redis", "supabase": "Supabase", "n8n": "n8n"}.get(
        dependency_id,
        dependency_id,
    )


def _dependency_address(dependency_id: str, port: int) -> str:
    if dependency_id == "redis":
        return f"redis://localhost:{port}"
    if dependency_id in {"supabase", "n8n"}:
        return f"http://localhost:{port}"
    return f"localhost:{port}"


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
    for step_index, step in enumerate(queued_steps):
        queued_text, resolution_error = _workflow_step_prompt_text(
            runtime,
            launch_config=launch_config,
            cli=cli,
            step=step,
            worktree=worktree,
        )
        if resolution_error is not None:
            return _QueueFailure("queue_prompt_resolution_failed", step_index=step_index, step_kind=step.kind)
        send_error = _paste_surface_text(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            text=queued_text,
            emit_failure_event=False,
        )
        if send_error is not None:
            return _QueueFailure("queue_send_failed", step_index=step_index, step_kind=step.kind)
        if not _queue_codex_message(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            text=queued_text,
            require_text_match=False,
        ):
            return _QueueFailure("queue_not_ready", step_index=step_index, step_kind=step.kind)
    runtime._emit(
        "planning.agent_launch.workflow_queued",
        workspace_id=workspace_id,
        surface_id=surface_id,
        worktree=worktree.name,
        cli=cli,
        workflow_mode=workflow.mode,
        codex_cycles=workflow.codex_cycles,
        queued_steps=len(queued_steps),
        queued_steps_confirmed=len(queued_steps),
        transport="cmux",
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
    tab_attempts = 0
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
        if tab_attempts > 0 and _codex_queue_screen_confirms_queued(
            screen,
            text,
            require_text_match=require_text_match,
        ):
            return True
        if _codex_queue_message_needs_tab(screen, text, require_text_match=require_text_match):
            if tab_attempts >= _CODEX_QUEUE_MAX_TAB_ATTEMPTS:
                return False
            tab_error = _send_surface_key(
                runtime,
                workspace_id=workspace_id,
                surface_id=surface_id,
                key="tab",
                emit_failure_event=False,
            )
            if tab_error is not None:
                return False
            tab_attempts += 1
            time.sleep(_CODEX_QUEUE_READY_POLL_INTERVAL_SECONDS)
            continue
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
    first_visible_line = next((line.strip() for line in str(text).splitlines() if line.strip()), "")
    if not require_text_match:
        return "pasted content" in normalized_screen or (
            bool(first_visible_line) and _normalized_screen_text(first_visible_line) in normalized_screen
        )
    if not first_visible_line:
        return False
    return _normalized_screen_text(first_visible_line) in normalized_screen


def _codex_queue_screen_confirms_queued(screen: str, text: str, *, require_text_match: bool = True) -> bool:
    normalized_screen = _normalized_screen_text(screen)
    if not normalized_screen:
        return False
    if any(marker in normalized_screen for marker in _CODEX_QUEUE_CONFIRMED_MARKERS):
        return True
    if _CODEX_QUEUE_READY_HINT in normalized_screen:
        return False
    if _codex_queue_text_is_visible(screen, text, require_text_match=require_text_match):
        return False
    return True


def _codex_queue_text_is_visible(screen: str, text: str, *, require_text_match: bool = True) -> bool:
    normalized_screen = _normalized_screen_text(screen)
    if not normalized_screen:
        return False
    normalized_text = _normalized_screen_text(text)
    if normalized_text and normalized_text in normalized_screen:
        return True
    first_visible_line = next((line.strip() for line in str(text).splitlines() if line.strip()), "")
    if not first_visible_line:
        return False
    if not require_text_match and "pasted content" in normalized_screen:
        return True
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
    active_matches = _plan_matches_for_feature(repo_root / _PLANNING_ROOT, feature_name=normalized_feature)
    if len(active_matches) == 1:
        return active_matches[0]
    if active_matches:
        return None
    archived_matches = _plan_matches_for_feature(repo_root / _DONE_PLANNING_ROOT, feature_name=normalized_feature)
    if len(archived_matches) == 1:
        return archived_matches[0]
    return None


def _plan_matches_for_feature(planning_root: Path, *, feature_name: str) -> list[Path]:
    if not planning_root.is_dir():
        return []
    matches: list[Path] = []
    for candidate in sorted(planning_root.glob("*/*.md")):
        if candidate.name == "README.md":
            continue
        relative = candidate.relative_to(planning_root)
        if planning_feature_name(str(relative).replace("\\", "/")) != feature_name:
            continue
        matches.append(candidate.resolve())
    return matches


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


def resolve_plan_agent_launch_command(
    *,
    project_name: str,
    project_root: Path,
    repo_root: Path,
    envctl_executable: str = "envctl",
) -> str | None:
    plan_path = _review_original_plan_path(project_name, project_root, repo_root=repo_root)
    selector = (
        _active_plan_selector_for_path(repo_root=repo_root, plan_path=plan_path)
        if plan_path is not None
        else None
    )
    if not selector:
        selector = f"{_feature_name_from_project_name(project_name)}.md"
    return " ".join(
        (
            shlex.quote(envctl_executable),
            "--repo",
            shlex.quote(str(repo_root)),
            "--plan",
            shlex.quote(selector),
            "--tmux",
            "--opencode",
            "--headless",
            "--tmux-new-session",
        )
    )


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
    starter_surface_id, probe_result, surface_count = _starter_surface_for_new_workspace(
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
    if launch_config.transport == "omx":
        required = ["omx", "tmux", "script", "codex"]
    else:
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


def _tmux_active_pane_id(runtime: Any, session_name: str) -> str:
    result = _run_tmux_probe(
        runtime,
        ("tmux", "display-message", "-p", "-t", session_name, "#{pane_id}"),
        cwd=Path(runtime.config.base_dir).resolve(),
    )
    if result.returncode != 0:
        return ""
    return str(getattr(result, "stdout", "")).strip()


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
        error = _omx_spawn_failure_text(returncode=getattr(process, "returncode", None), stdout=stdout, stderr=stderr)
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


def _post_submit_screen_looks_accepted(cli: str, screen: str, prompt_text: str) -> bool:
    normalized_cli = str(cli).strip().lower()
    if normalized_cli != "opencode":
        return True
    cleaned = _strip_ansi_sequences(screen)
    lower_text = cleaned.lower()
    if "no matching items" in lower_text or "unrecognized command" in lower_text:
        return False
    if "ask anything" in lower_text and "/status" in lower_text:
        return True
    if _screen_looks_active(normalized_cli, screen):
        return True
    prompt_lines = [line.strip().lower() for line in str(prompt_text).splitlines() if line.strip()]
    if prompt_lines and all(line in lower_text for line in prompt_lines):
        return False
    return False


def _screen_looks_active(cli: str, screen: str) -> bool:
    normalized_cli = str(cli).strip().lower()
    cleaned = _strip_ansi_sequences(screen)
    lower_text = cleaned.lower()
    if normalized_cli in {"opencode", "codex"}:
        return "esc to interrupt" in lower_text and ("working" in lower_text or "ctrl+c" in lower_text)
    return False


def _wait_for_tmux_prompt_accepted(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    cli: str,
    prompt_text: str,
) -> AiCliReadyResult:
    normalized_cli = str(cli).strip().lower()
    if normalized_cli != "opencode":
        return AiCliReadyResult(ready=True, reason="post_submit_check_not_required")
    deadline = time.monotonic() + _PROMPT_SUBMIT_READY_TIMEOUT_SECONDS
    last_screen = ""
    while time.monotonic() < deadline:
        last_screen = _read_tmux_screen(runtime, session_name=session_name, window_name=window_name)
        if _post_submit_screen_looks_accepted(normalized_cli, last_screen, prompt_text):
            return AiCliReadyResult(ready=True, reason="prompt_accepted", screen_excerpt=_screen_excerpt(last_screen))
        time.sleep(_PROMPT_SUBMIT_READY_POLL_INTERVAL_SECONDS)
    return AiCliReadyResult(
        ready=False,
        reason="opencode_prompt_accept_timeout",
        screen_excerpt=_screen_excerpt(last_screen),
    )


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
    lower_text = _screen_tail_text(cleaned).lower()
    if any(marker in lower_text for marker in _AI_CLI_SHELL_FAILURE_MARKERS):
        return False
    if any(marker in lower_text for marker in _OPENCODE_LOADING_MARKERS):
        return False
    if all(marker in lower_text for marker in _OPENCODE_READY_MARKERS):
        return True
    return False


def _strip_ansi_sequences(raw: str) -> str:
    return _ANSI_ESCAPE_RE.sub("", str(raw or "")).replace("\r", "")


def _screen_tail_text(cleaned: str, *, line_count: int = 12) -> str:
    lines = [line.rstrip() for line in str(cleaned or "").splitlines() if line.strip()]
    return "\n".join(lines[-line_count:])


def _screen_excerpt(raw: str, *, limit: int = 600) -> str:
    cleaned = _strip_ansi_sequences(raw).strip()
    if not cleaned:
        return ""
    lines = [line.rstrip() for line in cleaned.splitlines() if line.strip()]
    excerpt = scrub_sensitive_text("\n".join(lines[-8:]).strip())
    if len(excerpt) <= limit:
        return excerpt
    return excerpt[-limit:]


def _format_ai_cli_ready_failure(result: AiCliReadyResult) -> str:
    reason = str(result.reason or "ai_cli_ready_timeout").strip() or "ai_cli_ready_timeout"
    excerpt = str(result.screen_excerpt or "").strip()
    if excerpt:
        return f"{reason}: {excerpt}"
    return reason


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
