from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.config import PortDefaults, StartupProfile, discover_local_config_state
from envctl_engine.config.persistence import ManagedConfigValues
from envctl_engine.ui.textual.screens.config_wizard import (
    _directory_validation_message,
    _visible_directory_fields,
    _visible_port_fields,
    run_config_wizard_textual,
)


class ConfigWizardTextualTests(unittest.TestCase):
    def test_build_only_simple_flow_has_expected_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            local_state = discover_local_config_state(repo)

            app = run_config_wizard_textual(local_state=local_state, build_only=True, default_wizard_type="simple")
            if app is None:
                self.skipTest("Textual is not available in this environment")

            self.assertEqual(app._wizard_type, "simple")  # noqa: SLF001
            self.assertEqual(
                app._steps,  # noqa: SLF001
                ["welcome", "wizard_type", "default_mode", "main_preset", "trees_preset", "review"],
            )

    def test_build_only_advanced_flow_has_expected_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".envctl").write_text("ENVCTL_DEFAULT_MODE=main\n", encoding="utf-8")
            local_state = discover_local_config_state(repo)

            app = run_config_wizard_textual(local_state=local_state, build_only=True, default_wizard_type="advanced")
            if app is None:
                self.skipTest("Textual is not available in this environment")

            self.assertEqual(app._wizard_type, "advanced")  # noqa: SLF001
            self.assertEqual(
                app._steps,  # noqa: SLF001
                [
                    "welcome",
                    "wizard_type",
                    "default_mode",
                    "startup_modes",
                    "main_profile",
                    "trees_profile",
                    "directories",
                    "ports",
                    "review",
                ],
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
            (("backend_dir_name", "Backend directory"), ("frontend_dir_name", "Frontend directory")),
        )
        self.assertEqual(
            _visible_port_fields(values),
            (
                ("backend_port_base", "Backend base port"),
                ("frontend_port_base", "Frontend base port"),
                ("dependency::postgres::primary", "postgres base port"),
                ("dependency::redis::primary", "redis base port"),
                ("dependency::n8n::primary", "n8n base port"),
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
        self.assertEqual(_visible_port_fields(values), ())

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


if __name__ == "__main__":
    unittest.main()
