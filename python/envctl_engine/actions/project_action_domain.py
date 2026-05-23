from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Mapping

import envctl_engine.actions.action_pr_message_support as pr_message_support
import envctl_engine.actions.action_ship_support as ship_support
from envctl_engine.actions.action_protected_artifacts import (
    EnvctlProtectedPathPartition,
    ordered_unique_paths as _ordered_unique_paths,
    partition_envctl_protected_paths as _partition_envctl_protected_paths,
    status_candidate_path as _status_candidate_path,
)
from envctl_engine.actions.action_review_output_support import (
    display_path as _display_path,
    parse_review_stats as _parse_review_stats,
    print_review_completion as _print_review_completion,
    print_review_completion_rich as _print_review_completion_rich,
    print_review_failure as _print_review_failure,
    prune_review_output_dir as _prune_review_output_dir,
    review_colorizer as _review_colorizer,
)
from envctl_engine.planning import planning_feature_name
from envctl_engine.shared.parsing import parse_bool
from envctl_engine.ui.path_links import render_paths_in_terminal_text

PR_BODY_MAX_CHARS = 48_000
PR_TITLE_MAX_CHARS = 240
COMMIT_MESSAGE_MAX_CHARS = 16_000
WORKTREE_PROVENANCE_SCHEMA_VERSION = 1
WORKTREE_PROVENANCE_PATH = Path(".envctl-state") / "worktree-provenance.json"
PLANNING_ROOT = Path("todo") / "plans"
DONE_PLANNING_ROOT = Path("todo") / "done"
ENVCTL_COMMIT_LEDGER_NAME = ".envctl-commit-message.md"
ENVCTL_COMMIT_POINTER_MARKER = "### Envctl pointer ###"

__all__ = [
    "ActionProjectContext",
    "DirtyWorktreeReport",
    "EnvctlProtectedPathPartition",
    "OriginalPlanResolution",
    "ReviewBaseResolution",
    "ReviewBaseResolutionError",
    "_display_path",
    "_latest_changelog_commit_message",
    "_main_task_title",
    "_normalize_text_block",
    "_normalize_title_text",
    "_parse_merge_tree_conflicts",
    "_partition_envctl_protected_paths",
    "_pr_body",
    "_pr_commit_messages",
    "_pr_diff_stat",
    "_pr_title",
    "_print_review_completion",
    "_print_review_completion_rich",
    "_read_text",
    "_review_colorizer",
    "_status_candidate_path",
    "_truncate_pr_body",
    "_unmerged_stage_entries",
    "_write_pr_body_file",
    "detect_default_branch",
    "existing_pr_url",
    "probe_dirty_worktree",
    "resolve_git_root",
    "run_commit_action",
    "run_pr_action",
    "run_review_action",
    "run_ship_action",
    "sanitize_label",
]


@dataclass(frozen=True, slots=True)
class ActionProjectContext:
    repo_root: Path
    project_root: Path
    project_name: str
    env: Mapping[str, str]

    @property
    def interactive(self) -> bool:
        return parse_bool(self.env.get("ENVCTL_ACTION_INTERACTIVE"), False) and bool(sys.stdin.isatty())


@dataclass(frozen=True, slots=True)
class ReviewBaseResolution:
    base_branch: str
    base_ref: str
    source: str
    merge_base: str


class ReviewBaseResolutionError(RuntimeError):
    """Raised when envctl cannot determine a usable review base."""


@dataclass(frozen=True, slots=True)
class OriginalPlanResolution:
    path: Path | None
    source: str


@dataclass(frozen=True, slots=True)
class DirtyWorktreeReport:
    project_name: str
    project_root: Path
    git_root: Path
    staged: bool
    unstaged: bool
    untracked: bool

    @property
    def dirty(self) -> bool:
        return self.staged or self.unstaged or self.untracked


def run_commit_action(context: ActionProjectContext) -> int:
    git_root = resolve_git_root(context.project_root, context.repo_root)
    if shutil.which("git") is None:
        print("git is required for commit action")
        return 1

    branch = _git_output(git_root, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
    if not branch or branch == "HEAD":
        print(f"Skipping {context.project_name} (detached HEAD).")
        return 0

    pre_stage_status = _run_git(git_root, ["status", "--porcelain", "--untracked-files=all"])
    if pre_stage_status.returncode != 0:
        _print_error("git status failed", pre_stage_status)
        return 1
    partition = _partition_envctl_protected_paths(pre_stage_status.stdout)
    unstaged_protected_paths: list[str] = []
    if partition.protected_staged_paths:
        reset = _unstage_envctl_protected_paths(git_root, partition.protected_staged_paths)
        if reset.returncode != 0:
            _print_error("git reset protected envctl-local artifacts failed", reset)
            print("Protected envctl-local artifacts still staged: " + ", ".join(partition.protected_staged_paths))
            return 1
        unstaged_protected_paths = list(partition.protected_staged_paths)
        print("Unstaged envctl-local artifacts: " + ", ".join(unstaged_protected_paths))

        refreshed_status = _run_git(git_root, ["status", "--porcelain", "--untracked-files=all"])
        if refreshed_status.returncode != 0:
            _print_error("git status failed", refreshed_status)
            return 1
        partition = _partition_envctl_protected_paths(refreshed_status.stdout)
        if partition.protected_staged_paths:
            print(
                "Protected envctl-local artifacts remain staged after recovery: "
                + ", ".join(partition.protected_staged_paths)
            )
            return 1

    if partition.stageable_paths:
        add = _run_git(git_root, ["add", "--", *partition.stageable_paths])
        if add.returncode != 0:
            _print_error("git add failed", add)
            return 1
    protected_paths = _ordered_unique_paths(unstaged_protected_paths, partition.protected_skipped_paths)
    if protected_paths:
        print("Skipping envctl-local artifacts: " + ", ".join(protected_paths))

    status = _run_git(git_root, ["status", "--porcelain"])
    if status.returncode != 0:
        _print_error("git status failed", status)
        return 1
    commit_partition = _partition_envctl_protected_paths(status.stdout)
    if commit_partition.protected_staged_paths:
        print(
            "Protected envctl-local artifacts remain staged after recovery: "
            + ", ".join(commit_partition.protected_staged_paths)
        )
        return 1
    if not commit_partition.stageable_paths:
        print(f"No changes to commit for {branch}.")
        return 0

    commit_message, message_file, error, ledger_path = _resolve_commit_message(context, branch=branch)
    if error:
        error_paths: list[object] = []
        explicit_message_file = str(context.env.get("ENVCTL_COMMIT_MESSAGE_FILE", "")).strip()
        if explicit_message_file:
            error_paths.append(explicit_message_file)
        elif ledger_path is not None:
            error_paths.append(ledger_path)
        print(render_paths_in_terminal_text(error, paths=error_paths, env=context.env, stream=sys.stdout))
        return 1

    generated_message_file = message_file.endswith(".envctl-commit-message.txt")
    try:
        if message_file:
            commit = _run_git(git_root, ["commit", "-F", message_file])
        else:
            commit = _run_git(git_root, ["commit", "-m", commit_message])
    finally:
        if generated_message_file:
            try:
                Path(message_file).unlink()
            except OSError:
                pass
    if commit.returncode != 0:
        _print_error("git commit failed", commit)
        return 1

    if ledger_path is not None:
        advance_error = _advance_commit_ledger_pointer(ledger_path)
        if advance_error:
            print(
                render_paths_in_terminal_text(
                    advance_error,
                    paths=[ledger_path],
                    env=context.env,
                    stream=sys.stdout,
                )
            )
            return 1

    remote = str(context.env.get("PR_REMOTE") or "origin").strip() or "origin"
    push = _run_git(git_root, ["push", "-u", remote, branch])
    if push.returncode != 0:
        _print_error("git push failed", push)
        return 1

    print(f"Committed and pushed changes for {context.project_name} ({branch}).")
    return 0


def _unstage_envctl_protected_paths(git_root: Path, paths: list[str]) -> subprocess.CompletedProcess[str]:
    return _run_git(git_root, ["reset", "-q", "--", *paths])


def _pr_title(context: ActionProjectContext, git_root: Path, head_branch: str) -> str:
    return pr_message_support.pr_title(
        context,
        git_root,
        head_branch,
        git_output=_git_output,
        max_chars=PR_TITLE_MAX_CHARS,
    )


def _pr_body(context: ActionProjectContext, git_root: Path, head_branch: str, base_branch: str) -> str:
    return pr_message_support.pr_body(
        context,
        git_root,
        head_branch,
        base_branch,
        git_output=_git_output,
        max_chars=PR_BODY_MAX_CHARS,
    )


def _pr_commit_messages(git_root: Path, *, head_branch: str, base_branch: str) -> str:
    return pr_message_support.pr_commit_messages(
        git_root,
        head_branch=head_branch,
        base_branch=base_branch,
        git_output=_git_output,
        max_chars=PR_BODY_MAX_CHARS,
    )


def _pr_diff_stat(git_root: Path, *, head_branch: str, base_branch: str) -> str:
    return pr_message_support.pr_diff_stat(
        git_root,
        head_branch=head_branch,
        base_branch=base_branch,
        git_output=_git_output,
    )


def _pr_commit_range(git_root: Path, *, head_branch: str, base_branch: str) -> str:
    return pr_message_support.pr_commit_range(
        git_root,
        head_branch=head_branch,
        base_branch=base_branch,
        git_output=_git_output,
    )


def _pr_compare_range(git_root: Path, *, head_branch: str, base_branch: str) -> str:
    return pr_message_support.pr_compare_range(
        git_root,
        head_branch=head_branch,
        base_branch=base_branch,
        git_output=_git_output,
    )


def _pr_base_ref(git_root: Path, base_branch: str) -> str:
    return pr_message_support.pr_base_ref(git_root, base_branch, git_output=_git_output)


def _existing_merge_conflict_report(git_root: Path, *, branch: str) -> dict[str, object]:
    return ship_support.existing_merge_conflict_report(git_root, branch=branch, git_output=_git_output)


def _predicted_merge_conflict_report(
    context: ActionProjectContext,
    git_root: Path,
    *,
    branch: str,
) -> dict[str, object]:
    return ship_support.predicted_merge_conflict_report(
        context,
        git_root,
        branch=branch,
        resolve_base_branch=_resolve_pr_base_branch,
        resolve_base_ref=_pr_base_ref,
        run_git=_run_git,
        git_output=_git_output,
    )


def _unmerged_stage_entries(git_root: Path) -> dict[str, list[dict[str, str]]]:
    return ship_support.unmerged_stage_entries(git_root, git_output=_git_output)


_parse_merge_tree_conflicts = ship_support.parse_merge_tree_conflicts
_github_pr_checks = ship_support.github_pr_checks
_ship_payload = ship_support.ship_payload
_print_ship_result = ship_support.print_ship_result
_recent_text_excerpt = pr_message_support.recent_text_excerpt
_truncate_recent_entries = pr_message_support.truncate_recent_entries
_latest_changelog_commit_message = pr_message_support.latest_changelog_commit_message
_select_changelog_subject = pr_message_support.select_changelog_subject
_main_task_title = pr_message_support.main_task_title_from_project
_normalize_title_text = pr_message_support.normalize_title_text
_truncate_pr_body = pr_message_support.truncate_pr_body
_normalize_text_block = pr_message_support.normalize_text_block
_read_text = pr_message_support.read_text
_write_pr_body_file = pr_message_support.write_pr_body_file


def run_pr_action(context: ActionProjectContext) -> int:
    git_root = resolve_git_root(context.project_root, context.repo_root)
    if shutil.which("git") is None:
        print("git is required for pr action")
        return 1

    head_branch = _git_output(git_root, ["rev-parse", "--abbrev-ref", "HEAD"]).strip() or "unknown"
    if head_branch in {"HEAD", "unknown"}:
        print(f"Skipping {context.project_name} (detached HEAD).")
        return 0
    base_branch = _resolve_pr_base_branch(context, git_root)

    existing_url = existing_pr_url(git_root, head_branch)
    if existing_url:
        print(f"PR already exists: {existing_url}")
        return 0

    dirty_report = probe_dirty_worktree(context.project_root, context.repo_root, project_name=context.project_name)
    if dirty_report.dirty:
        print(f"Dirty worktree detected for {context.project_name}; committing and pushing before PR creation.")
        commit_code = run_commit_action(context)
        if commit_code != 0:
            return commit_code

    helper = context.repo_root / "utils" / "create-pr.sh"
    if helper.is_file() and os.access(helper, os.X_OK):
        command = [str(helper)]
        if base_branch:
            command.extend(["--base", base_branch])
        command.extend(["--head", head_branch, "--workdir", str(git_root)])
        created = subprocess.run(
            command,
            cwd=str(context.repo_root),
            text=True,
            capture_output=True,
            check=False,
        )
        _print_process_output(created)
        if created.returncode != 0:
            return 1
        return 0

    gh_path = shutil.which("gh")
    if gh_path is None:
        print("gh is required for pr action when utils/create-pr.sh is unavailable")
        return 1
    title = _pr_title(context, git_root, head_branch)
    body = _pr_body(context, git_root, head_branch, base_branch)
    body_file = _write_pr_body_file(body)
    args = [gh_path, "pr", "create", "--title", title, "--body-file", str(body_file), "--head", head_branch]
    if base_branch:
        args.extend(["--base", base_branch])
    try:
        created = subprocess.run(args, cwd=str(git_root), text=True, capture_output=True, check=False)
        _print_process_output(created)
        if created.returncode != 0:
            return 1
        return 0
    finally:
        try:
            body_file.unlink()
        except OSError:
            pass


def run_ship_action(context: ActionProjectContext) -> int:
    git_root = resolve_git_root(context.project_root, context.repo_root)
    json_output = parse_bool(context.env.get("ENVCTL_ACTION_JSON"), False)
    started = time.monotonic()
    if shutil.which("git") is None:
        payload = _ship_payload(
            context=context,
            git_root=git_root,
            branch="",
            status="git_unavailable",
            started=started,
        )
        return _print_ship_result(payload, json_output=json_output, ok=False)

    branch = _git_output(git_root, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
    if not branch or branch == "HEAD":
        payload = _ship_payload(
            context=context,
            git_root=git_root,
            branch=branch or "HEAD",
            status="detached_head",
            started=started,
        )
        return _print_ship_result(payload, json_output=json_output, ok=True)

    existing_conflicts = _existing_merge_conflict_report(git_root, branch=branch)
    if existing_conflicts.get("state") == "conflicts":
        payload = _ship_payload(
            context=context,
            git_root=git_root,
            branch=branch,
            status="merge_conflicts",
            started=started,
            merge_conflicts=existing_conflicts,
            step_statuses=["merge_conflicts"],
        )
        return _print_ship_result(payload, json_output=json_output, ok=False)

    before_sha = _git_output(git_root, ["rev-parse", "HEAD"]).strip()
    protected_paths = _ship_protected_paths(git_root)
    pre_commit_dirty = probe_dirty_worktree(
        context.project_root,
        context.repo_root,
        project_name=context.project_name,
    ).dirty
    step_statuses: list[str] = []
    existing_url = existing_pr_url(git_root, branch)

    commit_code = run_commit_action(context)
    after_sha = _git_output(git_root, ["rev-parse", "HEAD"]).strip()
    committed = bool(after_sha and before_sha and after_sha != before_sha) or bool(
        pre_commit_dirty and commit_code == 0
    )
    step_statuses.append("committed_pushed" if committed else "clean_no_changes")
    if commit_code != 0:
        payload = _ship_payload(
            context=context,
            git_root=git_root,
            branch=branch,
            status="commit_failed",
            started=started,
            commit_sha=after_sha,
            committed=committed,
            protected_paths=protected_paths,
            step_statuses=step_statuses,
        )
        return _print_ship_result(payload, json_output=json_output, ok=False)

    pr_url = existing_url
    pr_created = False
    if not pr_url:
        pr_code = run_pr_action(context)
        if pr_code != 0:
            payload = _ship_payload(
                context=context,
                git_root=git_root,
                branch=branch,
                status="pr_failed",
                started=started,
                commit_sha=after_sha,
                committed=committed,
                protected_paths=protected_paths,
                step_statuses=step_statuses,
            )
            return _print_ship_result(payload, json_output=json_output, ok=False)
        pr_url = existing_pr_url(git_root, branch)
        pr_created = bool(pr_url)
        step_statuses.append("pr_created" if pr_created else "pr_unresolved")
    else:
        step_statuses.append("pr_exists")

    merge_conflicts = _predicted_merge_conflict_report(context, git_root, branch=branch)
    if merge_conflicts.get("state") == "conflicts":
        step_statuses.append("merge_conflicts")
        payload = _ship_payload(
            context=context,
            git_root=git_root,
            branch=branch,
            status="merge_conflicts",
            started=started,
            commit_sha=after_sha,
            committed=committed,
            pushed=committed,
            pr_url=pr_url,
            pr_created=pr_created,
            protected_paths=protected_paths,
            checks={"state": "merge_conflicts", "failing_checks": [], "pending_checks": []},
            step_statuses=step_statuses,
            merge_conflicts=merge_conflicts,
        )
        return _print_ship_result(payload, json_output=json_output, ok=False)

    checks = _github_pr_checks(git_root, branch=branch, pr_url=pr_url)
    status = str(checks.get("state") or ("pr_created" if pr_created else "pr_exists"))
    if status:
        step_statuses.append(status)
    payload = _ship_payload(
        context=context,
        git_root=git_root,
        branch=branch,
        status=status,
        started=started,
        commit_sha=after_sha,
        committed=committed,
        pushed=committed,
        pr_url=pr_url,
        pr_created=pr_created,
        protected_paths=protected_paths,
        checks=checks,
        step_statuses=step_statuses,
        merge_conflicts=merge_conflicts,
    )
    ok = status not in {"checks_failed", "commit_failed", "pr_failed"}
    return _print_ship_result(payload, json_output=json_output, ok=ok)


def _ship_protected_paths(git_root: Path) -> list[str]:
    status_output = _git_output(git_root, ["status", "--porcelain", "--untracked-files=all"])
    partition = _partition_envctl_protected_paths(status_output)
    return _ordered_unique_paths(partition.protected_staged_paths, partition.protected_skipped_paths)


def run_review_action(context: ActionProjectContext) -> int:
    git_root = resolve_git_root(context.project_root, context.repo_root)
    if shutil.which("git") is None:
        print("git is required for review action")
        return 1

    mode = _resolve_analyze_mode(context)
    scope = str(context.env.get("ENVCTL_ANALYZE_SCOPE", "all")).strip().lower() or "all"
    original_plan = _resolve_original_plan(context)
    review_base: ReviewBaseResolution | None = None
    if mode == "single" or str(context.env.get("ENVCTL_REVIEW_BASE", "")).strip():
        try:
            review_base = _resolve_review_base(context, git_root)
        except ReviewBaseResolutionError as exc:
            print(str(exc))
            return 1

    helper = context.repo_root / "utils" / "analyze-tree-changes.sh"
    if helper.is_file() and os.access(helper, os.X_OK):
        iterations = _analysis_iterations(context, mode=mode)
        if iterations:
            return _run_analyze_helper(
                context=context,
                helper=helper,
                iterations=iterations,
                mode=mode,
                scope=scope,
                review_base=review_base,
                original_plan=original_plan,
            )

    if review_base is None:
        diff_stat = _git_output(git_root, ["diff", "--stat"]).strip()
        status = _git_output(git_root, ["status", "--porcelain"]).strip()
        output_path = _tree_diffs_output_path(
            context,
            "review",
            f"review_{sanitize_label(context.project_name)}_{mode}",
        )
        _write_markdown_lines(
            output_path,
            [
                f"# Review Summary: {context.project_name}",
                "",
                f"Mode: {mode}",
                f"Scope: {scope}",
                "",
                *_original_plan_markdown_lines(original_plan, include_contents=True),
                "## Diff Stat",
                diff_stat or "(no diff)",
                "",
                "## Working Tree",
                status or "(clean)",
                "",
            ],
        )
        _print_review_completion(
            context,
            mode=mode,
            scope=scope,
            output_dir=output_path.parent,
            summary_path=output_path,
            all_in_one_path=output_path,
            stats=[],
            tree_count=1,
        )
        return 0

    diff_left = review_base.merge_base or review_base.base_ref
    diff_stat = _git_output(git_root, ["diff", "--find-renames", "--stat", diff_left]).strip()
    changed_files = _git_output(git_root, ["diff", "--find-renames", "--name-status", diff_left]).strip()
    full_diff = _git_output(git_root, ["diff", "--find-renames", diff_left]).strip()
    status = _git_output(git_root, ["status", "--porcelain", "--untracked-files=all"]).strip()
    output_path = _tree_diffs_output_path(
        context,
        "review",
        f"review_{sanitize_label(context.project_name)}_{mode}",
    )
    _write_markdown_lines(
        output_path,
        [
            f"# Review Summary: {context.project_name}",
            "",
            f"Mode: {mode}",
            f"Scope: {scope}",
            "",
            *_original_plan_markdown_lines(original_plan, include_contents=True),
            "## Base branch",
            review_base.base_branch,
            "",
            "## Base resolution source",
            review_base.source,
            "",
            "## Base ref",
            review_base.base_ref,
            "",
            "## Merge base",
            review_base.merge_base or "(merge-base unavailable)",
            "",
            "## Diff Stat",
            diff_stat or "(no diff)",
            "",
            "## Changed files",
            changed_files or "(no changed files)",
            "",
            "## Full diff",
            full_diff or "(no diff)",
            "",
            "## Working tree / untracked files",
            status or "(clean)",
            "",
        ],
    )
    _print_review_completion(
        context,
        mode=mode,
        scope=scope,
        output_dir=output_path.parent,
        summary_path=output_path,
        all_in_one_path=output_path,
        stats=[],
        tree_count=1,
    )
    return 0


def resolve_git_root(project_root: Path, repo_root: Path) -> Path:
    for candidate in (project_root, repo_root):
        if (candidate / ".git").exists():
            return candidate
    return project_root


def probe_dirty_worktree(project_root: Path, repo_root: Path, *, project_name: str = "") -> DirtyWorktreeReport:
    git_root = resolve_git_root(project_root, repo_root)
    status_output = _git_output(git_root, ["status", "--porcelain", "--untracked-files=all"])
    staged, unstaged, untracked = _classify_dirty_porcelain(status_output)
    resolved_name = project_name.strip() or project_root.name or git_root.name or "project"
    return DirtyWorktreeReport(
        project_name=resolved_name,
        project_root=project_root,
        git_root=git_root,
        staged=staged,
        unstaged=unstaged,
        untracked=untracked,
    )


def _classify_dirty_porcelain(status_output: str) -> tuple[bool, bool, bool]:
    staged = False
    unstaged = False
    untracked = False
    for raw_line in str(status_output or "").splitlines():
        line = raw_line.rstrip("\n")
        if not line:
            continue
        if line.startswith("??"):
            untracked = True
            continue
        if len(line) < 2:
            continue
        index_status = line[0]
        worktree_status = line[1]
        if index_status not in {" ", "?"}:
            staged = True
        if worktree_status not in {" ", "?"}:
            unstaged = True
    return staged, unstaged, untracked


def detect_default_branch(git_root: Path) -> str:
    ref = _git_output(git_root, ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"]).strip()
    if ref.startswith("origin/"):
        return ref.split("origin/", 1)[1]
    for candidate in ("main", "master"):
        if _git_output(git_root, ["rev-parse", "--verify", candidate]).strip():
            return candidate
    return "main"


def existing_pr_url(git_root: Path, branch: str) -> str:
    branch_name = branch.strip()
    if not branch_name or branch_name in {"HEAD", "unknown"}:
        return ""
    gh_path = shutil.which("gh")
    if gh_path is None:
        return ""
    listed = subprocess.run(
        [gh_path, "pr", "list", "--head", branch_name, "--state", "open", "--json", "url", "--jq", ".[0].url"],
        cwd=str(git_root),
        text=True,
        capture_output=True,
        check=False,
    )
    if listed.returncode != 0:
        return ""
    return listed.stdout.strip()


def sanitize_label(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)
    return cleaned.strip("_") or "project"


def _resolve_original_plan(context: ActionProjectContext) -> OriginalPlanResolution:
    if context.project_root.resolve() == context.repo_root.resolve():
        return OriginalPlanResolution(path=None, source="not_applicable")

    provenance = _read_worktree_provenance(context.project_root)
    recorded_plan = str(provenance.get("plan_file", "")).strip()
    resolved = _resolve_plan_file_from_record(provenance_root=context.repo_root, recorded_plan=recorded_plan)
    if resolved is not None:
        return OriginalPlanResolution(path=resolved, source="provenance")

    inferred = _infer_original_plan_file(
        context.repo_root,
        feature_name=_feature_name_from_project_name(context.project_name),
    )
    if inferred is not None:
        return OriginalPlanResolution(path=inferred, source="feature_inference")
    return OriginalPlanResolution(path=None, source="unresolved")


def _read_worktree_provenance(project_root: Path) -> dict[str, object]:
    path = project_root / WORKTREE_PROVENANCE_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _resolve_plan_file_from_record(*, provenance_root: Path, recorded_plan: str) -> Path | None:
    normalized = str(recorded_plan or "").strip()
    if not normalized:
        return None
    relative = Path(normalized.replace("\\", "/").lstrip("./"))
    for root in (PLANNING_ROOT, DONE_PLANNING_ROOT):
        candidate = provenance_root / root / relative
        if candidate.is_file():
            return candidate.resolve()
    return None


def _infer_original_plan_file(repo_root: Path, *, feature_name: str) -> Path | None:
    normalized_feature = str(feature_name).strip()
    if not normalized_feature:
        return None
    matches: list[Path] = []
    for root in (PLANNING_ROOT, DONE_PLANNING_ROOT):
        planning_root = repo_root / root
        if not planning_root.is_dir():
            continue
        for candidate in sorted(planning_root.glob("*/*.md")):
            if candidate.name == "README.md":
                continue
            relative = candidate.relative_to(planning_root)
            if planning_feature_name(str(relative).replace("\\", "/")) != normalized_feature:
                continue
            matches.append(candidate.resolve())
    if len(matches) == 1:
        return matches[0]
    return None


def _feature_name_from_project_name(project_name: str) -> str:
    normalized = str(project_name).strip()
    return re.sub(r"-\d+$", "", normalized)


def _original_plan_markdown_lines(resolution: OriginalPlanResolution, *, include_contents: bool) -> list[str]:
    resolved_path = str(resolution.path) if resolution.path is not None else "(unresolved)"
    lines = [
        "## Original plan file",
        resolved_path,
        "",
        "## Original plan resolution",
        resolution.source,
        "",
    ]
    if include_contents:
        plan_text = _read_text(resolution.path) if resolution.path is not None else ""
        lines.extend(
            [
                "## Original plan",
                plan_text or "(unavailable)",
                "",
            ]
        )
    return lines


def _augment_review_output_dir(output_dir: Path, *, original_plan: OriginalPlanResolution) -> None:
    _augment_review_markdown_file(output_dir / "all.md", original_plan=original_plan, include_contents=True)
    _augment_review_markdown_file(output_dir / "summary.md", original_plan=original_plan, include_contents=False)


def _augment_review_markdown_file(path: Path, *, original_plan: OriginalPlanResolution, include_contents: bool) -> None:
    if not path.is_file():
        return
    original_text = _read_text(path)
    if not original_text:
        return
    if "## Original plan file" in original_text:
        return
    metadata_block = "\n".join(_original_plan_markdown_lines(original_plan, include_contents=include_contents)).strip()
    if not metadata_block:
        return
    lines = original_text.splitlines()
    if lines and lines[0].startswith("# "):
        title = lines[0]
        remainder = "\n".join(lines[1:]).strip()
        rewritten = f"{title}\n\n{metadata_block}\n\n{remainder}".rstrip() + "\n"
    else:
        rewritten = f"{metadata_block}\n\n{original_text.strip()}".rstrip() + "\n"
    _atomic_write(path, rewritten)


def _resolve_commit_message(
    context: ActionProjectContext,
    *,
    branch: str,
) -> tuple[str, str, str | None, Path | None]:
    commit_message = str(context.env.get("ENVCTL_COMMIT_MESSAGE", "")).strip()
    commit_message_file = str(context.env.get("ENVCTL_COMMIT_MESSAGE_FILE", "")).strip()
    if commit_message:
        return commit_message, "", None, None
    if commit_message_file:
        path = Path(commit_message_file)
        if path.is_file() and _file_has_text(path):
            return "", str(path), None, None
        return "", "", f"Commit message file is missing or empty: {commit_message_file}", None

    ledger_path = context.project_root / ENVCTL_COMMIT_LEDGER_NAME
    payload, error = _read_commit_ledger_segment(ledger_path)
    if error:
        return "", "", error, ledger_path
    return "", str(_write_commit_message_file(payload)), None, ledger_path


def _read_commit_ledger_segment(path: Path) -> tuple[str, str | None]:
    if not path.exists():
        _atomic_write(path, f"# Envctl Commit Log\n\n{ENVCTL_COMMIT_POINTER_MARKER}\n")

    text = _read_text(path)
    marker_count = text.count(ENVCTL_COMMIT_POINTER_MARKER)
    if marker_count == 0:
        payload = _normalize_text_block(text)
        if not payload:
            return "", (
                f"Envctl commit log is empty in {path}. Provide --commit-message, "
                f"--commit-message-file, or append a new summary to {path}."
            )
        return payload[:COMMIT_MESSAGE_MAX_CHARS].rstrip() or payload, None
    if marker_count > 1:
        return "", f"Envctl commit log is malformed: {path} contains multiple pointer markers."

    before, after = text.split(ENVCTL_COMMIT_POINTER_MARKER, 1)
    del before
    payload = _normalize_text_block(after)
    if not payload:
        return "", (
            f"Envctl commit log is empty after the pointer in {path}. Provide --commit-message, "
            f"--commit-message-file, or append a new summary to {path}."
        )
    return payload[:COMMIT_MESSAGE_MAX_CHARS].rstrip() or payload, None


def _advance_commit_ledger_pointer(path: Path) -> str | None:
    if not path.exists():
        return f"Envctl commit log disappeared before pointer advance: {path}"
    text = _read_text(path)
    marker_count = text.count(ENVCTL_COMMIT_POINTER_MARKER)
    if marker_count == 0:
        archived = _normalize_text_block(text)
        updated = f"{archived}\n\n{ENVCTL_COMMIT_POINTER_MARKER}\n" if archived else f"{ENVCTL_COMMIT_POINTER_MARKER}\n"
        try:
            _atomic_write(path, updated)
        except OSError as exc:
            return f"Failed to advance envctl commit log pointer in {path}: {exc}"
        return None
    if marker_count > 1:
        return f"Envctl commit log is malformed during pointer advance: {path} contains multiple pointer markers."
    before, after = text.split(ENVCTL_COMMIT_POINTER_MARKER, 1)
    archived_before = _normalize_text_block(before)
    payload = _normalize_text_block(after)
    parts = [part for part in (archived_before, payload) if part]
    archived = "\n\n".join(parts).strip()
    updated = f"{archived}\n\n{ENVCTL_COMMIT_POINTER_MARKER}\n" if archived else f"{ENVCTL_COMMIT_POINTER_MARKER}\n"
    try:
        _atomic_write(path, updated)
    except OSError as exc:
        return f"Failed to advance envctl commit log pointer in {path}: {exc}"
    return None


def _resolve_pr_base_branch(context: ActionProjectContext, git_root: Path) -> str:
    explicit = str(context.env.get("ENVCTL_PR_BASE", "")).strip()
    if explicit:
        return explicit
    return detect_default_branch(git_root)


def _resolve_analyze_mode(context: ActionProjectContext) -> str:
    explicit = str(context.env.get("ENVCTL_ANALYZE_MODE", "")).strip().lower()
    if explicit in {"single", "grouped"}:
        return explicit
    return "single"


def _resolve_review_base(context: ActionProjectContext, git_root: Path) -> ReviewBaseResolution:
    explicit = str(context.env.get("ENVCTL_REVIEW_BASE", "")).strip()
    if explicit:
        resolved = _resolve_review_base_candidate(git_root, base_branch=explicit, source="explicit")
        if resolved is None:
            raise ReviewBaseResolutionError(
                f"Review base '{explicit}' could not be resolved. "
                + "Supply --review-base <branch> with an existing branch."
            )
        return resolved

    if context.project_root.resolve() != context.repo_root.resolve():
        provenance = _load_worktree_provenance(context.project_root)
        resolved = _resolve_provenance_review_base(git_root, provenance)
        if resolved is not None:
            return resolved

    resolved = _resolve_upstream_review_base(git_root)
    if resolved is not None:
        return resolved

    default_branch = detect_default_branch(git_root).strip()
    resolved = _resolve_review_base_candidate(git_root, base_branch=default_branch, source="default_branch")
    if resolved is not None:
        return resolved
    raise ReviewBaseResolutionError(
        "Unable to resolve a review base automatically. Supply --review-base <branch>."
    )


def _resolve_provenance_review_base(
    git_root: Path,
    provenance: Mapping[str, object] | None,
) -> ReviewBaseResolution | None:
    if not provenance:
        return None
    source_branch = str(provenance.get("source_branch", "")).strip()
    source_ref = str(provenance.get("source_ref", "")).strip()
    if source_branch:
        return _resolve_review_base_candidate(
            git_root,
            base_branch=source_branch,
            source="provenance",
            preferred_ref=source_ref,
        )
    if source_ref:
        return _resolve_review_base_candidate(
            git_root,
            base_branch=_branch_name_from_ref(source_ref),
            source="provenance",
            preferred_ref=source_ref,
        )
    return None


def _resolve_upstream_review_base(git_root: Path) -> ReviewBaseResolution | None:
    head_branch = _git_output(git_root, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
    if not head_branch or head_branch == "HEAD":
        return None
    upstream_ref = _git_output(git_root, ["rev-parse", "--abbrev-ref", f"{head_branch}@{{upstream}}"]).strip()
    if not upstream_ref or upstream_ref == "HEAD":
        return None
    return _resolve_review_base_candidate(
        git_root,
        base_branch=_branch_name_from_ref(upstream_ref),
        source="upstream",
        preferred_ref=upstream_ref,
    )


def _resolve_review_base_candidate(
    git_root: Path,
    *,
    base_branch: str,
    source: str,
    preferred_ref: str = "",
) -> ReviewBaseResolution | None:
    normalized_branch = _branch_name_from_ref(base_branch)
    base_ref = _resolve_review_base_ref(git_root, base_branch=base_branch, preferred_ref=preferred_ref)
    if not base_ref:
        return None
    merge_base = _git_output(git_root, ["merge-base", "HEAD", base_ref]).strip()
    return ReviewBaseResolution(
        base_branch=normalized_branch or base_branch.strip(),
        base_ref=base_ref,
        source=source,
        merge_base=merge_base,
    )


def _resolve_review_base_ref(git_root: Path, *, base_branch: str, preferred_ref: str = "") -> str:
    branch = base_branch.strip()
    candidates: list[str] = []
    for candidate in (
        preferred_ref.strip(),
        branch,
        "" if not branch or branch.startswith("origin/") else f"origin/{branch}",
        "" if not branch.startswith("origin/") else branch.split("origin/", 1)[1],
    ):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    for candidate in candidates:
        if _git_output(git_root, ["rev-parse", "--verify", candidate]).strip():
            return candidate
    return ""


def _branch_name_from_ref(ref: str) -> str:
    cleaned = ref.strip()
    if cleaned.startswith("origin/"):
        return cleaned.split("origin/", 1)[1]
    return cleaned


def _load_worktree_provenance(project_root: Path) -> Mapping[str, object] | None:
    path = project_root / WORKTREE_PROVENANCE_PATH
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(loaded, dict):
        return None
    schema_version = int(loaded.get("schema_version", 0) or 0)
    if schema_version > WORKTREE_PROVENANCE_SCHEMA_VERSION:
        return None
    return loaded


def _write_commit_message_file(message: str) -> Path:
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        delete=False,
        suffix=".envctl-commit-message.txt",
    ) as handle:
        handle.write(message)
        return Path(handle.name)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        Path(temp_name).replace(path)
    finally:
        try:
            if Path(temp_name).exists():
                Path(temp_name).unlink()
        except OSError:
            pass


def _analysis_iterations(context: ActionProjectContext, *, mode: str) -> list[str]:
    project_root = context.project_root.resolve()
    if project_root == context.repo_root.resolve():
        return []
    family_dir = _project_family_dir(project_root)
    if family_dir is None:
        return []

    iterations = _git_iteration_dirs(family_dir)
    if not iterations:
        return []
    if mode == "single":
        current_name = project_root.name
        if current_name in iterations:
            return [current_name]
        return [iterations[0]]
    return iterations


def _project_family_dir(project_root: Path) -> Path | None:
    parent = project_root.parent
    if parent == project_root:
        return None
    if project_root.name.isdigit() and parent.is_dir():
        return parent
    child_git_dirs = _git_iteration_dirs(parent)
    if child_git_dirs:
        return parent
    return None


def _git_iteration_dirs(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    iterations: list[str] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        git_marker = child / ".git"
        if git_marker.is_file() or git_marker.is_dir():
            iterations.append(child.name)
    return iterations


def _run_analyze_helper(
    *,
    context: ActionProjectContext,
    helper: Path,
    iterations: list[str],
    mode: str,
    scope: str,
    review_base: ReviewBaseResolution | None,
    original_plan: OriginalPlanResolution,
) -> int:
    project_root = context.project_root.resolve()
    family_dir = _project_family_dir(project_root)
    if family_dir is None:
        return 1

    approach = "combine" if mode == "grouped" and len(iterations) > 1 else "optimal"
    output_dir = _tree_diffs_root(context) / (
        f"analysis_{sanitize_label(context.project_name)}_{sanitize_label(scope)}_{mode}_"
        f"{datetime.now(tz=UTC).strftime('%Y%m%d_%H%M%S')}"
    )
    args = [
        f"trees={','.join(iterations)}",
        f"approach={approach}",
        "output-dir=" + str(output_dir),
    ]
    if review_base is not None:
        args.extend(
            [
                f"base-branch={review_base.base_branch}",
                f"base-source={review_base.source}",
                f"base-ref={review_base.base_ref}",
            ]
        )
    if scope != "all":
        args.append(f"scope={scope}")
    if not (mode == "grouped" and len(iterations) > 1):
        args.extend(["security-check=true", "performance-check=true"])

    env_map = dict(os.environ)
    env_map.update(context.env)
    env_map["BASE_DIR"] = str(context.repo_root)
    env_map["TREES_DIR_NAME"] = str(family_dir)
    if original_plan.path is not None:
        env_map["ENVCTL_REVIEW_ORIGINAL_PLAN_FILE"] = str(original_plan.path)
    env_map["ENVCTL_REVIEW_ORIGINAL_PLAN_SOURCE"] = original_plan.source

    result = subprocess.run(
        [str(helper), *args],
        cwd=str(context.repo_root),
        env=env_map,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        _augment_review_output_dir(output_dir, original_plan=original_plan)
        short_summary_path = output_dir / "summary_short.txt"
        stats = _parse_review_stats(short_summary_path)
        _prune_review_output_dir(output_dir, keep_names={"summary.md", "all.md"})
        _print_review_completion(
            context,
            mode=mode,
            scope=scope,
            output_dir=output_dir,
            summary_path=_first_existing_path(output_dir / "summary.md", output_dir / "all.md"),
            all_in_one_path=output_dir / "all.md",
            stats=stats,
            tree_count=len(iterations),
        )
    else:
        _print_review_failure(
            context,
            output_dir=output_dir,
            result=result,
        )
    return result.returncode


def _tree_changelog_path(context: ActionProjectContext) -> Path | None:
    tree_name = "main" if context.project_name.strip().lower() == "main" else context.project_name.strip()
    candidate = context.project_root / "docs" / "changelog" / f"{sanitize_label(tree_name)}_changelog.md"
    if candidate.is_file() and _file_has_text(candidate):
        return candidate
    return None


def _file_has_text(path: Path) -> bool:
    try:
        return bool(path.read_text(encoding="utf-8").strip())
    except OSError:
        return False


def _summary_output_path(repo_root: Path, directory: str, prefix: str, label: str | None = None) -> Path:
    output_dir = repo_root / directory
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    if label:
        return output_dir / f"{prefix}_{sanitize_label(label)}_{timestamp}.md"
    return output_dir / f"{prefix}_{timestamp}.md"


def _tree_diffs_root(context: ActionProjectContext) -> Path:
    explicit = str(context.env.get("ENVCTL_ACTION_TREE_DIFFS_ROOT", "")).strip()
    if explicit:
        root = Path(explicit).expanduser()
    else:
        repo_hash = hashlib.sha256(str(context.repo_root.resolve()).encode("utf-8")).hexdigest()[:12]
        root = Path(tempfile.gettempdir()) / "envctl-tree-diffs" / repo_hash
    root.mkdir(parents=True, exist_ok=True)
    return root


def _tree_diffs_output_path(
    context: ActionProjectContext,
    directory: str,
    prefix: str,
    label: str | None = None,
) -> Path:
    output_dir = _tree_diffs_root(context) / directory
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    if label:
        return output_dir / f"{prefix}_{sanitize_label(label)}_{timestamp}.md"
    return output_dir / f"{prefix}_{timestamp}.md"


def _write_markdown_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines), encoding="utf-8")


def _run_git(git_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(git_root), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def _git_output(git_root: Path, args: list[str]) -> str:
    result = _run_git(git_root, args)
    if result.returncode != 0:
        return ""
    return result.stdout


def _print_process_output(result: subprocess.CompletedProcess[str]) -> None:
    stdout = str(result.stdout or "").strip()
    stderr = str(result.stderr or "").strip()
    if stdout:
        print(stdout)
    if result.returncode != 0 and stderr:
        print(stderr)


def _first_existing_path(*paths: Path) -> Path:
    for path in paths:
        if path.is_file():
            return path
    return paths[0]


def _print_error(prefix: str, result: subprocess.CompletedProcess[str]) -> None:
    output = result.stderr or result.stdout or f"exit:{result.returncode}"
    print(f"{prefix}: {output}")
