from __future__ import annotations

from typing import Any

from envctl_engine.runtime.ensure_worktree_support import run_ensure_worktree_command
from envctl_engine.runtime.codex_tmux_support import run_codex_tmux_command
from envctl_engine.runtime.prompt_install_support import run_install_prompts_command


def dispatch_utility_command(runtime: Any, route: object) -> int:
    command = str(getattr(route, "command", "")).strip()
    if command == "install-prompts":
        return run_install_prompts_command(runtime, route)
    if command == "codex-tmux":
        return run_codex_tmux_command(runtime, route)
    if command == "ensure-worktree":
        return run_ensure_worktree_command(runtime, route)
    raise RuntimeError(f"Unsupported utility command: {command}")
