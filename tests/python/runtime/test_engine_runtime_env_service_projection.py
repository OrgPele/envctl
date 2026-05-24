from __future__ import annotations

# ruff: noqa: F403,F405
from tests.python.runtime.engine_runtime_env_test_support import *


class EngineRuntimeEnvServiceProjectionTests(EngineRuntimeEnvTestCase):
    def test_project_service_env_builds_urls_and_log_overrides(self) -> None:
        runtime = SimpleNamespace(
            _command_override_value=lambda key: {"DB_HOST": "db.local", "DB_USER": "alice"}.get(key),
        )
        context = SimpleNamespace(
            name="Main",
            ports={
                "db": PortPlan(project="Main", requested=5432, assigned=5432, final=5432, source="assigned"),
                "supabase_api": PortPlan(
                    project="Main", requested=54321, assigned=54321, final=54321, source="assigned"
                ),
                "redis": PortPlan(project="Main", requested=6380, assigned=6380, final=6380, source="assigned"),
                "n8n": PortPlan(project="Main", requested=5678, assigned=5678, final=5678, source="assigned"),
            },
        )
        requirements = RequirementsResult(
            project="Main",
            db={"enabled": True, "success": True, "final": 5432},
            redis={"enabled": True, "success": True, "final": 6380},
            n8n={"enabled": True, "success": True, "final": 5678},
            supabase={
                "enabled": True,
                "success": True,
                "final": 5432,
                "resources": {"db": 5432, "api": 54321, "primary": 5432},
            },
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
        self.assertEqual(env["SUPABASE_URL"], "http://localhost:54321")
        self.assertEqual(env["SUPABASE_DB_PORT"], "5432")
        self.assertEqual(env["SUPABASE_PUBLIC_PORT"], "54321")
        self.assertEqual(env["SUPABASE_ANON_KEY"], default_supabase_anon_key(secret=DEFAULT_SUPABASE_JWT_SECRET))
        self.assertEqual(
            env["SUPABASE_SERVICE_ROLE_KEY"],
            default_supabase_service_role_key(secret=DEFAULT_SUPABASE_JWT_SECRET),
        )
        self.assertEqual(env["SUPABASE_JWT_SECRET"], DEFAULT_SUPABASE_JWT_SECRET)
        self.assertEqual(env["SUPABASE_JWKS_URL"], "http://localhost:54321/auth/v1/.well-known/jwks.json")
        self.assertEqual(env["LOG_PROFILE_OVERRIDE"], "debug")
        self.assertEqual(env["BACKEND_LOG_LEVEL_OVERRIDE"], "warn")
        self.assertEqual(env["FRONTEND_TEST_RUNNER"], "bun")

    def test_project_service_env_prefers_resource_ports_when_legacy_final_is_stale(self) -> None:
        runtime = SimpleNamespace(_command_override_value=lambda _key: None)
        context = SimpleNamespace(
            name="Main",
            ports={
                "db": PortPlan(project="Main", requested=5432, assigned=5432, final=5432, source="assigned"),
                "supabase_api": PortPlan(
                    project="Main", requested=54321, assigned=54321, final=54321, source="assigned"
                ),
                "redis": PortPlan(project="Main", requested=6380, assigned=6380, final=6380, source="assigned"),
                "n8n": PortPlan(project="Main", requested=5678, assigned=5678, final=5678, source="assigned"),
            },
        )
        requirements = RequirementsResult(
            project="Main",
            db={"enabled": True, "success": True, "final": 5432, "resources": {"primary": 15432}},
            redis={"enabled": True, "success": True, "final": 6380, "resources": {"primary": 16609}},
            n8n={"enabled": True, "success": True, "final": 5678, "resources": {"primary": 15908}},
            supabase={
                "enabled": True,
                "success": True,
                "final": 5662,
                "resources": {"db": 5574, "api": 54463, "primary": 5574},
            },
        )

        env = project_service_env(runtime, context, requirements=requirements, route=None)

        self.assertIn("@localhost:5574/postgres", env["DATABASE_URL"])
        self.assertEqual(env["SUPABASE_DB_PORT"], "5574")
        self.assertEqual(env["SUPABASE_PUBLIC_PORT"], "54463")
        self.assertEqual(env["SUPABASE_URL"], "http://localhost:54463")
        self.assertEqual(env["REDIS_URL"], "redis://localhost:16609/0")
        self.assertEqual(env["N8N_URL"], "http://localhost:15908")

    def test_no_deps_still_projects_launch_env_without_enabling_requirements(self) -> None:
        runtime = SimpleNamespace(
            env={},
            _command_override_value=lambda _key: None,
            config=SimpleNamespace(
                raw={},
                dependency_env_section_present=True,
                dependency_env_template_errors=(),
                dependency_env_templates=(
                    SimpleNamespace(
                        name="DATABASE_URL",
                        template="${ENVCTL_SOURCE_DATABASE_URL}",
                        line_number=1,
                    ),
                    SimpleNamespace(
                        name="REDIS_URL",
                        template="${ENVCTL_SOURCE_REDIS_URL}",
                        line_number=2,
                    ),
                ),
            ),
        )
        context = SimpleNamespace(
            name="feature-a-1",
            ports={
                "db": PortPlan(project="feature-a-1", requested=5432, assigned=5520, final=5520, source="assigned"),
                "redis": PortPlan(
                    project="feature-a-1", requested=6379, assigned=6467, final=6467, source="assigned"
                ),
                "n8n": PortPlan(project="feature-a-1", requested=5678, assigned=5766, final=5766, source="assigned"),
                "supabase_api": PortPlan(
                    project="feature-a-1", requested=54321, assigned=5473, final=5473, source="assigned"
                ),
            },
        )
        requirements = RequirementsResult(
            project="feature-a-1",
            db={"enabled": False, "success": True, "final": 5520},
            redis={"enabled": False, "success": True, "final": 6467},
            n8n={"enabled": False, "success": True, "final": 5766},
            supabase={
                "enabled": False,
                "success": True,
                "final": 5520,
                "resources": {"db": 5520, "api": 5473, "primary": 5520},
            },
        )
        route = parse_route(["--plan", "feature-a", "--no-deps"], env={})

        self.assertFalse(requirement_enabled_for_mode(runtime, "trees", "redis", route=route))
        internal_env = project_service_env_internal(runtime, context, requirements=requirements, route=route)
        backend_env = project_service_env(
            runtime,
            context,
            requirements=requirements,
            route=route,
            service_name="backend",
        )

        self.assertEqual(
            internal_env["DATABASE_URL"],
            "postgresql+asyncpg://postgres:supabase-db-password@localhost:5520/postgres",
        )
        self.assertEqual(internal_env["REDIS_URL"], "redis://localhost:6467/0")
        self.assertEqual(backend_env["DATABASE_URL"], internal_env["DATABASE_URL"])
        self.assertEqual(backend_env["REDIS_URL"], internal_env["REDIS_URL"])
        self.assertNotIn("DB_HOST", backend_env)

    def test_project_service_env_projects_external_supabase_contract_without_local_defaults(self) -> None:
        overrides = {
            "SUPABASE_URL": "https://supabase.example.test",
            "SUPABASE_ANON_KEY": "external-anon",
            "SUPABASE_SERVICE_ROLE_KEY": "external-service-role",
            "DATABASE_URL": "postgresql+asyncpg://app:secret@db.example.test:6543/app",
        }
        runtime = SimpleNamespace(
            env={"ENVCTL_DEPENDENCY_SUPABASE_MODE": "external", **overrides},
            config=SimpleNamespace(raw={}),
            _command_override_value=lambda key: overrides.get(key),
        )
        context = SimpleNamespace(
            name="Main",
            ports={
                "db": PortPlan(project="Main", requested=5432, assigned=5432, final=5432, source="assigned"),
                "supabase_api": PortPlan(
                    project="Main", requested=54321, assigned=54321, final=54321, source="assigned"
                ),
            },
        )
        requirements = RequirementsResult(
            project="Main",
            supabase={
                "enabled": True,
                "success": True,
                "runtime_status": "external",
                "external": True,
            },
        )

        env = project_service_env(runtime, context, requirements=requirements, route=None)

        self.assertEqual(env["SUPABASE_URL"], "https://supabase.example.test")
        self.assertEqual(env["SUPABASE_PUBLIC_URL"], "https://supabase.example.test")
        self.assertEqual(env["SUPABASE_ANON_KEY"], "external-anon")
        self.assertEqual(env["SUPABASE_SERVICE_ROLE_KEY"], "external-service-role")
        self.assertEqual(env["DATABASE_URL"], "postgresql+asyncpg://app:secret@db.example.test:6543/app")
        self.assertEqual(env["SUPABASE_API_PORT"], "443")
        self.assertEqual(env["SUPABASE_DB_PORT"], "6543")
        self.assertEqual(env["ENVCTL_SOURCE_SUPABASE_URL"], "https://supabase.example.test")
