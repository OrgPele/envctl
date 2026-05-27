from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from envctl_engine.planning.worktree_selection_memory import (
    initial_plan_selected_counts,
    load_plan_selection_memory,
    plan_selection_memory_path,
    save_plan_selection_memory,
)


class WorktreeSelectionMemoryTests(unittest.TestCase):
    def test_plan_selection_memory_path_uses_runtime_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_root = Path(tmpdir) / "runtime"

            self.assertEqual(
                plan_selection_memory_path(runtime_root=runtime_root),
                runtime_root / "planning_selection.json",
            )

    def test_load_plan_selection_memory_prefers_current_file_and_filters_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime_root = root / "runtime"
            legacy_root = root / "legacy"
            runtime_root.mkdir()
            legacy_root.mkdir()
            (runtime_root / "planning_selection.json").write_text(
                json.dumps(
                    {
                        "selected_counts": {
                            "feature/a.md": "2",
                            "feature/b.md": 0,
                            "feature/c.md": -1,
                            "feature/d.md": "invalid",
                        }
                    }
                ),
                encoding="utf-8",
            )
            (legacy_root / "planning_selection.json").write_text(
                json.dumps({"selected_counts": {"feature/a.md": 9}}),
                encoding="utf-8",
            )

            self.assertEqual(
                load_plan_selection_memory(runtime_root=runtime_root, runtime_legacy_root=legacy_root),
                {"feature/a.md": 2, "feature/b.md": 0},
            )

    def test_load_plan_selection_memory_falls_back_to_legacy_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime_root = root / "runtime"
            legacy_root = root / "legacy"
            runtime_root.mkdir()
            legacy_root.mkdir()
            (runtime_root / "planning_selection.json").write_text("not json", encoding="utf-8")
            (legacy_root / "planning_selection.json").write_text(
                json.dumps({"selected_counts": {"feature/a.md": "3"}}),
                encoding="utf-8",
            )

            self.assertEqual(
                load_plan_selection_memory(runtime_root=runtime_root, runtime_legacy_root=legacy_root),
                {"feature/a.md": 3},
            )

    def test_save_plan_selection_memory_writes_sorted_positive_counts_to_current_and_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime_root = root / "runtime"
            legacy_root = root / "legacy"
            runtime_root.mkdir()

            save_plan_selection_memory(
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                selected_counts={"z.md": 2, "a.md": 1, "zero.md": 0},
            )

            current_payload = json.loads((runtime_root / "planning_selection.json").read_text(encoding="utf-8"))
            legacy_payload = json.loads((legacy_root / "planning_selection.json").read_text(encoding="utf-8"))
            self.assertEqual(current_payload, legacy_payload)
            self.assertEqual(list(current_payload["selected_counts"].items()), [("a.md", 1), ("z.md", 2)])
            self.assertIsInstance(current_payload["saved_at"], str)

    def test_initial_plan_selected_counts_uses_current_existing_counts_only(self) -> None:
        self.assertEqual(
            initial_plan_selected_counts(
                planning_files=["feature/a.md", "feature/b.md", "feature/c.md"],
                existing_counts={"feature/a.md": 2},
                remembered_counts={"feature/a.md": 9, "feature/b.md": 4, "feature/c.md": -1},
            ),
            {"feature/a.md": 2, "feature/b.md": 0, "feature/c.md": 0},
        )


if __name__ == "__main__":
    unittest.main()
