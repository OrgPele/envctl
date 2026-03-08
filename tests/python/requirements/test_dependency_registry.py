from __future__ import annotations

import unittest
from types import SimpleNamespace

from envctl_engine.requirements.core import DependencyDefinition, DependencyResourceSpec, dependency_definitions
from envctl_engine.state.action_orchestrator import StateActionOrchestrator
from envctl_engine.state.models import RequirementsResult, RunState
import envctl_engine.state.action_orchestrator as action_module


class DependencyRegistryTests(unittest.TestCase):
    def test_registry_ids_are_unique_and_ordered(self) -> None:
        definitions = dependency_definitions()
        ids = [definition.id for definition in definitions]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, ["postgres", "redis", "supabase", "n8n"])
        self.assertEqual([definition.order for definition in definitions], sorted(definition.order for definition in definitions))

    def test_requirements_result_keeps_legacy_aliases_and_components(self) -> None:
        result = RequirementsResult(
            project="Main",
            db={"enabled": True, "success": True, "final": 5432},
            redis={"enabled": True, "success": True, "final": 6379},
            n8n={"enabled": False, "success": False},
        )
        self.assertTrue(result.component("postgres")["enabled"])
        self.assertEqual(result.db["final"], 5432)
        self.assertEqual(result.redis["final"], 6379)
        self.assertIn("postgres", result.components)
        self.assertIn("redis", result.components)

    def test_fake_registered_dependency_surfaces_in_health_rows(self) -> None:
        fake = DependencyDefinition(
            id="kafka",
            display_name="Kafka",
            order=25,
            resources=(DependencyResourceSpec(name="primary", legacy_port_key="redis", config_port_keys=("KAFKA_PORT",)),),
            mode_enable_keys={"main": ("MAIN_KAFKA_ENABLE",), "trees": ("TREES_KAFKA_ENABLE",)},
            default_enabled={"main": False, "trees": False},
        )
        orchestrator = StateActionOrchestrator(SimpleNamespace())
        state = RunState(
            run_id="run-1",
            mode="main",
            requirements={
                "Main": RequirementsResult(
                    project="Main",
                    components={
                        "kafka": {"enabled": True, "success": True, "final": 9092, "runtime_status": "healthy"},
                    },
                )
            },
        )
        original = action_module.dependency_definitions
        try:
            action_module.dependency_definitions = lambda: (*dependency_definitions(), fake)
            rows = orchestrator._requirement_health_rows(state)
        finally:
            action_module.dependency_definitions = original
        kafka_rows = [row for row in rows if row["component"] == "kafka"]
        self.assertEqual(len(kafka_rows), 1)
        self.assertEqual(kafka_rows[0]["port"], 9092)
        self.assertEqual(kafka_rows[0]["status"], "healthy")


if __name__ == "__main__":
    unittest.main()
