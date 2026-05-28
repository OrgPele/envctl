from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree
from envctl_engine.planning.worktree_import_orchestration import import_remote_branch_worktree
from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.context_selection import select_startup_contexts
from envctl_engine.startup.session import StartupSession
from envctl_engine.ui.selection_types import TargetSelection


class _RuntimeStub:
    def __init__(self, project_contexts: list[SimpleNamespace]) -> None:
        self.project_contexts = project_contexts
        self.config = SimpleNamespace(base_dir=Path("/repo"), trees_dir_name="trees")
        self.events: list[tuple[str, dict[str, object]]] = []
        self.duplicate_error = ""
        self.can_tty = True
        self.selection = TargetSelection()
        self.selection_kwargs: dict[str, object] | None = None
        self.setup_selection_error: RuntimeError | None = None
        self.selected_plan_contexts: list[SimpleNamespace] | None = None
        self.last_plan_selection_result = SimpleNamespace(created_worktrees=())
        self.import_calls: list[str] = []
        self.planning_worktree_orchestrator = SimpleNamespace(
            last_plan_selection_result=lambda: self.last_plan_selection_result,
            import_remote_branch_worktree=self._import_remote_branch_worktree,
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

    def _can_interactive_tty(self) -> bool:
        return self.can_tty

    def _select_project_targets(self, **kwargs):  # noqa: ANN001
        self.selection_kwargs = dict(kwargs)
        return self.selection

    def _import_remote_branch_worktree(self, *, branch_input: str):  # noqa: ANN001
        self.import_calls.append(branch_input)
        return self.import_result

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

    def test_select_startup_contexts_import_without_branch_prompts_and_imports_selection(self) -> None:
        root = Path("/tmp/feature-bar")
        created = CreatedPlanWorktree(name="feature-bar", root=root, plan_file="")
        runtime = _RuntimeStub([])
        runtime.selection = TargetSelection(project_names=["feature/bar"])
        runtime.import_result = SimpleNamespace(
            raw_projects=[("feature-bar", root)],
            created_worktrees=(created,),
            error=None,
        )
        route = Route(command="import", mode="trees", raw_args=[], passthrough_args=[], projects=[], flags={})
        session = self._session(route)

        with patch(
            "envctl_engine.startup.context_selection.list_importable_origin_branches",
            return_value=["feature/bar"],
        ) as branches:
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
        branches.assert_called_once()
        self.assertEqual(runtime.import_calls, ["feature/bar"])
        self.assertIsNotNone(runtime.selection_kwargs)
        assert runtime.selection_kwargs is not None
        self.assertEqual(runtime.selection_kwargs.get("prompt"), "Import remote branch")
        self.assertFalse(runtime.selection_kwargs.get("allow_all"))
        self.assertFalse(runtime.selection_kwargs.get("multi"))
        self.assertEqual([context.name for context in session.selected_contexts], ["feature-bar"])

    def test_select_startup_contexts_import_without_branch_cancel_does_not_import(self) -> None:
        runtime = _RuntimeStub([])
        runtime.selection = TargetSelection(cancelled=True)
        route = Route(command="import", mode="trees", raw_args=[], passthrough_args=[], projects=[], flags={})
        session = self._session(route)

        with patch(
            "envctl_engine.startup.context_selection.list_importable_origin_branches",
            return_value=["feature/bar"],
        ):
            result = select_startup_contexts(
                runtime=runtime,
                session=session,
                trees_start_selection_required=lambda _route, _mode: False,
                select_start_tree_projects=lambda *, route, project_contexts: project_contexts,
                apply_restart_ports=lambda _session, project_contexts: None,
                emit_phase=lambda _session, phase, started_at, **extra: None,
                emit_snapshot=lambda _session, checkpoint, **extra: None,
            )

        self.assertEqual(result, 1)
        self.assertEqual(runtime.import_calls, [])

    def test_select_startup_contexts_import_without_branch_headless_fails_without_prompt(self) -> None:
        runtime = _RuntimeStub([])
        route = Route(command="import", mode="trees", raw_args=[], passthrough_args=[], projects=[], flags={"batch": True})
        session = self._session(route)

        with patch("envctl_engine.startup.context_selection.list_importable_origin_branches") as branches:
            result = select_startup_contexts(
                runtime=runtime,
                session=session,
                trees_start_selection_required=lambda _route, _mode: False,
                select_start_tree_projects=lambda *, route, project_contexts: project_contexts,
                apply_restart_ports=lambda _session, project_contexts: None,
                emit_phase=lambda _session, phase, started_at, **extra: None,
                emit_snapshot=lambda _session, checkpoint, **extra: None,
            )

        self.assertEqual(result, 1)
        branches.assert_not_called()
        self.assertIsNone(runtime.selection_kwargs)
        self.assertEqual(runtime.import_calls, [])

    def test_select_startup_contexts_import_without_branch_no_candidates_does_not_import(self) -> None:
        runtime = _RuntimeStub([])
        route = Route(command="import", mode="trees", raw_args=[], passthrough_args=[], projects=[], flags={})
        session = self._session(route)

        with patch(
            "envctl_engine.startup.context_selection.list_importable_origin_branches",
            return_value=[],
        ):
            result = select_startup_contexts(
                runtime=runtime,
                session=session,
                trees_start_selection_required=lambda _route, _mode: False,
                select_start_tree_projects=lambda *, route, project_contexts: project_contexts,
                apply_restart_ports=lambda _session, project_contexts: None,
                emit_phase=lambda _session, phase, started_at, **extra: None,
                emit_snapshot=lambda _session, checkpoint, **extra: None,
            )

        self.assertEqual(result, 1)
        self.assertIsNone(runtime.selection_kwargs)
        self.assertEqual(runtime.import_calls, [])

    def test_select_startup_contexts_import_selector_smoke_imports_only_importable_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            origin = root / "origin.git"
            source = root / "source"
            repo = root / "repo"
            subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
            subprocess.run(["git", "clone", str(origin), str(source)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(source), "config", "user.email", "dev@example.test"], check=True)
            subprocess.run(["git", "-C", str(source), "config", "user.name", "Dev"], check=True)
            (source / "README.md").write_text("main\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(source), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(source), "commit", "-m", "main"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(source), "push", "origin", "HEAD:main"], check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", str(origin), "symbolic-ref", "HEAD", "refs/heads/main"],
                check=True,
                capture_output=True,
            )
            for branch, filename in (("feature/checked", "checked.txt"), ("feature/import-me", "import.txt")):
                subprocess.run(["git", "-C", str(source), "switch", "-C", branch, "HEAD"], check=True, capture_output=True)
                (source / filename).write_text(f"{branch}\n", encoding="utf-8")
                subprocess.run(["git", "-C", str(source), "add", filename], check=True)
                subprocess.run(["git", "-C", str(source), "commit", "-m", branch], check=True, capture_output=True)
                subprocess.run(["git", "-C", str(source), "push", "-u", "origin", branch], check=True, capture_output=True)
            subprocess.run(["git", "clone", str(origin), str(repo)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repo), "fetch", "origin"], check=True, capture_output=True)
            checked_target = repo / "trees" / "checked"
            checked_target.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "worktree",
                    "add",
                    "-b",
                    "feature/checked",
                    str(checked_target),
                    "origin/feature/checked",
                ],
                check=True,
                capture_output=True,
            )

            runtime = _RuntimeStub([])
            runtime.config = SimpleNamespace(base_dir=repo, trees_dir_name="trees", raw={})
            runtime.env = {}
            runtime.process_runner = SimpleNamespace(run=subprocess.run)
            runtime._command_env = lambda *, port, extra=None: dict(os.environ, **dict(extra or {}))
            runtime.selection = TargetSelection(project_names=["feature/import-me"])
            runtime.planning_worktree_orchestrator = SimpleNamespace(
                import_remote_branch_worktree=lambda *, branch_input: import_remote_branch_worktree(
                    runtime,
                    branch_input=branch_input,
                )
            )
            route = Route(command="import", mode="trees", raw_args=[], passthrough_args=[], projects=[], flags={})
            session = self._session(route)

            with (
                patch("envctl_engine.planning.worktree_import_orchestration.link_repo_local_shared_artifacts"),
                patch("envctl_engine.planning.worktree_import_orchestration.prepare_worktree_code_intelligence"),
            ):
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
            self.assertIsNotNone(runtime.selection_kwargs)
            assert runtime.selection_kwargs is not None
            selector_names = [project.name for project in runtime.selection_kwargs["projects"]]
            self.assertEqual(selector_names, ["feature/import-me"])
            imported = (repo / "trees" / "imported" / "feature-import-me").resolve()
            self.assertEqual([context.root for context in session.selected_contexts], [imported])
            branch = subprocess.run(
                ["git", "-C", str(imported), "branch", "--show-current"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            upstream = subprocess.run(
                ["git", "-C", str(imported), "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            provenance = json.loads((imported / ".envctl-state" / "worktree-provenance.json").read_text())
            self.assertEqual(branch, "feature/import-me")
            self.assertEqual(upstream, "origin/feature/import-me")
            self.assertEqual(provenance["imported_branch"], "feature/import-me")


if __name__ == "__main__":
    unittest.main()
