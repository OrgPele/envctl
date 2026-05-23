from __future__ import annotations

import json
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import cast
from unittest.mock import patch

from envctl_engine.planning.plan_agent_launch_support import (
    PlanAgentAttachTarget,
    PlanAgentLaunchOutcome,
    PlanAgentLaunchResult,
)
from envctl_engine.runtime.command_router import parse_route
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
from envctl_engine.startup.session import ProjectStartupResult
from envctl_engine.state.models import RequirementsResult, ServiceRecord

from tests.python.runtime.engine_runtime_real_startup_test_support import (
    _EngineRuntimeRealStartupTestCase,
    _FakeProcessRunner,
)


class EngineRuntimePlanStartupTests(_EngineRuntimeRealStartupTestCase):
    def test_plan_planning_prs_runs_pr_action_and_skips_startup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"ENVCTL_ACTION_PR_CMD": "sh -lc 'exit 0'"},
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--planning-prs", "feature-a", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(fake_runner.start_background_calls, [])
            self.assertTrue(
                any(len(call[0]) >= 2 and call[0][0] == "sh" and call[0][1] == "-lc" for call in fake_runner.run_calls)
            )
            self.assertIn("Planning PR mode complete; skipping service startup.", out.getvalue())

    def test_plan_planning_prs_uses_default_pr_command_and_skips_startup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
            (repo / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--planning-prs", "feature-a", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(fake_runner.start_background_calls, [])
            self.assertIn("Planning PR mode complete; skipping service startup.", out.getvalue())

    def test_plan_feature_launches_only_new_worktrees(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "feature").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "feature" / "task.md").write_text("# task\n", encoding="utf-8")

            engine = PythonEngineRuntime(
                self._config(
                    repo,
                    runtime,
                    extra={
                        "TREES_STARTUP_ENABLE": "false",
                        "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                        "ENVCTL_PLAN_AGENT_CODEX_CYCLES": "2",
                        "ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK": "true",
                    },
                ),
                env={"CMUX_WORKSPACE_ID": "workspace:4"},
            )
            launches: list[list[str]] = []

            with patch(
                "envctl_engine.startup.lifecycle.launch_plan_agent_terminals",
                side_effect=lambda _runtime, *, route, created_worktrees: (
                    launches.append([item.name for item in created_worktrees]),
                    PlanAgentLaunchResult(status="launched", reason="launched", outcomes=()),
                )[1],
            ):
                first_code = engine.dispatch(parse_route(["--plan", "feature/task", "--batch"], env={}))
                second_code = engine.dispatch(parse_route(["--plan", "feature/task", "--batch"], env={}))

            self.assertEqual(first_code, 0)
            self.assertEqual(second_code, 0)
            self.assertEqual(launches, [["feature_task-1"], []])

    def test_plan_feature_superset_transport_reaches_startup_handoff_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "feature").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "feature" / "task.md").write_text("# task\n", encoding="utf-8")

            engine = PythonEngineRuntime(
                self._config(
                    repo,
                    runtime,
                    extra={
                        "TREES_STARTUP_ENABLE": "false",
                        "SUPERSET": "true",
                        "SUPERSET_PROJECT": "proj-1",
                        "ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK": "true",
                    },
                ),
                env={},
            )
            seen: list[tuple[str, ...]] = []

            def _fake_launch(_runtime, *, route, created_worktrees):  # noqa: ANN001, ANN202
                _ = route
                seen.append(tuple(item.name for item in created_worktrees))
                return PlanAgentLaunchResult(
                    status="launched",
                    reason="launched",
                    outcomes=(
                        PlanAgentLaunchOutcome(
                            worktree_name=created_worktrees[0].name,
                            worktree_root=created_worktrees[0].root,
                            surface_id="ws-123",
                            status="launched",
                        ),
                    ),
                )

            with patch("envctl_engine.startup.lifecycle.launch_plan_agent_terminals", side_effect=_fake_launch):
                code = engine.dispatch(parse_route(["--plan", "feature/task", "--batch"], env={}))

            self.assertEqual(code, 0)
            self.assertEqual(seen, [("feature_task-1",)])
            launch_events = [
                event for event in engine.events if event.get("event") == "startup.plan_agent_launch_state"
            ]
            self.assertEqual(len(launch_events), 1)
            self.assertEqual(launch_events[0]["status"], "launched")
            self.assertEqual(launch_events[0]["launched_worktrees"], ["feature_task-1"])

    def test_plan_feature_omx_launch_uses_managed_bootstrap_without_custom_passthrough(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "feature").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "feature" / "task.md").write_text("# task\n", encoding="utf-8")

            engine = PythonEngineRuntime(
                self._config(
                    repo,
                    runtime,
                    extra={
                        "TREES_STARTUP_ENABLE": "false",
                        "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                        "ENVCTL_PLAN_AGENT_CLI_CMD": "codex --model gpt-5.4 --dangerously-bypass-approvals-and-sandbox",
                        "ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK": "true",
                    },
                ),
                env={},
            )
            fake_runner = _FakeProcessRunner()
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            popen_calls: list[dict[str, object]] = []

            class _DummyPopen:
                def __init__(self, cmd, **kwargs):  # noqa: ANN001
                    popen_calls.append({"cmd": list(cmd), **kwargs})
                    omx_root = Path(str(kwargs["env"]["OMX_ROOT"]))
                    session_path = omx_root / ".omx" / "state" / "session.json"
                    session_path.parent.mkdir(parents=True, exist_ok=True)
                    worktree_root = Path(str(kwargs["cwd"]))
                    session_path.write_text(
                        json.dumps(
                            {
                                "session_id": "omx-session-123",
                                "native_session_id": "omx-feature-session",
                                "cwd": str(worktree_root.resolve()),
                            }
                        ),
                        encoding="utf-8",
                    )

                def poll(self):
                    return 0

                def wait(self, timeout=None):  # noqa: ANN001
                    return 0

            with (
                patch.object(engine, "_command_exists", return_value=True),
                patch("envctl_engine.planning.plan_agent.omx_transport.subprocess.Popen", _DummyPopen),
                patch("envctl_engine.planning.plan_agent.omx_transport._git_branch_name", return_value="feature/task"),
                patch("envctl_engine.planning.plan_agent.launch._run_tmux_existing_session_workflow", return_value=None),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(parse_route(["--plan", "feature/task", "--omx", "--codex", "--headless"], env={}))

            self.assertEqual(code, 0)
            self.assertEqual(len(popen_calls), 1)
            cmd = cast(list[str], popen_calls[0]["cmd"])
            self.assertEqual(cmd, ["script", "-qfc", "omx --tmux --madmax", "/dev/null"])
            self.assertNotIn("--model", " ".join(str(part) for part in cmd))
            child_env = cast(dict[str, str], popen_calls[0]["env"])
            expected_omx_root = repo / "trees" / "feature_task" / "1" / ".envctl-state" / "omx" / "feature-task-1"
            self.assertEqual(Path(child_env["OMX_ROOT"]).resolve(), expected_omx_root.resolve())
            self.assertTrue((expected_omx_root / ".omx" / "state" / "session.json").is_file())
            rendered = out.getvalue()
            self.assertIn("attach: tmux attach -t omx-feature-session", rendered)
            self.assertIn("kill: tmux kill-session -t omx-feature-session", rendered)

    def test_plan_planning_prs_does_not_invoke_plan_agent_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(
                    repo,
                    runtime,
                    extra={
                        "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                        "ENVCTL_PLAN_AGENT_CODEX_CYCLES": "2",
                    },
                ),
                env={"ENVCTL_ACTION_PR_CMD": "sh -lc 'exit 0'", "CMUX_WORKSPACE_ID": "workspace:4"},
            )
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]

            with patch("envctl_engine.startup.lifecycle.launch_plan_agent_terminals") as launch_mock:
                code = engine.dispatch(parse_route(["--planning-prs", "feature-a", "--batch"], env={}))

            self.assertEqual(code, 0)
            launch_mock.assert_not_called()

    def test_plan_feature_with_both_cli_creates_two_worktrees_then_reuses_existing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "feature").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "feature" / "task.md").write_text("# task\n", encoding="utf-8")

            engine = PythonEngineRuntime(
                self._config(
                    repo,
                    runtime,
                    extra={
                        "TREES_STARTUP_ENABLE": "false",
                        "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                        "ENVCTL_PLAN_AGENT_CLI": "both",
                        "ENVCTL_PLAN_AGENT_CODEX_CYCLES": "2",
                        "ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK": "true",
                    },
                ),
                env={"CMUX_WORKSPACE_ID": "workspace:4"},
            )
            launches: list[list[str]] = []

            with patch(
                "envctl_engine.startup.lifecycle.launch_plan_agent_terminals",
                side_effect=lambda _runtime, *, route, created_worktrees: (
                    launches.append([item.name for item in created_worktrees]),
                    PlanAgentLaunchResult(status="launched", reason="launched", outcomes=()),
                )[1],
            ):
                first_code = engine.dispatch(parse_route(["--plan", "feature/task", "--batch"], env={}))
                second_code = engine.dispatch(parse_route(["--plan", "feature/task", "--batch"], env={}))

            self.assertEqual(first_code, 0)
            self.assertEqual(second_code, 0)
            self.assertEqual(launches, [["feature_task-1", "feature_task-2"], []])
            self.assertTrue((repo / "trees" / "feature_task" / "1").is_dir())
            self.assertTrue((repo / "trees" / "feature_task" / "2").is_dir())

    def test_plan_launch_failure_preserves_created_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "feature").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "feature" / "task.md").write_text("# task\n", encoding="utf-8")

            engine = PythonEngineRuntime(
                self._config(
                    repo,
                    runtime,
                    extra={
                        "TREES_STARTUP_ENABLE": "false",
                        "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                        "ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK": "true",
                    },
                ),
                env={"CMUX_WORKSPACE_ID": "workspace:4"},
            )

            with patch(
                "envctl_engine.startup.lifecycle.launch_plan_agent_terminals",
                return_value=PlanAgentLaunchResult(status="failed", reason="missing_executables", outcomes=()),
            ):
                code = engine.dispatch(parse_route(["--plan", "feature/task", "--batch"], env={}))

            self.assertEqual(code, 1)
            self.assertTrue((repo / "trees" / "feature_task" / "1").is_dir())

    def test_ai_plan_run_warns_and_continues_when_project_start_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(
                    repo,
                    runtime,
                    extra={
                        "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                        "ENVCTL_PLAN_AGENT_CLI": "opencode",
                    },
                ),
                env={"ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "repo implementation"},
            )
            route = parse_route(["--plan", "feature-a", "--batch"], env={})
            launch_result = PlanAgentLaunchResult(
                status="launched",
                reason="launched",
                outcomes=(
                    PlanAgentLaunchOutcome(
                        worktree_name="feature-a-1",
                        worktree_root=repo / "trees" / "feature-a" / "1",
                        surface_id="surface-1",
                        status="launched",
                    ),
                ),
            )

            out = StringIO()
            with (
                patch(
                    "envctl_engine.startup.lifecycle.launch_plan_agent_terminals",
                    return_value=launch_result,
                ),
                patch.object(engine, "_start_project_context", side_effect=RuntimeError("missing_service_start_command: autodetect_failed_backend")),
                redirect_stdout(out),
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertIn("Implementation session is running, but local app startup failed.", rendered)
            self.assertIn("missing_service_start_command", rendered)
            state = engine._try_load_existing_state(mode="trees")
            self.assertIsNotNone(state)
            assert state is not None
            self.assertTrue(state.metadata["plan_agent_handoff_degraded"])
            self.assertTrue(state.metadata["implementation_session_running"])
            self.assertTrue(state.metadata["local_startup_failed"])
            self.assertEqual(
                state.metadata["local_startup_failures"],
                [
                    {
                        "project": "feature-a-1",
                        "error": "missing_service_start_command: autodetect_failed_backend",
                        "reason": "missing_service_start_command",
                    }
                ],
            )

    def test_omx_headless_plan_agent_handoff_persists_degraded_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature_task" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "feature").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "feature" / "task.md").write_text("# task\n", encoding="utf-8")

            engine = PythonEngineRuntime(
                self._config(
                    repo,
                    runtime,
                    extra={
                        "ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK": "true",
                    },
                ),
                env={},
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
                        worktree_name="feature_task-1",
                        worktree_root=repo / "trees" / "feature_task" / "1",
                        surface_id=None,
                        status="launched",
                    ),
                ),
                attach_target=attach_target,
            )

            out = StringIO()
            with (
                patch(
                    "envctl_engine.startup.lifecycle.launch_plan_agent_terminals",
                    return_value=launch_result,
                ),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=True),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_display_message_succeeds", return_value=(True, "%42")),
                patch.object(
                    engine,
                    "_start_project_context",
                    side_effect=RuntimeError("missing_service_start_command: autodetect_failed_backend"),
                ),
                redirect_stdout(out),
            ):
                code = engine.dispatch(parse_route(["--plan", "feature/task", "--omx", "--codex", "--headless"], env={}))

            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertIn("Implementation session is running, but local app startup failed.", rendered)
            self.assertIn("attach: tmux attach -t omx-feature-session", rendered)
            self.assertNotIn("Startup failed:", rendered)
            state = engine._try_load_existing_state(mode="trees")
            self.assertIsNotNone(state)
            assert state is not None
            self.assertTrue(state.metadata["plan_agent_handoff_degraded"])
            self.assertTrue(state.metadata["implementation_session_running"])
            self.assertTrue(state.metadata["local_startup_failed"])
            self.assertEqual(state.metadata["plan_agent_session_name"], "omx-feature-session")
            self.assertEqual(state.metadata["plan_agent_attach_command"], "tmux attach -t omx-feature-session")

    def test_plan_snapshot_emits_real_path_checkpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "ENVCTL_DEBUG_PLAN_SNAPSHOT": "1",
                },
            )
            engine.process_runner = _FakeProcessRunner()  # type: ignore[attr-defined]

            requirements = RequirementsResult(
                project="feature-a-1",
                components={
                    "redis": {"enabled": True, "success": True, "health": "healthy"},
                },
                health="healthy",
                failures=[],
            )
            services = {
                "feature-a-1 Backend": ServiceRecord(
                    name="feature-a-1 Backend",
                    type="backend",
                    cwd=str(repo),
                    pid=1111,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                ),
                "feature-a-1 Frontend": ServiceRecord(
                    name="feature-a-1 Frontend",
                    type="frontend",
                    cwd=str(repo),
                    pid=1112,
                    requested_port=9000,
                    actual_port=9000,
                    status="running",
                ),
            }

            route = parse_route(["--plan", "feature-a"], env={})
            with (
                patch.object(engine, "_run_interactive_dashboard_loop", return_value=0),
                patch.object(
                    engine,
                    "_start_project_context",
                    return_value=ProjectStartupResult(requirements=requirements, services=services, warnings=[]),
                ),
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            checkpoints = [
                event.get("checkpoint") for event in engine.events if event.get("event") == "ui.plan_handoff.snapshot"
            ]
            self.assertIn("plan_selector_exit", checkpoints)
            self.assertIn("startup_branch_enter", checkpoints)
            self.assertIn("before_dashboard_entry", checkpoints)

