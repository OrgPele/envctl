from __future__ import annotations

from contextlib import contextmanager, redirect_stdout
from io import StringIO
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from envctl_engine.config import load_config
from envctl_engine.runtime.command_router import parse_route
from envctl_engine.planning.plan_agent_launch_support import (
    CreatedPlanWorktree,
    PlanAgentAttachTarget,
    PlanAgentLaunchOutcome,
    PlanAgentLaunchResult,
    PlanSelectionResult,
)
import envctl_engine.runtime.engine_runtime_startup_support as startup_support
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
from envctl_engine.startup.run_reuse_support import RunReuseDecision
from envctl_engine.startup.session import ProjectStartupResult
from envctl_engine.state.models import PortPlan, RequirementsResult, RunState, ServiceRecord
from envctl_engine.ui.status_symbols import STATUS_FAILURE


class StartupOrchestratorFlowTests(unittest.TestCase):
    def _engine(self, repo: Path, runtime: Path, *, extra: dict[str, str] | None = None) -> PythonEngineRuntime:
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(runtime),
                **(extra or {}),
            }
        )
        return PythonEngineRuntime(config, env={})

    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        (repo / "backend").mkdir(parents=True, exist_ok=True)
        (repo / "frontend").mkdir(parents=True, exist_ok=True)
        return repo

    def _main_context(self, repo: Path) -> Any:
        return type(
            "Context",
            (),
            {
                "name": "Main",
                "root": repo,
                "ports": {
                    "backend": PortPlan("Main", 8000, 8000, 8000, "requested"),
                    "frontend": PortPlan("Main", 9000, 9000, 9000, "requested"),
                },
            },
        )()

    def _tree_context(self, repo: Path, name: str, tree_rel: str, *, backend_port: int, frontend_port: int) -> Any:
        root = repo / "trees" / tree_rel
        root.mkdir(parents=True, exist_ok=True)
        return type(
            "Context",
            (),
            {
                "name": name,
                "root": root,
                "ports": {
                    "backend": PortPlan(name, backend_port, backend_port, backend_port, "requested"),
                    "frontend": PortPlan(name, frontend_port, frontend_port, frontend_port, "requested"),
                },
            },
        )()

    def _plan_agent_dependency_bootstrap_calls(self, extra_args: list[str]) -> list[tuple[tuple[str, ...], str]]:
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
                },
            )
            context = self._tree_context(repo, "feature-a-1", "feature-a/1", backend_port=8100, frontend_port=9100)
            backend = Path(context.root) / "backend"
            frontend = Path(context.root) / "frontend"
            backend.mkdir(parents=True, exist_ok=True)
            frontend.mkdir(parents=True, exist_ok=True)
            (backend / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
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
                patch("envctl_engine.startup.startup_orchestrator.launch_plan_agent_terminals", side_effect=_launch),
                patch.object(engine, "_should_enter_post_start_interactive", return_value=False),
                patch.object(engine, "_write_artifacts"),
            ):
                code = engine.dispatch(parse_route(["--plan", "feature-a", "--batch", *extra_args], env={}))

            self.assertEqual(code, 0)
            return calls_at_launch

    def test_disabled_startup_writes_dashboard_state_without_starting_services(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime, extra={"MAIN_STARTUP_ENABLE": "false"})
            captured: dict[str, object] = {}

            route = parse_route([], env={"ENVCTL_DEFAULT_MODE": "main"})
            with (
                patch.object(engine, "_should_enter_post_start_interactive", return_value=False),
                patch.object(
                    engine,
                    "_write_artifacts",
                    side_effect=lambda state, contexts, *, errors: captured.update(
                        {"state": state, "contexts": list(contexts), "errors": list(errors)}
                    ),
                ),
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            state = cast(RunState, captured["state"])
            self.assertEqual(state.services, {})
            self.assertEqual(state.requirements, {})
            self.assertTrue(state.metadata["dashboard_runs_disabled"])
            self.assertIn("dashboard_banner", state.metadata)
            self.assertEqual(captured["errors"], [])

    def test_disabled_startup_reopens_existing_dashboard_run_when_identity_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime, extra={"MAIN_STARTUP_ENABLE": "false"})
            context = self._main_context(repo)
            metadata = startup_support.build_startup_identity_metadata(
                engine,
                runtime_mode="main",
                project_contexts=[context],
            )
            existing_state = RunState(
                run_id="run-dashboard",
                mode="main",
                services={},
                requirements={},
                metadata={
                    **metadata,
                    "dashboard_runs_disabled": True,
                    "repo_scope_id": engine.config.runtime_scope_id,
                },
            )
            saved_states: list[RunState] = []

            with (
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_try_load_existing_state", return_value=existing_state),
                patch.object(engine, "_write_artifacts", side_effect=AssertionError("fresh dashboard state should not be written")),
                patch.object(engine, "_should_enter_post_start_interactive", return_value=False),
                patch.object(
                    engine.state_repository,
                    "save_resume_state",
                    side_effect=lambda *, state, emit, runtime_map_builder: (
                        saved_states.append(state),
                        {},
                    )[1],
                ),
            ):
                code = engine.dispatch(parse_route([], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 0)
            self.assertEqual(len(saved_states), 1)
            self.assertEqual(saved_states[0].run_id, "run-dashboard")
            self.assertEqual(saved_states[0].services, {})
            self.assertEqual(saved_states[0].metadata.get("last_reuse_reason"), "resume_dashboard_exact")

    def test_disabled_startup_creates_fresh_dashboard_run_when_identity_differs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime, extra={"MAIN_STARTUP_ENABLE": "false"})
            context = self._main_context(repo)
            old_engine = self._engine(repo, runtime, extra={"MAIN_STARTUP_ENABLE": "false", "BACKEND_DIR": "api"})
            metadata = startup_support.build_startup_identity_metadata(
                old_engine,
                runtime_mode="main",
                project_contexts=[context],
            )
            existing_state = RunState(
                run_id="run-dashboard",
                mode="main",
                services={},
                requirements={},
                metadata={
                    **metadata,
                    "dashboard_runs_disabled": True,
                    "repo_scope_id": engine.config.runtime_scope_id,
                },
            )
            captured: dict[str, object] = {}

            with (
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_try_load_existing_state", return_value=existing_state),
                patch.object(engine, "_should_enter_post_start_interactive", return_value=False),
                patch.object(
                    engine.state_repository,
                    "save_resume_state",
                    side_effect=AssertionError("dashboard resume should not be used"),
                ),
                patch.object(
                    engine,
                    "_write_artifacts",
                    side_effect=lambda state, contexts, *, errors: captured.update(
                        {"state": state, "contexts": list(contexts), "errors": list(errors)}
                    ),
                ),
            ):
                code = engine.dispatch(parse_route([], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 0)
            state = cast(RunState, captured["state"])
            self.assertNotEqual(state.run_id, "run-dashboard")
            self.assertTrue(state.metadata["dashboard_runs_disabled"])

    def test_strict_truth_failure_terminates_started_services_and_writes_failed_state_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime, extra={"ENVCTL_RUNTIME_TRUTH_MODE": "strict"})

            route = parse_route(["start", "--batch"], env={"ENVCTL_DEFAULT_MODE": "main"})
            result = ProjectStartupResult(
                requirements=RequirementsResult(project="Main", health="healthy"),
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        pid=1234,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
                warnings=[],
            )
            terminated: list[dict[str, ServiceRecord]] = []

            with (
                patch.object(engine, "_start_project_context", return_value=result),
                patch.object(engine, "_reconcile_state_truth", return_value=["Main Backend"]),
                patch.object(engine, "_write_artifacts") as write_artifacts_mock,
                patch.object(
                    engine, "_terminate_started_services", side_effect=lambda services: terminated.append(services)
                ),
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertEqual(len(terminated), 1)
            self.assertEqual(write_artifacts_mock.call_count, 1)
            written_state = write_artifacts_mock.call_args.args[0]
            self.assertTrue(written_state.metadata["failed"])
            self.assertIn("failure_message", written_state.metadata)
            self.assertIn("Main Backend", written_state.services)

    def test_headless_plan_prints_attach_command_from_plan_agent_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime, extra={"TREES_STARTUP_ENABLE": "false"})
            context = self._tree_context(
                repo,
                "feature-a-1",
                "feature-a/1",
                backend_port=8200,
                frontend_port=9200,
            )

            attach_target = PlanAgentAttachTarget(
                repo_root=repo,
                session_name="envctl-test-session",
                window_name="feature-a-1",
                attach_via="attach-session",
                attach_command=("tmux", "attach", "-t", "envctl-test-session"),
                new_session_command=(
                    "ENVCTL_USE_REPO_WRAPPER=1",
                    "/tmp/repo/bin/envctl",
                    "--plan",
                    "feature-a",
                    "--tmux",
                    "--opencode",
                    "--tmux-new-session",
                    "--headless",
                ),
            )

            with (
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_select_plan_projects", return_value=[context]),
                patch.object(
                    engine.planning_worktree_orchestrator,
                    "last_plan_selection_result",
                    return_value=PlanSelectionResult(raw_projects=[], selected_contexts=[context], created_worktrees=()),
                ),
                patch("envctl_engine.startup.startup_orchestrator.launch_plan_agent_terminals", return_value=PlanAgentLaunchResult(status="launched", reason="launched", attach_target=attach_target)),
                patch.object(engine, "_write_artifacts"),
                patch.object(engine, "_should_enter_post_start_interactive", return_value=False),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(parse_route(["--plan", "feature-a", "--tmux", "--opencode", "--headless"], env={"ENVCTL_DEFAULT_MODE": "trees"}))

            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertNotIn("session_id:", rendered)
            self.assertNotIn("run_id:", rendered)
            self.assertIn(
                "existing session: envctl did not create a new AI session because one already exists for this plan/workspace/CLI.",
                rendered,
            )
            self.assertIn("attach: tmux attach -t envctl-test-session", rendered)
            self.assertIn("new session: ENVCTL_USE_REPO_WRAPPER=1 /tmp/repo/bin/envctl --plan feature-a --tmux --opencode --tmux-new-session --headless", rendered)
            self.assertIn("kill: tmux kill-session -t envctl-test-session", rendered)

    def test_existing_omx_plan_session_summary_reuses_selected_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime, extra={"TREES_STARTUP_ENABLE": "false"})
            context = self._tree_context(
                repo,
                "feature-a-1",
                "feature-a/1",
                backend_port=8200,
                frontend_port=9200,
            )

            attach_target = PlanAgentAttachTarget(
                repo_root=repo,
                session_name="omx-feature-session",
                window_name="",
                attach_via="attach-session",
                attach_command=("tmux", "attach", "-t", "omx-feature-session"),
                new_session_command=(
                    "ENVCTL_USE_REPO_WRAPPER=1",
                    "/tmp/repo/bin/envctl",
                    "--plan",
                    "feature-a",
                    "--omx",
                    "--codex",
                    "--tmux-new-session",
                    "--headless",
                ),
            )

            captured_created_worktrees: list[list[str]] = []

            def _record_launch(_runtime: object, *, route: object, created_worktrees: tuple[CreatedPlanWorktree, ...]):
                _ = route
                captured_created_worktrees.append([item.name for item in created_worktrees])
                return PlanAgentLaunchResult(status="launched", reason="launched", attach_target=attach_target)

            with (
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_select_plan_projects", return_value=[context]),
                patch.object(
                    engine.planning_worktree_orchestrator,
                    "last_plan_selection_result",
                    return_value=PlanSelectionResult(raw_projects=[], selected_contexts=[context], created_worktrees=()),
                ),
                patch("envctl_engine.startup.startup_orchestrator.launch_plan_agent_terminals", side_effect=_record_launch),
                patch.object(engine, "_write_artifacts"),
                patch.object(engine, "_should_enter_post_start_interactive", return_value=False),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(parse_route(["--plan", "feature-a", "--omx", "--codex", "--headless"], env={"ENVCTL_DEFAULT_MODE": "trees"}))

            self.assertEqual(code, 0)
            self.assertEqual(captured_created_worktrees, [["feature-a-1"]])
            rendered = out.getvalue()
            self.assertIn(
                "existing session: envctl did not create a new AI session because one already exists for this plan/workspace/CLI.",
                rendered,
            )
            self.assertIn("attach: tmux attach -t omx-feature-session", rendered)
            self.assertIn("new session: ENVCTL_USE_REPO_WRAPPER=1 /tmp/repo/bin/envctl --plan feature-a --omx --codex --tmux-new-session --headless", rendered)
            self.assertIn("kill: tmux kill-session -t omx-feature-session", rendered)

    def test_resume_dashboard_exact_headless_plan_prints_attach_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime, extra={"TREES_STARTUP_ENABLE": "false"})
            context = self._tree_context(
                repo,
                "feature-a-1",
                "feature-a/1",
                backend_port=8200,
                frontend_port=9200,
            )
            attach_target = PlanAgentAttachTarget(
                repo_root=repo,
                session_name="envctl-test-session",
                window_name="feature-a-1",
                attach_via="attach-session",
                attach_command=("tmux", "attach", "-t", "envctl-test-session"),
            )
            existing_state = RunState(
                run_id="run-dashboard",
                mode="trees",
                services={},
                requirements={},
                metadata={"repo_scope_id": engine.config.runtime_scope_id},
            )

            with (
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_select_plan_projects", return_value=[context]),
                patch.object(
                    engine.planning_worktree_orchestrator,
                    "last_plan_selection_result",
                    return_value=PlanSelectionResult(raw_projects=[], selected_contexts=[context], created_worktrees=()),
                ),
                patch(
                    "envctl_engine.startup.startup_orchestrator.launch_plan_agent_terminals",
                    return_value=PlanAgentLaunchResult(status="failed", reason="existing", attach_target=attach_target),
                ),
                patch(
                    "envctl_engine.startup.startup_orchestrator.evaluate_run_reuse",
                    return_value=RunReuseDecision(
                        candidate_state=existing_state,
                        decision_kind="resume_dashboard_exact",
                        reason="exact_match",
                        selected_projects=[{"name": context.name, "root": str(Path(context.root).resolve())}],
                        state_projects=[{"name": context.name, "root": str(Path(context.root).resolve())}],
                    ),
                ),
                patch.object(engine.state_repository, "save_resume_state", return_value={}),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(
                        parse_route(["--plan", "feature-a", "--tmux", "--opencode", "--headless"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                    )

            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertNotIn("Planning mode complete; skipping service startup", rendered)
            self.assertIn("attach: tmux attach -t envctl-test-session", rendered)
            self.assertIn("kill: tmux kill-session -t envctl-test-session", rendered)

    def test_interactive_plan_resume_exact_attaches_plan_agent_instead_of_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime)
            context = self._tree_context(
                repo,
                "feature-a-1",
                "feature-a/1",
                backend_port=8200,
                frontend_port=9200,
            )
            attach_target = PlanAgentAttachTarget(
                repo_root=repo,
                session_name="omx-feature-session",
                window_name="",
                attach_via="attach-session",
                attach_command=("tmux", "attach", "-t", "omx-feature-session"),
            )
            existing_state = RunState(
                run_id="run-existing",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(Path(context.root) / "backend"),
                        pid=123,
                        requested_port=8200,
                        actual_port=8200,
                        status="running",
                    )
                },
                requirements={},
                metadata={"repo_scope_id": engine.config.runtime_scope_id},
            )
            dependency_result = type(
                "DependencyBootstrapResult",
                (),
                {
                    "backend": type("BackendDependency", (), {"manager": "poetry"})(),
                    "frontend": type("FrontendDependency", (), {"manager": "npm"})(),
                    "skipped": (),
                },
            )()
            resumed_routes: list[object] = []

            def _record_resume(route: object) -> int:
                resumed_routes.append(route)
                return 0

            with (
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_select_plan_projects", return_value=[context]),
                patch.object(
                    engine.planning_worktree_orchestrator,
                    "last_plan_selection_result",
                    return_value=PlanSelectionResult(raw_projects=[], selected_contexts=[context], created_worktrees=()),
                ),
                patch(
                    "envctl_engine.startup.startup_orchestrator.prepare_project_dependencies",
                    return_value=dependency_result,
                ),
                patch(
                    "envctl_engine.startup.startup_orchestrator.launch_plan_agent_terminals",
                    return_value=PlanAgentLaunchResult(
                        status="launched",
                        reason="launched",
                        outcomes=(
                            PlanAgentLaunchOutcome(
                                worktree_name=context.name,
                                worktree_root=Path(context.root),
                                surface_id=None,
                                status="launched",
                            ),
                        ),
                        attach_target=attach_target,
                    ),
                ),
                patch(
                    "envctl_engine.startup.startup_orchestrator.evaluate_run_reuse",
                    return_value=RunReuseDecision(
                        candidate_state=existing_state,
                        decision_kind="resume_exact",
                        reason="exact_match",
                        selected_projects=[{"name": context.name, "root": str(Path(context.root).resolve())}],
                        state_projects=[{"name": context.name, "root": str(Path(context.root).resolve())}],
                    ),
                ),
                patch.object(engine, "_resume", side_effect=_record_resume),
                patch("envctl_engine.startup.startup_orchestrator.attach_plan_agent_terminal", return_value=0) as attach_mock,
                patch.object(engine, "_run_interactive_dashboard_loop", return_value=0) as dashboard_mock,
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(
                        parse_route(["--plan", "feature-a", "--omx"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                    )

            self.assertEqual(code, 0)
            attach_mock.assert_called_once_with(engine, attach_target)
            dashboard_mock.assert_not_called()
            self.assertEqual(len(resumed_routes), 1)
            resumed_route = resumed_routes[0]
            self.assertEqual(getattr(resumed_route, "command", ""), "resume")
            self.assertTrue(getattr(resumed_route, "flags", {}).get("batch"))
            self.assertEqual(getattr(resumed_route, "flags", {}).get("_resume_source_command"), "plan")

    def test_interactive_plan_opencode_without_tmux_launches_existing_worktree_and_attaches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime)
            context = self._tree_context(
                repo,
                "feature-a-1",
                "feature-a/1",
                backend_port=8200,
                frontend_port=9200,
            )
            attach_target = PlanAgentAttachTarget(
                repo_root=repo,
                session_name="envctl-opencode-session",
                window_name="feature-a-1",
                attach_via="attach-session",
                attach_command=("tmux", "attach", "-t", "envctl-opencode-session"),
            )
            existing_state = RunState(
                run_id="run-existing",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(Path(context.root) / "backend"),
                        pid=123,
                        requested_port=8200,
                        actual_port=8200,
                        status="running",
                    )
                },
                requirements={},
                metadata={"repo_scope_id": engine.config.runtime_scope_id},
            )
            dependency_result = type(
                "DependencyBootstrapResult",
                (),
                {
                    "backend": type("BackendDependency", (), {"manager": "poetry"})(),
                    "frontend": type("FrontendDependency", (), {"manager": "npm"})(),
                    "skipped": (),
                },
            )()
            captured_launch_worktrees: list[list[str]] = []
            resumed_routes: list[object] = []
            spinner_calls: list[tuple[str, str, bool | None]] = []

            def _record_launch(
                _runtime: object,
                *,
                route: object,
                created_worktrees: tuple[CreatedPlanWorktree, ...],
            ) -> PlanAgentLaunchResult:
                _ = route
                captured_launch_worktrees.append([worktree.name for worktree in created_worktrees])
                if not created_worktrees:
                    return PlanAgentLaunchResult(status="skipped", reason="no_new_worktrees")
                return PlanAgentLaunchResult(
                    status="launched",
                    reason="launched",
                    outcomes=(
                        PlanAgentLaunchOutcome(
                            worktree_name=context.name,
                            worktree_root=Path(context.root),
                            surface_id=None,
                            status="launched",
                        ),
                    ),
                    attach_target=attach_target,
                )

            def _record_resume(route: object) -> int:
                resumed_routes.append(route)
                return 0

            @contextmanager
            def _record_spinner(message: str, *, enabled: bool, start_immediately: bool = True):
                _ = start_immediately
                spinner_calls.append(("start", message, enabled))

                class _SpinnerStub:
                    def update(self, message: str) -> None:
                        spinner_calls.append(("update", message, None))

                    def succeed(self, message: str) -> None:
                        spinner_calls.append(("succeed", message, None))

                    def fail(self, message: str) -> None:
                        spinner_calls.append(("fail", message, None))

                yield _SpinnerStub()

            with (
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_select_plan_projects", return_value=[context]),
                patch.object(
                    engine.planning_worktree_orchestrator,
                    "last_plan_selection_result",
                    return_value=PlanSelectionResult(raw_projects=[], selected_contexts=[context], created_worktrees=()),
                ),
                patch(
                    "envctl_engine.startup.startup_orchestrator.prepare_project_dependencies",
                    return_value=dependency_result,
                ),
                patch(
                    "envctl_engine.startup.startup_orchestrator.launch_plan_agent_terminals",
                    side_effect=_record_launch,
                ),
                patch(
                    "envctl_engine.startup.startup_orchestrator.evaluate_run_reuse",
                    return_value=RunReuseDecision(
                        candidate_state=existing_state,
                        decision_kind="resume_exact",
                        reason="exact_match",
                        selected_projects=[{"name": context.name, "root": str(Path(context.root).resolve())}],
                        state_projects=[{"name": context.name, "root": str(Path(context.root).resolve())}],
                    ),
                ),
                patch.object(engine, "_resume", side_effect=_record_resume),
                patch("envctl_engine.startup.startup_orchestrator.attach_plan_agent_terminal", return_value=0) as attach_mock,
                patch.object(engine, "_run_interactive_dashboard_loop", return_value=0) as dashboard_mock,
                patch("envctl_engine.startup.startup_orchestrator.spinner", side_effect=_record_spinner),
                patch("envctl_engine.startup.startup_orchestrator.resolve_spinner_policy") as policy_mock,
            ):
                policy_mock.side_effect = lambda *_args, **_kwargs: type(
                    "_Policy",
                    (),
                    {
                        "mode": "on",
                        "enabled": True,
                        "reason": "",
                        "backend": "rich",
                        "min_ms": 120,
                        "verbose_events": False,
                    },
                )()
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(
                        parse_route(["--plan", "feature-a", "--opencode"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                    )

            self.assertEqual(code, 0)
            self.assertEqual(captured_launch_worktrees, [["feature-a-1"]])
            attach_mock.assert_called_once_with(engine, attach_target)
            dashboard_mock.assert_not_called()
            self.assertEqual(len(resumed_routes), 1)
            self.assertTrue(getattr(resumed_routes[0], "flags", {}).get("batch"))
            self.assertIn(("start", "Launching OpenCode AI session...", True), spinner_calls)
            self.assertIn(("succeed", "OpenCode AI session ready", None), spinner_calls)
            lifecycle_events = [event for event in engine.events if event.get("event") == "ui.spinner.lifecycle"]
            self.assertTrue(
                any(
                    event.get("op_id") == "plan_agent.launch"
                    and event.get("state") == "start"
                    and event.get("message") == "Launching OpenCode AI session..."
                    for event in lifecycle_events
                )
            )

    def test_headless_plan_agent_handoff_prints_attach_when_local_startup_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime)
            context = self._tree_context(
                repo,
                "feature-a-1",
                "feature-a/1",
                backend_port=8200,
                frontend_port=9200,
            )
            attach_target = PlanAgentAttachTarget(
                repo_root=repo,
                session_name="envctl-feature-session",
                window_name="feature-a-1",
                attach_via="attach-session",
                attach_command=("tmux", "attach", "-t", "envctl-feature-session"),
            )
            launch_result = PlanAgentLaunchResult(
                status="launched",
                reason="launched",
                outcomes=(
                    PlanAgentLaunchOutcome(
                        worktree_name=context.name,
                        worktree_root=Path(context.root),
                        surface_id=None,
                        status="launched",
                    ),
                ),
                attach_target=attach_target,
            )
            captured: dict[str, object] = {}

            with (
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_select_plan_projects", return_value=[context]),
                patch.object(
                    engine.planning_worktree_orchestrator,
                    "last_plan_selection_result",
                    return_value=PlanSelectionResult(raw_projects=[], selected_contexts=[context], created_worktrees=()),
                ),
                patch("envctl_engine.startup.startup_orchestrator.launch_plan_agent_terminals", return_value=launch_result),
                patch.object(
                    engine,
                    "_start_project_context",
                    side_effect=RuntimeError("missing_service_start_command: autodetect_failed_backend"),
                ),
                patch.object(
                    engine,
                    "_write_artifacts",
                    side_effect=lambda state, contexts, *, errors: captured.update(
                        {"state": state, "contexts": list(contexts), "errors": list(errors)}
                    ),
                ),
                patch.object(engine, "_should_enter_post_start_interactive", return_value=False),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(
                        parse_route(
                            ["--plan", "feature-a", "--tmux", "--headless"],
                            env={"ENVCTL_DEFAULT_MODE": "trees"},
                        )
                    )

            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertIn("Implementation session is running, but local app startup failed.", rendered)
            self.assertIn("AI session:", rendered)
            self.assertIn("attach: tmux attach -t envctl-feature-session", rendered)
            self.assertIn("kill: tmux kill-session -t envctl-feature-session", rendered)
            self.assertIn("Local app startup:", rendered)
            self.assertIn("project: feature-a-1", rendered)
            self.assertIn("missing_service_start_command: autodetect_failed_backend", rendered)
            self.assertNotIn("Startup failed:", rendered)
            state = cast(RunState, captured["state"])
            self.assertTrue(state.metadata["plan_agent_handoff_degraded"])
            self.assertTrue(state.metadata["implementation_session_running"])
            self.assertTrue(state.metadata["local_startup_failed"])
            self.assertEqual(state.metadata["plan_agent_session_name"], "envctl-feature-session")
            self.assertEqual(captured["errors"], [])
            launch_events = [event for event in engine.events if event.get("event") == "startup.plan_agent_launch_state"]
            self.assertTrue(launch_events)
            self.assertEqual(launch_events[-1].get("status"), "launched")
            self.assertTrue(launch_events[-1].get("implementation_session_running"))
            self.assertTrue(launch_events[-1].get("codex_goal_enable"))
            warning_events = [event for event in engine.events if event.get("event") == "startup.project.warning"]
            self.assertTrue(warning_events)
            self.assertEqual(warning_events[-1].get("reason"), "plan_agent_handoff_local_startup_failed")
            self.assertTrue(warning_events[-1].get("implementation_session_running"))
            degraded_events = [
                event for event in engine.events if event.get("event") == "startup.plan_agent_handoff.degraded"
            ]
            self.assertTrue(degraded_events)
            self.assertEqual(degraded_events[-1].get("reason"), "missing_service_start_command")
            self.assertEqual(degraded_events[-1].get("route_transport"), "tmux")

    def test_omx_ralph_headless_plan_agent_handoff_survives_local_startup_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime)
            context = self._tree_context(
                repo,
                "feature-a-1",
                "feature-a/1",
                backend_port=8200,
                frontend_port=9200,
            )
            attach_target = PlanAgentAttachTarget(
                repo_root=repo,
                session_name="omx-feature-session",
                window_name="",
                attach_via="attach-session",
                attach_command=("tmux", "attach", "-t", "omx-feature-session"),
            )
            launch_result = PlanAgentLaunchResult(
                status="launched",
                reason="launched",
                outcomes=(
                    PlanAgentLaunchOutcome(
                        worktree_name=context.name,
                        worktree_root=Path(context.root),
                        surface_id=None,
                        status="launched",
                    ),
                ),
                attach_target=attach_target,
            )

            with (
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_select_plan_projects", return_value=[context]),
                patch.object(
                    engine.planning_worktree_orchestrator,
                    "last_plan_selection_result",
                    return_value=PlanSelectionResult(raw_projects=[], selected_contexts=[context], created_worktrees=()),
                ),
                patch("envctl_engine.startup.startup_orchestrator.launch_plan_agent_terminals", return_value=launch_result),
                patch.object(
                    engine,
                    "_start_project_context",
                    side_effect=RuntimeError("missing_service_start_command: autodetect_failed_backend"),
                ),
                patch.object(engine, "_write_artifacts"),
                patch.object(engine, "_should_enter_post_start_interactive", return_value=False),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(
                        parse_route(
                            ["--plan", "feature-a", "--omx", "--ralph", "--headless"],
                            env={"ENVCTL_DEFAULT_MODE": "trees"},
                        )
                    )

            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertIn("Implementation session is running, but local app startup failed.", rendered)
            self.assertIn("attach: tmux attach -t omx-feature-session", rendered)
            self.assertIn("Local app startup:", rendered)
            self.assertNotIn("Startup failed:", rendered)

    def test_strict_truth_does_not_turn_degraded_plan_agent_handoff_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime, extra={"ENVCTL_RUNTIME_TRUTH_MODE": "strict"})
            context = self._tree_context(
                repo,
                "feature-a-1",
                "feature-a/1",
                backend_port=8200,
                frontend_port=9200,
            )
            attach_target = PlanAgentAttachTarget(
                repo_root=repo,
                session_name="envctl-feature-session",
                window_name="feature-a-1",
                attach_via="attach-session",
                attach_command=("tmux", "attach", "-t", "envctl-feature-session"),
            )
            launch_result = PlanAgentLaunchResult(
                status="launched",
                reason="launched",
                outcomes=(
                    PlanAgentLaunchOutcome(
                        worktree_name=context.name,
                        worktree_root=Path(context.root),
                        surface_id=None,
                        status="launched",
                    ),
                ),
                attach_target=attach_target,
            )

            with (
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_select_plan_projects", return_value=[context]),
                patch.object(
                    engine.planning_worktree_orchestrator,
                    "last_plan_selection_result",
                    return_value=PlanSelectionResult(raw_projects=[], selected_contexts=[context], created_worktrees=()),
                ),
                patch("envctl_engine.startup.startup_orchestrator.launch_plan_agent_terminals", return_value=launch_result),
                patch.object(
                    engine,
                    "_start_project_context",
                    side_effect=RuntimeError("missing_service_start_command: autodetect_failed_backend"),
                ),
                patch.object(engine, "_reconcile_state_truth", return_value=["feature-a-1 Backend"]) as reconcile_mock,
                patch.object(engine, "_write_artifacts"),
                patch.object(engine, "_should_enter_post_start_interactive", return_value=False),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(
                        parse_route(
                            ["--plan", "feature-a", "--tmux", "--headless"],
                            env={"ENVCTL_DEFAULT_MODE": "trees"},
                        )
                    )

            self.assertEqual(code, 0)
            reconcile_mock.assert_not_called()
            rendered = out.getvalue()
            self.assertIn("Implementation session is running, but local app startup failed.", rendered)
            self.assertNotIn("service truth degraded after startup", rendered)
            self.assertNotIn("Startup failed:", rendered)
            reconcile_events = [event for event in engine.events if event.get("event") == "state.reconcile"]
            self.assertTrue(reconcile_events)
            self.assertEqual(reconcile_events[-1].get("reason"), "plan_agent_handoff_degraded")
            self.assertTrue(reconcile_events[-1].get("skipped"))

    def test_plan_agent_launch_failed_keeps_startup_failure_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime)
            context = self._tree_context(
                repo,
                "feature-a-1",
                "feature-a/1",
                backend_port=8200,
                frontend_port=9200,
            )

            with (
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_select_plan_projects", return_value=[context]),
                patch.object(
                    engine.planning_worktree_orchestrator,
                    "last_plan_selection_result",
                    return_value=PlanSelectionResult(raw_projects=[], selected_contexts=[context], created_worktrees=()),
                ),
                patch(
                    "envctl_engine.startup.startup_orchestrator.launch_plan_agent_terminals",
                    return_value=PlanAgentLaunchResult(status="failed", reason="missing_executables", outcomes=()),
                ),
                patch.object(
                    engine,
                    "_start_project_context",
                    side_effect=RuntimeError("missing_service_start_command: autodetect_failed_backend"),
                ),
                patch.object(engine, "_write_artifacts"),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(
                        parse_route(
                            ["--plan", "feature-a", "--tmux", "--headless"],
                            env={"ENVCTL_DEFAULT_MODE": "trees"},
                        )
                    )

            self.assertEqual(code, 1)
            rendered = out.getvalue()
            self.assertIn("Startup failed: missing_service_start_command: autodetect_failed_backend", rendered)
            self.assertIn(f"{STATUS_FAILURE} Startup failed: missing_service_start_command", rendered)
            self.assertNotIn("Implementation session is running, but local app startup failed.", rendered)

    def test_startup_failure_final_status_colors_x_and_names_failed_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime)
            engine.env["ENVCTL_UI_COLOR_MODE"] = "on"
            healthy_context = self._tree_context(
                repo,
                "refactoring_supportopia_to_pele_complete_repo_rename-1",
                "refactoring_supportopia_to_pele_complete_repo_rename/1",
                backend_port=8215,
                frontend_port=9215,
            )
            failing_context = self._tree_context(
                repo,
                "refactoring_repository_layout_cleanliness_consolidation-1",
                "refactoring_repository_layout_cleanliness_consolidation/1",
                backend_port=8204,
                frontend_port=9204,
            )

            failure = (
                "Failed to start refactoring_repository_layout_cleanliness_consolidation-1 backend on port 8204: "
                "backend listener not detected for refactoring_repository_layout_cleanliness_consolidation-1 "
                "on port 8204"
            )

            with (
                patch.object(engine, "_discover_projects", return_value=[healthy_context, failing_context]),
                patch.object(engine, "_select_plan_projects", return_value=[healthy_context, failing_context]),
                patch.object(
                    engine.planning_worktree_orchestrator,
                    "last_plan_selection_result",
                    return_value=PlanSelectionResult(
                        raw_projects=[],
                        selected_contexts=[healthy_context, failing_context],
                        created_worktrees=(),
                    ),
                ),
                patch.object(engine, "_start_project_context", side_effect=RuntimeError(failure)),
                patch.object(engine, "_write_artifacts"),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(
                        parse_route(
                            ["--plan", "--headless"],
                            env={"ENVCTL_DEFAULT_MODE": "trees"},
                        )
                    )

            self.assertEqual(code, 1)
            rendered = out.getvalue()
            self.assertIn("\033[31m✗\033[0m", rendered)
            self.assertIn("worktree: refactoring_repository_layout_cleanliness_consolidation-1", rendered)
            self.assertIn(
                "Startup failed: Failed to start refactoring_repository_layout_cleanliness_consolidation-1",
                rendered,
            )

    def test_plain_plan_without_ai_session_keeps_missing_service_command_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime)
            context = self._tree_context(
                repo,
                "feature-a-1",
                "feature-a/1",
                backend_port=8200,
                frontend_port=9200,
            )

            with (
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_select_plan_projects", return_value=[context]),
                patch.object(
                    engine.planning_worktree_orchestrator,
                    "last_plan_selection_result",
                    return_value=PlanSelectionResult(raw_projects=[], selected_contexts=[context], created_worktrees=()),
                ),
                patch.object(
                    engine,
                    "_start_project_context",
                    side_effect=RuntimeError("missing_service_start_command: autodetect_failed_backend"),
                ),
                patch.object(engine, "_write_artifacts"),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(
                        parse_route(["--plan", "feature-a", "--headless"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                    )

            self.assertEqual(code, 1)
            rendered = out.getvalue()
            self.assertIn("Startup failed: missing_service_start_command: autodetect_failed_backend", rendered)
            self.assertNotIn("Implementation session is running, but local app startup failed.", rendered)

    def test_interactive_plan_agent_degraded_handoff_attempts_attach(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime)
            context = self._tree_context(
                repo,
                "feature-a-1",
                "feature-a/1",
                backend_port=8200,
                frontend_port=9200,
            )
            attach_target = PlanAgentAttachTarget(
                repo_root=repo,
                session_name="envctl-feature-session",
                window_name="feature-a-1",
                attach_via="attach-session",
                attach_command=("tmux", "attach", "-t", "envctl-feature-session"),
            )

            with (
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_select_plan_projects", return_value=[context]),
                patch.object(
                    engine.planning_worktree_orchestrator,
                    "last_plan_selection_result",
                    return_value=PlanSelectionResult(raw_projects=[], selected_contexts=[context], created_worktrees=()),
                ),
                patch(
                    "envctl_engine.startup.startup_orchestrator.launch_plan_agent_terminals",
                    return_value=PlanAgentLaunchResult(
                        status="launched",
                        reason="launched",
                        outcomes=(
                            PlanAgentLaunchOutcome(
                                worktree_name=context.name,
                                worktree_root=Path(context.root),
                                surface_id=None,
                                status="launched",
                            ),
                        ),
                        attach_target=attach_target,
                    ),
                ),
                patch.object(
                    engine,
                    "_start_project_context",
                    side_effect=RuntimeError("missing_service_start_command: autodetect_failed_backend"),
                ),
                patch.object(engine, "_write_artifacts"),
                patch("envctl_engine.startup.startup_orchestrator.attach_plan_agent_terminal", return_value=0) as attach_mock,
                patch.object(engine, "_should_enter_post_start_interactive", return_value=True),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(
                        parse_route(["--plan", "feature-a", "--tmux"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                    )

            self.assertEqual(code, 0)
            attach_mock.assert_called_once()
            rendered = out.getvalue()
            self.assertIn("Implementation session is running, but local app startup failed.", rendered)
            self.assertNotIn("Startup failed:", rendered)

    def test_resume_reuse_failure_falls_back_to_fresh_run_id_before_failure_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime)
            context = self._main_context(repo)
            metadata = startup_support.build_startup_identity_metadata(
                engine,
                runtime_mode="main",
                project_contexts=[context],
            )
            existing_state = RunState(
                run_id="run-existing",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
                metadata=metadata,
            )
            captured: dict[str, object] = {}

            out = StringIO()
            with (
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_try_load_existing_state", return_value=existing_state),
                patch.object(engine, "_resume", return_value=1),
                patch.object(engine, "_new_run_id", return_value="run-fresh-after-resume-failure"),
                patch.object(engine, "_start_project_context", side_effect=RuntimeError("fresh startup failed")),
                patch.object(
                    engine,
                    "_write_artifacts",
                    side_effect=lambda state, contexts, *, errors: captured.update(
                        {"state": state, "contexts": list(contexts), "errors": list(errors)}
                    ),
                ),
                redirect_stdout(out),
            ):
                code = engine.dispatch(parse_route(["start", "--batch"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 1)
            written_state = cast(RunState, captured["state"])
            self.assertEqual(written_state.run_id, "run-fresh-after-resume-failure")
            self.assertNotEqual(written_state.run_id, existing_state.run_id)

    def test_reuse_expand_failure_writes_failed_state_to_fresh_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime, extra={"ENVCTL_DEFAULT_MODE": "trees"})
            context_a = self._tree_context(repo, "feature-a-1", "feature-a/1", backend_port=8100, frontend_port=9100)
            context_b = self._tree_context(repo, "feature-b-1", "feature-b/1", backend_port=8200, frontend_port=9200)
            metadata = startup_support.build_startup_identity_metadata(
                engine,
                runtime_mode="trees",
                project_contexts=[context_a],
            )
            existing_state = RunState(
                run_id="run-existing-expand",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(Path(context_a.root) / "backend"),
                        pid=1111,
                        requested_port=8100,
                        actual_port=8100,
                        status="running",
                    )
                },
                metadata=metadata,
            )
            captured: dict[str, object] = {}

            with (
                patch.object(engine, "_discover_projects", return_value=[context_a, context_b]),
                patch.object(engine, "_select_plan_projects", return_value=[context_a, context_b]),
                patch(
                    "envctl_engine.startup.startup_orchestrator.evaluate_run_reuse",
                    return_value=RunReuseDecision(
                        candidate_state=existing_state,
                        decision_kind="reuse_expand",
                        reason="expand_match",
                        selected_projects=[
                            {"name": "feature-a-1", "root": str(Path(context_a.root).resolve())},
                            {"name": "feature-b-1", "root": str(Path(context_b.root).resolve())},
                        ],
                        state_projects=[{"name": "feature-a-1", "root": str(Path(context_a.root).resolve())}],
                    ),
                ),
                patch.object(engine, "_reconcile_state_truth", return_value=[]),
                patch.object(engine, "_new_run_id", return_value="run-fresh-expand-failure"),
                patch.object(engine, "_start_project_context", side_effect=RuntimeError("new project startup failed")),
                patch.object(
                    engine,
                    "_write_artifacts",
                    side_effect=lambda state, contexts, *, errors: captured.update(
                        {"state": state, "contexts": list(contexts), "errors": list(errors)}
                    ),
                ),
            ):
                code = engine.dispatch(parse_route(["--plan", "feature-a,feature-b", "--batch"], env={}))

            self.assertEqual(code, 1)
            written_state = cast(RunState, captured["state"])
            self.assertEqual(written_state.run_id, "run-fresh-expand-failure")
            self.assertNotEqual(written_state.run_id, existing_state.run_id)

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
                    "envctl_engine.startup.startup_orchestrator.launch_plan_agent_terminals",
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
                patch("envctl_engine.startup.startup_orchestrator.launch_plan_agent_terminals", side_effect=_launch),
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
                patch("envctl_engine.startup.startup_orchestrator.launch_plan_agent_terminals") as launch_mock,
                patch.object(engine, "_write_artifacts"),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(parse_route(["--plan", "feature-a", "--batch"], env={}))

            self.assertEqual(code, 1)
            launch_mock.assert_not_called()
            rendered = out.getvalue()
            self.assertIn("backend bootstrap failed for feature-a-1 during pip install -r requirements.txt", rendered)


if __name__ == "__main__":
    unittest.main()
