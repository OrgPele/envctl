from __future__ import annotations

import unittest
from types import SimpleNamespace

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.ui.selector_model import SelectorContext, build_grouped_selector_items, build_project_selector_items


class SelectorModelTests(unittest.TestCase):
    def test_project_items_hide_all_when_only_one_project(self) -> None:
        context = SelectorContext(
            projects=[SimpleNamespace(name="Main")],
            allow_all=True,
            allow_untested=False,
            mode="project",
        )
        result = build_project_selector_items(context)

        labels = [item.label for item in result.items]
        self.assertEqual(labels, ["Main"])
        self.assertNotIn("All projects", labels)

    def test_project_items_hide_untested_when_no_subset(self) -> None:
        context = SelectorContext(
            projects=[SimpleNamespace(name="Main"), SimpleNamespace(name="Feature-A")],
            allow_all=True,
            allow_untested=True,
            untested_projects=["Main", "Feature-A"],
            mode="project",
        )
        result = build_project_selector_items(context)

        labels = [item.label for item in result.items]
        self.assertNotIn("Run untested projects", labels)
        self.assertIn("All projects", labels)

    def test_grouped_items_suppress_duplicate_all_scope_for_single_project(self) -> None:
        context = SelectorContext(
            projects=[SimpleNamespace(name="Main")],
            services=["Main Backend", "Main Frontend"],
            allow_all=True,
            mode="grouped",
        )
        result = build_grouped_selector_items(context)

        labels = [item.label for item in result.items]
        self.assertNotIn("All services", labels)
        self.assertIn("Main (all)", labels)
        self.assertIn("Main Backend", labels)
        self.assertIn("Main Frontend", labels)

    def test_grouped_items_suppress_project_group_when_it_matches_single_service(self) -> None:
        context = SelectorContext(
            projects=[SimpleNamespace(name="Main")],
            services=["Main Backend"],
            allow_all=True,
            mode="grouped",
        )
        result = build_grouped_selector_items(context)

        labels = [item.label for item in result.items]
        self.assertEqual(labels, ["Main Backend"])


if __name__ == "__main__":
    unittest.main()
