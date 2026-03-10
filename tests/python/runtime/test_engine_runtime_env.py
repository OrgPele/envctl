from __future__ import annotations

from pathlib import Path
import unittest
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.command_router import parse_route  # noqa: E402
from envctl_engine.runtime.engine_runtime_env import (  # noqa: E402
    _route_is_implicit_start,
    effective_main_requirement_flags,
    main_requirements_mode,
    project_service_env,
    requirement_enabled_for_mode,
    requirements_ready,
    runtime_env_overrides,
    service_enabled_for_mode,
    validate_mode_toggles,
)
from envctl_engine.state.models import PortPlan, RequirementsResult  # noqa: E402


class EngineRuntimeEnvTests(unittest.TestCase):
    def test_runtime_env_overrides_forward_expected_flags(self) -> None:
        route = parse_route(
            [
                "--plan",
                "feature-a",
                "--docker",
                "--setup-worktree-existing",
                "--recreate-existing-worktree",
                "--setup-include-worktrees",
                "feature-a-1,feature-a-2",
                "--seed-requirements-from-base",
                "--stop-all-remove-volumes",
            ],
            env={},
        )

        env = runtime_env_overrides(route)

        self.assertEqual(env.get("DOCKER_MODE"), "true")
        self.assertEqual(env.get("SETUP_WORKTREE_EXISTING"), "true")
        self.assertEqual(env.get("SETUP_WORKTREE_RECREATE"), "true")
        self.assertEqual(env.get("SETUP_INCLUDE_WORKTREES_RAW"), "feature-a-1,feature-a-2")
        self.assertEqual(env.get("SEED_REQUIREMENTS_FROM_BASE"), "true")
        self.assertEqual(env.get("RUN_SH_COMMAND_STOP_ALL_REMOVE_VOLUMES"), "true")

    def test_main_requirements_mode_rejects_conflicting_flags(self) -> None:
        route = parse_route(
            ["start", "--main-services-local", "--main-services-remote"],
            env={},
        )
        with self.assertRaises(RuntimeError):
            main_requirements_mode(route)

    def test_effective_main_requirement_flags_switch_with_local_mode(self) -> None:
        runtime = SimpleNamespace(
            config=SimpleNamespace(
                postgres_main_enable=True,
                redis_main_enable=True,
                supabase_main_enable=False,
                n8n_main_enable=False,
            )
        )
        route = parse_route(["start", "--main-services-local"], env={})

        flags = effective_main_requirement_flags(runtime, route)

        self.assertFalse(flags["postgres_main_enable"])
        self.assertTrue(flags["supabase_main_enable"])
        self.assertTrue(flags["n8n_main_enable"])
        self.assertTrue(flags["redis_main_enable"])

    def test_validate_mode_toggles_rejects_invalid_main_combo(self) -> None:
        runtime = SimpleNamespace(
            config=SimpleNamespace(
                startup_enabled_for_mode=lambda mode: True,
                postgres_main_enable=True,
                redis_main_enable=True,
                supabase_main_enable=True,
                n8n_main_enable=False,
            )
        )
        with self.assertRaises(RuntimeError):
            validate_mode_toggles(runtime, "main")

    def test_validate_mode_toggles_rejects_disabled_startup(self) -> None:
        runtime = SimpleNamespace(
            config=SimpleNamespace(
                startup_enabled_for_mode=lambda mode: mode != "main",
                profile_for_mode=lambda mode: SimpleNamespace(
                    startup_enable=mode != "main",
                    backend_enable=True,
                    frontend_enable=True,
                    postgres_enable=True,
                    redis_enable=True,
                    supabase_enable=False,
                    n8n_enable=False,
                ),
            )
        )

        with self.assertRaisesRegex(RuntimeError, "envctl runs are disabled for main"):
            validate_mode_toggles(runtime, "main")

    def test_validate_mode_toggles_allows_plan_when_runs_disabled(self) -> None:
        runtime = SimpleNamespace(
            config=SimpleNamespace(
                startup_enabled_for_mode=lambda mode: mode != "main",
                profile_for_mode=lambda mode: SimpleNamespace(
                    startup_enable=mode != "main",
                    backend_enable=True,
                    frontend_enable=True,
                    postgres_enable=True,
                    redis_enable=True,
                    supabase_enable=False,
                    n8n_enable=False,
                ),
            )
        )

        validate_mode_toggles(runtime, "main", route=parse_route(["--plan"], env={}))

    def test_validate_mode_toggles_allows_implicit_start_when_runs_disabled(self) -> None:
        runtime = SimpleNamespace(
            config=SimpleNamespace(
                startup_enabled_for_mode=lambda mode: mode != "main",
                profile_for_mode=lambda mode: SimpleNamespace(
                    startup_enable=mode != "main",
                    backend_enable=True,
                    frontend_enable=True,
                    postgres_enable=True,
                    redis_enable=True,
                    supabase_enable=False,
                    n8n_enable=False,
                ),
            )
        )

        validate_mode_toggles(runtime, "main", route=parse_route(["--main"], env={}))

    def test_route_is_implicit_start_distinguishes_bare_mode_from_explicit_start(self) -> None:
        self.assertTrue(_route_is_implicit_start(parse_route(["--main"], env={})))
        self.assertTrue(_route_is_implicit_start(parse_route([], env={})))
        self.assertFalse(_route_is_implicit_start(parse_route(["start", "--main"], env={})))
        self.assertFalse(_route_is_implicit_start(parse_route(["--command=start", "--main"], env={})))

    def test_project_service_env_builds_urls_and_log_overrides(self) -> None:
        runtime = SimpleNamespace(
            _command_override_value=lambda key: {"DB_HOST": "db.local", "DB_USER": "alice"}.get(key),
        )
        context = SimpleNamespace(
            name="Main",
            ports={
                "db": PortPlan(project="Main", requested=5432, assigned=5432, final=5432, source="assigned"),
                "redis": PortPlan(project="Main", requested=6380, assigned=6380, final=6380, source="assigned"),
                "n8n": PortPlan(project="Main", requested=5678, assigned=5678, final=5678, source="assigned"),
            },
        )
        requirements = RequirementsResult(
            project="Main",
            db={"enabled": True, "success": True, "final": 5432},
            redis={"enabled": True, "success": True, "final": 6380},
            n8n={"enabled": True, "success": True, "final": 5678},
            supabase={"enabled": True, "success": True, "final": 5432},
            health="healthy",
            failures=[],
        )
        route = parse_route(
            [
                "start",
                "--log-profile",
                "debug",
                "--backend-log-level",
                "warn",
                "--frontend-test-runner",
                "bun",
            ],
            env={},
        )

        env = project_service_env(runtime, context, requirements=requirements, route=route)

        self.assertEqual(env["ENVCTL_PROJECT_NAME"], "Main")
        self.assertEqual(env["DB_HOST"], "db.local")
        self.assertEqual(env["DB_USER"], "alice")
        self.assertIn("postgresql+asyncpg://alice:supabase-db-password@db.local:5432/postgres", env["DATABASE_URL"])
        self.assertEqual(env["REDIS_URL"], "redis://localhost:6380/0")
        self.assertEqual(env["N8N_URL"], "http://localhost:5678")
        self.assertEqual(env["SUPABASE_URL"], "http://localhost:5432")
        self.assertEqual(env["LOG_PROFILE_OVERRIDE"], "debug")
        self.assertEqual(env["BACKEND_LOG_LEVEL_OVERRIDE"], "warn")
        self.assertEqual(env["FRONTEND_TEST_RUNNER"], "bun")

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
