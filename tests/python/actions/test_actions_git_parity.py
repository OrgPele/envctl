from __future__ import annotations

import os
import shlex
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from envctl_engine.actions.actions_git import default_commit_command, default_pr_command, default_ship_command
from tests.python.actions.actions_parity_test_support import (
    ActionCommandOrchestrator,
    PythonEngineRuntime,
    _ActionsParityTestCase,
    _FakeRunner,
    load_config,
    parse_route,
)


REPO_ROOT = Path(__file__).resolve().parents[3]


class ActionsGitParityTests(_ActionsParityTestCase):
    def test_headless_review_auto_selects_single_main_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_DEFAULT_MODE": "main",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={"ENVCTL_ACTION_ANALYZE_CMD": "sh -lc 'exit 0'"},
            )
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["review", "--headless"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 0, msg=out.getvalue())
            self.assertEqual(len(fake_runner.run_calls), 1, msg=fake_runner.run_calls)
            only_cmd, only_cwd = fake_runner.run_calls[0]
            self.assertEqual(only_cmd, ("sh", "-lc", "exit 0"))
            self.assertEqual(Path(only_cwd).resolve(), repo.resolve())

    def test_headless_review_streams_output_on_tty_without_reprinting_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_DEFAULT_MODE": "main",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={"ENVCTL_ACTION_ANALYZE_CMD": "sh -lc 'exit 0'"},
            )

            class _StreamingRunner:
                def __init__(self) -> None:
                    self.run_calls: list[tuple[tuple[str, ...], str]] = []
                    self.streaming_calls: list[tuple[tuple[str, ...], str]] = []

                def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                    _ = env, timeout
                    self.run_calls.append((tuple(cmd), str(cwd)))
                    return SimpleNamespace(returncode=0, stdout="SHOULD_NOT_BE_PRINTED\n", stderr="")

                def run_streaming(self, cmd, *, cwd=None, env=None, timeout=None, show_spinner=True, echo_output=True):  # noqa: ANN001
                    _ = env, timeout, show_spinner, echo_output
                    self.streaming_calls.append((tuple(cmd), str(cwd)))
                    print("\x1b[36mRICH_REVIEW_BLOCK\x1b[0m")
                    return SimpleNamespace(returncode=0, stdout="RICH_REVIEW_BLOCK\n", stderr="", args=list(cmd))

            fake_runner = _StreamingRunner()
            engine.process_runner = fake_runner  # type: ignore[assignment]

            out = StringIO()
            with (
                patch("envctl_engine.actions.action_command_orchestrator._stdout_is_live_terminal", return_value=True),
                redirect_stdout(out),
            ):
                code = engine.dispatch(parse_route(["review", "--headless"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            rendered = out.getvalue()
            self.assertEqual(code, 0, msg=rendered)
            self.assertEqual(fake_runner.run_calls, [])
            self.assertEqual(len(fake_runner.streaming_calls), 1, msg=fake_runner.streaming_calls)
            self.assertIn("RICH_REVIEW_BLOCK", rendered)
            self.assertEqual(rendered.count("RICH_REVIEW_BLOCK"), 1, msg=rendered)

    def test_action_env_marks_default_headless_pr_routes_non_interactive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            target_root = repo / "trees" / "feature-a" / "1"
            target_root.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            route = parse_route(
                ["pr", "--project", "feature-a-1"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            target = SimpleNamespace(name="feature-a-1", root=target_root)

            env = engine.action_command_orchestrator.action_env(
                "pr",
                [target],
                route=route,
                target=target,
                extra=engine.action_command_orchestrator.action_extra_env(route),
            )

            self.assertEqual(env.get("ENVCTL_ACTION_INTERACTIVE"), "0")

    def test_action_env_keeps_interactive_pr_routes_interactive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            target_root = repo / "trees" / "feature-a" / "1"
            target_root.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            route = parse_route(
                ["pr", "--project", "feature-a-1"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            route.flags = {**route.flags, "interactive_command": True, "batch": True, "pr_base": "main"}
            target = SimpleNamespace(name="feature-a-1", root=target_root)

            env = engine.action_command_orchestrator.action_env(
                "pr",
                [target],
                route=route,
                target=target,
                extra=engine.action_command_orchestrator.action_extra_env(route),
            )

            self.assertEqual(env.get("ENVCTL_ACTION_INTERACTIVE"), "1")
            self.assertEqual(env.get("ENVCTL_PR_BASE"), "main")

    def test_ship_without_project_infers_current_worktree(self) -> None:
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
                env={
                    "ENVCTL_INVOCATION_CWD": str(invocation_cwd),
                    "ENVCTL_ACTION_SHIP_CMD": "sh -lc 'exit 0'",
                },
            )
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["ship"], env={"ENVCTL_DEFAULT_MODE": "main"})
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(len(fake_runner.run_calls), 1)
            self.assertEqual(fake_runner.run_calls[0][1], str(target.resolve()))
            self.assertEqual(fake_runner.run_envs[0]["ENVCTL_ACTION_PROJECT"], "feature-a-1")
            self.assertEqual(fake_runner.run_envs[0]["ENVCTL_ACTION_PROJECT_ROOT"], str(target.resolve()))

    def test_ship_without_project_infers_current_worktree_in_trees_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            target = repo / "trees" / "feature-a" / "1"
            sibling = repo / "trees" / "feature-b" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            target.mkdir(parents=True, exist_ok=True)
            sibling.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "ENVCTL_DEFAULT_MODE": "trees",
                    }
                ),
                env={
                    "ENVCTL_INVOCATION_CWD": str(target),
                    "ENVCTL_ACTION_SHIP_CMD": "sh -lc 'exit 0'",
                },
            )
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["ship"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(len(fake_runner.run_calls), 1)
            self.assertEqual(fake_runner.run_calls[0][1], str(target.resolve()))
            self.assertEqual(fake_runner.run_envs[0]["ENVCTL_ACTION_PROJECT"], "feature-a-1")
            self.assertEqual(fake_runner.run_envs[0]["ENVCTL_ACTION_PROJECT_ROOT"], str(target.resolve()))

    def test_repo_wrapper_ship_targets_external_linked_worktree_in_main_and_trees_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            linked = root / "external-linked-worktree"
            repo.mkdir()

            def git(*args: str, cwd: Path = repo) -> None:
                subprocess.run(
                    ["git", *args],
                    cwd=cwd,
                    check=True,
                    capture_output=True,
                    text=True,
                )

            git("init", "-q", "-b", "main")
            git("config", "user.email", "envctl-test@example.test")
            git("config", "user.name", "Envctl Test")
            (repo / ".envctl").write_text(
                "ENVCTL_DEFAULT_MODE=trees\nMAIN_STARTUP_ENABLE=false\nTREES_STARTUP_ENABLE=false\n",
                encoding="utf-8",
            )
            (repo / "README.md").write_text("# linked worktree ship test\n", encoding="utf-8")
            git("add", "-f", ".envctl", "README.md")
            git("commit", "-q", "-m", "initial")
            git("worktree", "add", "-q", "-b", "feature/external", str(linked))

            invocation_cwd = linked / "nested" / "source"
            invocation_cwd.mkdir(parents=True)
            assertion_script = (
                "import os,sys; from pathlib import Path; "
                "expected=Path(sys.argv[1]).resolve(); "
                "ok=(Path.cwd().resolve()==expected "
                "and os.environ.get('ENVCTL_ACTION_PROJECT')=='feature/external' "
                "and Path(os.environ.get('ENVCTL_ACTION_PROJECT_ROOT','')).resolve()==expected); "
                "raise SystemExit(0 if ok else 9)"
            )
            harmless_ship_command = shlex.join(
                [sys.executable, "-c", assertion_script, str(linked.resolve())]
            )

            for mode in ("trees", "main"):
                with self.subTest(mode=mode):
                    env = dict(os.environ)
                    for key in ("RUN_REPO_ROOT", "ENVCTL_EXECUTION_ROOT", "ENVCTL_INVOCATION_CWD"):
                        env.pop(key, None)
                    env.update(
                        {
                            "ENVCTL_ACTION_SHIP_CMD": harmless_ship_command,
                            "ENVCTL_DEFAULT_MODE": mode,
                            "ENVCTL_UI_BACKEND": "non_interactive",
                            "ENVCTL_USE_REPO_WRAPPER": "1",
                            "RUN_SH_RUNTIME_DIR": str(root / f"runtime-{mode}"),
                        }
                    )
                    completed = subprocess.run(
                        [str(REPO_ROOT / "bin" / "envctl"), "ship", "--human"],
                        cwd=invocation_cwd,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=30,
                        check=False,
                    )

                    self.assertEqual(completed.returncode, 0, msg=completed.stdout + completed.stderr)
                    self.assertIn("ship handoff status for feature/external: success", completed.stdout)
                    self.assertNotIn("ship handoff status for Main", completed.stdout)

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
                all(call[0][0] == sys.executable for call in fake_runner.run_calls),
                msg=fake_runner.run_calls,
            )
            self.assertTrue(
                all(call[0][1:3] == ("-m", "envctl_engine.actions.actions_cli") for call in fake_runner.run_calls),
                msg=fake_runner.run_calls,
            )

    def test_git_action_methods_delegate_to_owner_module(self) -> None:
        self.assertNotIn("default_pr_command", ActionCommandOrchestrator.run_pr_action.__code__.co_names)
        self.assertNotIn("default_commit_command", ActionCommandOrchestrator.run_commit_action.__code__.co_names)
        self.assertNotIn("default_ship_command", ActionCommandOrchestrator.run_ship_action.__code__.co_names)
        self.assertNotIn("default_review_command", ActionCommandOrchestrator.run_review_action.__code__.co_names)

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

    def test_interactive_review_prints_failure_details_and_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            target = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            target.mkdir(parents=True, exist_ok=True)

            details = (
                "Review failed: feature-a-1\n"
                "  Output directory\n"
                "    /tmp/review-output\n"
                "  Details: analyzer could not resolve docs path\n"
            )
            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"ENVCTL_ACTION_ANALYZE_CMD": "sh -lc 'exit 1'"},
            )
            fake_runner = _FakeRunner(returncode=1, stderr=details)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["review", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            route.flags = {**route.flags, "interactive_command": True, "batch": True}
            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            rendered = out.getvalue()
            self.assertIn("review action failed for feature-a-1: Review failed: feature-a-1", rendered)
            self.assertIn("Output directory", rendered)
            self.assertIn("/tmp/review-output", rendered)
            self.assertIn("analyzer could not resolve docs path", rendered)

    def test_review_dispatch_outside_dashboard_does_not_launch_origin_review_tab(self) -> None:
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

            with patch("envctl_engine.ui.dashboard.orchestrator.launch_review_agent_terminal") as launch_mock:
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            launch_mock.assert_not_called()

    def test_headless_review_outside_dashboard_does_not_launch_origin_review_tab(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "ENVCTL_DEFAULT_MODE": "main",
                    }
                ),
                env={"ENVCTL_ACTION_ANALYZE_CMD": "sh -lc 'echo Review summary written: /tmp/review.md'"},
            )
            fake_runner = _FakeRunner(returncode=0, stdout="Review summary written: /tmp/review.md\n")
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["review", "--headless"], env={"ENVCTL_DEFAULT_MODE": "main"})

            with patch("envctl_engine.ui.dashboard.orchestrator.launch_review_agent_terminal") as launch_mock:
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            launch_mock.assert_not_called()

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

    def test_review_action_extra_env_forwards_explicit_review_base_only_when_supplied(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            explicit_route = parse_route(
                ["review", "--review-base", "release/2026.03"],
                env={"ENVCTL_DEFAULT_MODE": "main"},
            )
            explicit_extra = engine.action_command_orchestrator.action_extra_env(explicit_route)
            self.assertEqual(explicit_extra.get("ENVCTL_REVIEW_BASE"), "release/2026.03")

            implicit_route = parse_route(["review"], env={"ENVCTL_DEFAULT_MODE": "main"})
            implicit_extra = engine.action_command_orchestrator.action_extra_env(implicit_route)
            self.assertNotIn("ENVCTL_REVIEW_BASE", implicit_extra)

    def test_ship_action_extra_env_forwards_pr_label_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".envctl").write_text(
                "ENVCTL_SHIP_PR_LABEL_ENABLE=true\n"
                "ENVCTL_SHIP_PR_LABEL=codex-generated\n"
                "ENVCTL_SHIP_NO_CHECKS_GRACE_SECONDS=180\n",
                encoding="utf-8",
            )

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            route = parse_route(["ship"], env={"ENVCTL_DEFAULT_MODE": "main"})

            extra = engine.action_command_orchestrator.ship_action_extra_env(route)

            self.assertEqual(extra.get("ENVCTL_SHIP_PR_LABEL_ENABLE"), "true")
            self.assertEqual(extra.get("ENVCTL_SHIP_PR_LABEL"), "codex-generated")
            self.assertEqual(extra.get("ENVCTL_SHIP_NO_CHECKS_GRACE_SECONDS"), "180")

    def test_default_git_actions_prefer_uv_inside_python_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            (repo / "pyproject.toml").write_text("[project]\nname='envctl'\n", encoding="utf-8")

            with patch("envctl_engine.actions.actions_git.shutil.which", return_value="/usr/bin/uv"):
                self.assertEqual(
                    default_ship_command(repo),
                    ["uv", "run", "--extra", "dev", "python", "-m", "envctl_engine.actions.actions_cli", "ship"],
                )
                self.assertEqual(default_pr_command(repo)[-1], "pr")
                self.assertEqual(default_commit_command(repo)[-1], "commit")

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

            for command in ("pr", "commit", "review"):
                route = parse_route([command, "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                code = engine.dispatch(route)
                self.assertEqual(code, 0, msg=command)

            self.assertTrue(
                all(call[0][0] == sys.executable for call in fake_runner.run_calls),
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

            route = parse_route(["pr", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertTrue(fake_runner.run_calls)
            self.assertEqual(fake_runner.run_calls[0][0][0], sys.executable)
