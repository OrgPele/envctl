from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import unittest
from types import SimpleNamespace

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.runtime.command_router import Route
from envctl_engine.ui.dashboard.orchestrator import DashboardOrchestrator
from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.ui.target_selector import TargetSelection


class _RuntimeStub:
    def __init__(self) -> None:
        self.config = SimpleNamespace(raw={})
        self.env: dict[str, str] = {}
        self.selection_calls: list[dict[str, object]] = []
        self.last_dispatched_route: Route | None = None
        self._latest_state: RunState | None = None
        self.next_selection = TargetSelection(project_names=["Main"])
        self.dispatch_code: int = 0

    @staticmethod
    def _emit(*_args, **_kwargs):  # noqa: ANN001
        return None

    @staticmethod
    def _project_name_from_service(name: str) -> str:
        trimmed = str(name).strip()
        for suffix in (" Backend", " Frontend"):
            if trimmed.endswith(suffix):
                return trimmed[: -len(suffix)].strip()
        return "Main" if name.startswith("Main ") else ""

    @staticmethod
    def _projects_for_services(_services: list[str]) -> set[str]:
        return {"Main"}

    @staticmethod
    def _selectors_from_passthrough(_args):  # noqa: ANN001
        return set()

    def dispatch(self, route: Route) -> int:
        self.last_dispatched_route = route
        return self.dispatch_code

    def _try_load_existing_state(self, *, mode: str, strict_mode_match: bool = True):  # noqa: ANN001, ARG002
        if self._latest_state is None:
            return None
        return self._latest_state

    def _select_grouped_targets(
        self,
        *,
        prompt: str,
        projects: list[object],
        services: list[str],
        allow_all: bool,
        multi: bool,
    ) -> TargetSelection:
        self.selection_calls.append(
            {
                "selector": "grouped",
                "prompt": prompt,
                "projects": [getattr(project, "name", "") for project in projects],
                "services": list(services),
                "allow_all": allow_all,
                "multi": multi,
            }
        )
        return self.next_selection

    def _select_project_targets(
        self,
        *,
        prompt: str,
        projects: list[object],
        allow_all: bool,
        allow_untested: bool,
        multi: bool,
    ) -> TargetSelection:
        self.selection_calls.append(
            {
                "selector": "project",
                "prompt": prompt,
                "projects": [getattr(project, "name", "") for project in projects],
                "allow_all": allow_all,
                "allow_untested": allow_untested,
                "multi": multi,
            }
        )
        return self.next_selection


class DashboardOrchestratorRestartSelectorTests(unittest.TestCase):
    def test_interactive_stop_defers_selection_to_lifecycle_cleanup(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                )
            },
        )
        runtime._latest_state = state

        should_continue, next_state = orchestrator._run_interactive_command("s", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual(runtime.selection_calls, [])
        self.assertIsNotNone(runtime.last_dispatched_route)
        self.assertEqual(runtime.last_dispatched_route.command, "stop")  # type: ignore[union-attr]

    def test_hidden_dashboard_command_is_rejected_without_dispatch(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-plan",
            mode="trees",
            metadata={"dashboard_hidden_commands": ["restart"]},
        )
        runtime._latest_state = state

        out = StringIO()
        with redirect_stdout(out):
            should_continue, next_state = orchestrator._run_interactive_command("r", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertIsNone(runtime.last_dispatched_route)
        self.assertIn("Command 'restart' is not available in this dashboard", out.getvalue())

    def test_migrate_is_rejected_when_nothing_is_running(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(run_id="run-plan", mode="trees")
        runtime._latest_state = state

        out = StringIO()
        with redirect_stdout(out):
            should_continue, next_state = orchestrator._run_interactive_command("m", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertIsNone(runtime.last_dispatched_route)
        self.assertIn("Command 'migrate' is not available in this dashboard", out.getvalue())

    def test_restart_selector_uses_runtime_backend_selection(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                )
            },
        )
        route = Route(
            command="restart", mode="main", raw_args=["--restart"], passthrough_args=[], projects=[], flags={}
        )
        updated = orchestrator._apply_restart_selection(route, state, runtime)

        self.assertIsNotNone(updated)
        self.assertEqual(runtime.selection_calls[0]["prompt"], "Restart")
        self.assertEqual(updated.projects, ["Main"])

    def test_restart_selector_does_not_flush_pending_input_for_interactive_command(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                )
            },
        )
        route = Route(
            command="restart",
            mode="main",
            raw_args=["restart"],
            passthrough_args=[],
            projects=[],
            flags={"interactive_command": True},
        )

        updated = orchestrator._apply_restart_selection(route, state, runtime)

        self.assertIsNotNone(updated)
        self.assertEqual(len(runtime.selection_calls), 1)

    def test_restart_selector_skips_prompt_when_all_already_selected(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                )
            },
        )
        route = Route(
            command="restart",
            mode="main",
            raw_args=["restart", "--all"],
            passthrough_args=[],
            projects=[],
            flags={"all": True, "interactive_command": True},
        )

        updated = orchestrator._apply_restart_selection(route, state, runtime)

        self.assertIsNotNone(updated)
        self.assertEqual(runtime.selection_calls, [])

    def test_interactive_restart_prompts_selector_for_single_project(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                ),
                "Main Frontend": ServiceRecord(
                    name="Main Frontend",
                    type="frontend",
                    cwd=".",
                    pid=101,
                    requested_port=9000,
                    actual_port=9000,
                    status="running",
                ),
            },
        )
        runtime._latest_state = state

        should_continue, next_state = orchestrator._run_interactive_command("r", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, "run-1")
        self.assertEqual(len(runtime.selection_calls), 1)
        self.assertIsNotNone(runtime.last_dispatched_route)
        self.assertEqual(runtime.last_dispatched_route.projects, ["Main"])  # type: ignore[union-attr]
        self.assertFalse(bool(runtime.last_dispatched_route.flags.get("all")))  # type: ignore[union-attr]
        self.assertFalse(bool(runtime.last_dispatched_route.flags.get("restart_include_requirements")))  # type: ignore[union-attr]

    def test_restart_selector_marks_full_restart_when_all_selected(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(all_selected=True)
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                ),
                "Main Frontend": ServiceRecord(
                    name="Main Frontend",
                    type="frontend",
                    cwd=".",
                    pid=101,
                    requested_port=9000,
                    actual_port=9000,
                    status="running",
                ),
            },
        )
        route = Route(
            command="restart",
            mode="main",
            raw_args=["restart"],
            passthrough_args=[],
            projects=[],
            flags={"interactive_command": True},
        )
        updated = orchestrator._apply_restart_selection(route, state, runtime)

        self.assertIsNotNone(updated)
        self.assertEqual(updated.projects, ["Main"])
        self.assertFalse(bool(updated.flags.get("all")))
        self.assertTrue(bool(updated.flags.get("restart_include_requirements")))

    def test_restart_selector_service_selection_restarts_selected_service_only(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(service_names=["Main Backend"])
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                ),
                "Main Frontend": ServiceRecord(
                    name="Main Frontend",
                    type="frontend",
                    cwd=".",
                    pid=101,
                    requested_port=9000,
                    actual_port=9000,
                    status="running",
                ),
            },
        )
        route = Route(
            command="restart",
            mode="main",
            raw_args=["restart"],
            passthrough_args=[],
            projects=[],
            flags={"interactive_command": True},
        )
        updated = orchestrator._apply_restart_selection(route, state, runtime)

        self.assertIsNotNone(updated)
        self.assertEqual(updated.projects, ["Main"])
        self.assertEqual(updated.flags.get("services"), ["Main Backend"])
        self.assertEqual(updated.flags.get("restart_service_types"), ["backend"])
        self.assertFalse(bool(updated.flags.get("restart_include_requirements")))

    def test_interactive_shortcuts_map_to_action_commands(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                ),
            },
        )
        runtime._latest_state = state

        for raw, expected in (("p", "pr"), ("c", "commit"), ("a", "review"), ("migrations", "migrate")):
            with self.subTest(raw=raw):
                runtime.last_dispatched_route = None
                should_continue, next_state = orchestrator._run_interactive_command(raw, state, runtime)
                self.assertTrue(should_continue)
                self.assertEqual(next_state.run_id, state.run_id)
                self.assertIsNotNone(runtime.last_dispatched_route)
                self.assertEqual(runtime.last_dispatched_route.command, expected)  # type: ignore[union-attr]

    def test_project_scoped_commands_use_project_selector(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(project_names=["Main"])
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                ),
                "Main Frontend": ServiceRecord(
                    name="Main Frontend",
                    type="frontend",
                    cwd=".",
                    pid=101,
                    requested_port=9000,
                    actual_port=9000,
                    status="running",
                ),
            },
        )
        runtime._latest_state = state

        expected_prompts = {
            "p": "Create PR for",
            "c": "Commit changes for",
            "a": "Review changes for",
            "m": "Run migrations for",
        }
        for raw, prompt in expected_prompts.items():
            with self.subTest(raw=raw):
                runtime.selection_calls.clear()
                runtime.last_dispatched_route = None
                should_continue, next_state = orchestrator._run_interactive_command(raw, state, runtime)
                self.assertTrue(should_continue)
                self.assertEqual(next_state.run_id, state.run_id)
                self.assertEqual(len(runtime.selection_calls), 1)
                self.assertEqual(runtime.selection_calls[0]["selector"], "project")
                self.assertEqual(runtime.selection_calls[0]["prompt"], prompt)
                self.assertIsNotNone(runtime.last_dispatched_route)
                assert runtime.last_dispatched_route is not None
                self.assertEqual(runtime.last_dispatched_route.projects, ["Main"])
                self.assertIsNone(runtime.last_dispatched_route.flags.get("services"))

    def test_interactive_test_prompts_grouped_selector_in_single_project_mode(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(project_names=["Main"])
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                ),
                "Main Frontend": ServiceRecord(
                    name="Main Frontend",
                    type="frontend",
                    cwd=".",
                    pid=101,
                    requested_port=9000,
                    actual_port=9000,
                    status="running",
                ),
            },
        )
        runtime._latest_state = state

        should_continue, next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, "run-1")
        self.assertEqual(len(runtime.selection_calls), 1)
        self.assertEqual(runtime.selection_calls[0]["prompt"], "Run tests for")
        self.assertIsNotNone(runtime.last_dispatched_route)
        self.assertEqual(runtime.last_dispatched_route.projects, ["Main"])  # type: ignore[union-attr]
        self.assertFalse(bool(runtime.last_dispatched_route.flags.get("all")))  # type: ignore[union-attr]

    def test_interactive_test_all_selection_sets_all_flag(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(all_selected=True)
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                )
            },
        )
        runtime._latest_state = state

        should_continue, _next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(len(runtime.selection_calls), 1)
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.projects, ["Main"])
        self.assertFalse(bool(runtime.last_dispatched_route.flags.get("all")))

    def test_interactive_test_cancelled_selector_skips_dispatch(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(cancelled=True)
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                )
            },
        )
        runtime._latest_state = state

        should_continue, next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, "run-1")
        self.assertEqual(len(runtime.selection_calls), 1)
        self.assertIsNone(runtime.last_dispatched_route)

    def test_interactive_test_in_trees_prompts_selector_before_dispatch(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(project_names=["feature-a-1"])
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="trees",
            services={
                "feature-a-1 Backend": ServiceRecord(
                    name="feature-a-1 Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                ),
                "feature-a-1 Frontend": ServiceRecord(
                    name="feature-a-1 Frontend",
                    type="frontend",
                    cwd=".",
                    pid=101,
                    requested_port=9000,
                    actual_port=9000,
                    status="running",
                ),
                "feature-b-1 Backend": ServiceRecord(
                    name="feature-b-1 Backend",
                    type="backend",
                    cwd=".",
                    pid=102,
                    requested_port=8010,
                    actual_port=8010,
                    status="running",
                ),
            },
        )
        runtime._latest_state = state

        should_continue, next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, "run-1")
        self.assertEqual(len(runtime.selection_calls), 1)
        self.assertEqual(runtime.selection_calls[0]["prompt"], "Run tests for")
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.projects, ["feature-a-1"])
        self.assertFalse(bool(runtime.last_dispatched_route.flags.get("all")))

    def test_interactive_test_service_selection_limits_backend_frontend_flags(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(service_names=["feature-a-1 Frontend"])
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="trees",
            services={
                "feature-a-1 Backend": ServiceRecord(
                    name="feature-a-1 Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                ),
                "feature-a-1 Frontend": ServiceRecord(
                    name="feature-a-1 Frontend",
                    type="frontend",
                    cwd=".",
                    pid=101,
                    requested_port=9000,
                    actual_port=9000,
                    status="running",
                ),
            },
        )
        runtime._latest_state = state

        should_continue, next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, "run-1")
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.projects, ["Main"])
        self.assertEqual(runtime.last_dispatched_route.flags.get("services"), ["feature-a-1 Frontend"])
        self.assertEqual(runtime.last_dispatched_route.flags.get("backend"), False)
        self.assertEqual(runtime.last_dispatched_route.flags.get("frontend"), True)

    def test_interactive_test_failure_does_not_print_generic_command_failed_banner(self) -> None:
        runtime = _RuntimeStub()
        runtime.dispatch_code = 1
        runtime.next_selection = TargetSelection(project_names=["Main"])
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                )
            },
        )
        runtime._latest_state = state

        out = StringIO()
        with redirect_stdout(out):
            should_continue, next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, "run-1")
        self.assertNotIn("Command failed (exit 1).", out.getvalue())


if __name__ == "__main__":
    unittest.main()
