from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from envctl_engine.runtime.codex_tmux_support import _run_probe as _run_tmux_probe

from envctl_engine.planning.plan_agent.models import PlanAgentAttachTarget


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


def _tmux_display_message_succeeds(runtime: Any, session_name: str) -> tuple[bool, str]:
    result = _run_tmux_probe(
        runtime,
        ("tmux", "display-message", "-p", "-t", session_name, "#{pane_id}"),
        cwd=Path(runtime.config.base_dir).resolve(),
    )
    if result.returncode != 0:
        return False, ""
    return True, str(getattr(result, "stdout", "")).strip()


def _tmux_active_pane_id(runtime: Any, session_name: str) -> str:
    result = _run_tmux_probe(
        runtime,
        ("tmux", "display-message", "-p", "-t", session_name, "#{pane_id}"),
        cwd=Path(runtime.config.base_dir).resolve(),
    )
    if result.returncode != 0:
        return ""
    return str(getattr(result, "stdout", "")).strip()


__all__ = tuple(name for name in globals() if not name.startswith("__"))
