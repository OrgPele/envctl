from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.runtime.lifecycle_requirement_ports import (
    component_port_values,
    release_requirement_ports,
    requirement_key_for_project,
    requirement_port_values,
)
from envctl_engine.state.models import RequirementsResult, RunState
from envctl_engine.shared.ports import PortPlanner


class LifecycleRequirementPortsTests(unittest.TestCase):
    def test_requirement_key_for_project_matches_case_insensitive_key(self) -> None:
        state = RunState(run_id="run-1", mode="main", requirements={"Main": RequirementsResult(project="Main")})

        self.assertEqual(requirement_key_for_project(state, "main"), "Main")
        self.assertIsNone(requirement_key_for_project(state, " "))
        self.assertIsNone(requirement_key_for_project(state, "missing"))

    def test_requirement_port_values_returns_all_enabled_internal_resource_ports(self) -> None:
        requirements = RequirementsResult(
            project="Main",
            db={"enabled": True, "final": 5432},
            redis={"enabled": False, "final": 6379},
            supabase={
                "enabled": True,
                "external": True,
                "final": 54321,
                "resources": {"external_api": 55432},
            },
            n8n={"enabled": True, "final": 5678, "resources": {"secondary": 15678}},
        )

        self.assertEqual(requirement_port_values(requirements), {5432, 5678, 15678})

    def test_component_port_values_collects_final_and_resource_ports(self) -> None:
        self.assertEqual(
            component_port_values({"final": 5432, "resources": {"shadow": 15432, "duplicate": 5432, "zero": 0}}),
            {5432, 15432},
        )

    def test_release_requirement_ports_uses_runtime_port_planner_in_sorted_order(self) -> None:
        released: list[int] = []
        runtime = SimpleNamespace(port_planner=SimpleNamespace(release=lambda port: released.append(port)))
        requirements = RequirementsResult(
            project="Main",
            db={"enabled": True, "final": 5432},
            supabase={
                "enabled": True,
                "final": 15432,
                "resources": {"db": 15432, "api": 15433},
            },
            n8n={"enabled": True, "final": 5678},
        )

        release_requirement_ports(runtime, requirements)

        self.assertEqual(released, [5432, 5678, 15432, 15433])

    def test_release_requirement_ports_can_release_verified_prior_session_owners(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prior = PortPlanner(
                lock_dir=tmpdir,
                session_id="prior-session",
                availability_checker=lambda _port: True,
            )
            current = PortPlanner(
                lock_dir=tmpdir,
                session_id="current-session",
                availability_checker=lambda _port: True,
            )
            prior.reserve_next(5432, owner="Main:db")
            prior.reserve_next(5433, owner="Main:requirements")
            requirements = RequirementsResult(
                project="Main",
                db={
                    "enabled": True,
                    "final": 5432,
                    "resources": {"primary": 5432, "retry": 5433},
                    "port_lock_session": "prior-session",
                },
            )

            release_requirement_ports(SimpleNamespace(port_planner=current), requirements)

            self.assertEqual(list(Path(tmpdir).glob("*.lock")), [])

    def test_stale_requirement_state_cannot_release_newer_live_same_owner_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            newer = PortPlanner(
                lock_dir=tmpdir,
                session_id="newer-session",
                availability_checker=lambda _port: True,
            )
            cleanup = PortPlanner(
                lock_dir=tmpdir,
                session_id="cleanup-session",
                availability_checker=lambda _port: True,
            )
            newer.reserve_next(5432, owner="Main:db")
            stale_requirements = RequirementsResult(
                project="Main",
                db={
                    "enabled": True,
                    "final": 5432,
                    "port_lock_session": "stale-session",
                },
            )

            release_requirement_ports(
                SimpleNamespace(port_planner=cleanup),
                stale_requirements,
            )

            self.assertTrue((Path(tmpdir) / "5432.lock").exists())

    def test_legacy_requirement_state_preserves_live_foreign_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            live = PortPlanner(
                lock_dir=tmpdir,
                session_id="live-session",
                availability_checker=lambda _port: True,
            )
            cleanup = PortPlanner(
                lock_dir=tmpdir,
                session_id="cleanup-session",
                availability_checker=lambda _port: True,
            )
            live.reserve_next(5432, owner="Main:db")

            release_requirement_ports(
                SimpleNamespace(port_planner=cleanup),
                RequirementsResult(project="Main", db={"enabled": True, "final": 5432}),
            )

            self.assertTrue((Path(tmpdir) / "5432.lock").exists())

    def test_legacy_requirement_state_reaps_only_proven_dead_foreign_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "5432.lock"
            lock_path.write_text(
                '{"created_at": 0, "owner": "Main:db", "pid": 99999999, "session": "dead-session"}',
                encoding="utf-8",
            )
            cleanup = PortPlanner(
                lock_dir=tmpdir,
                session_id="cleanup-session",
                availability_checker=lambda _port: True,
            )

            release_requirement_ports(
                SimpleNamespace(port_planner=cleanup),
                RequirementsResult(project="Main", db={"enabled": True, "final": 5432}),
            )

            self.assertFalse(lock_path.exists())


if __name__ == "__main__":
    unittest.main()
