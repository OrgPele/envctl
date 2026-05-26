from __future__ import annotations

from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
import subprocess
from typing import Callable
from unittest.mock import patch

from tests.python.actions.actions_cli_test_support import actions_cli, os, redirect_stdout


@dataclass(frozen=True, slots=True)
class CommitActionResult:
    code: int
    output: str


@dataclass(slots=True)
class CommitActionHarness:
    project_root: Path
    branch: str = "feature/demo"
    pre_stage_statuses: list[str] = field(default_factory=lambda: [" M app.py\n"])
    staged_status: str = "M  app.py\n"
    reset_returncode: int = 0
    reset_stderr: str = ""
    commit_returncode: int = 0
    commit_stdout: str = "[feature/demo abc123] Ship it\n"
    commit_stderr: str = ""
    push_returncode: int = 0
    push_stderr: str = ""
    seen_git_args: list[list[str]] = field(default_factory=list)
    captured_commit_messages: list[str] = field(default_factory=list)

    def run(
        self,
        *,
        project_name: str = "Main",
        env: dict[str, str] | None = None,
        stdout_factory: Callable[[], StringIO] = StringIO,
    ) -> CommitActionResult:
        buffer = stdout_factory()
        with (
            patch.dict(os.environ, env or {}, clear=False),
            patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/git"),
            patch("envctl_engine.actions.project_action_domain._run_git", side_effect=self.run_git),
            redirect_stdout(buffer),
        ):
            code = actions_cli._run_commit_action(self.project_root, project_name)
        return CommitActionResult(code=code, output=buffer.getvalue())

    def run_git(self, _git_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        self.seen_git_args.append(list(args))
        if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=f"{self.branch}\n", stderr="")
        if args == ["status", "--porcelain", "--untracked-files=all"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=self._next_pre_stage_status(), stderr="")
        if args[:3] == ["reset", "-q", "--"]:
            return subprocess.CompletedProcess(args=args, returncode=self.reset_returncode, stdout="", stderr=self.reset_stderr)
        if args[:2] == ["add", "--"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        if args == ["status", "--porcelain"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=self.staged_status, stderr="")
        if args[:2] == ["commit", "-F"]:
            self.captured_commit_messages.append(Path(args[2]).read_text(encoding="utf-8"))
            return subprocess.CompletedProcess(
                args=args,
                returncode=self.commit_returncode,
                stdout=self.commit_stdout,
                stderr=self.commit_stderr,
            )
        if args[:2] == ["commit", "-m"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=self.commit_returncode,
                stdout=self.commit_stdout,
                stderr=self.commit_stderr,
            )
        if args[:2] == ["push", "-u"]:
            return subprocess.CompletedProcess(args=args, returncode=self.push_returncode, stdout="", stderr=self.push_stderr)
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="unexpected")

    def _next_pre_stage_status(self) -> str:
        if len(self.pre_stage_statuses) > 1:
            return self.pre_stage_statuses.pop(0)
        return self.pre_stage_statuses[0] if self.pre_stage_statuses else ""


def write_commit_ledger(project_root: Path, text: str) -> Path:
    ledger = project_root / ".envctl-commit-message.md"
    ledger.write_text(text, encoding="utf-8")
    return ledger
