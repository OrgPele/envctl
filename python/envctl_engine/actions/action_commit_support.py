from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Callable

from envctl_engine.actions.action_protected_artifacts import EnvctlProtectedPathPartition
from envctl_engine.actions.action_pr_message_support import normalize_text_block, read_text
from envctl_engine.ui.path_links import render_paths_in_terminal_text


COMMIT_MESSAGE_MAX_CHARS = 16_000
ENVCTL_COMMIT_LEDGER_NAME = ".envctl-commit-message.md"
ENVCTL_COMMIT_POINTER_MARKER = "### Envctl pointer ###"

RunGitFn = Callable[[Path, list[str]], subprocess.CompletedProcess[str]]
GitOutputFn = Callable[[Path, list[str]], str]
PrintErrorFn = Callable[[str, subprocess.CompletedProcess[str]], None]
ResolveGitRootFn = Callable[[Path, Path], Path]
PartitionProtectedPathsFn = Callable[[str], EnvctlProtectedPathPartition]
OrderedUniquePathsFn = Callable[..., list[str]]


def run_commit_workflow(
    context: Any,
    *,
    resolve_git_root: ResolveGitRootFn,
    git_available: bool,
    git_output: GitOutputFn,
    run_git: RunGitFn,
    print_error: PrintErrorFn,
    partition_envctl_protected_paths: PartitionProtectedPathsFn,
    ordered_unique_paths: OrderedUniquePathsFn,
) -> int:
    git_root = resolve_git_root(context.project_root, context.repo_root)
    if not git_available:
        print("git is required for commit action")
        return 1

    branch = git_output(git_root, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
    if not branch or branch == "HEAD":
        print(f"Skipping {context.project_name} (detached HEAD).")
        return 0

    pre_stage_status = run_git(git_root, ["status", "--porcelain", "--untracked-files=all"])
    if pre_stage_status.returncode != 0:
        print_error("git status failed", pre_stage_status)
        return 1
    partition = partition_envctl_protected_paths(pre_stage_status.stdout)
    unstaged_protected_paths: list[str] = []
    if partition.protected_staged_paths:
        reset = unstage_envctl_protected_paths(git_root, partition.protected_staged_paths, run_git=run_git)
        if reset.returncode != 0:
            print_error("git reset protected envctl-local artifacts failed", reset)
            print("Protected envctl-local artifacts still staged: " + ", ".join(partition.protected_staged_paths))
            return 1
        unstaged_protected_paths = list(partition.protected_staged_paths)
        print("Unstaged envctl-local artifacts: " + ", ".join(unstaged_protected_paths))

        refreshed_status = run_git(git_root, ["status", "--porcelain", "--untracked-files=all"])
        if refreshed_status.returncode != 0:
            print_error("git status failed", refreshed_status)
            return 1
        partition = partition_envctl_protected_paths(refreshed_status.stdout)
        if partition.protected_staged_paths:
            print(
                "Protected envctl-local artifacts remain staged after recovery: "
                + ", ".join(partition.protected_staged_paths)
            )
            return 1

    if partition.stageable_paths:
        add = run_git(git_root, ["add", "--", *partition.stageable_paths])
        if add.returncode != 0:
            print_error("git add failed", add)
            return 1
    protected_paths = ordered_unique_paths(unstaged_protected_paths, partition.protected_skipped_paths)
    if protected_paths:
        print("Skipping envctl-local artifacts: " + ", ".join(protected_paths))

    status = run_git(git_root, ["status", "--porcelain"])
    if status.returncode != 0:
        print_error("git status failed", status)
        return 1
    commit_partition = partition_envctl_protected_paths(status.stdout)
    if commit_partition.protected_staged_paths:
        print(
            "Protected envctl-local artifacts remain staged after recovery: "
            + ", ".join(commit_partition.protected_staged_paths)
        )
        return 1
    if not commit_partition.stageable_paths:
        print(f"No changes to commit for {branch}.")
        return 0

    commit_message, message_file, error, ledger_path = resolve_commit_message(context, branch=branch)
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
            commit = run_git(git_root, ["commit", "-F", message_file])
        else:
            commit = run_git(git_root, ["commit", "-m", commit_message])
    finally:
        if generated_message_file:
            try:
                Path(message_file).unlink()
            except OSError:
                pass
    if commit.returncode != 0:
        print_error("git commit failed", commit)
        return 1

    if ledger_path is not None:
        advance_error = advance_commit_ledger_pointer(ledger_path)
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
    push = run_git(git_root, ["push", "-u", remote, branch])
    if push.returncode != 0:
        print_error("git push failed", push)
        return 1

    print(f"Committed and pushed changes for {context.project_name} ({branch}).")
    return 0


def unstage_envctl_protected_paths(
    git_root: Path,
    paths: list[str],
    *,
    run_git: RunGitFn,
) -> subprocess.CompletedProcess[str]:
    return run_git(git_root, ["reset", "-q", "--", *paths])


def resolve_commit_message(context: Any, *, branch: str) -> tuple[str, str, str | None, Path | None]:
    del branch
    commit_message = str(context.env.get("ENVCTL_COMMIT_MESSAGE", "")).strip()
    commit_message_file = str(context.env.get("ENVCTL_COMMIT_MESSAGE_FILE", "")).strip()
    if commit_message:
        return commit_message, "", None, None
    if commit_message_file:
        path = Path(commit_message_file)
        if path.is_file() and file_has_text(path):
            return "", str(path), None, None
        return "", "", f"Commit message file is missing or empty: {commit_message_file}", None

    ledger_path = context.project_root / ENVCTL_COMMIT_LEDGER_NAME
    payload, error = read_commit_ledger_segment(ledger_path)
    if error:
        return "", "", error, ledger_path
    return "", str(write_commit_message_file(payload)), None, ledger_path


def read_commit_ledger_segment(path: Path) -> tuple[str, str | None]:
    if not path.exists():
        atomic_write(path, f"# Envctl Commit Log\n\n{ENVCTL_COMMIT_POINTER_MARKER}\n")

    text = read_text(path)
    marker_count = text.count(ENVCTL_COMMIT_POINTER_MARKER)
    if marker_count == 0:
        payload = normalize_text_block(text)
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
    payload = normalize_text_block(after)
    if not payload:
        return "", (
            f"Envctl commit log is empty after the pointer in {path}. Provide --commit-message, "
            f"--commit-message-file, or append a new summary to {path}."
        )
    return payload[:COMMIT_MESSAGE_MAX_CHARS].rstrip() or payload, None


def advance_commit_ledger_pointer(path: Path) -> str | None:
    if not path.exists():
        return f"Envctl commit log disappeared before pointer advance: {path}"
    text = read_text(path)
    marker_count = text.count(ENVCTL_COMMIT_POINTER_MARKER)
    if marker_count == 0:
        archived = normalize_text_block(text)
        updated = f"{archived}\n\n{ENVCTL_COMMIT_POINTER_MARKER}\n" if archived else f"{ENVCTL_COMMIT_POINTER_MARKER}\n"
        try:
            atomic_write(path, updated)
        except OSError as exc:
            return f"Failed to advance envctl commit log pointer in {path}: {exc}"
        return None
    if marker_count > 1:
        return f"Envctl commit log is malformed during pointer advance: {path} contains multiple pointer markers."
    before, after = text.split(ENVCTL_COMMIT_POINTER_MARKER, 1)
    archived_before = normalize_text_block(before)
    payload = normalize_text_block(after)
    parts = [part for part in (archived_before, payload) if part]
    archived = "\n\n".join(parts).strip()
    updated = f"{archived}\n\n{ENVCTL_COMMIT_POINTER_MARKER}\n" if archived else f"{ENVCTL_COMMIT_POINTER_MARKER}\n"
    try:
        atomic_write(path, updated)
    except OSError as exc:
        return f"Failed to advance envctl commit log pointer in {path}: {exc}"
    return None


def write_commit_message_file(message: str) -> Path:
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        delete=False,
        suffix=".envctl-commit-message.txt",
    ) as handle:
        handle.write(message)
        return Path(handle.name)


def atomic_write(path: Path, text: str) -> None:
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


def file_has_text(path: Path) -> bool:
    try:
        return bool(path.read_text(encoding="utf-8").strip())
    except OSError:
        return False
