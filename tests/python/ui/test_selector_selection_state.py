from __future__ import annotations

import unittest

from envctl_engine.ui.selector_model import SelectorItem
from envctl_engine.ui.textual.screens.selector.selection_state import (
    apply_selector_filter,
    build_selector_rows,
    fallback_selector_values,
    selector_submit_values,
    selector_visibility_counts,
    select_selector_model_index,
    selected_selector_values,
    selector_row_classes,
    selector_row_text,
    toggle_selector_model_index,
    toggle_visible_selector_rows,
)


def _item(label: str, token: str, *, kind: str = "service") -> SelectorItem:
    return SelectorItem(
        id=f"{kind}:{token}",
        label=label,
        kind=kind,
        token=token,
        scope_signature=(f"{kind}:{token}",),
    )


class SelectorSelectionStateTests(unittest.TestCase):
    def test_build_rows_tracks_initial_single_selection_without_duplicates(self) -> None:
        rows, initial_index = build_selector_rows(
            [_item("Alpha", "alpha"), _item("Beta", "beta"), _item("Gamma", "gamma")],
            initial_token_set={"beta", "gamma"},
            multi=False,
        )

        self.assertEqual(initial_index, 1)
        self.assertEqual([row.selected for row in rows], [False, True, False])

    def test_row_rendering_includes_selection_marker_kind_and_safe_classes(self) -> None:
        rows, _ = build_selector_rows([_item("API", "api", kind="backend_service")], set(), multi=True)
        self.assertEqual(selector_row_text(rows[0]), "○ API  (backend service)")
        self.assertIn("selector-row", selector_row_classes(rows[0]))
        self.assertIn("kind-backend-service", selector_row_classes(rows[0]))

        rows[0].selected = True
        self.assertEqual(selector_row_text(rows[0]), "● API  (backend service)")
        self.assertIn("selector-row-selected", selector_row_classes(rows[0]))

    def test_toggle_model_index_enforces_single_select_and_exclusive_multi_token(self) -> None:
        rows, _ = build_selector_rows(
            [_item("Backend", "backend"), _item("Frontend", "frontend"), _item("Failed", "failed")],
            set(),
            multi=True,
        )

        self.assertEqual(toggle_selector_model_index(rows, 0, multi=True, exclusive_token="failed"), rows[0])
        self.assertEqual(toggle_selector_model_index(rows, 1, multi=True, exclusive_token="failed"), rows[1])
        self.assertEqual(selected_selector_values(rows), ["backend", "frontend"])

        self.assertEqual(toggle_selector_model_index(rows, 2, multi=True, exclusive_token="failed"), rows[2])
        self.assertEqual(selected_selector_values(rows), ["failed"])

        self.assertEqual(toggle_selector_model_index(rows, 1, multi=True, exclusive_token="failed"), rows[1])
        self.assertEqual(selected_selector_values(rows), ["frontend"])

    def test_visible_toggle_respects_exclusive_token_and_empty_visibility(self) -> None:
        rows, _ = build_selector_rows(
            [_item("Backend", "backend"), _item("Frontend", "frontend"), _item("Failed", "failed")],
            {"failed"},
            multi=True,
        )

        self.assertTrue(toggle_visible_selector_rows(rows, multi=True, exclusive_token="failed"))
        self.assertEqual(selected_selector_values(rows), ["backend", "frontend"])

        for row in rows:
            row.visible = False
        self.assertIsNone(toggle_visible_selector_rows(rows, multi=True, exclusive_token="failed"))

    def test_filter_normalizes_query_and_updates_row_visibility(self) -> None:
        rows, _ = build_selector_rows(
            [_item("API Backend", "api"), _item("Worker", "worker"), _item("Frontend", "frontend")],
            set(),
            multi=True,
        )

        self.assertEqual(apply_selector_filter(rows, "  BACK  "), "back")
        self.assertEqual([row.visible for row in rows], [True, False, False])

        self.assertEqual(apply_selector_filter(rows, ""), "")
        self.assertEqual([row.visible for row in rows], [True, True, True])

    def test_visibility_counts_only_count_visible_selected_rows(self) -> None:
        rows, _ = build_selector_rows(
            [_item("Alpha", "alpha"), _item("Beta", "beta"), _item("Gamma", "gamma")],
            {"alpha", "gamma"},
            multi=True,
        )
        rows[1].visible = False
        rows[1].selected = True

        self.assertEqual(selector_visibility_counts(rows), (2, 2))

    def test_submit_values_select_focused_visible_row_for_single_select_fallback(self) -> None:
        rows, _ = build_selector_rows(
            [_item("Alpha", "alpha"), _item("Beta", "beta"), _item("Gamma", "gamma")],
            set(),
            multi=False,
        )
        rows[0].visible = False

        self.assertEqual(selector_submit_values(rows, multi=False, focused_index=0), [])
        self.assertEqual(selector_submit_values(rows, multi=False, focused_index=1), ["beta"])
        self.assertEqual([row.selected for row in rows], [False, True, False])

    def test_submit_values_preserve_existing_selection_and_multi_select_empty_state(self) -> None:
        rows, _ = build_selector_rows(
            [_item("Alpha", "alpha"), _item("Beta", "beta")],
            {"alpha"},
            multi=True,
        )

        self.assertEqual(selector_submit_values(rows, multi=True, focused_index=1), ["alpha"])

    def test_select_and_fallback_values_use_visible_rows_and_focus_hints(self) -> None:
        rows, _ = build_selector_rows(
            [_item("Alpha", "alpha"), _item("Beta", "beta"), _item("Gamma", "gamma")],
            set(),
            multi=False,
        )
        rows[0].visible = False

        self.assertEqual(fallback_selector_values(rows, focused_indexes=(None, 1, 2)), ["beta"])
        self.assertEqual(select_selector_model_index(rows, 2, multi=False), rows[2])
        self.assertEqual(selected_selector_values(rows), ["gamma"])
        self.assertEqual(fallback_selector_values(rows, focused_indexes=(1,)), ["gamma"])


if __name__ == "__main__":
    unittest.main()
