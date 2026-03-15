from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]
from envctl_engine.config import LocalConfigState, discover_local_config_state
from envctl_engine.config.persistence import ManagedConfigValues
from envctl_engine.config import PortDefaults, StartupProfile
from envctl_engine.ui.textual.screens.config_wizard import (
    _COMPONENT_FIELDS,
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
        self.assertIn(_port_input_id("db_port_base"), identifiers)

    def test_port_input_id_preserves_simple_fields(self) -> None:
        self.assertEqual(_port_input_id("backend_port_base"), "port-backend_port_base")
        self.assertEqual(_port_input_id("db_port_base"), "port-db_port_base")


class TextualConfigWizardAppTests(unittest.IsolatedAsyncioTestCase):
    def _local_state(self) -> LocalConfigState:
        return LocalConfigState(
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

    async def test_wizard_builds_with_canonical_port_fields(self) -> None:
        if importlib.util.find_spec("textual") is None:
            self.skipTest("textual is not installed")

        app = run_config_wizard_textual(local_state=self._local_state(), build_only=True)

        async with app.run_test() as pilot:
            await pilot.pause()
            db_input = app.query_one(f"#{_port_input_id('db_port_base')}")
            redis_input = app.query_one(f"#{_port_input_id('redis_port_base')}")
            self.assertEqual(getattr(db_input, "value", None), "5432")
            self.assertEqual(getattr(redis_input, "value", None), "6379")
            app.exit(None)

    async def test_enter_advances_from_default_mode_without_toggling_row(self) -> None:
        if importlib.util.find_spec("textual") is None:
            self.skipTest("textual is not installed")

        app = run_config_wizard_textual(local_state=self._local_state(), build_only=True)

        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(app._current_step(), "default_mode")  # noqa: SLF001
            await pilot.press("down")
            await pilot.pause()
            self.assertEqual(app.values.default_mode, "trees")  # noqa: SLF001
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(app._current_step(), "components")  # noqa: SLF001
            self.assertEqual(app.values.default_mode, "trees")  # noqa: SLF001
            app.exit(None)

    async def test_left_and_right_arrows_navigate_steps(self) -> None:
        if importlib.util.find_spec("textual") is None:
            self.skipTest("textual is not installed")

        app = run_config_wizard_textual(local_state=self._local_state(), build_only=True)

        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("right")
            await pilot.pause()
            self.assertEqual(app._current_step(), "components")  # noqa: SLF001
            await pilot.press("left")
            await pilot.pause()
            self.assertEqual(app._current_step(), "default_mode")  # noqa: SLF001
            app.exit(None)

    async def test_components_show_services_and_dependencies_together(self) -> None:
        if importlib.util.find_spec("textual") is None:
            self.skipTest("textual is not installed")

        app = run_config_wizard_textual(local_state=self._local_state(), build_only=True)

        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("right")
            await pilot.pause()
            self.assertEqual(app._current_step(), "components")  # noqa: SLF001
            labels = [label.render().plain for label in app.query("#config-list Label")]
            self.assertIn("Services", labels)
            self.assertIn("● Backend (Main + Trees)", labels)
            self.assertIn("● Frontend (Main + Trees)", labels)
            self.assertIn("Dependencies", labels)
            self.assertIn("○ Postgres (Main + Trees)", labels)
            headers = [item for item in app.query("#config-list ListItem") if "config-section-header" in item.classes]
            self.assertEqual(len(headers), 2)
            app.exit(None)

    async def test_components_is_second_step_after_default_mode(self) -> None:
        if importlib.util.find_spec("textual") is None:
            self.skipTest("textual is not installed")

        app = run_config_wizard_textual(local_state=self._local_state(), build_only=True)

        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("right")
            await pilot.pause()
            self.assertEqual(app._current_step(), "components")  # noqa: SLF001
            app.exit(None)

    async def test_space_toggles_service_rows_and_enter_only_advances(self) -> None:
        if importlib.util.find_spec("textual") is None:
            self.skipTest("textual is not installed")

        initial_values = ManagedConfigValues(
            default_mode="main",
            main_profile=StartupProfile(True, True, True, False, False, False, False),
            trees_profile=StartupProfile(True, True, True, False, False, False, False),
            port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
            backend_start_cmd="python src/main.py",
            frontend_start_cmd="npm run dev -- --port 0 --host",
        )
        app = run_config_wizard_textual(local_state=self._local_state(), initial_values=initial_values, build_only=True)

        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("right")
            await pilot.pause()
            self.assertTrue(app.values.main_profile.backend_enable)  # noqa: SLF001
            self.assertTrue(app.values.trees_profile.backend_enable)  # noqa: SLF001
            await pilot.press("space")
            await pilot.pause()
            self.assertFalse(app.values.main_profile.backend_enable)  # noqa: SLF001
            self.assertFalse(app.values.trees_profile.backend_enable)  # noqa: SLF001
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(app._current_step(), "directories")  # noqa: SLF001
            self.assertFalse(app.values.main_profile.backend_enable)  # noqa: SLF001
            self.assertFalse(app.values.trees_profile.backend_enable)  # noqa: SLF001
            app.exit(None)

    async def test_backend_only_projects_show_service_startup_step_after_components(self) -> None:
        if importlib.util.find_spec("textual") is None:
            self.skipTest("textual is not installed")

        initial_values = ManagedConfigValues(
            default_mode="main",
            main_profile=StartupProfile(True, True, False, False, False, False, False),
            trees_profile=StartupProfile(True, True, False, False, False, False, False),
            port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
            backend_start_cmd="python src/main.py",
        )
        app = run_config_wizard_textual(
            local_state=self._local_state(),
            initial_values=initial_values,
            build_only=True,
        )

        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("right")
            await pilot.pause()
            self.assertEqual(app._current_step(), "components")  # noqa: SLF001
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(app._current_step(), "service_startup")  # noqa: SLF001
            labels = [label.render().plain for label in app.query("#config-list Label")]
            self.assertIn("● Main - start this service with envctl", labels)
            self.assertIn("● Trees - start this service with envctl", labels)
            self.assertIn("● Main - wait for a listener/port before continuing", labels)
            self.assertIn("● Trees - wait for a listener/port before continuing", labels)
            app.exit(None)

    async def test_backend_only_non_running_service_skips_ports_step(self) -> None:
        if importlib.util.find_spec("textual") is None:
            self.skipTest("textual is not installed")

        initial_values = ManagedConfigValues(
            default_mode="main",
            main_profile=StartupProfile(False, True, False, False, False, False, False),
            trees_profile=StartupProfile(False, True, False, False, False, False, False),
            port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
            backend_test_cmd="pytest",
        )
        app = run_config_wizard_textual(
            local_state=self._local_state(),
            initial_values=initial_values,
            build_only=True,
        )

        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("right")
            await pilot.pause()
            self.assertEqual(app._current_step(), "components")  # noqa: SLF001
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(app._current_step(), "service_startup")  # noqa: SLF001
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(app._current_step(), "directories")  # noqa: SLF001
            app.query_one("#btn-next").focus()
            await pilot.pause()
            await pilot.press("right")
            await pilot.pause()
            self.assertEqual(app._current_step(), "commands")  # noqa: SLF001
            app.query_one("#btn-next").focus()
            await pilot.pause()
            await pilot.press("right")
            await pilot.pause()
            self.assertEqual(app._current_step(), "review")  # noqa: SLF001
            self.assertNotIn("ports", app._steps)  # noqa: SLF001
            app.exit(None)

    async def test_components_split_focused_row_into_main_and_trees(self) -> None:
        if importlib.util.find_spec("textual") is None:
            self.skipTest("textual is not installed")

        app = run_config_wizard_textual(local_state=self._local_state(), build_only=True)

        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("right")
            await pilot.pause()
            await pilot.press("down")
            await pilot.press("down")
            await pilot.pause()
            self.assertEqual(app._current_step(), "components")  # noqa: SLF001
            await pilot.press("d")
            await pilot.pause()
            labels = [label.render().plain for label in app.query("#config-list Label")]
            self.assertIn("○ Main - Postgres", labels)
            self.assertIn("○ Trees - Postgres", labels)
            self.assertNotIn("○ Postgres (Main + Trees)", labels)
            app.exit(None)

    async def test_components_status_mentions_split_only_for_selectable_rows(self) -> None:
        if importlib.util.find_spec("textual") is None:
            self.skipTest("textual is not installed")

        initial_values = ManagedConfigValues(
            default_mode="main",
            main_profile=StartupProfile(True, True, True, False, False, False, False),
            trees_profile=StartupProfile(True, True, True, False, False, False, False),
            port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
            backend_dir_name=".",
            frontend_dir_name=".",
            backend_start_cmd="python src/main.py",
            frontend_start_cmd="npm run dev -- --port 0 --host",
        )
        app = run_config_wizard_textual(local_state=self._local_state(), initial_values=initial_values, build_only=True)

        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("right")
            await pilot.pause()
            status = app.query_one("#config-status").render().plain
            self.assertIn("D to split/merge", status)
            app.exit(None)

    async def test_non_component_steps_do_not_mention_split_in_status(self) -> None:
        if importlib.util.find_spec("textual") is None:
            self.skipTest("textual is not installed")

        app = run_config_wizard_textual(local_state=self._local_state(), build_only=True)

        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.pause()
            status = app.query_one("#config-status").render().plain
            self.assertNotIn("D to split", status)
            app.exit(None)

    async def test_components_start_split_when_main_and_trees_differ(self) -> None:
        if importlib.util.find_spec("textual") is None:
            self.skipTest("textual is not installed")

        initial_values = ManagedConfigValues(
            default_mode="main",
            main_profile=StartupProfile(True, True, True, False, True, False, False),
            trees_profile=StartupProfile(True, True, True, False, False, False, False),
            port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
        )
        app = run_config_wizard_textual(
            local_state=self._local_state(),
            initial_values=initial_values,
            build_only=True,
        )

        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("right")
            await pilot.pause()
            labels = [label.render().plain for label in app.query("#config-list Label")]
            self.assertIn("● Main - Redis", labels)
            self.assertIn("○ Trees - Redis", labels)
            self.assertNotIn("● Redis (Main + Trees)", labels)
            app.exit(None)

    async def test_left_and_right_arrows_do_not_navigate_steps_inside_directory_input(self) -> None:
        if importlib.util.find_spec("textual") is None:
            self.skipTest("textual is not installed")

        initial_values = ManagedConfigValues(
            default_mode="main",
            main_profile=StartupProfile(True, True, False, False, False, False, False),
            trees_profile=StartupProfile(True, True, False, False, False, False, False),
            port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
            backend_start_cmd="python src/main.py",
        )
        app = run_config_wizard_textual(local_state=self._local_state(), initial_values=initial_values, build_only=True)

        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("right")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(app._current_step(), "service_startup")  # noqa: SLF001
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(app._current_step(), "directories")  # noqa: SLF001
            backend_input = app.query_one("#directory-backend_dir_name")
            backend_input.focus()
            await pilot.pause()
            await pilot.press("left")
            await pilot.pause()
            self.assertEqual(app._current_step(), "directories")  # noqa: SLF001
            await pilot.press("right")
            await pilot.pause()
            self.assertEqual(app._current_step(), "directories")  # noqa: SLF001
            app.exit(None)

    async def test_commands_step_shows_backend_entrypoint_for_backend_projects(self) -> None:
        if importlib.util.find_spec("textual") is None:
            self.skipTest("textual is not installed")

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "src").mkdir(parents=True, exist_ok=True)
            (repo / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
            tests_dir = repo / "tests"
            tests_dir.mkdir(parents=True, exist_ok=True)
            (tests_dir / "test_sample.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
            local_state = discover_local_config_state(repo)
            initial_values = ManagedConfigValues(
                default_mode="main",
                main_profile=StartupProfile(True, True, False, False, False, False, False),
                trees_profile=StartupProfile(True, True, False, False, False, False, False),
                port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
                backend_start_cmd="python src/main.py",
            )
            app = run_config_wizard_textual(local_state=local_state, initial_values=initial_values, build_only=True)

            async with app.run_test() as pilot:
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("right")
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                self.assertEqual(app._current_step(), "service_startup")  # noqa: SLF001
                await pilot.press("enter")
                await pilot.pause()
                self.assertEqual(app._current_step(), "directories")  # noqa: SLF001
                app.query_one("#btn-next").focus()
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                self.assertEqual(app._current_step(), "commands")  # noqa: SLF001
                entrypoint = app.query_one("#directory-backend_start_cmd")
                self.assertEqual(getattr(entrypoint, "value", None), "python src/main.py")
                test_command = app.query_one("#directory-backend_test_cmd")
                self.assertTrue(
                    str(getattr(test_command, "value", "")).endswith(
                        " -m unittest discover -s tests -t . -p test_*.py"
                    )
                )
                app.exit(None)

    async def test_directories_step_shows_frontend_tests_directory_and_commands_step_shows_test_commands_when_detected(
        self,
    ) -> None:
        if importlib.util.find_spec("textual") is None:
            self.skipTest("textual is not installed")

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "backend" / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "requirements.txt").write_text("pytest\n", encoding="utf-8")
            frontend = repo / "frontend"
            frontend.mkdir(parents=True, exist_ok=True)
            (frontend / "package.json").write_text(
                '{"name":"app","scripts":{"dev":"vite","test":"vitest"}}\n',
                encoding="utf-8",
            )
            local_state = discover_local_config_state(repo)
            initial_values = ManagedConfigValues(
                default_mode="main",
                main_profile=StartupProfile(True, True, True, False, False, False, False),
                trees_profile=StartupProfile(True, True, True, False, False, False, False),
                port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
                backend_start_cmd="python backend/main.py",
                frontend_start_cmd="npm run dev -- --port 0 --host",
            )
            app = run_config_wizard_textual(local_state=local_state, initial_values=initial_values, build_only=True)

            async with app.run_test() as pilot:
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("right")
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                self.assertEqual(app._current_step(), "directories")  # noqa: SLF001
                frontend_test_path = app.query_one("#directory-frontend_test_path")
                self.assertEqual(getattr(frontend_test_path, "value", None), "")
                app.query_one("#btn-next").focus()
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                self.assertEqual(app._current_step(), "commands")  # noqa: SLF001
                backend_test_command = app.query_one("#directory-backend_test_cmd")
                backend_value = str(getattr(backend_test_command, "value", ""))
                self.assertIn(" -m pytest ", backend_value)
                self.assertTrue(
                    backend_value.endswith(str((repo / "backend" / "tests").resolve())),
                    msg=backend_value,
                )
                frontend_test_command = app.query_one("#directory-frontend_test_cmd")
                self.assertEqual(getattr(frontend_test_command, "value", None), "npm run test")
                app.exit(None)

    async def test_commands_step_shows_frontend_entrypoint_for_frontend_projects(self) -> None:
        if importlib.util.find_spec("textual") is None:
            self.skipTest("textual is not installed")

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            frontend = repo / "frontend"
            frontend.mkdir(parents=True, exist_ok=True)
            (frontend / "package.json").write_text(
                '{"name":"app","scripts":{"dev":"vite"}}\n',
                encoding="utf-8",
            )
            local_state = discover_local_config_state(repo)
            initial_values = ManagedConfigValues(
                default_mode="main",
                main_profile=StartupProfile(True, False, True, False, False, False, False),
                trees_profile=StartupProfile(True, False, True, False, False, False, False),
                port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
                frontend_start_cmd="npm run dev -- --port 0 --host",
            )
            app = run_config_wizard_textual(
                local_state=local_state,
                initial_values=initial_values,
                build_only=True,
            )

            async with app.run_test() as pilot:
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("right")
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                self.assertEqual(app._current_step(), "directories")  # noqa: SLF001
                frontend_test_path = app.query_one("#directory-frontend_test_path")
                self.assertEqual(getattr(frontend_test_path, "value", None), "")
                app.query_one("#btn-next").focus()
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                self.assertEqual(app._current_step(), "commands")  # noqa: SLF001
                entrypoint = app.query_one("#directory-frontend_start_cmd")
                self.assertEqual(getattr(entrypoint, "value", None), "npm run dev -- --port 0 --host")
                app.exit(None)

    async def test_directories_step_shows_frontend_tests_directory_when_detected(self) -> None:
        if importlib.util.find_spec("textual") is None:
            self.skipTest("textual is not installed")

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            frontend = repo / "frontend"
            src_dir = frontend / "src"
            src_dir.mkdir(parents=True, exist_ok=True)
            (frontend / "package.json").write_text(
                '{"name":"app","scripts":{"dev":"vite","test":"vitest"}}\n',
                encoding="utf-8",
            )
            (src_dir / "app.test.ts").write_text("it('works', () => {})\n", encoding="utf-8")
            local_state = discover_local_config_state(repo)
            initial_values = ManagedConfigValues(
                default_mode="main",
                main_profile=StartupProfile(True, False, True, False, False, False, False),
                trees_profile=StartupProfile(True, False, True, False, False, False, False),
                port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
                frontend_start_cmd="npm run dev -- --port 0 --host",
            )
            app = run_config_wizard_textual(
                local_state=local_state,
                initial_values=initial_values,
                build_only=True,
            )

            async with app.run_test() as pilot:
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("right")
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                self.assertEqual(app._current_step(), "directories")  # noqa: SLF001
                frontend_test_path = app.query_one("#directory-frontend_test_path")
                self.assertEqual(getattr(frontend_test_path, "value", None), "frontend/src")
                app.exit(None)

    async def test_enter_on_back_button_goes_back_instead_of_next(self) -> None:
        if importlib.util.find_spec("textual") is None:
            self.skipTest("textual is not installed")

        app = run_config_wizard_textual(local_state=self._local_state(), build_only=True)

        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("right")
            await pilot.pause()
            self.assertEqual(app._current_step(), "components")  # noqa: SLF001
            app.query_one("#btn-back").focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(app._current_step(), "default_mode")  # noqa: SLF001
            app.exit(None)
