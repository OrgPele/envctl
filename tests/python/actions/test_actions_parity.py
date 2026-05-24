from __future__ import annotations

import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.python.actions.actions_parity_test_support import (
    PYTHON_ROOT,
    PythonEngineRuntime,
    _ActionsParityTestCase,
    _FakeRunner,
    load_config,
    action_test_support_module,
    parse_route,
    suggest_backend_test_command,
    suggest_frontend_test_command,
)


class ActionsParityTests(_ActionsParityTestCase):
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

    def test_action_commands_require_explicit_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-b" / "1").mkdir(parents=True, exist_ok=True)

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
            (repo / "trees" / "feature-b" / "1").mkdir(parents=True, exist_ok=True)

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

    def test_action_env_strips_repo_wrapper_launcher_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            target_root = repo / "trees" / "feature-a" / "1"
            target_root.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "ENVCTL_USE_REPO_WRAPPER": "1",
                    "ENVCTL_WRAPPER_ORIGINAL_ARGV0": "envctl",
                    "ENVCTL_WRAPPER_PYTHON_REEXEC": "1",
                },
            )
            route = parse_route(
                ["test", "--project", "feature-a-1"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            target = SimpleNamespace(name="feature-a-1", root=target_root)

            env = engine.action_command_orchestrator.action_env(
                "test",
                [target],
                route=route,
                target=target,
                extra=None,
            )

            self.assertNotIn("ENVCTL_USE_REPO_WRAPPER", env)
            self.assertNotIn("ENVCTL_WRAPPER_ORIGINAL_ARGV0", env)
            self.assertNotIn("ENVCTL_WRAPPER_PYTHON_REEXEC", env)

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

    def test_test_focused_without_project_infers_current_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            target = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            target.mkdir(parents=True, exist_ok=True)
            (target / "MAIN_TASK.md").write_text("# Feature A\n", encoding="utf-8")
            invocation_cwd = target / "backend" / "src"
            invocation_cwd.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "ENVCTL_DEFAULT_MODE": "main",
                    }
                ),
                env={"ENVCTL_INVOCATION_CWD": str(invocation_cwd)},
            )
            observed_contexts: list[tuple[str, Path]] = []

            def fake_test_focused(context, *, json_output: bool = False, dry_run: bool = False):  # noqa: ANN001, ANN202
                observed_contexts.append((str(context.project_name), Path(context.project_root)))
                self.assertFalse(json_output)
                self.assertFalse(dry_run)
                return 0

            route = parse_route(["test-focused"], env={"ENVCTL_DEFAULT_MODE": "main"})
            with patch(
                "envctl_engine.actions.action_test_plan_support.run_test_plan_action",
                side_effect=fake_test_focused,
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(observed_contexts, [("feature-a-1", target.resolve())])

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
            self.assertIn(str(PYTHON_ROOT), env["PYTHONPATH"])
            self.assertEqual(env.get("GIT_TERMINAL_PROMPT"), "0")
            self.assertEqual(env.get("GH_PROMPT_DISABLED"), "1")
            self.assertEqual(env.get("GCM_INTERACTIVE"), "Never")

    def test_single_value_suggestion_wrappers_remain_compatible(self) -> None:
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
                backend = suggest_backend_test_command(repo)
                frontend_command = suggest_frontend_test_command(repo)

            self.assertEqual(backend, "/usr/bin/python3 -m pytest " + str(repo / "backend" / "tests"))
            self.assertEqual(frontend_command, "pnpm run test")

    def test_shared_configured_frontend_package_test_runs_from_frontend_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            frontend = repo / "frontend"
            frontend.mkdir(parents=True, exist_ok=True)
            (frontend / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )

            target = action_test_support_module.TestTargetContext(
                project_name="Main",
                project_root=repo,
                target_obj=None,
            )

            specs = action_test_support_module.build_test_execution_specs(
                repo_root=repo,
                target_contexts=[target],
                shared_raw_command="pnpm run test",
                backend_raw_command=None,
                frontend_raw_command=None,
                include_backend=False,
                include_frontend=True,
                frontend_test_path="src",
                run_all=False,
                untested=False,
                split_command=lambda raw, _replacements: raw.split(),
                replacements_for_target=lambda _target: {},
                is_legacy_tree_test_script=lambda _cmd: False,
            )

            self.assertEqual(len(specs), 1)
            self.assertEqual(specs[0].spec.command, ["pnpm", "run", "test", "--", "src"])
            self.assertEqual(specs[0].spec.cwd, frontend)
            self.assertEqual(specs[0].spec.source, "frontend_package_test")

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

