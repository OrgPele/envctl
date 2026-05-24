from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from tests.python.actions.actions_parity_test_support import (
    PythonEngineRuntime,
    _ActionsParityTestCase,
    _FakeRunner,
    parse_route,
)


class ActionsTestServiceScopeParityTests(_ActionsParityTestCase):
    def test_test_action_runs_backend_and_frontend_for_mixed_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "pyproject.toml").write_text(
                "[project]\nname='backend'\nversion='1.0.0'\n",
                encoding="utf-8",
            )
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend" / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (repo / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            with (
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
            ):
                route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(len(fake_runner.run_calls), 2, msg=fake_runner.run_calls)
            command_set = {call[0] for call in fake_runner.run_calls}
            cwd_set = {Path(call[1]).resolve() for call in fake_runner.run_calls}
            frontend_commands = [
                command for command in command_set if len(command) >= 3 and command[:3] == ("pnpm", "run", "test")
            ]
            self.assertEqual(len(frontend_commands), 1)
            self.assertEqual(frontend_commands[0][-3], "--")
            self.assertEqual(frontend_commands[0][-2], "--reporter=default")
            self.assertTrue(frontend_commands[0][-1].endswith("vitest_progress_reporter.mjs"))
            pytest_commands = [
                command
                for command in command_set
                if len(command) >= 4 and command[:3] == ("/usr/bin/python3", "-m", "pytest")
            ]
            self.assertEqual(len(pytest_commands), 1)
            self.assertIn("envctl_engine.test_output.pytest_progress_plugin", pytest_commands[0])
            self.assertTrue(any(str(part).endswith("/backend/tests") for part in pytest_commands[0]))
            self.assertIn(repo.resolve(), cwd_set)
            self.assertIn((repo / "frontend").resolve(), cwd_set)

    def test_test_action_uses_separate_backend_and_frontend_test_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_root = repo / "trees" / "feature-a" / "1"
            tree_root.mkdir(parents=True, exist_ok=True)
            (repo / ".envctl").write_text(
                "\n".join(
                    [
                        "ENVCTL_DEFAULT_MODE=trees",
                        "MAIN_BACKEND_ENABLE=true",
                        "MAIN_FRONTEND_ENABLE=true",
                        "TREES_BACKEND_ENABLE=true",
                        "TREES_FRONTEND_ENABLE=true",
                        "ENVCTL_BACKEND_TEST_CMD=python -m pytest backend/tests",
                        "ENVCTL_FRONTEND_TEST_CMD=pnpm run test",
                        "ENVCTL_FRONTEND_TEST_PATH=src",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            frontend = tree_root / "frontend"
            (frontend / "src").mkdir(parents=True, exist_ok=True)
            (frontend / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (frontend / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            with patch(
                "envctl_engine.runtime.engine_runtime_commands.shutil.which",
                side_effect=lambda name: f"/usr/bin/{name}",
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            commands = {call[0] for call in fake_runner.run_calls}
            backend_commands = [
                command for command in commands if len(command) >= 4 and command[:3] == ("python", "-m", "pytest")
            ]
            self.assertEqual(len(backend_commands), 1, msg=commands)
            self.assertIn("envctl_engine.test_output.pytest_progress_plugin", backend_commands[0])
            self.assertEqual(backend_commands[0][-1], "backend/tests")
            frontend_commands = [
                command
                for command in commands
                if len(command) >= 5 and command[:5] == ("pnpm", "run", "test", "--", "src")
            ]
            self.assertEqual(len(frontend_commands), 1, msg=commands)

    def test_test_action_backend_false_runs_frontend_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "pyproject.toml").write_text(
                "[project]\nname='backend'\nversion='1.0.0'\n",
                encoding="utf-8",
            )
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend" / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (repo / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            with (
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
            ):
                route = parse_route(
                    ["test", "--project", "feature-a-1", "backend=false"],
                    env={"ENVCTL_DEFAULT_MODE": "trees"},
                )
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(len(fake_runner.run_calls), 1, msg=fake_runner.run_calls)
            only_cmd, only_cwd = fake_runner.run_calls[0]
            self.assertEqual(only_cmd[:3], ("pnpm", "run", "test"))
            self.assertEqual(only_cmd[-3], "--")
            self.assertEqual(only_cmd[-2], "--reporter=default")
            self.assertTrue(only_cmd[-1].endswith("vitest_progress_reporter.mjs"))
            self.assertEqual(Path(only_cwd).resolve(), (repo / "frontend").resolve())

    def test_test_action_frontend_false_runs_backend_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "pyproject.toml").write_text(
                "[project]\nname='backend'\nversion='1.0.0'\n",
                encoding="utf-8",
            )
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend" / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (repo / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            with (
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
            ):
                route = parse_route(
                    ["test", "--project", "feature-a-1", "frontend=false"],
                    env={"ENVCTL_DEFAULT_MODE": "trees"},
                )
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(len(fake_runner.run_calls), 1, msg=fake_runner.run_calls)
            only_cmd, only_cwd = fake_runner.run_calls[0]
            self.assertEqual(only_cmd[:3], ("/usr/bin/python3", "-m", "pytest"))
            self.assertIn("envctl_engine.test_output.pytest_progress_plugin", only_cmd)
            self.assertTrue(any(str(part).endswith("/backend/tests") for part in only_cmd))
            self.assertEqual(Path(only_cwd).resolve(), repo.resolve())

    def test_test_action_services_frontend_only_runs_frontend_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "pyproject.toml").write_text(
                "[project]\nname='backend'\nversion='1.0.0'\n",
                encoding="utf-8",
            )
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend" / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (repo / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            with (
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
            ):
                route = parse_route(
                    ["test", "--project", "feature-a-1"],
                    env={"ENVCTL_DEFAULT_MODE": "trees"},
                )
                route.flags = {**route.flags, "services": ["feature-a-1 Frontend"]}
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(len(fake_runner.run_calls), 1, msg=fake_runner.run_calls)
            only_cmd, only_cwd = fake_runner.run_calls[0]
            self.assertEqual(only_cmd[:3], ("pnpm", "run", "test"))
            self.assertEqual(only_cmd[-3], "--")
            self.assertEqual(only_cmd[-2], "--reporter=default")
            self.assertTrue(only_cmd[-1].endswith("vitest_progress_reporter.mjs"))
            self.assertEqual(Path(only_cwd).resolve(), (repo / "frontend").resolve())

    def test_test_action_disabling_all_suites_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "pyproject.toml").write_text(
                "[project]\nname='backend'\nversion='1.0.0'\n",
                encoding="utf-8",
            )
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend" / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (repo / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(
                ["test", "--project", "feature-a-1", "backend=false", "frontend=false"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertEqual(fake_runner.run_calls, [])

