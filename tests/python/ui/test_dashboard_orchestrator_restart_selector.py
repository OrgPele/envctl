from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.runtime.command_router import Route
from envctl_engine.ui.dashboard.orchestrator import DashboardOrchestrator
from envctl_engine.test_output.parser_base import strip_ansi
from envctl_engine.ui.dashboard.pr_flow import PrFlowResult
from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.ui.target_selector import TargetSelection


class _TtyStringIO(StringIO):
    def isatty(self) -> bool:
        return True


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
        self.confirm_prompts: list[dict[str, str]] = []
        self.confirm_responses: list[bool | None] = []
        self.pr_flow_calls: list[dict[str, object]] = []
        self.next_pr_flow_result: PrFlowResult | None = PrFlowResult(project_names=["Main"], base_branch="main")
        self.startup_orchestrator = object()
        self.dispatched_routes: list[Route] = []

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
        self.dispatched_routes.append(route)
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

    def _prompt_yes_no(self, *, title: str, prompt: str) -> bool | None:
        self.confirm_prompts.append({"title": title, "prompt": prompt})
        if self.confirm_responses:
            return self.confirm_responses.pop(0)
        return False


class _RuntimeStubMissingProjectResolver(_RuntimeStub):
    @staticmethod
    def _project_name_from_service(name: str) -> str:
        _ = name
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
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.command, "stop")

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
        assert updated is not None
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

    def test_test_failure_details_render_hyperlinked_summary_path(self) -> None:
        runtime = _RuntimeStub()
        runtime.env["ENVCTL_UI_HYPERLINK_MODE"] = "on"
        orchestrator = DashboardOrchestrator(runtime)
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_path = Path(tmpdir) / "failed_tests_summary.txt"
            summary_path.write_text("summary\n", encoding="utf-8")
            state = RunState(
                run_id="run-1",
                mode="main",
                metadata={
                    "project_test_summaries": {
                        "Main": {
                            "short_summary_path": str(summary_path),
                            "status": "failed",
                        }
                    }
                },
            )

            out = _TtyStringIO()
            with redirect_stdout(out):
                printed = orchestrator._print_test_failure_details(
                    Route(command="test", mode="main", raw_args=["test"], passthrough_args=[], projects=["Main"], flags={}),
                    state,
                )

        self.assertTrue(printed)
        self.assertIn("\x1b]8;;file://", out.getvalue())
        self.assertIn(str(summary_path), strip_ansi(out.getvalue()))

    def test_project_action_failure_details_render_hyperlinked_report_path(self) -> None:
        runtime = _RuntimeStub()
        runtime.env["ENVCTL_UI_HYPERLINK_MODE"] = "on"
        orchestrator = DashboardOrchestrator(runtime)
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "failure.log"
            report_path.write_text("report\n", encoding="utf-8")
            state = RunState(
                run_id="run-1",
                mode="main",
                metadata={
                    "project_action_reports": {
                        "Main": {
                            "review": {
                                "status": "failed",
                                "summary": "review failed\nhint: open the log",
                                "report_path": str(report_path),
                            }
                        }
                    }
                },
            )

            out = _TtyStringIO()
            with redirect_stdout(out):
                printed = orchestrator._print_project_action_failure_details(
                    Route(
                        command="review",
                        mode="main",
                        raw_args=["review"],
                        passthrough_args=[],
                        projects=["Main"],
                        flags={},
                    ),
                    state,
                )

        self.assertTrue(printed)
        self.assertIn("\x1b]8;;file://", out.getvalue())
        self.assertIn(str(report_path), strip_ansi(out.getvalue()))

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

        with patch("envctl_engine.ui.dashboard.orchestrator.probe_dirty_worktree") as dirty_probe:
            dirty_probe.return_value = SimpleNamespace(
                project_name="Main",
                project_root=Path(runtime.config.base_dir),
                git_root=Path(runtime.config.base_dir),
                staged=False,
                unstaged=False,
                untracked=False,
                dirty=False,
            )
            should_continue, _next_state = orchestrator._run_interactive_command("p", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(len(runtime.pr_flow_calls), 1)
        self.assertEqual(runtime.read_prompts, [])
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.flags.get("pr_base"), "release/2026-03-10")

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
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.projects, ["Main"])
        self.assertFalse(bool(runtime.last_dispatched_route.flags.get("all")))
        self.assertTrue(bool(runtime.last_dispatched_route.flags.get("restart_include_requirements")))

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
        assert updated is not None
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
        assert updated is not None
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
                    with patch("envctl_engine.ui.dashboard.orchestrator.probe_dirty_worktree") as dirty_probe:
                        dirty_probe.return_value = SimpleNamespace(
                            project_name="Main",
                            project_root=Path(runtime.config.base_dir),
                            git_root=Path(runtime.config.base_dir),
                            staged=False,
                            unstaged=False,
                            untracked=False,
                            dirty=False,
                        )
                        should_continue, next_state = orchestrator._run_interactive_command(raw, state, runtime)
                else:
                    should_continue, next_state = orchestrator._run_interactive_command(raw, state, runtime)
                self.assertTrue(should_continue)
                self.assertEqual(next_state.run_id, state.run_id)
                self.assertIsNotNone(runtime.last_dispatched_route)
                assert runtime.last_dispatched_route is not None
                self.assertEqual(runtime.last_dispatched_route.command, expected)

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
                    with patch("envctl_engine.ui.dashboard.orchestrator.probe_dirty_worktree") as dirty_probe:
                        dirty_probe.return_value = SimpleNamespace(
                            project_name="Main",
                            project_root=Path(runtime.config.base_dir),
                            git_root=Path(runtime.config.base_dir),
                            staged=False,
                            unstaged=False,
                            untracked=False,
                            dirty=False,
                        )
                        should_continue, next_state = orchestrator._run_interactive_command(raw, state, runtime)
                else:
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
        self.assertEqual(runtime.text_input_prompts[0]["default_button_label"], "Use envctl commit log")
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

        with patch("envctl_engine.ui.dashboard.orchestrator.probe_dirty_worktree") as dirty_probe:
            dirty_probe.return_value = SimpleNamespace(
                project_name="Main",
                project_root=Path(runtime.config.base_dir),
                git_root=Path(runtime.config.base_dir),
                staged=False,
                unstaged=False,
                untracked=False,
                dirty=False,
            )
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

        with patch("envctl_engine.ui.dashboard.orchestrator.probe_dirty_worktree") as dirty_probe:
            dirty_probe.return_value = SimpleNamespace(
                project_name="Main",
                project_root=Path(runtime.config.base_dir),
                git_root=Path(runtime.config.base_dir),
                staged=False,
                unstaged=False,
                untracked=False,
                dirty=False,
            )
            should_continue, next_state = orchestrator._run_interactive_command("p", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, state.run_id)
        self.assertEqual(runtime.read_prompts, [])
        self.assertEqual(len(runtime.text_input_prompts), 1)
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.command, "pr")
        self.assertNotIn("pr_body", runtime.last_dispatched_route.flags)

    def test_pr_dirty_target_accepts_commit_then_dispatches_pr(self) -> None:
        runtime = _RuntimeStub()
        runtime.text_input_responses = ["PR body", "Ship dirty changes"]
        orchestrator = DashboardOrchestrator(runtime)
        orchestrator._run_pr_selection_flow = lambda **kwargs: (
            runtime.pr_flow_calls.append(kwargs) or runtime.next_pr_flow_result
        )  # type: ignore[method-assign]
        state = RunState(
            run_id="run-pr-dirty-accept",
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
            metadata={"project_roots": {"Main": "."}},
        )
        runtime._latest_state = state

        with (
            patch("envctl_engine.ui.dashboard.orchestrator.probe_dirty_worktree") as dirty_probe,
            patch("envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl") as selector,
        ):
            selector.return_value = ["__DIRTY_PR_COMMIT__"]
            dirty_probe.return_value = SimpleNamespace(
                project_name="Main",
                project_root=Path(runtime.config.base_dir),
                git_root=Path(runtime.config.base_dir),
                staged=False,
                unstaged=True,
                untracked=False,
                dirty=True,
            )
            should_continue, next_state = orchestrator._run_interactive_command("p", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual([route.command for route in runtime.dispatched_routes], ["commit", "pr"])
        self.assertEqual(runtime.dispatched_routes[0].projects, ["Main"])
        self.assertEqual(runtime.dispatched_routes[0].flags.get("commit_message"), "Ship dirty changes")
        self.assertEqual(runtime.dispatched_routes[1].flags.get("pr_body"), "PR body")
        selector.assert_called_once()
        selector_kwargs = selector.call_args.kwargs
        self.assertEqual(
            selector_kwargs["prompt"],
            "UNSTAGED CODE IN WORKTREE Main - DO YOU WANT TO STAGE IT?",
        )
        self.assertEqual([item.label for item in selector_kwargs["options"]], ["Commit", "Do nothing"])
        self.assertEqual([item.kind for item in selector_kwargs["options"]], ["", ""])
        self.assertEqual(selector_kwargs["multi"], False)

    def test_pr_dirty_target_decline_skips_commit_and_dispatches_pr_only(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        orchestrator._run_pr_selection_flow = lambda **kwargs: (
            runtime.pr_flow_calls.append(kwargs) or runtime.next_pr_flow_result
        )  # type: ignore[method-assign]
        state = RunState(
            run_id="run-pr-dirty-decline",
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
            metadata={"project_roots": {"Main": "."}},
        )
        runtime._latest_state = state

        with (
            patch("envctl_engine.ui.dashboard.orchestrator.probe_dirty_worktree") as dirty_probe,
            patch("envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl", return_value=["__DIRTY_PR_SKIP__"]),
        ):
            dirty_probe.return_value = SimpleNamespace(
                project_name="Main",
                project_root=Path(runtime.config.base_dir),
                git_root=Path(runtime.config.base_dir),
                staged=True,
                unstaged=False,
                untracked=False,
                dirty=True,
            )
            should_continue, next_state = orchestrator._run_interactive_command("p", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual([route.command for route in runtime.dispatched_routes], ["pr"])

    def test_pr_dirty_target_cancel_aborts_without_dispatch(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        orchestrator._run_pr_selection_flow = lambda **kwargs: (
            runtime.pr_flow_calls.append(kwargs) or runtime.next_pr_flow_result
        )  # type: ignore[method-assign]
        state = RunState(
            run_id="run-pr-dirty-cancel",
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
            metadata={"project_roots": {"Main": "."}},
        )
        runtime._latest_state = state

        out = StringIO()
        with (
            patch("envctl_engine.ui.dashboard.orchestrator.probe_dirty_worktree") as dirty_probe,
            patch("envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl", return_value=None),
            redirect_stdout(out),
        ):
            dirty_probe.return_value = SimpleNamespace(
                project_name="Main",
                project_root=Path(runtime.config.base_dir),
                git_root=Path(runtime.config.base_dir),
                staged=False,
                unstaged=False,
                untracked=True,
                dirty=True,
            )
            should_continue, next_state = orchestrator._run_interactive_command("p", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual(runtime.dispatched_routes, [])
        self.assertIn("Cancelled PR creation.", out.getvalue())

    def test_prompt_yes_no_dialog_supports_runtime_single_argument_signature(self) -> None:
        prompts: list[str] = []

        class _RuntimeSingleArgConfirm:
            @staticmethod
            def _prompt_yes_no(prompt: str) -> bool:
                prompts.append(prompt)
                return True

        result = DashboardOrchestrator._prompt_yes_no_dialog(
            _RuntimeSingleArgConfirm(),
            title="Commit dirty changes before PR?",
            prompt="Main has unstaged changes. Choose whether to commit first, continue without committing, or cancel PR creation.",
        )

        self.assertEqual(result, "commit")
        self.assertEqual(
            prompts,
            [
                "Main has unstaged changes. Choose whether to commit first, continue without committing, or cancel PR creation."
            ],
        )

    def test_prompt_yes_no_dialog_blank_fallback_declines_commit(self) -> None:
        class _RuntimeReadFallback:
            def __init__(self) -> None:
                self.read_prompts: list[str] = []
                self.read_responses: list[str] = [""]

            def _read_interactive_command_line(self, prompt: str) -> str:
                self.read_prompts.append(prompt)
                if self.read_responses:
                    return self.read_responses.pop(0)
                return ""

        runtime = _RuntimeReadFallback()

        result = DashboardOrchestrator._prompt_yes_no_dialog(
            runtime,
            title="Commit dirty changes before PR?",
            prompt="Main has unstaged changes. Choose whether to commit first, continue without committing, or cancel PR creation.",
        )

        self.assertEqual(result, "skip")
        self.assertEqual(
            runtime.read_prompts,
            [
                "Main has unstaged changes. Choose whether to commit first, continue without committing, or cancel PR creation."
            ],
        )

    def test_pr_clean_target_skips_commit_prompt(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        orchestrator._run_pr_selection_flow = lambda **kwargs: (
            runtime.pr_flow_calls.append(kwargs) or runtime.next_pr_flow_result
        )  # type: ignore[method-assign]
        state = RunState(
            run_id="run-pr-clean",
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
            metadata={"project_roots": {"Main": "."}},
        )
        runtime._latest_state = state

        with patch("envctl_engine.ui.dashboard.orchestrator.probe_dirty_worktree") as dirty_probe:
            dirty_probe.return_value = SimpleNamespace(
                project_name="Main",
                project_root=Path(runtime.config.base_dir),
                git_root=Path(runtime.config.base_dir),
                staged=False,
                unstaged=False,
                untracked=False,
                dirty=False,
            )
            should_continue, next_state = orchestrator._run_interactive_command("p", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual(runtime.confirm_prompts, [])
        self.assertEqual([route.command for route in runtime.dispatched_routes], ["pr"])

    def test_typed_pr_command_still_runs_dirty_preflight(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-pr-typed",
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
            metadata={"project_roots": {"Main": "."}},
        )
        runtime._latest_state = state

        with (
            patch("envctl_engine.ui.dashboard.orchestrator.probe_dirty_worktree") as dirty_probe,
            patch("envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl", return_value=["__DIRTY_PR_SKIP__"]),
        ):
            dirty_probe.return_value = SimpleNamespace(
                project_name="Main",
                project_root=Path(runtime.config.base_dir),
                git_root=Path(runtime.config.base_dir),
                staged=True,
                unstaged=False,
                untracked=False,
                dirty=True,
            )
            should_continue, next_state = orchestrator._run_interactive_command(
                "pr --project Main --pr-base release/2026-03-10",
                state,
                runtime,
            )

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        dirty_probe.assert_called_once()
        self.assertEqual([route.command for route in runtime.dispatched_routes], ["pr"])
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.flags.get("pr_base"), "release/2026-03-10")

    def test_pr_commit_failure_aborts_pr_dispatch(self) -> None:
        runtime = _RuntimeStub()
        runtime.text_input_responses = ["Ship dirty changes"]
        orchestrator = DashboardOrchestrator(runtime)
        orchestrator._run_pr_selection_flow = lambda **kwargs: (
            runtime.pr_flow_calls.append(kwargs) or runtime.next_pr_flow_result
        )  # type: ignore[method-assign]
        state = RunState(
            run_id="run-pr-commit-fail",
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
            metadata={
                "project_roots": {"Main": "."},
                "project_action_reports": {
                    "Main": {
                        "commit": {
                            "status": "failed",
                            "summary": "git commit failed\ndetails",
                            "report_path": "/tmp/runtime/Main_commit.txt",
                        }
                    }
                },
            },
        )
        runtime._latest_state = state

        def fail_commit_dispatch(route: Route) -> int:
            runtime.last_dispatched_route = route
            runtime.dispatched_routes.append(route)
            return 1 if route.command == "commit" else 0

        runtime.dispatch = fail_commit_dispatch  # type: ignore[assignment]

        out = StringIO()
        with (
            patch("envctl_engine.ui.dashboard.orchestrator.probe_dirty_worktree") as dirty_probe,
            patch("envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl", return_value=["__DIRTY_PR_COMMIT__"]),
            redirect_stdout(out),
        ):
            dirty_probe.return_value = SimpleNamespace(
                project_name="Main",
                project_root=Path(runtime.config.base_dir),
                git_root=Path(runtime.config.base_dir),
                staged=True,
                unstaged=True,
                untracked=False,
                dirty=True,
            )
            should_continue, next_state = orchestrator._run_interactive_command("p", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual([route.command for route in runtime.dispatched_routes], ["commit"])
        self.assertIn("commit failed for Main: git commit failed", out.getvalue())

    def test_pr_multi_target_commits_only_dirty_subset(self) -> None:
        runtime = _RuntimeStub()
        runtime.text_input_responses = ["Ship dirty subset"]
        runtime.next_pr_flow_result = PrFlowResult(project_names=["feature-a-1", "feature-b-1"], base_branch="main")
        orchestrator = DashboardOrchestrator(runtime)
        orchestrator._run_pr_selection_flow = lambda **kwargs: (
            runtime.pr_flow_calls.append(kwargs) or runtime.next_pr_flow_result
        )  # type: ignore[method-assign]
        state = RunState(
            run_id="run-pr-dirty-multi",
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
                "feature-b-1 Backend": ServiceRecord(
                    name="feature-b-1 Backend",
                    type="backend",
                    cwd=".",
                    pid=101,
                    requested_port=8001,
                    actual_port=8001,
                    status="running",
                ),
            },
            metadata={
                "project_roots": {
                    "feature-a-1": "trees/feature-a/1",
                    "feature-b-1": "trees/feature-b/1",
                }
            },
        )
        runtime._latest_state = state

        def fake_probe(project_root: Path, repo_root: Path, *, project_name: str = "") -> object:
            is_dirty = project_name == "feature-a-1"
            return SimpleNamespace(
                project_name=project_name,
                project_root=project_root,
                git_root=project_root,
                staged=is_dirty,
                unstaged=False,
                untracked=False,
                dirty=is_dirty,
            )

        with (
            patch("envctl_engine.ui.dashboard.orchestrator.probe_dirty_worktree", side_effect=fake_probe),
            patch("envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl", return_value=["__DIRTY_PR_COMMIT__"]),
        ):
            should_continue, next_state = orchestrator._run_interactive_command("p", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual([route.command for route in runtime.dispatched_routes], ["commit", "pr"])
        self.assertEqual(runtime.dispatched_routes[0].projects, ["feature-a-1"])
        self.assertEqual(runtime.dispatched_routes[1].projects, ["feature-a-1"])

    def test_pr_multi_target_dedupes_shared_git_root_before_commit_and_pr(self) -> None:
        runtime = _RuntimeStub()
        runtime.text_input_responses = ["PR body", "Ship shared root"]
        runtime.next_pr_flow_result = PrFlowResult(project_names=["feature-a-1", "feature-b-1"], base_branch="main")
        orchestrator = DashboardOrchestrator(runtime)
        orchestrator._run_pr_selection_flow = lambda **kwargs: (
            runtime.pr_flow_calls.append(kwargs) or runtime.next_pr_flow_result
        )  # type: ignore[method-assign]
        state = RunState(
            run_id="run-pr-dirty-shared-root",
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
                "feature-b-1 Backend": ServiceRecord(
                    name="feature-b-1 Backend",
                    type="backend",
                    cwd=".",
                    pid=101,
                    requested_port=8001,
                    actual_port=8001,
                    status="running",
                ),
            },
            metadata={
                "project_roots": {
                    "feature-a-1": ".",
                    "feature-b-1": ".",
                }
            },
        )
        runtime._latest_state = state

        def fake_probe(project_root: Path, repo_root: Path, *, project_name: str = "") -> object:
            return SimpleNamespace(
                project_name=project_name,
                project_root=project_root,
                git_root=Path(runtime.config.base_dir),
                staged=True,
                unstaged=False,
                untracked=False,
                dirty=True,
            )

        with (
            patch("envctl_engine.ui.dashboard.orchestrator.probe_dirty_worktree", side_effect=fake_probe),
            patch("envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl", return_value=["__DIRTY_PR_COMMIT__"]),
        ):
            should_continue, next_state = orchestrator._run_interactive_command("p", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual([route.command for route in runtime.dispatched_routes], ["commit", "pr"])
        self.assertEqual(runtime.dispatched_routes[0].projects, ["feature-a-1"])
        self.assertEqual(runtime.dispatched_routes[1].projects, ["feature-a-1"])

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
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.projects, ["Feature A"])

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
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.projects, ["Main"])
        self.assertFalse(bool(runtime.last_dispatched_route.flags.get("all")))

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
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.projects, ["Main"])

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

    def test_interactive_test_service_selection_hides_failed_rerun_when_latest_status_passed(
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
        self.assertEqual(runtime.selection_calls[0]["projects"], ["Backend", "Frontend"])
        self.assertEqual(runtime.selection_calls[0]["multi"], True)
        self.assertIsNone(runtime.selection_calls[0]["exclusive_project_name"])

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

    def test_interactive_test_failure_does_not_replay_duplicate_summary_after_test_suite_block(self) -> None:
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
                            "summary_excerpt": [
                                "[Repository tests (unittest)]",
                                "tests/python/ui/test_selector.py::test_keyboard_burst",
                                "AssertionError: Regex didn't match: 'RESULT_CANCELLED=False'",
                            ],
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
        rendered = strip_ansi(out.getvalue())
        self.assertNotIn("Test failure summary for Main:", rendered)
        self.assertNotIn("/tmp/runtime/run_1/ft_deadbeef00.txt", rendered)
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

    def test_interactive_test_interrupt_returns_to_dashboard_without_failure_summary_block(self) -> None:
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

        def interrupted_dispatch(route: Route) -> int:
            runtime.last_dispatched_route = route
            raise KeyboardInterrupt

        runtime.dispatch = interrupted_dispatch  # type: ignore[assignment]

        out = StringIO()
        with redirect_stdout(out):
            should_continue, next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, "run-1")
        rendered = out.getvalue()
        self.assertNotIn("Command failed (exit 1).", rendered)
        self.assertNotIn("Test failure summary for Main:", rendered)
        self.assertEqual(runtime.read_prompts, ["Press Enter to return to dashboard: "])

    def test_interactive_migrate_failure_prints_summary_and_failure_log_path(self) -> None:
        runtime = _RuntimeStub()
        runtime.dispatch_code = 1
        runtime.env["ENVCTL_UI_HYPERLINK_MODE"] = "on"
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
                                "summary": (
                                    "alembic.util.exc.CommandError: migration failed\n"
                                    "hint: envctl migrate loads backend env from backend/.env by default.\n"
                                    "hint: BACKEND_ENV_FILE_OVERRIDE or MAIN_ENV_FILE_PATH can redirect the env file.\n"
                                ),
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
        self.assertEqual(
            rendered.count("hint: envctl migrate loads backend env from backend/.env by default."),
            1,
        )
        self.assertIn(
            "hint: BACKEND_ENV_FILE_OVERRIDE or MAIN_ENV_FILE_PATH can redirect the env file.",
            strip_ansi(rendered),
        )
        self.assertIn(
            "migrate failure log for Main:\n/tmp/runtime/Main_migrate.txt",
            strip_ansi(rendered),
        )
        self.assertIn("\x1b]8;;file://", rendered)
        self.assertNotIn("Command failed (exit 1).", rendered)

    def test_project_action_failure_details_print_migrate_results_in_route_order_with_deduped_hints(self) -> None:
        runtime = _RuntimeStub()
        runtime.env["ENVCTL_UI_HYPERLINK_MODE"] = "on"
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-migrate-results",
            mode="trees",
            metadata={
                "project_action_reports": {
                    "feature-a-1": {
                        "migrate": {
                            "status": "success",
                        }
                    },
                    "feature-b-1": {
                        "migrate": {
                            "status": "failed",
                            "headline": "alembic.util.exc.CommandError: migration failed",
                            "summary": (
                                "Traceback (most recent call last):\n"
                                "alembic.util.exc.CommandError: migration failed\n"
                                "hint: envctl migrate loads backend env from backend/.env by default.\n"
                                "hint: envctl migrate loads backend env from backend/.env by default.\n"
                                "hint: BACKEND_ENV_FILE_OVERRIDE or MAIN_ENV_FILE_PATH can redirect the env file.\n"
                            ),
                            "report_path": "/tmp/runtime/feature-b-1_migrate.txt",
                        }
                    },
                }
            },
        )

        out = _TtyStringIO()
        with redirect_stdout(out):
            printed = orchestrator._print_project_action_failure_details(
                Route(
                    command="migrate",
                    mode="trees",
                    raw_args=["migrate"],
                    passthrough_args=[],
                    projects=["feature-a-1", "feature-b-1"],
                    flags={},
                ),
                state,
            )

        self.assertTrue(printed)
        rendered = strip_ansi(out.getvalue())
        self.assertLess(
            rendered.index("✓ migrate succeeded for feature-a-1"),
            rendered.index("✗ migrate failed for feature-b-1: alembic.util.exc.CommandError: migration failed"),
        )
        self.assertEqual(
            rendered.count("hint: envctl migrate loads backend env from backend/.env by default."),
            1,
        )
        self.assertIn(
            "hint: BACKEND_ENV_FILE_OVERRIDE or MAIN_ENV_FILE_PATH can redirect the env file.",
            rendered,
        )
        self.assertIn(
            "migrate failure log for feature-b-1:\n/tmp/runtime/feature-b-1_migrate.txt",
            rendered,
        )

    def test_interactive_migrate_success_prints_result_summary_for_all_targets(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(project_names=["feature-a-1", "feature-b-1"])
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-migrate-success",
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
                "feature-b-1 Backend": ServiceRecord(
                    name="feature-b-1 Backend",
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

        def successful_dispatch(route: Route) -> int:
            runtime.last_dispatched_route = route
            runtime._latest_state = RunState(
                run_id="run-migrate-success",
                mode="trees",
                services=state.services,
                metadata={
                    "project_action_reports": {
                        "feature-a-1": {"migrate": {"status": "success"}},
                        "feature-b-1": {"migrate": {"status": "success"}},
                    }
                },
            )
            return 0

        runtime.dispatch = successful_dispatch  # type: ignore[assignment]

        out = StringIO()
        with redirect_stdout(out):
            should_continue, next_state = orchestrator._run_interactive_command("m", state, runtime)

        rendered = out.getvalue()
        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, "run-migrate-success")
        self.assertIn("✓ migrate succeeded for feature-a-1", rendered)
        self.assertIn("✓ migrate succeeded for feature-b-1", rendered)

    def test_successful_single_worktree_review_selects_origin_tab_before_dispatch_and_launches_after_success(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        order: list[str] = []
        state = RunState(
            run_id="run-review",
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
                )
            },
            metadata={
                "project_roots": {"feature-a-1": "trees/feature-a/1"},
                "project_action_reports": {
                    "feature-a-1": {
                        "review": {
                            "status": "success",
                            "bundle_path": "/tmp/review-output/all.md",
                        }
                    }
                },
            },
        )
        runtime._latest_state = state

        def dispatch(route: Route) -> int:
            order.append("dispatch")
            runtime.last_dispatched_route = route
            runtime.dispatched_routes.append(route)
            return 0

        runtime.dispatch = dispatch  # type: ignore[assignment]

        with (
            patch(
                "envctl_engine.ui.dashboard.orchestrator.review_agent_launch_readiness",
                return_value=SimpleNamespace(ready=True, reason="ready", cli="codex"),
            ),
            patch(
                "envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl",
                side_effect=lambda **_kwargs: (order.append("selector") or ["__REVIEW_TAB_OPEN__"]),
            ) as selector_mock,
            patch(
                "envctl_engine.ui.dashboard.orchestrator.launch_review_agent_terminal",
                side_effect=lambda *args, **kwargs: (
                    order.append("launch") or SimpleNamespace(status="launched", reason="launched")
                ),
            ) as launch_mock,
        ):
            should_continue, next_state = orchestrator._run_interactive_command("a", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual(order, ["selector", "dispatch", "launch"])
        self.assertEqual(runtime.confirm_prompts, [])
        selector_kwargs = selector_mock.call_args.kwargs
        self.assertEqual(selector_kwargs["prompt"], "Open an origin-side AI review tab for feature-a-1?")
        self.assertEqual([item.label for item in selector_kwargs["options"]], ["Yes", "No"])
        self.assertEqual(selector_kwargs["multi"], False)
        launch_mock.assert_called_once_with(
            runtime,
            repo_root=runtime.config.base_dir,
            project_name="feature-a-1",
            project_root=(runtime.config.base_dir / "trees" / "feature-a" / "1").resolve(),
            review_bundle_path=Path("/tmp/review-output/all.md"),
        )

    def test_successful_single_worktree_review_decline_keeps_existing_behavior(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-review-decline",
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
                )
            },
            metadata={"project_roots": {"feature-a-1": "trees/feature-a/1"}},
        )
        runtime._latest_state = state

        with (
            patch(
                "envctl_engine.ui.dashboard.orchestrator.review_agent_launch_readiness",
                return_value=SimpleNamespace(ready=True, reason="ready", cli="codex"),
            ),
            patch("envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl", return_value=["__REVIEW_TAB_SKIP__"]),
            patch("envctl_engine.ui.dashboard.orchestrator.launch_review_agent_terminal") as launch_mock,
        ):
            should_continue, next_state = orchestrator._run_interactive_command("a", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual(runtime.confirm_prompts, [])
        launch_mock.assert_not_called()

    def test_failed_review_does_not_launch_origin_tab_after_preselected_opt_in(self) -> None:
        runtime = _RuntimeStub()
        runtime.dispatch_code = 1
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-review-fail",
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
                )
            },
            metadata={"project_roots": {"feature-a-1": "trees/feature-a/1"}},
        )
        runtime._latest_state = state

        with (
            patch(
                "envctl_engine.ui.dashboard.orchestrator.review_agent_launch_readiness",
                return_value=SimpleNamespace(ready=True, reason="ready", cli="codex"),
            ) as readiness_mock,
            patch("envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl", return_value=["__REVIEW_TAB_OPEN__"]) as selector_mock,
            patch("envctl_engine.ui.dashboard.orchestrator.launch_review_agent_terminal") as launch_mock,
        ):
            should_continue, next_state = orchestrator._run_interactive_command("a", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual(runtime.confirm_prompts, [])
        readiness_mock.assert_called_once()
        selector_mock.assert_called_once()
        launch_mock.assert_not_called()

    def test_review_tab_selector_cancel_behaves_like_decline_and_still_runs_review(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-review-cancel-menu",
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
                )
            },
            metadata={"project_roots": {"feature-a-1": "trees/feature-a/1"}},
        )
        runtime._latest_state = state

        with (
            patch(
                "envctl_engine.ui.dashboard.orchestrator.review_agent_launch_readiness",
                return_value=SimpleNamespace(ready=True, reason="ready", cli="codex"),
            ),
            patch("envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl", return_value=None) as selector_mock,
            patch("envctl_engine.ui.dashboard.orchestrator.launch_review_agent_terminal") as launch_mock,
        ):
            should_continue, next_state = orchestrator._run_interactive_command("a", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        selector_mock.assert_called_once()
        self.assertEqual([route.command for route in runtime.dispatched_routes], ["review"])
        launch_mock.assert_not_called()

    def test_main_review_does_not_prompt_for_origin_tab(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-review-main",
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
            metadata={"project_roots": {"Main": "."}},
        )
        runtime._latest_state = state

        with (
            patch("envctl_engine.ui.dashboard.orchestrator.review_agent_launch_readiness") as readiness_mock,
            patch("envctl_engine.ui.dashboard.orchestrator.launch_review_agent_terminal") as launch_mock,
        ):
            should_continue, next_state = orchestrator._run_interactive_command("a", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual(runtime.confirm_prompts, [])
        readiness_mock.assert_not_called()
        launch_mock.assert_not_called()

    def test_multi_target_review_does_not_prompt_for_origin_tab(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(project_names=["feature-a-1", "feature-b-1"])
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-review-multi",
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
                "feature-b-1 Backend": ServiceRecord(
                    name="feature-b-1 Backend",
                    type="backend",
                    cwd=".",
                    pid=101,
                    requested_port=8001,
                    actual_port=8001,
                    status="running",
                ),
            },
            metadata={
                "project_roots": {
                    "feature-a-1": "trees/feature-a/1",
                    "feature-b-1": "trees/feature-b/1",
                }
            },
        )
        runtime._latest_state = state

        with (
            patch("envctl_engine.ui.dashboard.orchestrator.review_agent_launch_readiness") as readiness_mock,
            patch("envctl_engine.ui.dashboard.orchestrator.launch_review_agent_terminal") as launch_mock,
        ):
            should_continue, next_state = orchestrator._run_interactive_command("a", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual(runtime.confirm_prompts, [])
        readiness_mock.assert_not_called()
        launch_mock.assert_not_called()

    def test_typed_review_with_explicit_project_still_uses_selector_when_eligible(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-review-explicit",
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
                )
            },
            metadata={"project_roots": {"feature-a-1": "trees/feature-a/1"}},
        )
        runtime._latest_state = state

        with (
            patch(
                "envctl_engine.ui.dashboard.orchestrator.review_agent_launch_readiness",
                return_value=SimpleNamespace(ready=True, reason="ready", cli="codex"),
            ),
            patch("envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl", return_value=["__REVIEW_TAB_SKIP__"]) as selector_mock,
            patch("envctl_engine.ui.dashboard.orchestrator.launch_review_agent_terminal") as launch_mock,
        ):
            should_continue, next_state = orchestrator._run_interactive_command(
                "review --project feature-a-1",
                state,
                runtime,
            )

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual(runtime.confirm_prompts, [])
        selector_mock.assert_called_once()
        launch_mock.assert_not_called()

    def test_review_tab_unavailable_skips_selector_and_prints_message_before_dispatch(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-review-no-cmux",
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
                )
            },
            metadata={"project_roots": {"feature-a-1": "trees/feature-a/1"}},
        )
        runtime._latest_state = state

        out = StringIO()
        with (
            patch(
                "envctl_engine.ui.dashboard.orchestrator.review_agent_launch_readiness",
                return_value=SimpleNamespace(
                    ready=False,
                    reason="missing_cmux_context",
                    cli="codex",
                    missing=(),
                ),
            ) as readiness_mock,
            patch("envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl") as selector_mock,
            patch("envctl_engine.ui.dashboard.orchestrator.launch_review_agent_terminal") as launch_mock,
            redirect_stdout(out),
        ):
            should_continue, next_state = orchestrator._run_interactive_command("a", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        readiness_mock.assert_called_once()
        selector_mock.assert_not_called()
        self.assertEqual([route.command for route in runtime.dispatched_routes], ["review"])
        launch_mock.assert_not_called()
        self.assertIn("Origin review tab unavailable: current cmux workspace context is unavailable.", out.getvalue())

    def test_duplicate_review_targets_collapsing_to_one_git_root_prompt_once(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(project_names=["feature-a-1", "feature-b-1"])
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-review-duplicate-root",
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
                "feature-b-1 Backend": ServiceRecord(
                    name="feature-b-1 Backend",
                    type="backend",
                    cwd=".",
                    pid=101,
                    requested_port=8001,
                    actual_port=8001,
                    status="running",
                ),
            },
            metadata={
                "project_roots": {
                    "feature-a-1": "trees/shared/1",
                    "feature-b-1": "trees/shared/1",
                },
                "project_action_reports": {
                    "feature-a-1": {
                        "review": {
                            "status": "success",
                            "bundle_path": "/tmp/review-output/all.md",
                        }
                    }
                },
            },
        )
        runtime._latest_state = state

        with (
            patch(
                "envctl_engine.ui.dashboard.orchestrator.review_agent_launch_readiness",
                return_value=SimpleNamespace(ready=True, reason="ready", cli="codex"),
            ) as readiness_mock,
            patch("envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl", return_value=["__REVIEW_TAB_OPEN__"]) as selector_mock,
            patch(
                "envctl_engine.ui.dashboard.orchestrator.launch_review_agent_terminal",
                return_value=SimpleNamespace(status="launched", reason="launched"),
            ) as launch_mock,
        ):
            should_continue, next_state = orchestrator._run_interactive_command("a", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual(runtime.confirm_prompts, [])
        readiness_mock.assert_called_once()
        selector_mock.assert_called_once()
        launch_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
