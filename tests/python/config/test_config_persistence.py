from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.config import (
    CONFIG_BACKEND_DEPENDENCY_ENV_END,
    CONFIG_BACKEND_DEPENDENCY_ENV_START,
    CONFIG_DEPENDENCY_ENV_END,
    CONFIG_DEPENDENCY_ENV_START,
    CONFIG_FRONTEND_DEPENDENCY_ENV_END,
    CONFIG_FRONTEND_DEPENDENCY_ENV_START,
    DEFAULTS,
    LocalConfigState,
    PortDefaults,
    StartupProfile,
    _parse_envctl_text,
    ensure_dependency_env_section,
    parse_dependency_env_section,
    render_default_dependency_env_section,
)
from envctl_engine.config.persistence import (
    ManagedConfigValues,
    ensure_local_config_ignored,
    managed_values_from_mapping,
    managed_values_to_mapping,
    merge_managed_block,
    render_managed_block,
    save_local_config,
)


class ConfigPersistenceTests(unittest.TestCase):
    def test_merge_managed_block_preserves_unknown_lines(self) -> None:
        values = ManagedConfigValues(
            default_mode="trees",
            main_profile=StartupProfile(False, True, False, False, False, False, False),
            trees_profile=StartupProfile(False, True, False, False, False, False, False),
            port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
            backend_dir_name=".",
            backend_start_cmd="python src/main.py",
        )
        existing = "FOO=bar\n# comment\n\nBAR=baz\n"

        merged = merge_managed_block(existing, render_managed_block(values))

        self.assertIn("FOO=bar", merged)
        self.assertIn("BAR=baz", merged)
        self.assertIn("# >>> envctl managed startup config >>>", merged)
        self.assertIn("ENVCTL_DEFAULT_MODE=trees", merged)
        self.assertIn("BACKEND_DIR=.", merged)
        self.assertIn("MAIN_STARTUP_ENABLE=false", merged)
        self.assertIn("MAIN_FRONTEND_ENABLE=false", merged)
        self.assertNotIn("FRONTEND_DIR=frontend", merged)
        self.assertNotIn("BACKEND_PORT_BASE=8000", merged)

    def test_save_local_config_rewrites_only_managed_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            path = repo / ".envctl"
            path.write_text(
                "FOO=bar\n# >>> envctl managed startup config >>>\nENVCTL_DEFAULT_MODE=main\n# <<< envctl managed startup config <<<\nBAR=baz\n",
                encoding="utf-8",
            )
            local_state = LocalConfigState(
                base_dir=repo,
                config_file_path=path,
                config_file_exists=True,
                config_source="envctl",
                active_source_path=path,
                legacy_source_path=None,
                explicit_path=None,
                parsed_values={},
                file_text=path.read_text(encoding="utf-8"),
            )
            values = ManagedConfigValues(
                default_mode="trees",
                main_profile=StartupProfile(True, True, False, True, True, False, False),
                trees_profile=StartupProfile(True, True, True, True, False, False, True),
                port_defaults=PortDefaults(8100, 9100, 5434, 6381, 5680, 11),
                backend_start_cmd="python src/main.py",
                frontend_start_cmd="npm run dev -- --port 0 --host",
                backend_test_cmd="python -m unittest discover -s tests -t . -p test_*.py",
                frontend_test_cmd="pnpm run test",
                frontend_test_path="src",
            )

            result = save_local_config(local_state=local_state, values=values)
            written = path.read_text(encoding="utf-8")

            self.assertEqual(result.path, path)
            self.assertIn("FOO=bar", written)
            self.assertIn("BAR=baz", written)
            self.assertIn("ENVCTL_DEFAULT_MODE=trees", written)
            self.assertNotIn("BACKEND_DIR=backend", written)
            self.assertNotIn("FRONTEND_DIR=frontend", written)
            self.assertIn("ENVCTL_BACKEND_START_CMD=python src/main.py", written)
            self.assertIn("ENVCTL_FRONTEND_START_CMD=npm run dev -- --port 0 --host", written)
            self.assertIn("ENVCTL_BACKEND_TEST_CMD=python -m unittest discover -s tests -t . -p test_*.py", written)
            self.assertIn("ENVCTL_FRONTEND_TEST_CMD=pnpm run test", written)
            self.assertIn("ENVCTL_FRONTEND_TEST_PATH=frontend/src", written)
            self.assertIn("BACKEND_PORT_BASE=8100", written)
            self.assertIn("FRONTEND_PORT_BASE=9100", written)
            self.assertIn("DB_PORT=5434", written)
            self.assertIn("REDIS_PORT=6381", written)
            self.assertIn("N8N_PORT_BASE=5680", written)
            self.assertIn("PORT_SPACING=11", written)
            self.assertNotIn("MAIN_STARTUP_ENABLE=true", written)
            self.assertIn("MAIN_FRONTEND_ENABLE=false", written)
            self.assertNotIn("ENVCTL_DEFAULT_MODE=main", written)
            self.assertIn(CONFIG_BACKEND_DEPENDENCY_ENV_START, written)
            self.assertIn(CONFIG_FRONTEND_DEPENDENCY_ENV_START, written)
            self.assertIn("DATABASE_URL=${ENVCTL_SOURCE_DATABASE_URL}", written)
            self.assertIn("SQLAlchemy async URL", written)
            self.assertNotIn(CONFIG_DEPENDENCY_ENV_START, written)

    def test_save_local_config_preserves_dependency_env_section_verbatim(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            path = repo / ".envctl"
            dependency_section = (
                "# >>> envctl dependency env >>>\n"
                "# keep this comment\n"
                "APP_DATABASE_URL=${ENVCTL_SOURCE_DATABASE_URL}?sslmode=disable\n"
                "\n"
                "WORKFLOW_BASE_URL=${ENVCTL_SOURCE_N8N_URL}\n"
                "# <<< envctl dependency env <<<\n"
            )
            path.write_text(
                "FOO=bar\n"
                "# >>> envctl managed startup config >>>\n"
                "ENVCTL_DEFAULT_MODE=main\n"
                "# <<< envctl managed startup config <<<\n\n"
                + dependency_section,
                encoding="utf-8",
            )
            local_state = LocalConfigState(
                base_dir=repo,
                config_file_path=path,
                config_file_exists=True,
                config_source="envctl",
                active_source_path=path,
                legacy_source_path=None,
                explicit_path=None,
                parsed_values={},
                file_text=path.read_text(encoding="utf-8"),
            )
            values = ManagedConfigValues(
                default_mode="trees",
                main_profile=StartupProfile(True, True, False, True, True, False, False),
                trees_profile=StartupProfile(True, True, True, True, False, False, True),
                port_defaults=PortDefaults(8100, 9100, 5434, 6381, 5680, 11),
                backend_start_cmd="python src/main.py",
                frontend_start_cmd="npm run dev -- --port 0 --host",
            )

            save_local_config(local_state=local_state, values=values)

            written = path.read_text(encoding="utf-8")
            self.assertIn(dependency_section, written)

    def test_save_local_config_preserves_service_scoped_dependency_sections_without_injecting_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            path = repo / ".envctl"
            backend_section = (
                f"{CONFIG_BACKEND_DEPENDENCY_ENV_START}\n"
                "APP_DATABASE_URL=${ENVCTL_SOURCE_DATABASE_URL}\n"
                f"{CONFIG_BACKEND_DEPENDENCY_ENV_END}\n"
            )
            path.write_text(
                "FOO=bar\n"
                "# >>> envctl managed startup config >>>\n"
                "ENVCTL_DEFAULT_MODE=main\n"
                "# <<< envctl managed startup config <<<\n\n"
                + backend_section,
                encoding="utf-8",
            )
            local_state = LocalConfigState(
                base_dir=repo,
                config_file_path=path,
                config_file_exists=True,
                config_source="envctl",
                active_source_path=path,
                legacy_source_path=None,
                explicit_path=None,
                parsed_values={},
                file_text=path.read_text(encoding="utf-8"),
            )
            values = ManagedConfigValues(
                default_mode="trees",
                main_profile=StartupProfile(True, True, False, True, True, False, False),
                trees_profile=StartupProfile(True, True, True, True, False, False, True),
                port_defaults=PortDefaults(8100, 9100, 5434, 6381, 5680, 11),
                backend_start_cmd="python src/main.py",
                frontend_start_cmd="npm run dev -- --port 0 --host",
            )

            save_local_config(local_state=local_state, values=values)

            written = path.read_text(encoding="utf-8")
            self.assertIn(backend_section, written)
            self.assertNotIn(CONFIG_DEPENDENCY_ENV_START, written)
            self.assertNotIn(CONFIG_FRONTEND_DEPENDENCY_ENV_START, written)

    def test_render_managed_block_omits_irrelevant_default_entries(self) -> None:
        values = ManagedConfigValues(
            default_mode="trees",
            main_profile=StartupProfile(False, True, False, False, False, False, False),
            trees_profile=StartupProfile(False, True, False, False, False, False, False),
            port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
            backend_dir_name=".",
            backend_start_cmd="python src/main.py",
            backend_test_cmd="python -m unittest discover -s tests -t . -p test_*.py",
        )

        rendered = render_managed_block(values)

        self.assertIn("ENVCTL_DEFAULT_MODE=trees", rendered)
        self.assertIn("BACKEND_DIR=.", rendered)
        self.assertIn("ENVCTL_BACKEND_TEST_CMD=python -m unittest discover -s tests -t . -p test_*.py", rendered)
        self.assertIn("MAIN_STARTUP_ENABLE=false", rendered)
        self.assertIn("TREES_STARTUP_ENABLE=false", rendered)
        self.assertIn("MAIN_FRONTEND_ENABLE=false", rendered)
        self.assertIn("TREES_FRONTEND_ENABLE=false", rendered)
        self.assertNotIn("MAIN_POSTGRES_ENABLE=false", rendered)
        self.assertNotIn("TREES_POSTGRES_ENABLE=false", rendered)
        self.assertNotIn("FRONTEND_DIR=frontend", rendered)
        self.assertNotIn("ENVCTL_FRONTEND_START_CMD=", rendered)
        self.assertNotIn("BACKEND_PORT_BASE=8000", rendered)
        self.assertNotIn("PORT_SPACING=20", rendered)
        self.assertNotIn("MAIN_BACKEND_ENABLE=true", rendered)
        self.assertNotIn("TREES_BACKEND_ENABLE=true", rendered)

    def test_render_managed_block_includes_backend_listener_expectation_when_disabled(self) -> None:
        values = ManagedConfigValues(
            default_mode="main",
            main_profile=StartupProfile(True, True, False, False, False, False, False),
            trees_profile=StartupProfile(False, False, False, False, False, False, False),
            port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
            main_backend_expect_listener=False,
            backend_start_cmd="python worker.py",
        )

        rendered = render_managed_block(values)

        self.assertIn("MAIN_BACKEND_EXPECT_LISTENER=false", rendered)
        self.assertNotIn("BACKEND_PORT_BASE=8000", rendered)

    def test_validation_allows_zero_components_when_startup_disabled(self) -> None:
        values = ManagedConfigValues(
            default_mode="main",
            main_profile=StartupProfile(False, False, False, False, False, False, False),
            trees_profile=StartupProfile(True, True, True, True, True, False, True),
            port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
            backend_start_cmd="python src/main.py",
            frontend_start_cmd="npm run dev -- --port 0 --host",
        )

        from envctl_engine.config.persistence import validate_managed_values

        validation = validate_managed_values(values)

        self.assertTrue(validation.valid)

    def test_validation_can_defer_entrypoint_requirements(self) -> None:
        values = ManagedConfigValues(
            default_mode="main",
            main_profile=StartupProfile(True, True, True, False, False, False, False),
            trees_profile=StartupProfile(False, False, False, False, False, False, False),
            port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
            backend_dir_name="",
            frontend_dir_name="",
            backend_start_cmd="",
            frontend_start_cmd="",
        )

        from envctl_engine.config.persistence import validate_managed_values

        deferred = validate_managed_values(values, require_directories=False, require_entrypoints=False)
        strict = validate_managed_values(values)

        self.assertTrue(deferred.valid)
        self.assertIn("Backend directory must not be empty.", strict.errors)
        self.assertIn("Frontend directory must not be empty.", strict.errors)
        self.assertIn("Backend entrypoint must not be empty.", strict.errors)

    def test_validation_does_not_require_entrypoint_for_non_running_backend(self) -> None:
        values = ManagedConfigValues(
            default_mode="main",
            main_profile=StartupProfile(False, True, False, False, False, False, False),
            trees_profile=StartupProfile(False, True, False, False, False, False, False),
            port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
            backend_start_cmd="",
            frontend_start_cmd="",
        )

        from envctl_engine.config.persistence import validate_managed_values

        validation = validate_managed_values(values)

        self.assertTrue(validation.valid)

    def test_empty_mapping_defaults_to_no_requirements_selected(self) -> None:
        values = managed_values_from_mapping({})

        self.assertFalse(values.main_profile.postgres_enable)
        self.assertFalse(values.main_profile.redis_enable)
        self.assertFalse(values.main_profile.supabase_enable)
        self.assertFalse(values.main_profile.n8n_enable)
        self.assertFalse(values.trees_profile.postgres_enable)
        self.assertFalse(values.trees_profile.redis_enable)
        self.assertFalse(values.trees_profile.supabase_enable)
        self.assertFalse(values.trees_profile.n8n_enable)

    def test_reference_envctl_example_matches_current_defaults(self) -> None:
        example_path = REPO_ROOT / "docs" / "reference" / ".envctl.example"
        example_values = _parse_envctl_text(example_path.read_text(encoding="utf-8"))
        expected_managed = managed_values_from_mapping(DEFAULTS)
        expected_mapping = managed_values_to_mapping(expected_managed)

        self.assertEqual(example_values["ENVCTL_PLANNING_DIR"], DEFAULTS["ENVCTL_PLANNING_DIR"])
        for key, value in expected_mapping.items():
            if key in {
                "ENVCTL_BACKEND_START_CMD",
                "ENVCTL_FRONTEND_START_CMD",
                "ENVCTL_BACKEND_TEST_CMD",
                "ENVCTL_FRONTEND_TEST_CMD",
                "ENVCTL_FRONTEND_TEST_PATH",
            } and value == "":
                continue
            self.assertEqual(example_values.get(key), value, msg=key)
        example_text = example_path.read_text(encoding="utf-8")
        self.assertIn(CONFIG_BACKEND_DEPENDENCY_ENV_START, example_text)
        self.assertIn(CONFIG_FRONTEND_DEPENDENCY_ENV_START, example_text)
        self.assertIn("generic DB URL; e.g. postgresql://user:pass@host:5432/dbname", example_text)
        self.assertIn("SQLAlchemy async URL; e.g. postgresql+asyncpg://user:pass@host:5432/dbname", example_text)
        self.assertNotIn(CONFIG_DEPENDENCY_ENV_START, example_text)
        self.assertIn(CONFIG_BACKEND_DEPENDENCY_ENV_END, example_text)
        self.assertIn(CONFIG_FRONTEND_DEPENDENCY_ENV_END, example_text)

    def test_managed_values_from_mapping_canonicalizes_frontend_test_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "frontend" / "src").mkdir(parents=True, exist_ok=True)

            values = managed_values_from_mapping(
                {
                    "FRONTEND_DIR": "frontend",
                    "ENVCTL_FRONTEND_TEST_PATH": "src",
                },
                base_dir=repo,
            )

            self.assertEqual(values.frontend_test_path, "frontend/src")

    def test_parse_dependency_env_section_reads_entries_and_line_numbers(self) -> None:
        text = (
            "ENVCTL_DEFAULT_MODE=main\n"
            f"{CONFIG_DEPENDENCY_ENV_START}\n"
            "# comment\n"
            "DATABASE_URL=${ENVCTL_SOURCE_DATABASE_URL}  # generic DB URL\n"
            "APP_DATABASE_URL=${DATABASE_URL}?sslmode=disable\n"
            f"{CONFIG_DEPENDENCY_ENV_END}\n"
        )

        entries = parse_dependency_env_section(text)

        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].name, "DATABASE_URL")
        self.assertEqual(entries[0].line_number, 4)
        self.assertEqual(entries[1].name, "APP_DATABASE_URL")
        self.assertEqual(entries[1].line_number, 5)

    def test_parse_dependency_env_section_rejects_invalid_lines(self) -> None:
        text = (
            f"{CONFIG_DEPENDENCY_ENV_START}\n"
            "NOT_VALID\n"
            f"{CONFIG_DEPENDENCY_ENV_END}\n"
        )

        with self.assertRaisesRegex(ValueError, "line 2"):
            parse_dependency_env_section(text)

    def test_parse_dependency_env_section_rejects_missing_marker_pair(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing closing marker"):
            parse_dependency_env_section(f"{CONFIG_DEPENDENCY_ENV_START}\nDATABASE_URL=x\n")

    def test_parse_dependency_env_section_accepts_legacy_markers(self) -> None:
        text = (
            "# >>> envctl dependency env >>>\n"
            "DATABASE_URL=${ENVCTL_SOURCE_DATABASE_URL}\n"
            "# <<< envctl dependency env <<<\n"
        )

        entries = parse_dependency_env_section(text)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].name, "DATABASE_URL")

    def test_ensure_dependency_env_section_seeds_defaults_once(self) -> None:
        seeded = ensure_dependency_env_section("# existing\n")

        self.assertIn(CONFIG_BACKEND_DEPENDENCY_ENV_START, seeded)
        self.assertIn(CONFIG_FRONTEND_DEPENDENCY_ENV_START, seeded)
        self.assertNotIn(CONFIG_DEPENDENCY_ENV_START, seeded)
        self.assertEqual(ensure_dependency_env_section(seeded), seeded)

    def test_ensure_dependency_env_section_upgrades_legacy_default_boilerplate(self) -> None:
        legacy = (
            "# The shared section below applies to both backend and frontend launches.\n"
            "# The backend/frontend sections below it are service-specific.\n"
            "# For a given service, envctl emits only the vars defined in the sections that apply to that service.\n\n"
            "# >>> envctl dependency env >>>\n"
            "# Primary database connection string for apps that expect a generic DB URL.\n"
            "# Usually looks like: postgresql://user:pass@host:5432/dbname\n"
            "DATABASE_URL=${ENVCTL_SOURCE_DATABASE_URL}\n"
            "# Redis connection string for cache, queues, and pub/sub clients.\n"
            "# Usually looks like: redis://host:6379/0\n"
            "REDIS_URL=${ENVCTL_SOURCE_REDIS_URL}\n"
            "# Base HTTP URL for your local n8n instance.\n"
            "# Usually looks like: http://localhost:5678\n"
            "N8N_URL=${ENVCTL_SOURCE_N8N_URL}\n"
            "# Base HTTP URL for local Supabase APIs and Studio integrations.\n"
            "# Usually looks like: http://localhost:54321\n"
            "SUPABASE_URL=${ENVCTL_SOURCE_SUPABASE_URL}\n"
            "# SQLAlchemy sync driver URL, commonly used by sync app/database layers.\n"
            "# Usually looks like: postgresql+psycopg://user:pass@host:5432/dbname\n"
            "SQLALCHEMY_DATABASE_URL=${ENVCTL_SOURCE_SQLALCHEMY_DATABASE_URL}\n"
            "# SQLAlchemy async driver URL, commonly used by async Python services.\n"
            "# Usually looks like: postgresql+asyncpg://user:pass@host:5432/dbname\n"
            "ASYNC_DATABASE_URL=${ENVCTL_SOURCE_ASYNC_DATABASE_URL}\n"
            "# <<< envctl dependency env <<<\n\n"
            "# >>> envctl backend dependency env >>>\n"
            "# Add backend-only dependency aliases/templates here.\n"
            "# Example:\n"
            "# APP_DATABASE_URL=${ENVCTL_SOURCE_DATABASE_URL}\n"
            "# <<< envctl backend dependency env <<<\n\n"
            "# >>> envctl frontend dependency env >>>\n"
            "# Add frontend-only dependency aliases/templates here.\n"
            "# Example:\n"
            "# VITE_SUPABASE_URL=${ENVCTL_SOURCE_SUPABASE_URL}\n"
            "# <<< envctl frontend dependency env <<<\n"
        )

        upgraded = ensure_dependency_env_section(legacy)

        self.assertIn(CONFIG_BACKEND_DEPENDENCY_ENV_START, upgraded)
        self.assertIn(CONFIG_FRONTEND_DEPENDENCY_ENV_START, upgraded)
        self.assertNotIn("# >>> envctl dependency env >>>", upgraded)
        self.assertNotIn("The shared section below applies to both backend and frontend launches.", upgraded)
        self.assertIn("DATABASE_URL=${ENVCTL_SOURCE_DATABASE_URL}", upgraded)

    def test_ignore_local_config_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".git" / "info").mkdir(parents=True, exist_ok=True)

            updated_first, warning_first = ensure_local_config_ignored(repo)
            updated_second, warning_second = ensure_local_config_ignored(repo)
            exclude_text = (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")
            gitignore_text = (repo / ".gitignore").read_text(encoding="utf-8")
            exclude_lines = exclude_text.splitlines()
            gitignore_lines = gitignore_text.splitlines()

            self.assertTrue(updated_first)
            self.assertIsNone(warning_first)
            self.assertFalse(updated_second)
            self.assertIsNone(warning_second)
            self.assertEqual(exclude_lines.count(".envctl*"), 1)
            self.assertEqual(gitignore_lines.count(".envctl*"), 1)
            self.assertEqual(gitignore_lines.count("trees/"), 1)
            self.assertEqual(gitignore_lines.count("MAIN_TASK.md"), 1)

    def test_ignore_local_config_does_not_duplicate_existing_gitignore_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".git" / "info").mkdir(parents=True, exist_ok=True)
            (repo / ".gitignore").write_text(".envctl*\ntrees/\nMAIN_TASK.md\n", encoding="utf-8")

            updated, warning = ensure_local_config_ignored(repo)

            gitignore_text = (repo / ".gitignore").read_text(encoding="utf-8")
            exclude_text = (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")
            exclude_lines = exclude_text.splitlines()

            self.assertTrue(updated)
            self.assertIsNone(warning)
            self.assertEqual(gitignore_text, ".envctl*\ntrees/\nMAIN_TASK.md\n")
            self.assertEqual(exclude_lines.count(".envctl*"), 1)


if __name__ == "__main__":
    unittest.main()
