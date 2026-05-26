from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
from typing import Any

from envctl_engine.planning.worktree_creation_flow import (
    create_feature_worktrees_result,
    create_single_worktree,
)


class WorktreeCreationFlowTests(unittest.TestCase):
    def test_create_single_worktree_wires_success_artifacts_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            feature_root = Path(tmpdir) / "trees" / "feature-a"
            calls: list[tuple[str, object]] = []

            error = create_single_worktree(
                feature="feature-a",
                iteration="2",
                preferred_tree_root_for_feature=lambda feature: calls.append(("feature", feature)) or feature_root,
                command_env=lambda **kwargs: calls.append(("env", kwargs)) or {"ENV": "1"},
                run_worktree_add=lambda **kwargs: calls.append(("add", kwargs))
                or subprocess.CompletedProcess(args=["git"], returncode=0),
                recover_partial_worktree_creation=self._unexpected,
                link_repo_local_shared_artifacts=lambda **kwargs: calls.append(("link", kwargs)),
                prepare_worktree_code_intelligence=lambda **kwargs: calls.append(("cgc", kwargs)),
                write_worktree_provenance=lambda **kwargs: calls.append(("provenance", kwargs)),
                worktree_add_failure=self._unexpected,
            )

            target = feature_root / "2"
            self.assertIsNone(error)
            self.assertTrue(feature_root.is_dir())
            self.assertEqual(
                calls,
                [
                    ("feature", "feature-a"),
                    ("env", {"port": 0}),
                    (
                        "add",
                        {
                            "feature": "feature-a",
                            "iteration": "2",
                            "target": target,
                            "env": {"ENV": "1"},
                        },
                    ),
                    ("link", {"target": target}),
                    ("cgc", {"target": target}),
                    ("provenance", {"target": target}),
                ],
            )

    def test_create_single_worktree_recovers_partial_failure_without_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            feature_root = Path(tmpdir) / "trees" / "feature-a"
            calls: list[str] = []
            failed = subprocess.CompletedProcess(args=["git"], returncode=1)

            error = create_single_worktree(
                feature="feature-a",
                iteration="1",
                preferred_tree_root_for_feature=lambda _feature: feature_root,
                command_env=lambda **_kwargs: {},
                run_worktree_add=lambda **_kwargs: failed,
                recover_partial_worktree_creation=lambda **kwargs: calls.append(f"recover:{kwargs['target'].name}") or True,
                link_repo_local_shared_artifacts=lambda **_kwargs: calls.append("link"),
                prepare_worktree_code_intelligence=lambda **_kwargs: calls.append("cgc"),
                write_worktree_provenance=lambda **_kwargs: calls.append("provenance"),
                worktree_add_failure=self._unexpected,
            )

            self.assertIsNone(error)
            self.assertEqual(calls, ["recover:1", "link", "cgc", "provenance"])

    def test_create_feature_worktrees_assigns_iterations_provenance_tasks_and_cli_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            feature_root = root / "trees" / "feature-a"
            (feature_root / "1").mkdir(parents=True)
            planning_root = root / "todo" / "plans"
            planning_root.mkdir(parents=True)
            plan_path = planning_root / "feature.md"
            plan_path.write_text("# Plan\n", encoding="utf-8")
            calls: list[tuple[str, object]] = []

            result = create_feature_worktrees_result(
                feature="feature-a",
                count=2,
                plan_file="feature.md",
                created_for_fresh_ai_launch=True,
                launch_transport="tmux",
                preferred_tree_root_for_feature=lambda _feature: feature_root,
                planning_root=lambda: planning_root,
                command_env=lambda **kwargs: calls.append(("env", kwargs)) or {"PLAN_FILE": kwargs["extra"]["PLAN_FILE"]},
                run_worktree_add=lambda **kwargs: calls.append(("add", kwargs))
                or subprocess.CompletedProcess(args=["git"], returncode=0),
                recover_partial_worktree_creation=self._unexpected,
                write_worktree_provenance=lambda **kwargs: calls.append(("provenance", kwargs)),
                prepare_worktree_code_intelligence=lambda **kwargs: calls.append(("cgc", kwargs)),
                worktree_add_failure=self._unexpected,
                seed_main_task_from_plan=lambda **kwargs: calls.append(("seed", kwargs)),
                next_available_iteration=lambda existing_iters: min(set(range(1, 5)) - set(existing_iters)),
                worktree_project_name=lambda **kwargs: f"{kwargs['feature']}-{kwargs['iteration']}",
                env={"ENVCTL_PLAN_AGENT_CLI": "both"},
                config_raw={},
            )

            self.assertIsNone(result.error)
            self.assertEqual([created.name for created in result.created_worktrees], ["feature-a-2", "feature-a-3"])
            self.assertEqual([created.cli for created in result.created_worktrees], ["codex", "opencode"])
            self.assertEqual([created.plan_file for created in result.created_worktrees], ["feature.md", "feature.md"])
            self.assertEqual([created.root for created in result.created_worktrees], [(feature_root / "2").resolve(), (feature_root / "3").resolve()])
            self.assertEqual(calls[0], ("env", {"port": 0, "extra": {"PLAN_FILE": str(plan_path)}}))
            self.assertEqual(
                [call for call in calls if call[0] == "provenance"],
                [
                    (
                        "provenance",
                        {
                            "target": feature_root / "2",
                            "plan_file": "feature.md",
                            "created_for_fresh_ai_launch": True,
                            "launch_transport": "tmux",
                        },
                    ),
                    (
                        "provenance",
                        {
                            "target": feature_root / "3",
                            "plan_file": "feature.md",
                            "created_for_fresh_ai_launch": True,
                            "launch_transport": "tmux",
                        },
                    ),
                ],
            )
            self.assertEqual(
                [call for call in calls if call[0] == "seed"],
                [
                    ("seed", {"target": feature_root / "2", "plan_path": plan_path}),
                    ("seed", {"target": feature_root / "3", "plan_path": plan_path}),
                ],
            )

    def test_create_feature_worktrees_returns_partial_result_on_unrecovered_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            feature_root = root / "trees" / "feature-a"
            planning_root = root / "todo" / "plans"
            planning_root.mkdir(parents=True)
            attempts: list[int] = []
            seeded: list[Path] = []

            def run_worktree_add(**kwargs: Any) -> subprocess.CompletedProcess[Any]:
                iteration = int(kwargs["iteration"])
                attempts.append(iteration)
                return subprocess.CompletedProcess(args=["git"], returncode=0 if iteration == 1 else 1)

            result = create_feature_worktrees_result(
                feature="feature-a",
                count=2,
                plan_file="feature.md",
                preferred_tree_root_for_feature=lambda _feature: feature_root,
                planning_root=lambda: planning_root,
                command_env=lambda **_kwargs: {},
                run_worktree_add=run_worktree_add,
                recover_partial_worktree_creation=lambda **_kwargs: False,
                write_worktree_provenance=lambda **_kwargs: None,
                prepare_worktree_code_intelligence=lambda **_kwargs: None,
                worktree_add_failure=lambda **kwargs: f"failed {kwargs['iteration']}",
                seed_main_task_from_plan=lambda **kwargs: seeded.append(kwargs["target"]),
                next_available_iteration=lambda existing_iters: min(set(range(1, 5)) - set(existing_iters)),
                worktree_project_name=lambda **kwargs: f"{kwargs['feature']}-{kwargs['iteration']}",
                env={},
                config_raw={},
            )

            self.assertEqual(attempts, [1, 2])
            self.assertEqual(result.error, "failed 2")
            self.assertEqual([created.name for created in result.created_worktrees], ["feature-a-1"])
            self.assertEqual(seeded, [feature_root / "1"])

    def test_create_feature_worktrees_zero_count_is_noop(self) -> None:
        result = create_feature_worktrees_result(
            feature="feature-a",
            count=0,
            plan_file="feature.md",
            preferred_tree_root_for_feature=self._unexpected,
            planning_root=self._unexpected,
            command_env=self._unexpected,
            run_worktree_add=self._unexpected,
            recover_partial_worktree_creation=self._unexpected,
            write_worktree_provenance=self._unexpected,
            prepare_worktree_code_intelligence=self._unexpected,
            worktree_add_failure=self._unexpected,
            seed_main_task_from_plan=self._unexpected,
            next_available_iteration=self._unexpected,
            worktree_project_name=self._unexpected,
            env={},
            config_raw={},
        )

        self.assertEqual(result.raw_projects, [])
        self.assertEqual(result.created_worktrees, ())
        self.assertIsNone(result.error)

    def _unexpected(self, *args: Any, **kwargs: Any) -> Any:
        self.fail(f"unexpected call args={args!r} kwargs={kwargs!r}")


if __name__ == "__main__":
    unittest.main()
