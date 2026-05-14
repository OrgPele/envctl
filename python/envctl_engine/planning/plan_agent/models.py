from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


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


__all__ = tuple(name for name in globals() if not name.startswith("__"))
