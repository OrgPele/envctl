from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from envctl_engine.actions.action_ship_contract import print_ship_result, ship_payload


def finish_ship_workflow(
    context: Any,
    state: Any,
    *,
    status: str,
    ok: bool,
    commit_sha: str = "",
    pushed: bool = False,
    pr_url: str = "",
    pr_created: bool = False,
    checks: Mapping[str, object] | None = None,
    merge_conflicts: Mapping[str, object] | None = None,
) -> int:
    payload = ship_payload(
        context=context,
        git_root=state.git_root,
        branch=state.branch,
        status=status,
        started=state.started,
        commit_sha=commit_sha,
        committed=state.committed,
        pushed=pushed,
        pr_url=pr_url,
        pr_created=pr_created,
        protected_paths=state.protected_paths,
        checks=checks,
        step_statuses=state.step_statuses,
        merge_conflicts=merge_conflicts,
    )
    return print_ship_result(payload, json_output=state.json_output, ok=ok)


__all__ = ["finish_ship_workflow"]
