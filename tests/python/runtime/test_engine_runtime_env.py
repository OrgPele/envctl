from __future__ import annotations

from pathlib import Path
import unittest
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.command_router import parse_route  # noqa: E402
from envctl_engine.shared.dependency_compose_assets import (  # noqa: E402
    DEFAULT_SUPABASE_JWT_SECRET,
    default_supabase_anon_key,
    default_supabase_service_role_key,
)
from envctl_engine.runtime.engine_runtime_env import (  # noqa: E402
    _route_is_implicit_start,
    effective_main_requirement_flags,
    main_requirements_mode,
    project_service_env,
    project_service_env_internal,
    requirement_enabled_for_mode,
    requirements_ready,
    resolve_dependency_env_templates,
    runtime_env_overrides,
    service_env_overlays,
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

    def test_external_dependency_mode_implies_requirement_enabled(self) -> None:
        runtime = SimpleNamespace(
            env={"ENVCTL_EXTERNAL_DEPENDENCIES": "supabase"},
            config=SimpleNamespace(
                startup_enabled_for_mode=lambda _mode: True,
                requirement_enabled_for_mode=lambda _mode, _name: False,
            ),
        )

        self.assertTrue(requirement_enabled_for_mode(runtime, "main", "supabase"))

    def test_project_service_env_uses_dependency_env_templates_when_section_present(self) -> None:
        runtime = SimpleNamespace(
            _command_override_value=lambda key: {"DB_HOST": "db.local", "DB_USER": "alice"}.get(key),
            config=SimpleNamespace(
                dependency_env_section_present=True,
                dependency_env_template_errors=(),
                dependency_env_templates=(
                    SimpleNamespace(
                        name="APP_DATABASE_URL",
                        template="${ENVCTL_SOURCE_DATABASE_URL}?sslmode=disable",
                        line_number=1,
                    ),
                    SimpleNamespace(
                        name="WORKFLOW_BASE_URL",
                        template="${ENVCTL_SOURCE_N8N_URL}",
                        line_number=2,
                    ),
                ),
            ),
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
            supabase={"enabled": False, "success": False, "final": 0},
            health="healthy",
            failures=[],
        )

        internal_env = project_service_env_internal(runtime, context, requirements=requirements, route=None)
        env = project_service_env(runtime, context, requirements=requirements, route=None)

        self.assertIn("DATABASE_URL", internal_env)
        self.assertIn("REDIS_URL", internal_env)
        self.assertEqual(env["APP_DATABASE_URL"], internal_env["DATABASE_URL"] + "?sslmode=disable")
        self.assertEqual(env["WORKFLOW_BASE_URL"], "http://localhost:5678")
        self.assertNotIn("DATABASE_URL", env)
        self.assertNotIn("REDIS_URL", env)
        self.assertNotIn("DB_HOST", env)

    def test_project_service_env_applies_backend_only_templates_to_backend(self) -> None:
        runtime = SimpleNamespace(
            _command_override_value=lambda key: None,
            config=SimpleNamespace(
                backend_dependency_env_section_present=True,
                backend_dependency_env_template_errors=(),
                backend_dependency_env_templates=(
                    SimpleNamespace(
                        name="APP_DATABASE_URL",
                        template="${ENVCTL_SOURCE_DATABASE_URL}",
                        line_number=1,
                    ),
                ),
            ),
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
            n8n={"enabled": False, "success": False, "final": 0},
            supabase={"enabled": False, "success": False, "final": 0},
            health="healthy",
            failures=[],
        )

        backend_env = project_service_env(
            runtime,
            context,
            requirements=requirements,
            route=None,
            service_name="backend",
        )
        frontend_env = project_service_env(
            runtime,
            context,
            requirements=requirements,
            route=None,
            service_name="frontend",
        )
        internal_env = project_service_env_internal(runtime, context, requirements=requirements, route=None)

        self.assertEqual(backend_env["APP_DATABASE_URL"], internal_env["DATABASE_URL"])
        self.assertNotIn("DATABASE_URL", backend_env)
        self.assertNotIn("DATABASE_URL", frontend_env)
        self.assertNotIn("APP_DATABASE_URL", frontend_env)

    def test_project_service_env_combines_shared_and_frontend_templates_for_frontend(self) -> None:
        runtime = SimpleNamespace(
            _command_override_value=lambda key: None,
            config=SimpleNamespace(
                dependency_env_section_present=True,
                dependency_env_template_errors=(),
                dependency_env_templates=(
                    SimpleNamespace(
                        name="SUPABASE_URL",
                        template="${ENVCTL_SOURCE_SUPABASE_URL}",
                        line_number=1,
                    ),
                ),
                frontend_dependency_env_section_present=True,
                frontend_dependency_env_template_errors=(),
                frontend_dependency_env_templates=(
                    SimpleNamespace(
                        name="VITE_SUPABASE_URL",
                        template="${SUPABASE_URL}",
                        line_number=10,
                    ),
                ),
            ),
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
            db={"enabled": False, "success": False, "final": 0},
            redis={"enabled": False, "success": False, "final": 0},
            n8n={"enabled": False, "success": False, "final": 0},
            supabase={
                "enabled": True,
                "success": True,
                "final": 5432,
                "resources": {"db": 5432, "api": 54321, "primary": 5432},
            },
            health="healthy",
            failures=[],
        )

        frontend_env = project_service_env(
            runtime,
            context,
            requirements=requirements,
            route=None,
            service_name="frontend",
        )
        backend_env = project_service_env(
            runtime,
            context,
            requirements=requirements,
            route=None,
            service_name="backend",
        )

        self.assertEqual(frontend_env["SUPABASE_URL"], "http://localhost:54321")
        self.assertEqual(frontend_env["VITE_SUPABASE_URL"], "http://localhost:54321")
        self.assertEqual(backend_env["SUPABASE_URL"], "http://localhost:54321")
        self.assertNotIn("VITE_SUPABASE_URL", backend_env)

    def test_project_service_env_projects_supabase_auth_url_separate_from_db_port(self) -> None:
        runtime = SimpleNamespace(
            _command_override_value=lambda key: None,
            config=SimpleNamespace(
                frontend_dependency_env_section_present=True,
                frontend_dependency_env_template_errors=(),
                frontend_dependency_env_templates=(
                    SimpleNamespace(
                        name="VITE_SUPABASE_URL",
                        template="${ENVCTL_SOURCE_SUPABASE_URL}",
                        line_number=1,
                    ),
                ),
                backend_dependency_env_section_present=True,
                backend_dependency_env_template_errors=(),
                backend_dependency_env_templates=(
                    SimpleNamespace(
                        name="SUPABASE_JWKS_URL",
                        template="${ENVCTL_SOURCE_SUPABASE_URL}/auth/v1/.well-known/jwks.json",
                        line_number=2,
                    ),
                ),
            ),
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
                "final": 5432,
                "resources": {"db": 5432, "api": 54321, "primary": 5432},
            },
            health="healthy",
            failures=[],
        )

        internal_env = project_service_env_internal(runtime, context, requirements=requirements, route=None)
        frontend_env = project_service_env(
            runtime, context, requirements=requirements, route=None, service_name="frontend"
        )
        backend_env = project_service_env(runtime, context, requirements=requirements, route=None, service_name="backend")

        self.assertEqual(internal_env["DB_PORT"], "5432")
        self.assertEqual(internal_env["SUPABASE_DB_PORT"], "5432")
        self.assertEqual(internal_env["SUPABASE_PUBLIC_PORT"], "54321")
        self.assertEqual(internal_env["SUPABASE_URL"], "http://localhost:54321")
        self.assertEqual(frontend_env["VITE_SUPABASE_URL"], "http://localhost:54321")
        self.assertEqual(
            backend_env["SUPABASE_JWKS_URL"],
            "http://localhost:54321/auth/v1/.well-known/jwks.json",
        )

    def test_project_service_env_exposes_source_aliases_and_structured_overlays(self) -> None:
        runtime = SimpleNamespace(
            _command_override_value=lambda key: None,
            env={"ENVCTL_FRONTEND_ENV__VITE_SUPABASE_URL": "${ENVCTL_SOURCE_SUPABASE_URL}"},
            config=SimpleNamespace(raw={"ENVCTL_FRONTEND_ENV__VITE_API_URL": "${ENVCTL_SOURCE_BACKEND_URL}/api/v1"}),
        )
        context = SimpleNamespace(
            name="Main",
            ports={
                "backend": PortPlan(project="Main", requested=8000, assigned=8000, final=8123, source="assigned"),
                "db": PortPlan(project="Main", requested=5432, assigned=5432, final=5432, source="assigned"),
                "supabase_api": PortPlan(
                    project="Main", requested=54321, assigned=54321, final=54447, source="assigned"
                ),
            },
        )
        requirements = RequirementsResult(
            project="Main",
            supabase={
                "enabled": True,
                "success": True,
                "final": 5432,
                "resources": {"db": 5432, "api": 54447, "primary": 5432},
            },
        )

        env = project_service_env(runtime, context, requirements=requirements, route=None, service_name="frontend")
        overlays = service_env_overlays(runtime, service_name="frontend", base_env=env)

        self.assertEqual(env["ENVCTL_SOURCE_SUPABASE_URL"], "http://localhost:54447")
        self.assertEqual(env["ENVCTL_SOURCE_BACKEND_URL"], "http://localhost:8123")
        self.assertEqual(overlays["VITE_SUPABASE_URL"], "http://localhost:54447")
        self.assertEqual(overlays["VITE_API_URL"], "http://localhost:8123/api/v1")

    def test_frontend_launch_env_rejects_supabase_service_role_source_template(self) -> None:
        runtime = SimpleNamespace(
            _command_override_value=lambda key: None,
            config=SimpleNamespace(
                frontend_dependency_env_section_present=True,
                frontend_dependency_env_template_errors=(),
                frontend_dependency_env_templates=(
                    SimpleNamespace(
                        name="SUPABASE_SERVICE_ROLE_KEY",
                        template="${ENVCTL_SOURCE_SUPABASE_SERVICE_ROLE_KEY}",
                        line_number=4,
                    ),
                ),
            ),
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
                "final": 5432,
                "resources": {"db": 5432, "api": 54321, "primary": 5432},
            },
            health="healthy",
            failures=[],
        )

        with self.assertRaisesRegex(RuntimeError, "SUPABASE_SERVICE_ROLE_KEY.*frontend"):
            project_service_env(runtime, context, requirements=requirements, route=None, service_name="frontend")

    def test_project_service_env_includes_synced_supabase_auth_user_sources(self) -> None:
        runtime = SimpleNamespace(
            _command_override_value=lambda key: None,
            config=SimpleNamespace(
                supabase_auth_users=(
                    SimpleNamespace(
                        name="e2e",
                        env_suffix="E2E",
                        email="e2e@example.test",
                        password="e2e-password",
                        expose_password=True,
                    ),
                ),
                runtime_root=Path("/unused"),
            ),
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
                "final": 5432,
                "resources": {"db": 5432, "api": 54321, "primary": 5432},
                "auth_users": {
                    "e2e": {
                        "id": "auth-user-id",
                        "email": "e2e@example.test",
                        "status": "created",
                    }
                },
            },
            health="healthy",
            failures=[],
        )

        env = project_service_env_internal(runtime, context, requirements=requirements, route=None)

        self.assertEqual(env["SUPABASE_USER_E2E_ID"], "auth-user-id")
        self.assertEqual(env["SUPABASE_USER_E2E_EMAIL"], "e2e@example.test")
        self.assertEqual(env["SUPABASE_USER_E2E_PASSWORD"], "e2e-password")
        self.assertEqual(env["SUPABASE_TEST_USER_ID"], "auth-user-id")
        self.assertEqual(env["SUPABASE_TEST_USER_EMAIL"], "e2e@example.test")
        self.assertEqual(env["SUPABASE_TEST_USER_PASSWORD"], "e2e-password")

    def test_project_service_env_applies_generic_service_templates_and_service_source_placeholders(self) -> None:
        runtime = SimpleNamespace(
            _command_override_value=lambda key: None,
            config=SimpleNamespace(
                service_dependency_env_section_present={"voice-runtime": True},
                service_dependency_env_template_errors={"voice-runtime": ()},
                service_dependency_env_templates={
                    "voice-runtime": (
                        SimpleNamespace(
                            name="VOICE_RUNTIME_PUBLIC_URL",
                            template="${ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_PUBLIC_URL}",
                            line_number=1,
                        ),
                    )
                },
                mode_service_dependency_env_section_present={("main", "voice-runtime"): True},
                mode_service_dependency_env_template_errors={("main", "voice-runtime"): ()},
                mode_service_dependency_env_templates={
                    ("main", "voice-runtime"): (
                        SimpleNamespace(
                            name="PELE_API_BASE_URL",
                            template="${ENVCTL_SOURCE_BACKEND_URL}",
                            line_number=2,
                        ),
                    )
                },
                app_service_by_name=lambda name: SimpleNamespace(
                    env_suffix="VOICE_RUNTIME",
                    public_url_template="http://${ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_HOST}:${ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_PORT}",
                    health_url_template="http://${ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_HOST}:${ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_PORT}/readyz",
                )
                if name == "voice-runtime"
                else None,
            ),
        )
        context = SimpleNamespace(
            name="Main",
            ports={
                "backend": PortPlan(project="Main", requested=8000, assigned=8000, final=8000, source="assigned"),
                "voice-runtime": PortPlan(
                    project="Main", requested=8010, assigned=8010, final=8010, source="assigned"
                ),
                "db": PortPlan(project="Main", requested=5432, assigned=5432, final=5432, source="assigned"),
                "redis": PortPlan(project="Main", requested=6380, assigned=6380, final=6380, source="assigned"),
                "n8n": PortPlan(project="Main", requested=5678, assigned=5678, final=5678, source="assigned"),
            },
        )
        requirements = RequirementsResult(project="Main")
        route = parse_route(["start", "--main"], env={})

        voice_env = project_service_env(
            runtime,
            context,
            requirements=requirements,
            route=route,
            service_name="voice-runtime",
        )
        backend_env = project_service_env(
            runtime,
            context,
            requirements=requirements,
            route=route,
            service_name="backend",
        )

        self.assertEqual(voice_env["VOICE_RUNTIME_PUBLIC_URL"], "http://localhost:8010")
        self.assertEqual(voice_env["PELE_API_BASE_URL"], "http://localhost:8000")
        self.assertNotIn("VOICE_RUNTIME_PUBLIC_URL", backend_env)

    def test_project_service_env_skips_missing_source_lines_and_keeps_following_valid_aliases(self) -> None:
        runtime = SimpleNamespace(
            _command_override_value=lambda key: None,
            config=SimpleNamespace(
                dependency_env_section_present=True,
                dependency_env_template_errors=(),
                dependency_env_templates=(
                    SimpleNamespace(
                        name="N8N_URL",
                        template="${ENVCTL_SOURCE_N8N_URL}",
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
            name="Main",
            ports={
                "db": PortPlan(project="Main", requested=5432, assigned=5432, final=5432, source="assigned"),
                "redis": PortPlan(project="Main", requested=6380, assigned=6380, final=6380, source="assigned"),
                "n8n": PortPlan(project="Main", requested=5678, assigned=5678, final=5678, source="assigned"),
            },
        )
        requirements = RequirementsResult(
            project="Main",
            db={"enabled": False, "success": False, "final": 0},
            redis={"enabled": True, "success": True, "final": 6380},
            n8n={"enabled": False, "success": False, "final": 0},
            supabase={"enabled": False, "success": False, "final": 0},
            health="healthy",
            failures=[],
        )

        env = project_service_env(runtime, context, requirements=requirements, route=None)

        self.assertNotIn("N8N_URL", env)
        self.assertEqual(env["REDIS_URL"], "redis://localhost:6380/0")

    def test_resolve_dependency_env_templates_raises_for_unknown_emitted_reference(self) -> None:
        entries = (
            SimpleNamespace(
                name="APP_DATABASE_URL",
                template="${DATABASE_URL}?sslmode=disable",
                line_number=14,
            ),
        )

        with self.assertRaisesRegex(RuntimeError, "unknown variable DATABASE_URL"):
            resolve_dependency_env_templates(entries, canonical_dependency_env={"DATABASE_URL": "postgresql://db"})

    def test_resolve_dependency_env_templates_rejects_reserved_prefix_and_duplicates(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "reserved prefix ENVCTL_SOURCE_"):
            resolve_dependency_env_templates(
                (SimpleNamespace(name="ENVCTL_SOURCE_DATABASE_URL", template="x", line_number=1),),
                canonical_dependency_env={"DATABASE_URL": "postgresql://db"},
            )
        with self.assertRaisesRegex(RuntimeError, "duplicate launch env key APP_DATABASE_URL"):
            resolve_dependency_env_templates(
                (
                    SimpleNamespace(name="APP_DATABASE_URL", template="first", line_number=1),
                    SimpleNamespace(name="APP_DATABASE_URL", template="second", line_number=2),
                ),
                canonical_dependency_env={"DATABASE_URL": "postgresql://db"},
            )
        with self.assertRaisesRegex(RuntimeError, "duplicate launch env key APP_DATABASE_URL"):
            resolve_dependency_env_templates(
                (SimpleNamespace(name="APP_DATABASE_URL", template="ignored", line_number=2),),
                canonical_dependency_env={"DATABASE_URL": "postgresql://db"},
                resolved_env_base={"APP_DATABASE_URL": "postgresql://db"},
            )

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
