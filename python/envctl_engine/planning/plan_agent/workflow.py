from __future__ import annotations

# ruff: noqa: F401
from typing import Any

from envctl_engine.planning.plan_agent.constants import (
    _AI_CLI_SHELL_FAILURE_MARKERS,
    _ANSI_ESCAPE_RE,
    _BROWSER_E2E_FOLLOWUP_TEMPLATE,
    _CLI_READY_DELAY_SECONDS_BY_CLI,
    _CLI_READY_POLL_INTERVAL_SECONDS,
    _CODEX_BYPASS_FLAGS,
    _CODEX_LOADING_MARKERS,
    _CODEX_QUEUE_CONFIRMED_MARKERS,
    _CODEX_QUEUE_MAX_TAB_ATTEMPTS,
    _CODEX_QUEUE_READY_HINT,
    _CODEX_QUEUE_READY_POLL_INTERVAL_SECONDS,
    _CODEX_QUEUE_READY_TIMEOUT_SECONDS,
    _CODEX_READY_MARKERS,
    _CODEX_READY_PROMPT_RE,
    _DEFAULT_CLI_READY_DELAY_SECONDS,
    _DEFAULT_PRESET,
    _DEFAULT_SHELL,
    _DONE_PLANNING_ROOT,
    _FINALIZATION_INSTRUCTION_TEMPLATE,
    _FIRST_CYCLE_COMPLETION_TEMPLATE,
    _INTERMEDIATE_CYCLE_COMPLETION_TEMPLATE,
    _LOW_SIGNAL_TAB_TITLE_WORDS,
    _OMX_SESSION_READY_POLL_INTERVAL_SECONDS,
    _OMX_SESSION_READY_TIMEOUT_SECONDS,
    _OMX_SESSION_STATE_RELATIVE_PATH,
    _OMX_SPAWN_OUTPUT_EXCERPT_CHARS,
    _OMX_TMUX_EXTENDED_KEYS_RELATIVE_PATH,
    _OMX_TMUX_LOCK_STALE_SECONDS,
    _OMX_WORKFLOW_KEYWORDS,
    _OPENCODE_LOADING_MARKERS,
    _OPENCODE_READY_MARKERS,
    _OPENCODE_READY_PROMPT_RE,
    _PLAN_AGENT_CODEX_CYCLE_CAP,
    _PLAN_AGENT_TAB_TITLE_MAX_LEN,
    _PLAN_AGENT_WORKFLOW_CODEX_CYCLES,
    _PLAN_AGENT_WORKFLOW_SINGLE_PROMPT,
    _PLANNING_ROOT,
    _PR_REVIEW_COMMENTS_FOLLOWUP_TEMPLATE,
    _PROMPT_PRE_SUBMIT_DELAY_SECONDS,
    _PROMPT_SHAPING_COMMAND_TOKEN_RE,
    _PROMPT_SUBMIT_READY_DELAY_SECONDS,
    _PROMPT_SUBMIT_READY_POLL_INTERVAL_SECONDS,
    _PROMPT_SUBMIT_READY_TIMEOUT_SECONDS,
    _PROMPT_TEMPLATE_PACKAGE,
    _READ_SCREEN_LINE_COUNT,
    _REVIEW_WORKTREE_PRESET,
    _SUPPORTED_PLAN_AGENT_CLIS,
    _SURFACE_READY_DELAY_SECONDS,
    _TMUX_WINDOW_READY_POLL_INTERVAL_SECONDS,
    _TMUX_WINDOW_READY_TIMEOUT_SECONDS,
    _WORKTREE_PROVENANCE_PATH,
)
from envctl_engine.planning.plan_agent.config import (
    PlanAgentLaunchPolicy,
    _cli_ready_delay_seconds,
    _cmux_transport_explicitly_requested,
    _codex_tui_queue_workflow_supported,
    _command_executable,
    _default_plan_agent_cli_command,
    _default_plan_agent_surface_transport,
    _guidance_attach_command,
    _launch_policy,
    _missing_launch_commands,
    _parse_codex_cycles,
    _resolve_available_plan_agent_surface_transport,
    _route_requests_ulw,
    _ulw_route_supported,
    _uses_direct_submission,
    _workflow_mode_for_launch_config,
    cli_ready_delay_seconds,
    codex_tui_queue_workflow_supported,
    command_executable,
    default_plan_agent_cli_command,
    default_plan_agent_surface_transport,
    guidance_attach_command,
    missing_launch_commands,
    normalize_plan_agent_surface_transport,
    parse_codex_cycles,
    plan_agent_launch_prereq_commands,
    resolve_plan_agent_launch_config,
    uses_direct_submission,
    workflow_mode_for_launch_config,
)
from envctl_engine.planning.plan_agent.models import (
    AgentTerminalLaunchResult,
    AiCliReadyResult,
    CreatedPlanWorktree,
    PlanAgentAttachTarget,
    PlanAgentAttachValidation,
    PlanAgentLaunchConfig,
    PlanAgentLaunchOutcome,
    PlanAgentLaunchResult,
    PlanSelectionResult,
    PlanWorktreeSyncResult,
    ReviewAgentLaunchReadiness,
    _OmxSessionRecord,
    _OmxSpawnProcessRecord,
    _PlanAgentWorkflow,
    _PlanAgentWorkflowStep,
    _QueueFailure,
    _WorkspaceLaunchTarget,
)
from envctl_engine.planning.plan_agent.terminal_screen import (
    _CODEX_GOAL_ACTIVE_MARKERS,
    _codex_goal_screen_looks_active,
    _codex_queue_message_needs_tab,
    _codex_queue_screen_confirms_queued,
    _codex_queue_screen_looks_ready,
    _codex_queue_text_is_visible,
    _format_ai_cli_ready_failure,
    _normalized_screen_text,
    _post_submit_screen_looks_accepted,
    _prompt_picker_screen_looks_ready,
    _prompt_submit_screen_looks_ready,
    _screen_excerpt,
    _screen_looks_active,
    _screen_looks_ready,
    _screen_tail_text,
    _strip_ansi_sequences,
)
from envctl_engine.planning.plan_agent.workflow_build import (
    PlanAgentWorkflowBuilder,
    _browser_e2e_instruction_text,
    _build_plan_agent_workflow,
    _finalization_instruction_text,
    _first_cycle_completion_instruction_text,
    _intermediate_cycle_completion_instruction_text,
    _load_plan_agent_followup_prompt,
    _pr_review_comments_instruction_text,
    _slash_command,
    _tab_title_for_worktree,
)
from envctl_engine.planning.plan_agent.workflow_prompt_support import (
    _append_runtime_addresses_for_preset,
    _component_port,
    _dependency_address,
    _dependency_address_lines,
    _dependency_label,
    _int_or_none,
    _latest_runtime_state,
    _original_plan_file_path,
    _original_task_source_prompt_section,
    _resolve_preset_submission_text,
    _runtime_addresses_prompt_section,
    _service_address_lines,
    _shape_prompt_text,
    _shape_queue_message_text,
    _state_project_matches_worktree,
    _state_service_matches_worktree,
    _workflow_step_prompt_text,
    optional_state_repository,
    resolve_codex_direct_prompt_body,
    resolve_opencode_direct_prompt_body,
)
from envctl_engine.planning.plan_agent.workflow_review_support import (
    _active_plan_selector_for_path,
    _cli_display_path,
    _feature_name_from_project_name,
    _infer_plan_file_from_feature,
    _plan_matches_for_feature,
    _recorded_plan_file_from_worktree,
    _resolve_recorded_plan_file,
    _review_original_plan_path,
    _review_prompt_arguments,
    resolve_plan_agent_launch_command,
)
import envctl_engine.runtime.runtime_context as runtime_context


def _surface_respawn_command(launch_config: PlanAgentLaunchConfig, worktree: CreatedPlanWorktree) -> str:
    _ = worktree
    return launch_config.shell


def _wrap_omx_initial_prompt_for_workflow(text: str, *, workflow: str) -> str:
    normalized_workflow = str(workflow or "").strip().lower()
    if normalized_workflow not in _OMX_WORKFLOW_KEYWORDS:
        return text
    stripped = str(text).lstrip()
    prefix = f"${normalized_workflow}"
    if stripped == prefix or stripped.startswith(f"{prefix} ") or stripped.startswith(f"{prefix}\n"):
        return text
    return f"{prefix}\n\n{text}"


def _codex_goal_text_for_worktree(
    *,
    worktree: CreatedPlanWorktree,
    preset: str,
    workflow_mode: str,
    omx_workflow: str,
) -> str:
    _ = (worktree, preset, workflow_mode)
    lines = [
        "Implement MAIN_TASK.md end-to-end in this worktree.",
        "Read it first, update code/tests, run focused validation, then ship with `envctl ship -m \"<message>\"`.",
    ]
    normalized_omx = str(omx_workflow or "").strip().lower()
    if normalized_omx:
        lines.append(f"Keep ${normalized_omx} completion contract active.")
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


__all__ = tuple(name for name in globals() if not name.startswith("__"))
