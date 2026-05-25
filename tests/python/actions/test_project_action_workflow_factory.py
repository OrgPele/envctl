from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from envctl_engine.actions import project_action_domain as domain
from envctl_engine.actions import project_action_workflow_factory


class ProjectActionWorkflowFactoryTests(unittest.TestCase):
    def test_workflow_runner_uses_named_factory_bridges_for_legacy_patch_points(self) -> None:
        report = object()
        context = domain.ActionProjectContext(
            repo_root=Path("/repo"),
            project_root=Path("/repo/worktree"),
            project_name="feature-a-1",
            env={},
        )
        original_plan = SimpleNamespace()

        with (
            patch("envctl_engine.actions.project_action_domain.probe_dirty_worktree", return_value=report) as probe,
            patch("envctl_engine.actions.project_action_domain._analysis_iterations", return_value=["1"]) as iterations,
            patch("envctl_engine.actions.project_action_domain._run_analyze_helper", return_value=0) as analyze,
            patch(
                "envctl_engine.actions.project_action_domain._original_plan_markdown_lines",
                return_value=["# Plan"],
            ) as markdown,
        ):
            runner = domain._workflow_runner()

            self.assertIs(runner.probe_dirty_worktree_fn(Path("/project"), Path("/repo"), "Main"), report)
            self.assertEqual(runner.analysis_iterations_fn(context, "full"), ["1"])
            self.assertEqual(
                runner.run_analyze_helper_fn(
                    context,
                    Path("/helper.py"),
                    ["1"],
                    "full",
                    "branch",
                    None,
                    original_plan,
                ),
                0,
            )
            self.assertEqual(runner.original_plan_markdown_lines_fn(original_plan), ["# Plan"])

        probe.assert_called_once_with(Path("/project"), Path("/repo"), project_name="Main")
        iterations.assert_called_once_with(context, mode="full")
        analyze.assert_called_once_with(
            context=context,
            helper=Path("/helper.py"),
            iterations=["1"],
            mode="full",
            scope="branch",
            review_base=None,
            original_plan=original_plan,
        )
        markdown.assert_called_once_with(original_plan, include_contents=True)

    def test_workflow_runner_construction_has_no_anonymous_lambda_wiring(self) -> None:
        source = Path(project_action_workflow_factory.__file__).read_text(encoding="utf-8")
        self.assertIn("class ProjectActionWorkflowFactory", source)
        self.assertNotIn("lambda", source)


if __name__ == "__main__":
    unittest.main()
