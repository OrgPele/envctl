from __future__ import annotations

import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tests.python.actions.actions_parity_test_support import (
    PythonEngineRuntime,
    _ActionsParityTestCase,
    _FakeRunner,
    _TtyStringIO,
    _configured_or_default_test_spec,
    action_test_support_module,
    default_test_command,
    default_test_commands,
    frontend_test_path_suggestions,
    parse_route,
    rich_test_command_suggestions,
    strip_ansi,
)
from envctl_engine.actions.actions_test_command_discovery import TestCommandDiscovery


class ActionsTestDiscoveryParityTests(_ActionsParityTestCase):
    def test_interactive_root_unittest_action_prints_resolved_command_and_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_root.mkdir(parents=True, exist_ok=True)
            (tree_root / "tests").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"ENVCTL_UI_HYPERLINK_MODE": "on", "ENVCTL_UI_COLOR_MODE": "on"},
            )
            fake_runner = _FakeRunner(
                returncode=0,
                stdout="..\n----------------------------------------------------------------------\nRan 2 tests in 0.003s\n\nOK\n",
            )
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            route.flags = {**route.flags, "interactive_command": True, "batch": True}

            with patch(
                "envctl_engine.actions.action_command_orchestrator._rich_progress_available",
                return_value=(False, "forced_unavailable"),
            ):
                out = _TtyStringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(route)

            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertIn("\x1b]8;;file://", rendered)
            visible = strip_ansi(rendered)
            self.assertIn("command: ", visible)
            self.assertIn("-m unittest discover -s tests -t . -p test_*.py", visible)
            self.assertIn(f"cwd: {tree_root.resolve()}", visible)
            self.assertIn("2 passed, 0 failed, 0 skipped", visible)
            self.assertIn("Repository tests (unittest)", visible)

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

    def test_test_command_suggestions_describe_backend_and_frontend_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "requirements.txt").write_text("pytest\n", encoding="utf-8")
            frontend = repo / "frontend"
            frontend.mkdir(parents=True, exist_ok=True)
            (frontend / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (frontend / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            with (
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
            ):
                suggestions = rich_test_command_suggestions(repo)
                commands = default_test_commands(repo)

            self.assertEqual([suggestion.source for suggestion in suggestions], ["backend_pytest", "frontend_package_test"])
            self.assertEqual(suggestions[0].command_text, "/usr/bin/python3 -m pytest " + str(repo / "backend" / "tests"))
            self.assertEqual(suggestions[0].label, "Backend pytest")
            self.assertEqual(suggestions[0].confidence, "high")
            self.assertIn("backend/tests", suggestions[0].reason)
            self.assertEqual(suggestions[1].command_text, "pnpm run test")
            self.assertEqual(suggestions[1].cwd, repo / "frontend")
            self.assertEqual([command.source for command in commands], ["backend_pytest", "frontend_package_test"])

    def test_test_command_suggestions_include_root_pytest_before_unittest_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            (repo / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "pyproject.toml").write_text(
                "[tool.pytest.ini_options]\ntestpaths = ['tests']\n",
                encoding="utf-8",
            )

            with patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"):
                suggestions = rich_test_command_suggestions(repo, include_backend=True, include_frontend=False)
                commands = default_test_commands(repo, include_backend=True, include_frontend=False)

            self.assertEqual([suggestion.source for suggestion in suggestions], ["root_pytest"])
            self.assertEqual(suggestions[0].command_text, "/usr/bin/python3 -m pytest tests")
            self.assertIn("root pytest", suggestions[0].label.lower())
            self.assertEqual(commands[0].source, "root_pytest")
            self.assertEqual(commands[0].command, ["/usr/bin/python3", "-m", "pytest", "tests"])

    def test_test_action_uses_root_pytest_when_root_pytest_config_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "tests" / "test_sample.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
            (repo / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            with patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"):
                route = parse_route(
                    ["test", "--project", "feature-a-1", "frontend=false"],
                    env={"ENVCTL_DEFAULT_MODE": "trees"},
                )
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(len(fake_runner.run_calls), 1, msg=fake_runner.run_calls)
            command, cwd = fake_runner.run_calls[0]
            self.assertEqual(command[:3], ("/usr/bin/python3", "-m", "pytest"))
            self.assertIn("envctl_engine.test_output.pytest_progress_plugin", command)
            self.assertIn("tests", command)
            self.assertEqual(Path(cwd).resolve(), repo.resolve())

    def test_test_command_suggestions_keep_root_unittest_as_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            (repo / "tests").mkdir(parents=True, exist_ok=True)

            with patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"):
                suggestions = rich_test_command_suggestions(repo, include_backend=True, include_frontend=False)

            self.assertEqual([suggestion.source for suggestion in suggestions], ["root_unittest"])
            self.assertEqual(
                suggestions[0].command_text,
                "/usr/bin/python3 -m unittest discover -s tests -t . -p test_*.py",
            )
            self.assertEqual(suggestions[0].confidence, "medium")

    def test_frontend_test_path_suggestions_label_detected_and_common_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            frontend = repo / "frontend"
            (frontend / "src").mkdir(parents=True, exist_ok=True)
            (frontend / "tests").mkdir(parents=True, exist_ok=True)
            (frontend / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (frontend / "src" / "app.test.ts").write_text("it('works', () => {})\n", encoding="utf-8")

            suggestions = frontend_test_path_suggestions(repo)

            self.assertEqual([suggestion.path for suggestion in suggestions], ["frontend/src", "frontend/tests"])
            self.assertEqual(suggestions[0].confidence, "high")
            self.assertIn("test/spec", suggestions[0].reason)
            self.assertEqual(suggestions[1].confidence, "low")

    def test_default_test_commands_append_frontend_test_path_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            frontend = repo / "frontend"
            frontend.mkdir(parents=True, exist_ok=True)
            (frontend / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (frontend / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            with patch(
                "envctl_engine.shared.node_tooling.shutil.which",
                side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
            ):
                commands = default_test_commands(repo, frontend_test_path="src")

            self.assertEqual(len(commands), 1)
            self.assertEqual(commands[0].command, ["pnpm", "run", "test", "--", "src"])
            self.assertEqual(commands[0].cwd, repo / "frontend")

    def test_default_test_commands_normalize_repo_relative_frontend_test_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            frontend = repo / "frontend"
            frontend.mkdir(parents=True, exist_ok=True)
            (frontend / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (frontend / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            with patch(
                "envctl_engine.shared.node_tooling.shutil.which",
                side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
            ):
                commands = default_test_commands(repo, frontend_test_path="frontend/src")

            self.assertEqual(len(commands), 1)
            self.assertEqual(commands[0].command, ["pnpm", "run", "test", "--", "src"])
            self.assertEqual(commands[0].cwd, repo / "frontend")

    def test_command_discovery_object_keeps_default_and_suggestion_precedence_together(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "requirements.txt").write_text("pytest\n", encoding="utf-8")
            frontend = repo / "frontend"
            frontend.mkdir(parents=True, exist_ok=True)
            (frontend / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (frontend / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            with patch(
                "envctl_engine.shared.node_tooling.shutil.which",
                side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
            ):
                discovery = TestCommandDiscovery(
                    repo,
                    detect_python_bin_fn=lambda _project_root, _base_dir: "/usr/bin/python3",
                )
                commands = discovery.default_commands()
                suggestions = discovery.suggestions()

            self.assertEqual([command.source for command in commands], ["backend_pytest", "frontend_package_test"])
            self.assertEqual([suggestion.source for suggestion in suggestions], ["backend_pytest", "frontend_package_test"])
            self.assertTrue(all(suggestion.is_default for suggestion in suggestions))

    def test_test_action_appends_frontend_test_path_to_configured_frontend_test_command(self) -> None:
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
                        "MAIN_BACKEND_ENABLE=false",
                        "MAIN_FRONTEND_ENABLE=true",
                        "TREES_BACKEND_ENABLE=false",
                        "TREES_FRONTEND_ENABLE=true",
                        "ENVCTL_FRONTEND_TEST_CMD=pnpm run test",
                        "ENVCTL_FRONTEND_TEST_PATH=src",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            frontend = tree_root / "frontend"
            src_dir = frontend / "src"
            src_dir.mkdir(parents=True, exist_ok=True)
            (frontend / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (frontend / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(
                ["test", "--project", "feature-a-1", "backend=false", "frontend=true"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            with patch(
                "envctl_engine.runtime.engine_runtime_commands.shutil.which",
                side_effect=lambda name: f"/usr/bin/{name}",
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertTrue(fake_runner.run_calls)
            self.assertEqual(fake_runner.run_calls[0][0][:5], ("pnpm", "run", "test", "--", "src"))
            if len(fake_runner.run_calls[0][0]) > 5:
                self.assertEqual(fake_runner.run_calls[0][0][5], "--reporter=default")
                self.assertTrue(fake_runner.run_calls[0][0][6].startswith("--reporter="))

    def test_test_action_normalizes_repo_relative_frontend_test_path_for_configured_frontend_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".envctl").write_text(
                "\n".join(
                    [
                        "ENVCTL_DEFAULT_MODE=main",
                        "MAIN_BACKEND_ENABLE=false",
                        "MAIN_FRONTEND_ENABLE=true",
                        "TREES_BACKEND_ENABLE=false",
                        "TREES_FRONTEND_ENABLE=true",
                        "ENVCTL_FRONTEND_TEST_CMD=pnpm run test",
                        "ENVCTL_FRONTEND_TEST_PATH=frontend/src",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            frontend = repo / "frontend"
            (frontend / "src").mkdir(parents=True, exist_ok=True)
            (frontend / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (frontend / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(
                ["test", "backend=false", "frontend=true"],
                env={"ENVCTL_DEFAULT_MODE": "main"},
            )
            with patch(
                "envctl_engine.runtime.engine_runtime_commands.shutil.which",
                side_effect=lambda name: f"/usr/bin/{name}",
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertTrue(fake_runner.run_calls)
            self.assertEqual(fake_runner.run_calls[0][0][:5], ("pnpm", "run", "test", "--", "src"))
            if len(fake_runner.run_calls[0][0]) > 5:
                self.assertEqual(fake_runner.run_calls[0][0][5], "--reporter=default")
                self.assertTrue(fake_runner.run_calls[0][0][6].startswith("--reporter="))

    def test_configured_backend_and_frontend_test_commands_keep_runner_suite_labels(self) -> None:
        target = action_test_support_module.TestTargetContext(
            project_name="Main",
            project_root=Path("/tmp/repo"),
            target_obj=None,
        )

        backend_spec = _configured_or_default_test_spec(
            raw_command="python -m pytest backend/tests",
            target=target,
            repo_root=Path("/tmp/repo"),
            include_backend=True,
            include_frontend=False,
            frontend_test_path=None,
            split_command=lambda raw, _replacements: raw.split(),
            replacements_for_target=lambda _target: {},
        )
        frontend_spec = _configured_or_default_test_spec(
            raw_command="pnpm run test",
            target=target,
            repo_root=Path("/tmp/repo"),
            include_backend=False,
            include_frontend=True,
            frontend_test_path="src",
            split_command=lambda raw, _replacements: raw.split(),
            replacements_for_target=lambda _target: {},
        )

        self.assertIsNotNone(backend_spec)
        self.assertIsNotNone(frontend_spec)
        self.assertEqual(backend_spec.source, "backend_pytest")
        self.assertEqual(frontend_spec.source, "frontend_package_test")

    def test_configured_backend_python_test_command_uses_poetry_project_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            backend = repo / "backend"
            backend.mkdir(parents=True, exist_ok=True)
            (backend / "pyproject.toml").write_text("[tool.poetry]\nname = 'backend'\n", encoding="utf-8")
            target = action_test_support_module.TestTargetContext(
                project_name="Main",
                project_root=repo,
                target_obj=None,
            )

            with patch("envctl_engine.actions.action_test_support.shutil.which", return_value="/usr/bin/poetry"):
                backend_spec = _configured_or_default_test_spec(
                    raw_command="python3.12 -m pytest backend/tests",
                    target=target,
                    repo_root=repo,
                    include_backend=True,
                    include_frontend=False,
                    frontend_test_path=None,
                    split_command=lambda raw, _replacements: raw.split(),
                    replacements_for_target=lambda _target: {},
                )

            self.assertIsNotNone(backend_spec)
            self.assertEqual(backend_spec.source, "backend_pytest")
            self.assertEqual(
                backend_spec.command,
                ["poetry", "--project", str(backend), "run", "python", "-m", "pytest", "backend/tests"],
            )

    def test_shared_configured_root_unittest_command_keeps_repository_suite_label(self) -> None:
        target = action_test_support_module.TestTargetContext(
            project_name="Main",
            project_root=Path("/tmp/repo"),
            target_obj=None,
        )

        specs = action_test_support_module.build_test_execution_specs(
            repo_root=Path("/tmp/repo"),
            target_contexts=[target],
            shared_raw_command="python3.12 -m unittest discover -s tests -t . -p test_*.py",
            backend_raw_command=None,
            frontend_raw_command=None,
            include_backend=True,
            include_frontend=False,
            frontend_test_path=None,
            run_all=False,
            untested=False,
            split_command=lambda raw, _replacements: raw.split(),
            replacements_for_target=lambda _target: {},
            is_legacy_tree_test_script=lambda _cmd: False,
        )

        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].spec.source, "root_unittest")
        self.assertEqual(specs[0].resolved_source, "root_unittest")
