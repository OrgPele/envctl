from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.shared.ports import PortPlanner


class PortPlanTests(unittest.TestCase):
    def test_plan_is_deterministic_for_same_input(self) -> None:
        planner = PortPlanner(backend_base=8000, frontend_base=9000, spacing=20)

        first = planner.plan_project("tree-alpha", index=1)
        second = planner.plan_project("tree-alpha", index=1)

        self.assertEqual(first["backend"].final, 8020)
        self.assertEqual(first["frontend"].final, 9020)
        self.assertEqual(first["backend"], second["backend"])
        self.assertEqual(first["frontend"], second["frontend"])

    def test_reserve_next_assigns_unique_ports_across_workers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base_port = 54320
            planner_a = PortPlanner(lock_dir=tmpdir, availability_checker=lambda _port: True)
            planner_b = PortPlanner(lock_dir=tmpdir, availability_checker=lambda _port: True)

            a_port = planner_a.reserve_next(base_port, owner="worker-a")
            b_port = planner_b.reserve_next(base_port, owner="worker-b")

            self.assertEqual(a_port, base_port)
            self.assertEqual(b_port, base_port + 1)

    def test_update_final_port_records_retry_source(self) -> None:
        planner = PortPlanner()
        plans = planner.plan_project(
            "tree-beta",
            index=0,
            sources={"backend": "worktree_config"},
            retries={"backend": 1},
        )

        updated = planner.update_final_port(plans["backend"], final_port=8010, source="retry")

        self.assertEqual(updated.source, "retry")
        self.assertEqual(updated.final, 8010)
        self.assertEqual(updated.retries, 2)

    def test_requirement_plan_assigns_unique_ports_per_tree(self) -> None:
        planner = PortPlanner(backend_base=8000, frontend_base=9000, spacing=20)
        alpha = planner.plan_project_stack("tree-alpha", index=0)
        beta = planner.plan_project_stack("tree-beta", index=1)

        self.assertEqual(alpha["db"].final, 5432)
        self.assertEqual(beta["db"].final, 5433)
        self.assertEqual(alpha["redis"].final, 6379)
        self.assertEqual(beta["redis"].final, 6380)
        self.assertEqual(alpha["n8n"].final, 5678)
        self.assertEqual(beta["n8n"].final, 5679)

    def test_attach_existing_port_marks_existing_container_source(self) -> None:
        planner = PortPlanner()
        plans = planner.plan_project_stack("tree-alpha", index=0)
        attached = planner.attach_existing_port(plans["redis"], existing_port=6384)

        self.assertEqual(attached.final, 6384)
        self.assertEqual(attached.source, "existing_container")


if __name__ == "__main__":
    unittest.main()
