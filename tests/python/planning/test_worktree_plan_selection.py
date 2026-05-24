from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
import unittest

from envctl_engine.planning.worktree_plan_selection import (
    adjust_plan_counts_for_fresh_ai_launch,
    fresh_ai_launch_transport,
    planning_keep_plan_enabled,
    route_requests_fresh_ai_worktree,
)
from envctl_engine.runtime.command_router import Route


class WorktreePlanSelectionTests(unittest.TestCase):
    def test_route_requests_fresh_ai_worktree_requires_new_session_transport_and_not_dry_run(self) -> None:
        self.assertTrue(
            route_requests_fresh_ai_worktree(
                Route(
                    command="plan",
                    mode="trees",
                    raw_args=[],
                    passthrough_args=[],
                    projects=[],
                    flags={"new_session": True, "tmux": True},
                )
            )
        )
        self.assertFalse(
            route_requests_fresh_ai_worktree(
                Route(
                    command="plan",
                    mode="trees",
                    raw_args=[],
                    passthrough_args=[],
                    projects=[],
                    flags={"tmux": True},
                )
            )
        )
        self.assertFalse(
            route_requests_fresh_ai_worktree(
                Route(
                    command="plan",
                    mode="trees",
                    raw_args=[],
                    passthrough_args=[],
                    projects=[],
                    flags={"new_session": True, "tmux": True, "dry_run": True},
                )
            )
        )
        self.assertFalse(
            route_requests_fresh_ai_worktree(
                Route(
                    command="plan",
                    mode="trees",
                    raw_args=[],
                    passthrough_args=[],
                    projects=[],
                    flags={"new_session": True},
                )
            )
        )

    def test_fresh_ai_launch_transport_prefers_omx_tmux_then_cmux(self) -> None:
        base = {
            "new_session": True,
            "cmux": True,
            "tmux": True,
            "omx": True,
        }

        self.assertEqual(fresh_ai_launch_transport(self._route(flags=base)), "omx")
        self.assertEqual(fresh_ai_launch_transport(self._route(flags={"cmux": True, "tmux": True})), "tmux")
        self.assertEqual(fresh_ai_launch_transport(self._route(flags={"cmux": True})), "cmux")
        self.assertEqual(fresh_ai_launch_transport(self._route(flags={})), "")

    def test_adjust_plan_counts_for_fresh_ai_launch_adds_existing_counts(self) -> None:
        projects = [
            ("backend_task-1", Path("/tmp/backend_task/1")),
            ("backend_task-2", Path("/tmp/backend_task/2")),
            ("frontend_task-1", Path("/tmp/frontend_task/1")),
        ]
        plan_counts = OrderedDict([("backend/task.md", 1), ("frontend/task.md", 2)])

        adjusted = adjust_plan_counts_for_fresh_ai_launch(
            raw_projects=projects,
            plan_counts=plan_counts,
            route=self._route(flags={"new_session": True, "cmux": True}),
        )

        self.assertEqual(adjusted, OrderedDict([("backend/task.md", 3), ("frontend/task.md", 3)]))
        self.assertIsNot(adjusted, plan_counts)

    def test_adjust_plan_counts_for_fresh_ai_launch_keeps_counts_when_route_is_not_fresh(self) -> None:
        plan_counts = OrderedDict([("backend/task.md", 1)])

        adjusted = adjust_plan_counts_for_fresh_ai_launch(
            raw_projects=[("backend_task-1", Path("/tmp/backend_task/1"))],
            plan_counts=plan_counts,
            route=self._route(flags={"cmux": True}),
        )

        self.assertIs(adjusted, plan_counts)

    def test_planning_keep_plan_enabled_prefers_route_flag_then_env_then_config(self) -> None:
        self.assertTrue(planning_keep_plan_enabled(route=self._route(flags={"keep_plan": True}), env={}, config_raw={}))
        self.assertTrue(
            planning_keep_plan_enabled(
                route=self._route(flags={}),
                env={"PLANNING_KEEP_PLAN": "yes"},
                config_raw={"PLANNING_KEEP_PLAN": "false"},
            )
        )
        self.assertTrue(
            planning_keep_plan_enabled(
                route=self._route(flags={}),
                env={},
                config_raw={"PLANNING_KEEP_PLAN": "true"},
            )
        )
        self.assertFalse(planning_keep_plan_enabled(route=self._route(flags={}), env={}, config_raw={}))

    def _route(self, *, flags: dict[str, object]) -> Route:
        return Route(
            command="plan",
            mode="trees",
            raw_args=[],
            passthrough_args=[],
            projects=[],
            flags=flags,
        )


if __name__ == "__main__":
    unittest.main()
