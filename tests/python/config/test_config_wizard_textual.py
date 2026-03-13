from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
from envctl_engine.config import PortDefaults, StartupProfile, discover_local_config_state
from envctl_engine.config.persistence import ManagedConfigValues
from envctl_engine.ui.textual.screens.config_wizard import (
    _directory_validation_message,
    _visible_command_fields,
    _visible_directory_fields,
    _visible_port_fields,
    run_config_wizard_textual,
)


class ConfigWizardTextualTests(unittest.TestCase):
    def test_build_only_flow_has_expected_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            local_state = discover_local_config_state(repo)
            app = run_config_wizard_textual(local_state=local_state, build_only=True)
            if app is None:
                self.skipTest("Textual is not available in this environment")
            self.assertEqual(  # noqa: SLF001
                app._steps,
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
            self.assertEqual(  # noqa: SLF001
                app._steps,
                ["welcome", "default_mode", "components", "service_startup", "directories", "commands", "ports", "review"],
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
                ("frontend_port_base", "Frontend base port"),
                ("db_port_base", "Database base port"),
                ("redis_port_base", "Redis base port"),
                ("n8n_port_base", "n8n base port"),
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

    def test_directory_fields_hide_entrypoint_when_backend_is_not_long_running(self) -> None:
        values = ManagedConfigValues(
            default_mode="main",
            main_profile=StartupProfile(False, True, False, False, False, False, False),
            trees_profile=StartupProfile(False, True, False, False, False, False, False),
            port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
        )

        self.assertEqual(
            _visible_directory_fields(values),
            (
                ("backend_dir_name", "Backend directory"),
            ),
        )
        self.assertEqual(
            _visible_command_fields(values),
            (
                ("backend_test_cmd", "Backend test command"),
            ),
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
