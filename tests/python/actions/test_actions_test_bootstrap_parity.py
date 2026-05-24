from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.python.actions.actions_parity_test_support import (
    PythonEngineRuntime,
    _ActionsParityTestCase,
    _FakeRunner,
    actions_test_module,
    parse_route,
)


class ActionsTestBootstrapParityTests(_ActionsParityTestCase):
    def test_envctl_repo_test_bootstrap_creates_repo_local_venv_and_installs_dev_deps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "python" / "envctl_engine").mkdir(parents=True, exist_ok=True)
            (repo / "python" / "envctl_engine" / "__init__.py").write_text('"""envctl"""\n', encoding="utf-8")
            (repo / "pyproject.toml").write_text(
                "\n".join(
                    [
                        "[project]",
                        'name = "envctl"',
                        'version = "0.0.0"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            commands: list[tuple[str, ...]] = []
            statuses: list[str] = []

            def fake_run(command, *, cwd=None, capture_output=None, text=None, check=None):  # noqa: ANN001
                _ = capture_output, text, check
                commands.append(tuple(str(part) for part in command))
                self.assertEqual(Path(str(cwd)).resolve(), repo.resolve())
                rendered = tuple(str(part) for part in command)
                if rendered[1:3] == ("-m", "venv"):
                    python_bin = repo / ".venv" / "bin" / "python"
                    python_bin.parent.mkdir(parents=True, exist_ok=True)
                    python_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                    python_bin.chmod(0o755)
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch("envctl_engine.actions.actions_test.subprocess.run", side_effect=fake_run):
                actions_test_module.ensure_repo_local_test_prereqs(repo, emit_status=statuses.append)

            self.assertEqual(len(commands), 2)
            self.assertEqual(commands[0][1:3], ("-m", "venv"))
            self.assertEqual(Path(commands[0][3]).resolve(), (repo / ".venv").resolve())
            self.assertEqual(
                commands[1],
                (str((repo / ".venv" / "bin" / "python").resolve()), "-m", "pip", "install", "-e", ".[dev]"),
            )
            self.assertTrue(
                any("Creating repo-local .venv for envctl test actions" in message for message in statuses),
                msg=statuses,
            )
            self.assertTrue(
                any("Installing repo-local envctl test prerequisites" in message for message in statuses),
                msg=statuses,
            )

    def test_envctl_repo_test_bootstrap_skips_when_repo_local_python_is_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "python" / "envctl_engine").mkdir(parents=True, exist_ok=True)
            (repo / "python" / "envctl_engine" / "__init__.py").write_text('"""envctl"""\n', encoding="utf-8")
            (repo / "pyproject.toml").write_text(
                "\n".join(
                    [
                        "[project]",
                        'name = "envctl"',
                        'version = "0.0.0"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            python_bin = repo / ".venv" / "bin" / "python"
            python_bin.parent.mkdir(parents=True, exist_ok=True)
            python_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            python_bin.chmod(0o755)

            def fake_run(command, *, cwd=None, capture_output=None, text=None, check=None):  # noqa: ANN001
                _ = cwd, capture_output, text, check
                rendered = tuple(str(part) for part in command)
                if rendered == (
                    str(python_bin.resolve()),
                    "-c",
                    "import build, prompt_toolkit, psutil, pytest, rich, textual",
                ):
                    return SimpleNamespace(returncode=0, stdout="", stderr="")
                self.fail(f"Unexpected bootstrap command: {rendered}")

            with patch("envctl_engine.actions.actions_test.subprocess.run", side_effect=fake_run):
                actions_test_module.ensure_repo_local_test_prereqs(repo)

    def test_test_action_uses_python_native_fallback_when_repo_has_tests_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertTrue(
                any(
                    "-m" in call[0] and "envctl_engine.test_output.unittest_runner" in call[0] and "discover" in call[0]
                    for call in fake_runner.run_calls
                ),
                msg=fake_runner.run_calls,
            )

