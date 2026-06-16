# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *

from envctl_engine.planning.plan_agent.workflow_e2e_prompt_context import (
    _original_task_source_prompt_section,
    _shape_queue_message_text,
)


class PlanAgentWorkflowE2EPromptContextTests(PlanAgentLaunchSupportTestCase):
    def test_original_task_source_section_resolves_relative_plan_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_dir = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            repo.mkdir(parents=True, exist_ok=True)
            worktree_root.mkdir(parents=True, exist_ok=True)
            runtime = self._runtime(repo, runtime_dir)

            section = _original_task_source_prompt_section(
                runtime,
                worktree=CreatedPlanWorktree(
                    name="feature-a-1",
                    root=worktree_root,
                    plan_file="implementations/feature-a.md",
                ),
            )

        self.assertIn("## Original task source for E2E validation", section)
        self.assertIn(str(repo / "todo" / "plans" / "implementations" / "feature-a.md"), section)
        self.assertIn(str(worktree_root / "MAIN_TASK.md"), section)

    def test_non_browser_queue_message_is_left_unchanged(self) -> None:
        runtime = self._runtime(Path("/tmp/repo"), Path("/tmp/runtime"))

        self.assertEqual(_shape_queue_message_text(runtime, "Continue implementation"), "Continue implementation")

    def test_browser_e2e_followup_injects_original_plan_without_runtime_addresses(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_dir = Path(tmpdir) / "runtime"
            original_plan = repo / "todo" / "plans" / "implementations" / "feature-a.md"
            worktree_root = repo / "trees" / "feature-a" / "1"
            original_plan.parent.mkdir(parents=True, exist_ok=True)
            worktree_root.mkdir(parents=True, exist_ok=True)
            original_plan.write_text("# Original task\n", encoding="utf-8")
            runtime = self._runtime(repo, runtime_dir)
            runtime.state_repository = _StateRepositoryHarness(
                RunState(
                    run_id="run-1",
                    mode="trees",
                    services={
                        "feature-a Frontend": ServiceRecord(
                            name="feature-a Frontend",
                            type="frontend",
                            cwd=str(worktree_root / "frontend"),
                            actual_port=9300,
                            status="running",
                        )
                    },
                    requirements={
                        "feature-a": RequirementsResult(
                            project="feature-a",
                            components={"postgres": {"enabled": True, "success": True, "final": 5500}},
                        )
                    },
                )
            )

            prompt_text = _shape_queue_message_text(
                runtime,
                _browser_e2e_instruction_text(),
                worktree=CreatedPlanWorktree(
                    name="feature-a-1",
                    root=worktree_root,
                    plan_file="implementations/feature-a.md",
                ),
            )

        self.assertIn("## Original task source for E2E validation", prompt_text)
        self.assertIn(str(original_plan), prompt_text)
        self.assertIn("Use this original plan file before the current MAIN_TASK.md", prompt_text)
        self.assertNotIn("## Current envctl runtime addresses", prompt_text)
        self.assertNotIn("Postgres (feature-a): localhost:5500", prompt_text)
        self.assertNotIn("Frontend (feature-a Frontend): http://localhost:9300", prompt_text)

    def test_browser_e2e_followup_omits_stale_runtime_addresses_for_other_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_dir = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-b" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            runtime = self._runtime(repo, runtime_dir)
            runtime.state_repository = _StateRepositoryHarness(
                RunState(
                    run_id="run-previous",
                    mode="trees",
                    services={
                        "feature-a-1 Frontend": ServiceRecord(
                            name="feature-a-1 Frontend",
                            type="frontend",
                            cwd=str(repo / "trees" / "feature-a" / "1" / "frontend"),
                            actual_port=9300,
                            status="running",
                        )
                    },
                    requirements={
                        "feature-a-1": RequirementsResult(
                            project="feature-a-1",
                            components={"n8n": {"enabled": True, "success": True, "final": 5780}},
                        )
                    },
                )
            )

            prompt_text = _shape_queue_message_text(
                runtime,
                _browser_e2e_instruction_text(),
                worktree=CreatedPlanWorktree(
                    name="feature-b-1",
                    root=worktree_root,
                    plan_file="features/feature-b.md",
                ),
            )

        self.assertIn("## Original task source for E2E validation", prompt_text)
        self.assertNotIn("## Current envctl runtime addresses", prompt_text)
        self.assertNotIn("feature-a", prompt_text)
        self.assertNotIn("localhost:9300", prompt_text)
        self.assertNotIn("http://localhost:5780", prompt_text)


if __name__ == "__main__":
    unittest.main()
