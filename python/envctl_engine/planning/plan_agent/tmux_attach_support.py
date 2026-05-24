from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from envctl_engine.planning.plan_agent.models import (
    AiCliReadyResult,
    CreatedPlanWorktree,
    PlanAgentAttachTarget,
    PlanAgentLaunchOutcome,
)

FindExistingAttachTargetFn = Callable[..., PlanAgentAttachTarget | None]
GuidanceAttachCommandFn = Callable[[str], tuple[str, ...]]
TmuxSessionExistsFn = Callable[[Any, str], bool]
TmuxWindowExistsFn = Callable[..., bool]
RunTmuxProbeFn = Callable[..., object]
ExistingSessionHealthFn = Callable[..., AiCliReadyResult]
FormatReadyFailureFn = Callable[[AiCliReadyResult], str]
SessionNameForWorktreeFn = Callable[..., str]
WindowNameForWorktreeFn = Callable[[CreatedPlanWorktree], str]


def resolve_tmux_attach_target(
    *,
    runtime: Any,
    repo_root: Path,
    session_name: str,
    window_name: str | None,
    attach_via: str,
    created_worktrees: tuple[CreatedPlanWorktree, ...],
    cli: str,
    find_existing_attach_target_fn: FindExistingAttachTargetFn,
    tmux_session_exists_fn: TmuxSessionExistsFn,
    tmux_window_exists_fn: TmuxWindowExistsFn,
    guidance_attach_command_fn: GuidanceAttachCommandFn,
) -> PlanAgentAttachTarget | None:
    existing_attach_target = find_existing_attach_target_fn(
        runtime,
        repo_root=repo_root,
        created_worktrees=created_worktrees,
        cli=cli,
    )
    if existing_attach_target is not None:
        return existing_attach_target
    if not tmux_session_exists_fn(runtime, session_name):
        return None
    if window_name and not tmux_window_exists_fn(runtime, session_name=session_name, window_name=window_name):
        return None
    return PlanAgentAttachTarget(
        repo_root=repo_root,
        session_name=session_name,
        window_name=window_name or "",
        attach_via=attach_via,
        attach_command=guidance_attach_command_fn(session_name),
    )


def find_existing_tmux_attach_target(
    *,
    runtime: Any,
    repo_root: Path,
    created_worktrees: tuple[CreatedPlanWorktree, ...],
    cli: str,
    session_name_for_worktree_fn: SessionNameForWorktreeFn,
    window_name_for_worktree_fn: WindowNameForWorktreeFn,
    tmux_session_exists_fn: TmuxSessionExistsFn,
    run_tmux_probe_fn: RunTmuxProbeFn,
    existing_session_health_fn: ExistingSessionHealthFn,
    format_ai_cli_ready_failure_fn: FormatReadyFailureFn,
    guidance_attach_command_fn: GuidanceAttachCommandFn,
) -> PlanAgentAttachTarget | None:
    separator = "|||ENVCTL_TMUX_PATH|||"
    targets = [Path(worktree.root).expanduser().resolve(strict=False) for worktree in created_worktrees]
    attach_by_root = {
        Path(worktree.root).expanduser().resolve(strict=False): PlanAgentAttachTarget(
            repo_root=repo_root,
            session_name=session_name_for_worktree_fn(repo_root, worktree, cli=cli),
            window_name=window_name_for_worktree_fn(worktree),
            attach_via="attach-session",
            attach_command=guidance_attach_command_fn(session_name_for_worktree_fn(repo_root, worktree, cli=cli)),
        )
        for worktree in created_worktrees
    }
    if not targets:
        return None
    for target in targets:
        attach_target = attach_by_root[target]
        session_name = attach_target.session_name
        if not tmux_session_exists_fn(runtime, session_name):
            continue
        windows_result = run_tmux_probe_fn(
            runtime,
            ("tmux", "list-windows", "-t", session_name, "-F", f"#{{window_name}}{separator}#{{pane_current_path}}"),
            cwd=Path(runtime.config.base_dir).resolve(),
        )
        if getattr(windows_result, "returncode", 1) != 0:
            continue
        for raw_line in str(getattr(windows_result, "stdout", "")).splitlines():
            window, _, raw_path = raw_line.partition(separator)
            window_name = window.strip()
            normalized_path = raw_path.strip()
            if not window_name or not normalized_path:
                continue
            candidate = Path(normalized_path).expanduser().resolve(strict=False)
            if candidate == target or target in candidate.parents:
                health = existing_session_health_fn(
                    runtime,
                    session_name=session_name,
                    window_name=window_name,
                    cli=cli,
                )
                if not health.ready:
                    _record_unhealthy_existing_tmux_session(
                        runtime,
                        cli=cli,
                        created_worktrees=created_worktrees,
                        target=target,
                        session_name=session_name,
                        window_name=window_name,
                        health=health,
                        format_ai_cli_ready_failure_fn=format_ai_cli_ready_failure_fn,
                    )
                    continue
                return PlanAgentAttachTarget(
                    repo_root=repo_root,
                    session_name=session_name,
                    window_name=window_name,
                    attach_via="attach-session",
                    attach_command=guidance_attach_command_fn(session_name),
                )
    return None


def _record_unhealthy_existing_tmux_session(
    runtime: Any,
    *,
    cli: str,
    created_worktrees: tuple[CreatedPlanWorktree, ...],
    target: Path,
    session_name: str,
    window_name: str,
    health: AiCliReadyResult,
    format_ai_cli_ready_failure_fn: FormatReadyFailureFn,
) -> None:
    reason = f"existing_{str(cli).strip().lower() or 'ai'}_session_unhealthy"
    detail = format_ai_cli_ready_failure_fn(
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


__all__ = tuple(name for name in globals() if not name.startswith("__"))
