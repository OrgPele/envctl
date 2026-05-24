from __future__ import annotations

# ruff: noqa: F403,F405
from tests.python.runtime.engine_runtime_env_test_support import *


class EngineRuntimeEnvReadinessTests(EngineRuntimeEnvTestCase):
    def test_requirements_ready_honors_strict_mode(self) -> None:
        result = RequirementsResult(
            project="Main",
            db={"enabled": True, "success": False},
            redis={"enabled": True, "success": True},
            n8n={"enabled": False, "success": False},
            supabase={"enabled": False, "success": False},
            health="degraded",
            failures=["postgres"],
        )
        strict_runtime = SimpleNamespace(config=SimpleNamespace(requirements_strict=True))
        lenient_runtime = SimpleNamespace(config=SimpleNamespace(requirements_strict=False))

        self.assertFalse(requirements_ready(strict_runtime, result))
        self.assertTrue(requirements_ready(lenient_runtime, result))

    def test_requirements_ready_does_not_block_on_unreachable_external_dependency(self) -> None:
        result = RequirementsResult(
            project="Main",
            db={"enabled": False, "success": False},
            redis={
                "enabled": True,
                "success": False,
                "external": True,
                "runtime_status": "unreachable",
                "error": "redis external probe failed: cannot connect to localhost:6493",
            },
            n8n={"enabled": False, "success": False},
            supabase={"enabled": False, "success": False},
            health="degraded",
            failures=["redis"],
        )
        strict_runtime = SimpleNamespace(config=SimpleNamespace(requirements_strict=True))

        self.assertTrue(requirements_ready(strict_runtime, result))

    def test_service_and_requirement_enablement_follow_profiles(self) -> None:
        config = SimpleNamespace(
            startup_enabled_for_mode=lambda mode: mode != "main",
            service_enabled_for_mode=lambda mode, service: {
                ("main", "backend"): False,
                ("main", "frontend"): True,
                ("trees", "backend"): True,
                ("trees", "frontend"): False,
            }.get((mode, service), False),
            requirement_enabled_for_mode=lambda mode, name: {
                ("trees", "supabase"): True,
                ("trees", "postgres"): False,
                ("trees", "redis"): True,
                ("trees", "n8n"): True,
            }.get((mode, name), False),
            postgres_main_enable=True,
            redis_main_enable=True,
            supabase_main_enable=False,
            n8n_main_enable=False,
        )
        runtime = SimpleNamespace(config=config)

        self.assertFalse(service_enabled_for_mode(runtime, "main", "backend"))
        self.assertFalse(service_enabled_for_mode(runtime, "main", "frontend"))
        self.assertTrue(requirement_enabled_for_mode(runtime, "trees", "supabase"))
        self.assertFalse(requirement_enabled_for_mode(runtime, "trees", "postgres"))
        self.assertFalse(requirement_enabled_for_mode(runtime, "main", "redis"))


if __name__ == "__main__":
    unittest.main()
