from __future__ import annotations

from collections.abc import Callable
from typing import Any

from envctl_engine.actions.action_ship_contract import emit_ship_progress
from envctl_engine.actions.action_ship_phase_status import (
    callable_accepts_keyword,
    check_phase_status,
    ship_status_is_success,
)

GithubPrChecks = Callable[..., dict[str, object]]
FinishShip = Callable[..., int]


def run_ship_checks_phase(
    *,
    state: Any,
    checks_fn: GithubPrChecks,
    finish: FinishShip,
) -> int:
    check_kwargs: dict[str, object] = {
        "branch": state.branch,
        "pr_url": state.pr_url,
        "expected_head_sha": state.after_sha,
    }
    if callable_accepts_keyword(checks_fn, "progress_callback"):
        check_kwargs["progress_callback"] = emit_ship_progress
    checks = checks_fn(state.git_root, **check_kwargs)
    status = check_phase_status(checks)
    state.step_statuses.append(status)
    return finish(
        state,
        status=status,
        ok=ship_status_is_success(status),
        commit_sha=state.after_sha,
        pushed=state.pushed,
        pr_url=state.pr_url,
        pr_created=state.pr_created,
        checks=checks,
        merge_conflicts=state.merge_conflicts,
    )


__all__ = ["run_ship_checks_phase"]
