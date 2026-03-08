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
        planner = PortPlanner(backend_base=8000, frontend_base=9000, spacing=20, scope_key="repo-a")

        first = planner.plan_project("tree-alpha", index=1)
        second = planner.plan_project("tree-alpha", index=1)

        self.assertEqual(first["backend"].final - 8000, first["frontend"].final - 9000)
        self.assertEqual(first["backend"], second["backend"])
        self.assertEqual(first["frontend"], second["frontend"])

    def test_project_slot_strategy_is_independent_of_discovery_index(self) -> None:
        planner = PortPlanner(backend_base=8000, frontend_base=9000, spacing=20, scope_key="repo-a")

        first = planner.plan_project("tree-alpha", index=0)
        second = planner.plan_project("tree-alpha", index=17)

        self.assertEqual(first["backend"].final, second["backend"].final)
        self.assertEqual(first["frontend"].final, second["frontend"].final)

    def test_main_project_keeps_base_ports(self) -> None:
        planner = PortPlanner(backend_base=8000, frontend_base=9000, spacing=20, scope_key="repo-a")

        plans = planner.plan_project_stack("Main", index=9)

        self.assertEqual(plans["backend"].final, 8000)
        self.assertEqual(plans["frontend"].final, 9000)
        self.assertEqual(plans["db"].final, 5432)
        self.assertEqual(plans["redis"].final, 6379)
        self.assertEqual(plans["n8n"].final, 5678)

    def test_main_project_identity_is_normalized(self) -> None:
        planner = PortPlanner(backend_base=8000, frontend_base=9000, spacing=20, scope_key="repo-a")

        first = planner.plan_project_stack(" Main ", index=0)
        second = planner.plan_project_stack("main", index=4)

        self.assertEqual(first["backend"].final, 8000)
        self.assertEqual(second["frontend"].final, 9000)
        self.assertEqual(first["db"].final, 5432)
        self.assertEqual(second["redis"].final, 6379)

    def test_project_identity_normalization_keeps_equivalent_names_stable(self) -> None:
        planner = PortPlanner(backend_base=8000, frontend_base=9000, spacing=20, scope_key="repo-a")

        first = planner.plan_project_stack("Feature A/1", index=0)
        second = planner.plan_project_stack("feature-a-1", index=9)

        self.assertEqual(first["backend"].final, second["backend"].final)
        self.assertEqual(first["frontend"].final, second["frontend"].final)
        self.assertEqual(first["db"].final, second["db"].final)

    def test_project_slot_is_scoped_by_repo_identity(self) -> None:
        planner_a = PortPlanner(backend_base=8000, frontend_base=9000, spacing=20, scope_key="repo-a")
        planner_b = PortPlanner(backend_base=8000, frontend_base=9000, spacing=20, scope_key="repo-b")

        slot_a = planner_a._project_slot("tree-alpha")
        slot_b = planner_b._project_slot("tree-alpha")

        self.assertNotEqual(slot_a, slot_b)

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

    def test_project_slot_span_uses_smallest_gap_between_service_bases(self) -> None:
        planner = PortPlanner(
            backend_base=8000,
            frontend_base=9000,
            db_base=8050,
            redis_base=8150,
            n8n_base=8250,
            spacing=20,
        )

        self.assertEqual(planner._project_slot_span(), 50)

    def test_requirement_plan_assigns_unique_ports_per_tree(self) -> None:
        planner = PortPlanner(backend_base=8000, frontend_base=9000, spacing=20, scope_key="repo-a")
        alpha = planner.plan_project_stack("tree-alpha", index=0)
        beta = planner.plan_project_stack("tree-beta", index=1)

        self.assertNotEqual(alpha["backend"].final, beta["backend"].final)
        self.assertNotEqual(alpha["frontend"].final, beta["frontend"].final)
        self.assertNotEqual(alpha["db"].final, beta["db"].final)
        self.assertNotEqual(alpha["redis"].final, beta["redis"].final)
        self.assertNotEqual(alpha["n8n"].final, beta["n8n"].final)
        self.assertEqual(alpha["backend"].final - 8000, alpha["db"].final - 5432)
        self.assertEqual(alpha["backend"].final - 8000, alpha["redis"].final - 6379)
        self.assertEqual(alpha["backend"].final - 8000, alpha["n8n"].final - 5678)
        self.assertEqual(beta["backend"].final - 8000, beta["db"].final - 5432)

    def test_attach_existing_port_marks_existing_container_source(self) -> None:
        planner = PortPlanner()
        plans = planner.plan_project_stack("tree-alpha", index=0)
        attached = planner.attach_existing_port(plans["redis"], existing_port=6384)

        self.assertEqual(attached.final, 6384)
        self.assertEqual(attached.source, "existing_container")

    def test_legacy_spacing_strategy_remains_available(self) -> None:
        planner = PortPlanner(
            backend_base=8000,
            frontend_base=9000,
            spacing=20,
            preferred_port_strategy="legacy_spacing",
            scope_key="repo-a",
        )

        plans = planner.plan_project_stack("tree-beta", index=2)

        self.assertEqual(plans["backend"].final, 8040)
        self.assertEqual(plans["frontend"].final, 9040)
        self.assertEqual(plans["db"].final, 5434)
        self.assertEqual(plans["redis"].final, 6381)
        self.assertEqual(plans["n8n"].final, 5680)

    def test_invalid_strategy_falls_back_to_project_slot(self) -> None:
        planner = PortPlanner(
            backend_base=8000,
            frontend_base=9000,
            spacing=20,
            preferred_port_strategy="unexpected",
            scope_key="repo-a",
        )

        project_slot = planner.plan_project_stack("tree-alpha", index=0)
        redis_slot = project_slot["redis"].final - 6379
        backend_slot = project_slot["backend"].final - 8000

        self.assertEqual(planner.preferred_port_strategy, "project_slot")
        self.assertEqual(redis_slot, backend_slot)


if __name__ == "__main__":
    unittest.main()
