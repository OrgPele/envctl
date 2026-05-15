from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.run_reuse_application import apply_run_reuse_decision
from envctl_engine.startup.run_reuse_support import RunReuseDecision, mark_run_reused
from envctl_engine.startup.session import StartupSession
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord


class RunReuseApplicationTests(unittest.TestCase):
    def _context(self, name: str) -> SimpleNamespace:
        return SimpleNamespace(name=name, root=Path(f"/tmp/repo/{name}"), ports={})

    def _session(self, route: Route, contexts: list[SimpleNamespace]) -> StartupSession:
        return StartupSession(
            requested_route=route,
            effective_route=route,
            requested_command=route.command,
            runtime_mode=route.mode,
            run_id=None,
            selected_contexts=list(contexts),
            contexts_to_start=list(contexts),
        )

    def _orchestrator(self, *, missing_services: list[str] | None = None) -> SimpleNamespace:
        events: list[tuple[str, dict[str, object]]] = []
        resume_routes: list[Route] = []
        runtime = SimpleNamespace(
            env={},
            events=[],
            _emit=lambda event, **payload: events.append((event, payload)),
            _resume=lambda route: resume_routes.append(route) or 0,
            _reconcile_state_truth=lambda state: list(missing_services or []),
            _terminate_services_from_state=lambda *args, **kwargs: None,
            _project_name_from_service=lambda name: str(name).split()[0],
            config=SimpleNamespace(additional_services=()),
        )
        orchestrator = SimpleNamespace(
            runtime=runtime,
            events=events,
            resume_routes=resume_routes,
            _resolved_run_id=lambda session: session.run_id or "run-new",
            _announce_session_identifiers=lambda session: setattr(session, "identifiers_announced", True),
            _emit_phase=lambda session, phase, started_at, **extra: events.append(("startup.phase", {"phase": phase, **extra})),
            _headless_plan_output_only=lambda session: False,
            _maybe_attach_plan_agent_terminal=lambda session: None,
            _configured_service_types_for_mode=lambda mode: ["backend", "frontend"],
            _print_headless_plan_session_summary=lambda session: None,
            _print_plan_dry_run_preview=lambda session: None,
            _emit_snapshot=lambda session, checkpoint, **extra: None,
            _terminate_restart_orphan_listeners=lambda **kwargs: None,
            _restart_service_types_for_project=lambda **kwargs: {"backend", "frontend"},
        )
        return orchestrator

    def test_exact_resume_builds_resume_route_and_stops_orchestration(self) -> None:
        context = self._context("feature-a-1")
        route = Route(command="start", mode="trees", raw_args=["--tree"], passthrough_args=[], projects=["feature-a-1"], flags={})
        session = self._session(route, [context])
        candidate = RunState(
            run_id="run-existing",
            mode="trees",
            services={
                "feature-a-1 Backend": ServiceRecord(
                    name="feature-a-1 Backend",
                    type="backend",
                    cwd="/tmp/repo/feature-a-1/backend",
                )
            },
        )
        decision = RunReuseDecision(
            candidate_state=candidate,
            decision_kind="resume_exact",
            reason="exact_match",
            selected_projects=[{"name": "feature-a-1", "root": str(context.root)}],
            state_projects=[{"name": "feature-a-1", "root": str(context.root)}],
        )
        orchestrator = self._orchestrator()

        result = apply_run_reuse_decision(
            orchestrator,
            session,
            decision,
            reuse_started=0.0,
            mark_run_reused_fn=mark_run_reused,
        )

        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.return_code, 0)
        self.assertEqual(len(orchestrator.resume_routes), 1)
        resume_route = orchestrator.resume_routes[0]
        self.assertEqual(resume_route.command, "resume")
        self.assertEqual(resume_route.mode, "trees")
        self.assertEqual(resume_route.projects, ["feature-a-1"])
        self.assertEqual(resume_route.flags["_resume_source_command"], "start")
        self.assertEqual(resume_route.flags["_run_reuse_reason"], "resume_exact")
        self.assertEqual(session.run_id, "run-existing")

    def test_reuse_expand_preserves_existing_state_and_starts_only_new_contexts(self) -> None:
        restored = self._context("feature-a-1")
        new = self._context("feature-b-1")
        route = Route(command="plan", mode="trees", raw_args=[], passthrough_args=[], projects=[], flags={})
        session = self._session(route, [restored, new])
        preserved_service = ServiceRecord(
            name="feature-a-1 Backend",
            type="backend",
            cwd="/tmp/repo/feature-a-1/backend",
        )
        preserved_requirements = RequirementsResult(project="feature-a-1", redis={"enabled": True, "success": True})
        candidate = RunState(
            run_id="run-existing",
            mode="trees",
            services={"feature-a-1 Backend": preserved_service},
            requirements={"feature-a-1": preserved_requirements},
            metadata={"metadata": "kept"},
        )
        decision = RunReuseDecision(
            candidate_state=candidate,
            decision_kind="reuse_expand",
            reason="expand_match",
            selected_projects=[
                {"name": "feature-a-1", "root": str(restored.root)},
                {"name": "feature-b-1", "root": str(new.root)},
            ],
            state_projects=[{"name": "feature-a-1", "root": str(restored.root)}],
        )
        orchestrator = self._orchestrator()

        result = apply_run_reuse_decision(
            orchestrator,
            session,
            decision,
            reuse_started=0.0,
            mark_run_reused_fn=mark_run_reused,
        )

        self.assertEqual(result.status, "continue")
        self.assertEqual(session.resumed_context_names, ["feature-a-1"])
        self.assertEqual([context.name for context in session.contexts_to_start], ["feature-b-1"])
        self.assertIs(session.preserved_services["feature-a-1 Backend"], preserved_service)
        self.assertIs(session.preserved_requirements["feature-a-1"], preserved_requirements)
        self.assertEqual(session.base_metadata["last_reuse_reason"], "reuse_expand")

    def test_stale_reuse_expand_skips_preservation_and_keeps_fresh_start_path(self) -> None:
        restored = self._context("feature-a-1")
        new = self._context("feature-b-1")
        route = Route(command="plan", mode="trees", raw_args=[], passthrough_args=[], projects=[], flags={})
        session = self._session(route, [restored, new])
        candidate = RunState(
            run_id="run-existing",
            mode="trees",
            services={
                "feature-a-1 Backend": ServiceRecord(
                    name="feature-a-1 Backend",
                    type="backend",
                    cwd="/tmp/repo/feature-a-1/backend",
                )
            },
        )
        decision = RunReuseDecision(
            candidate_state=candidate,
            decision_kind="reuse_expand",
            reason="expand_match",
            selected_projects=[
                {"name": "feature-a-1", "root": str(restored.root)},
                {"name": "feature-b-1", "root": str(new.root)},
            ],
            state_projects=[{"name": "feature-a-1", "root": str(restored.root)}],
        )
        orchestrator = self._orchestrator(missing_services=["feature-a-1 Backend"])

        result = apply_run_reuse_decision(
            orchestrator,
            session,
            decision,
            reuse_started=0.0,
            mark_run_reused_fn=mark_run_reused,
        )

        self.assertEqual(result.status, "continue_fresh")
        self.assertEqual(session.resumed_context_names, [])
        self.assertEqual(session.preserved_services, {})
        self.assertEqual([context.name for context in session.contexts_to_start], ["feature-a-1", "feature-b-1"])
        skipped_events = [payload for event, payload in orchestrator.events if event == "state.run_reuse.skipped"]
        self.assertEqual(skipped_events[-1]["reason"], "stale_existing_state")

    def test_dashboard_stopped_service_restore_rewrites_route_to_start_only_stopped_services(self) -> None:
        context = self._context("Main")
        route = Route(command="start", mode="main", raw_args=[], passthrough_args=[], projects=[], flags={})
        session = self._session(route, [context])
        backend = ServiceRecord(name="Main Backend", type="backend", cwd="/tmp/repo/backend")
        requirements = RequirementsResult(project="Main", redis={"enabled": True, "success": True})
        candidate = RunState(
            run_id="run-existing",
            mode="main",
            services={"Main Backend": backend},
            requirements={"Main": requirements},
            metadata={
                "dashboard_stopped_services": [
                    {"name": "Main Frontend", "project": "Main", "type": "frontend"},
                ]
            },
        )
        decision = RunReuseDecision(
            candidate_state=candidate,
            decision_kind="resume_exact",
            reason="exact_match",
            selected_projects=[{"name": "Main", "root": str(context.root)}],
            state_projects=[{"name": "Main", "root": str(context.root)}],
        )
        orchestrator = self._orchestrator()

        result = apply_run_reuse_decision(
            orchestrator,
            session,
            decision,
            reuse_started=0.0,
            mark_run_reused_fn=mark_run_reused,
        )

        self.assertEqual(result.status, "continue")
        self.assertEqual(session.effective_route.flags["services"], ["Main Frontend"])
        self.assertEqual(session.effective_route.flags["restart_service_types"], ["frontend"])
        self.assertFalse(session.effective_route.flags["restart_include_requirements"])
        self.assertEqual([context.name for context in session.contexts_to_start], ["Main"])
        self.assertIs(session.preserved_services["Main Backend"], backend)
        self.assertIs(session.preserved_requirements["Main"], requirements)
        self.assertNotIn("dashboard_stopped_services", session.base_metadata)


if __name__ == "__main__":
    unittest.main()
