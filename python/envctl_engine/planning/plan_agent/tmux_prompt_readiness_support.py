from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from envctl_engine.planning.plan_agent.constants import (
    _CLI_READY_POLL_INTERVAL_SECONDS,
    _PROMPT_SUBMIT_READY_POLL_INTERVAL_SECONDS,
    _PROMPT_SUBMIT_READY_TIMEOUT_SECONDS,
)
from envctl_engine.planning.plan_agent.models import AiCliReadyResult
from envctl_engine.planning.plan_agent.terminal_screen import (
    _post_submit_screen_looks_accepted,
    _screen_excerpt,
    _screen_looks_ready,
)


ReadTmuxScreenFn = Callable[..., str]


def wait_for_tmux_cli_ready(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    cli: str,
    timeout_seconds: float,
    read_tmux_screen_fn: ReadTmuxScreenFn,
) -> AiCliReadyResult:
    normalized_cli = str(cli).strip().lower()
    if normalized_cli not in {"codex", "opencode"}:
        time.sleep(timeout_seconds)
        return AiCliReadyResult(ready=True, reason="unsupported_cli_assumed_ready")
    deadline = time.monotonic() + timeout_seconds
    last_screen = ""
    while time.monotonic() < deadline:
        last_screen = read_tmux_screen_fn(runtime, session_name=session_name, window_name=window_name)
        if _screen_looks_ready(normalized_cli, last_screen):
            return AiCliReadyResult(ready=True, reason="ready", screen_excerpt=_screen_excerpt(last_screen))
        time.sleep(_CLI_READY_POLL_INTERVAL_SECONDS)
    return AiCliReadyResult(
        ready=False,
        reason=f"{normalized_cli}_ready_timeout",
        screen_excerpt=_screen_excerpt(last_screen),
    )


def wait_for_tmux_prompt_ready_after_goal(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    read_tmux_screen_fn: ReadTmuxScreenFn,
) -> bool:
    deadline = time.monotonic() + _PROMPT_SUBMIT_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        screen = read_tmux_screen_fn(runtime, session_name=session_name, window_name=window_name)
        if _screen_looks_ready("codex", screen):
            return True
        time.sleep(_PROMPT_SUBMIT_READY_POLL_INTERVAL_SECONDS)
    return False


def wait_for_tmux_prompt_accepted(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    cli: str,
    prompt_text: str,
    read_tmux_screen_fn: ReadTmuxScreenFn,
) -> AiCliReadyResult:
    normalized_cli = str(cli).strip().lower()
    if normalized_cli != "opencode":
        return AiCliReadyResult(ready=True, reason="post_submit_check_not_required")
    deadline = time.monotonic() + _PROMPT_SUBMIT_READY_TIMEOUT_SECONDS
    last_screen = ""
    while time.monotonic() < deadline:
        last_screen = read_tmux_screen_fn(runtime, session_name=session_name, window_name=window_name)
        if _post_submit_screen_looks_accepted(normalized_cli, last_screen, prompt_text):
            return AiCliReadyResult(ready=True, reason="prompt_accepted", screen_excerpt=_screen_excerpt(last_screen))
        time.sleep(_PROMPT_SUBMIT_READY_POLL_INTERVAL_SECONDS)
    return AiCliReadyResult(
        ready=False,
        reason="opencode_prompt_accept_timeout",
        screen_excerpt=_screen_excerpt(last_screen),
    )
