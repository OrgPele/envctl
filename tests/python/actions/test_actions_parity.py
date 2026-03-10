from __future__ import annotations

import tempfile
import unittest
import importlib
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
import sys
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
actions_test_module = importlib.import_module("envctl_engine.actions.actions_test")
command_router_module = importlib.import_module("envctl_engine.runtime.command_router")
config_module = importlib.import_module("envctl_engine.config")
engine_runtime_module = importlib.import_module("envctl_engine.runtime.engine_runtime")

default_test_command = actions_test_module.default_test_command
default_test_commands = actions_test_module.default_test_commands
parse_route = command_router_module.parse_route
load_config = config_module.load_config
PythonEngineRuntime = engine_runtime_module.PythonEngineRuntime
RunState = engine_runtime_module.RunState
ServiceRecord = engine_runtime_module.ServiceRecord


class _FakeRunner:
    def __init__(self, *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.run_calls: list[tuple[tuple[str, ...], str]] = []
        self.run_envs: list[dict[str, str] | None] = []

    def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
        _ = env, timeout
        self.run_calls.append((tuple(cmd), str(cwd)))
        self.run_envs.append(dict(env) if isinstance(env, dict) else None)
        return SimpleNamespace(returncode=self.returncode, stdout=self.stdout, stderr=self.stderr)

    def start(self, cmd, *, cwd=None, env=None):  # noqa: ANN001
        _ = cmd, cwd, env
        return SimpleNamespace(pid=10001, poll=lambda: None)

    def wait_for_port(self, _port: int, *, host: str = "127.0.0.1", timeout: float = 30.0) -> bool:
        _ = host, timeout
        return True

    def is_pid_running(self, _pid: int) -> bool:
        return False


class ActionsParityTests(unittest.TestCase):
    def _config(self, repo: Path, runtime: Path):
        return load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(runtime),
                "ENVCTL_DEFAULT_MODE": "trees",
            }
        )

    def test_action_commands_execute_with_configured_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "ENVCTL_ACTION_TEST_CMD": "sh -lc 'exit 0'",
                    "ENVCTL_ACTION_PR_CMD": "sh -lc 'exit 0'",
                    "ENVCTL_ACTION_COMMIT_CMD": "sh -lc 'exit 0'",
                    "ENVCTL_ACTION_ANALYZE_CMD": "sh -lc 'exit 0'",
                    "ENVCTL_ACTION_MIGRATE_CMD": "sh -lc 'exit 0'",
                },
            )
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            commands = ("test", "pr", "commit", "review", "migrate")
            for command in commands:
                route = parse_route([command, "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                code = engine.dispatch(route)
                self.assertEqual(code, 0, msg=command)

            self.assertGreaterEqual(len(fake_runner.run_calls), len(commands))

    def test_interactive_test_action_reports_status_without_stdout_summary_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"ENVCTL_ACTION_TEST_CMD": "sh -lc 'exit 0'"},
            )
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            route.flags = {**route.flags, "interactive_command": True, "batch": True}

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertNotIn("Executed test action", out.getvalue())
            status_messages = [
                str(event.get("message", "")) for event in engine.events if event.get("event") == "ui.status"
            ]
            self.assertTrue(any("Executing configured test command" in message for message in status_messages))
            self.assertTrue(any("Test command finished" in message for message in status_messages))

    def test_interactive_root_unittest_action_prints_resolved_command_and_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_root.mkdir(parents=True, exist_ok=True)
            (tree_root / "tests").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(
                returncode=0,
                stdout="..\n----------------------------------------------------------------------\nRan 2 tests in 0.003s\n\nOK\n",
            )
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            route.flags = {**route.flags, "interactive_command": True, "batch": True}

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertIn("command: ", rendered)
            self.assertIn("-m unittest discover -s tests -p test_*.py", rendered)
            self.assertIn(f"cwd: {tree_root.resolve()}", rendered)
            self.assertIn("2 passed, 0 failed, 0 skipped", rendered)
            self.assertIn("Repository tests (unittest)", rendered)

    def test_interactive_test_action_emits_live_progress_status_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_root.mkdir(parents=True, exist_ok=True)
            (tree_root / "tests").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            class _ProgressRunner:
                def __init__(self, *_args, **_kwargs) -> None:
                    self.last_result = SimpleNamespace(
                        counts_detected=True,
                        passed=3,
                        failed=0,
                        skipped=0,
                        errors=0,
                        total=3,
                    )

                def run_tests(self, command, *, cwd=None, env=None, timeout=None, progress_callback=None):  # noqa: ANN001
                    _ = command, cwd, env, timeout
                    if callable(progress_callback):
                        progress_callback(1, 3)
                        progress_callback(3, 3)
                    return SimpleNamespace(returncode=0, stdout="", stderr="")

            route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            route.flags = {**route.flags, "interactive_command": True, "batch": True}

            with patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _ProgressRunner):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(route)

            self.assertEqual(code, 0)
            status_messages = [
                str(event.get("message", "")) for event in engine.events if event.get("event") == "ui.status"
            ]
            self.assertTrue(
                any("1/3 tests complete • 1 passed, 0 failed" in message for message in status_messages),
                msg=status_messages,
            )
            self.assertTrue(
                any("3/3 tests complete • 3 passed, 0 failed" in message for message in status_messages),
                msg=status_messages,
            )

    def test_interactive_test_action_live_progress_counts_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_root.mkdir(parents=True, exist_ok=True)
            (tree_root / "tests").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            class _ProgressRunner:
                def __init__(self, *_args, **_kwargs) -> None:
                    self.last_result = SimpleNamespace(
                        counts_detected=True,
                        passed=1,
                        failed=1,
                        skipped=0,
                        errors=0,
                        total=2,
                        failed_tests=["tests/test_sample.py::test_two"],
                    )

                def run_tests(self, command, *, cwd=None, env=None, timeout=None, progress_callback=None):  # noqa: ANN001
                    _ = command, cwd, env, timeout
                    if callable(progress_callback):
                        progress_callback(2, 2)
                    return SimpleNamespace(returncode=1, stdout="", stderr="")

            route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            route.flags = {**route.flags, "interactive_command": True, "batch": True}

            with patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _ProgressRunner):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(route)

            self.assertEqual(code, 1)
            status_messages = [
                str(event.get("message", "")) for event in engine.events if event.get("event") == "ui.status"
            ]
            self.assertTrue(
                any("2/2 tests complete • 1 passed, 1 failed" in message for message in status_messages),
                msg=status_messages,
            )

    def test_interactive_test_action_prints_failure_excerpt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_root.mkdir(parents=True, exist_ok=True)
            (tree_root / "tests").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(
                returncode=1,
                stdout="E\nFAILED (errors=1)\n",
                stderr="ImportError: cannot import name 'x' from 'y'\n",
            )
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            route.flags = {**route.flags, "interactive_command": True, "batch": True}

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            rendered = out.getvalue()
            self.assertIn("failure: ", rendered)
            self.assertIn("ImportError: cannot import name 'x' from 'y'", rendered)

    def test_action_commands_require_explicit_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"ENVCTL_ACTION_TEST_CMD": "sh -lc 'exit 0'"},
            )

            code = engine.dispatch(parse_route(["test"], env={"ENVCTL_DEFAULT_MODE": "trees"}))
            self.assertEqual(code, 1)

    def test_action_commands_use_shell_compatible_missing_target_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            expected_messages = {
                "pr": "No PR target selected.",
                "commit": "No commit target selected.",
                "review": "No review target selected.",
                "migrate": "No migration target selected.",
            }
            for command, expected in expected_messages.items():
                with self.subTest(command=command):
                    out = StringIO()
                    with redirect_stdout(out):
                        code = engine.dispatch(parse_route([command], env={"ENVCTL_DEFAULT_MODE": "trees"}))
                    self.assertEqual(code, 1, msg=command)
                    self.assertIn(expected, out.getvalue(), msg=command)

    def test_action_env_marks_batch_routes_non_interactive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            target_root = repo / "trees" / "feature-a" / "1"
            target_root.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            route = parse_route(
                ["commit", "--project", "feature-a-1", "--batch"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            target = SimpleNamespace(name="feature-a-1", root=target_root)

            env = engine.action_command_orchestrator.action_env(
                "commit",
                [target],
                route=route,
                target=target,
                extra=None,
            )
            self.assertEqual(env.get("ENVCTL_ACTION_INTERACTIVE"), "0")

    def test_action_env_exposes_runtime_scoped_tree_diffs_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            target_root = repo / "trees" / "feature-a" / "1"
            target_root.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            route = parse_route(
                ["review", "--project", "feature-a-1"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            target = SimpleNamespace(name="feature-a-1", root=target_root)

            env = engine.action_command_orchestrator.action_env(
                "review",
                [target],
                route=route,
                target=target,
                extra=None,
            )

            expected_root = engine.state_repository.tree_diffs_dir_path(None)
            self.assertEqual(env.get("ENVCTL_ACTION_TREE_DIFFS_ROOT"), str(expected_root))
            self.assertEqual(env.get("ENVCTL_ACTION_RUNTIME_ROOT"), str(engine.state_repository.runtime_root))

    def test_action_explicit_main_mode_does_not_fallback_to_tree_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "ENVCTL_DEFAULT_MODE": "main",
                    }
                ),
                env={"ENVCTL_ACTION_TEST_CMD": "sh -lc 'exit 0'"},
            )
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(
                ["test", "--main", "--project", "feature-a-1"],
                env={"ENVCTL_DEFAULT_MODE": "main"},
            )
            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertIn("No matching targets found", out.getvalue())
            self.assertEqual(fake_runner.run_calls, [])

    def test_action_implicit_main_mode_keeps_main_scope_when_main_candidate_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "ENVCTL_DEFAULT_MODE": "main",
                    }
                ),
                env={"ENVCTL_ACTION_TEST_CMD": "sh -lc 'exit 0'"},
            )
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(
                ["test", "--project", "feature-a-1"],
                env={"ENVCTL_DEFAULT_MODE": "main"},
            )
            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertIn("No matching targets found", out.getvalue())
            self.assertEqual(fake_runner.run_calls, [])

    def test_git_actions_use_python_native_defaults_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            target = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
            (repo / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            target.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            for command in ("pr", "commit", "review"):
                route = parse_route([command, "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                code = engine.dispatch(route)
                self.assertEqual(code, 0, msg=command)

            self.assertTrue(
                any(
                    ("envctl_engine.actions.actions_cli" in call[0]) or ("envctl_engine.actions.actions_cli" in call[0])
                    for call in fake_runner.run_calls
                )
            )

    def test_interactive_review_prints_action_output_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            target = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            target.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"ENVCTL_ACTION_ANALYZE_CMD": "sh -lc 'echo Review summary written: /tmp/review.md'"},
            )
            fake_runner = _FakeRunner(returncode=0, stdout="Review summary written: /tmp/review.md\n")
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["review", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            route.flags = {**route.flags, "interactive_command": True, "batch": True}
            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertIn("Review summary written: /tmp/review.md", rendered)

    def test_interactive_pr_reports_existing_pr_status_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            target = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            target.mkdir(parents=True, exist_ok=True)

            existing_line = "PR already exists: https://github.com/acme/supportopia/pull/42"
            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "ENVCTL_ACTION_PR_CMD": "sh -lc 'echo PR already exists: https://github.com/acme/supportopia/pull/42'"
                },
            )
            fake_runner = _FakeRunner(returncode=0, stdout=f"{existing_line}\n")
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["pr", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            route.flags = {**route.flags, "interactive_command": True, "batch": True}
            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertIn(existing_line, rendered)
            status_messages = [
                str(event.get("message", "")) for event in engine.events if event.get("event") == "ui.status"
            ]
            self.assertTrue(any(existing_line in message for message in status_messages), msg=status_messages)

    def test_review_action_extra_env_maps_project_scoped_backend_service_to_backend_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            route = parse_route(
                ["review", "--service", "Main Backend"],
                env={"ENVCTL_DEFAULT_MODE": "main"},
            )

            extra = engine.action_command_orchestrator.action_extra_env(route)
            self.assertEqual(extra.get("ENVCTL_ANALYZE_SCOPE"), "backend")

    def test_git_actions_fallback_to_system_python_when_repo_has_no_venv(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            target = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            target.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            with patch(
                "envctl_engine.actions.action_utils.shutil.which",
                side_effect=lambda name: "/usr/bin/python3" if name in {"python3", "python"} else None,
            ):
                for command in ("pr", "commit", "review"):
                    route = parse_route([command, "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                    code = engine.dispatch(route)
                    self.assertEqual(code, 0, msg=command)

            self.assertTrue(
                any(call[0][0] == "/usr/bin/python3" for call in fake_runner.run_calls),
                msg=fake_runner.run_calls,
            )

    def test_git_actions_fallback_to_runtime_python_when_path_lookup_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            target = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            target.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            with patch(
                "envctl_engine.actions.action_utils.shutil.which",
                return_value=None,
            ):
                route = parse_route(["pr", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertTrue(fake_runner.run_calls)
            self.assertEqual(fake_runner.run_calls[0][0][0], sys.executable)

    def test_migrate_action_uses_local_dot_venv_python_when_backend_venv_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            target = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (target / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
            (target / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            target.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["migrate", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertTrue(fake_runner.run_calls)
            command = fake_runner.run_calls[0][0]
            self.assertEqual(Path(command[0]).resolve(), (target / ".venv" / "bin" / "python").resolve())
            self.assertEqual(command[1:4], ("-m", "alembic", "upgrade"))

    def test_migrate_action_falls_back_to_system_python_when_local_venv_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            target = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            target.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            with patch(
                "envctl_engine.actions.action_utils.shutil.which",
                side_effect=lambda name: "/usr/bin/python3" if name in {"python3.12", "python3", "python"} else None,
            ):
                route = parse_route(["migrate", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertTrue(fake_runner.run_calls)
            self.assertEqual(fake_runner.run_calls[0][0][:3], ("/usr/bin/python3", "-m", "alembic"))

    def test_action_env_includes_pythonpath_for_native_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            target = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
            (repo / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            target.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["pr", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            code = engine.dispatch(route)
            self.assertEqual(code, 0)

            self.assertTrue(fake_runner.run_envs)
            env = fake_runner.run_envs[0] or {}
            self.assertIn("PYTHONPATH", env)
            self.assertIn(str(repo / "python"), env["PYTHONPATH"])

    def test_test_action_writes_failed_tests_summary_and_persists_dashboard_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_root.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"ENVCTL_ACTION_TEST_CMD": "sh -lc 'exit 1'", "NO_COLOR": "1"},
            )
            fake_runner = _FakeRunner(returncode=1)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            state = RunState(
                run_id="run-tests-artifact",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(tree_root),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                    "feature-a-1 Frontend": ServiceRecord(
                        name="feature-a-1 Frontend",
                        type="frontend",
                        cwd=str(tree_root),
                        pid=2222,
                        requested_port=9000,
                        actual_port=9000,
                        status="running",
                    ),
                },
            )
            engine.state_repository.save_resume_state(
                state=state,
                emit=engine._emit,
                runtime_map_builder=engine_runtime_module.build_runtime_map,
            )

            class _FailingRunner:
                def __init__(self, *_args, **_kwargs) -> None:
                    self.last_result = None

                def run_tests(self, _command, *, cwd=None, env=None, timeout=None):  # noqa: ANN001, ARG002
                    from envctl_engine.test_output.parser_base import TestResult

                    self.last_result = TestResult(
                        passed=10,
                        failed=1,
                        skipped=0,
                        total=11,
                        failed_tests=["backend/tests/test_auth.py::test_signup_regression"],
                        error_details={
                            "backend/tests/test_auth.py::test_signup_regression": "AssertionError: expected 201, got 500"
                        },
                    )
                    return SimpleNamespace(returncode=1, stdout="", stderr="suite failed")

            with patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _FailingRunner):
                route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                code = engine.dispatch(route)

            self.assertEqual(code, 1)

            refreshed = engine._try_load_existing_state(mode="trees", strict_mode_match=False)
            self.assertIsNotNone(refreshed)
            assert refreshed is not None
            summaries = refreshed.metadata.get("project_test_summaries")
            self.assertIsInstance(summaries, dict)
            assert isinstance(summaries, dict)
            project_entry = summaries.get("feature-a-1")
            self.assertIsInstance(project_entry, dict)
            assert isinstance(project_entry, dict)
            summary_path = project_entry.get("summary_path")
            self.assertIsInstance(summary_path, str)
            assert isinstance(summary_path, str)
            expected_root = engine.runtime_root / "runs" / state.run_id / "test-results"
            self.assertTrue(summary_path.endswith("failed_tests_summary.txt"))
            self.assertTrue(Path(summary_path).is_file())
            self.assertTrue(Path(summary_path).is_relative_to(expected_root))
            summary_text = Path(summary_path).read_text(encoding="utf-8")
            self.assertIn("backend/tests/test_auth.py::test_signup_regression", summary_text)
            self.assertIn("AssertionError: expected 201, got 500", summary_text)
            self.assertEqual(project_entry.get("status"), "failed")
            results_root = refreshed.metadata.get("project_test_results_root")
            self.assertEqual(results_root, str(Path(summary_path).parent.parent))
            self.assertTrue(Path(str(results_root)).is_relative_to(expected_root))
            self.assertFalse((repo / "test-results").exists())

            dashboard_out = StringIO()
            with redirect_stdout(dashboard_out):
                engine._print_dashboard_snapshot(refreshed)
            rendered = dashboard_out.getvalue()
            self.assertIn("tests:", rendered)
            self.assertIn(summary_path, rendered)

    def test_test_action_writes_passed_summary_with_no_failed_tests_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_root.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"ENVCTL_ACTION_TEST_CMD": "sh -lc 'exit 0'"},
            )

            state = RunState(
                run_id="run-tests-artifact-pass",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(tree_root),
                        pid=3333,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                    "feature-a-1 Frontend": ServiceRecord(
                        name="feature-a-1 Frontend",
                        type="frontend",
                        cwd=str(tree_root),
                        pid=4444,
                        requested_port=9000,
                        actual_port=9000,
                        status="running",
                    ),
                },
            )
            engine.state_repository.save_resume_state(
                state=state,
                emit=engine._emit,
                runtime_map_builder=engine_runtime_module.build_runtime_map,
            )

            class _PassingRunner:
                def __init__(self, *_args, **_kwargs) -> None:
                    self.last_result = None

                def run_tests(self, _command, *, cwd=None, env=None, timeout=None):  # noqa: ANN001, ARG002
                    from envctl_engine.test_output.parser_base import TestResult

                    self.last_result = TestResult(
                        passed=5,
                        failed=0,
                        skipped=1,
                        total=6,
                        failed_tests=[],
                        error_details={},
                    )
                    return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _PassingRunner):
                route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            refreshed = engine._try_load_existing_state(mode="trees", strict_mode_match=False)
            self.assertIsNotNone(refreshed)
            assert refreshed is not None
            summaries = refreshed.metadata.get("project_test_summaries")
            self.assertIsInstance(summaries, dict)
            assert isinstance(summaries, dict)
            project_entry = summaries.get("feature-a-1")
            self.assertIsInstance(project_entry, dict)
            assert isinstance(project_entry, dict)
            summary_path = project_entry.get("summary_path")
            self.assertIsInstance(summary_path, str)
            assert isinstance(summary_path, str)
            expected_root = engine.runtime_root / "runs" / state.run_id / "test-results"
            self.assertTrue(Path(summary_path).is_relative_to(expected_root))
            text = Path(summary_path).read_text(encoding="utf-8")
            self.assertIn("No failed tests.", text)
            self.assertEqual(project_entry.get("status"), "passed")
            self.assertEqual(
                refreshed.metadata.get("project_test_results_root"),
                str(Path(summary_path).parent.parent),
            )
            self.assertFalse((repo / "test-results").exists())

    def test_test_action_skips_summary_artifacts_when_no_run_state_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            class _PassingRunner:
                def __init__(self, *_args, **_kwargs) -> None:
                    self.last_result = None

                def run_tests(self, _command, *, cwd=None, env=None, timeout=None):  # noqa: ANN001, ARG002
                    from envctl_engine.test_output.parser_base import TestResult

                    self.last_result = TestResult(
                        passed=3,
                        failed=0,
                        skipped=0,
                        total=3,
                        failed_tests=[],
                        error_details={},
                    )
                    return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _PassingRunner):
                route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertFalse((repo / "test-results").exists())
            self.assertFalse((engine.runtime_root / "runs").exists())

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

    def test_test_action_uses_backend_pytest_fallback_when_backend_tests_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "pyproject.toml").write_text(
                "[project]\nname='backend'\nversion='1.0.0'\n",
                encoding="utf-8",
            )
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            with patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"):
                route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertTrue(
                any(
                    call[0][:3] == ("/usr/bin/python3", "-m", "pytest")
                    and any(str(arg).endswith("/backend/tests") for arg in call[0])
                    for call in fake_runner.run_calls
                ),
                msg=fake_runner.run_calls,
            )

    def test_default_test_command_prefers_backend_pytest_over_root_unittest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            (repo / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "tests" / "test_placeholder.py").write_text(
                "import unittest\n\nclass Placeholder(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            (repo / "backend" / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "pyproject.toml").write_text(
                "[project]\nname='backend'\nversion='1.0.0'\n",
                encoding="utf-8",
            )

            with patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"):
                command = default_test_command(repo)

            self.assertEqual(command, ["/usr/bin/python3", "-m", "pytest", str(repo / "backend" / "tests")])

    def test_test_action_prefers_backend_pytest_when_both_root_and_backend_tests_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "tests" / "test_placeholder.py").write_text(
                "import unittest\n\nclass Placeholder(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            (repo / "backend" / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "pyproject.toml").write_text(
                "[project]\nname='backend'\nversion='1.0.0'\n",
                encoding="utf-8",
            )
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            with patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"):
                route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertTrue(fake_runner.run_calls, msg="expected test command execution")
            command = fake_runner.run_calls[0][0]
            self.assertEqual(command[:3], ("/usr/bin/python3", "-m", "pytest"))
            self.assertIn("envctl_engine.test_output.pytest_progress_plugin", command)
            self.assertTrue(any(str(part).endswith("/backend/tests") for part in command), msg=command)

    def test_default_test_command_uses_package_manager_test_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            (repo / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (repo / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            with patch(
                "envctl_engine.shared.node_tooling.shutil.which",
                side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
            ):
                command = default_test_command(repo)

            self.assertEqual(command, ["pnpm", "run", "test"])

    def test_default_test_commands_include_backend_and_frontend_for_mixed_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
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

            with (
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
            ):
                commands = default_test_commands(repo)

            self.assertEqual(len(commands), 2)
            self.assertEqual(commands[0].command, ["/usr/bin/python3", "-m", "pytest", str(repo / "backend" / "tests")])
            self.assertEqual(commands[0].cwd, repo)
            self.assertEqual(commands[1].command, ["pnpm", "run", "test"])
            self.assertEqual(commands[1].cwd, repo / "frontend")

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
            self.assertIn(("pnpm", "run", "test"), command_set)
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

    def test_test_action_uses_parallel_executor_for_mixed_repo(self) -> None:
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

            executor_calls: dict[str, int] = {"workers": 0, "submitted": 0}

            class _ExecutorStub:
                def __init__(self, max_workers: int) -> None:
                    executor_calls["workers"] = max_workers

                def __enter__(self) -> "_ExecutorStub":
                    return self

                def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
                    _ = exc_type, exc, tb
                    return False

                def submit(self, fn, *args, **kwargs):  # noqa: ANN001
                    executor_calls["submitted"] += 1
                    from concurrent.futures import Future

                    future: Future = Future()
                    try:
                        future.set_result(fn(*args, **kwargs))
                    except Exception as exc:  # pragma: no cover - defensive
                        future.set_exception(exc)
                    return future

            with (
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator.concurrent.futures.ThreadPoolExecutor",
                    side_effect=lambda max_workers: _ExecutorStub(max_workers),
                ),
            ):
                route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(executor_calls["workers"], 2)
            self.assertEqual(executor_calls["submitted"], 2)
            plans = [event for event in engine.events if event.get("event") == "test.suite.plan"]
            self.assertTrue(plans)
            self.assertTrue(bool(plans[-1].get("parallel")))

    def test_test_action_fans_out_across_all_selected_tree_roots_in_parallel(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_a = repo / "trees" / "feature-a" / "1"
            tree_b = repo / "trees" / "feature-b" / "1"
            for tree in (tree_a, tree_b):
                (tree / "backend" / "tests").mkdir(parents=True, exist_ok=True)
                (tree / "backend" / "pyproject.toml").write_text(
                    "[project]\nname='backend'\nversion='1.0.0'\n",
                    encoding="utf-8",
                )
                (tree / "frontend").mkdir(parents=True, exist_ok=True)
                (tree / "frontend" / "package.json").write_text(
                    '{"name":"frontend","scripts":{"test":"vitest run"}}',
                    encoding="utf-8",
                )
                (tree / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            executor_calls: dict[str, int] = {"workers": 0, "submitted": 0}

            class _ExecutorStub:
                def __init__(self, max_workers: int) -> None:
                    executor_calls["workers"] = max_workers

                def __enter__(self) -> "_ExecutorStub":
                    return self

                def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
                    _ = exc_type, exc, tb
                    return False

                def submit(self, fn, *args, **kwargs):  # noqa: ANN001
                    executor_calls["submitted"] += 1
                    from concurrent.futures import Future

                    future: Future = Future()
                    try:
                        future.set_result(fn(*args, **kwargs))
                    except Exception as exc:  # pragma: no cover - defensive
                        future.set_exception(exc)
                    return future

            with (
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator.concurrent.futures.ThreadPoolExecutor",
                    side_effect=lambda max_workers: _ExecutorStub(max_workers),
                ),
            ):
                route = parse_route(["test", "--all"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(executor_calls["workers"], 4)
            self.assertEqual(executor_calls["submitted"], 4)
            self.assertEqual(len(fake_runner.run_calls), 4, msg=fake_runner.run_calls)

            cwd_set = {Path(call[1]).resolve() for call in fake_runner.run_calls}
            self.assertIn(tree_a.resolve(), cwd_set)
            self.assertIn((tree_a / "frontend").resolve(), cwd_set)
            self.assertIn(tree_b.resolve(), cwd_set)
            self.assertIn((tree_b / "frontend").resolve(), cwd_set)

            plans = [event for event in engine.events if event.get("event") == "test.suite.plan"]
            self.assertTrue(plans)
            self.assertEqual(int(plans[-1].get("total", 0)), 4)
            self.assertEqual(sorted(plans[-1].get("projects") or []), ["feature-a-1", "feature-b-1"])

    def test_test_action_parallel_max_flag_controls_worker_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_a = repo / "trees" / "feature-a" / "1"
            tree_b = repo / "trees" / "feature-b" / "1"
            for tree in (tree_a, tree_b):
                (tree / "backend" / "tests").mkdir(parents=True, exist_ok=True)
                (tree / "backend" / "pyproject.toml").write_text(
                    "[project]\nname='backend'\nversion='1.0.0'\n",
                    encoding="utf-8",
                )
                (tree / "frontend").mkdir(parents=True, exist_ok=True)
                (tree / "frontend" / "package.json").write_text(
                    '{"name":"frontend","scripts":{"test":"vitest run"}}',
                    encoding="utf-8",
                )
                (tree / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            executor_calls: dict[str, int] = {"workers": 0, "submitted": 0}

            class _ExecutorStub:
                def __init__(self, max_workers: int) -> None:
                    executor_calls["workers"] = max_workers

                def __enter__(self) -> "_ExecutorStub":
                    return self

                def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
                    _ = exc_type, exc, tb
                    return False

                def submit(self, fn, *args, **kwargs):  # noqa: ANN001
                    executor_calls["submitted"] += 1
                    from concurrent.futures import Future

                    future: Future = Future()
                    try:
                        future.set_result(fn(*args, **kwargs))
                    except Exception as exc:  # pragma: no cover - defensive
                        future.set_exception(exc)
                    return future

            with (
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator.concurrent.futures.ThreadPoolExecutor",
                    side_effect=lambda max_workers: _ExecutorStub(max_workers),
                ),
            ):
                route = parse_route(
                    ["test", "--all", "--test-parallel-max", "4"],
                    env={"ENVCTL_DEFAULT_MODE": "trees"},
                )
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(executor_calls["workers"], 4)
            self.assertEqual(executor_calls["submitted"], 4)

    def test_test_action_parallel_progress_status_reports_queued_and_running(self) -> None:
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
                patch(
                    "envctl_engine.actions.action_command_orchestrator._rich_progress_available",
                    return_value=(False, "forced_unavailable"),
                ),
            ):
                route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                route.flags = {**route.flags, "interactive_command": True, "batch": True}
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            status_messages = [
                str(event.get("message", "")) for event in engine.events if event.get("event") == "ui.status"
            ]
            self.assertTrue(
                any(
                    message.startswith("Tests progress: running ") and "queued " in message
                    for message in status_messages
                ),
                msg=status_messages,
            )
            self.assertTrue(
                any(" • running: " in message and " • done: " in message for message in status_messages),
                msg=status_messages,
            )

    def test_test_action_uses_suite_spinner_group_and_suppresses_single_line_progress(self) -> None:
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

            class _Policy:
                enabled = True
                backend = "rich"
                style = "dots"
                mode = "auto"
                reason = ""
                min_ms = 0
                verbose_events = False

            suite_events: list[str] = []

            class _SuiteSpinnerStub:
                def __init__(self, **kwargs) -> None:  # noqa: ANN003
                    self.enabled = bool(kwargs.get("enabled", False))

                def __enter__(self):
                    suite_events.append("enter")
                    return self

                def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
                    _ = exc_type, exc, tb
                    suite_events.append("exit")
                    return False

                def mark_running(self, execution) -> None:  # noqa: ANN001
                    suite_events.append(f"running:{int(getattr(execution, 'index', 0))}")

                def mark_finished(self, execution, *, success: bool, duration_text: str, parsed: object | None) -> None:  # noqa: ANN001
                    _ = duration_text, parsed
                    marker = "ok" if success else "fail"
                    suite_events.append(f"done:{int(getattr(execution, 'index', 0))}:{marker}")

            with (
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator.resolve_spinner_policy", return_value=_Policy()
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator._rich_progress_available",
                    return_value=(True, ""),
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator.sys.stderr",
                    new=SimpleNamespace(isatty=lambda: True),
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator._TestSuiteSpinnerGroup",
                    side_effect=lambda **kwargs: _SuiteSpinnerStub(**kwargs),
                ),
            ):
                route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                route.flags = {**route.flags, "interactive_command": True, "batch": True}
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertIn("enter", suite_events)
            self.assertIn("exit", suite_events)
            self.assertTrue(any(event.startswith("running:") for event in suite_events), msg=suite_events)
            self.assertTrue(any(event.startswith("done:") for event in suite_events), msg=suite_events)
            status_messages = [
                str(event.get("message", "")) for event in engine.events if event.get("event") == "ui.status"
            ]
            self.assertFalse(
                any(message.startswith("Tests progress: running ") for message in status_messages), msg=status_messages
            )

    def test_test_action_suite_spinner_group_overrides_non_tty_policy_reason(self) -> None:
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

            class _Policy:
                enabled = False
                backend = "rich"
                style = "dots"
                mode = "auto"
                reason = "non_tty"
                min_ms = 0
                verbose_events = False

            suite_events: list[str] = []

            class _SuiteSpinnerStub:
                def __init__(self, **kwargs) -> None:  # noqa: ANN003
                    self.enabled = bool(kwargs.get("enabled", False))

                def __enter__(self):
                    suite_events.append("enter")
                    return self

                def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
                    _ = exc_type, exc, tb
                    suite_events.append("exit")
                    return False

                def mark_running(self, execution) -> None:  # noqa: ANN001
                    suite_events.append(f"running:{int(getattr(execution, 'index', 0))}")

                def mark_finished(self, execution, *, success: bool, duration_text: str, parsed: object | None) -> None:  # noqa: ANN001
                    _ = duration_text, parsed
                    marker = "ok" if success else "fail"
                    suite_events.append(f"done:{int(getattr(execution, 'index', 0))}:{marker}")

            with (
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator.resolve_spinner_policy", return_value=_Policy()
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator._rich_progress_available",
                    return_value=(True, ""),
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator._TestSuiteSpinnerGroup",
                    side_effect=lambda **kwargs: _SuiteSpinnerStub(**kwargs),
                ),
            ):
                route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                route.flags = {**route.flags, "interactive_command": True, "batch": True}
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertIn("enter", suite_events)
            self.assertIn("exit", suite_events)
            self.assertTrue(any(event.startswith("running:") for event in suite_events), msg=suite_events)
            self.assertTrue(any(event.startswith("done:") for event in suite_events), msg=suite_events)
            policy_events = [
                event for event in engine.events if event.get("event") == "test.suite_spinner_group.policy"
            ]
            self.assertTrue(policy_events)
            self.assertTrue(bool(policy_events[-1].get("enabled")))

    def test_interactive_multi_project_test_output_is_grouped_by_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_a = repo / "trees" / "feature-a" / "1"
            tree_b = repo / "trees" / "feature-b" / "1"
            for tree in (tree_a, tree_b):
                (tree / "backend" / "tests").mkdir(parents=True, exist_ok=True)
                (tree / "backend" / "pyproject.toml").write_text(
                    "[project]\nname='backend'\nversion='1.0.0'\n",
                    encoding="utf-8",
                )
                (tree / "frontend").mkdir(parents=True, exist_ok=True)
                (tree / "frontend" / "package.json").write_text(
                    '{"name":"frontend","scripts":{"test":"vitest run"}}',
                    encoding="utf-8",
                )
                (tree / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

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
                route = parse_route(["test", "--all"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                route.flags = {**route.flags, "interactive_command": True, "batch": True}
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(route)

            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertIn("Test execution mode: parallel (4 suites across 2 projects)", rendered)
            self.assertNotIn("Selected test targets:", rendered)
            self.assertIn("feature-a-1", rendered)
            self.assertIn("feature-b-1", rendered)
            self.assertIn("Backend (pytest)", rendered)
            self.assertIn("Frontend (package test)", rendered)

    def test_test_action_sequential_flag_disables_parallel_executor(self) -> None:
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
                patch(
                    "envctl_engine.actions.action_command_orchestrator.concurrent.futures.ThreadPoolExecutor",
                    side_effect=AssertionError("ThreadPoolExecutor should not be used for --test-sequential"),
                ),
            ):
                route = parse_route(
                    ["test", "--project", "feature-a-1", "--test-sequential"],
                    env={"ENVCTL_DEFAULT_MODE": "trees"},
                )
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            plans = [event for event in engine.events if event.get("event") == "test.suite.plan"]
            self.assertTrue(plans)
            self.assertFalse(bool(plans[-1].get("parallel")))

    def test_test_action_parallel_flag_overrides_env_false(self) -> None:
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

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"ENVCTL_ACTION_TEST_PARALLEL": "false"},
            )
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]
            executor_calls: dict[str, int] = {"workers": 0, "submitted": 0}

            class _ExecutorStub:
                def __init__(self, max_workers: int) -> None:
                    executor_calls["workers"] = max_workers

                def __enter__(self) -> "_ExecutorStub":
                    return self

                def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
                    _ = exc_type, exc, tb
                    return False

                def submit(self, fn, *args, **kwargs):  # noqa: ANN001
                    executor_calls["submitted"] += 1
                    from concurrent.futures import Future

                    future: Future = Future()
                    try:
                        future.set_result(fn(*args, **kwargs))
                    except Exception as exc:  # pragma: no cover - defensive
                        future.set_exception(exc)
                    return future

            with (
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator.concurrent.futures.ThreadPoolExecutor",
                    side_effect=lambda max_workers: _ExecutorStub(max_workers),
                ),
            ):
                route = parse_route(
                    ["test", "--project", "feature-a-1", "--test-parallel"],
                    env={"ENVCTL_DEFAULT_MODE": "trees"},
                )
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(executor_calls["workers"], 2)
            self.assertEqual(executor_calls["submitted"], 2)
            plans = [event for event in engine.events if event.get("event") == "test.suite.plan"]
            self.assertTrue(plans)
            self.assertTrue(bool(plans[-1].get("parallel")))

    def test_test_action_interactive_reports_parallel_execution_mode(self) -> None:
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
                route.flags = {**route.flags, "interactive_command": True, "batch": True}
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(route)

            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertIn("Test execution mode: parallel (2 suites)", rendered)
            self.assertNotIn("Backend (pytest) started", rendered)
            self.assertNotIn("Frontend (package test) started", rendered)
            mode_events = [event for event in engine.events if event.get("event") == "test.execution.mode"]
            self.assertTrue(mode_events)
            self.assertEqual(mode_events[-1].get("mode"), "parallel")
            status_messages = [
                str(event.get("message", "")) for event in engine.events if event.get("event") == "ui.status"
            ]
            spinner_events = [
                event
                for event in engine.events
                if event.get("event") == "ui.spinner.lifecycle" and event.get("component") == "action.test.parallel"
            ]
            self.assertTrue(
                any(message.startswith("Tests progress: running ") for message in status_messages)
                or bool(spinner_events)
            )
            self.assertFalse(any("Running bun test script" in message for message in status_messages))
            self.assertFalse(any("Running pytest suite" in message for message in status_messages))

    def test_failed_test_summary_artifacts_are_scoped_per_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_a = repo / "trees" / "feature-a" / "1"
            tree_b = repo / "trees" / "feature-b" / "1"
            for tree in (tree_a, tree_b):
                (tree / "backend" / "tests").mkdir(parents=True, exist_ok=True)
                (tree / "backend" / "pyproject.toml").write_text(
                    "[project]\nname='backend'\nversion='1.0.0'\n",
                    encoding="utf-8",
                )

            engine = PythonEngineRuntime(self._config(repo, runtime), env={"NO_COLOR": "1"})
            state = RunState(
                run_id="run-tests-artifact-multi",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(tree_a),
                        pid=1001,
                        requested_port=8001,
                        actual_port=8001,
                        status="running",
                    ),
                    "feature-b-1 Backend": ServiceRecord(
                        name="feature-b-1 Backend",
                        type="backend",
                        cwd=str(tree_b),
                        pid=1002,
                        requested_port=8002,
                        actual_port=8002,
                        status="running",
                    ),
                },
            )
            engine.state_repository.save_resume_state(
                state=state,
                emit=engine._emit,
                runtime_map_builder=engine_runtime_module.build_runtime_map,
            )

            class _PerProjectFailingRunner:
                def __init__(self, *_args, **_kwargs) -> None:
                    self.last_result = None

                def run_tests(self, _command, *, cwd=None, env=None, timeout=None):  # noqa: ANN001, ARG002
                    from envctl_engine.test_output.parser_base import TestResult

                    cwd_text = str(cwd or "")
                    marker = "feature-a-1" if "feature-a" in cwd_text else "feature-b-1"
                    self.last_result = TestResult(
                        passed=2,
                        failed=1,
                        skipped=0,
                        total=3,
                        failed_tests=[f"{marker}/backend/tests/test_auth.py::test_signup"],
                        error_details={
                            f"{marker}/backend/tests/test_auth.py::test_signup": f"AssertionError: {marker} failed"
                        },
                    )
                    return SimpleNamespace(returncode=1, stdout="", stderr=f"{marker} suite failed")

            with (
                patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _PerProjectFailingRunner),
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
            ):
                route = parse_route(["test", "--all", "frontend=false"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            refreshed = engine._try_load_existing_state(mode="trees", strict_mode_match=False)
            self.assertIsNotNone(refreshed)
            assert refreshed is not None
            summaries = refreshed.metadata.get("project_test_summaries")
            self.assertIsInstance(summaries, dict)
            assert isinstance(summaries, dict)

            first = summaries.get("feature-a-1")
            second = summaries.get("feature-b-1")
            self.assertIsInstance(first, dict)
            self.assertIsInstance(second, dict)
            assert isinstance(first, dict)
            assert isinstance(second, dict)

            first_text = Path(str(first.get("summary_path"))).read_text(encoding="utf-8")
            second_text = Path(str(second.get("summary_path"))).read_text(encoding="utf-8")
            self.assertIn("feature-a-1/backend/tests/test_auth.py::test_signup", first_text)
            self.assertNotIn("feature-b-1/backend/tests/test_auth.py::test_signup", first_text)
            self.assertIn("feature-b-1/backend/tests/test_auth.py::test_signup", second_text)
            self.assertNotIn("feature-a-1/backend/tests/test_auth.py::test_signup", second_text)

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
            self.assertEqual(only_cmd, ("pnpm", "run", "test"))
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
            self.assertEqual(only_cmd[-2:], ("run", "test"))
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

    def test_delete_worktree_supports_project_selection_and_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_a = repo / "trees" / "feature-a" / "1"
            tree_b = repo / "trees" / "feature-b" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_a.mkdir(parents=True, exist_ok=True)
            tree_b.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=1)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            delete_one = parse_route(
                ["delete-worktree", "--project", "feature-a-1"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            code_one = engine.dispatch(delete_one)
            self.assertEqual(code_one, 0)
            self.assertFalse(tree_a.exists())
            self.assertTrue(tree_b.exists())

            delete_all_without_yes = parse_route(
                ["delete-worktree", "--all"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            code_guard = engine.dispatch(delete_all_without_yes)
            self.assertEqual(code_guard, 1)
            self.assertTrue(tree_b.exists())

            delete_all_with_yes = parse_route(
                ["delete-worktree", "--all", "--yes"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            code_all = engine.dispatch(delete_all_with_yes)
            self.assertEqual(code_all, 0)
            self.assertFalse(tree_b.exists())

    def test_delete_worktree_supports_flat_trees_feature_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_a = repo / "trees-feature-a" / "1"
            tree_b = repo / "trees-feature-b" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_a.mkdir(parents=True, exist_ok=True)
            tree_b.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=1)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            delete_one = parse_route(
                ["delete-worktree", "--project", "feature-a-1"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            code_one = engine.dispatch(delete_one)

            self.assertEqual(code_one, 0)
            self.assertFalse(tree_a.exists())
            self.assertTrue(tree_b.exists())

    def test_delete_worktree_runs_blast_cleanup_before_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_a = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_a.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=1)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            cleanup_calls: list[tuple[str, Path, str]] = []

            def fake_blast_worktree_before_delete(*, project_name: str, project_root: Path, source_command: str):
                cleanup_calls.append((project_name, project_root, source_command))
                return []

            engine._blast_worktree_before_delete = fake_blast_worktree_before_delete  # type: ignore[assignment]
            route = parse_route(
                ["delete-worktree", "--project", "feature-a-1"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(cleanup_calls, [("feature-a-1", tree_a.resolve(), "delete-worktree")])
            self.assertFalse(tree_a.exists())

    def test_blast_worktree_alias_routes_to_delete_flow_with_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_a = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_a.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=1)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            cleanup_calls: list[tuple[str, Path, str]] = []

            def fake_blast_worktree_before_delete(*, project_name: str, project_root: Path, source_command: str):
                cleanup_calls.append((project_name, project_root, source_command))
                return []

            engine._blast_worktree_before_delete = fake_blast_worktree_before_delete  # type: ignore[assignment]
            route = parse_route(
                ["blast-worktree", "--project", "feature-a-1"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(cleanup_calls, [("feature-a-1", tree_a.resolve(), "blast-worktree")])
            self.assertFalse(tree_a.exists())

    def test_delete_worktree_dry_run_skips_blast_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_a = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_a.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=1)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            cleanup_calls: list[tuple[str, Path, str]] = []

            def fake_blast_worktree_before_delete(*, project_name: str, project_root: Path, source_command: str):
                cleanup_calls.append((project_name, project_root, source_command))
                return []

            engine._blast_worktree_before_delete = fake_blast_worktree_before_delete  # type: ignore[assignment]
            route = parse_route(
                ["delete-worktree", "--project", "feature-a-1", "--dry-run"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(cleanup_calls, [])
            self.assertTrue(tree_a.exists())


if __name__ == "__main__":
    unittest.main()
