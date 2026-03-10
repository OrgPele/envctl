from __future__ import annotations

from dataclasses import dataclass
import unittest

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.ui.textual.list_controller import TextualListController


@dataclass
class _Row:
    visible: bool = True
    selected: bool = False


class TextualSelectorSharedBehaviorTests(unittest.TestCase):
    def test_controller_tracks_focus_and_cursor_bounds(self) -> None:
        controller = TextualListController([_Row(), _Row(), _Row()], initial_model_index=2)
        checkpoint = controller.capture_render_checkpoint(view_index=1, filter_has_focus=False)
        controller.index_map = [0, 2]

        self.assertEqual(controller.restore_view_index(checkpoint), 1)
        self.assertEqual(controller.focused_model_index(1), 2)
        self.assertEqual(controller.cursor_up(0), 0)
        self.assertEqual(controller.cursor_down(0), 1)
        self.assertEqual(controller.ensure_list_index(None), 0)

    def test_controller_cycles_focus_and_toggles_visible_rows(self) -> None:
        rows = [
            _Row(visible=True, selected=False),
            _Row(visible=True, selected=True),
            _Row(visible=False, selected=False),
        ]
        controller = TextualListController(rows)

        self.assertEqual(controller.cycle_focus_target(filter_has_focus=False), "filter")
        self.assertEqual(controller.cycle_focus_target(filter_has_focus=True), "list")

        should_activate = controller.apply_visible_toggle(
            is_visible=lambda row: row.visible,
            is_active=lambda row: row.selected,
            activate=lambda row: setattr(row, "selected", True),
            deactivate=lambda row: setattr(row, "selected", False),
        )
        self.assertTrue(should_activate)
        self.assertEqual([row.selected for row in rows], [True, True, False])


if __name__ == "__main__":
    unittest.main()
