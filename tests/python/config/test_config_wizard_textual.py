from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parents[3]
from envctl_engine.config import AppServiceConfig, PortDefaults, StartupProfile, discover_local_config_state
from envctl_engine.config.persistence import ManagedConfigValues, config_review_text, managed_values_to_mapping
from envctl_engine.ui.textual.screens.config_wizard import (
    _additional_service_input_id,
    _directory_validation_message,
    _hydrate_wizard_values,
    _visible_command_fields,
    _visible_directory_fields,
    _visible_port_fields,
    run_config_wizard_textual,
)
from envctl_engine.ui.textual.screens.config_wizard_fields import build_additional_service_from_input_values


class ConfigWizardTextualTests(unittest.TestCase):
    def test_review_text_references_global_git_excludes_instead_of_repo_gitignore(self) -> None:
        values = ManagedConfigValues(
            default_mode="main",
            main_profile=StartupProfile(True, True, True, False, False, False, False),
            trees_profile=StartupProfile(True, True, True, False, False, False, False),
            port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
        )

        review = config_review_text(
            path=Path("/tmp/repo/.envctl"),
            values=values,
            source_label="defaults",
            ignore_warning="envctl local artifacts are managed through Git global excludes.",
        )

        self.assertIn("Git global excludes", review)
        self.assertNotIn(".gitignore on save", review)

    def test_build_only_flow_has_expected_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            local_state = discover_local_config_state(repo)
            app = run_config_wizard_textual(local_state=local_state, build_only=True)
            if app is None:
                self.skipTest("Textual is not available in this environment")
            app = cast(Any, app)
            self.assertEqual(  # noqa: SLF001
                getattr(app, "_steps"),
                ["welcome", "default_mode", "components", "directories", "commands", "ports", "review"],
            )

    def test_build_only_flow_includes_service_startup_for_backend_only_projects(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            local_state = discover_local_config_state(repo)
            values = ManagedConfigValues(
                default_mode="main",
                main_profile=StartupProfile(True, True, False, False, False, False, False),
                trees_profile=StartupProfile(True, True, False, False, False, False, False),
                port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
            )
            app = run_config_wizard_textual(local_state=local_state, initial_values=values, build_only=True)
            if app is None:
                self.skipTest("Textual is not available in this environment")
            app = cast(object, app)
            self.assertEqual(  # noqa: SLF001
                getattr(app, "_steps"),
                [
                    "welcome",
                    "default_mode",
                    "components",
                    "service_startup",
                    "directories",
                    "commands",
                    "ports",
                    "review",
                ],
            )


    def test_build_only_flow_includes_additional_services_step_when_services_are_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            local_state = discover_local_config_state(repo)
            values = ManagedConfigValues(
                default_mode="main",
                main_profile=StartupProfile(True, True, True, False, False, False, False),
                trees_profile=StartupProfile(True, True, True, False, False, False, False),
                port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
                additional_services=(
                    AppServiceConfig(
                        name="voice-runtime",
                        env_suffix="VOICE_RUNTIME",
                        enabled_main=True,
                        enabled_trees=False,
                        dir_name="voice-runtime",
                        start_cmd="python -m voice_runtime --port {port}",
                        port_base=8010,
                        depends_on=("backend",),
                        critical=False,
                    ),
                ),
            )
            app = run_config_wizard_textual(local_state=local_state, initial_values=values, build_only=True)
            if app is None:
                self.skipTest("Textual is not available in this environment")
            app = cast(Any, app)
            self.assertIn("additional_services", getattr(app, "_steps"))  # noqa: SLF001
            self.assertLess(  # noqa: SLF001
                getattr(app, "_steps").index("components"),
                getattr(app, "_steps").index("additional_services"),
            )

    def test_hydration_preserves_additional_service_enable_if_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "voice-runtime").mkdir()
            values = ManagedConfigValues(
                default_mode="main",
                main_profile=StartupProfile(True, True, True, False, False, False, False),
                trees_profile=StartupProfile(True, True, True, False, False, False, False),
                port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
                additional_services=(
                    AppServiceConfig(
                        name="voice-runtime",
                        env_suffix="VOICE_RUNTIME",
                        enabled_main=True,
                        enabled_trees=False,
                        dir_name="voice-runtime",
                        start_cmd="python -m voice_runtime --port {port}",
                        port_base=8010,
                        enable_if_path="voice-runtime/app/main.py",
                    ),
                ),
            )

            hydrated = _hydrate_wizard_values(values, base_dir=repo)

            self.assertEqual(hydrated.additional_services[0].enable_if_path, "voice-runtime/app/main.py")
            self.assertIsNot(hydrated.additional_services[0], values.additional_services[0])

    def test_additional_service_input_builder_preserves_hidden_fields(self) -> None:
        existing = AppServiceConfig(
            name="voice-runtime",
            env_suffix="VOICE_RUNTIME",
            enabled_main=True,
            enabled_trees=True,
            dir_name="voice-runtime",
            start_cmd="old-start {port}",
            startup_group="workers",
            enable_if_path="voice-runtime/app/main.py",
        )
        values = {
            "slug": "voice-runtime",
            "dir_name": "voice-runtime",
            "start_cmd": "scripts/start-voice.sh {port}",
            "port_base": "8010",
            "listener_expected": "true",
            "enabled_main": "true",
            "enabled_trees": "false",
            "test_cmd": "scripts/test-voice.sh",
            "public_url": "https://voice.example.test",
            "health_url": "https://voice.example.test/readyz",
            "depends_on": "backend, redis",
            "start_order": "45",
            "critical": "false",
        }

        result = build_additional_service_from_input_values(values.get, existing_service=existing)

        self.assertIsNone(result.error_message)
        self.assertIsNotNone(result.service)
        service = cast(AppServiceConfig, result.service)
        self.assertEqual(service.name, "voice-runtime")
        self.assertEqual(service.env_suffix, "VOICE_RUNTIME")
        self.assertEqual(service.port_base, 8010)
        self.assertEqual(service.depends_on, ("backend", "redis"))
        self.assertEqual(service.start_order, 45)
        self.assertFalse(service.critical)
        self.assertEqual(service.startup_group, "workers")
        self.assertEqual(service.enable_if_path, "voice-runtime/app/main.py")

    def test_additional_service_input_builder_reports_field_errors(self) -> None:
        values = {
            "slug": "voice-runtime",
            "port_base": "eight",
            "start_order": "45",
        }

        result = build_additional_service_from_input_values(lambda field: values.get(field, ""))

        self.assertEqual(result.error_message, "Base port must be a positive integer.")
        self.assertEqual(result.focus_field, "port_base")
        self.assertIsNone(result.service)

    def test_additional_service_input_builder_removes_current_service_for_blank_slug(self) -> None:
        result = build_additional_service_from_input_values(lambda _field: "")

        self.assertTrue(result.remove_current)
        self.assertIsNone(result.service)
        self.assertIsNone(result.error_message)

    def test_additional_app_service_wizard_inputs_add_full_service_definition(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "voice-runtime").mkdir()
            local_state = discover_local_config_state(repo)
            app = run_config_wizard_textual(
                local_state=local_state,
                build_only=True,
                default_wizard_type="advanced",
            )
            if app is None:
                self.skipTest("Textual is not available in this environment")
            app = cast(Any, app)

            async def run_test() -> None:
                async with app.run_test():
                    app.step_index = getattr(app, "_steps").index("additional_services")  # noqa: SLF001
                    app._refresh_all()  # noqa: SLF001
                    app.query_one(f"#{_additional_service_input_id('slug')}").value = "voice-runtime"
                    app.query_one(f"#{_additional_service_input_id('dir_name')}").value = "voice-runtime"
                    app.query_one(f"#{_additional_service_input_id('start_cmd')}").value = "scripts/start-voice.sh {port}"
                    app.query_one(f"#{_additional_service_input_id('port_base')}").value = "8010"
                    app.query_one(f"#{_additional_service_input_id('listener_expected')}").value = "true"
                    app.query_one(f"#{_additional_service_input_id('enabled_main')}").value = "true"
                    app.query_one(f"#{_additional_service_input_id('enabled_trees')}").value = "false"
                    app.query_one(f"#{_additional_service_input_id('test_cmd')}").value = "scripts/test-voice.sh"
                    app.query_one(f"#{_additional_service_input_id('public_url')}").value = "https://voice.example.test"
                    app.query_one(f"#{_additional_service_input_id('health_url')}").value = "https://voice.example.test/readyz"
                    app.query_one(f"#{_additional_service_input_id('depends_on')}").value = "backend,redis"
                    app.query_one(f"#{_additional_service_input_id('start_order')}").value = "45"
                    app.query_one(f"#{_additional_service_input_id('critical')}").value = "false"
                    self.assertTrue(app._apply_additional_service_inputs())  # noqa: SLF001

            import asyncio

            asyncio.run(run_test())
            service = app.values.additional_services[0]  # noqa: SLF001
            self.assertEqual(service.name, "voice-runtime")
            self.assertEqual(service.dir_name, "voice-runtime")
            self.assertEqual(service.start_cmd, "scripts/start-voice.sh {port}")
            self.assertEqual(service.port_base, 8010)
            self.assertTrue(service.expect_listener)
            self.assertTrue(service.enabled_main)
            self.assertFalse(service.enabled_trees)
            self.assertEqual(service.test_cmd, "scripts/test-voice.sh")
            self.assertEqual(service.public_url_template, "https://voice.example.test")
            self.assertEqual(service.health_url_template, "https://voice.example.test/readyz")
            self.assertEqual(service.depends_on, ("backend", "redis"))
            self.assertEqual(service.start_order, 45)
            self.assertFalse(service.critical)
            rendered = managed_values_to_mapping(app.values)  # noqa: SLF001
            self.assertEqual(rendered["ENVCTL_ADDITIONAL_SERVICES"], "voice-runtime")
            self.assertEqual(rendered["ENVCTL_SERVICE_VOICE_RUNTIME_MAIN_ENABLE"], "true")
            self.assertEqual(rendered["ENVCTL_SERVICE_VOICE_RUNTIME_TREES_ENABLE"], "false")
            self.assertEqual(rendered["ENVCTL_SERVICE_VOICE_RUNTIME_PUBLIC_URL"], "https://voice.example.test")
            self.assertEqual(rendered["ENVCTL_SERVICE_VOICE_RUNTIME_HEALTH_URL"], "https://voice.example.test/readyz")
            self.assertEqual(rendered["ENVCTL_SERVICE_VOICE_RUNTIME_DEPENDS_ON"], "backend,redis")
            self.assertEqual(rendered["ENVCTL_SERVICE_VOICE_RUNTIME_START_ORDER"], "45")
            self.assertEqual(rendered["ENVCTL_SERVICE_VOICE_RUNTIME_CRITICAL"], "false")

    def test_additional_app_service_wizard_inputs_edit_existing_service_and_preserve_others(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "voice-runtime").mkdir()
            (repo / "worker").mkdir()
            local_state = discover_local_config_state(repo)
            values = ManagedConfigValues(
                default_mode="main",
                main_profile=StartupProfile(True, True, True, False, False, False, False),
                trees_profile=StartupProfile(True, True, True, False, False, False, False),
                port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
                additional_services=(
                    AppServiceConfig(
                        name="voice-runtime",
                        env_suffix="VOICE_RUNTIME",
                        enabled_main=True,
                        enabled_trees=True,
                        dir_name="voice-runtime",
                        start_cmd="old-start {port}",
                        port_base=8010,
                        startup_group="workers",
                        enable_if_path="voice-runtime/app/main.py",
                    ),
                    AppServiceConfig(
                        name="worker",
                        env_suffix="WORKER",
                        enabled_main=False,
                        enabled_trees=True,
                        dir_name="worker",
                        start_cmd="python worker.py",
                        expect_listener=False,
                        critical=False,
                    ),
                ),
            )
            app = run_config_wizard_textual(local_state=local_state, initial_values=values, build_only=True)
            if app is None:
                self.skipTest("Textual is not available in this environment")
            app = cast(Any, app)

            async def run_test() -> None:
                async with app.run_test():
                    app.step_index = getattr(app, "_steps").index("additional_services")  # noqa: SLF001
                    app._refresh_all()  # noqa: SLF001
                    app.query_one(f"#{_additional_service_input_id('start_cmd')}").value = "new-start {port}"
                    app.query_one(f"#{_additional_service_input_id('enabled_trees')}").value = "false"
                    self.assertTrue(app._apply_additional_service_inputs())  # noqa: SLF001

            import asyncio

            asyncio.run(run_test())
            self.assertEqual([service.name for service in app.values.additional_services], ["voice-runtime", "worker"])  # noqa: SLF001
            voice = app.values.additional_services[0]  # noqa: SLF001
            worker = app.values.additional_services[1]  # noqa: SLF001
            self.assertEqual(voice.start_cmd, "new-start {port}")
            self.assertFalse(voice.enabled_trees)
            self.assertEqual(voice.startup_group, "workers")
            self.assertEqual(voice.enable_if_path, "voice-runtime/app/main.py")
            self.assertEqual(worker.name, "worker")
            self.assertFalse(worker.expect_listener)
            self.assertFalse(worker.critical)

    def test_additional_app_service_wizard_validation_rejects_invalid_integer_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "voice-runtime").mkdir()
            local_state = discover_local_config_state(repo)
            app = run_config_wizard_textual(
                local_state=local_state,
                build_only=True,
                default_wizard_type="advanced",
            )
            if app is None:
                self.skipTest("Textual is not available in this environment")
            app = cast(Any, app)

            async def run_test() -> None:
                async with app.run_test():
                    app.step_index = getattr(app, "_steps").index("additional_services")  # noqa: SLF001
                    app._refresh_all()  # noqa: SLF001
                    app.query_one(f"#{_additional_service_input_id('slug')}").value = "voice-runtime"
                    app.query_one(f"#{_additional_service_input_id('dir_name')}").value = "voice-runtime"
                    app.query_one(f"#{_additional_service_input_id('start_cmd')}").value = "scripts/start-voice.sh {port}"
                    app.query_one(f"#{_additional_service_input_id('port_base')}").value = "eight"
                    app.query_one(f"#{_additional_service_input_id('start_order')}").value = "late"
                    self.assertFalse(app._apply_additional_service_inputs())  # noqa: SLF001
                    self.assertIn("Base port must be a positive integer", app._last_status_message)  # noqa: SLF001

            import asyncio

            asyncio.run(run_test())

    def test_managed_value_validation_blocks_additional_service_dependency_errors(self) -> None:
        from envctl_engine.config.persistence import validate_managed_values

        values = ManagedConfigValues(
            default_mode="main",
            main_profile=StartupProfile(True, True, True, False, False, False, False),
            trees_profile=StartupProfile(True, True, True, False, False, False, False),
            port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
            additional_services=(
                AppServiceConfig(
                    name="voice-runtime",
                    env_suffix="VOICE_RUNTIME",
                    enabled_main=True,
                    enabled_trees=True,
                    dir_name="voice-runtime",
                    start_cmd="python -m voice_runtime --port {port}",
                    port_base=8010,
                    depends_on=("missing-service",),
                ),
            ),
        )

        validation = validate_managed_values(values, require_directories=False, require_entrypoints=True)

        self.assertFalse(validation.valid)
        self.assertIn(
            "service 'voice-runtime' depends on unknown service or dependency 'missing-service'",
            validation.errors,
        )

    def test_dynamic_fields_follow_configured_components_across_modes(self) -> None:
        values = ManagedConfigValues(
            default_mode="main",
            main_profile=StartupProfile(True, True, False, True, False, False, False),
            trees_profile=StartupProfile(False, True, True, True, True, False, True),
            port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
        )

        self.assertEqual(
            _visible_directory_fields(values),
            (
                ("backend_dir_name", "Backend directory"),
                ("frontend_dir_name", "Frontend directory"),
                ("frontend_test_path", "Frontend tests directory"),
            ),
        )
        self.assertEqual(
            _visible_command_fields(values),
            (
                ("backend_start_cmd", "Backend entrypoint"),
                ("backend_test_cmd", "Backend test command"),
                ("frontend_test_cmd", "Frontend test command"),
            ),
        )
        self.assertEqual(
            _visible_port_fields(values),
            (
                ("backend_port_base", "Backend base port"),
                ("db_port_base", "Database base port"),
                ("port_spacing", "Port spacing"),
            ),
        )

    def test_dynamic_fields_show_nothing_when_components_disabled_everywhere(self) -> None:
        values = ManagedConfigValues(
            default_mode="main",
            main_profile=StartupProfile(False, False, False, False, False, False, False),
            trees_profile=StartupProfile(False, False, False, False, False, False, False),
            port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
        )

        self.assertEqual(_visible_directory_fields(values), ())
        self.assertEqual(_visible_command_fields(values), ())
        self.assertEqual(_visible_port_fields(values), ())

    def test_port_fields_hide_backend_when_backend_runs_without_listener(self) -> None:
        values = ManagedConfigValues(
            default_mode="main",
            main_profile=StartupProfile(True, True, False, False, False, False, False),
            trees_profile=StartupProfile(False, True, False, False, False, False, False),
            port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
            main_backend_expect_listener=False,
            trees_backend_expect_listener=False,
        )

        self.assertEqual(_visible_port_fields(values), ())

    def test_directory_fields_hide_entrypoint_when_backend_is_not_long_running(self) -> None:
        values = ManagedConfigValues(
            default_mode="main",
            main_profile=StartupProfile(False, True, False, False, False, False, False),
            trees_profile=StartupProfile(False, True, False, False, False, False, False),
            port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
        )

        self.assertEqual(
            _visible_directory_fields(values),
            (("backend_dir_name", "Backend directory"),),
        )
        self.assertEqual(
            _visible_command_fields(values),
            (("backend_test_cmd", "Backend test command"),),
        )

    def test_directory_validation_message_requires_existing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "backend").mkdir()
            self.assertIsNone(_directory_validation_message(repo, "Backend directory", "backend"))
            self.assertEqual(
                _directory_validation_message(repo, "Backend directory", "api"),
                "Directory does not exist: api",
            )
        self.assertEqual(
            _directory_validation_message(repo, "Backend directory", ""),
            "Backend directory must not be empty.",
        )

    def test_command_validation_requires_entrypoints_but_not_test_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            local_state = discover_local_config_state(repo)
            values = ManagedConfigValues(
                default_mode="main",
                main_profile=StartupProfile(True, True, False, False, False, False, False),
                trees_profile=StartupProfile(True, True, False, False, False, False, False),
                port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
            )
            app = run_config_wizard_textual(local_state=local_state, initial_values=values, build_only=True)
            if app is None:
                self.skipTest("Textual is not available in this environment")
            app = cast(object, app)

            self.assertEqual(  # noqa: SLF001
                app._directory_validation_error("backend_start_cmd", raw=""),
                "Backend entrypoint must not be empty.",
            )
            self.assertIsNone(app._directory_validation_error("backend_test_cmd", raw=""))  # noqa: SLF001
