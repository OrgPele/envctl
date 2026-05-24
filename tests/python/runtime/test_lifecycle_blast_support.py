from __future__ import annotations

import unittest

from envctl_engine.runtime.lifecycle_blast_support import LifecycleBlastCleanupSupport


class _BlastHarness(LifecycleBlastCleanupSupport):
    def __init__(self, ps_tree_stdout: str) -> None:
        self.ps_tree_stdout = ps_tree_stdout
        self.calls: list[tuple[str, ...]] = []

    def run_best_effort_command(
        self,
        cmd: list[str],
        *,
        timeout: float | None = None,
    ) -> tuple[int, str, str]:
        _ = timeout
        self.calls.append(tuple(cmd))
        if cmd == ["ps", "-axo", "pid=,ppid="]:
            return 0, self.ps_tree_stdout, ""
        return 127, "", "unexpected"


class LifecycleBlastSupportTests(unittest.TestCase):
    def test_container_matcher_covers_dependency_names_and_images(self) -> None:
        self.assertTrue(LifecycleBlastCleanupSupport.blast_all_matches_container(image="postgres:16", name="db"))
        self.assertTrue(LifecycleBlastCleanupSupport.blast_all_matches_container(image="app", name="feature-redis"))
        self.assertTrue(LifecycleBlastCleanupSupport.blast_all_matches_container(image="supabase/postgres", name="api"))
        self.assertFalse(LifecycleBlastCleanupSupport.blast_all_matches_container(image="node:22", name="frontend"))

    def test_process_tree_kill_order_returns_children_before_parent(self) -> None:
        harness = _BlastHarness(
            "100 1\n"
            "101 100\n"
            "102 100\n"
            "201 101\n"
        )

        self.assertEqual(harness.blast_all_process_tree_kill_order(100), [201, 102, 101, 100])
        self.assertEqual(harness.calls, [("ps", "-axo", "pid=,ppid=")])

    def test_process_tree_kill_order_falls_back_to_root_when_ps_fails(self) -> None:
        harness = _BlastHarness("")

        self.assertEqual(harness.blast_all_process_tree_kill_order(100), [100])


if __name__ == "__main__":
    unittest.main()
