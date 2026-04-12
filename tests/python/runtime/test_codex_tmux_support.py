from __future__ import annotations

import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.runtime.codex_tmux_support import run_codex_tmux_command


class _InteractiveProcess:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode

    def wait(self) -> int:
        return self.returncode


class _RecordingProcessRunner:
    def __init__(self, *, probe_results: list[subprocess.CompletedProcess[str]] | None = None) -> None:
        self.probe_results = list(probe_results or [])
        self.probe_calls: list[list[str]] = []
        self.interactive_calls: list[list[str]] = []

    def run_probe(self, cmd, *, cwd=None, env=None, timeout=None, stdout_target=None, stderr_target=None):  # noqa: ANN001
        _ = cwd, env, timeout, stdout_target, stderr_target
        self.probe_calls.append([str(part) for part in cmd])
        if self.probe_results:
            return self.probe_results.pop(0)
        return subprocess.CompletedProcess(args=list(cmd), returncode=0, stdout="", stderr="")

    def start_interactive_child(self, cmd, *, cwd=None, env=None, stdin=None, stdout=None, stderr=None):  # noqa: ANN001
        _ = cwd, env, stdin, stdout, stderr
        self.interactive_calls.append([str(part) for part in cmd])
        return _InteractiveProcess(0)


class CodexTmuxSupportTests(unittest.TestCase):
    def _runtime(
        self,
        repo_root: Path,
        *,
        env: dict[str, str] | None = None,
        process_runner: _RecordingProcessRunner | None = None,
        missing: set[str] | None = None,
    ) -> SimpleNamespace:
        missing_commands = set(missing or set())
        return SimpleNamespace(
            config=SimpleNamespace(base_dir=repo_root),
            env=dict(env or {}),
            process_runner=process_runner or _RecordingProcessRunner(),
            _command_exists=lambda command: command not in missing_commands,
        )

    def test_codex_tmux_creates_session_and_attaches_outside_tmux(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            runner = _RecordingProcessRunner(
                probe_results=[
                    subprocess.CompletedProcess(args=["tmux"], returncode=1, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="", stderr=""),
                ]
            )
            runtime = self._runtime(repo_root, process_runner=runner)
            route = SimpleNamespace(command="codex-tmux", flags={}, passthrough_args=["review"])

            code = run_codex_tmux_command(runtime, route)

            self.assertEqual(code, 0)
            self.assertEqual(runner.probe_calls[0][:3], ["tmux", "has-session", "-t"])
            self.assertEqual(
                runner.probe_calls[1],
                [
                    "tmux",
                    "new-session",
                    "-d",
                    "-s",
                    runner.probe_calls[0][3],
                    "-n",
                    "codex",
                    "-c",
                    str(repo_root.resolve()),
                    "codex review",
                ],
            )
            self.assertEqual(runner.interactive_calls, [["tmux", "attach-session", "-t", runner.probe_calls[0][3]]])

    def test_codex_tmux_reuses_session_and_switches_inside_tmux(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            runner = _RecordingProcessRunner(
                probe_results=[
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="", stderr=""),
                ]
            )
            runtime = self._runtime(repo_root, env={"TMUX": "/tmp/tmux-100/default,123,0"}, process_runner=runner)
            route = SimpleNamespace(command="codex-tmux", flags={}, passthrough_args=[])

            code = run_codex_tmux_command(runtime, route)

            self.assertEqual(code, 0)
            self.assertEqual(runner.probe_calls[0][:3], ["tmux", "has-session", "-t"])
            self.assertEqual(runner.probe_calls[1], ["tmux", "switch-client", "-t", runner.probe_calls[0][3]])
            self.assertEqual(runner.interactive_calls, [])

    def test_codex_tmux_dry_run_supports_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            runner = _RecordingProcessRunner(
                probe_results=[subprocess.CompletedProcess(args=["tmux"], returncode=1, stdout="", stderr="")]
            )
            runtime = self._runtime(repo_root, process_runner=runner)
            route = SimpleNamespace(command="codex-tmux", flags={"dry_run": True, "json": True}, passthrough_args=["review"])
            stdout = StringIO()

            with redirect_stdout(stdout):
                code = run_codex_tmux_command(runtime, route)

            self.assertEqual(code, 0)
            self.assertIn('"create_session": true', stdout.getvalue())
            self.assertIn('"codex_command": [', stdout.getvalue())
            self.assertEqual(runner.interactive_calls, [])

    def test_codex_tmux_missing_executable_fails_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            runtime = self._runtime(repo_root, missing={"tmux"})
            route = SimpleNamespace(command="codex-tmux", flags={}, passthrough_args=[])
            stderr = StringIO()

            with redirect_stderr(stderr):
                code = run_codex_tmux_command(runtime, route)

            self.assertEqual(code, 1)
            self.assertIn("Missing required executables: tmux", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
