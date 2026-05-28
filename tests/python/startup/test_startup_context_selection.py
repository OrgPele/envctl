from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree
from envctl_engine.planning.worktree_import_commands import normalize_import_branch_ref
from envctl_engine.planning.worktree_import_orchestration import ImportWorktreeResult
from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.context_selection import select_startup_contexts
from envctl_engine.startup.session import StartupSession


class _RuntimeStub:
    def __init__(self, project_contexts: list[SimpleNamespace]) -> None:
        self.project_contexts = project_contexts
        self.events: list[tuple[str, dict[str, object]]] = []
        self.duplicate_error = ""
        self.setup_selection_error: RuntimeError | None = None
        self.selected_plan_contexts: list[SimpleNamespace] | None = None
        self.last_plan_selection_result = SimpleNamespace(created_worktrees=())
        self.last_import_result = None
        self.planning_worktree_orchestrator = SimpleNamespace(
            last_plan_selection_result=lambda: self.last_plan_selection_result,
            last_import_result=lambda: self.last_import_result,
        )

    def _discover_projects(self, *, mode: str) -> list[SimpleNamespace]:
        self.discovered_mode = mode
        return list(self.project_contexts)

    def _select_plan_projects(self, route: Route, project_contexts: list[SimpleNamespace]) -> list[SimpleNamespace]:
        self.plan_route = route
        return list(self.selected_plan_contexts or project_contexts)

    def _select_import_project(self, route: Route, project_contexts: list[SimpleNamespace]) -> list[SimpleNamespace]:
        self.import_route = route
        ref = normalize_import_branch_ref(str(route.passthrough_args[0]))
        worktree = CreatedPlanWorktree(name=ref.project_name, root=Path("/tmp") / ref.project_name, plan_file="")
        self.last_import_result = ImportWorktreeResult(ref=ref, worktree=worktree, action="created")
        return [SimpleNamespace(name=worktree.name, root=worktree.root, ports={})]

    def _apply_setup_worktree_selection(
        self, route: Route, project_contexts: list[SimpleNamespace]
    ) -> list[SimpleNamespace]:
        self.setup_route = route
        if self.setup_selection_error is not None:
            raise self.setup_selection_error
        return list(project_contexts)

    def _duplicate_project_context_error(self, project_contexts: list[SimpleNamespace]) -> str | None:
        self.duplicate_checked = list(project_contexts)
        return self.duplicate_error or None

    def _emit(self, event: str, **payload: object) -> None:
        self.events.append((event, dict(payload)))


class StartupContextSelectionTests(unittest.TestCase):
    @staticmethod
    def _context(name: str) -> SimpleNamespace:
        return SimpleNamespace(name=name, root=Path("/tmp") / name, ports={})

    @staticmethod
    def _session(route: Route) -> StartupSession:
        return StartupSession(
            requested_route=route,
            effective_route=route,
            requested_command=route.command,
            runtime_mode=route.mode,
            run_id="run-1",
        )

    def test_select_startup_contexts_filters_explicit_projects_and_emits_phase_and_snapshot(self) -> None:
        contexts = [self._context("Alpha"), self._context("Beta")]
        runtime = _RuntimeStub(contexts)
        route = Route(command="start", mode="main", raw_args=[], passthrough_args=[], projects=["beta"], flags={})
        session = self._session(route)
        session.debug_plan_snapshot = True
        phases: list[tuple[str, dict[str, object]]] = []
        snapshots: list[tuple[str, dict[str, object]]] = []

        result = select_startup_contexts(
            runtime=runtime,
            session=session,
            trees_start_selection_required=lambda *, route, runtime_mode: False,
            select_start_tree_projects=lambda *, route, project_contexts: project_contexts,
            apply_restart_ports=lambda _session, project_contexts: None,
            emit_phase=lambda _session, phase, started_at, **extra: phases.append((phase, dict(extra))),
            emit_snapshot=lambda _session, checkpoint, **extra: snapshots.append((checkpoint, dict(extra))),
        )

        self.assertIsNone(result)
        self.assertEqual([context.name for context in session.selected_contexts], ["Beta"])
        self.assertEqual([context.name for context in session.contexts_to_start], ["Beta"])
        self.assertEqual(phases, [("project_selection", {"status": "ok", "project_count": 1})])
        self.assertEqual(snapshots[0][0], "plan_selector_exit")
        self.assertEqual(snapshots[0][1]["projects"], ["Beta"])

    def test_select_startup_contexts_reports_duplicate_project_error(self) -> None:
        contexts = [self._context("Alpha")]
        runtime = _RuntimeStub(contexts)
        runtime.duplicate_error = "duplicate project Alpha"
        route = Route(command="start", mode="main", raw_args=[], passthrough_args=[], projects=[], flags={})
        session = self._session(route)
        phases: list[tuple[str, dict[str, object]]] = []

        result = select_startup_contexts(
            runtime=runtime,
            session=session,
            trees_start_selection_required=lambda *, route, runtime_mode: False,
            select_start_tree_projects=lambda *, route, project_contexts: project_contexts,
            apply_restart_ports=lambda _session, project_contexts: None,
            emit_phase=lambda _session, phase, started_at, **extra: phases.append((phase, dict(extra))),
            emit_snapshot=lambda _session, checkpoint, **extra: None,
        )

        self.assertEqual(result, 1)
        self.assertEqual(phases, [("project_selection", {"status": "error"})])
        self.assertEqual(runtime.events, [("planning.projects.duplicate", {"error": "duplicate project Alpha"})])

    def test_select_startup_contexts_recovers_explicit_plan_agent_launch_worktrees(self) -> None:
        context = self._context("feature-a-1")
        runtime = _RuntimeStub([context])
        runtime.last_plan_selection_result = SimpleNamespace(created_worktrees=())
        route = Route(command="plan", mode="trees", raw_args=[], passthrough_args=[], projects=[], flags={"cmux": True})
        session = self._session(route)

        result = select_startup_contexts(
            runtime=runtime,
            session=session,
            trees_start_selection_required=lambda _route, _mode: False,
            select_start_tree_projects=lambda *, route, project_contexts: project_contexts,
            apply_restart_ports=lambda _session, project_contexts: None,
            emit_phase=lambda _session, phase, started_at, **extra: None,
            emit_snapshot=lambda _session, checkpoint, **extra: None,
        )

        self.assertIsNone(result)
        self.assertTrue(session.plan_agent_launch_requested)
        self.assertEqual(
            session.pending_plan_agent_worktrees,
            (CreatedPlanWorktree(name="feature-a-1", root=context.root, plan_file=""),),
        )

    def test_import_selection_records_import_metadata_and_skips_no_infra_startup(self) -> None:
        runtime = _RuntimeStub([])
        route = Route(
            command="import",
            mode="trees",
            raw_args=["--import", "feature/foo", "--no-infra"],
            passthrough_args=["feature/foo"],
            projects=[],
            flags={"launch_backend": False, "launch_frontend": False, "launch_dependencies": False},
        )
        session = self._session(route)

        result = select_startup_contexts(
            runtime=runtime,
            session=session,
            trees_start_selection_required=lambda *, route, runtime_mode: False,
            select_start_tree_projects=lambda *, route, project_contexts: project_contexts,
            apply_restart_ports=lambda _session, project_contexts: None,
            emit_phase=lambda _session, phase, started_at, **extra: None,
            emit_snapshot=lambda _session, checkpoint, **extra: None,
        )

        self.assertIsNone(result)
        self.assertEqual([context.name for context in session.selected_contexts], ["imported-feature-foo"])
        self.assertEqual(session.contexts_to_start, [])
        self.assertIsNotNone(session.imported_startup_context)
        assert session.imported_startup_context is not None
        self.assertEqual(session.imported_startup_context.remote_ref, "origin/feature/foo")
        self.assertEqual(session.imported_startup_context.project, "imported-feature-foo")


if __name__ == "__main__":
    unittest.main()
