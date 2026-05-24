from __future__ import annotations

from typing import Any, Callable

from envctl_engine.planning.plan_agent.models import AiCliReadyResult


def existing_tmux_session_looks_healthy(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    cli: str,
    existing_session_health_fn: Callable[..., AiCliReadyResult],
) -> bool:
    return existing_session_health_fn(
        runtime,
        session_name=session_name,
        window_name=window_name,
        cli=cli,
    ).ready


def existing_tmux_session_health(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    cli: str,
    read_tmux_screen_fn: Callable[..., str],
    screen_looks_ready_fn: Callable[[str, str], bool],
    screen_looks_active_fn: Callable[[str, str], bool],
    screen_excerpt_fn: Callable[[str], str],
) -> AiCliReadyResult:
    normalized_cli = str(cli).strip().lower()
    if normalized_cli not in {"opencode", "codex"}:
        return AiCliReadyResult(ready=True, reason="health_check_not_required")
    screen = read_tmux_screen_fn(runtime, session_name=session_name, window_name=window_name)
    if not str(screen or "").strip():
        return AiCliReadyResult(ready=False, reason=f"existing_{normalized_cli}_session_empty", screen_excerpt="")
    if screen_looks_ready_fn(normalized_cli, screen) or screen_looks_active_fn(normalized_cli, screen):
        return AiCliReadyResult(ready=True, reason="healthy", screen_excerpt=screen_excerpt_fn(screen))
    return AiCliReadyResult(
        ready=False,
        reason=f"existing_{normalized_cli}_session_unhealthy",
        screen_excerpt=screen_excerpt_fn(screen),
    )
