from __future__ import annotations

import time
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.project_execution import execute_project_startup_plan
from envctl_engine.startup.session import ProjectStartupResult, StartupSession
from envctl_engine.state.models import RequirementsResult, ServiceRecord


class _SpinnerStub:
    def update(self, message: str) -> None:
        _ = message

    def fail(self, message: str) -> None:
        _ = message

    def succeed(self, message: str) -> None:
        _ = message


class StartupProjectExecutionTests(unittest.TestCase):
    def _context(self, name: str) -> SimpleNamespace:
        return SimpleNamespace(name=name, root=Path(f"/tmp/repo/{name}"), ports={})

    def _session(self, contexts: list[SimpleNamespace]) -> StartupSession:
        route = Route(command="plan", mode="trees", raw_args=[], passthrough_args=[], projects=[], flags={})
        return StartupSession(
            requested_route=route,
            effective_route=route,
            requested_command="plan",
            runtime_mode="trees",
            run_id="run-1",
            selected_contexts=list(contexts),
            contexts_to_start=list(contexts),
        )

    def _orchestrator(self, *, parallel: bool, workers: int = 2) -> SimpleNamespace:
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(
            env={},
            _emit=lambda event, **payload: events.append((event, payload)),
            _tree_parallel_startup_config=lambda **kwargs: (parallel, workers),
        )
        return SimpleNamespace(
            runtime=runtime,
            events=events,
            _suppress_progress_output=lambda route: True,
            _resolved_run_id=lambda session: session.run_id or "run-1",
            _record_project_startup=lambda session, context, result: (
                session.requirements_by_project.__setitem__(context.name, result.requirements),
                session.services_by_project.__setitem__(context.name, result.services),
                session.started_context_names.append(context.name),
            ),
            _render_project_startup_warnings=lambda **kwargs: None,
            _should_degrade_to_plan_agent_handoff=lambda session, error: False,
            _record_plan_agent_handoff_local_startup_failure=lambda **kwargs: None,
        )

    def _project_result(self, context: SimpleNamespace) -> ProjectStartupResult:
        return ProjectStartupResult(
            requirements=RequirementsResult(project=context.name),
            services={
                f"{context.name} Backend": ServiceRecord(
                    name=f"{context.name} Backend",
                    type="backend",
                    cwd=str(context.root / "backend"),
                )
            },
        )

    def test_parallel_execution_records_results_in_selected_order(self) -> None:
        first = self._context("feature-a-1")
        second = self._context("feature-b-1")
        session = self._session([first, second])
        orchestrator = self._orchestrator(parallel=True, workers=2)

        def start_project_context(*, context, mode, route, run_id):  # noqa: ANN001
            _ = mode, route, run_id
            if context.name == "feature-a-1":
                time.sleep(0.02)
            return self._project_result(context)

        orchestrator.runtime._start_project_context = start_project_context

        execute_project_startup_plan(
            orchestrator,
            session,
            project_spinner_group_factory=lambda *args, **kwargs: nullcontext(),
            resolve_spinner_policy_fn=lambda env: SimpleNamespace(enabled=False, backend="plain"),
            emit_spinner_policy_fn=lambda emit, policy, context: None,
            use_spinner_policy_fn=lambda policy: nullcontext(),
            spinner_factory=lambda message, enabled: nullcontext(_SpinnerStub()),
            project_success_message_fn=lambda session, context: f"startup completed for {context.name}",
        )

        self.assertEqual(session.started_context_names, ["feature-a-1", "feature-b-1"])
        execution_events = [payload for event, payload in orchestrator.events if event == "startup.execution"]
        self.assertEqual(execution_events, [
            {
                "mode": "parallel",
                "workers": 2,
                "projects": ["feature-a-1", "feature-b-1"],
            }
        ])

    def test_degraded_plan_agent_handoff_records_warning_instead_of_failing(self) -> None:
        context = self._context("feature-a-1")
        session = self._session([context])
        failures: list[tuple[str, str]] = []
        orchestrator = self._orchestrator(parallel=False, workers=1)
        orchestrator._should_degrade_to_plan_agent_handoff = lambda session, error: True
        orchestrator._record_plan_agent_handoff_local_startup_failure = (
            lambda session, project_name, error: failures.append((project_name, error))
        )
        orchestrator.runtime._start_project_context = (
            lambda **kwargs: (_ for _ in ()).throw(RuntimeError("missing_service_start_command: backend"))
        )

        execute_project_startup_plan(
            orchestrator,
            session,
            project_spinner_group_factory=lambda *args, **kwargs: nullcontext(),
            resolve_spinner_policy_fn=lambda env: SimpleNamespace(enabled=False, backend="plain"),
            emit_spinner_policy_fn=lambda emit, policy, context: None,
            use_spinner_policy_fn=lambda policy: nullcontext(),
            spinner_factory=lambda message, enabled: nullcontext(_SpinnerStub()),
            project_success_message_fn=lambda session, context: f"startup completed for {context.name}",
        )

        self.assertEqual(failures, [("feature-a-1", "missing_service_start_command: backend")])
        self.assertEqual(session.started_context_names, [])


if __name__ == "__main__":
    unittest.main()
