from __future__ import annotations

import unittest

from envctl_engine.planning.worktree_runtime_bridge import PlanningRuntimeBridge, create_planning_runtime_bridge


class WorktreeRuntimeBridgeTests(unittest.TestCase):
    def test_create_planning_runtime_bridge_owns_runtime_dependency_wiring(self) -> None:
        runtime = object()

        def output(*_args: object, **_kwargs: object) -> None:
            return None

        bridge = create_planning_runtime_bridge(runtime, output=output)

        self.assertIsInstance(bridge, PlanningRuntimeBridge)
        self.assertIs(bridge.runtime, runtime)
        self.assertIs(bridge.output, output)
        self.assertEqual(bridge.delete_worktree_path.__name__, "delete_worktree_path")
        self.assertEqual(bridge.discover_tree_projects.__name__, "discover_tree_projects")
        self.assertEqual(bridge.process_runtime_factory.__name__, "resolve_process_runtime")
        self.assertEqual(bridge.select_planning_counts.__name__, "select_planning_counts_textual")


if __name__ == "__main__":
    unittest.main()
