from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from envctl_engine.config import PortDefaults, StartupProfile
from envctl_engine.config.persistence import ManagedConfigValues
from envctl_engine.ui.textual.screens.config_wizard_values import (
    apply_port_field_value,
    apply_port_field_values,
    apply_text_field_values,
    validate_text_field,
    wizard_field_value,
)


class ConfigWizardValuePolicyTests(unittest.TestCase):
    def _values(self) -> ManagedConfigValues:
        return ManagedConfigValues(
            default_mode="main",
            main_profile=StartupProfile(True, True, True, True, True, False, False),
            trees_profile=StartupProfile(False, False, False, False, False, False, False),
            port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
            backend_dir_name="backend",
            frontend_dir_name="frontend",
            backend_start_cmd="python app.py",
            frontend_start_cmd="npm run dev",
            backend_test_cmd="pytest",
            frontend_test_cmd="npm test",
            frontend_test_path="src",
        )

    def test_wizard_field_value_reads_text_and_port_fields(self) -> None:
        values = self._values()

        self.assertEqual(wizard_field_value(values, "backend_dir_name"), "backend")
        self.assertEqual(wizard_field_value(values, "frontend_test_path"), "src")
        self.assertEqual(wizard_field_value(values, "backend_port_base"), 8000)
        self.assertEqual(wizard_field_value(values, "db_port_base"), 5432)
        self.assertEqual(wizard_field_value(values, "unknown"), 0)

    def test_text_field_validation_matches_wizard_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            (base_dir / "backend").mkdir()

            self.assertIsNone(validate_text_field(base_dir, "backend_dir_name", "Backend directory", "backend"))
            self.assertEqual(
                validate_text_field(base_dir, "backend_dir_name", "Backend directory", "api"),
                "Directory does not exist: api",
            )
            self.assertEqual(
                validate_text_field(base_dir, "backend_start_cmd", "Backend entrypoint", ""),
                "Backend entrypoint must not be empty.",
            )
            self.assertIsNone(validate_text_field(base_dir, "backend_test_cmd", "Backend test command", ""))
            self.assertIsNone(validate_text_field(base_dir, "frontend_test_path", "Frontend test path", ""))

    def test_apply_text_field_values_validates_before_mutating(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            (base_dir / "api").mkdir()
            values = self._values()

            result = apply_text_field_values(
                values,
                base_dir=base_dir,
                visible_fields=(
                    ("backend_dir_name", "Backend directory"),
                    ("frontend_dir_name", "Frontend directory"),
                ),
                raw_values={"backend_dir_name": "api", "frontend_dir_name": "web"},
            )

            self.assertFalse(result.valid)
            self.assertEqual(result.error_message, "Directory does not exist: web")
            self.assertEqual(result.focus_field, "frontend_dir_name")
            self.assertEqual(values.backend_dir_name, "backend")
            self.assertEqual(values.frontend_dir_name, "frontend")

    def test_apply_text_field_values_updates_all_valid_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            (base_dir / "api").mkdir()
            values = self._values()

            result = apply_text_field_values(
                values,
                base_dir=base_dir,
                visible_fields=(
                    ("backend_dir_name", "Backend directory"),
                    ("backend_start_cmd", "Backend entrypoint"),
                    ("backend_test_cmd", "Backend test command"),
                    ("frontend_test_path", "Frontend test path"),
                ),
                raw_values={
                    "backend_dir_name": "api",
                    "backend_start_cmd": "uvicorn app:app",
                    "backend_test_cmd": "",
                    "frontend_test_path": "",
                },
            )

            self.assertTrue(result.valid)
            self.assertEqual(values.backend_dir_name, "api")
            self.assertEqual(values.backend_start_cmd, "uvicorn app:app")
            self.assertEqual(values.backend_test_cmd, "")
            self.assertEqual(values.frontend_test_path, "")

    def test_apply_port_field_values_validates_before_mutating(self) -> None:
        values = self._values()

        result = apply_port_field_values(
            values,
            visible_fields=(
                ("backend_port_base", "Backend base port"),
                ("frontend_port_base", "Frontend base port"),
            ),
            raw_values={"backend_port_base": "8100", "frontend_port_base": "0"},
        )

        self.assertFalse(result.valid)
        self.assertEqual(result.error_message, "Frontend base port must be a positive integer.")
        self.assertEqual(result.focus_field, "frontend_port_base")
        self.assertEqual(values.port_defaults.backend_port_base, 8000)
        self.assertEqual(values.port_defaults.frontend_port_base, 9000)

    def test_apply_port_field_values_does_not_mutate_when_global_validation_fails(self) -> None:
        values = self._values()
        values.main_profile.supabase_enable = True

        result = apply_port_field_values(
            values,
            visible_fields=(("db_port_base", "DB base port"),),
            raw_values={"db_port_base": "15432"},
        )

        self.assertFalse(result.valid)
        self.assertEqual(result.error_message, "main cannot enable both postgres and supabase.")
        self.assertEqual(values.port_defaults.dependency_ports["postgres"]["primary"], 5432)
        self.assertEqual(values.port_defaults.dependency_ports["supabase"]["db"], 5432)

    def test_apply_port_field_values_updates_dependency_ports(self) -> None:
        values = self._values()

        result = apply_port_field_values(
            values,
            visible_fields=(
                ("db_port_base", "DB base port"),
                ("redis_port_base", "Redis base port"),
                ("n8n_port_base", "n8n base port"),
                ("port_spacing", "Port spacing"),
            ),
            raw_values={
                "db_port_base": "15432",
                "redis_port_base": "16379",
                "n8n_port_base": "15678",
                "port_spacing": "50",
            },
        )

        self.assertTrue(result.valid)
        self.assertEqual(values.port_defaults.dependency_ports["postgres"]["primary"], 15432)
        self.assertEqual(values.port_defaults.dependency_ports["supabase"]["db"], 15432)
        self.assertEqual(values.port_defaults.dependency_ports["redis"]["primary"], 16379)
        self.assertEqual(values.port_defaults.dependency_ports["n8n"]["primary"], 15678)
        self.assertEqual(values.port_defaults.port_spacing, 50)

    def test_apply_port_field_value_ignores_unknown_fields(self) -> None:
        values = self._values()

        apply_port_field_value(values, "unknown", 12345)

        self.assertEqual(values.port_defaults.backend_port_base, 8000)


if __name__ == "__main__":
    unittest.main()
