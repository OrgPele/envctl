from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
import subprocess
import time
from typing import Any, Callable

from envctl_engine.actions.action_ship_checks import github_pr_checks, normalize_github_pr_checks
from envctl_engine.actions.action_ship_conflicts import (
    existing_merge_conflict_report,
    parse_merge_tree_conflicts,
    predicted_merge_conflict_report,
    unmerged_stage_entries,
)
from envctl_engine.actions.action_ship_contract import (
    parse_ship_json_output,
    print_ship_result,
    ship_payload,
    ship_protected_paths,
)

GitOutput = Callable[[Path, list[str]], str]
RunGit = Callable[[Path, list[str]], subprocess.CompletedProcess[str]]
ResolveBaseBranch = Callable[[Any, Path], str]
ResolveBaseRef = Callable[[Path, str], str]
GithubPrChecks = Callable[..., dict[str, object]]


@dataclass(slots=True)
class ShipWorkflowState:
    git_root: Path
    json_output: bool
    started: float
    branch: str = ""
    before_sha: str = ""
    after_sha: str = ""
    protected_paths: list[str] = field(default_factory=list)
    pre_commit_dirty: bool = False
    committed: bool = False
    pr_url: str = ""
    pr_created: bool = False
    step_statuses: list[str] = field(default_factory=list)
    merge_conflicts: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class ShipWorkflowRunner:
    context: Any
    resolve_git_root: Callable[[Path, Path], Path]
    git_available: bool
    git_output: GitOutput
    run_git: RunGit
    resolve_base_branch: ResolveBaseBranch
    resolve_base_ref: ResolveBaseRef
    run_commit_action: Callable[[Any], int]
    run_pr_action: Callable[[Any], int]
    probe_dirty_worktree: Callable[..., Any]
    existing_pr_url: Callable[[Path, str], str]
    partition_envctl_protected_paths: Callable[[str], Any]
    ordered_unique_paths: Callable[..., list[str]]
    github_pr_checks: GithubPrChecks | None = None

    def run(self) -> int:
        state = self._new_state()
        if result := self._reject_unavailable_git(state):
            return result
        if result := self._resolve_branch(state):
            return result
        if result := self._reject_existing_merge_conflicts(state):
            return result
        if result := self._run_commit_phase(state):
            return result
        if result := self._run_pr_phase(state):
            return result
        if result := self._reject_predicted_merge_conflicts(state):
            return result
        return self._run_checks_phase(state)

    def _new_state(self) -> ShipWorkflowState:
        return ShipWorkflowState(
            git_root=self.resolve_git_root(self.context.project_root, self.context.repo_root),
            json_output=parse_ship_json_output(self.context),
            started=time.monotonic(),
        )

    def _reject_unavailable_git(self, state: ShipWorkflowState) -> int | None:
        if self.git_available:
            return None
        return self._finish(state, status="git_unavailable", ok=False)

    def _resolve_branch(self, state: ShipWorkflowState) -> int | None:
        state.branch = self.git_output(state.git_root, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
        if state.branch and state.branch != "HEAD":
            return None
        state.branch = state.branch or "HEAD"
        return self._finish(state, status="detached_head", ok=True)

    def _reject_existing_merge_conflicts(self, state: ShipWorkflowState) -> int | None:
        existing_conflicts = existing_merge_conflict_report(
            state.git_root,
            branch=state.branch,
            git_output=self.git_output,
        )
        if existing_conflicts.get("state") != "conflicts":
            return None
        state.step_statuses.append("merge_conflicts")
        return self._finish(
            state,
            status="merge_conflicts",
            ok=False,
            merge_conflicts=existing_conflicts,
        )

    def _run_commit_phase(self, state: ShipWorkflowState) -> int | None:
        state.before_sha = self.git_output(state.git_root, ["rev-parse", "HEAD"]).strip()
        state.protected_paths = ship_protected_paths(
            state.git_root,
            git_output=self.git_output,
            partition_envctl_protected_paths=self.partition_envctl_protected_paths,
            ordered_unique_paths=self.ordered_unique_paths,
        )
        state.pre_commit_dirty = self.probe_dirty_worktree(
            self.context.project_root,
            self.context.repo_root,
            project_name=self.context.project_name,
        ).dirty
        state.pr_url = self.existing_pr_url(state.git_root, state.branch)

        commit_code = self.run_commit_action(self.context)
        state.after_sha = self.git_output(state.git_root, ["rev-parse", "HEAD"]).strip()
        state.committed = bool(state.after_sha and state.before_sha and state.after_sha != state.before_sha) or bool(
            state.pre_commit_dirty and commit_code == 0
        )
        state.step_statuses.append("committed_pushed" if state.committed else "clean_no_changes")
        if commit_code == 0:
            return None
        return self._finish(state, status="commit_failed", ok=False, commit_sha=state.after_sha)

    def _run_pr_phase(self, state: ShipWorkflowState) -> int | None:
        if state.pr_url:
            state.step_statuses.append("pr_exists")
            return None

        pr_code = self.run_pr_action(self.context)
        if pr_code != 0:
            return self._finish(state, status="pr_failed", ok=False, commit_sha=state.after_sha)

        state.pr_url = self.existing_pr_url(state.git_root, state.branch)
        state.pr_created = bool(state.pr_url)
        state.step_statuses.append("pr_created" if state.pr_created else "pr_unresolved")
        return None

    def _reject_predicted_merge_conflicts(self, state: ShipWorkflowState) -> int | None:
        state.merge_conflicts = predicted_merge_conflict_report(
            self.context,
            state.git_root,
            branch=state.branch,
            resolve_base_branch=self.resolve_base_branch,
            resolve_base_ref=self.resolve_base_ref,
            run_git=self.run_git,
            git_output=self.git_output,
        )
        if state.merge_conflicts.get("state") != "conflicts":
            return None
        state.step_statuses.append("merge_conflicts")
        return self._finish(
            state,
            status="merge_conflicts",
            ok=False,
            commit_sha=state.after_sha,
            pushed=state.committed,
            pr_url=state.pr_url,
            pr_created=state.pr_created,
            checks={"state": "merge_conflicts", "failing_checks": [], "pending_checks": []},
            merge_conflicts=state.merge_conflicts,
        )

    def _run_checks_phase(self, state: ShipWorkflowState) -> int:
        checks_fn = self.github_pr_checks or globals()["github_pr_checks"]
        checks = checks_fn(state.git_root, branch=state.branch, pr_url=state.pr_url)
        status = str(checks.get("state") or ("pr_created" if state.pr_created else "pr_exists"))
        if status:
            state.step_statuses.append(status)
        return self._finish(
            state,
            status=status,
            ok=status not in {"checks_failed", "commit_failed", "pr_failed"},
            commit_sha=state.after_sha,
            pushed=state.committed,
            pr_url=state.pr_url,
            pr_created=state.pr_created,
            checks=checks,
            merge_conflicts=state.merge_conflicts,
        )

    def _finish(
        self,
        state: ShipWorkflowState,
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
            context=self.context,
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


def run_ship_workflow(
    context: Any,
    *,
    resolve_git_root: Callable[[Path, Path], Path],
    git_available: bool,
    git_output: GitOutput,
    run_git: RunGit,
    resolve_base_branch: ResolveBaseBranch,
    resolve_base_ref: ResolveBaseRef,
    run_commit_action: Callable[[Any], int],
    run_pr_action: Callable[[Any], int],
    probe_dirty_worktree: Callable[..., Any],
    existing_pr_url: Callable[[Path, str], str],
    partition_envctl_protected_paths: Callable[[str], Any],
    ordered_unique_paths: Callable[..., list[str]],
    github_pr_checks: GithubPrChecks | None = None,
) -> int:
    return ShipWorkflowRunner(
        context=context,
        resolve_git_root=resolve_git_root,
        git_available=git_available,
        git_output=git_output,
        run_git=run_git,
        resolve_base_branch=resolve_base_branch,
        resolve_base_ref=resolve_base_ref,
        run_commit_action=run_commit_action,
        run_pr_action=run_pr_action,
        probe_dirty_worktree=probe_dirty_worktree,
        existing_pr_url=existing_pr_url,
        partition_envctl_protected_paths=partition_envctl_protected_paths,
        ordered_unique_paths=ordered_unique_paths,
        github_pr_checks=github_pr_checks,
    ).run()


_parse_json_output = parse_ship_json_output


__all__ = [
    "GitOutput",
    "GithubPrChecks",
    "ResolveBaseBranch",
    "ResolveBaseRef",
    "RunGit",
    "ShipWorkflowRunner",
    "ShipWorkflowState",
    "_parse_json_output",
    "existing_merge_conflict_report",
    "github_pr_checks",
    "normalize_github_pr_checks",
    "parse_merge_tree_conflicts",
    "parse_ship_json_output",
    "predicted_merge_conflict_report",
    "print_ship_result",
    "run_ship_workflow",
    "ship_payload",
    "ship_protected_paths",
    "unmerged_stage_entries",
]
