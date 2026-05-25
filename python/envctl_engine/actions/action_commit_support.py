from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class CommitWorkflowDependencies:
    resolve_git_root: ResolveGitRootFn
    git_available: bool
    git_output: GitOutputFn
    run_git: RunGitFn
    print_error: PrintErrorFn
    partition_envctl_protected_paths: PartitionProtectedPathsFn
    ordered_unique_paths: OrderedUniquePathsFn


@dataclass(frozen=True, slots=True)
class CommitWorkflowRunner:
    context: Any
    dependencies: CommitWorkflowDependencies

    def execute(self) -> int:
        git_root = self.dependencies.resolve_git_root(self.context.project_root, self.context.repo_root)
        if not self.dependencies.git_available:
            return self._missing_git()

        branch = self._current_branch(git_root)
        if not branch or branch == "HEAD":
            print(f"Skipping {self.context.project_name} (detached HEAD).")
            return 0

        stage_result = self._stage_commit_candidates(git_root)
        if stage_result is None:
            return 1

        commit_partition = self._commit_partition(git_root)
        if commit_partition is None:
            return 1
        if not commit_partition.stageable_paths:
            print(f"No changes to commit for {branch}.")
            return 0

        commit_result = self._commit_staged_changes(git_root, branch)
        if commit_result != 0:
            return commit_result

        return self._push(git_root, branch)

    @staticmethod
    def _missing_git() -> int:
        print("git is required for commit action")
        return 1

    def _current_branch(self, git_root: Path) -> str:
        return self.dependencies.git_output(git_root, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()

    def _stage_commit_candidates(self, git_root: Path) -> EnvctlProtectedPathPartition | None:
        pre_stage_status = self.dependencies.run_git(git_root, ["status", "--porcelain", "--untracked-files=all"])
        if pre_stage_status.returncode != 0:
            self.dependencies.print_error("git status failed", pre_stage_status)
            return None

        partition = self.dependencies.partition_envctl_protected_paths(pre_stage_status.stdout)
        unstaged_protected_paths = self._unstage_protected_paths(git_root, partition)
        if unstaged_protected_paths is None:
            return None
        if unstaged_protected_paths:
            refreshed_partition = self._refreshed_partition_after_unstage(git_root)
            if refreshed_partition is None:
                return None
            partition = refreshed_partition

        if not self._stage_paths(git_root, partition.stageable_paths):
            return None
        self._print_skipped_protected_paths(unstaged_protected_paths, partition.protected_skipped_paths)
        return partition

    def _unstage_protected_paths(
        self,
        git_root: Path,
        partition: EnvctlProtectedPathPartition,
    ) -> list[str] | None:
        if not partition.protected_staged_paths:
            return []

        reset = unstage_envctl_protected_paths(
            git_root,
            partition.protected_staged_paths,
            run_git=self.dependencies.run_git,
        )
        if reset.returncode != 0:
            self.dependencies.print_error("git reset protected envctl-local artifacts failed", reset)
            print("Protected envctl-local artifacts still staged: " + ", ".join(partition.protected_staged_paths))
            return None

        unstaged_protected_paths = list(partition.protected_staged_paths)
        print("Unstaged envctl-local artifacts: " + ", ".join(unstaged_protected_paths))
        return unstaged_protected_paths

    def _refreshed_partition_after_unstage(self, git_root: Path) -> EnvctlProtectedPathPartition | None:
        refreshed_status = self.dependencies.run_git(git_root, ["status", "--porcelain", "--untracked-files=all"])
        if refreshed_status.returncode != 0:
            self.dependencies.print_error("git status failed", refreshed_status)
            return None
        partition = self.dependencies.partition_envctl_protected_paths(refreshed_status.stdout)
        if partition.protected_staged_paths:
            print(
                "Protected envctl-local artifacts remain staged after recovery: "
                + ", ".join(partition.protected_staged_paths)
            )
            return None
        return partition

    def _stage_paths(self, git_root: Path, stageable_paths: list[str]) -> bool:
        if not stageable_paths:
            return True
        add = self.dependencies.run_git(git_root, ["add", "--", *stageable_paths])
        if add.returncode != 0:
            self.dependencies.print_error("git add failed", add)
            return False
        return True

    def _print_skipped_protected_paths(self, *protected_path_groups: list[str]) -> None:
        protected_paths = self.dependencies.ordered_unique_paths(*protected_path_groups)
        if protected_paths:
            print("Skipping envctl-local artifacts: " + ", ".join(protected_paths))

    def _commit_partition(self, git_root: Path) -> EnvctlProtectedPathPartition | None:
        status = self.dependencies.run_git(git_root, ["status", "--porcelain"])
        if status.returncode != 0:
            self.dependencies.print_error("git status failed", status)
            return None
        partition = self.dependencies.partition_envctl_protected_paths(status.stdout)
        if partition.protected_staged_paths:
            print(
                "Protected envctl-local artifacts remain staged after recovery: "
                + ", ".join(partition.protected_staged_paths)
            )
            return None
        return partition

    def _commit_staged_changes(self, git_root: Path, branch: str) -> int:
        commit_message, message_file, error, ledger_path = resolve_commit_message(self.context, branch=branch)
        if error:
            self._print_commit_message_error(error, ledger_path=ledger_path)
            return 1

        commit = self._run_commit(git_root, commit_message=commit_message, message_file=message_file)
        if commit.returncode != 0:
            self.dependencies.print_error("git commit failed", commit)
            return 1

        if ledger_path is not None:
            return self._advance_ledger_pointer(ledger_path)
        return 0

    def _print_commit_message_error(self, error: str, *, ledger_path: Path | None) -> None:
        error_paths: list[object] = []
        explicit_message_file = str(self.context.env.get("ENVCTL_COMMIT_MESSAGE_FILE", "")).strip()
        if explicit_message_file:
            error_paths.append(explicit_message_file)
        elif ledger_path is not None:
            error_paths.append(ledger_path)
        print(
            render_paths_in_terminal_text(
                error,
                paths=error_paths,
                env=self.context.env,
                stream=sys.stdout,
            )
        )

    def _run_commit(
        self,
        git_root: Path,
        *,
        commit_message: str,
        message_file: str,
    ) -> subprocess.CompletedProcess[str]:
        generated_message_file = message_file.endswith(".envctl-commit-message.txt")
        try:
            if message_file:
                return self.dependencies.run_git(git_root, ["commit", "-F", message_file])
            return self.dependencies.run_git(git_root, ["commit", "-m", commit_message])
        finally:
            self._remove_generated_message_file(message_file, generated_message_file=generated_message_file)

    @staticmethod
    def _remove_generated_message_file(message_file: str, *, generated_message_file: bool) -> None:
        if generated_message_file:
            try:
                Path(message_file).unlink()
            except OSError:
                pass

    def _advance_ledger_pointer(self, ledger_path: Path) -> int:
        advance_error = advance_commit_ledger_pointer(ledger_path)
        if advance_error:
            print(
                render_paths_in_terminal_text(
                    advance_error,
                    paths=[ledger_path],
                    env=self.context.env,
                    stream=sys.stdout,
                )
            )
            return 1
        return 0

    def _push(self, git_root: Path, branch: str) -> int:
        remote = str(self.context.env.get("PR_REMOTE") or "origin").strip() or "origin"
        push = self.dependencies.run_git(git_root, ["push", "-u", remote, branch])
        if push.returncode != 0:
            self.dependencies.print_error("git push failed", push)
            return 1

        print(f"Committed and pushed changes for {self.context.project_name} ({branch}).")
        return 0


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
    return CommitWorkflowRunner(
        context=context,
        dependencies=CommitWorkflowDependencies(
            resolve_git_root=resolve_git_root,
            git_available=git_available,
            git_output=git_output,
            run_git=run_git,
            print_error=print_error,
            partition_envctl_protected_paths=partition_envctl_protected_paths,
            ordered_unique_paths=ordered_unique_paths,
        ),
    ).execute()


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
