from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.config import LocalConfigState
from envctl_engine.ui.textual.screens.config_wizard import (
    _PORT_FIELDS,
    _port_input_id,
    run_config_wizard_textual,
)


class ConfigWizardIdTests(unittest.TestCase):
    def test_port_input_ids_are_valid_textual_identifiers(self) -> None:
        pattern = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
        identifiers = [_port_input_id(field_name) for field_name, _ in _PORT_FIELDS]

        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertTrue(all(pattern.fullmatch(identifier) for identifier in identifiers))
        self.assertIn(_port_input_id("dependency::postgres::primary"), identifiers)

    def test_port_input_id_preserves_simple_fields(self) -> None:
        self.assertEqual(_port_input_id("backend_port_base"), "port-backend_port_base")
        self.assertEqual(_port_input_id("dependency::postgres::primary"), "port-dependency-postgres-primary")


class TextualConfigWizardAppTests(unittest.IsolatedAsyncioTestCase):
    async def test_wizard_builds_with_dependency_port_fields(self) -> None:
        if importlib.util.find_spec("textual") is None:
            self.skipTest("textual is not installed")

        local_state = LocalConfigState(
            base_dir=REPO_ROOT,
            config_file_path=REPO_ROOT / ".envctl",
            config_file_exists=False,
            config_source="defaults",
            active_source_path=None,
            legacy_source_path=None,
            explicit_path=None,
            parsed_values={},
            file_text="",
        )
        app = run_config_wizard_textual(local_state=local_state, build_only=True)

        async with app.run_test() as pilot:
            await pilot.pause()
            postgres_input = app.query_one(f"#{_port_input_id('dependency::postgres::primary')}")
            redis_input = app.query_one(f"#{_port_input_id('dependency::redis::primary')}")

            self.assertEqual(getattr(postgres_input, "value", None), "5432")
            self.assertEqual(getattr(redis_input, "value", None), "6379")
            app.exit(None)

    async def test_enter_advances_from_wizard_type_screen_with_list_focus(self) -> None:
        if importlib.util.find_spec("textual") is None:
            self.skipTest("textual is not installed")

        local_state = LocalConfigState(
            base_dir=REPO_ROOT,
            config_file_path=REPO_ROOT / ".envctl",
            config_file_exists=False,
            config_source="defaults",
            active_source_path=None,
            legacy_source_path=None,
            explicit_path=None,
            parsed_values={},
            file_text="",
        )
        app = run_config_wizard_textual(local_state=local_state, build_only=True)

        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(app._current_step(), "wizard_type")  # noqa: SLF001

            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(app._current_step(), "default_mode")  # noqa: SLF001
            app.exit(None)

    async def test_enter_commits_highlighted_wizard_type_before_advancing(self) -> None:
        if importlib.util.find_spec("textual") is None:
            self.skipTest("textual is not installed")

        local_state = LocalConfigState(
            base_dir=REPO_ROOT,
            config_file_path=REPO_ROOT / ".envctl",
            config_file_exists=False,
            config_source="defaults",
            active_source_path=None,
            legacy_source_path=None,
            explicit_path=None,
            parsed_values={},
            file_text="",
        )
        app = run_config_wizard_textual(local_state=local_state, build_only=True)

        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(app._wizard_type, "advanced")  # noqa: SLF001
            self.assertEqual(app._current_step(), "default_mode")  # noqa: SLF001
            self.assertEqual(
                app._steps,
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
            )  # noqa: SLF001
            app.exit(None)

    async def test_advanced_startup_step_is_separate_from_profile_settings(self) -> None:
        if importlib.util.find_spec("textual") is None:
            self.skipTest("textual is not installed")

        local_state = LocalConfigState(
            base_dir=REPO_ROOT,
            config_file_path=REPO_ROOT / ".envctl",
            config_file_exists=False,
            config_source="defaults",
            active_source_path=None,
            legacy_source_path=None,
            explicit_path=None,
            parsed_values={},
            file_text="",
        )
        app = run_config_wizard_textual(local_state=local_state, build_only=True, default_wizard_type="advanced")

        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            self.assertEqual(app._current_step(), "startup_modes")  # noqa: SLF001
            startup_labels = [label.render().plain for label in app.query("#config-list Label")]
            self.assertEqual(startup_labels, ["● Main: Enabled for envctl runs", "● Trees: Enabled for envctl runs"])

            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(app._current_step(), "main_profile")  # noqa: SLF001
            profile_labels = [label.render().plain for label in app.query("#config-list Label")]
            self.assertNotIn("● Enabled for envctl runs", profile_labels)
            app.exit(None)


if __name__ == "__main__":
    unittest.main()
