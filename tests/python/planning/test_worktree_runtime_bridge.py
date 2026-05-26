from __future__ import annotations

import unittest

from envctl_engine.planning.worktree_runtime_bridge import PlanningRuntimeBridge, create_planning_runtime_bridge
from envctl_engine.planning.worktree_selection_runtime_bridge import WorktreeSelectionRuntimeBridge
from envctl_engine.planning.worktree_sync_runtime_bridge import WorktreeSyncRuntimeBridge


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

    def test_planning_runtime_bridge_delegates_sync_wiring_to_sync_bridge(self) -> None:
        bridge = create_planning_runtime_bridge(object())

        sync_bridge = bridge.sync_bridge()

        self.assertIsInstance(sync_bridge, WorktreeSyncRuntimeBridge)
        self.assertIs(sync_bridge.runtime, bridge.runtime)
        self.assertIs(sync_bridge.discover_tree_projects, bridge.discover_tree_projects)
        self.assertIs(sync_bridge.delete_worktree_path, bridge.delete_worktree_path)
        self.assertIs(sync_bridge.process_runtime_factory, bridge.process_runtime_factory)
        self.assertIs(sync_bridge.render_planning_path.__self__, bridge)
        self.assertIs(sync_bridge.render_planning_path.__func__, bridge.render_planning_path.__func__)
        self.assertIs(sync_bridge.update_spinner.__self__, bridge)
        self.assertIs(sync_bridge.update_spinner.__func__, bridge.update_spinner.__func__)
        self.assertIs(sync_bridge.output, bridge.output)

    def test_planning_runtime_bridge_delegates_selection_wiring_to_selection_bridge(self) -> None:
        bridge = create_planning_runtime_bridge(object())

        selection_bridge = bridge.selection_bridge()

        self.assertIsInstance(selection_bridge, WorktreeSelectionRuntimeBridge)
        self.assertIs(selection_bridge.runtime, bridge.runtime)
        self.assertIs(selection_bridge.select_planning_counts, bridge.select_planning_counts)


if __name__ == "__main__":
    unittest.main()
