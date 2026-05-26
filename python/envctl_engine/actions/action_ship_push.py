from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Any, Callable

from envctl_engine.actions.action_ship_contract import emit_ship_progress

RunGit = Callable[[Path, list[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True, slots=True)
class ShipPushPhaseResult:
    failed: bool = False
    pushed: bool = False
    step_status: str = ""


def run_ship_push_phase(
    *,
    git_root: Path,
    branch: str,
    after_sha: str,
    pr_url: str,
    committed: bool,
    context: Any,
    run_git: RunGit,
) -> ShipPushPhaseResult:
    if not after_sha or not pr_url or committed:
        return ShipPushPhaseResult()
    if not _remote_branch_needs_push(git_root=git_root, after_sha=after_sha, run_git=run_git):
        return ShipPushPhaseResult()

    remote = str(getattr(context, "env", {}).get("PR_REMOTE") or "origin").strip() or "origin"
    result = run_git(git_root, ["push", "-u", remote, branch])
    if int(getattr(result, "returncode", 1) or 0) != 0:
        return ShipPushPhaseResult(failed=True, pushed=False, step_status="push_failed")

    emit_ship_progress(f"ship: push succeeded for {context.project_name}.")
    return ShipPushPhaseResult(failed=False, pushed=True, step_status="pushed_existing_head")


def _remote_branch_needs_push(*, git_root: Path, after_sha: str, run_git: RunGit) -> bool:
    upstream = run_git(git_root, ["rev-parse", "--verify", "@{u}"])
    if int(getattr(upstream, "returncode", 1) or 0) != 0:
        return True
    upstream_sha = str(getattr(upstream, "stdout", "") or "").strip()
    return upstream_sha != after_sha


__all__ = ["ShipPushPhaseResult", "run_ship_push_phase"]
