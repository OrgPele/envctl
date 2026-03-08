from __future__ import annotations

import tempfile
import unittest
from collections import OrderedDict
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.planning import (
    list_planning_files,
    planning_existing_counts,
    planning_feature_name,
    resolve_planning_files,
    select_projects_for_plan_files,
)


class PlanningSelectionTests(unittest.TestCase):
    def test_list_planning_files_excludes_done_readme_and_plan_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            planning_dir = Path(tmpdir) / "docs" / "planning"
            (planning_dir / "backend").mkdir(parents=True, exist_ok=True)
            (planning_dir / "Done" / "backend").mkdir(parents=True, exist_ok=True)
            (planning_dir / "done" / "frontend").mkdir(parents=True, exist_ok=True)
            (planning_dir / "backend" / "task.md").write_text("# task\n", encoding="utf-8")
            (planning_dir / "backend" / "README.md").write_text("# readme\n", encoding="utf-8")
            (planning_dir / "backend" / "task_PLAN.md").write_text("# plan\n", encoding="utf-8")
            (planning_dir / "Done" / "backend" / "old.md").write_text("# done\n", encoding="utf-8")
            (planning_dir / "done" / "frontend" / "old.md").write_text("# done\n", encoding="utf-8")

            files = list_planning_files(planning_dir)

            self.assertEqual(files, ["backend/task.md"])

    def test_resolve_planning_files_accepts_repo_and_planning_prefixes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            planning_dir = repo / "work" / "plans"
            planning_dir.mkdir(parents=True, exist_ok=True)
            available = ["backend/task.md"]
            selection_raw = (
                f"backend/task,work/plans/backend/task,{planning_dir / 'backend' / 'task.md'}"
            )

            counts = resolve_planning_files(
                selection_raw=selection_raw,
                planning_files=available,
                base_dir=repo,
                planning_dir=planning_dir,
            )

            self.assertEqual(counts, OrderedDict([("backend/task.md", 3)]))

    def test_select_projects_for_plan_files_respects_requested_count(self) -> None:
        projects = [
            ("feature_a_task-2", Path("/tmp/feature_a_task/2")),
            ("feature_a_task-1", Path("/tmp/feature_a_task/1")),
            ("feature_b_task-1", Path("/tmp/feature_b_task/1")),
        ]
        plan_counts = OrderedDict(
            [
                ("feature-a/task.md", 1),
                ("feature-b/task.md", 1),
            ]
        )

        selected = select_projects_for_plan_files(projects=projects, plan_counts=plan_counts)

        self.assertEqual([name for name, _root in selected], ["feature_a_task-1", "feature_b_task-1"])

    def test_planning_feature_name_matches_shell_slugify_underscore_shape(self) -> None:
        self.assertEqual(
            planning_feature_name("Implementations/Voice provider dual runtime.md"),
            "implementations_voice_provider_dual_runtime",
        )

    def test_planning_existing_counts_reflect_discovered_iterations(self) -> None:
        projects = [
            ("backend_task-1", Path("/tmp/backend_task/1")),
            ("backend_task-2", Path("/tmp/backend_task/2")),
            ("frontend_task-1", Path("/tmp/frontend_task/1")),
        ]
        planning_files = ["backend/task.md", "frontend/task.md", "ops/missing.md"]

        counts = planning_existing_counts(projects=projects, planning_files=planning_files)

        self.assertEqual(counts["backend/task.md"], 2)
        self.assertEqual(counts["frontend/task.md"], 1)
        self.assertEqual(counts["ops/missing.md"], 0)


if __name__ == "__main__":
    unittest.main()
