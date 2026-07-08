# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *



class PlanAgentLaunchCmuxReviewTests(PlanAgentLaunchSupportTestCase):
    def test_review_launch_uses_reviews_workspace_and_repo_root_for_codex_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            project_root = repo / "trees" / "feature-a" / "1"
            review_bundle = repo / "runtime" / "review" / "all.md"
            original_plan = repo / "todo" / "plans" / "implementations" / "feature-a.md"
            project_root.mkdir(parents=True, exist_ok=True)
            review_bundle.parent.mkdir(parents=True, exist_ok=True)
            original_plan.parent.mkdir(parents=True, exist_ok=True)
            review_bundle.write_text("# review\n", encoding="utf-8")
            original_plan.write_text("# Original plan\n", encoding="utf-8")
            (project_root / ".envctl-state").mkdir(parents=True, exist_ok=True)
            (project_root / ".envctl-state" / "worktree-provenance.json").write_text(
                json.dumps({"schema_version": 1, "plan_file": "implementations/feature-a.md"}) + "\n",
                encoding="utf-8",
            )
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "CMUX_WORKSPACE_ID": "workspace:4",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:4  envctl  [selected]\n  workspace:8  envctl implementation\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="workspace:10\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:12\n", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport.threading.Thread", _ImmediateThread),
                patch("envctl_engine.planning.plan_agent.cmux_transport._wait_for_cli_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._wait_for_prompt_picker_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._wait_for_prompt_submit_ready", return_value=None),
            ):
                _ImmediateThread.created = []
                result = launch_support.launch_review_agent_terminal(
                    rt,
                    repo_root=repo,
                    project_name="feature-a-1",
                    project_root=project_root,
                    review_bundle_path=review_bundle,
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(rt.process_runner.calls[0], ["cmux", "list-workspaces"])
            self.assertEqual(rt.process_runner.calls[1], ["cmux", "new-workspace", "--cwd", str(repo.resolve())])
            self.assertEqual(rt.process_runner.calls[2], ["cmux", "rename-workspace", "--workspace", "workspace:10", "envctl reviews"])
            self.assertEqual(rt.process_runner.calls[3], ["cmux", "list-pane-surfaces", "--workspace", "workspace:10"])
            self.assertEqual(rt.process_runner.calls[4], ["cmux", "new-surface", "--workspace", "workspace:10"])
            self.assertIn(
                ["cmux", "send", "--workspace", "workspace:10", "--surface", "surface:12", f"cd {repo}"],
                rt.process_runner.calls,
            )
            self.assertNotIn(
                ["cmux", "send", "--workspace", "workspace:10", "--surface", "surface:12", f"cd {project_root}"],
                rt.process_runner.calls,
            )
            review_prompt_calls = [
                call
                for call in rt.process_runner.calls
                if call[:4] == ["cmux", "set-buffer", "--name", "envctl-surface-12"]
            ]
            self.assertEqual(len(review_prompt_calls), 1)
            self.assertTrue(str(review_prompt_calls[0][-1]).startswith("$envctl-review-worktree "))
            self.assertIn(f'Review bundle: "{review_bundle}"', str(review_prompt_calls[0][-1]))
            self.assertIn(f'Worktree directory: "{project_root}"', str(review_prompt_calls[0][-1]))
            self.assertIn(f'Original plan file: "{original_plan.resolve()}"', str(review_prompt_calls[0][-1]))
            self.assertIn(
                ["cmux", "paste-buffer", "--name", "envctl-surface-12", "--workspace", "workspace:10", "--surface", "surface:12"],
                rt.process_runner.calls,
            )

    def test_review_launch_honors_explicit_workspace_override_and_opencode_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            project_root = repo / "trees" / "feature-a" / "1"
            review_bundle = repo / "runtime" / "review" / "all.md"
            original_plan = repo / "todo" / "plans" / "implementations" / "feature-a.md"
            project_root.mkdir(parents=True, exist_ok=True)
            review_bundle.parent.mkdir(parents=True, exist_ok=True)
            original_plan.parent.mkdir(parents=True, exist_ok=True)
            review_bundle.write_text("# review\n", encoding="utf-8")
            original_plan.write_text("# Current plan\n", encoding="utf-8")
            (project_root / ".envctl-state").mkdir(parents=True, exist_ok=True)
            (project_root / ".envctl-state" / "worktree-provenance.json").write_text(
                json.dumps({"schema_version": 1, "plan_file": "implementations/feature-a.md"}) + "\n",
                encoding="utf-8",
            )
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_CLI": "opencode",
                    "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "workspace:9",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:15\n", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport.threading.Thread", _ImmediateThread),
                patch("envctl_engine.planning.plan_agent.cmux_transport._wait_for_cli_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._wait_for_prompt_picker_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._wait_for_prompt_submit_ready", return_value=None),
            ):
                _ImmediateThread.created = []
                result = launch_support.launch_review_agent_terminal(
                    rt,
                    repo_root=repo,
                    project_name="feature-a-1",
                    project_root=project_root,
                    review_bundle_path=review_bundle,
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(rt.process_runner.calls[0], ["cmux", "new-surface", "--workspace", "workspace:9"])
            self.assertNotIn(["cmux", "list-workspaces"], rt.process_runner.calls)
            direct_prompt_calls = [
                call
                for call in rt.process_runner.calls
                if call[:4] == ["cmux", "set-buffer", "--name", "envctl-surface-15"]
            ]
            self.assertEqual(len(direct_prompt_calls), 1)
            self.assertTrue(str(direct_prompt_calls[0][-1]).startswith("/ulw-loop You are reviewing"))
            self.assertIn(f'Review bundle: "{review_bundle}"', str(direct_prompt_calls[0][-1]))
            self.assertIn(f'Worktree directory: "{project_root}"', str(direct_prompt_calls[0][-1]))
            self.assertIn(f'Original plan file: "{original_plan.resolve()}"', str(direct_prompt_calls[0][-1]))
            self.assertIn(
                ["cmux", "paste-buffer", "--name", "envctl-surface-15", "--workspace", "workspace:9", "--surface", "surface:15"],
                rt.process_runner.calls,
            )

    def test_review_launch_resolves_original_plan_file_from_worktree_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            project_root = repo / "trees" / "feature-a" / "1"
            original_plan = repo / "todo" / "plans" / "implementations" / "feature-a.md"
            project_root.mkdir(parents=True, exist_ok=True)
            original_plan.parent.mkdir(parents=True, exist_ok=True)
            original_plan.write_text("# first plan\n", encoding="utf-8")
            (project_root / ".envctl-state").mkdir(parents=True, exist_ok=True)
            (project_root / ".envctl-state" / "worktree-provenance.json").write_text(
                json.dumps({"schema_version": 1, "plan_file": "implementations/feature-a.md"}) + "\n",
                encoding="utf-8",
            )
            original_plan_path = workflow._review_original_plan_path(
                "feature-a-1",
                project_root,
                repo_root=repo,
            )

            self.assertEqual(original_plan_path, original_plan.resolve())

    def test_review_launch_returns_none_when_original_plan_file_cannot_be_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            project_root = repo / "trees" / "feature-a" / "1"
            project_root.mkdir(parents=True, exist_ok=True)

            original_plan_path = workflow._review_original_plan_path(
                "feature-a-1",
                project_root,
                repo_root=repo,
            )

            self.assertIsNone(original_plan_path)

    def test_review_launch_does_not_infer_when_recorded_plan_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            project_root = repo / "trees" / "implementations_task" / "1"
            inferred_plan = repo / "todo" / "done" / "implementations" / "task.md"
            project_root.mkdir(parents=True, exist_ok=True)
            inferred_plan.parent.mkdir(parents=True, exist_ok=True)
            inferred_plan.write_text("# done plan\n", encoding="utf-8")
            (project_root / ".envctl-state").mkdir(parents=True, exist_ok=True)
            (project_root / ".envctl-state" / "worktree-provenance.json").write_text(
                json.dumps({"schema_version": 1, "plan_file": "implementations/missing.md"}) + "\n",
                encoding="utf-8",
            )

            original_plan_path = workflow._review_original_plan_path(
                "implementations_task-1",
                project_root,
                repo_root=repo,
            )

            self.assertIsNone(original_plan_path)

    def test_review_launch_can_infer_original_plan_file_without_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            project_root = repo / "trees" / "implementations_task" / "1"
            original_plan = repo / "todo" / "done" / "implementations" / "task.md"
            project_root.mkdir(parents=True, exist_ok=True)
            original_plan.parent.mkdir(parents=True, exist_ok=True)
            original_plan.write_text("# done plan\n", encoding="utf-8")

            original_plan_path = workflow._review_original_plan_path(
                "implementations_task-1",
                project_root,
                repo_root=repo,
            )

            self.assertEqual(original_plan_path, original_plan.resolve())

    def test_review_launch_prefers_active_plan_over_archived_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            project_root = repo / "trees" / "features_task"
            active_plan = repo / "todo" / "plans" / "features" / "task.md"
            archived_plan = repo / "todo" / "done" / "features" / "task.md"
            project_root.mkdir(parents=True, exist_ok=True)
            active_plan.parent.mkdir(parents=True, exist_ok=True)
            archived_plan.parent.mkdir(parents=True, exist_ok=True)
            active_plan.write_text("# active plan\n", encoding="utf-8")
            archived_plan.write_text("# archived plan\n", encoding="utf-8")

            original_plan_path = workflow._review_original_plan_path(
                "features_task",
                project_root,
                repo_root=repo,
            )

            self.assertEqual(original_plan_path, active_plan.resolve())
