from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from envctl_engine.shared.parsing import parse_bool


def setup_worktree_placeholder_fallback_enabled(
    *,
    env: Mapping[str, str],
    config_raw: Mapping[str, Any],
) -> bool:
    raw = env.get("ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK") or config_raw.get(
        "ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK"
    )
    return parse_bool(raw, False)


def worktree_target_created(target: Path) -> bool:
    return target.is_dir() and (target / ".git").exists()


def recover_partial_worktree_creation(
    *,
    git_hooks_disabled: bool,
    target: Path,
    feature: str,
    iteration: str,
    result: object,
    command_result_error_text: Callable[[object], str],
    emit: Callable[..., None],
) -> bool:
    if not git_hooks_disabled:
        return False
    if not worktree_target_created(target):
        return False
    reason = command_result_error_text(result)
    emit(
        "setup.worktree.partial_git_failure_recovered",
        feature=feature,
        iteration=iteration,
        target=str(target),
        reason=reason,
    )
    return True


def worktree_add_failure(
    *,
    feature: str,
    iteration: str,
    target: Path,
    result: object,
    placeholder_fallback_enabled: bool,
    command_result_error_text: Callable[[object], str],
    link_repo_local_shared_artifacts: Callable[[Path], None],
    emit: Callable[..., None],
) -> str | None:
    reason = command_result_error_text(result)
    if placeholder_fallback_enabled:
        target.mkdir(parents=True, exist_ok=True)
        marker = target / ".envctl_worktree_placeholder"
        marker.write_text(
            (
                "envctl placeholder worktree created after git worktree add failure\n"
                f"feature={feature}\n"
                f"iteration={iteration}\n"
                f"error={reason}\n"
            ),
            encoding="utf-8",
        )
        link_repo_local_shared_artifacts(target)
        emit(
            "setup.worktree.placeholder_fallback",
            feature=feature,
            iteration=iteration,
            target=str(target),
            reason=reason,
        )
        return None
    target_status = "target exists" if target.exists() else "target missing"
    hook_policy_hint = (
        "envctl disables repo-local Git hooks during managed worktree creation by default; "
        "set ENVCTL_WORKTREE_GIT_HOOKS=inherit to opt into hooks."
    )
    return f"failed creating worktree {feature}/{iteration}: {reason} ({target_status}). {hook_policy_hint}"
