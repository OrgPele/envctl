from __future__ import annotations

import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from envctl_engine.runtime.command_router import parse_route
from envctl_engine.runtime.engine_runtime import ProjectContext, PythonEngineRuntime
from envctl_engine.startup.session import ProjectStartupResult
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord

from tests.python.runtime.engine_runtime_real_startup_test_support import (
    _EngineRuntimeRealStartupTestCase,
)


class EngineRuntimePlanResumeStartupTests(_EngineRuntimeRealStartupTestCase):
    def test_plan_auto_resumes_existing_run_when_selected_projects_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
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

            route = parse_route(["--plan", "feature-a", "--batch"], env={})
            with (
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch.object(engine, "_resume", return_value=0) as resume_mock,
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(resume_mock.call_count, 1)

    def test_plan_falls_back_to_fresh_start_when_auto_resume_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
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

            started_projects: list[str] = []

            def fake_start_project_context(*, context, mode, route, run_id):  # noqa: ANN001
                _ = mode, route, run_id
                started_projects.append(context.name)
                return ProjectStartupResult(
                    requirements=RequirementsResult(project=context.name, health="healthy"),
                    services={
                        f"{context.name} Backend": ServiceRecord(
                            name=f"{context.name} Backend",
                            type="backend",
                            cwd=str(context.root),
                            pid=2222,
                            requested_port=context.ports["backend"].requested,
                            actual_port=context.ports["backend"].final,
                            status="running",
                        )
                    },
                    warnings=[],
                )

            route = parse_route(["--plan", "feature-a", "--batch"], env={})
            with (
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch.object(engine, "_resume", return_value=1) as resume_mock,
                patch.object(engine, "_terminate_services_from_state", return_value=set()) as terminate_mock,
                patch.object(engine, "_start_project_context", side_effect=fake_start_project_context),
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(resume_mock.call_count, 1)
            self.assertEqual(terminate_mock.call_count, 1)
            self.assertEqual(started_projects, ["feature-a-1"])

    def test_plan_auto_resumes_existing_run_when_selected_projects_are_subset_of_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-b" / "1").mkdir(parents=True, exist_ok=True)
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
                    ),
                    "feature-b-1 Backend": ServiceRecord(
                        name="feature-b-1 Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=2222,
                        requested_port=8020,
                        actual_port=8020,
                        status="running",
                    ),
                },
            )

            route = parse_route(["--plan", "feature-a", "--batch"], env={})
            with (
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch.object(engine, "_resume", return_value=0) as resume_mock,
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(resume_mock.call_count, 1)

    def test_plan_preserves_existing_run_and_starts_only_new_projects_when_selection_expands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-b" / "1").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            existing_service = ServiceRecord(
                name="feature-a-1 Backend",
                type="backend",
                cwd=str(repo / "trees" / "feature-a" / "1"),
                pid=1111,
                requested_port=8000,
                actual_port=8000,
                status="running",
            )
            state = RunState(
                run_id="run-1",
                mode="trees",
                services={"feature-a-1 Backend": existing_service},
                requirements={},
            )

            started_projects: list[str] = []

            def fake_start_project_context(*, context, mode, route, run_id):  # noqa: ANN001
                _ = mode, route, run_id
                started_projects.append(context.name)
                return ProjectStartupResult(
                    requirements=RequirementsResult(project=context.name, health="healthy"),
                    services={
                        f"{context.name} Backend": ServiceRecord(
                            name=f"{context.name} Backend",
                            type="backend",
                            cwd=str(context.root),
                            pid=2222,
                            requested_port=context.ports["backend"].requested,
                            actual_port=context.ports["backend"].final,
                            status="running",
                        )
                    },
                    warnings=[],
                )

            route = parse_route(["--plan", "feature-a,feature-b", "--batch"], env={})
            with (
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch.object(engine, "_reconcile_state_truth", return_value=[]),
                patch.object(engine, "_resume", return_value=0) as resume_mock,
                patch.object(engine, "_start_project_context", side_effect=fake_start_project_context),
                patch.object(engine, "_write_artifacts") as write_artifacts_mock,
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(resume_mock.call_count, 0)
            self.assertEqual(started_projects, ["feature-b-1"])
            written_state = write_artifacts_mock.call_args.args[0]
            self.assertIn("feature-a-1 Backend", written_state.services)
            self.assertIn("feature-b-1 Backend", written_state.services)

    def test_plan_skips_auto_resume_when_selected_projects_do_not_match_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-b" / "1").mkdir(parents=True, exist_ok=True)
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

            route = parse_route(["--plan", "feature-b", "--batch"], env={})
            with (
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch.object(engine, "_resume", return_value=0) as resume_mock,
                patch.object(engine, "_start_project_context", side_effect=RuntimeError("expected startup path")),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertEqual(resume_mock.call_count, 0)
            self.assertIn("expected startup path", out.getvalue())

    def test_plan_no_resume_flag_disables_auto_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
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

            route = parse_route(["--plan", "feature-a", "--no-resume", "--batch"], env={})
            with (
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch.object(engine, "_resume", return_value=0) as resume_mock,
                patch.object(engine, "_terminate_services_from_state", return_value=set()) as terminate_mock,
                patch.object(engine, "_start_project_context", side_effect=RuntimeError("expected startup path")),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertEqual(resume_mock.call_count, 0)
            self.assertEqual(terminate_mock.call_count, 1)
            self.assertIn("expected startup path", out.getvalue())

    def test_exact_tree_plan_match_reuses_prior_run_id(self) -> None:
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
            with patch.object(first_engine, "_start_project_context", side_effect=lambda **kwargs: fake_result(kwargs["context"])):
                first_code = first_engine.dispatch(parse_route(["--plan", "feature-a", "--batch"], env={}))
            self.assertEqual(first_code, 0)
            first_state = first_engine.state_repository.load_latest(mode="trees", strict_mode_match=True)
            self.assertIsNotNone(first_state)
            assert first_state is not None

            second_engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            second_engine._reconcile_state_truth = lambda _state: []  # type: ignore[assignment]
            second_session_id = second_engine._current_session_id()
            with redirect_stdout(StringIO()):
                second_code = second_engine.dispatch(parse_route(["--plan", "feature-a", "--batch"], env={}))

            self.assertEqual(second_code, 0)
            second_state = second_engine.state_repository.load_latest(mode="trees", strict_mode_match=True)
            self.assertIsNotNone(second_state)
            assert second_state is not None
            self.assertEqual(second_state.run_id, first_state.run_id)
            self.assertNotEqual(first_engine._current_session_id(), second_session_id)
