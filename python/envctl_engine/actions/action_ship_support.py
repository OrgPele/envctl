from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
import subprocess
import time
from typing import Any, Callable

from envctl_engine.actions.action_ship_check_results import normalize_github_pr_checks  # noqa: F401
from envctl_engine.actions.action_ship_checks import github_pr_checks as default_github_pr_checks
from envctl_engine.actions.action_ship_conflicts import (
    existing_merge_conflict_report,
    parse_merge_tree_conflicts,  # noqa: F401
    predicted_merge_conflict_report,
    unmerged_stage_entries,  # noqa: F401
)
from envctl_engine.actions.action_ship_contract import (
    emit_ship_commit_progress,
    emit_ship_progress,
    parse_ship_json_output,
    print_ship_result,  # noqa: F401
    ship_payload,  # noqa: F401
    ship_protected_paths,
)
from envctl_engine.actions.action_ship_finish import finish_ship_workflow
from envctl_engine.actions.action_ship_phase_status import (
    callable_accepts_keyword,
    check_phase_status,
    ship_status_is_success,
)
from envctl_engine.actions.action_ship_push import run_ship_push_phase

GitOutput = Callable[[Path, list[str]], str]
RunGit = Callable[[Path, list[str]], subprocess.CompletedProcess[str]]
ResolveBaseBranch = Callable[[Any, Path], str]
ResolveBaseRef = Callable[[Path, str], str]
GithubPrChecks = Callable[..., dict[str, object]]
github_pr_checks = default_github_pr_checks

@dataclass(slots=True)
class ShipWorkflowState:
    git_root: Path
    json_output: bool
    started: float
    branch: str = ""
    before_sha: str = ""
    after_sha: str = ""
    protected_paths: list[str] = field(default_factory=list)
    committed: bool = False
    pushed: bool = False
    pr_url: str = ""
    pr_created: bool = False
    step_statuses: list[str] = field(default_factory=list)
    merge_conflicts: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class ShipWorkflowDependencies:
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


@dataclass(slots=True)
class ShipWorkflowRunner:
    context: Any
    dependencies: ShipWorkflowDependencies

    def run(self) -> int:
        state = self._new_state()
        for phase in (
            self._reject_unavailable_git,
            self._resolve_branch,
            self._reject_existing_merge_conflicts,
            self._run_commit_phase,
            self._run_pr_phase,
            self._reject_predicted_merge_conflicts,
            self._run_push_phase,
        ):
            result = phase(state)
            if result is not None:
                return result
        return self._run_checks_phase(state)

    def _new_state(self) -> ShipWorkflowState:
        return ShipWorkflowState(
            git_root=self.dependencies.resolve_git_root(self.context.project_root, self.context.repo_root),
            json_output=parse_ship_json_output(self.context),
            started=time.monotonic(),
        )

    def _reject_unavailable_git(self, state: ShipWorkflowState) -> int | None:
        if self.dependencies.git_available:
            return None
        return self._finish(state, status="git_unavailable", ok=False)

    def _resolve_branch(self, state: ShipWorkflowState) -> int | None:
        state.branch = self.dependencies.git_output(state.git_root, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
        if state.branch and state.branch != "HEAD":
            return None
        state.branch = state.branch or "HEAD"
        return self._finish(state, status="detached_head", ok=False)

    def _reject_existing_merge_conflicts(self, state: ShipWorkflowState) -> int | None:
        existing_conflicts = existing_merge_conflict_report(
            state.git_root,
            branch=state.branch,
            git_output=self.dependencies.git_output,
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
        state.before_sha = self.dependencies.git_output(state.git_root, ["rev-parse", "HEAD"]).strip()
        state.protected_paths = ship_protected_paths(
            state.git_root,
            git_output=self.dependencies.git_output,
            partition_envctl_protected_paths=self.dependencies.partition_envctl_protected_paths,
            ordered_unique_paths=self.dependencies.ordered_unique_paths,
        )
        self.dependencies.probe_dirty_worktree(
            self.context.project_root,
            self.context.repo_root,
            project_name=self.context.project_name,
        )
        state.pr_url = self.dependencies.existing_pr_url(state.git_root, state.branch)

        commit_code = self.dependencies.run_commit_action(self.context)
        state.after_sha = self.dependencies.git_output(state.git_root, ["rev-parse", "HEAD"]).strip()
        sha_changed = bool(state.after_sha and state.before_sha and state.after_sha != state.before_sha)
        state.committed = sha_changed
        state.pushed = state.committed
        state.step_statuses.append("committed_pushed" if state.committed else "clean_no_changes")
        if commit_code == 0:
            if state.committed:
                emit_ship_commit_progress(project_name=str(self.context.project_name), commit_sha=state.after_sha)
            return None
        return self._finish(state, status="commit_failed", ok=False, commit_sha=state.after_sha)

    def _run_pr_phase(self, state: ShipWorkflowState) -> int | None:
        if state.pr_url:
            state.step_statuses.append("pr_exists")
            emit_ship_progress(f"ship: PR already exists for {self.context.project_name}: {state.pr_url}")
            return None

        pr_code = self.dependencies.run_pr_action(self.context)
        if pr_code != 0:
            return self._finish(state, status="pr_failed", ok=False, commit_sha=state.after_sha)

        state.pr_url = self.dependencies.existing_pr_url(state.git_root, state.branch)
        state.pr_created = bool(state.pr_url)
        state.step_statuses.append("pr_created" if state.pr_created else "pr_unresolved")
        if state.pr_created:
            emit_ship_progress(f"ship: PR created for {self.context.project_name}: {state.pr_url}")
            return None
        return self._finish(
            state,
            status="pr_unresolved",
            ok=False,
            commit_sha=state.after_sha,
            pushed=state.pushed,
            pr_url="",
            pr_created=False,
        )

    def _reject_predicted_merge_conflicts(self, state: ShipWorkflowState) -> int | None:
        state.merge_conflicts = predicted_merge_conflict_report(
            self.context,
            state.git_root,
            branch=state.branch,
            resolve_base_branch=self.dependencies.resolve_base_branch,
            resolve_base_ref=self.dependencies.resolve_base_ref,
            run_git=self.dependencies.run_git,
            git_output=self.dependencies.git_output,
        )
        if state.merge_conflicts.get("state") != "conflicts":
            return None
        state.step_statuses.append("merge_conflicts")
        return self._finish(
            state,
            status="merge_conflicts",
            ok=False,
            commit_sha=state.after_sha,
            pushed=state.pushed,
            pr_url=state.pr_url,
            pr_created=state.pr_created,
            checks={"state": "merge_conflicts", "failing_checks": [], "pending_checks": []},
            merge_conflicts=state.merge_conflicts,
        )

    def _run_push_phase(self, state: ShipWorkflowState) -> int | None:
        result = run_ship_push_phase(
            git_root=state.git_root,
            branch=state.branch,
            after_sha=state.after_sha,
            pr_url=state.pr_url,
            committed=state.committed,
            context=self.context,
            run_git=self.dependencies.run_git,
        )
        if result.step_status:
            state.step_statuses.append(result.step_status)
        if result.failed:
            return self._finish(
                state,
                status="push_failed",
                ok=False,
                commit_sha=state.after_sha,
                pushed=False,
                pr_url=state.pr_url,
                pr_created=state.pr_created,
                merge_conflicts=state.merge_conflicts,
            )
        if result.pushed:
            state.pushed = True
        return None

    def _run_checks_phase(self, state: ShipWorkflowState) -> int:
        checks_fn = self.dependencies.github_pr_checks or default_github_pr_checks
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
        return self._finish(
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
        return finish_ship_workflow(
            self.context,
            state,
            status=status,
            ok=ok,
            commit_sha=commit_sha,
            pushed=pushed,
            pr_url=pr_url,
            pr_created=pr_created,
            checks=checks,
            merge_conflicts=merge_conflicts,
        )

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
        dependencies=ShipWorkflowDependencies(
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
        ),
    ).run()
