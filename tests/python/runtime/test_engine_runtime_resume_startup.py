from __future__ import annotations

import os
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from envctl_engine.runtime.command_router import parse_route
from envctl_engine.runtime.engine_runtime import ProjectContext, PythonEngineRuntime
from envctl_engine.startup.session import ProjectStartupResult
from envctl_engine.state import dump_state
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord
import envctl_engine.runtime.engine_runtime_startup_support as startup_support

from tests.python.runtime.engine_runtime_real_startup_test_support import (
    _EngineRuntimeRealStartupTestCase,
)


class EngineRuntimeResumeStartupTests(_EngineRuntimeRealStartupTestCase):
    def test_main_start_does_not_auto_resume_trees_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            trees_state = RunState(
                run_id="run-trees",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )
            dump_state(trees_state, str(engine.state_repository.run_state_path()))

            route = parse_route(["--main", "--batch"], env={})
            with (
                patch.object(engine, "_resume", return_value=0) as resume_mock,
                patch.object(engine, "_discover_projects", return_value=[]),
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertEqual(resume_mock.call_count, 0)

    def test_explicit_main_start_auto_resumes_matching_main_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)

            def fake_result(context: ProjectContext) -> ProjectStartupResult:
                return ProjectStartupResult(
                    requirements=RequirementsResult(project=context.name, health="healthy"),
                    services={
                        "Main Backend": ServiceRecord(
                            name="Main Backend",
                            type="backend",
                            cwd=str(context.root / "backend"),
                            pid=1234,
                            requested_port=context.ports["backend"].requested,
                            actual_port=context.ports["backend"].final,
                            status="running",
                        ),
                        "Main Frontend": ServiceRecord(
                            name="Main Frontend",
                            type="frontend",
                            cwd=str(context.root / "frontend"),
                            pid=1235,
                            requested_port=context.ports["frontend"].requested,
                            actual_port=context.ports["frontend"].final,
                            status="running",
                        ),
                    },
                    warnings=[],
                )

            first_engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            first_engine._reconcile_state_truth = lambda _state: []  # type: ignore[assignment]
            with patch.object(
                first_engine,
                "_start_project_context",
                side_effect=lambda **kwargs: fake_result(kwargs["context"]),
            ) as first_start_mock:
                first_code = first_engine.dispatch(parse_route(["--main", "--batch"], env={}))
            self.assertEqual(first_code, 0)
            self.assertEqual(first_start_mock.call_count, 1)
            first_state = first_engine.state_repository.load_latest(mode="main", strict_mode_match=True)
            self.assertIsNotNone(first_state)
            assert first_state is not None

            second_engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            second_engine._reconcile_state_truth = lambda _state: []  # type: ignore[assignment]
            with (
                patch.object(second_engine, "_resume", return_value=0) as resume_mock,
                patch.object(
                    second_engine,
                    "_start_project_context",
                    side_effect=AssertionError("fresh start not expected"),
                ),
                redirect_stdout(StringIO()),
            ):
                second_code = second_engine.dispatch(parse_route(["--main", "--batch"], env={}))

            self.assertEqual(second_code, 0)
            self.assertEqual(resume_mock.call_count, 1)
            second_state = second_engine.state_repository.load_latest(mode="main", strict_mode_match=True)
            self.assertIsNotNone(second_state)
            assert second_state is not None
            self.assertEqual(second_state.run_id, first_state.run_id)

    def test_start_does_not_auto_resume_non_resumable_service_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "backend": ServiceRecord(
                        name="backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )

            route = parse_route(["--debug-ui", "--batch"], env={})
            with (
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch.object(engine, "_resume", return_value=0) as resume_mock,
                patch.object(engine, "_discover_projects", return_value=[]),
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertEqual(resume_mock.call_count, 0)

    def test_disabled_tree_dashboard_relaunch_reuses_prior_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            config = self._config(
                repo,
                runtime,
                extra={"TREES_STARTUP_ENABLE": "false", "ENVCTL_DEFAULT_MODE": "trees"},
            )
            first_engine = PythonEngineRuntime(config, env={})
            with redirect_stdout(StringIO()):
                first_code = first_engine.dispatch(parse_route(["--plan", "feature-a", "--batch"], env={}))
            self.assertEqual(first_code, 0)
            first_state = first_engine.state_repository.load_latest(mode="trees", strict_mode_match=True)
            self.assertIsNotNone(first_state)
            assert first_state is not None

            second_engine = PythonEngineRuntime(config, env={})
            with redirect_stdout(StringIO()):
                second_code = second_engine.dispatch(parse_route(["--plan", "feature-a", "--batch"], env={}))
            self.assertEqual(second_code, 0)
            second_state = second_engine.state_repository.load_latest(mode="trees", strict_mode_match=True)
            self.assertIsNotNone(second_state)
            assert second_state is not None
            self.assertEqual(second_state.run_id, first_state.run_id)
            self.assertEqual(second_state.metadata.get("last_reuse_reason"), "resume_dashboard_exact")

    def test_config_profile_change_forces_fresh_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (tree / "backend").mkdir(parents=True, exist_ok=True)
            (tree / "frontend").mkdir(parents=True, exist_ok=True)

            def fake_result(context: ProjectContext) -> ProjectStartupResult:
                return ProjectStartupResult(
                    requirements=RequirementsResult(project=context.name, health="healthy"),
                    services={
                        f"{context.name} Backend": ServiceRecord(
                            name=f"{context.name} Backend",
                            type="backend",
                            cwd=str(context.root / "backend"),
                            pid=1234,
                            requested_port=context.ports["backend"].requested,
                            actual_port=context.ports["backend"].final,
                            status="running",
                        )
                    },
                    warnings=[],
                )

            first_engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            first_engine._reconcile_state_truth = lambda _state: []  # type: ignore[assignment]
            with patch.object(
                first_engine, "_start_project_context", side_effect=lambda **kwargs: fake_result(kwargs["context"])
            ):
                first_code = first_engine.dispatch(parse_route(["--plan", "feature-a", "--batch"], env={}))
            self.assertEqual(first_code, 0)
            first_state = first_engine.state_repository.load_latest(mode="trees", strict_mode_match=True)
            self.assertIsNotNone(first_state)
            assert first_state is not None

            second_engine = PythonEngineRuntime(self._config(repo, runtime, extra={"BACKEND_DIR": "api"}), env={})
            second_engine._reconcile_state_truth = lambda _state: []  # type: ignore[assignment]
            with patch.object(
                second_engine, "_start_project_context", side_effect=lambda **kwargs: fake_result(kwargs["context"])
            ):
                second_code = second_engine.dispatch(parse_route(["--plan", "feature-a", "--batch"], env={}))

            self.assertEqual(second_code, 0)
            second_state = second_engine.state_repository.load_latest(mode="trees", strict_mode_match=True)
            self.assertIsNotNone(second_state)
            assert second_state is not None
            self.assertNotEqual(second_state.run_id, first_state.run_id)

    def test_project_root_change_forces_fresh_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (tree / "backend").mkdir(parents=True, exist_ok=True)
            (tree / "frontend").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            context = engine._discover_projects(mode="trees")[0]
            wrong_root_context = ProjectContext(
                name=context.name, root=repo / "trees" / "feature-a" / "99", ports=context.ports
            )
            metadata = startup_support.build_startup_identity_metadata(
                engine,
                runtime_mode="trees",
                project_contexts=[wrong_root_context],
            )
            engine.state_repository.save_resume_state(
                state=RunState(
                    run_id="run-wrong-root",
                    mode="trees",
                    services={
                        f"{context.name} Backend": ServiceRecord(
                            name=f"{context.name} Backend",
                            type="backend",
                            cwd=str(wrong_root_context.root / "backend"),
                            pid=9999,
                            requested_port=context.ports["backend"].requested,
                            actual_port=context.ports["backend"].final,
                            status="running",
                        )
                    },
                    metadata={**metadata, "repo_scope_id": engine.config.runtime_scope_id},
                ),
                emit=lambda *args, **kwargs: None,
                runtime_map_builder=lambda _state: {},
            )

            def fake_result(selected_context: ProjectContext) -> ProjectStartupResult:
                return ProjectStartupResult(
                    requirements=RequirementsResult(project=selected_context.name, health="healthy"),
                    services={
                        f"{selected_context.name} Backend": ServiceRecord(
                            name=f"{selected_context.name} Backend",
                            type="backend",
                            cwd=str(selected_context.root / "backend"),
                            pid=1234,
                            requested_port=selected_context.ports["backend"].requested,
                            actual_port=selected_context.ports["backend"].final,
                            status="running",
                        )
                    },
                    warnings=[],
                )

            engine._reconcile_state_truth = lambda _state: []  # type: ignore[assignment]
            with patch.object(
                engine, "_start_project_context", side_effect=lambda **kwargs: fake_result(kwargs["context"])
            ):
                code = engine.dispatch(parse_route(["--plan", "feature-a", "--batch"], env={}))

            self.assertEqual(code, 0)
            latest = engine.state_repository.load_latest(mode="trees", strict_mode_match=True)
            self.assertIsNotNone(latest)
            assert latest is not None
            self.assertNotEqual(latest.run_id, "run-wrong-root")

    def test_resume_rejects_state_without_resumable_services(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "backend": ServiceRecord(
                        name="backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )

            route = parse_route(["--resume", "--interactive"], env={})
            output = StringIO()
            with (
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch.object(engine, "_run_interactive_dashboard_loop", return_value=0) as loop_mock,
                patch(
                    "envctl_engine.startup.resume_orchestrator.release_lifecycle_operation"
                ) as release_lifecycle_operation_mock,
                patch("sys.stdin.isatty", return_value=True),
                patch("sys.stdout.isatty", return_value=True),
                patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=False),
                redirect_stdout(output),
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertEqual(loop_mock.call_count, 0)
            release_lifecycle_operation_mock.assert_not_called()
            self.assertIn("No active services to resume.", output.getvalue())

    def test_dashboard_interactive_flag_enters_loop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(
                run_id="run-1",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )

            route = parse_route(["--dashboard", "--interactive"], env={})
            with (
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch("sys.stdin.isatty", return_value=True),
                patch("sys.stdout.isatty", return_value=True),
                patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=False),
                patch.object(engine, "_run_interactive_dashboard_loop", return_value=0) as loop_mock,
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(loop_mock.call_count, 1)

    def test_resume_defaults_to_interactive_in_tty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(
                run_id="run-1",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )

            route = parse_route(["--resume"], env={})
            with (
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch.object(engine, "_reconcile_state_truth", return_value=[]),
                patch("sys.stdin.isatty", return_value=True),
                patch("sys.stdout.isatty", return_value=True),
                patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=False),
                patch.object(engine, "_run_interactive_dashboard_loop", return_value=0) as loop_mock,
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(loop_mock.call_count, 1)

    def test_resume_batch_flag_skips_interactive_loop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(
                run_id="run-1",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )

            route = parse_route(["--resume", "--batch"], env={})
            with (
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch.object(engine, "_reconcile_state_truth", return_value=[]),
                patch("sys.stdin.isatty", return_value=True),
                patch("sys.stdout.isatty", return_value=True),
                patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=False),
                patch.object(engine, "_run_interactive_dashboard_loop", return_value=0) as loop_mock,
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(loop_mock.call_count, 0)
