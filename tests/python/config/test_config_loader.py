from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.config import discover_local_config_state, load_config


class ConfigLoaderTests(unittest.TestCase):
    def test_env_overrides_envctl_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".envctl").write_text(
                'ENVCTL_DEFAULT_MODE="main"\nBACKEND_PORT_BASE=8000\n',
                encoding="utf-8",
            )

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "ENVCTL_DEFAULT_MODE": "trees",
                    "BACKEND_PORT_BASE": "8100",
                }
            )

            self.assertEqual(config.default_mode, "trees")
            self.assertEqual(config.backend_port_base, 8100)

    def test_load_config_exposes_plan_agent_pr_review_comment_followup_toggle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".envctl").write_text(
                "ENVCTL_PLAN_AGENT_PR_REVIEW_COMMENTS_ENABLE=false\n",
                encoding="utf-8",
            )

            config = load_config({"RUN_REPO_ROOT": str(repo)})

            self.assertFalse(config.plan_agent_pr_review_comments_enable)
            self.assertEqual(config.raw["ENVCTL_PLAN_AGENT_PR_REVIEW_COMMENTS_ENABLE"], "false")

    def test_load_config_exposes_plan_agent_browser_e2e_followup_toggle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".envctl").write_text(
                "ENVCTL_PLAN_AGENT_BROWSER_E2E_ENABLE=false\n",
                encoding="utf-8",
            )

            config = load_config({"RUN_REPO_ROOT": str(repo)})

            self.assertFalse(config.plan_agent_browser_e2e_enable)
            self.assertEqual(config.raw["ENVCTL_PLAN_AGENT_BROWSER_E2E_ENABLE"], "false")

    def test_load_config_exposes_plan_agent_codex_goal_default_and_false_toggle(self) -> None:
        default_config = load_config({"RUN_REPO_ROOT": tempfile.mkdtemp()})
        self.assertTrue(default_config.plan_agent_codex_goal_enable)
        self.assertEqual(default_config.raw["ENVCTL_PLAN_AGENT_CODEX_GOAL_ENABLE"], "true")

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".envctl").write_text(
                "ENVCTL_PLAN_AGENT_CODEX_GOAL_ENABLE=false\n",
                encoding="utf-8",
            )

            config = load_config({"RUN_REPO_ROOT": str(repo)})

            self.assertFalse(config.plan_agent_codex_goal_enable)
            self.assertEqual(config.raw["ENVCTL_PLAN_AGENT_CODEX_GOAL_ENABLE"], "false")

    def test_envctl_example_documents_plan_agent_codex_cycles(self) -> None:
        example = (REPO_ROOT / "docs" / "reference" / ".envctl.example").read_text(encoding="utf-8")

        self.assertIn("ENVCTL_PLAN_AGENT_CODEX_CYCLES=2", example)

    def test_envctl_sh_is_parsed_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".envctl.sh").write_text(
                'ENVCTL_DEFAULT_MODE="trees"\nMALICIOUS=$(echo no)\n',
                encoding="utf-8",
            )

            config = load_config({"RUN_REPO_ROOT": str(repo)})

            self.assertEqual(config.default_mode, "trees")
            self.assertEqual(config.raw["MALICIOUS"], "$(echo no)")

    def test_discover_local_config_state_prefers_envctl_and_tracks_legacy_prefill(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".envctl.sh").write_text("ENVCTL_DEFAULT_MODE=trees\n", encoding="utf-8")

            local_state = discover_local_config_state(repo)

            self.assertFalse(local_state.config_file_exists)
            self.assertEqual(local_state.config_source, "legacy_prefill")
            self.assertEqual(local_state.legacy_source_path, (repo / ".envctl.sh").resolve())

    def test_load_config_exposes_profiles_and_compatibility_mirrors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".envctl").write_text(
                "\n".join(
                    [
                        "ENVCTL_DEFAULT_MODE=trees",
                        "MAIN_STARTUP_ENABLE=false",
                        "MAIN_BACKEND_ENABLE=false",
                        "MAIN_FRONTEND_ENABLE=true",
                        "MAIN_POSTGRES_ENABLE=false",
                        "MAIN_REDIS_ENABLE=true",
                        "MAIN_SUPABASE_ENABLE=true",
                        "MAIN_N8N_ENABLE=true",
                        "TREES_BACKEND_ENABLE=true",
                        "TREES_FRONTEND_ENABLE=false",
                        "TREES_POSTGRES_ENABLE=true",
                        "TREES_REDIS_ENABLE=false",
                        "TREES_SUPABASE_ENABLE=false",
                        "TREES_N8N_ENABLE=true",
                        "BACKEND_PORT_BASE=8100",
                        "PORT_SPACING=7",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            config = load_config({"RUN_REPO_ROOT": str(repo)})

            self.assertEqual(config.default_mode, "trees")
            self.assertFalse(config.main_profile.startup_enable)
            self.assertFalse(config.main_profile.backend_enable)
            self.assertTrue(config.main_profile.supabase_enable)
            self.assertFalse(config.trees_profile.frontend_enable)
            self.assertEqual(config.port_defaults.backend_port_base, 8100)
            self.assertEqual(config.port_defaults.port_spacing, 7)
            self.assertFalse(config.postgres_main_enable)
            self.assertTrue(config.redis_main_enable)
            self.assertTrue(config.supabase_main_enable)
            self.assertTrue(config.n8n_main_enable)
            self.assertTrue(config.redis_enable)
            self.assertTrue(config.n8n_enable)
            self.assertFalse(config.startup_enabled_for_mode("main"))
            self.assertTrue(config.startup_enabled_for_mode("trees"))

    def test_load_config_exposes_supabase_db_and_public_api_ports(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".envctl").write_text(
                "DB_PORT=15432\nSUPABASE_PUBLIC_PORT=15421\n",
                encoding="utf-8",
            )

            config = load_config({"RUN_REPO_ROOT": str(repo)})

            self.assertEqual(config.port_defaults.dependency_port("supabase", "db"), 15432)
            self.assertEqual(config.port_defaults.dependency_port("supabase", "api"), 15421)

    def test_load_config_reads_backend_and_frontend_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".envctl").write_text(
                "BACKEND_DIR=api\nFRONTEND_DIR=web\n",
                encoding="utf-8",
            )

            config = load_config({"RUN_REPO_ROOT": str(repo)})

            self.assertEqual(config.backend_dir_name, "api")
            self.assertEqual(config.frontend_dir_name, "web")

    def test_load_config_autodetects_backend_and_frontend_dirs_when_unset(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "src").mkdir(parents=True, exist_ok=True)
            (repo / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
            frontend = repo / "frontend"
            frontend.mkdir(parents=True, exist_ok=True)
            (frontend / "package.json").write_text(
                '{"name":"demo","scripts":{"dev":"vite"}}\n',
                encoding="utf-8",
            )
            (repo / ".envctl").write_text("", encoding="utf-8")

            config = load_config({"RUN_REPO_ROOT": str(repo)})

            self.assertEqual(config.backend_dir_name, "src")
            self.assertEqual(config.frontend_dir_name, "frontend")

    def test_load_config_autodetects_backend_test_command_when_unset(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            tests_dir = repo / "tests"
            tests_dir.mkdir(parents=True, exist_ok=True)
            (tests_dir / "test_sample.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
            (repo / ".envctl").write_text("", encoding="utf-8")

            config = load_config({"RUN_REPO_ROOT": str(repo)})

            self.assertIn("ENVCTL_BACKEND_TEST_CMD", config.raw)
            self.assertEqual(config.raw["ENVCTL_BACKEND_TEST_CMD"], "")
            self.assertTrue(config.backend_test_cmd.endswith(" -m unittest discover -s tests -t . -p test_*.py"))

    def test_load_config_prefers_root_pytest_when_pytest_config_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            tests_dir = repo / "tests"
            tests_dir.mkdir(parents=True, exist_ok=True)
            (tests_dir / "test_sample.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
            (repo / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")
            (repo / ".envctl").write_text("", encoding="utf-8")

            config = load_config({"RUN_REPO_ROOT": str(repo)})

            self.assertTrue(config.backend_test_cmd.endswith(" -m pytest tests"), msg=config.backend_test_cmd)

    def test_load_config_autodetects_frontend_test_path_when_unset(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            frontend = repo / "frontend"
            src_dir = frontend / "src"
            src_dir.mkdir(parents=True, exist_ok=True)
            (frontend / "package.json").write_text(
                '{"name":"app","scripts":{"test":"vitest run"}}\n',
                encoding="utf-8",
            )
            (frontend / "bun.lockb").write_text("", encoding="utf-8")
            (src_dir / "app.test.ts").write_text("it('works', () => {})\n", encoding="utf-8")
            (repo / ".envctl").write_text("", encoding="utf-8")

            config = load_config({"RUN_REPO_ROOT": str(repo)})

            self.assertEqual(config.frontend_test_path, "frontend/src")

    def test_load_config_canonicalizes_saved_frontend_test_path_to_repo_relative(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            frontend = repo / "frontend"
            src_dir = frontend / "src"
            src_dir.mkdir(parents=True, exist_ok=True)
            (frontend / "package.json").write_text(
                '{"name":"app","scripts":{"test":"vitest run"}}\n',
                encoding="utf-8",
            )
            (frontend / "bun.lockb").write_text("", encoding="utf-8")
            (src_dir / "app.test.ts").write_text("it('works', () => {})\n", encoding="utf-8")
            (repo / ".envctl").write_text("ENVCTL_FRONTEND_TEST_PATH=src\n", encoding="utf-8")

            config = load_config({"RUN_REPO_ROOT": str(repo)})

            self.assertEqual(config.frontend_test_path, "frontend/src")

    def test_load_config_uses_managed_dependency_baseline_when_envctl_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".envctl").write_text(
                "\n".join(
                    [
                        "ENVCTL_DEFAULT_MODE=main",
                        "BACKEND_DIR=src",
                        "ENVCTL_BACKEND_START_CMD=python main.py",
                        "MAIN_FRONTEND_ENABLE=false",
                        "TREES_STARTUP_ENABLE=false",
                        "TREES_FRONTEND_ENABLE=false",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            config = load_config({"RUN_REPO_ROOT": str(repo)})

            self.assertFalse(config.main_profile.postgres_enable)
            self.assertFalse(config.main_profile.redis_enable)
            self.assertFalse(config.main_profile.supabase_enable)
            self.assertFalse(config.main_profile.n8n_enable)
            self.assertFalse(config.trees_profile.postgres_enable)
            self.assertFalse(config.trees_profile.redis_enable)
            self.assertFalse(config.trees_profile.supabase_enable)
            self.assertFalse(config.trees_profile.n8n_enable)
            self.assertFalse(config.postgres_main_enable)
            self.assertFalse(config.redis_main_enable)
            self.assertFalse(config.redis_enable)
            self.assertFalse(config.n8n_main_enable)
            self.assertFalse(config.n8n_enable)

    def test_load_config_infers_core_dynamic_dependencies_from_backend_launch_env_templates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".envctl").write_text(
                "\n".join(
                    [
                        "# >>> envctl managed startup config >>>",
                        "ENVCTL_DEFAULT_MODE=main",
                        "ENVCTL_BACKEND_START_CMD=python -m uvicorn app.main:app --port {port}",
                        "MAIN_FRONTEND_ENABLE=false",
                        "# <<< envctl managed startup config <<<",
                        "",
                        "# >>> envctl backend launch env >>>",
                        "DATABASE_URL=${ENVCTL_SOURCE_DATABASE_URL}",
                        "REDIS_URL=${ENVCTL_SOURCE_REDIS_URL}",
                        "N8N_URL=${ENVCTL_SOURCE_N8N_URL}",
                        "SUPABASE_URL=${ENVCTL_SOURCE_SUPABASE_URL}",
                        "# <<< envctl backend launch env <<<",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            config = load_config({"RUN_REPO_ROOT": str(repo)})

            self.assertTrue(config.main_profile.postgres_enable)
            self.assertTrue(config.main_profile.redis_enable)
            self.assertFalse(config.main_profile.n8n_enable)
            self.assertFalse(config.main_profile.supabase_enable)
            self.assertTrue(config.trees_profile.postgres_enable)
            self.assertTrue(config.trees_profile.redis_enable)
            self.assertFalse(config.trees_profile.n8n_enable)
            self.assertFalse(config.trees_profile.supabase_enable)

    def test_load_config_does_not_infer_dynamic_dependencies_when_toggles_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".envctl").write_text(
                "\n".join(
                    [
                        "# >>> envctl managed startup config >>>",
                        "ENVCTL_DEFAULT_MODE=main",
                        "MAIN_POSTGRES_ENABLE=false",
                        "MAIN_REDIS_ENABLE=false",
                        "TREES_POSTGRES_ENABLE=false",
                        "TREES_REDIS_ENABLE=false",
                        "# <<< envctl managed startup config <<<",
                        "",
                        "# >>> envctl backend launch env >>>",
                        "DATABASE_URL=${ENVCTL_SOURCE_DATABASE_URL}",
                        "REDIS_URL=${ENVCTL_SOURCE_REDIS_URL}",
                        "# <<< envctl backend launch env <<<",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            config = load_config({"RUN_REPO_ROOT": str(repo)})

            self.assertFalse(config.main_profile.postgres_enable)
            self.assertFalse(config.main_profile.redis_enable)
            self.assertFalse(config.trees_profile.postgres_enable)
            self.assertFalse(config.trees_profile.redis_enable)

    def test_load_config_parses_mode_specific_launch_env_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".envctl").write_text(
                "\n".join(
                    [
                        "# >>> envctl managed startup config >>>",
                        "ENVCTL_DEFAULT_MODE=trees",
                        "MAIN_POSTGRES_ENABLE=true",
                        "TREES_SUPABASE_ENABLE=true",
                        "# <<< envctl managed startup config <<<",
                        "",
                        "# >>> envctl main frontend launch env >>>",
                        "VITE_SUPABASE_URL=http://main.example.test:54321",
                        "# <<< envctl main frontend launch env <<<",
                        "",
                        "# >>> envctl trees frontend launch env >>>",
                        "VITE_SUPABASE_URL=${ENVCTL_SOURCE_SUPABASE_URL}",
                        "# <<< envctl trees frontend launch env <<<",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            config = load_config({"RUN_REPO_ROOT": str(repo)})

            self.assertTrue(config.main_frontend_dependency_env_section_present)
            self.assertTrue(config.trees_frontend_dependency_env_section_present)
            self.assertEqual(config.main_frontend_dependency_env_templates[0].name, "VITE_SUPABASE_URL")
            self.assertEqual(
                config.trees_frontend_dependency_env_templates[0].template,
                "${ENVCTL_SOURCE_SUPABASE_URL}",
            )


    def test_load_config_parses_additional_service_enable_if_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            config_file = repo / ".envctl"
            config_file.write_text(
                "\n".join(
                    [
                        "ENVCTL_ADDITIONAL_SERVICES=voice-runtime",
                        "ENVCTL_SERVICE_VOICE_RUNTIME_DIR=voice-runtime",
                        "ENVCTL_SERVICE_VOICE_RUNTIME_START_CMD=scripts/envctl/start-voice-runtime.sh {port}",
                        "ENVCTL_SERVICE_VOICE_RUNTIME_PORT_BASE=8010",
                        "ENVCTL_SERVICE_VOICE_RUNTIME_ENABLE_IF_PATH=voice-runtime/app/main.py",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            config = load_config({"RUN_REPO_ROOT": str(repo)})

            self.assertEqual(len(config.additional_services), 1)
            self.assertEqual(config.additional_services[0].enable_if_path, "voice-runtime/app/main.py")

    def test_load_config_parses_additional_services_and_generic_launch_env_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".envctl").write_text(
                "\n".join(
                    [
                        "ENVCTL_ADDITIONAL_SERVICES=voice-runtime,worker",
                        "ENVCTL_SERVICE_VOICE_RUNTIME_ENABLE=true",
                        "ENVCTL_SERVICE_VOICE_RUNTIME_DIR=voice-runtime",
                        "ENVCTL_SERVICE_VOICE_RUNTIME_PORT_BASE=8010",
                        "ENVCTL_SERVICE_VOICE_RUNTIME_START_CMD=scripts/start-voice.sh {port}",
                        "ENVCTL_SERVICE_VOICE_RUNTIME_HEALTH_URL=http://${ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_HOST}:${ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_PORT}/readyz",
                        "ENVCTL_SERVICE_WORKER_ENABLE=true",
                        "ENVCTL_SERVICE_WORKER_DIR=backend",
                        "ENVCTL_SERVICE_WORKER_START_CMD=python -m app.worker",
                        "ENVCTL_SERVICE_WORKER_EXPECT_LISTENER=false",
                        "ENVCTL_SERVICE_WORKER_TEST_CMD=python -m pytest tests/test_worker.py",
                        "",
                        "# >>> envctl service voice-runtime launch env >>>",
                        "VOICE_RUNTIME_PUBLIC_URL=${ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_PUBLIC_URL}",
                        "# <<< envctl service voice-runtime launch env <<<",
                        "",
                        "# >>> envctl main service voice-runtime launch env >>>",
                        "PELE_API_BASE_URL=${ENVCTL_SOURCE_BACKEND_URL}",
                        "# <<< envctl main service voice-runtime launch env <<<",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            config = load_config({"RUN_REPO_ROOT": str(repo)})

            self.assertEqual([service.name for service in config.additional_services], ["voice-runtime", "worker"])
            voice = config.app_service_by_name("voice-runtime")
            worker = config.app_service_by_name("worker")
            self.assertIsNotNone(voice)
            self.assertIsNotNone(worker)
            assert voice is not None
            assert worker is not None
            self.assertEqual(voice.env_suffix, "VOICE_RUNTIME")
            self.assertEqual(voice.dir_name, "voice-runtime")
            self.assertEqual(voice.port_base, 8010)
            self.assertTrue(voice.expect_listener)
            self.assertEqual(worker.test_cmd, "python -m pytest tests/test_worker.py")
            self.assertFalse(worker.expect_listener)
            self.assertTrue(config.service_enabled_for_mode("main", "voice-runtime"))
            self.assertTrue(config.service_enabled_for_mode("trees", "worker"))
            self.assertEqual(config.all_app_service_names_for_mode("main"), ("backend", "frontend", "voice-runtime", "worker"))
            self.assertTrue(config.service_dependency_env_section_present["voice-runtime"])
            self.assertEqual(config.service_dependency_env_templates["voice-runtime"][0].name, "VOICE_RUNTIME_PUBLIC_URL")
            self.assertTrue(config.mode_service_dependency_env_section_present[("main", "voice-runtime")])
            self.assertEqual(
                config.mode_service_dependency_env_templates[("main", "voice-runtime")][0].template,
                "${ENVCTL_SOURCE_BACKEND_URL}",
            )

    def test_load_config_rejects_invalid_additional_service_definitions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".envctl").write_text(
                "\n".join(
                    [
                        "ENVCTL_ADDITIONAL_SERVICES=backend,bad_name,listener",
                        "ENVCTL_SERVICE_LISTENER_ENABLE=true",
                        "ENVCTL_SERVICE_LISTENER_START_CMD=python listener.py {port}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            config = load_config({"RUN_REPO_ROOT": str(repo)})

            self.assertEqual(config.additional_services, ())
            self.assertIn("reserved service name 'backend'", "\n".join(config.additional_service_errors))
            self.assertIn("invalid service slug 'bad_name'", "\n".join(config.additional_service_errors))
            self.assertIn("listener service 'listener' requires ENVCTL_SERVICE_LISTENER_PORT_BASE", "\n".join(config.additional_service_errors))

    def test_load_config_reports_unknown_and_cyclic_additional_service_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".envctl").write_text(
                "\n".join(
                    [
                        "ENVCTL_ADDITIONAL_SERVICES=voice-runtime,relay,worker",
                        "ENVCTL_SERVICE_VOICE_RUNTIME_PORT_BASE=8010",
                        "ENVCTL_SERVICE_VOICE_RUNTIME_START_CMD=python voice.py {port}",
                        "ENVCTL_SERVICE_VOICE_RUNTIME_DEPENDS_ON=backend,missing-service",
                        "ENVCTL_SERVICE_RELAY_PORT_BASE=8020",
                        "ENVCTL_SERVICE_RELAY_START_CMD=python relay.py {port}",
                        "ENVCTL_SERVICE_RELAY_DEPENDS_ON=worker",
                        "ENVCTL_SERVICE_WORKER_EXPECT_LISTENER=false",
                        "ENVCTL_SERVICE_WORKER_START_CMD=python worker.py",
                        "ENVCTL_SERVICE_WORKER_DEPENDS_ON=relay",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            config = load_config({"RUN_REPO_ROOT": str(repo)})

            errors = "\n".join(config.additional_service_errors)
            self.assertIn("service 'voice-runtime' depends on unknown service or dependency 'missing-service'", errors)
            self.assertIn("additional service dependency cycle", errors)
            self.assertEqual(config.additional_services, ())

    def test_load_config_allows_known_dependency_references_and_noncritical_services(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".envctl").write_text(
                "\n".join(
                    [
                        "ENVCTL_ADDITIONAL_SERVICES=voice-runtime,worker",
                        "ENVCTL_SERVICE_VOICE_RUNTIME_PORT_BASE=8010",
                        "ENVCTL_SERVICE_VOICE_RUNTIME_START_CMD=python voice.py {port}",
                        "ENVCTL_SERVICE_VOICE_RUNTIME_DEPENDS_ON=backend,redis,worker",
                        "ENVCTL_SERVICE_VOICE_RUNTIME_CRITICAL=false",
                        "ENVCTL_SERVICE_WORKER_EXPECT_LISTENER=false",
                        "ENVCTL_SERVICE_WORKER_START_CMD=python worker.py",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            config = load_config({"RUN_REPO_ROOT": str(repo)})

            self.assertEqual(config.additional_service_errors, ())
            voice = config.app_service_by_name("voice-runtime")
            self.assertIsNotNone(voice)
            assert voice is not None
            self.assertEqual(voice.depends_on, ("backend", "redis", "worker"))
            self.assertFalse(voice.critical)


if __name__ == "__main__":
    unittest.main()
