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
from typing import Mapping

from envctl_engine.shared.parsing import parse_bool
from envctl_engine.ui.color_policy import colors_enabled
from envctl_engine.ui.path_links import (
    normalize_local_path_text,
    render_path_for_terminal,
    render_paths_in_terminal_text,
    rich_path_text,
)

PR_BODY_MAX_CHARS = 48_000
PR_TITLE_MAX_CHARS = 240
COMMIT_MESSAGE_MAX_CHARS = 16_000
WORKTREE_PROVENANCE_SCHEMA_VERSION = 1
WORKTREE_PROVENANCE_PATH = Path(".envctl-state") / "worktree-provenance.json"
ENVCTL_COMMIT_LEDGER_NAME = ".envctl-commit-message.md"
ENVCTL_COMMIT_POINTER_MARKER = "### Envctl pointer ###"


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

    add = _run_git(git_root, ["add", "-A"])
    if add.returncode != 0:
        _print_error("git add failed", add)
        return 1

    status = _run_git(git_root, ["status", "--porcelain"])
    if status.returncode != 0:
        _print_error("git status failed", status)
        return 1
    if not status.stdout.strip():
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


def run_review_action(context: ActionProjectContext) -> int:
    git_root = resolve_git_root(context.project_root, context.repo_root)
    if shutil.which("git") is None:
        print("git is required for review action")
        return 1

    mode = _resolve_analyze_mode(context)
    scope = str(context.env.get("ENVCTL_ANALYZE_SCOPE", "all")).strip().lower() or "all"
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
        return "", (
            f"Envctl commit log is malformed: {path} is missing the required pointer marker "
            f"'{ENVCTL_COMMIT_POINTER_MARKER}'."
        )
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
        return f"Envctl commit log is malformed during pointer advance: {path} is missing the required pointer marker."
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
                f"Review base '{explicit}' could not be resolved. Supply --review-base <branch> with an existing branch."
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


def _pr_title(context: ActionProjectContext, git_root: Path, head_branch: str) -> str:
    explicit = _normalize_title_text(str(context.env.get("ENVCTL_PR_TITLE", "")))
    if explicit:
        return explicit[:PR_TITLE_MAX_CHARS].rstrip() or head_branch
    main_task_title = _main_task_title(context.project_root)
    if main_task_title:
        return main_task_title[:PR_TITLE_MAX_CHARS].rstrip() or head_branch
    subject = _git_output(git_root, ["log", "-1", "--pretty=%s"]).strip()
    title = subject or f"{context.project_name}: {head_branch}"
    title = " ".join(title.split())
    return title[:PR_TITLE_MAX_CHARS].rstrip() or head_branch


def _pr_body(context: ActionProjectContext, git_root: Path, head_branch: str, base_branch: str) -> str:
    explicit_body = _normalize_text_block(str(context.env.get("ENVCTL_PR_BODY", "")))
    if explicit_body:
        return _truncate_pr_body(explicit_body, max_chars=PR_BODY_MAX_CHARS)

    main_task = context.project_root / "MAIN_TASK.md"
    if main_task.is_file() and _file_has_text(main_task):
        return _truncate_pr_body(_read_text(main_task), max_chars=PR_BODY_MAX_CHARS)

    commits = _pr_commit_messages(git_root, head_branch=head_branch, base_branch=base_branch)
    if commits:
        return _truncate_pr_body(commits, max_chars=PR_BODY_MAX_CHARS)
    return ""


def _pr_commit_messages(git_root: Path, *, head_branch: str, base_branch: str) -> str:
    range_spec = _pr_commit_range(git_root, head_branch=head_branch, base_branch=base_branch)
    raw = _git_output(git_root, ["log", "--reverse", "--no-merges", "--format=%h%x1f%s%x1f%b%x1e", range_spec])
    entries: list[str] = []
    for chunk in raw.split("\x1e"):
        normalized = chunk.strip()
        if not normalized:
            continue
        parts = normalized.split("\x1f", 2)
        short_hash = parts[0].strip() if len(parts) > 0 else ""
        subject = " ".join((parts[1] if len(parts) > 1 else "").split()).strip()
        body = _normalize_text_block(parts[2] if len(parts) > 2 else "")
        if not short_hash and not subject and not body:
            continue
        header = f"- {subject or short_hash}"
        if short_hash and subject:
            header = f"- {subject} ({short_hash})"
        entry_lines = [header]
        if body:
            entry_lines.append("")
            entry_lines.extend(f"  {line}" if line else "" for line in body.splitlines())
        entries.append("\n".join(entry_lines).strip())
    if not entries:
        return ""
    return _truncate_recent_entries(
        entries, max_chars=PR_BODY_MAX_CHARS - 8_000, notice="[truncated to most recent commit messages]"
    )


def _pr_diff_stat(git_root: Path, *, head_branch: str, base_branch: str) -> str:
    diff_args = ["diff", "--stat"]
    if base_branch:
        diff_args.append(_pr_compare_range(git_root, head_branch=head_branch, base_branch=base_branch))
    diff_stat = _git_output(git_root, diff_args).strip()
    return _truncate_pr_body(diff_stat, max_chars=8_000) if diff_stat else ""


def _pr_commit_range(git_root: Path, *, head_branch: str, base_branch: str) -> str:
    head_ref = head_branch or "HEAD"
    if not base_branch:
        return head_ref
    base_ref = _pr_base_ref(git_root, base_branch)
    merge_base = _git_output(git_root, ["merge-base", head_ref, base_ref]).strip()
    if merge_base:
        return f"{merge_base}..{head_ref}"
    return f"{base_ref}..{head_ref}"


def _pr_compare_range(git_root: Path, *, head_branch: str, base_branch: str) -> str:
    head_ref = head_branch or "HEAD"
    if not base_branch:
        return head_ref
    base_ref = _pr_base_ref(git_root, base_branch)
    return f"{base_ref}...{head_ref}"


def _pr_base_ref(git_root: Path, base_branch: str) -> str:
    remote_candidate = f"origin/{base_branch}"
    if _git_output(git_root, ["rev-parse", "--verify", remote_candidate]).strip():
        return remote_candidate
    if _git_output(git_root, ["rev-parse", "--verify", base_branch]).strip():
        return base_branch
    return base_branch


def _recent_text_excerpt(text: str, *, max_chars: int) -> str:
    cleaned = _normalize_text_block(text)
    if len(cleaned) <= max_chars:
        return cleaned
    notice = "[truncated to most recent changelog content]\n\n"
    tail_limit = max(0, max_chars - len(notice))
    tail = cleaned[-tail_limit:] if tail_limit else ""
    if "\n" in tail:
        tail = tail.split("\n", 1)[1]
    return f"{notice}{tail}".strip()


def _truncate_recent_entries(entries: list[str], *, max_chars: int, notice: str) -> str:
    cleaned_entries = [entry.strip() for entry in entries if entry.strip()]
    if not cleaned_entries:
        return ""
    full_text = "\n\n".join(cleaned_entries).strip()
    if len(full_text) <= max_chars:
        return full_text
    notice_block = f"{notice}\n\n"
    keep_limit = max(0, max_chars - len(notice_block))
    kept: list[str] = []
    current_len = 0
    for entry in reversed(cleaned_entries):
        extra = len(entry) + (2 if kept else 0)
        if current_len + extra > keep_limit:
            break
        kept.append(entry)
        current_len += extra
    if not kept:
        tail = full_text[-keep_limit:] if keep_limit else ""
        if "\n" in tail:
            tail = tail.split("\n", 1)[1]
        return f"{notice_block}{tail}".strip()
    kept.reverse()
    return f"{notice_block}{'\n\n'.join(kept)}".strip()


def _latest_changelog_commit_message(text: str, *, max_chars: int) -> str:
    normalized = _normalize_text_block(text)
    if not normalized:
        return ""
    lines = normalized.splitlines()
    latest_heading = ""
    section_lines: list[str] = []
    inside_latest_section = False
    for line in lines:
        if line.startswith("## "):
            if inside_latest_section:
                break
            latest_heading = line[3:].strip()
            inside_latest_section = True
            continue
        if inside_latest_section:
            section_lines.append(line)
    if not inside_latest_section:
        return _truncate_pr_body(normalized, max_chars=max_chars)
    body = _normalize_text_block("\n".join(section_lines))
    if body:
        subject, remainder = _select_changelog_subject(body, fallback=latest_heading)
        if not subject:
            subject = latest_heading
        commit_message = subject if not remainder else f"{subject}\n\n{remainder}"
        return _truncate_pr_body(commit_message, max_chars=max_chars)
    if latest_heading:
        return _truncate_pr_body(latest_heading, max_chars=max_chars)
    return ""


def _select_changelog_subject(body: str, *, fallback: str) -> tuple[str, str]:
    lines = body.splitlines()
    subject_index = -1
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue
        if re.match(r"^#{1,6}\s+", line):
            continue
        subject_index = index
        break
    if subject_index == -1:
        return fallback.strip(), ""
    subject = lines[subject_index].strip()
    remainder = "\n".join(lines[subject_index + 1 :]).strip()
    return subject, remainder


def _main_task_title(project_root: Path) -> str:
    main_task = project_root / "MAIN_TASK.md"
    if not main_task.is_file():
        return ""
    text = _read_text(main_task)
    if not text.strip():
        return ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("# "):
            continue
        return _normalize_title_text(line[2:])
    return ""


def _normalize_title_text(text: str) -> str:
    cleaned = text.replace("`", " ")
    cleaned = " ".join(cleaned.split())
    return cleaned.strip()


def _truncate_pr_body(text: str, *, max_chars: int) -> str:
    cleaned = _normalize_text_block(text)
    if len(cleaned) <= max_chars:
        return cleaned
    notice = "\n\n[truncated]"
    keep = max(0, max_chars - len(notice))
    return f"{cleaned[:keep].rstrip()}{notice}".strip()


def _normalize_text_block(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = [line.rstrip() for line in normalized.splitlines()]
    return "\n".join(lines).strip()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _write_pr_body_file(body: str) -> Path:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".md") as handle:
        handle.write(body)
        return Path(handle.name)


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

    result = subprocess.run(
        [str(helper), *args],
        cwd=str(context.repo_root),
        env=env_map,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
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


def _print_review_completion(
    context: ActionProjectContext,
    *,
    mode: str,
    scope: str,
    output_dir: Path,
    summary_path: Path,
    all_in_one_path: Path,
    stats: list[tuple[str, str]],
    tree_count: int,
) -> None:
    if parse_bool(context.env.get("ENVCTL_ACTION_FORCE_RICH"), False):
        if _print_review_completion_rich(
            context,
            mode=mode,
            scope=scope,
            output_dir=output_dir,
            summary_path=summary_path,
            all_in_one_path=all_in_one_path,
            stats=stats,
            tree_count=tree_count,
        ):
            return
    color = _review_colorizer(context)
    print(color(f"Review Ready: {context.project_name}", fg="cyan", bold=True))
    print(f"  Mode: {mode}")
    print(f"  Scope: {scope}")
    print(f"  Trees: {tree_count}")
    print()
    print(color("  Output directory", fg="blue", bold=True))
    print(f"    {_display_path(output_dir, env=context.env)}")
    print(color("  Summary file", fg="blue", bold=True))
    print(f"    {_display_path(summary_path, env=context.env)}")
    print(color("  Full review bundle", fg="blue", bold=True))
    print(f"    {_display_path(all_in_one_path, env=context.env)}")
    if stats:
        print()
        print(color("  Quick stats", fg="green", bold=True))
        for label, value in stats:
            print(f"    {label}: {value}")

    print()
    print(color("  Next steps", fg="green", bold=True))
    print("    1. Start with the summary file.")
    print("    2. Open the full review when you need the complete context.")


def _print_review_completion_rich(
    context: ActionProjectContext,
    *,
    mode: str,
    scope: str,
    output_dir: Path,
    summary_path: Path,
    all_in_one_path: Path,
    stats: list[tuple[str, str]],
    tree_count: int,
) -> bool:
    force_rich = parse_bool(context.env.get("ENVCTL_ACTION_FORCE_RICH"), False)
    if not force_rich:
        return False
    try:
        from rich import box
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text
    except Exception:
        return False

    console = Console(
        file=sys.stdout,
        no_color=not colors_enabled(context.env, stream=sys.stdout, interactive_tty=force_rich or sys.stdout.isatty()),
        force_terminal=True,
    )

    details = Table.grid(padding=(0, 1))
    details.add_column(style="bold")
    details.add_column()
    details.add_row("Mode", mode)
    details.add_row("Scope", scope)
    details.add_row("Trees", str(tree_count))
    link_tty = force_rich or sys.stdout.isatty()
    details.add_row(
        "Output",
        rich_path_text(output_dir, text_cls=Text, env=context.env, stream=sys.stdout, interactive_tty=link_tty),
    )
    details.add_row(
        "Summary",
        rich_path_text(summary_path, text_cls=Text, env=context.env, stream=sys.stdout, interactive_tty=link_tty),
    )
    details.add_row(
        "Bundle",
        rich_path_text(all_in_one_path, text_cls=Text, env=context.env, stream=sys.stdout, interactive_tty=link_tty),
    )
    for label, value in stats:
        details.add_row(label, value)

    steps = Table.grid(padding=(0, 1))
    steps.add_column(width=3, style="bold")
    steps.add_column()
    steps.add_row("1.", "Start with the summary file.")
    steps.add_row("2.", "Open the full review when you need the complete context.")

    title = Text.assemble(("Review Ready", "bold"), (": ", "bold"), (context.project_name, "cyan"))
    body = Table.grid(padding=(1, 0))
    body.add_row(details)
    body.add_row(Text(""))
    body.add_row(Text("Next steps", style="bold"))
    body.add_row(steps)
    console.print(Panel(body, title=title, box=box.ROUNDED, expand=True))
    return True


def _print_review_failure(
    context: ActionProjectContext,
    *,
    output_dir: Path,
    result: subprocess.CompletedProcess[str],
) -> None:
    color = _review_colorizer(context)
    print(color(f"Review failed: {context.project_name}", fg="red", bold=True))
    print(color("  Output directory", fg="blue", bold=True))
    print(f"    {_display_path(output_dir, env=context.env)}")
    stderr = str(result.stderr or "").strip()
    stdout = str(result.stdout or "").strip()
    details = stderr or stdout or f"exit:{result.returncode}"
    print(f"  Details: {details}")


def _parse_review_stats(summary_short_path: Path | None) -> list[tuple[str, str]]:
    if summary_short_path is None or not summary_short_path.is_file():
        return []
    wanted = {
        "Trees analyzed": "Trees analyzed",
        "Base branch": "Base branch",
        "Trees with changes": "Trees with changes",
        "Trees with no changes": "Trees with no changes",
    }
    rows: list[tuple[str, str]] = []
    try:
        for raw in summary_short_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if ":" not in line:
                continue
            key, value = [part.strip() for part in line.split(":", 1)]
            if key in wanted and value:
                rows.append((wanted[key], value))
    except OSError:
        return []
    return rows


def _prune_review_output_dir(output_dir: Path, *, keep_names: set[str]) -> None:
    for child in list(output_dir.iterdir()):
        if child.name in keep_names:
            continue
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
            continue
        try:
            child.unlink()
        except OSError:
            continue


def _review_colorizer(context: ActionProjectContext):
    enabled = colors_enabled(context.env, stream=sys.stdout, interactive_tty=context.interactive)

    def colorize(text: str, *, fg: str | None = None, bold: bool = False) -> str:
        if not enabled:
            return text
        palette = {
            "red": "31",
            "green": "32",
            "yellow": "33",
            "blue": "34",
            "magenta": "35",
            "cyan": "36",
            "gray": "90",
        }
        codes: list[str] = []
        if bold:
            codes.append("1")
        if fg is not None and fg in palette:
            codes.append(palette[fg])
        if not codes:
            return text
        return f"\x1b[{';'.join(codes)}m{text}\x1b[0m"

    return colorize


def _display_path(path: Path, *, env: Mapping[str, str] | None = None) -> str:
    return render_path_for_terminal(normalize_local_path_text(path), env=env, stream=sys.stdout)


def _print_error(prefix: str, result: subprocess.CompletedProcess[str]) -> None:
    output = result.stderr or result.stdout or f"exit:{result.returncode}"
    print(f"{prefix}: {output}")
