# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.startup.startup_orchestrator_flow_test_support import *


class StartupOrchestratorFlowBootstrapTests(StartupOrchestratorFlowTestCase):
    def test_plan_launch_hook_runs_before_disabled_startup_dashboard_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(
                repo,
                runtime,
                extra={
                    "TREES_STARTUP_ENABLE": "false",
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                },
            )
            context = self._tree_context(repo, "feature-a-1", "feature-a/1", backend_port=8100, frontend_port=9100)
            order: list[str] = []
            engine.planning_worktree_orchestrator._last_plan_selection_result = PlanSelectionResult(
                raw_projects=[(context.name, context.root)],
                selected_contexts=[context],
                created_worktrees=(
                    CreatedPlanWorktree(name=context.name, root=Path(context.root), plan_file="feature/task.md"),
                ),
            )

            with (
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_select_plan_projects", return_value=[context]),
                patch(
                    "envctl_engine.startup.lifecycle.launch_plan_agent_terminals",
                    side_effect=lambda *args, **kwargs: (
                        order.append("launch"),
                        PlanAgentLaunchResult(status="launched", reason="launched", outcomes=()),
                    )[1],
                ),
                patch.object(engine, "_should_enter_post_start_interactive", return_value=False),
                patch.object(
                    engine,
                    "_write_artifacts",
                    side_effect=lambda *args, **kwargs: order.append("write_artifacts"),
                ),
            ):
                code = engine.dispatch(parse_route(["--plan", "feature-a", "--batch"], env={}))

            self.assertEqual(code, 0)
            self.assertEqual(order, ["launch", "write_artifacts"])

    def test_plan_agent_dependency_bootstrap_runs_before_disabled_startup_launch(self) -> None:
        class _RecordingRunner:
            def __init__(self) -> None:
                self.run_calls: list[tuple[tuple[str, ...], str]] = []

            def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = env, timeout
                self.run_calls.append((tuple(str(part) for part in cmd), str(cwd)))
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(
                repo,
                runtime,
                extra={
                    "TREES_STARTUP_ENABLE": "false",
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "ENVCTL_BACKEND_MIGRATIONS_ON_STARTUP": "true",
                },
            )
            context = self._tree_context(repo, "feature-a-1", "feature-a/1", backend_port=8100, frontend_port=9100)
            backend = Path(context.root) / "backend"
            frontend = Path(context.root) / "frontend"
            backend.mkdir(parents=True, exist_ok=True)
            frontend.mkdir(parents=True, exist_ok=True)
            (backend / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
            (backend / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")
            (frontend / "package.json").write_text('{"scripts":{"dev":"vite"}}', encoding="utf-8")
            (frontend / "package-lock.json").write_text("{}", encoding="utf-8")
            runner = _RecordingRunner()
            engine.process_runner = cast(Any, runner)
            engine._command_exists = (  # type: ignore[attr-defined]
                lambda executable: "/" in executable
                or executable in {"npm", "python", "python3", "python3.12", "sh"}
            )
            engine.planning_worktree_orchestrator._last_plan_selection_result = PlanSelectionResult(
                raw_projects=[(context.name, context.root)],
                selected_contexts=[context],
                created_worktrees=(
                    CreatedPlanWorktree(name=context.name, root=Path(context.root), plan_file="feature/task.md"),
                ),
            )
            calls_at_launch: list[tuple[tuple[str, ...], str]] = []

            def _launch(_runtime: object, *, route: object, created_worktrees: tuple[CreatedPlanWorktree, ...]):
                _ = route, created_worktrees
                calls_at_launch.extend(runner.run_calls)
                return PlanAgentLaunchResult(status="launched", reason="launched", outcomes=())

            with (
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_select_plan_projects", return_value=[context]),
                patch("envctl_engine.startup.lifecycle.launch_plan_agent_terminals", side_effect=_launch),
                patch.object(engine, "_should_enter_post_start_interactive", return_value=False),
                patch.object(engine, "_write_artifacts"),
            ):
                code = engine.dispatch(parse_route(["--plan", "feature-a", "--batch"], env={}))

            self.assertEqual(code, 0)
            self.assertTrue(
                any(
                    call[0][1:3] == ("-m", "venv") and call[0][-1].endswith("/backend/venv")
                    for call in calls_at_launch
                ),
                msg=str(calls_at_launch),
            )
            self.assertTrue(
                any(call[0][1:4] == ("-m", "pip", "install") for call in calls_at_launch),
                msg=str(calls_at_launch),
            )
            self.assertTrue(any(call[0][:2] == ("npm", "ci") for call in calls_at_launch), msg=str(calls_at_launch))
            self.assertFalse(
                any(call[0][-3:] == ("alembic", "upgrade", "head") for call in calls_at_launch),
                msg=str(calls_at_launch),
            )

    def test_plan_agent_dependency_bootstrap_respects_no_deps_flag(self) -> None:
        calls_at_launch = self._plan_agent_dependency_bootstrap_calls(["--no-deps"])

        self.assertEqual(calls_at_launch, [])

    def test_plan_agent_dependency_bootstrap_respects_no_infra_flag(self) -> None:
        calls_at_launch = self._plan_agent_dependency_bootstrap_calls(["--no-infra"])

        self.assertEqual(calls_at_launch, [])

    def test_plan_agent_dependency_bootstrap_respects_only_backend_flag(self) -> None:
        calls_at_launch = self._plan_agent_dependency_bootstrap_calls(["--only-backend"])

        self.assertEqual(calls_at_launch, [])

    def test_plan_agent_dependency_bootstrap_respects_only_frontend_flag(self) -> None:
        calls_at_launch = self._plan_agent_dependency_bootstrap_calls(["--only-frontend"])

        self.assertEqual(calls_at_launch, [])

    def test_plan_agent_dependency_bootstrap_failure_skips_launch(self) -> None:
        class _FailingRunner:
            def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = tuple(str(part) for part in cmd)
                if command[1:4] == ("-m", "pip", "install"):
                    return type("Result", (), {"returncode": 1, "stdout": "", "stderr": "pip failed"})()
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(
                repo,
                runtime,
                extra={
                    "TREES_STARTUP_ENABLE": "false",
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                },
            )
            context = self._tree_context(repo, "feature-a-1", "feature-a/1", backend_port=8100, frontend_port=9100)
            backend = Path(context.root) / "backend"
            backend.mkdir(parents=True, exist_ok=True)
            (backend / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
            engine.process_runner = cast(Any, _FailingRunner())
            engine._command_exists = (  # type: ignore[attr-defined]
                lambda executable: "/" in executable or executable in {"python", "python3", "python3.12", "sh"}
            )
            engine.planning_worktree_orchestrator._last_plan_selection_result = PlanSelectionResult(
                raw_projects=[(context.name, context.root)],
                selected_contexts=[context],
                created_worktrees=(
                    CreatedPlanWorktree(name=context.name, root=Path(context.root), plan_file="feature/task.md"),
                ),
            )

            with (
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_select_plan_projects", return_value=[context]),
                patch("envctl_engine.startup.lifecycle.launch_plan_agent_terminals") as launch_mock,
                patch.object(engine, "_write_artifacts"),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(parse_route(["--plan", "feature-a", "--batch"], env={}))

            self.assertEqual(code, 1)
            launch_mock.assert_not_called()
            rendered = out.getvalue()
            self.assertIn("backend bootstrap failed for feature-a-1 during pip install -r requirements.txt", rendered)
