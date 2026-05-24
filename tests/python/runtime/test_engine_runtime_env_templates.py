from __future__ import annotations

# ruff: noqa: F403,F405
from tests.python.runtime.engine_runtime_env_test_support import *


class EngineRuntimeEnvTemplatesTests(EngineRuntimeEnvTestCase):
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
