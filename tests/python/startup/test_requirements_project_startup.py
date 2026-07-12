from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from envctl_engine.requirements.orchestrator import FailureClass, RequirementOutcome
from envctl_engine.shared.ports import PortPlanner
from envctl_engine.startup.requirements_component_startup import RequirementComponentStarter
from envctl_engine.startup.requirements_project_startup import RequirementProjectStarter
from envctl_engine.state.models import PortPlan


class RequirementProjectStarterTests(unittest.TestCase):
    @staticmethod
    def _plan(port: int) -> PortPlan:
        return PortPlan(
            project="Main",
            requested=port,
            assigned=port,
            final=port,
            source="test",
        )

    def _starter(self, *, parallel: bool) -> RequirementProjectStarter:
        postgres = SimpleNamespace(
            id="postgres",
            resources=(SimpleNamespace(name="db", legacy_port_key="db"),),
        )
        redis = SimpleNamespace(
            id="redis",
            resources=(SimpleNamespace(name="redis", legacy_port_key="redis"),),
        )

        def start_component(_context, component, plan, _reserve_next, **_kwargs):  # noqa: ANN001, ANN202
            if component == "redis":
                raise RuntimeError("redis native startup crashed")
            return RequirementOutcome(
                service_name=component,
                success=True,
                requested_port=plan.requested,
                final_port=plan.final,
                retries=0,
                container_name="postgres-main",
            )

        runtime = SimpleNamespace(
            env={"ENVCTL_REQUIREMENTS_PARALLEL": "true" if parallel else "false"},
            config=SimpleNamespace(raw={}, strict_n8n_bootstrap=False),
            port_planner=SimpleNamespace(session_id="requirements-session"),
            _emit=lambda *_args, **_kwargs: None,
            _start_requirement_component=start_component,
        )
        return RequirementProjectStarter(
            orchestrator=SimpleNamespace(runtime=runtime),
            context=SimpleNamespace(
                name="Main",
                ports={"db": self._plan(5432), "redis": self._plan(6379)},
            ),
            mode="main",
            definitions=[postgres, redis],
        )

    def test_sequential_component_exception_becomes_partial_failed_outcome(self) -> None:
        starter = self._starter(parallel=False)

        starter._run_enabled_components(starter.definitions)

        self.assertTrue(starter.outcomes["postgres"].success)
        self.assertFalse(starter.outcomes["redis"].success)
        self.assertEqual(starter.outcomes["redis"].final_port, 6379)
        self.assertIn("native startup crashed", str(starter.outcomes["redis"].error))

    def test_parallel_component_exception_waits_for_and_preserves_other_outcomes(self) -> None:
        starter = self._starter(parallel=True)

        with patch(
            "envctl_engine.startup.requirements_project_startup.requirements_parallel_enabled",
            return_value=True,
        ):
            starter._run_enabled_components(starter.definitions)

        self.assertEqual(set(starter.outcomes), {"postgres", "redis"})
        self.assertTrue(starter.outcomes["postgres"].success)
        self.assertFalse(starter.outcomes["redis"].success)

    def test_managed_components_record_exact_port_planner_session(self) -> None:
        starter = self._starter(parallel=False)
        starter._run_enabled_components(starter.definitions)

        components = starter._build_components(
            {"postgres": True, "redis": True},
            {"postgres": False, "redis": False},
        )

        self.assertEqual(
            components["postgres"]["port_lock_session"],
            "requirements-session",
        )
        self.assertEqual(
            components["redis"]["port_lock_session"],
            "requirements-session",
        )

    def test_multiple_requirement_rebinds_release_every_failed_port_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            planner = PortPlanner(
                lock_dir=tmpdir,
                session_id="startup-session",
                availability_checker=lambda _port: True,
            )
            planner.reserve_next(5432, owner="Main:db")
            starter = object.__new__(RequirementComponentStarter)
            starter.runtime = SimpleNamespace(
                port_planner=planner,
                requirements=SimpleNamespace(reason_code_for_failure=lambda *_args, **_kwargs: "port_in_use"),
                _emit=lambda *_args, **_kwargs: None,
            )
            starter.context = SimpleNamespace(name="Main")
            starter.name = "postgres"

            retry_one = planner.reserve_next(5433, owner="Main:requirements")
            starter._on_retry(
                "postgres",
                5432,
                retry_one,
                1,
                FailureClass.BIND_CONFLICT_RETRYABLE,
                "address already in use",
            )
            retry_two = planner.reserve_next(5434, owner="Main:requirements")
            starter._on_retry(
                "postgres",
                retry_one,
                retry_two,
                2,
                FailureClass.BIND_CONFLICT_RETRYABLE,
                "address already in use",
            )

            locks = list(Path(tmpdir).glob("*.lock"))
            self.assertEqual([path.name for path in locks], ["5434.lock"])
            payload = json.loads(locks[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["owner"], "Main:requirements")


if __name__ == "__main__":
    unittest.main()
