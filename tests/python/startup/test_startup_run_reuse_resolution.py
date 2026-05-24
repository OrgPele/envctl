from __future__ import annotations

from types import SimpleNamespace
import unittest

from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.run_reuse_resolution import resolve_startup_run_reuse, resolve_startup_run_reuse_with_runtime
from envctl_engine.startup.run_reuse_support import RunReuseDecision
from envctl_engine.startup.session import StartupSession


def _session(route: Route) -> StartupSession:
    return StartupSession(
        requested_route=route,
        effective_route=route,
        requested_command=route.command,
        runtime_mode=route.mode,
        run_id=None,
        selected_contexts=[SimpleNamespace(name="Main")],
    )


class _RuntimeStub:
    def __init__(self) -> None:
        self.env: dict[str, str] = {}
        self.events: list[tuple[str, dict[str, object]]] = []
        self.pr_calls: list[tuple[Route, list[object]]] = []
        self.config = SimpleNamespace(additional_services=())
        self.replacement_progress: list[str] = []

    def _emit(self, event: str, **payload: object) -> None:
        self.events.append((event, payload))

    def _run_pr_action(self, route: Route, targets: list[object]) -> int:
        self.pr_calls.append((route, list(targets)))
        return 0

    def _project_name_from_service(self, service_name: str) -> str:
        return service_name.split(" Backend", 1)[0]

    def _terminate_services_from_state(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        self.terminated = (args, kwargs)

    def _current_session_id(self) -> str:
        return "session-run-reuse"


class StartupRunReuseResolutionTests(unittest.TestCase):
    def test_planning_prs_branch_runs_pr_action_after_reuse_evaluation_and_skips_startup(self) -> None:
        route = Route(command="plan", mode="trees", raw_args=[], passthrough_args=[], projects=[], flags={"planning_prs": True})
        runtime = _RuntimeStub()
        rendered: list[str] = []
        evaluated: list[bool] = []

        result = resolve_startup_run_reuse(
            runtime=runtime,
            session=_session(route),
            evaluate_run_reuse_fn=lambda *args, **kwargs: (
                evaluated.append(True),
                RunReuseDecision(
                    candidate_state=None,
                    decision_kind="fresh_run",
                    reason="no_matching_state",
                    selected_projects=[{"name": "Main", "root": None}],
                    state_projects=[],
                ),
            )[1],
            prepare_dashboard_stopped_service_restore=lambda *args, **kwargs: False,
            announce_session_identifiers=lambda session: None,
            emit_phase=lambda *args, **kwargs: None,
            headless_plan_output_only=lambda session: False,
            maybe_attach_plan_agent_terminal=lambda session: None,
            print_headless_plan_session_summary=lambda session: None,
            print_plan_dry_run_preview=lambda session: None,
            configured_service_types_for_mode=lambda mode: set(),
            emit_snapshot=lambda *args, **kwargs: None,
            replace_existing_project_services_for_fresh_start=lambda *args, **kwargs: None,
            print_fn=rendered.append,
        )

        self.assertEqual(result, 0)
        self.assertEqual(evaluated, [True])
        self.assertEqual(len(runtime.pr_calls), 1)
        self.assertEqual(
            [event for event, _payload in runtime.events],
            ["state.run_reuse.evaluate", "planning.projects.start", "planning.projects.finish"],
        )
        self.assertEqual(rendered, ["Planning PR mode complete; skipping service startup."])

    def test_fresh_run_emits_auto_resume_none_and_startup_branch_snapshot(self) -> None:
        route = Route(command="plan", mode="trees", raw_args=[], passthrough_args=[], projects=[], flags={})
        runtime = _RuntimeStub()
        runtime.env["ENVCTL_DEBUG_PLAN_ORCH_GROUP"] = "alpha,beta"
        phases: list[tuple[str, dict[str, object]]] = []
        snapshots: list[tuple[str, dict[str, object]]] = []

        result = resolve_startup_run_reuse(
            runtime=runtime,
            session=_session(route),
            evaluate_run_reuse_fn=lambda *args, **kwargs: RunReuseDecision(
                candidate_state=None,
                decision_kind="fresh_run",
                reason="no_matching_state",
                selected_projects=[{"name": "Main", "root": None}],
                state_projects=[],
            ),
            prepare_dashboard_stopped_service_restore=lambda *args, **kwargs: False,
            announce_session_identifiers=lambda session: None,
            emit_phase=lambda session, phase, started_at, **extra: phases.append((phase, dict(extra))),
            headless_plan_output_only=lambda session: False,
            maybe_attach_plan_agent_terminal=lambda session: None,
            print_headless_plan_session_summary=lambda session: None,
            print_plan_dry_run_preview=lambda session: None,
            configured_service_types_for_mode=lambda mode: set(),
            emit_snapshot=lambda session, snapshot, **payload: snapshots.append((snapshot, payload)),
            replace_existing_project_services_for_fresh_start=lambda *args, **kwargs: None,
        )

        self.assertIsNone(result)
        self.assertEqual(phases[0][0], "auto_resume_evaluate")
        self.assertEqual(phases[0][1]["status"], "none")
        self.assertEqual(snapshots, [("startup_branch_enter", {"command": "plan", "mode": "trees", "orch_group": ["alpha", "beta"]})])

    def test_runtime_bound_run_reuse_helper_handles_planning_prs(self) -> None:
        route = Route(command="plan", mode="trees", raw_args=[], passthrough_args=[], projects=[], flags={"planning_prs": True})
        runtime = _RuntimeStub()
        session = _session(route)
        rendered: list[str] = []

        result = resolve_startup_run_reuse_with_runtime(
            runtime,
            session,
            terminate_restart_orphan_listeners=lambda **kwargs: None,
            validate_attach_target_fn=lambda *args, **kwargs: None,
            attach_plan_agent_terminal=lambda *args, **kwargs: None,
            progress_lock=None,
            last_progress_message_by_project={},
            print_fn=rendered.append,
        )

        self.assertEqual(result, 0)
        self.assertEqual(len(runtime.pr_calls), 1)
        self.assertEqual(rendered, ["Planning PR mode complete; skipping service startup."])
        self.assertEqual(runtime.events[0][0], "state.run_reuse.evaluate")
        self.assertEqual(runtime.events[1][0], "startup.phase")
        self.assertEqual(runtime.events[1][1]["phase"], "auto_resume_evaluate")
        self.assertEqual([event for event, _payload in runtime.events[-2:]], ["planning.projects.start", "planning.projects.finish"])


if __name__ == "__main__":
    unittest.main()
