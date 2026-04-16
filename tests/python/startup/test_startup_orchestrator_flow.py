from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import subprocess
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
    PlanAgentLaunchResult,
    PlanSelectionResult,
)
import envctl_engine.runtime.engine_runtime_startup_support as startup_support
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
from envctl_engine.startup.run_reuse_support import RunReuseDecision
from envctl_engine.startup.session import ProjectStartupResult
from envctl_engine.state.models import PortPlan, RequirementsResult, RunState, ServiceRecord


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


    class _TmuxProbeRunner:
        def __init__(self, *, window_name: str) -> None:
            self.calls: list[list[str]] = []
            self._window_name = window_name
            self._session_created = False

        def _result(
            self, cmd: list[str], *, returncode: int = 0, stdout: str = "", stderr: str = ""
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(args=cmd, returncode=returncode, stdout=stdout, stderr=stderr)

        def run_probe(self, cmd, *, cwd=None, env=None, timeout=None, stdout_target=None, stderr_target=None):  # noqa: ANN001
            _ = cwd, env, timeout, stdout_target, stderr_target
            command = [str(part) for part in cmd]
            self.calls.append(command)
            if command[:3] == ["tmux", "has-session", "-t"]:
                return self._result(command, returncode=0 if self._session_created else 1)
            if command[:3] == ["tmux", "new-session", "-d"]:
                self._session_created = True
                return self._result(command)
            if command[:3] == ["tmux", "new-window", "-d"]:
                return self._result(command)
            if command[:3] == ["tmux", "list-sessions", "-F"]:
                return self._result(command, stdout="")
            if command[:3] == ["tmux", "list-windows", "-t"]:
                return self._result(command, stdout=f"{self._window_name}\n")
            if command[:3] == ["tmux", "send-keys", "-t"]:
                return self._result(command)
            if command[:3] == ["tmux", "capture-pane", "-p"]:
                return self._result(command, stdout="ask anything\n/status\n> ")
            return self._result(command)

        def run(self, cmd, *, cwd=None, env=None, timeout=None, stdin=None):  # noqa: ANN001
            _ = stdin
            return self.run_probe(cmd, cwd=cwd, env=env, timeout=timeout)

        def start_interactive_child(self, *args, **kwargs):  # noqa: ANN001
            _ = args, kwargs
            raise AssertionError("headless startup must not attach an interactive tmux child")

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
                attach_command=("tmux", "attach-session", "-t", "envctl-test-session"),
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
                patch("envctl_engine.startup.startup_orchestrator.attach_plan_agent_terminal") as attach_mock,
                patch.object(engine, "_write_artifacts"),
                patch.object(engine, "_should_enter_post_start_interactive", return_value=False),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(parse_route(["--plan", "feature-a", "--tmux", "--opencode", "--headless"], env={"ENVCTL_DEFAULT_MODE": "trees"}))

            self.assertEqual(code, 0)
            attach_mock.assert_not_called()
            rendered = out.getvalue()
            self.assertNotIn("session_id:", rendered)
            self.assertNotIn("run_id:", rendered)
            self.assertIn("attach: tmux attach-session -t envctl-test-session", rendered)
            self.assertIn("kill: tmux kill-session -t envctl-test-session", rendered)

    def test_disabled_startup_headless_plan_prints_attach_command_without_attaching_terminal(self) -> None:
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
                attach_command=("tmux", "attach-session", "-t", "envctl-test-session"),
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
                    return_value=PlanAgentLaunchResult(status="launched", reason="launched", attach_target=attach_target),
                ),
                patch("envctl_engine.startup.startup_orchestrator.attach_plan_agent_terminal") as attach_mock,
                patch.object(engine, "_write_artifacts"),
                patch.object(engine, "_should_enter_post_start_interactive", return_value=False),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(
                        parse_route(["--plan", "feature-a", "--tmux", "--opencode", "--headless"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                    )

            self.assertEqual(code, 0)
            attach_mock.assert_not_called()
            rendered = out.getvalue()
            self.assertNotIn("Planning mode complete; skipping service startup", rendered)
            self.assertIn("attach: tmux attach-session -t envctl-test-session", rendered)
            self.assertIn("kill: tmux kill-session -t envctl-test-session", rendered)

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
                attach_command=("tmux", "attach-session", "-t", "envctl-test-session"),
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
                patch("envctl_engine.startup.startup_orchestrator.attach_plan_agent_terminal") as attach_mock,
                patch.object(engine.state_repository, "save_resume_state", return_value={}),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(
                        parse_route(["--plan", "feature-a", "--tmux", "--opencode", "--headless"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                    )

            self.assertEqual(code, 0)
            attach_mock.assert_not_called()
            rendered = out.getvalue()
            self.assertNotIn("Planning mode complete; skipping service startup", rendered)
            self.assertIn("attach: tmux attach-session -t envctl-test-session", rendered)
            self.assertIn("kill: tmux kill-session -t envctl-test-session", rendered)

    def test_headless_plan_real_tmux_launch_stays_detached_and_prints_attach_instructions(self) -> None:
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
            runner = self._TmuxProbeRunner(window_name="feature-a-1")
            setattr(engine, "process_runner", runner)

            with (
                patch.object(engine, "_command_exists", side_effect=lambda command: command in {"tmux", "opencode", "zsh"}),
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_select_plan_projects", return_value=[context]),
                patch.object(
                    engine.planning_worktree_orchestrator,
                    "last_plan_selection_result",
                    return_value=PlanSelectionResult(raw_projects=[], selected_contexts=[context], created_worktrees=()),
                ),
                patch("envctl_engine.planning.plan_agent_launch_support._wait_for_tmux_cli_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent_launch_support._submit_tmux_prompt_workflow_step", return_value=None),
                patch("envctl_engine.planning.plan_agent_launch_support.time.sleep", return_value=None),
                patch("envctl_engine.startup.startup_orchestrator.attach_plan_agent_terminal") as attach_mock,
                patch.object(engine, "_write_artifacts"),
                patch.object(engine, "_should_enter_post_start_interactive", return_value=False),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(
                        parse_route(["--plan", "feature-a", "--tmux", "--opencode", "--headless"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                    )

            self.assertEqual(code, 0)
            attach_mock.assert_not_called()
            session_name = next(call[3] for call in runner.calls if call[:3] == ["tmux", "has-session", "-t"])
            rendered = out.getvalue()
            self.assertIn(f"attach: tmux attach-session -t {session_name}", rendered)
            self.assertIn(f"kill: tmux kill-session -t {session_name}", rendered)
            self.assertIn(
                ["tmux", "new-session", "-d", "-s", session_name, "-n", "feature-a-1", "-c", str(context.root), "zsh"],
                runner.calls,
            )
            self.assertFalse(any(call[:2] == ["tmux", "attach"] for call in runner.calls))
            self.assertFalse(any(call[:2] == ["tmux", "attach-session"] for call in runner.calls))
            self.assertFalse(any(call[:2] == ["tmux", "switch-client"] for call in runner.calls))
            self.assertIn(
                ["tmux", "send-keys", "-t", f"{session_name}:feature-a-1", "-l", f"cd {context.root}"],
                runner.calls,
            )
            self.assertIn(["tmux", "send-keys", "-t", f"{session_name}:feature-a-1", "-l", "opencode"], runner.calls)

    def test_headless_plan_inside_tmux_does_not_switch_client_and_prints_manual_attach_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime, extra={"TREES_STARTUP_ENABLE": "false"})
            engine.env["TMUX"] = "/tmp/tmux-1000/default,123,0"
            context = self._tree_context(
                repo,
                "feature-a-1",
                "feature-a/1",
                backend_port=8200,
                frontend_port=9200,
            )
            runner = self._TmuxProbeRunner(window_name="feature-a-1")
            setattr(engine, "process_runner", runner)

            with (
                patch.object(engine, "_command_exists", side_effect=lambda command: command in {"tmux", "opencode", "zsh"}),
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_select_plan_projects", return_value=[context]),
                patch.object(
                    engine.planning_worktree_orchestrator,
                    "last_plan_selection_result",
                    return_value=PlanSelectionResult(raw_projects=[], selected_contexts=[context], created_worktrees=()),
                ),
                patch("envctl_engine.planning.plan_agent_launch_support._wait_for_tmux_cli_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent_launch_support._submit_tmux_prompt_workflow_step", return_value=None),
                patch("envctl_engine.planning.plan_agent_launch_support.time.sleep", return_value=None),
                patch("envctl_engine.startup.startup_orchestrator.attach_plan_agent_terminal") as attach_mock,
                patch.object(engine, "_write_artifacts"),
                patch.object(engine, "_should_enter_post_start_interactive", return_value=False),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(
                        parse_route(["--plan", "feature-a", "--tmux", "--opencode", "--headless"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                    )

            self.assertEqual(code, 0)
            attach_mock.assert_not_called()
            session_name = next(call[3] for call in runner.calls if call[:3] == ["tmux", "has-session", "-t"])
            rendered = out.getvalue()
            self.assertIn(f"attach: tmux switch-client -t {session_name}", rendered)
            self.assertIn(f"kill: tmux kill-session -t {session_name}", rendered)
            self.assertIn(
                ["tmux", "new-session", "-d", "-s", session_name, "-n", "feature-a-1", "-c", str(context.root), "zsh"],
                runner.calls,
            )
            self.assertFalse(any(call[:2] == ["tmux", "attach"] for call in runner.calls))
            self.assertFalse(any(call[:2] == ["tmux", "attach-session"] for call in runner.calls))
            self.assertFalse(any(call[:2] == ["tmux", "switch-client"] for call in runner.calls))

    def test_headless_plan_with_existing_tmux_session_prints_attach_instructions_without_attaching(self) -> None:
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
            existing_session_name = "envctl-existing"
            existing_attach_target = PlanAgentAttachTarget(
                repo_root=repo,
                session_name=existing_session_name,
                window_name="feature-a-1",
                attach_via="attach-session",
                attach_command=("tmux", "attach-session", "-t", existing_session_name),
            )

            with (
                patch.object(engine, "_command_exists", side_effect=lambda command: command in {"tmux", "opencode", "zsh"}),
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_select_plan_projects", return_value=[context]),
                patch.object(
                    engine.planning_worktree_orchestrator,
                    "last_plan_selection_result",
                    return_value=PlanSelectionResult(raw_projects=[], selected_contexts=[context], created_worktrees=()),
                ),
                patch(
                    "envctl_engine.planning.plan_agent_launch_support._find_existing_tmux_attach_target",
                    return_value=existing_attach_target,
                ),
                patch("envctl_engine.startup.startup_orchestrator.attach_plan_agent_terminal") as attach_mock,
                patch.object(engine, "_write_artifacts"),
                patch.object(engine, "_should_enter_post_start_interactive", return_value=False),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(
                        parse_route(["--plan", "feature-a", "--tmux", "--opencode", "--headless"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                    )

            self.assertEqual(code, 0)
            attach_mock.assert_not_called()
            rendered = out.getvalue()
            self.assertIn(f"attach: tmux attach-session -t {existing_session_name}", rendered)
            self.assertIn(f"kill: tmux kill-session -t {existing_session_name}", rendered)

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
                created_worktrees=(CreatedPlanWorktree(name=context.name, root=Path(context.root), plan_file="feature/task.md"),),
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


if __name__ == "__main__":
    unittest.main()
