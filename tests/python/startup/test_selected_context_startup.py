from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
import unittest

from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.selected_context_startup import (
    record_project_startup,
    start_selected_contexts,
    start_selected_contexts_with_runtime,
)
from envctl_engine.startup.session import ProjectStartupResult, StartupSession
from envctl_engine.state.models import RequirementsResult


class _SpinnerStub:
    def __init__(self) -> None:
        self.updates: list[str] = []
        self.failures: list[str] = []
        self.successes: list[str] = []

    def update(self, message: str) -> None:
        self.updates.append(message)

    def fail(self, message: str) -> None:
        self.failures.append(message)

    def succeed(self, message: str) -> None:
        self.successes.append(message)

    def end(self) -> None:
        pass


class _SpinnerFactory:
    def __init__(self) -> None:
        self.instances: list[_SpinnerStub] = []

    def __call__(self, message: str, *, enabled: bool):  # noqa: ANN201
        _ = message, enabled
        instance = _SpinnerStub()
        self.instances.append(instance)

        class _Context:
            def __enter__(self_nonlocal):  # noqa: ANN001, ANN202
                return instance

            def __exit__(self_nonlocal, exc_type, exc, tb):  # noqa: ANN001, ANN202
                return False

        return _Context()


class _RuntimeStub:
    def __init__(self) -> None:
        self.env: dict[str, str] = {}
        self.events: list[tuple[str, dict[str, object]]] = []
        self.start_calls: list[tuple[str, Route]] = []

    def _emit(self, event: str, **payload: object) -> None:
        self.events.append((event, dict(payload)))

    def _tree_parallel_startup_config(self, *, mode: str, route: Route, project_count: int) -> tuple[bool, int]:
        _ = mode, route, project_count
        return False, 1

    def _start_project_context(self, *, context, mode: str, route: Route, run_id: str):  # noqa: ANN001, ANN202
        _ = mode, run_id
        self.start_calls.append((context.name, route))
        return ProjectStartupResult(
            requirements=RequirementsResult(project=context.name),
            services={},
            warnings=[f"{context.name} warning"],
        )


class SelectedContextStartupTests(unittest.TestCase):
    @staticmethod
    def _context(name: str) -> SimpleNamespace:
        return SimpleNamespace(name=name, root=Path("/tmp") / name, ports={})

    @staticmethod
    def _session(*, route: Route, contexts: list[SimpleNamespace]) -> StartupSession:
        session = StartupSession(
            requested_route=route,
            effective_route=route,
            requested_command=route.command,
            runtime_mode=route.mode,
            run_id="run-1",
        )
        session.selected_contexts = list(contexts)
        session.contexts_to_start = list(contexts)
        return session

    def test_start_selected_contexts_builds_execution_route_and_records_sequential_results(self) -> None:
        runtime = _RuntimeStub()
        runtime.env["ENVCTL_DEBUG_SUPPRESS_PLAN_PROGRESS"] = "true"
        route = Route(command="plan", mode="trees", raw_args=["plan"], passthrough_args=[], projects=[], flags={})
        session = self._session(route=route, contexts=[self._context("Alpha")])

        start_selected_contexts(
            runtime=runtime,
            session=session,
            suppress_progress_output=lambda route: False,
            resolved_run_id=lambda session: "run-1",
            record_project_startup=lambda session, context, result: (
                session.requirements_by_project.__setitem__(context.name, result.requirements),
                session.services_by_project.__setitem__(context.name, result.services),
                session.started_context_names.append(context.name),
            ),
            render_project_startup_warnings=lambda *, context, warnings, route, project_spinner_group: warnings and None,
            should_degrade_to_plan_agent_handoff=lambda session, error: False,
            record_plan_agent_handoff_local_startup_failure=lambda session, project_name, error: None,
            spinner_factory=_SpinnerFactory(),
            use_spinner_policy_fn=lambda policy: nullcontext(),
            resolve_spinner_policy_fn=lambda env: SimpleNamespace(enabled=False, backend="rich"),
            emit_spinner_policy_fn=lambda emit, policy, context: emit("spinner.policy", **context),
            project_spinner_group_factory=lambda **kwargs: SimpleNamespace(
                __enter__=lambda self: self,
                __exit__=lambda self, exc_type, exc, tb: False,
                update_project=lambda project, message: None,
                mark_success=lambda project, message: None,
                mark_failure=lambda project, message: None,
            ),
        )

        self.assertEqual(session.started_context_names, ["Alpha"])
        self.assertEqual(runtime.start_calls[0][0], "Alpha")
        execution_route = runtime.start_calls[0][1]
        self.assertIsNone(execution_route.flags["_spinner_update"])
        self.assertIsNone(execution_route.flags["_spinner_update_project"])
        self.assertTrue(execution_route.flags["debug_suppress_progress_output"])
        self.assertEqual(runtime.events[0][0], "spinner.policy")
        self.assertIn(("startup.execution", {"mode": "sequential", "workers": 1, "projects": ["Alpha"]}), runtime.events)

    def test_record_project_startup_updates_session_result_maps_and_started_names(self) -> None:
        route = Route(command="start", mode="trees", raw_args=["start"], passthrough_args=[], projects=[], flags={})
        context = self._context("Alpha")
        session = self._session(route=route, contexts=[context])
        requirements = RequirementsResult(project="Alpha")
        result = ProjectStartupResult(requirements=requirements, services={"Alpha Backend": object()})

        record_project_startup(session, context, result)

        self.assertEqual(session.requirements_by_project, {"Alpha": requirements})
        self.assertEqual(session.services_by_project, {"Alpha": result.services})
        self.assertEqual(session.started_context_names, ["Alpha"])

    def test_start_selected_contexts_degrades_local_startup_failure_when_handoff_allowed(self) -> None:
        runtime = _RuntimeStub()

        def fail_start_project_context(**kwargs):  # noqa: ANN001, ANN202
            raise RuntimeError("backend failed")

        runtime._start_project_context = fail_start_project_context  # type: ignore[method-assign]
        route = Route(command="plan", mode="trees", raw_args=["plan"], passthrough_args=[], projects=[], flags={})
        session = self._session(route=route, contexts=[self._context("Alpha")])
        degraded: list[tuple[str, str]] = []

        start_selected_contexts(
            runtime=runtime,
            session=session,
            suppress_progress_output=lambda route: False,
            resolved_run_id=lambda session: "run-1",
            record_project_startup=lambda session, context, result: None,
            render_project_startup_warnings=lambda *, context, warnings, route, project_spinner_group: None,
            should_degrade_to_plan_agent_handoff=lambda session, error: True,
            record_plan_agent_handoff_local_startup_failure=lambda session, project_name, error: degraded.append(
                (project_name, error)
            ),
            spinner_factory=_SpinnerFactory(),
            use_spinner_policy_fn=lambda policy: nullcontext(),
            resolve_spinner_policy_fn=lambda env: SimpleNamespace(enabled=False, backend="rich"),
            emit_spinner_policy_fn=lambda emit, policy, context: None,
            project_spinner_group_factory=lambda **kwargs: SimpleNamespace(),
        )

        self.assertEqual(degraded, [("Alpha", "backend failed")])
        self.assertEqual(session.started_context_names, [])

    def test_runtime_bound_selected_context_startup_records_results_and_uses_owner_dependencies(self) -> None:
        runtime = _RuntimeStub()
        route = Route(command="start", mode="trees", raw_args=["start"], passthrough_args=[], projects=[], flags={})
        context = self._context("Alpha")
        session = self._session(route=route, contexts=[context])
        rendered_warnings: list[tuple[str, list[str]]] = []
        degradation_checks: list[tuple[str, str]] = []
        local_failures: list[tuple[str, str]] = []
        spinner_policies: list[dict[str, object]] = []

        start_selected_contexts_with_runtime(
            runtime,
            session,
            resolved_run_id=lambda session: "run-1",
            render_project_startup_warnings=lambda *, context, warnings, route, project_spinner_group: rendered_warnings.append(
                (context.name, list(warnings))
            ),
            should_degrade_to_plan_agent_handoff=lambda session, error: degradation_checks.append(
                (session.requested_command, error)
            )
            or False,
            record_plan_agent_handoff_local_startup_failure=lambda session, project_name, error: local_failures.append(
                (project_name, error)
            ),
            spinner_factory=_SpinnerFactory(),
            use_spinner_policy_fn=lambda policy: nullcontext(),
            resolve_spinner_policy_fn=lambda env: SimpleNamespace(enabled=False, backend="rich"),
            emit_spinner_policy_fn=lambda emit, policy, context: spinner_policies.append(dict(context)),
            project_spinner_group_factory=lambda **kwargs: SimpleNamespace(
                __enter__=lambda self: self,
                __exit__=lambda self, exc_type, exc, tb: False,
                update_project=lambda project, message: None,
                mark_success=lambda project, message: None,
                mark_failure=lambda project, message: None,
            ),
        )

        self.assertEqual(session.started_context_names, ["Alpha"])
        self.assertIn("Alpha", session.requirements_by_project)
        self.assertEqual(session.services_by_project, {"Alpha": {}})
        self.assertEqual(rendered_warnings, [("Alpha", ["Alpha warning"])])
        self.assertEqual(degradation_checks, [])
        self.assertEqual(local_failures, [])
        self.assertEqual(spinner_policies, [{"component": "startup_orchestrator", "op_id": "startup.execute"}])


if __name__ == "__main__":
    unittest.main()
