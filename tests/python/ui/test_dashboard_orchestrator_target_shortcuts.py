from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.ui.dashboard.orchestrator import DashboardOrchestrator

from tests.python.ui.dashboard_orchestrator_test_support import (
    _DashboardOrchestratorTestCase,
    _RuntimeStub,
)


class DashboardOrchestratorTargetShortcutTests(_DashboardOrchestratorTestCase):
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
