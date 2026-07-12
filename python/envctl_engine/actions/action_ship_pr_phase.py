from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from envctl_engine.actions.action_ship_contract import emit_ship_progress
from envctl_engine.actions.action_ship_pr_context import explicit_pr_base as _explicit_pr_base


FinishShip = Callable[..., int]


def run_ship_pr_phase(
    *,
    state: Any,
    context: Any,
    run_pr_action: Callable[[Any], int],
    existing_pr_url: Callable[[Path, str], str],
    finish: FinishShip,
) -> int | None:
    if state.pr_url:
        explicit_base = _explicit_pr_base(context)
        if explicit_base:
            pr_code = run_pr_action(context)
            if pr_code != 0:
                return finish(
                    state,
                    status="pr_failed",
                    ok=False,
                    commit_sha=state.after_sha,
                    pr_url=state.pr_url,
                    pr_created=False,
                )
            state.pr_url = existing_pr_url(state.git_root, state.branch) or state.pr_url
        state.step_statuses.append("pr_exists")
        emit_ship_progress(f"ship: PR already exists for {context.project_name}: {state.pr_url}")
        return None

    pr_code = run_pr_action(context)
    if pr_code != 0:
        return finish(state, status="pr_failed", ok=False, commit_sha=state.after_sha)

    state.pr_url = existing_pr_url(state.git_root, state.branch)
    state.pr_created = bool(state.pr_url)
    state.step_statuses.append("pr_created" if state.pr_created else "pr_unresolved")
    if state.pr_created:
        emit_ship_progress(f"ship: PR created for {context.project_name}: {state.pr_url}")
        return None
    return finish(
        state,
        status="pr_unresolved",
        ok=False,
        commit_sha=state.after_sha,
        pushed=state.pushed,
        pr_url="",
        pr_created=False,
    )


def run_ship_pr_label_phase(
    *,
    state: Any,
    context: Any,
    add_ship_pr_label: Callable[[Any, Path, str], int],
    finish: FinishShip,
) -> int | None:
    if not state.pr_url:
        return None
    label_code = add_ship_pr_label(context, state.git_root, state.pr_url)
    if label_code == 0:
        return None
    state.step_statuses.append("pr_label_failed")
    return finish(
        state,
        status="pr_label_failed",
        ok=False,
        commit_sha=state.after_sha,
        pushed=state.pushed,
        pr_url=state.pr_url,
        pr_created=state.pr_created,
    )


__all__ = ["run_ship_pr_label_phase", "run_ship_pr_phase"]
