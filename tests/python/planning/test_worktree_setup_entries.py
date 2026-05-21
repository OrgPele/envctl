from __future__ import annotations

from pathlib import Path
import unittest

from envctl_engine.planning.worktree_setup_entries import (
    apply_multi_setup_entry,
    apply_single_setup_entry,
    coerce_setup_entries,
    resolve_included_setup_worktrees,
)


class WorktreeSetupEntriesTests(unittest.TestCase):
    def test_coerce_setup_entries_validates_feature_and_value_payloads(self) -> None:
        self.assertEqual(
            coerce_setup_entries(
                flags={"setup_worktrees": [{"feature": "backend", "count": "2"}]},
                flag_name="setup_worktrees",
                value_name="count",
            ),
            [("backend", "2")],
        )

        with self.assertRaisesRegex(RuntimeError, "Invalid feature name"):
            coerce_setup_entries(
                flags={"setup_worktrees": [{"feature": "../backend", "count": "2"}]},
                flag_name="setup_worktrees",
                value_name="count",
            )

        with self.assertRaisesRegex(RuntimeError, "Missing count"):
            coerce_setup_entries(
                flags={"setup_worktrees": [{"feature": "backend", "count": ""}]},
                flag_name="setup_worktrees",
                value_name="count",
            )

    def test_resolve_included_setup_worktrees_matches_names_and_feature_iterations(self) -> None:
        selected, missing = resolve_included_setup_worktrees(
            raw_projects=[
                ("backend-1", Path("/repo/trees/backend/1")),
                ("backend-2", Path("/repo/trees/backend/2")),
                ("frontend-1", Path("/repo/trees/frontend/1")),
            ],
            setup_features=["backend"],
            selected_names={"backend-1"},
            include_tokens=["FRONTEND-1", "2", "missing"],
        )

        self.assertEqual(selected, {"backend-1", "backend-2", "frontend-1"})
        self.assertEqual(missing, ["missing"])

    def test_apply_multi_setup_entry_creates_requested_count_and_returns_new_candidates(self) -> None:
        updates: list[str] = []
        created: list[tuple[str, int, str]] = []
        discovered_projects = [("backend-1", Path("/repo/trees/backend/1")), ("backend-2", Path("/repo/trees/backend/2"))]

        raw_projects, selected = apply_multi_setup_entry(
            feature="backend",
            count_raw="2",
            raw_projects=[("backend-1", Path("/repo/trees/backend/1"))],
            feature_project_candidates=lambda projects, feature: [
                project for project in projects if project[0].startswith(f"{feature}-")
            ],
            update=lambda message: updates.append(message),
            create_feature_worktrees=lambda *, feature, count, plan_file: created.append((feature, count, plan_file))
            or None,
            discover_tree_projects=lambda: discovered_projects,
        )

        self.assertEqual(raw_projects, discovered_projects)
        self.assertEqual(selected, {"backend-2"})
        self.assertEqual(created, [("backend", 2, "_setup/backend.md")])
        self.assertEqual(updates, ["Setting up 2 worktree(s) for backend..."])

    def test_apply_single_setup_entry_rejects_existing_without_policy_and_recreates_when_requested(self) -> None:
        deleted: list[Path] = []
        created: list[tuple[str, str]] = []

        with self.assertRaisesRegex(RuntimeError, "already exists"):
            apply_single_setup_entry(
                feature="backend",
                iteration_raw="1",
                raw_projects=[("backend-1", Path("/repo/trees/backend/1"))],
                preferred_tree_root_for_feature=lambda feature: Path("/repo/trees") / feature,
                trees_root_for_worktree=lambda target: target.parents[1],
                delete_worktree=lambda **_kwargs: (True, "deleted"),
                create_single_worktree=lambda **kwargs: created.append((kwargs["feature"], kwargs["iteration"]))
                or None,
                discover_tree_projects=lambda: [("backend-1", Path("/repo/trees/backend/1"))],
                update=lambda _message: None,
                repo_root=Path("/repo"),
                process_runner=object(),
                setup_worktree_existing=False,
                setup_worktree_recreate=False,
                path_exists=lambda _path: True,
            )

        raw_projects, selected = apply_single_setup_entry(
            feature="backend",
            iteration_raw="1",
            raw_projects=[("backend-1", Path("/repo/trees/backend/1"))],
            preferred_tree_root_for_feature=lambda feature: Path("/repo/trees") / feature,
            trees_root_for_worktree=lambda target: target.parents[1],
            delete_worktree=lambda *, worktree_root, **_kwargs: deleted.append(worktree_root) or (True, "deleted"),
            create_single_worktree=lambda **kwargs: created.append((kwargs["feature"], kwargs["iteration"])) or None,
            discover_tree_projects=lambda: [("backend-1", Path("/repo/trees/backend/1"))],
            update=lambda _message: None,
            repo_root=Path("/repo"),
            process_runner=object(),
            setup_worktree_existing=False,
            setup_worktree_recreate=True,
            path_exists=lambda path: path not in deleted,
        )

        self.assertEqual(raw_projects, [("backend-1", Path("/repo/trees/backend/1"))])
        self.assertEqual(selected, "backend-1")
        self.assertEqual(deleted, [Path("/repo/trees/backend/1")])
        self.assertEqual(created, [("backend", "1")])


if __name__ == "__main__":
    unittest.main()
