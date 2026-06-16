from __future__ import annotations

import json
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from envctl_engine.actions.action_ship_support import run_ship_workflow


@dataclass(frozen=True, slots=True)
class ShipWorkflowResult:
    code: int
    stdout: str
    stderr: str

    @property
    def payload(self) -> dict[str, Any]:
        return json.loads(self.stdout)


@dataclass(slots=True)
class ShipWorkflowFixture:
    repo_root: Path
    context: SimpleNamespace
    branch: str = "feature/demo"
    head_sha: str = "abc123"

    def run(
        self,
        *,
        git_output: Callable[[Path, list[str]], str] | None = None,
        run_git: Callable[[Path, list[str]], subprocess.CompletedProcess[str]] | None = None,
        resolve_base_branch: Callable[[object, Path], str] | None = None,
        resolve_base_ref: Callable[[Path, str], str] | None = None,
        run_commit_action: Callable[[object], int] | None = None,
        run_pr_action: Callable[[object], int] | None = None,
        add_ship_pr_label: Callable[[object, Path, str], int] | None = None,
        probe_dirty_worktree: Callable[..., object] | None = None,
        existing_pr_url: Callable[[Path, str], str] | None = None,
        partition_envctl_protected_paths: Callable[[str], object] | None = None,
        ordered_unique_paths: Callable[..., list[str]] | None = None,
        github_pr_checks: Callable[..., dict[str, object]] | None = None,
    ) -> ShipWorkflowResult:
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = run_ship_workflow(
                self.context,
                resolve_git_root=lambda project_root, repo_root: project_root,
                git_available=True,
                git_output=git_output or self.git_output,
                run_git=run_git or self.run_git,
                resolve_base_branch=resolve_base_branch or self.resolve_base_branch,
                resolve_base_ref=resolve_base_ref or self.resolve_base_ref,
                run_commit_action=run_commit_action or self.run_commit_action,
                run_pr_action=run_pr_action or self.run_pr_action,
                add_ship_pr_label=add_ship_pr_label or self.add_ship_pr_label,
                probe_dirty_worktree=probe_dirty_worktree or self.probe_dirty_worktree,
                existing_pr_url=existing_pr_url or self.existing_pr_url,
                partition_envctl_protected_paths=(
                    partition_envctl_protected_paths or self.partition_envctl_protected_paths
                ),
                ordered_unique_paths=ordered_unique_paths or self.ordered_unique_paths,
                github_pr_checks=github_pr_checks or self.github_pr_checks,
            )
        return ShipWorkflowResult(code=code, stdout=stdout.getvalue(), stderr=stderr.getvalue())

    def git_output(self, _git_root: Path, args: list[str]) -> str:
        if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
            return f"{self.branch}\n"
        if args == ["rev-parse", "HEAD"]:
            return f"{self.head_sha}\n"
        return ""

    @staticmethod
    def run_git(_git_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        if args == ["rev-parse", "--verify", "@{u}"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="abc123\n", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=0)

    @staticmethod
    def resolve_base_branch(_context: object, _git_root: Path) -> str:
        return "main"

    @staticmethod
    def resolve_base_ref(_git_root: Path, _base_branch: str) -> str:
        return "origin/main"

    @staticmethod
    def run_commit_action(_context: object) -> int:
        return 0

    @staticmethod
    def run_pr_action(_context: object) -> int:
        return 0

    @staticmethod
    def add_ship_pr_label(_context: object, _git_root: Path, _pr_url: str) -> int:
        return 0

    @staticmethod
    def probe_dirty_worktree(*_args: object, **_kwargs: object) -> object:
        return SimpleNamespace(dirty=False)

    @staticmethod
    def existing_pr_url(_git_root: Path, _branch: str) -> str:
        return "https://github.com/acme/repo/pull/7"

    @staticmethod
    def partition_envctl_protected_paths(_status: str) -> object:
        return SimpleNamespace(protected_staged_paths=[], protected_skipped_paths=[])

    @staticmethod
    def ordered_unique_paths(*groups: list[str]) -> list[str]:
        return [path for group in groups for path in group]

    @staticmethod
    def github_pr_checks(
        _git_root: Path,
        *,
        branch: str,
        pr_url: str,
        expected_head_sha: str,
    ) -> dict[str, object]:
        return {
            "state": "checks_passed",
            "passed_checks": [{"name": "pytest", "state": "SUCCESS"}],
            "failing_checks": [],
            "pending_checks": [],
            "duration_seconds": 0.1,
            "expected_head_sha": expected_head_sha,
        }


@contextmanager
def ship_workflow_fixture() -> Iterator[ShipWorkflowFixture]:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir) / "repo"
        repo_root.mkdir()
        context = SimpleNamespace(
            repo_root=repo_root,
            project_root=repo_root,
            project_name="Main",
            env={"ENVCTL_ACTION_JSON": "true"},
        )
        yield ShipWorkflowFixture(repo_root=repo_root, context=context)
