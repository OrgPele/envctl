from __future__ import annotations

from collections.abc import Callable
from typing import Any

from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.ensure_worktree_support import run_ensure_worktree_command
from envctl_engine.runtime.codex_tmux_support import run_codex_tmux_command
from envctl_engine.runtime.prompt_install_support import run_install_prompts_command
from envctl_engine.runtime.playwright_command_support import run_playwright_command
from envctl_engine.runtime.qa_user_command_support import run_qa_user_command
from envctl_engine.runtime.supabase_user_command_support import run_supabase_user_command

UtilityCommandHandler = Callable[[Any, Route], int]


def utility_command_handlers() -> dict[str, UtilityCommandHandler]:
    return {
        "install-prompts": run_install_prompts_command,
        "codex-tmux": run_codex_tmux_command,
        "ensure-worktree": run_ensure_worktree_command,
        "supabase-user": run_supabase_user_command,
        "qa-user": run_qa_user_command,
        "playwright": run_playwright_command,
    }


def dispatch_utility_command(runtime: Any, route: Route) -> int:
    command = str(getattr(route, "command", "")).strip()
    handler = utility_command_handlers().get(command)
    if handler is not None:
        return handler(runtime, route)
    raise RuntimeError(f"Unsupported utility command: {command}")
