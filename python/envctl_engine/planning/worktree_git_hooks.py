from __future__ import annotations

from typing import Any


_WORKTREE_GIT_HOOKS_DISABLED_VALUES = frozenset(("disabled", "disable", "off", "false", "0", "no"))
_WORKTREE_GIT_HOOKS_INHERITED_VALUES = frozenset(
    ("inherit", "inherited", "enabled", "enable", "on", "true", "1", "yes")
)


def worktree_git_hooks_policy(self: Any) -> str:
    raw = self.env.get("ENVCTL_WORKTREE_GIT_HOOKS") or self.config.raw.get("ENVCTL_WORKTREE_GIT_HOOKS") or "disabled"
    normalized = str(raw).strip().lower()
    if normalized in _WORKTREE_GIT_HOOKS_DISABLED_VALUES:
        return "disabled"
    if normalized in _WORKTREE_GIT_HOOKS_INHERITED_VALUES:
        return "inherit"
    allowed = ", ".join(sorted(_WORKTREE_GIT_HOOKS_DISABLED_VALUES | _WORKTREE_GIT_HOOKS_INHERITED_VALUES))
    raise RuntimeError(f"Invalid ENVCTL_WORKTREE_GIT_HOOKS value {raw!r}; expected one of: {allowed}.")


def worktree_git_hooks_disabled(self: Any) -> bool:
    return worktree_git_hooks_policy(self) == "disabled"
