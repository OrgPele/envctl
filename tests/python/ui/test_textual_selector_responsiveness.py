from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.ui.selector_model import SelectorItem
from envctl_engine.ui.textual.list_row_styles import selectable_list_row_css
from envctl_engine.ui.textual.list_row_styles import selectable_list_default_index
from envctl_engine.ui.textual.list_row_styles import selectable_list_row_classes
from envctl_engine.ui.textual.screens.planning_selector import select_planning_counts_textual
from envctl_engine.ui.textual.screens.config_wizard import CONFIG_ROW_STYLES_CSS
from envctl_engine.ui.textual.screens.planning_selector import PLANNING_ROW_STYLES_CSS
from envctl_engine.ui.textual.screens import selector
from envctl_engine.ui.textual.screens.selector.textual_app_chrome import SELECTOR_CSS
from envctl_engine.ui.textual.screens.selector.textual_app_chrome import SELECTOR_ROW_STYLES_CSS


class TextualSelectorResponsivenessTests(unittest.IsolatedAsyncioTestCase):
    def test_shared_list_row_styles_are_reused_across_textual_lists(self) -> None:
        self.assertEqual(SELECTOR_ROW_STYLES_CSS, selectable_list_row_css("selector-row"))
        self.assertEqual(PLANNING_ROW_STYLES_CSS, selectable_list_row_css("planning-row"))
        self.assertEqual(CONFIG_ROW_STYLES_CSS, selectable_list_row_css("config-row"))

    def test_shared_list_row_state_helpers_cover_classes_and_initial_focus(self) -> None:
        self.assertEqual(selectable_list_row_classes("config-row", selected=True), "config-row config-row-selected")
        self.assertEqual(
            selectable_list_row_classes("planning-row", selected=False),
            "planning-row planning-row-unselected",
        )
        self.assertEqual(selectable_list_default_index([False, True, False]), 1)
        self.assertEqual(selectable_list_default_index([False, False]), 0)

    def test_selector_css_uses_distinct_non_warning_hover_and_selected_states(self) -> None:
        self.assertIn(".selector-row-unselected.-highlight", SELECTOR_CSS)
        self.assertIn(".selector-row-selected {", SELECTOR_CSS)
        self.assertIn(".selector-row-selected.-highlight", SELECTOR_CSS)
        self.assertIn("ListItem.-highlight", SELECTOR_CSS)
        self.assertIn("background: $accent 18%;", SELECTOR_CSS)
        self.assertIn("background: $success 22%;", SELECTOR_CSS)
        self.assertIn("background: $success 34%;", SELECTOR_CSS)
        self.assertIn("background: $accent 8%;", SELECTOR_CSS)
        self.assertNotIn("background: $warning 18%;", SELECTOR_CSS)
        self.assertNotIn("background: $warning 14%;", SELECTOR_CSS)
        self.assertIn("border-left: wide $accent;", SELECTOR_CSS)
        self.assertIn("border-left: wide $success;", SELECTOR_CSS)
        self.assertIn("color: $success;", SELECTOR_CSS)

    async def test_arrow_navigation_moves_single_row_per_keypress(self) -> None:
        options = [
            SelectorItem(
                id="service:alpha",
                label="Alpha Backend",
                kind="service",
                token="alpha",
                scope_signature=("service:alpha",),
            ),
            SelectorItem(
                id="service:beta",
                label="Beta Frontend",
                kind="service",
                token="beta",
                scope_signature=("service:beta",),
            ),
            SelectorItem(
                id="service:gamma",
                label="Gamma Worker",
                kind="service",
                token="gamma",
                scope_signature=("service:gamma",),
            ),
        ]
        app = selector._run_textual_selector(  # type: ignore[assignment]
            prompt="Restart",
            options=options,
            multi=True,
            emit=None,
            build_only=True,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            list_view = app.query_one("#selector-list")
            self.assertEqual(list_view.index, 0)
            await pilot.press("down")
            await pilot.pause()
            self.assertEqual(list_view.index, 1)
            await pilot.press("down")
            await pilot.pause()
            self.assertEqual(list_view.index, 2)
            await pilot.press("up")
            await pilot.pause()
            self.assertEqual(list_view.index, 1)
            app.exit(None)

    async def test_arrow_navigation_clamps_at_edges(self) -> None:
        options = [
            SelectorItem(
                id="service:alpha",
                label="Alpha Backend",
                kind="service",
                token="alpha",
                scope_signature=("service:alpha",),
            ),
            SelectorItem(
                id="service:beta",
                label="Beta Frontend",
                kind="service",
                token="beta",
                scope_signature=("service:beta",),
            ),
            SelectorItem(
                id="service:gamma",
                label="Gamma Worker",
                kind="service",
                token="gamma",
                scope_signature=("service:gamma",),
            ),
        ]
        app = selector._run_textual_selector(  # type: ignore[assignment]
            prompt="Restart",
            options=options,
            multi=True,
            emit=None,
            build_only=True,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            list_view = app.query_one("#selector-list")
            self.assertEqual(list_view.index, 0)
            await pilot.press("up")
            await pilot.pause()
            self.assertEqual(list_view.index, 0)
            await pilot.press("down")
            await pilot.pause()
            self.assertEqual(list_view.index, 1)
            app.exit(None)

    async def test_vim_style_navigation_keys_move_cursor(self) -> None:
        options = [
            SelectorItem(
                id="service:alpha",
                label="Alpha Backend",
                kind="service",
                token="alpha",
                scope_signature=("service:alpha",),
            ),
            SelectorItem(
                id="service:beta",
                label="Beta Frontend",
                kind="service",
                token="beta",
                scope_signature=("service:beta",),
            ),
            SelectorItem(
                id="service:gamma",
                label="Gamma Worker",
                kind="service",
                token="gamma",
                scope_signature=("service:gamma",),
            ),
        ]
        app = selector._run_textual_selector(  # type: ignore[assignment]
            prompt="Restart",
            options=options,
            multi=True,
            emit=None,
            build_only=True,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            list_view = app.query_one("#selector-list")
            self.assertEqual(list_view.index, 0)
            await pilot.press("j")
            await pilot.pause()
            self.assertEqual(list_view.index, 1)
            await pilot.press("k")
            await pilot.pause()
            self.assertEqual(list_view.index, 0)
            app.exit(None)

    async def test_escape_cancels_selector(self) -> None:
        options = [
            SelectorItem(
                id="service:alpha",
                label="Alpha Backend",
                kind="service",
                token="alpha",
                scope_signature=("service:alpha",),
            ),
            SelectorItem(
                id="service:beta",
                label="Beta Frontend",
                kind="service",
                token="beta",
                scope_signature=("service:beta",),
            ),
        ]
        app = selector._run_textual_selector(  # type: ignore[assignment]
            prompt="Run tests for",
            options=options,
            multi=True,
            emit=None,
            build_only=True,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            list_view = app.query_one("#selector-list")
            self.assertEqual(list_view.index, 0)
            await pilot.press("escape")
        self.assertIsNone(app.return_value)

    async def test_keyboard_navigation_recovers_after_focus_drift(self) -> None:
        options = [
            SelectorItem(
                id="service:alpha",
                label="Alpha Backend",
                kind="service",
                token="alpha",
                scope_signature=("service:alpha",),
            ),
            SelectorItem(
                id="service:beta",
                label="Beta Frontend",
                kind="service",
                token="beta",
                scope_signature=("service:beta",),
            ),
        ]
        app = selector._run_textual_selector(  # type: ignore[assignment]
            prompt="Restart",
            options=options,
            multi=True,
            emit=None,
            build_only=True,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#selector-filter")
            await pilot.press("down")
            await pilot.press("space")
            await pilot.press("enter")
        self.assertEqual(app.return_value, ["beta"])

    async def test_filter_accepts_focus_when_clicked(self) -> None:
        options = [
            SelectorItem(
                id="service:alpha",
                label="Alpha Backend",
                kind="service",
                token="alpha",
                scope_signature=("service:alpha",),
            ),
            SelectorItem(
                id="service:beta",
                label="Beta Frontend",
                kind="service",
                token="beta",
                scope_signature=("service:beta",),
            ),
        ]
        app = selector._run_textual_selector(
            prompt="Run tests for",
            options=options,
            multi=True,
            emit=None,
            build_only=True,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            filter_input = app.query_one("#selector-filter")
            self.assertFalse(filter_input.has_focus)
            await pilot.click("#selector-filter")
            await pilot.pause()
            self.assertTrue(filter_input.has_focus)
            app.exit(None)

    async def test_tab_cycles_focus_between_list_filter_and_buttons(self) -> None:
        options = [
            SelectorItem(
                id="service:alpha",
                label="Alpha Backend",
                kind="service",
                token="alpha",
                scope_signature=("service:alpha",),
            ),
            SelectorItem(
                id="service:beta",
                label="Beta Frontend",
                kind="service",
                token="beta",
                scope_signature=("service:beta",),
            ),
        ]
        app = selector._run_textual_selector(
            prompt="Run tests for",
            options=options,
            multi=True,
            emit=None,
            build_only=True,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            filter_input = app.query_one("#selector-filter")
            list_view = app.query_one("#selector-list")
            cancel_button = app.query_one("#btn-cancel")
            run_button = app.query_one("#btn-run")
            self.assertTrue(list_view.has_focus)
            await pilot.press("tab")
            await pilot.pause()
            self.assertTrue(cancel_button.has_focus)
            await pilot.press("tab")
            await pilot.pause()
            self.assertTrue(run_button.has_focus)
            await pilot.press("tab")
            await pilot.pause()
            self.assertTrue(filter_input.has_focus)
            await pilot.press("tab")
            await pilot.pause()
            self.assertTrue(list_view.has_focus)
            app.exit(None)

    async def test_mouse_click_selects_single_mode_without_enter(self) -> None:
        options = [
            SelectorItem(
                id="service:alpha",
                label="Alpha Backend",
                kind="service",
                token="alpha",
                scope_signature=("service:alpha",),
            ),
            SelectorItem(
                id="service:beta",
                label="Beta Frontend",
                kind="service",
                token="beta",
                scope_signature=("service:beta",),
            ),
        ]
        app = selector._run_textual_selector(  # type: ignore[assignment]
            prompt="Analyze",
            options=options,
            multi=False,
            emit=None,
            build_only=True,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#selector-row-1")
        self.assertEqual(app.return_value, ["beta"])

    async def test_enter_submits_focused_row_in_single_mode_without_explicit_toggle(self) -> None:
        options = [
            SelectorItem(
                id="service:alpha",
                label="Alpha Backend",
                kind="service",
                token="alpha",
                scope_signature=("service:alpha",),
            ),
            SelectorItem(
                id="service:beta",
                label="Beta Frontend",
                kind="service",
                token="beta",
                scope_signature=("service:beta",),
            ),
        ]
        app = selector._run_textual_selector(  # type: ignore[assignment]
            prompt="Analyze",
            options=options,
            multi=False,
            emit=None,
            build_only=True,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()
            await pilot.press("enter")
        self.assertEqual(app.return_value, ["beta"])

    async def test_mouse_click_toggles_multi_row_once(self) -> None:
        options = [
            SelectorItem(
                id="service:alpha",
                label="Alpha Backend",
                kind="service",
                token="alpha",
                scope_signature=("service:alpha",),
            ),
            SelectorItem(
                id="service:beta",
                label="Beta Frontend",
                kind="service",
                token="beta",
                scope_signature=("service:beta",),
            ),
        ]
        app = selector._run_textual_selector(  # type: ignore[assignment]
            prompt="Run tests for",
            options=options,
            multi=True,
            emit=None,
            build_only=True,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#selector-row-1")
            await pilot.pause()
            self.assertTrue(app._rows[1].selected)  # type: ignore[attr-defined]
            await pilot.press("enter")
        self.assertEqual(app.return_value, ["beta"])

    async def test_repeated_click_toggles_multi_row_selection(self) -> None:
        options = [
            SelectorItem(
                id="service:alpha",
                label="Alpha Backend",
                kind="service",
                token="alpha",
                scope_signature=("service:alpha",),
            ),
            SelectorItem(
                id="service:beta",
                label="Beta Frontend",
                kind="service",
                token="beta",
                scope_signature=("service:beta",),
            ),
        ]
        app = selector._run_textual_selector(  # type: ignore[assignment]
            prompt="Run tests for",
            options=options,
            multi=True,
            emit=None,
            build_only=True,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#selector-row-1")
            await pilot.click("#selector-row-1")
            await pilot.pause()
            self.assertFalse(app._rows[1].selected)  # type: ignore[attr-defined]
            await pilot.click("#selector-row-1")
            await pilot.pause()
            self.assertTrue(app._rows[1].selected)  # type: ignore[attr-defined]
            await pilot.press("enter")
        self.assertEqual(app.return_value, ["beta"])

    async def test_enter_from_empty_filter_does_not_submit_without_selection(self) -> None:
        options = [
            SelectorItem(
                id="service:alpha",
                label="Alpha Backend",
                kind="service",
                token="alpha",
                scope_signature=("service:alpha",),
            ),
            SelectorItem(
                id="service:beta",
                label="Beta Frontend",
                kind="service",
                token="beta",
                scope_signature=("service:beta",),
            ),
        ]
        app = selector._run_textual_selector(  # type: ignore[assignment]
            prompt="Run tests for",
            options=options,
            multi=True,
            emit=None,
            build_only=True,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#selector-filter")
            await pilot.press("enter")
            await pilot.pause()
            self.assertIsNone(app.return_value)
            self.assertFalse(app._rows[0].selected)  # type: ignore[attr-defined]
            self.assertFalse(app._rows[1].selected)  # type: ignore[attr-defined]
            status = app.query_one("#selector-status")
            self.assertEqual(
                str(status.render()),
                "No items were selected. Press Space or click to select at least one.",
            )
            self.assertIn("selector-status-error", status.classes)
            await asyncio.sleep(3.2)
            await pilot.pause()
            self.assertNotIn("selector-status-error", status.classes)
            self.assertIn("0 selected", str(status.render()))
            await pilot.press("escape")
        self.assertIsNone(app.return_value)

    async def test_space_toggles_even_when_filter_has_focus(self) -> None:
        options = [
            SelectorItem(
                id="service:alpha",
                label="Alpha Backend",
                kind="service",
                token="alpha",
                scope_signature=("service:alpha",),
            ),
            SelectorItem(
                id="service:beta",
                label="Beta Frontend",
                kind="service",
                token="beta",
                scope_signature=("service:beta",),
            ),
        ]
        app = selector._run_textual_selector(  # type: ignore[assignment]
            prompt="Run tests for",
            options=options,
            multi=True,
            emit=None,
            build_only=True,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#selector-filter")
            await pilot.press("space")
            await pilot.press("enter")
        self.assertEqual(app.return_value, ["alpha"])

    async def test_exclusive_multi_option_clears_other_selected_rows(self) -> None:
        options = [
            SelectorItem(
                id="scope:backend",
                label="Backend",
                kind="project",
                token="__PROJECT__:Backend",
                scope_signature=("scope:backend",),
            ),
            SelectorItem(
                id="scope:frontend",
                label="Frontend",
                kind="project",
                token="__PROJECT__:Frontend",
                scope_signature=("scope:frontend",),
            ),
            SelectorItem(
                id="scope:failed",
                label="Failed tests",
                kind="project",
                token="__PROJECT__:Failed tests",
                scope_signature=("scope:failed",),
            ),
        ]
        app = selector._run_textual_selector(  # type: ignore[assignment]
            prompt="Choose test scope",
            options=options,
            multi=True,
            exclusive_token="__PROJECT__:Failed tests",
            emit=None,
            build_only=True,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("space")
            await pilot.press("down")
            await pilot.press("space")
            self.assertTrue(app._rows[0].selected)  # type: ignore[attr-defined]
            self.assertTrue(app._rows[1].selected)  # type: ignore[attr-defined]
            await pilot.press("down")
            await pilot.press("space")
            await pilot.pause()
            self.assertFalse(app._rows[0].selected)  # type: ignore[attr-defined]
            self.assertFalse(app._rows[1].selected)  # type: ignore[attr-defined]
            self.assertTrue(app._rows[2].selected)  # type: ignore[attr-defined]
            await pilot.press("up")
            await pilot.press("space")
            await pilot.pause()
            self.assertTrue(app._rows[1].selected)  # type: ignore[attr-defined]
            self.assertFalse(app._rows[2].selected)  # type: ignore[attr-defined]
            await pilot.press("enter")
        self.assertEqual(app.return_value, ["__PROJECT__:Frontend"])


class PlanningSelectorResponsivenessTests(unittest.IsolatedAsyncioTestCase):
    async def test_planning_filter_accepts_focus_when_clicked(self) -> None:
        app = select_planning_counts_textual(
            planning_files=["backend/task-a.md", "frontend/task-b.md"],
            selected_counts={"backend/task-a.md": 1, "frontend/task-b.md": 0},
            existing_counts={"backend/task-a.md": 0, "frontend/task-b.md": 0},
            emit=None,
            build_only=True,
        )
        assert app is not None
        async with app.run_test() as pilot:
            await pilot.pause()
            filter_input = app.query_one("#planning-filter")
            self.assertFalse(filter_input.has_focus)
            await pilot.click("#planning-filter")
            await pilot.pause()
            self.assertTrue(filter_input.has_focus)
            app.exit(None)

    async def test_planning_tab_cycles_focus_between_list_filter_and_buttons(self) -> None:
        app = select_planning_counts_textual(
            planning_files=["backend/task-a.md", "frontend/task-b.md"],
            selected_counts={"backend/task-a.md": 1, "frontend/task-b.md": 0},
            existing_counts={"backend/task-a.md": 0, "frontend/task-b.md": 0},
            emit=None,
            build_only=True,
        )
        assert app is not None
        async with app.run_test() as pilot:
            await pilot.pause()
            filter_input = app.query_one("#planning-filter")
            list_view = app.query_one("#planning-list")
            cancel_button = app.query_one("#btn-cancel")
            run_button = app.query_one("#btn-run")
            self.assertTrue(list_view.has_focus)
            await pilot.press("tab")
            await pilot.pause()
            self.assertTrue(cancel_button.has_focus)
            await pilot.press("tab")
            await pilot.pause()
            self.assertTrue(run_button.has_focus)
            await pilot.press("tab")
            await pilot.pause()
            self.assertTrue(filter_input.has_focus)
            await pilot.press("tab")
            await pilot.pause()
            self.assertTrue(list_view.has_focus)
            app.exit(None)

    async def test_planning_tab_skips_disabled_run_button(self) -> None:
        app = select_planning_counts_textual(
            planning_files=["backend/task-a.md", "frontend/task-b.md"],
            selected_counts={"backend/task-a.md": 0, "frontend/task-b.md": 0},
            existing_counts={"backend/task-a.md": 0, "frontend/task-b.md": 0},
            emit=None,
            build_only=True,
        )
        assert app is not None
        async with app.run_test() as pilot:
            await pilot.pause()
            filter_input = app.query_one("#planning-filter")
            list_view = app.query_one("#planning-list")
            cancel_button = app.query_one("#btn-cancel")
            run_button = app.query_one("#btn-run")
            self.assertTrue(run_button.disabled)
            self.assertTrue(list_view.has_focus)
            await pilot.press("tab")
            await pilot.pause()
            self.assertTrue(cancel_button.has_focus)
            await pilot.press("tab")
            await pilot.pause()
            self.assertTrue(filter_input.has_focus)
            await pilot.press("tab")
            await pilot.pause()
            self.assertTrue(list_view.has_focus)
            self.assertFalse(run_button.has_focus)
            app.exit(None)


class SelectorDriverTracePolicyTests(unittest.TestCase):
    def test_driver_trace_defaults_on_in_deep_mode(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "ENVCTL_DEBUG_UI_MODE": "deep",
                "ENVCTL_DEBUG_SELECTOR_KEYS": "1",
            },
            clear=False,
        ):
            self.assertTrue(selector._selector_driver_trace_enabled(None))

    def test_driver_trace_enables_with_explicit_flag(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "ENVCTL_DEBUG_UI_MODE": "deep",
                "ENVCTL_DEBUG_SELECTOR_KEYS": "1",
                "ENVCTL_DEBUG_SELECTOR_DRIVER_KEYS": "1",
            },
            clear=False,
        ):
            self.assertTrue(selector._selector_driver_trace_enabled(None))

    def test_driver_trace_disables_with_explicit_off_flag(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "ENVCTL_DEBUG_UI_MODE": "deep",
                "ENVCTL_DEBUG_SELECTOR_KEYS": "1",
                "ENVCTL_DEBUG_SELECTOR_DRIVER_KEYS": "0",
            },
            clear=False,
        ):
            self.assertFalse(selector._selector_driver_trace_enabled(None))

    def test_prompt_toolkit_io_probe_returns_tuple_when_disabled(self) -> None:
        with selector._instrument_prompt_toolkit_posix_io(  # type: ignore[attr-defined]
            emit=None,
            deep_debug=True,
            enabled=False,
            selector_id="test_selector",
        ) as probe_tuple:
            self.assertIsInstance(probe_tuple, tuple)
            self.assertEqual(len(probe_tuple), 1)
            self.assertEqual(probe_tuple[0](), {})


class TextualSelectorFallbackRecoveryTests(unittest.TestCase):
    def test_fallback_values_prefers_selected_then_focused_then_first_visible(self) -> None:
        options = [
            SelectorItem(
                id="service:alpha",
                label="Alpha Backend",
                kind="service",
                token="alpha",
                scope_signature=("service:alpha",),
            ),
            SelectorItem(
                id="service:beta",
                label="Beta Frontend",
                kind="service",
                token="beta",
                scope_signature=("service:beta",),
            ),
        ]
        app = selector._run_textual_selector(  # type: ignore[assignment]
            prompt="Run tests for",
            options=options,
            multi=True,
            emit=None,
            build_only=True,
        )
        # No selected row and no focused index yet -> first visible fallback.
        self.assertEqual(app.fallback_values(), ["alpha"])  # type: ignore[attr-defined]


if __name__ == "__main__":
    unittest.main()
