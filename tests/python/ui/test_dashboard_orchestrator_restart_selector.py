from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.command_router import Route
from envctl_engine.ui.dashboard.orchestrator import DashboardOrchestrator
from envctl_engine.test_output.parser_base import strip_ansi
from envctl_engine.ui.dashboard.pr_flow import PrFlowResult
from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.ui.target_selector import TargetSelection


class _RuntimeStub:
    def __init__(self, *, base_dir: Path | None = None) -> None:
        self.config = SimpleNamespace(raw={}, base_dir=base_dir or REPO_ROOT)
        self.env: dict[str, str] = {}
        self.selection_calls: list[dict[str, object]] = []
        self.last_dispatched_route: Route | None = None
        self._latest_state: RunState | None = None
        self.next_selection = TargetSelection(project_names=["Main"])
        self.next_selections: list[TargetSelection] = []
        self.dispatch_code: int = 0
        self.read_prompts: list[str] = []
        self.read_responses: list[str] = []
        self.text_input_prompts: list[dict[str, str]] = []
        self.text_input_responses: list[str | None] = []
        self.pr_flow_calls: list[dict[str, object]] = []
        self.next_pr_flow_result: PrFlowResult | None = PrFlowResult(project_names=["Main"], base_branch="main")
        self.startup_orchestrator = object()

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
        return self._pop_selection()

    def _select_project_targets(
        self,
        *,
        prompt: str,
        projects: list[object],
        allow_all: bool,
        allow_untested: bool,
        multi: bool,
        initial_project_names: list[str] | None = None,
        exclusive_project_name: str | None = None,
    ) -> TargetSelection:
        self.selection_calls.append(
            {
                "selector": "project",
                "prompt": prompt,
                "projects": [getattr(project, "name", "") for project in projects],
                "allow_all": allow_all,
                "allow_untested": allow_untested,
                "multi": multi,
                "initial_project_names": list(initial_project_names or []),
                "exclusive_project_name": exclusive_project_name,
            }
        )
        return self._pop_selection()

    def _pop_selection(self) -> TargetSelection:
        if self.next_selections:
            return self.next_selections.pop(0)
        return self.next_selection

    def _read_interactive_command_line(self, prompt: str) -> str:
        self.read_prompts.append(prompt)
        if self.read_responses:
            return self.read_responses.pop(0)
        return ""

    def _prompt_text_input(
        self,
        *,
        title: str,
        help_text: str,
        placeholder: str,
        initial_value: str,
        default_button_label: str,
    ) -> str | None:
        self.text_input_prompts.append(
            {
                "title": title,
                "help_text": help_text,
                "placeholder": placeholder,
                "initial_value": initial_value,
                "default_button_label": default_button_label,
            }
        )
        if self.text_input_responses:
            return self.text_input_responses.pop(0)
        return ""


class _RuntimeStubMissingProjectResolver(_RuntimeStub):
    @staticmethod
    def _project_name_from_service(_name: str) -> str:
        return ""


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

    def test_install_prompts_is_rejected_in_dashboard_context(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(run_id="run-plan", mode="trees")
        runtime._latest_state = state

        out = StringIO()
        with redirect_stdout(out):
            should_continue, next_state = orchestrator._run_interactive_command(
                "install-prompts --cli codex --dry-run",
                state,
                runtime,
            )

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertIsNone(runtime.last_dispatched_route)
        self.assertIn("Command 'install-prompts' is not available in this dashboard context.", out.getvalue())

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
        self.assertEqual(runtime.selection_calls, [])
        self.assertEqual(updated.projects, ["Main"])

    def test_pr_interactive_flow_prompts_for_target_before_base_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "Envctl Tests"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=repo, check=True)
            (repo / "README.md").write_text("test\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "branch", "release/2026-03-10"], cwd=repo, check=True)
            runtime = _RuntimeStub(base_dir=repo)
            orchestrator = DashboardOrchestrator(runtime)
            runtime.next_pr_flow_result = PrFlowResult(project_names=["Main"], base_branch="main")
            state = RunState(
                run_id="run-pr",
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
            orchestrator._run_pr_selection_flow = lambda **kwargs: (
                runtime.pr_flow_calls.append(kwargs) or runtime.next_pr_flow_result
            )  # type: ignore[method-assign]

            should_continue, next_state = orchestrator._run_interactive_command("p", state, runtime)

            self.assertTrue(should_continue)
            self.assertIs(next_state, state)
            self.assertEqual(len(runtime.pr_flow_calls), 1)
            self.assertEqual(runtime.pr_flow_calls[0]["default_branch"], "main")
            self.assertEqual(runtime.read_prompts, [])
            self.assertEqual(len(runtime.text_input_prompts), 1)
            self.assertEqual(runtime.text_input_prompts[0]["title"], "PR Message")
            self.assertEqual(runtime.text_input_prompts[0]["default_button_label"], "Use MAIN_TASK.md")
            self.assertIsNotNone(runtime.last_dispatched_route)
            self.assertEqual(runtime.last_dispatched_route.command, "pr")  # type: ignore[union-attr]
            self.assertEqual(runtime.last_dispatched_route.projects, ["Main"])  # type: ignore[union-attr]
            self.assertEqual(runtime.last_dispatched_route.flags.get("pr_base"), "main")  # type: ignore[union-attr]
            self.assertNotIn("pr_body", runtime.last_dispatched_route.flags)  # type: ignore[union-attr]

    def test_pr_interactive_flow_uses_entered_base_branch_after_target_selection(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        runtime.next_pr_flow_result = PrFlowResult(project_names=["Main"], base_branch="release/2026-03-10")
        state = RunState(
            run_id="run-pr-feature",
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
        orchestrator._run_pr_selection_flow = lambda **kwargs: (
            runtime.pr_flow_calls.append(kwargs) or runtime.next_pr_flow_result
        )  # type: ignore[method-assign]

        should_continue, _next_state = orchestrator._run_interactive_command("p", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(len(runtime.pr_flow_calls), 1)
        self.assertEqual(runtime.read_prompts, [])
        self.assertEqual(runtime.last_dispatched_route.flags.get("pr_base"), "release/2026-03-10")  # type: ignore[union-attr]

    def test_pr_interactive_flow_cancels_when_no_base_branch_is_selected(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        runtime.next_pr_flow_result = PrFlowResult(
            project_names=["Main"],
            base_branch=None,
            cancelled=True,
            cancelled_step="branch",
        )
        state = RunState(
            run_id="run-pr-cancelled",
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
        orchestrator._run_pr_selection_flow = lambda **kwargs: (
            runtime.pr_flow_calls.append(kwargs) or runtime.next_pr_flow_result
        )  # type: ignore[method-assign]

        out = StringIO()
        with redirect_stdout(out):
            should_continue, next_state = orchestrator._run_interactive_command("p", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertIsNone(runtime.last_dispatched_route)
        self.assertIn("No PR base branch selected.", out.getvalue())

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
        self.assertEqual(len(runtime.selection_calls), 0)

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
        runtime.next_selection = TargetSelection(project_names=["Backend", "Frontend"])
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
        self.assertEqual(runtime.selection_calls[0]["prompt"], "Choose services")
        self.assertEqual(runtime.selection_calls[0]["projects"], ["Backend", "Frontend"])
        self.assertIsNotNone(runtime.last_dispatched_route)
        self.assertEqual(runtime.last_dispatched_route.projects, ["Main"])  # type: ignore[union-attr]
        self.assertFalse(bool(runtime.last_dispatched_route.flags.get("all")))  # type: ignore[union-attr]
        self.assertTrue(bool(runtime.last_dispatched_route.flags.get("restart_include_requirements")))  # type: ignore[union-attr]

    def test_restart_selector_marks_full_restart_when_all_selected(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(project_names=["Backend", "Frontend"])
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
        runtime.next_selection = TargetSelection(project_names=["Backend"])
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
                if raw == "p":
                    orchestrator._run_pr_selection_flow = lambda **kwargs: (
                        runtime.pr_flow_calls.append(kwargs) or runtime.next_pr_flow_result
                    )  # type: ignore[method-assign]
                should_continue, next_state = orchestrator._run_interactive_command(raw, state, runtime)
                self.assertTrue(should_continue)
                self.assertEqual(next_state.run_id, state.run_id)
                self.assertIsNotNone(runtime.last_dispatched_route)
                self.assertEqual(runtime.last_dispatched_route.command, expected)  # type: ignore[union-attr]

    def test_project_scoped_commands_auto_select_single_project(self) -> None:
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

        for raw in ("p", "c", "a", "m"):
            with self.subTest(raw=raw):
                runtime.selection_calls.clear()
                runtime.pr_flow_calls.clear()
                runtime.last_dispatched_route = None
                if raw == "p":
                    orchestrator._run_pr_selection_flow = lambda **kwargs: (
                        runtime.pr_flow_calls.append(kwargs) or runtime.next_pr_flow_result
                    )  # type: ignore[method-assign]
                should_continue, next_state = orchestrator._run_interactive_command(raw, state, runtime)
                self.assertTrue(should_continue)
                self.assertEqual(next_state.run_id, state.run_id)
                self.assertEqual(len(runtime.selection_calls), 0)
                if raw == "p":
                    self.assertEqual(len(runtime.pr_flow_calls), 1)
                    self.assertEqual(runtime.pr_flow_calls[0]["initial_project_names"], ["Main"])
                else:
                    self.assertEqual(len(runtime.pr_flow_calls), 0)
                self.assertIsNotNone(runtime.last_dispatched_route)
                assert runtime.last_dispatched_route is not None
                self.assertEqual(runtime.last_dispatched_route.projects, ["Main"])
                self.assertIsNone(runtime.last_dispatched_route.flags.get("services"))

    def test_commit_prompts_for_message_and_uses_explicit_value_when_provided(self) -> None:
        runtime = _RuntimeStub()
        runtime.text_input_responses = ["Ship the feature"]
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

        should_continue, next_state = orchestrator._run_interactive_command("c", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, state.run_id)
        self.assertEqual(runtime.read_prompts, [])
        self.assertEqual(len(runtime.text_input_prompts), 1)
        self.assertEqual(runtime.text_input_prompts[0]["title"], "Commit Message")
        self.assertEqual(runtime.text_input_prompts[0]["default_button_label"], "Use changelog")
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.command, "commit")
        self.assertEqual(runtime.last_dispatched_route.projects, ["Main"])
        self.assertEqual(runtime.last_dispatched_route.flags.get("commit_message"), "Ship the feature")

    def test_commit_blank_message_uses_existing_default_resolution(self) -> None:
        runtime = _RuntimeStub()
        runtime.text_input_responses = [""]
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

        should_continue, next_state = orchestrator._run_interactive_command("c", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, state.run_id)
        self.assertEqual(runtime.read_prompts, [])
        self.assertEqual(len(runtime.text_input_prompts), 1)
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.command, "commit")
        self.assertNotIn("commit_message", runtime.last_dispatched_route.flags)

    def test_pr_prompts_for_message_and_uses_explicit_value_when_provided(self) -> None:
        runtime = _RuntimeStub()
        runtime.text_input_responses = ["Ship the feature in this PR"]
        orchestrator = DashboardOrchestrator(runtime)
        orchestrator._run_pr_selection_flow = lambda **kwargs: (
            runtime.pr_flow_calls.append(kwargs) or runtime.next_pr_flow_result
        )  # type: ignore[method-assign]
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

        should_continue, next_state = orchestrator._run_interactive_command("p", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, state.run_id)
        self.assertEqual(runtime.read_prompts, [])
        self.assertEqual(len(runtime.text_input_prompts), 1)
        self.assertEqual(runtime.text_input_prompts[0]["title"], "PR Message")
        self.assertEqual(runtime.text_input_prompts[0]["default_button_label"], "Use MAIN_TASK.md")
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.command, "pr")
        self.assertEqual(runtime.last_dispatched_route.projects, ["Main"])
        self.assertEqual(runtime.last_dispatched_route.flags.get("pr_base"), "main")
        self.assertEqual(runtime.last_dispatched_route.flags.get("pr_body"), "Ship the feature in this PR")

    def test_pr_blank_message_uses_existing_default_resolution(self) -> None:
        runtime = _RuntimeStub()
        runtime.text_input_responses = [""]
        orchestrator = DashboardOrchestrator(runtime)
        orchestrator._run_pr_selection_flow = lambda **kwargs: (
            runtime.pr_flow_calls.append(kwargs) or runtime.next_pr_flow_result
        )  # type: ignore[method-assign]
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

        should_continue, next_state = orchestrator._run_interactive_command("p", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, state.run_id)
        self.assertEqual(runtime.read_prompts, [])
        self.assertEqual(len(runtime.text_input_prompts), 1)
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.command, "pr")
        self.assertNotIn("pr_body", runtime.last_dispatched_route.flags)

    def test_project_scoped_commands_use_project_selector_when_multiple_projects_exist(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(project_names=["Feature A"])
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="trees",
            services={
                "Feature A Backend": ServiceRecord(
                    name="Feature A Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                ),
                "Feature B Backend": ServiceRecord(
                    name="Feature B Backend",
                    type="backend",
                    cwd=".",
                    pid=101,
                    requested_port=8001,
                    actual_port=8001,
                    status="running",
                ),
            },
        )
        runtime._latest_state = state

        should_continue, next_state = orchestrator._run_interactive_command("c", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, state.run_id)
        self.assertEqual(len(runtime.selection_calls), 1)
        self.assertEqual(runtime.selection_calls[0]["selector"], "project")
        self.assertEqual(runtime.selection_calls[0]["prompt"], "Commit changes for")
        self.assertIsNotNone(runtime.last_dispatched_route)
        self.assertEqual(runtime.last_dispatched_route.projects, ["Feature A"])  # type: ignore[union-attr]

    def test_interactive_test_auto_selects_single_project_in_single_project_mode(self) -> None:
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

        should_continue, next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, "run-1")
        self.assertEqual(len(runtime.selection_calls), 0)
        self.assertIsNotNone(runtime.last_dispatched_route)
        self.assertEqual(runtime.last_dispatched_route.projects, ["Main"])  # type: ignore[union-attr]
        self.assertFalse(bool(runtime.last_dispatched_route.flags.get("all")))  # type: ignore[union-attr]

    def test_interactive_test_single_project_with_backend_and_frontend_prompts_selector(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(project_names=["Backend", "Frontend"])
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
        self.assertEqual(runtime.selection_calls[0]["prompt"], "Choose test scope")
        self.assertEqual(runtime.selection_calls[0]["projects"], ["Backend", "Frontend"])
        self.assertEqual(runtime.selection_calls[0]["multi"], True)
        self.assertIsNotNone(runtime.last_dispatched_route)
        self.assertEqual(runtime.last_dispatched_route.projects, ["Main"])  # type: ignore[union-attr]

    def test_interactive_test_single_project_auto_selects_without_selector(self) -> None:
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

        should_continue, _next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(len(runtime.selection_calls), 0)
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.projects, ["Main"])
        self.assertFalse(bool(runtime.last_dispatched_route.flags.get("all")))

    def test_interactive_test_cancelled_selector_skips_dispatch_when_multiple_projects(self) -> None:
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
                ),
                "Docs Backend": ServiceRecord(
                    name="Docs Backend",
                    type="backend",
                    cwd=".",
                    pid=101,
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
        self.assertIsNone(runtime.last_dispatched_route)

    def test_interactive_test_in_trees_prompts_selector_before_dispatch(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selections = [
            TargetSelection(project_names=["feature-a-1"]),
            TargetSelection(project_names=["Backend", "Frontend"]),
        ]
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
        self.assertEqual(len(runtime.selection_calls), 2)
        self.assertEqual(runtime.selection_calls[0]["prompt"], "Choose worktrees to test")
        self.assertEqual(runtime.selection_calls[1]["prompt"], "Choose test scope")
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.projects, ["feature-a-1"])
        self.assertFalse(bool(runtime.last_dispatched_route.flags.get("all")))

    def test_interactive_test_in_trees_preselects_deployed_worktrees(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selections = [
            TargetSelection(project_names=["feature-a-1"]),
            TargetSelection(project_names=["Backend", "Frontend"]),
        ]
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

        with patch(
            "envctl_engine.ui.dashboard.orchestrator._tree_preselected_projects_from_state_impl",
            return_value=["feature-b-1"],
        ):
            should_continue, next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, "run-1")
        self.assertEqual(len(runtime.selection_calls), 2)
        self.assertEqual(runtime.selection_calls[0]["prompt"], "Choose worktrees to test")
        self.assertEqual(runtime.selection_calls[0]["initial_project_names"], ["feature-b-1"])

    def test_interactive_test_in_trees_auto_selects_single_project_before_dispatch(self) -> None:
        runtime = _RuntimeStub()
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
            },
        )
        runtime._latest_state = state

        should_continue, next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, "run-1")
        self.assertEqual(len(runtime.selection_calls), 0)
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.projects, ["feature-a-1"])
        self.assertFalse(bool(runtime.last_dispatched_route.flags.get("all")))

    def test_interactive_test_service_selection_limits_backend_frontend_flags(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selections = [
            TargetSelection(project_names=["feature-a-1"]),
            TargetSelection(project_names=["Frontend"]),
        ]
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
        self.assertEqual(len(runtime.selection_calls), 2)
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.projects, ["feature-a-1"])
        self.assertEqual(runtime.last_dispatched_route.flags.get("services"), ["feature-a-1 Frontend"])
        self.assertEqual(runtime.last_dispatched_route.flags.get("backend"), False)
        self.assertEqual(runtime.last_dispatched_route.flags.get("frontend"), True)

    def test_interactive_test_service_selection_offers_failed_rerun_when_saved_failures_exist(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(project_names=["Failed tests"])
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
            metadata={
                "project_test_summaries": {
                    "Main": {
                        "manifest_path": "/tmp/runtime/Main_failed_tests_manifest.json",
                        "failed_tests": 2,
                        "status": "failed",
                    }
                }
            },
        )
        runtime._latest_state = state

        should_continue, next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, "run-1")
        self.assertEqual(runtime.selection_calls[0]["projects"], ["Backend", "Frontend", "Failed tests"])
        self.assertEqual(runtime.selection_calls[0]["multi"], True)
        self.assertEqual(runtime.selection_calls[0]["exclusive_project_name"], "Failed tests")
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertTrue(bool(runtime.last_dispatched_route.flags.get("failed")))
        self.assertNotIn("services", runtime.last_dispatched_route.flags)
        self.assertNotIn("backend", runtime.last_dispatched_route.flags)
        self.assertNotIn("frontend", runtime.last_dispatched_route.flags)

    def test_interactive_test_service_selection_hides_failed_rerun_without_saved_failures(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(project_names=["Backend", "Frontend"])
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

        should_continue, _next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(runtime.selection_calls[0]["projects"], ["Backend", "Frontend"])
        self.assertEqual(runtime.selection_calls[0]["multi"], True)
        self.assertIsNone(runtime.selection_calls[0]["exclusive_project_name"])

    def test_interactive_test_service_selection_keeps_failed_rerun_when_saved_failure_state_exists_even_if_latest_status_passed(
        self,
    ) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(project_names=["Backend", "Frontend"])
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
            metadata={
                "project_test_summaries": {
                    "Main": {
                        "manifest_path": "/tmp/runtime/Main_failed_tests_manifest.json",
                        "short_summary_path": "/tmp/runtime/ft_deadbeef00.txt",
                        "failed_tests": 0,
                        "failed_manifest_entries": 0,
                        "status": "passed",
                    }
                }
            },
        )
        runtime._latest_state = state

        should_continue, _next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(runtime.selection_calls[0]["projects"], ["Backend", "Frontend", "Failed tests"])
        self.assertEqual(runtime.selection_calls[0]["multi"], True)
        self.assertEqual(runtime.selection_calls[0]["exclusive_project_name"], "Failed tests")

    def test_interactive_test_service_selection_falls_back_to_service_name_parsing(self) -> None:
        runtime = _RuntimeStubMissingProjectResolver()
        runtime.next_selection = TargetSelection(project_names=["Failed tests"])
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
            metadata={
                "project_test_summaries": {
                    "Main": {
                        "manifest_path": "/tmp/runtime/Main_failed_tests_manifest.json",
                        "failed_tests": 2,
                        "status": "failed",
                    }
                }
            },
        )
        runtime._latest_state = state

        should_continue, _next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(runtime.selection_calls[0]["projects"], ["Backend", "Frontend", "Failed tests"])
        self.assertEqual(runtime.selection_calls[0]["multi"], True)
        self.assertEqual(runtime.selection_calls[0]["exclusive_project_name"], "Failed tests")

    def test_interactive_test_service_selection_uses_configured_service_types_when_services_not_running(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(project_names=["Failed tests"])
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="main",
            services={},
            metadata={
                "dashboard_configured_service_types": ["backend", "frontend"],
                "project_roots": {"Main": "."},
                "project_test_summaries": {
                    "Main": {
                        "manifest_path": "/tmp/runtime/Main_failed_tests_manifest.json",
                        "failed_tests": 2,
                        "status": "failed",
                    }
                },
            },
        )
        runtime._latest_state = state

        should_continue, _next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(runtime.selection_calls[0]["projects"], ["Backend", "Frontend", "Failed tests"])
        self.assertEqual(runtime.selection_calls[0]["multi"], True)
        self.assertEqual(runtime.selection_calls[0]["exclusive_project_name"], "Failed tests")

    def test_interactive_test_service_selection_offers_failed_rerun_when_status_failed_but_count_zero(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(project_names=["Failed tests"])
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
            metadata={
                "project_test_summaries": {
                    "Main": {
                        "manifest_path": "/tmp/runtime/Main_failed_tests_manifest.json",
                        "failed_tests": 0,
                        "failed_manifest_entries": 0,
                        "status": "failed",
                    }
                }
            },
        )
        runtime._latest_state = state

        should_continue, _next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(runtime.selection_calls[0]["projects"], ["Backend", "Frontend", "Failed tests"])
        self.assertEqual(runtime.selection_calls[0]["multi"], True)
        self.assertEqual(runtime.selection_calls[0]["exclusive_project_name"], "Failed tests")
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertTrue(bool(runtime.last_dispatched_route.flags.get("failed")))

    def test_interactive_test_service_selection_offers_all_tests_when_only_root_suite_exists(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(project_names=["Backend", "Frontend"])
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="main",
            services={},
            metadata={
                "project_roots": {"Main": "."},
                "project_test_summaries": {
                    "Main": {
                        "manifest_path": "/tmp/runtime/Main_failed_tests_manifest.json",
                        "failed_tests": 2,
                        "status": "failed",
                    }
                },
            },
        )
        runtime._latest_state = state

        should_continue, _next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(runtime.selection_calls[0]["projects"], ["All tests", "Failed tests"])
        self.assertEqual(runtime.selection_calls[0]["multi"], True)
        self.assertEqual(runtime.selection_calls[0]["exclusive_project_name"], "Failed tests")
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertNotIn("services", runtime.last_dispatched_route.flags)
        self.assertNotIn("backend", runtime.last_dispatched_route.flags)
        self.assertNotIn("frontend", runtime.last_dispatched_route.flags)
        self.assertNotIn("failed", runtime.last_dispatched_route.flags)

    def test_interactive_test_failure_does_not_print_generic_command_failed_banner(self) -> None:
        runtime = _RuntimeStub()
        runtime.dispatch_code = 1
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

        def failing_dispatch(route: Route) -> int:
            runtime.last_dispatched_route = route
            runtime._latest_state = RunState(
                run_id="run-1",
                mode="main",
                services=state.services,
                metadata={
                    "project_test_summaries": {
                        "Main": {
                            "summary_path": "/tmp/runtime/test-results/run_1/Main/failed_tests_summary.txt",
                            "short_summary_path": "/tmp/runtime/run_1/ft_deadbeef00.txt",
                            "status": "failed",
                        }
                    }
                },
            )
            return 1

        runtime.dispatch = failing_dispatch  # type: ignore[assignment]

        out = StringIO()
        with redirect_stdout(out):
            should_continue, next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, "run-1")
        self.assertNotIn("Command failed (exit 1).", out.getvalue())
        self.assertNotIn("Test failure summary for Main:", strip_ansi(out.getvalue()))
        self.assertNotIn("Failed test summaries:", strip_ansi(out.getvalue()))
        self.assertEqual(runtime.read_prompts, ["Press Enter to return to dashboard: "])

    def test_interactive_test_success_pauses_before_returning_to_dashboard(self) -> None:
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

        should_continue, next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, "run-1")
        self.assertEqual(runtime.read_prompts, ["Press Enter to return to dashboard: "])

    def test_interactive_migrate_failure_prints_summary_and_failure_log_path(self) -> None:
        runtime = _RuntimeStub()
        runtime.dispatch_code = 1
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

        def failing_dispatch(route: Route) -> int:
            runtime.last_dispatched_route = route
            runtime._latest_state = RunState(
                run_id="run-1",
                mode="main",
                services=state.services,
                metadata={
                    "project_action_reports": {
                        "Main": {
                            "migrate": {
                                "status": "failed",
                                "summary": "alembic.util.exc.CommandError: migration failed\nsecond line",
                                "report_path": "/tmp/runtime/Main_migrate.txt",
                            }
                        }
                    }
                },
            )
            return 1

        runtime.dispatch = failing_dispatch  # type: ignore[assignment]

        out = StringIO()
        with redirect_stdout(out):
            should_continue, next_state = orchestrator._run_interactive_command("m", state, runtime)

        rendered = out.getvalue()
        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, "run-1")
        self.assertIn("migrate failed for Main: alembic.util.exc.CommandError: migration failed", rendered)
        self.assertIn(
            "migrate failure log for Main:\n/tmp/runtime/Main_migrate.txt",
            rendered,
        )
        self.assertNotIn("Command failed (exit 1).", rendered)


if __name__ == "__main__":
    unittest.main()
