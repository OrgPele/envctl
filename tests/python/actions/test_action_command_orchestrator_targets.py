from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch
import tempfile

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.actions.action_command_orchestrator import ActionCommandOrchestrator
from envctl_engine.actions.action_test_support import TestTargetContext
from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.ui.target_selector import TargetSelection


class _RuntimeStub:
    def __init__(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.env: dict[str, str] = {}
        self.config = SimpleNamespace(base_dir=Path("/tmp"), raw={})
        self.process_runner = SimpleNamespace(
            run=lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="/tmp\n", stderr="")
        )
        self._dashboard_pr_url_cache: dict[str, object] = {}
        self._emitted: list[tuple[str, dict[str, object]]] = []
        runtime_root = Path(self._tmpdir.name) / "runtime"
        self.state_repository = SimpleNamespace(
            run_dir_path=lambda run_id: runtime_root / "runs" / str(run_id),
            save_resume_state=self._save_resume_state,
        )
        self._latest_state: RunState | None = None

    def _discover_projects(self, *, mode: str):  # noqa: ANN001
        return [SimpleNamespace(name="alpha"), SimpleNamespace(name="beta")]

    @staticmethod
    def _selectors_from_passthrough(_args):  # noqa: ANN001
        return set()

    def _try_load_existing_state(self, *args, **kwargs):  # noqa: ANN001, ARG002
        return self._latest_state

    def _project_name_from_service(self, _name: str) -> str:
        return ""

    def _select_project_targets(self, **_kwargs):  # noqa: ANN001
        return TargetSelection(cancelled=True)

    def _emit(self, event: str, **payload: object) -> None:
        self._emitted.append((event, dict(payload)))

    def _save_resume_state(self, *, state, emit, runtime_map_builder):  # noqa: ANN001, ARG002
        self._latest_state = state
        return {}


class ActionCommandTargetTests(unittest.TestCase):
    def test_runtime_facade_routes_target_dependencies(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = ActionCommandOrchestrator(runtime)

        projects = orchestrator.runtime.discover_projects(mode="trees")

        self.assertEqual([project.name for project in projects], ["alpha", "beta"])
        self.assertEqual(orchestrator.runtime.selectors_from_passthrough(["ignored"]), set())


    def test_resolve_targets_main_action_from_worktree_uses_current_worktree(self) -> None:
        runtime = _RuntimeStub()
        worktree = Path("/tmp/repo/trees/feature-a/1")
        runtime.env["ENVCTL_INVOCATION_CWD"] = str(worktree)
        runtime.config = SimpleNamespace(base_dir=Path("/tmp/repo"), raw={}, trees_dir_name="trees")
        runtime._discover_projects = lambda mode: [SimpleNamespace(name="Main", root=Path("/tmp/repo"))] if mode == "main" else []
        orchestrator = ActionCommandOrchestrator(runtime)
        route = Route(command="test", mode="main", raw_args=["--main", "test"])

        with (
            patch.object(orchestrator, "_main_repo_root_for_worktree", return_value=Path("/tmp/repo")),
            patch(
                "envctl_engine.actions.action_command_orchestrator.discover_tree_projects",
                return_value=[("feature-a-1", worktree)],
            ),
        ):
            targets, error = orchestrator.resolve_targets(route, trees_only=False)

        self.assertIsNone(error)
        self.assertEqual([(target.name, target.root) for target in targets], [("feature-a-1", worktree)])

    def test_resolve_targets_uses_interactive_selection(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = ActionCommandOrchestrator(runtime)
        route = Route(command="test", mode="trees", flags={"interactive_command": True})

        selection = TargetSelection(all_selected=True)
        with (
            patch("envctl_engine.ui.dashboard.terminal_ui.RuntimeTerminalUI._can_interactive_tty", return_value=True),
            patch.object(runtime, "_select_project_targets", return_value=selection),
        ):
            targets, error = orchestrator.resolve_targets(route, trees_only=False)

        self.assertIsNone(error)
        self.assertEqual(len(targets), 2)

    def test_resolve_targets_self_destruct_uses_current_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = _RuntimeStub()
            tree_root = Path(tmpdir).resolve()
            orchestrator = ActionCommandOrchestrator(runtime)
            route = Route(command="self-destruct-worktree", mode="trees")

            with (
                patch("envctl_engine.actions.action_command_orchestrator.Path.cwd", return_value=tree_root),
                patch.object(orchestrator, "_main_repo_root_for_worktree", return_value=Path("/tmp/repo")),
                patch(
                    "envctl_engine.actions.action_command_orchestrator.discover_tree_projects",
                    return_value=[("feature-a-1", tree_root)],
                ),
            ):
                targets, error = orchestrator.resolve_targets(route, trees_only=True)

            self.assertIsNone(error)
            self.assertEqual([getattr(targets[0], "name")], ["feature-a-1"])

    def test_resolve_targets_self_destruct_requires_current_worktree(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = ActionCommandOrchestrator(runtime)
        route = Route(command="self-destruct-worktree", mode="trees")

        with (
            patch("envctl_engine.actions.action_command_orchestrator.Path.cwd", return_value=Path("/tmp/other")),
            patch.object(orchestrator, "_main_repo_root_for_worktree", return_value=Path("/tmp/repo")),
            patch(
                "envctl_engine.actions.action_command_orchestrator.discover_tree_projects",
                return_value=[("feature-a-1", Path("/tmp/feature-a/1"))],
            ),
        ):
            targets, error = orchestrator.resolve_targets(route, trees_only=True)

        self.assertEqual(targets, [])
        self.assertEqual(error, "self-destruct-worktree must be run from inside a discovered worktree.")

    def test_resolve_targets_does_not_flush_pending_input_for_interactive_command(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = ActionCommandOrchestrator(runtime)
        route = Route(command="test", mode="trees", flags={"interactive_command": True})

        selection = TargetSelection(all_selected=True)
        with (
            patch(
                "envctl_engine.actions.action_command_orchestrator.RuntimeTerminalUI.flush_pending_interactive_input"
            ) as flush_pending,
            patch.object(runtime, "_select_project_targets", return_value=selection),
        ):
            targets, error = orchestrator.resolve_targets(route, trees_only=False)

        self.assertIsNone(error)
        self.assertEqual(len(targets), 2)
        flush_pending.assert_not_called()

    def test_resolve_targets_does_not_flush_for_non_interactive_command(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = ActionCommandOrchestrator(runtime)
        route = Route(command="test", mode="trees")

        selection = TargetSelection(all_selected=True)
        with (
            patch("envctl_engine.ui.dashboard.terminal_ui.RuntimeTerminalUI._can_interactive_tty", return_value=True),
            patch(
                "envctl_engine.actions.action_command_orchestrator.RuntimeTerminalUI.flush_pending_interactive_input"
            ) as flush_pending,
            patch.object(runtime, "_select_project_targets", return_value=selection),
        ):
            targets, error = orchestrator.resolve_targets(route, trees_only=False)

        self.assertIsNone(error)
        self.assertEqual(len(targets), 2)
        flush_pending.assert_not_called()

    def test_projects_for_services_matches_additional_service_slug_from_state(self) -> None:
        runtime = _RuntimeStub()
        runtime._latest_state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Voice Runtime": ServiceRecord(
                    name="Main Voice Runtime",
                    type="voice-runtime",
                    cwd="/tmp/repo/voice-runtime",
                    requested_port=8010,
                    actual_port=8010,
                    status="running",
                )
            },
        )
        runtime._project_name_from_service = lambda service_name: "Main" if service_name == "Main Voice Runtime" else ""
        orchestrator = ActionCommandOrchestrator(runtime)

        projects = orchestrator.projects_for_services(["voice-runtime"])

        self.assertEqual(projects, ["Main"])

    def test_test_plan_action_delegates_to_owner(self) -> None:
        runtime = _RuntimeStub()
        runtime.config = SimpleNamespace(base_dir=Path("/tmp/repo"), raw={})
        orchestrator = ActionCommandOrchestrator(runtime)
        route = Route(command="test-focused", mode="main", flags={"json": True, "dry_run": True})
        targets = [SimpleNamespace(name="Main", root=Path("/tmp/repo"))]

        with patch(
            "envctl_engine.actions.action_command_orchestrator.run_test_plan_action_for_targets_impl",
            return_value=7,
        ) as run_test_plan:
            code = orchestrator.run_test_plan_action(route, targets)

        self.assertEqual(code, 7)
        run_test_plan.assert_called_once_with(orchestrator, route, targets)

    def test_migrate_action_delegates_to_owner(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = ActionCommandOrchestrator(runtime)
        route = Route(command="migrate", mode="trees")
        targets = [SimpleNamespace(name="alpha", root=Path("/tmp/alpha"))]

        with patch(
            "envctl_engine.actions.action_command_orchestrator.run_migrate_action_with_owner",
            return_value=11,
        ) as run_migrate:
            code = orchestrator.run_migrate_action(route, targets)

        self.assertEqual(code, 11)
        run_migrate.assert_called_once_with(orchestrator, route, targets, extra_env=orchestrator.action_extra_env(route))

    def test_test_execution_spec_methods_delegate_to_test_plan_owner(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = ActionCommandOrchestrator(runtime)
        route = Route(command="test", mode="main")
        target_contexts = [TestTargetContext(project_name="Main", project_root=Path("/tmp"), target_obj=object())]

        with patch(
            "envctl_engine.actions.action_command_orchestrator.build_test_execution_specs_for_orchestrator",
            return_value=[SimpleNamespace(index=1)],
        ) as build_specs:
            specs = orchestrator._build_test_execution_specs(
                route=route,
                targets=[],
                target_contexts=target_contexts,
                include_backend=True,
                include_frontend=False,
                run_all=False,
                untested=False,
            )

        self.assertEqual([spec.index for spec in specs], [1])
        build_specs.assert_called_once_with(
            orchestrator,
            route=route,
            targets=[],
            target_contexts=target_contexts,
            include_backend=True,
            include_frontend=False,
            run_all=False,
            untested=False,
        )

        with patch(
            "envctl_engine.actions.action_command_orchestrator.build_failed_test_execution_specs_for_orchestrator",
            return_value=[SimpleNamespace(index=2)],
        ) as build_failed:
            failed_specs = orchestrator._build_failed_test_execution_specs(route=route, target_contexts=target_contexts)

        self.assertEqual([spec.index for spec in failed_specs], [2])
        build_failed.assert_called_once_with(orchestrator, route=route, target_contexts=target_contexts)

    def test_build_test_execution_specs_uses_additional_service_test_command(self) -> None:
        runtime = _RuntimeStub()
        runtime.config = SimpleNamespace(
            base_dir=Path("/tmp/repo"),
            raw={},
            frontend_test_path="",
            app_service_by_name=lambda name: SimpleNamespace(
                name="voice-runtime",
                test_cmd="python -m pytest voice-runtime/tests",
                dir_name="voice-runtime",
            )
            if name == "voice-runtime"
            else None,
        )
        runtime.split_command = lambda raw, *, replacements: raw.split()
        orchestrator = ActionCommandOrchestrator(runtime)
        route = Route(command="test", mode="main", flags={"services": ["voice-runtime"]})
        target = SimpleNamespace(name="Main", root=Path("/tmp/repo"))

        specs = orchestrator._build_test_execution_specs(
            route=route,
            targets=[target],
            target_contexts=[TestTargetContext(project_name="Main", project_root=Path("/tmp/repo"), target_obj=target)],
            include_backend=False,
            include_frontend=False,
            run_all=False,
            untested=False,
        )

        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].spec.command, ["python", "-m", "pytest", "voice-runtime/tests"])
        self.assertEqual(specs[0].spec.cwd, Path("/tmp/repo/voice-runtime"))
        self.assertEqual(specs[0].spec.source, "configured_service:voice-runtime")


    def test_build_test_execution_specs_fails_for_additional_service_without_test_command(self) -> None:
        runtime = _RuntimeStub()
        runtime.config = SimpleNamespace(
            base_dir=Path("/tmp/repo"),
            raw={"ENVCTL_BACKEND_TEST_CMD": "python -m pytest backend/tests"},
            frontend_test_path="",
            app_service_by_name=lambda name: SimpleNamespace(
                name="voice-runtime",
                test_cmd="",
                dir_name="voice-runtime",
            )
            if name == "voice-runtime"
            else None,
        )
        runtime.split_command = lambda raw, *, replacements: raw.split()
        orchestrator = ActionCommandOrchestrator(runtime)
        route = Route(command="test", mode="main", flags={"services": ["voice-runtime"]})
        target = SimpleNamespace(name="Main", root=Path("/tmp/repo"))

        with self.assertRaisesRegex(RuntimeError, "ENVCTL_SERVICE_VOICE_RUNTIME_TEST_CMD"):
            orchestrator._build_test_execution_specs(
                route=route,
                targets=[target],
                target_contexts=[
                    TestTargetContext(project_name="Main", project_root=Path("/tmp/repo"), target_obj=target)
                ],
                include_backend=False,
                include_frontend=False,
                run_all=False,
                untested=False,
            )

    def test_pr_success_handler_clears_dashboard_cache_and_emits_created_url_status(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = ActionCommandOrchestrator(runtime)
        runtime._dashboard_pr_url_cache = {"stale": ("expires", None)}
        runtime._latest_state = RunState(run_id="run-1", mode="main")

        handler = orchestrator._project_action_success_handler("pr", "main", True)  # noqa: SLF001
        self.assertIsNotNone(handler)

        handler(  # type: ignore[misc]
            SimpleNamespace(name="Main", root=Path("/tmp"), index=1, total=1, target_obj=SimpleNamespace(name="Main")),
            SimpleNamespace(stdout="https://github.com/kfiramar/envctl/pull/21\n", stderr="", returncode=0),
        )

        self.assertEqual(runtime._dashboard_pr_url_cache, {})
        self.assertIn(
            ("ui.status", {"message": "PR created: https://github.com/kfiramar/envctl/pull/21"}),
            runtime._emitted,
        )

    def test_pr_success_handler_persists_skipped_for_detached_head(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = ActionCommandOrchestrator(runtime)
        runtime._dashboard_pr_url_cache = {"stale": ("expires", None)}
        runtime._latest_state = RunState(run_id="run-1", mode="main")

        handler = orchestrator._project_action_success_handler("pr", "main", True)  # noqa: SLF001
        self.assertIsNotNone(handler)

        handler(  # type: ignore[misc]
            SimpleNamespace(name="Main", root=Path("/tmp"), index=1, total=1, target_obj=SimpleNamespace(name="Main")),
            SimpleNamespace(stdout="Skipping Main (detached HEAD).\n", stderr="", returncode=0),
        )

        assert runtime._latest_state is not None
        metadata = runtime._latest_state.metadata.get("project_action_reports")
        self.assertIsInstance(metadata, dict)
        assert isinstance(metadata, dict)
        project_entry = metadata.get("Main")
        self.assertIsInstance(project_entry, dict)
        assert isinstance(project_entry, dict)
        pr_entry = project_entry.get("pr")
        self.assertIsInstance(pr_entry, dict)
        assert isinstance(pr_entry, dict)
        self.assertEqual(pr_entry.get("status"), "skipped")
        self.assertEqual(runtime._dashboard_pr_url_cache, {})
        self.assertEqual(runtime._emitted, [])

    def test_review_success_handler_persists_review_artifact_paths(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = ActionCommandOrchestrator(runtime)
        runtime._latest_state = RunState(run_id="run-1", mode="trees")

        handler = orchestrator._project_action_success_handler("review", "trees", True)  # noqa: SLF001
        self.assertIsNotNone(handler)

        handler(  # type: ignore[misc]
            SimpleNamespace(
                name="feature-a-1",
                root=Path("/tmp/worktree"),
                index=1,
                total=1,
                target_obj=SimpleNamespace(name="feature-a-1"),
            ),
            SimpleNamespace(
                stdout=(
                    "Review Ready: feature-a-1\n"
                    "  Output directory\n"
                    "    /tmp/review-output\n"
                    "  Summary file\n"
                    "    /tmp/review-output/summary.md\n"
                    "  Full review bundle\n"
                    "    /tmp/review-output/all.md\n"
                ),
                stderr="",
                returncode=0,
            ),
        )

        assert runtime._latest_state is not None
        metadata = runtime._latest_state.metadata.get("project_action_reports")
        self.assertIsInstance(metadata, dict)
        assert isinstance(metadata, dict)
        project_entry = metadata.get("feature-a-1")
        self.assertIsInstance(project_entry, dict)
        assert isinstance(project_entry, dict)
        review_entry = project_entry.get("review")
        self.assertIsInstance(review_entry, dict)
        assert isinstance(review_entry, dict)
        self.assertEqual(review_entry.get("status"), "success")
        self.assertEqual(review_entry.get("output_dir"), "/tmp/review-output")
        self.assertEqual(review_entry.get("summary_path"), "/tmp/review-output/summary.md")
        self.assertEqual(review_entry.get("bundle_path"), "/tmp/review-output/all.md")

    def test_project_action_failure_handler_persists_summary_and_report_path(self) -> None:
        runtime = _RuntimeStub()
        runtime._latest_state = RunState(run_id="run-1", mode="main")
        orchestrator = ActionCommandOrchestrator(runtime)

        handler = orchestrator._project_action_failure_handler("migrate", "main")  # noqa: SLF001
        handler(
            SimpleNamespace(name="Main", root=Path("/tmp"), index=1, total=1, target_obj=SimpleNamespace(name="Main")),
            "alembic failed\nline 2\nline 3",
        )

        assert runtime._latest_state is not None
        metadata = runtime._latest_state.metadata.get("project_action_reports")
        self.assertIsInstance(metadata, dict)
        assert isinstance(metadata, dict)
        project_entry = metadata.get("Main")
        self.assertIsInstance(project_entry, dict)
        assert isinstance(project_entry, dict)
        migrate_entry = project_entry.get("migrate")
        self.assertIsInstance(migrate_entry, dict)
        assert isinstance(migrate_entry, dict)
        self.assertEqual(migrate_entry.get("status"), "failed")
        self.assertIn("alembic failed", str(migrate_entry.get("summary", "")))
        report_path = Path(str(migrate_entry.get("report_path", "")))
        self.assertTrue(report_path.is_file())

    def test_project_action_handlers_delegate_to_owner_module(self) -> None:
        self.assertNotIn(
            "build_project_action_success_handler_impl",
            ActionCommandOrchestrator._project_action_success_handler.__code__.co_names,
        )
        self.assertNotIn(
            "build_project_action_failure_handler_impl",
            ActionCommandOrchestrator._project_action_failure_handler.__code__.co_names,
        )
        self.assertNotIn(
            "persist_project_action_result_impl",
            ActionCommandOrchestrator._persist_project_action_result.__code__.co_names,
        )


if __name__ == "__main__":
    unittest.main()
