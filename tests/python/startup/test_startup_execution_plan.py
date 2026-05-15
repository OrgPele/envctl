from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.execution_plan import (
    apply_execution_plan_to_session,
    apply_project_startup_result_to_session,
    build_startup_execution_plan,
)
from envctl_engine.startup.session import ProjectStartupResult, StartupSession
from envctl_engine.state.models import RequirementsResult, ServiceRecord


class StartupExecutionPlanTests(unittest.TestCase):
    def _context(self, name: str) -> SimpleNamespace:
        return SimpleNamespace(name=name, root=Path(f"/tmp/repo/{name}"), ports={})

    def _session(self, *, contexts: list[SimpleNamespace]) -> StartupSession:
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

    def test_builds_selected_restored_and_new_work_items_without_mutating_session(self) -> None:
        restored = self._context("feature-a-1")
        new = self._context("feature-b-1")
        session = self._session(contexts=[restored, new])
        session.contexts_to_start = [new]
        session.resumed_context_names = ["feature-a-1"]
        session.preserved_services = {
            "feature-a-1 Backend": ServiceRecord(
                name="feature-a-1 Backend",
                type="backend",
                cwd="/tmp/repo/feature-a-1/backend",
            )
        }
        session.preserved_requirements = {
            "feature-a-1": RequirementsResult(project="feature-a-1", redis={"enabled": True, "success": True})
        }
        original_contexts_to_start = list(session.contexts_to_start)

        plan = build_startup_execution_plan(
            session,
            reuse_decision_kind="reuse_expand",
            finalization_hint="preserve_and_start",
        )

        self.assertEqual([context.name for context in plan.selected_contexts], ["feature-a-1", "feature-b-1"])
        self.assertEqual([context.name for context in plan.contexts_to_start], ["feature-b-1"])
        self.assertEqual(plan.resumed_context_names, ("feature-a-1",))
        self.assertEqual(plan.reuse_decision_kind, "reuse_expand")
        self.assertEqual(plan.finalization_hint, "preserve_and_start")
        items = plan.work_items(mode=session.runtime_mode, run_id=session.run_id)
        self.assertEqual([(item.display_name, item.restored, item.newly_started) for item in items], [
            ("feature-a-1", True, False),
            ("feature-b-1", False, True),
        ])
        self.assertEqual(session.contexts_to_start, original_contexts_to_start)

    def test_applies_preserved_state_and_project_results_through_one_accumulator_path(self) -> None:
        restored = self._context("feature-a-1")
        new = self._context("feature-b-1")
        plan_session = self._session(contexts=[restored, new])
        plan_session.contexts_to_start = [new]
        plan_session.resumed_context_names = ["feature-a-1"]
        preserved_backend = ServiceRecord(
            name="feature-a-1 Backend",
            type="backend",
            cwd="/tmp/repo/feature-a-1/backend",
            pid=1111,
        )
        plan_session.preserved_services = {"feature-a-1 Backend": preserved_backend}
        plan_session.preserved_requirements = {
            "feature-a-1": RequirementsResult(project="feature-a-1", redis={"enabled": True, "success": True})
        }
        plan = build_startup_execution_plan(plan_session, reuse_decision_kind="reuse_expand")

        target = self._session(contexts=[restored, new])
        apply_execution_plan_to_session(target, plan)
        new_backend = ServiceRecord(
            name="feature-b-1 Backend",
            type="backend",
            cwd="/tmp/repo/feature-b-1/backend",
            pid=2222,
        )
        apply_project_startup_result_to_session(
            target,
            new,
            ProjectStartupResult(
                requirements=RequirementsResult(project="feature-b-1", redis={"enabled": True, "success": True}),
                services={"feature-b-1 Backend": new_backend},
            ),
        )

        self.assertEqual(target.resumed_context_names, ["feature-a-1"])
        self.assertEqual([context.name for context in target.contexts_to_start], ["feature-b-1"])
        self.assertIs(target.merged_services["feature-a-1 Backend"], preserved_backend)
        self.assertIs(target.merged_services["feature-b-1 Backend"], new_backend)
        self.assertEqual(sorted(target.merged_requirements), ["feature-a-1", "feature-b-1"])

    def test_new_project_results_replace_overlapping_preserved_state(self) -> None:
        context = self._context("Main")
        session = self._session(contexts=[context])
        preserved = ServiceRecord(name="Main Backend", type="backend", cwd="/tmp/repo/backend", pid=1111)
        replacement = ServiceRecord(name="Main Backend", type="backend", cwd="/tmp/repo/backend", pid=2222)
        session.preserved_services = {"Main Backend": preserved}
        session.preserved_requirements = {
            "Main": RequirementsResult(project="Main", redis={"enabled": True, "success": True, "final": 6379})
        }

        apply_project_startup_result_to_session(
            session,
            context,
            ProjectStartupResult(
                requirements=RequirementsResult(project="Main", redis={"enabled": True, "success": True, "final": 6380}),
                services={"Main Backend": replacement},
            ),
        )

        self.assertIs(session.merged_services["Main Backend"], replacement)
        self.assertEqual(session.merged_requirements["Main"].redis["final"], 6380)


if __name__ == "__main__":
    unittest.main()
