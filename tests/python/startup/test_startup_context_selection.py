from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree
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
        self.planning_worktree_orchestrator = SimpleNamespace(
            last_plan_selection_result=lambda: self.last_plan_selection_result,
            import_remote_branch_worktree=lambda *, branch_input: self.import_result,
        )
        self.import_result = SimpleNamespace(raw_projects=[], created_worktrees=(), error=None)

    def _discover_projects(self, *, mode: str) -> list[SimpleNamespace]:
        self.discovered_mode = mode
        return list(self.project_contexts)

    def _select_plan_projects(self, route: Route, project_contexts: list[SimpleNamespace]) -> list[SimpleNamespace]:
        self.plan_route = route
        return list(self.selected_plan_contexts or project_contexts)

    def _apply_setup_worktree_selection(
        self, route: Route, project_contexts: list[SimpleNamespace]
    ) -> list[SimpleNamespace]:
        self.setup_route = route
        if self.setup_selection_error is not None:
            raise self.setup_selection_error
        return list(project_contexts)

    def _contexts_from_raw_projects(self, raw_projects: list[tuple[str, Path]]) -> list[SimpleNamespace]:
        return [SimpleNamespace(name=name, root=root, ports={}) for name, root in raw_projects]

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

    def test_select_startup_contexts_imports_remote_branch_for_plan_agent_launch(self) -> None:
        root = Path("/tmp/feature-foo")
        created = CreatedPlanWorktree(name="feature-foo", root=root, plan_file="")
        runtime = _RuntimeStub([])
        runtime.import_result = SimpleNamespace(
            raw_projects=[("feature-foo", root)],
            created_worktrees=(created,),
            error=None,
        )
        route = Route(
            command="import",
            mode="trees",
            raw_args=[],
            passthrough_args=["feature/foo"],
            projects=[],
            flags={"tmux": True},
        )
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
        self.assertEqual([context.name for context in session.selected_contexts], ["feature-foo"])
        self.assertTrue(session.plan_agent_launch_requested)
        self.assertEqual(session.pending_plan_agent_worktrees, (created,))


if __name__ == "__main__":
    unittest.main()
