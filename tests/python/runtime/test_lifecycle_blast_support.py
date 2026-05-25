from __future__ import annotations

import unittest

from envctl_engine.runtime.lifecycle_blast_support import LifecycleBlastCleanupSupport
from envctl_engine.runtime.lifecycle_blast_docker import BlastDockerCleanupSupport, matches_blast_container
from envctl_engine.runtime.lifecycle_blast_ports import BlastPortSweepSupport
from envctl_engine.runtime.lifecycle_blast_processes import (
    BLAST_ALL_PROCESS_PATTERNS,
    BlastProcessCleanupSupport,
    is_orchestrator_process,
    looks_like_docker_process,
    process_tree_kill_order_from_ps,
)


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
        self.assertTrue(matches_blast_container(image="postgres:16", name="db"))
        self.assertFalse(matches_blast_container(image="node:22", name="frontend"))

    def test_process_tree_kill_order_returns_children_before_parent(self) -> None:
        harness = _BlastHarness(
            "100 1\n"
            "101 100\n"
            "102 100\n"
            "201 101\n"
        )

        self.assertEqual(harness.blast_all_process_tree_kill_order(100), [201, 102, 101, 100])
        self.assertEqual(harness.calls, [("ps", "-axo", "pid=,ppid=")])
        self.assertEqual(process_tree_kill_order_from_ps(harness.ps_tree_stdout, root_pid=100), [201, 102, 101, 100])

    def test_process_tree_kill_order_falls_back_to_root_when_ps_fails(self) -> None:
        harness = _BlastHarness("")

        self.assertEqual(harness.blast_all_process_tree_kill_order(100), [100])

    def test_blast_process_predicates_live_in_process_owner(self) -> None:
        self.assertIn("vite", BLAST_ALL_PROCESS_PATTERNS)
        self.assertTrue(is_orchestrator_process("/usr/bin/envctl --plan feature"))
        self.assertFalse(is_orchestrator_process("python app.py"))
        self.assertTrue(looks_like_docker_process("Docker Desktop networking"))
        self.assertFalse(looks_like_docker_process("python app.py"))

    def test_lifecycle_blast_support_is_composed_from_focused_owners(self) -> None:
        self.assertTrue(issubclass(LifecycleBlastCleanupSupport, BlastPortSweepSupport))
        self.assertTrue(issubclass(LifecycleBlastCleanupSupport, BlastProcessCleanupSupport))
        self.assertTrue(issubclass(LifecycleBlastCleanupSupport, BlastDockerCleanupSupport))


if __name__ == "__main__":
    unittest.main()
