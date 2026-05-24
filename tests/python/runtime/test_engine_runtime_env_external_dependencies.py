from __future__ import annotations

# ruff: noqa: F403,F405
from tests.python.runtime.engine_runtime_env_test_support import *


class EngineRuntimeEnvExternalDependenciesTests(EngineRuntimeEnvTestCase):
    def test_main_mode_auto_external_dependency_when_complete_local_env_exists(self) -> None:
        runtime = SimpleNamespace(
            env={
                "SUPABASE_URL": "https://supabase.example.test",
                "SUPABASE_ANON_KEY": "external-anon",
                "REDIS_URL": "redis://cache.example.test:6382/0",
            },
            config=SimpleNamespace(
                raw={},
                startup_enabled_for_mode=lambda _mode: True,
                requirement_enabled_for_mode=lambda _mode, _name: False,
            ),
        )

        self.assertTrue(dependency_external_mode(runtime, "supabase", mode="main"))
        self.assertTrue(dependency_external_mode(runtime, "redis", mode="main"))
        self.assertFalse(dependency_external_mode(runtime, "supabase", mode="trees"))
        self.assertFalse(requirement_enabled_for_mode(runtime, "trees", "supabase"))
        self.assertTrue(requirement_enabled_for_mode(runtime, "main", "supabase"))

    def test_managed_deps_route_flag_disables_main_auto_external_dependency_detection(self) -> None:
        runtime = SimpleNamespace(
            env={
                "SUPABASE_URL": "https://supabase.example.test",
                "SUPABASE_ANON_KEY": "external-anon",
                "REDIS_URL": "redis://cache.example.test:6382/0",
            },
            config=SimpleNamespace(
                raw={},
                startup_enabled_for_mode=lambda _mode: True,
                requirement_enabled_for_mode=lambda _mode, _name: False,
            ),
        )
        route = parse_route(["--main", "--managed-deps"], env={})

        self.assertFalse(dependency_external_mode(runtime, "supabase", mode="main", route=route))
        self.assertFalse(dependency_external_mode(runtime, "redis", mode="main", route=route))
        self.assertFalse(requirement_enabled_for_mode(runtime, "main", "supabase", route=route))

    def test_main_managed_redis_ignores_stale_default_backend_env_for_auto_external_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            backend = repo / "backend"
            backend.mkdir()
            backend.joinpath(".env").write_text("REDIS_URL=redis://localhost:6518/0\n", encoding="utf-8")
            runtime = SimpleNamespace(
                env={},
                config=SimpleNamespace(
                    raw={},
                    base_dir=repo,
                    backend_dir_name="backend",
                    frontend_dir_name="frontend",
                    startup_enabled_for_mode=lambda _mode: True,
                    requirement_enabled_for_mode=lambda _mode, name: name == "redis",
                ),
            )

            self.assertFalse(dependency_external_mode(runtime, "redis", mode="main"))
            self.assertTrue(requirement_enabled_for_mode(runtime, "main", "redis"))

    def test_global_managed_dependency_env_disables_main_auto_external_dependency_detection(self) -> None:
        runtime = SimpleNamespace(
            env={
                "ENVCTL_EXTERNAL_DEPENDENCIES_MODE": "managed",
                "SUPABASE_URL": "https://supabase.example.test",
                "SUPABASE_ANON_KEY": "external-anon",
                "REDIS_URL": "redis://cache.example.test:6382/0",
            },
            config=SimpleNamespace(
                raw={},
                startup_enabled_for_mode=lambda _mode: True,
                requirement_enabled_for_mode=lambda _mode, _name: False,
            ),
        )

        self.assertFalse(dependency_external_mode(runtime, "supabase", mode="main"))
        self.assertFalse(dependency_external_mode(runtime, "redis", mode="main"))

    def test_main_mode_does_not_auto_external_supabase_for_partial_env(self) -> None:
        runtime = SimpleNamespace(
            env={"SUPABASE_URL": "https://supabase.example.test"},
            config=SimpleNamespace(
                raw={},
                startup_enabled_for_mode=lambda _mode: True,
                requirement_enabled_for_mode=lambda _mode, _name: False,
            ),
        )

        self.assertFalse(dependency_external_mode(runtime, "supabase", mode="main"))
        self.assertFalse(requirement_enabled_for_mode(runtime, "main", "supabase"))

    def test_main_mode_auto_external_reads_application_env_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            backend = repo / "backend"
            frontend = repo / "frontend"
            backend.mkdir()
            frontend.mkdir()
            backend.joinpath(".env").write_text(
                "SUPABASE_URL=https://backend-supabase.example.test\n"
                "SUPABASE_ANON_KEY=backend-anon\n"
                "DATABASE_URL=postgresql+asyncpg://app:secret@db.example.test:6543/app\n",
                encoding="utf-8",
            )
            frontend.joinpath(".env").write_text("REDIS_URL=redis://cache.example.test:6382/0\n", encoding="utf-8")
            runtime = SimpleNamespace(
                env={},
                config=SimpleNamespace(
                    raw={},
                    base_dir=repo,
                    backend_dir_name="backend",
                    frontend_dir_name="frontend",
                    startup_enabled_for_mode=lambda _mode: True,
                    requirement_enabled_for_mode=lambda _mode, _name: False,
                ),
            )

            self.assertTrue(dependency_external_mode(runtime, "supabase", mode="main"))
            self.assertTrue(dependency_external_mode(runtime, "postgres", mode="main"))
            self.assertTrue(dependency_external_mode(runtime, "redis", mode="main"))
            self.assertFalse(dependency_external_mode(runtime, "supabase", mode="trees"))

    def test_backend_env_override_file_does_not_drive_external_dependency_auto_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            override = repo / "config" / "backend.override.env"
            override.parent.mkdir(parents=True, exist_ok=True)
            override.write_text(
                "DATABASE_URL=postgresql+asyncpg://app:secret@db.example.test:6543/app\n",
                encoding="utf-8",
            )
            runtime = SimpleNamespace(
                env={"BACKEND_ENV_FILE_OVERRIDE": str(override)},
                config=SimpleNamespace(
                    raw={},
                    base_dir=repo,
                    backend_dir_name="backend",
                    frontend_dir_name="frontend",
                    startup_enabled_for_mode=lambda _mode: True,
                    requirement_enabled_for_mode=lambda _mode, _name: False,
                ),
            )

            self.assertFalse(dependency_external_mode(runtime, "postgres", mode="main"))

    def test_main_mode_auto_external_reads_repo_root_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "backend").mkdir()
            (repo / "frontend").mkdir()
            repo.joinpath(".env").write_text(
                "SUPABASE_URL=https://root-supabase.example.test\n"
                "SUPABASE_ANON_KEY=root-anon\n"
                "DATABASE_URL=postgresql+asyncpg://app:secret@db.example.test:6543/app\n",
                encoding="utf-8",
            )
            runtime = SimpleNamespace(
                env={},
                config=SimpleNamespace(
                    raw={},
                    base_dir=repo,
                    backend_dir_name="backend",
                    frontend_dir_name="frontend",
                    startup_enabled_for_mode=lambda _mode: True,
                    requirement_enabled_for_mode=lambda _mode, _name: False,
                ),
            )

            self.assertTrue(dependency_external_mode(runtime, "supabase", mode="main"))
            self.assertTrue(dependency_external_mode(runtime, "postgres", mode="main"))
            self.assertFalse(dependency_external_mode(runtime, "supabase", mode="trees"))

    def test_external_supabase_accepts_vite_anon_key_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "backend").mkdir()
            (repo / "frontend").mkdir()
            repo.joinpath(".env").write_text(
                "SUPABASE_URL=https://root-supabase.example.test\n"
                "VITE_SUPABASE_ANON_KEY=vite-anon\n",
                encoding="utf-8",
            )
            runtime = SimpleNamespace(
                env={},
                config=SimpleNamespace(
                    raw={},
                    base_dir=repo,
                    backend_dir_name="backend",
                    frontend_dir_name="frontend",
                ),
                _command_override_value=lambda _key: None,
            )
            requirements = RequirementsResult(
                project="Main",
                supabase={"enabled": True, "success": True, "external": True, "runtime_status": "external"},
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

            self.assertTrue(dependency_external_mode(runtime, "supabase", mode="main"))

            projected = project_service_env(runtime, context, requirements=requirements)

            self.assertEqual(projected["SUPABASE_ANON_KEY"], "vite-anon")
            self.assertEqual(projected["ENVCTL_SOURCE_SUPABASE_ANON_KEY"], "vite-anon")

    def test_envctl_values_take_precedence_over_application_env_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            backend = repo / "backend"
            backend.mkdir()
            backend.joinpath(".env").write_text(
                "SUPABASE_URL=https://backend-supabase.example.test\n"
                "SUPABASE_ANON_KEY=backend-anon\n",
                encoding="utf-8",
            )
            runtime = SimpleNamespace(
                env={},
                config=SimpleNamespace(
                    raw={
                        "SUPABASE_URL": "https://envctl-supabase.example.test",
                        "SUPABASE_ANON_KEY": "envctl-anon",
                    },
                    base_dir=repo,
                    backend_dir_name="backend",
                    frontend_dir_name="frontend",
                ),
            )

            env = dependency_external_mode(runtime, "supabase", mode="main")
            self.assertTrue(env)

            requirements = RequirementsResult(
                project="Main",
                supabase={"enabled": True, "success": True, "external": True, "runtime_status": "external"},
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
            runtime._command_override_value = lambda _key: None

            projected = project_service_env(runtime, context, requirements=requirements)

            self.assertEqual(projected["SUPABASE_URL"], "https://envctl-supabase.example.test")
            self.assertEqual(projected["SUPABASE_ANON_KEY"], "envctl-anon")

    def test_explicit_external_dependency_mode_still_applies_to_trees(self) -> None:
        runtime = SimpleNamespace(
            env={"ENVCTL_DEPENDENCY_REDIS_MODE": "external"},
            config=SimpleNamespace(
                raw={},
                startup_enabled_for_mode=lambda _mode: True,
                requirement_enabled_for_mode=lambda _mode, _name: False,
            ),
        )

        self.assertTrue(dependency_external_mode(runtime, "redis", mode="trees"))
        self.assertTrue(requirement_enabled_for_mode(runtime, "trees", "redis"))
