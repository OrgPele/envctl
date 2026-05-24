# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *


class PlanAgentOmxAttachValidationTests(PlanAgentLaunchSupportTestCase):
    def test_validate_omx_attach_target_accepts_current_payload_candidate(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                rt = self._runtime(repo, runtime)
                worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")
                omx_root = self._expected_omx_root(worktree)
                state_path = omx_root / ".omx" / "state" / "session.json"
                state_path.parent.mkdir(parents=True, exist_ok=True)
                state_path.write_text(
                    json.dumps(
                        {
                            "session_id": "omx-abc123",
                            "native_session_id": "omx-native-session",
                            "cwd": str(repo),
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                attach_target = launch_support.PlanAgentAttachTarget(
                    repo_root=repo,
                    session_name="omx-native-session",
                    window_name="%42",
                    attach_via="attach-session",
                    attach_command=("tmux", "attach", "-t", "omx-native-session"),
                )

                with (
                    patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=True),
                    patch("envctl_engine.planning.plan_agent.omx_transport._tmux_display_message_succeeds", return_value=(True, "%42")),
                ):
                    validation = launch_support.validate_plan_agent_attach_target(
                        rt,
                        attach_target,
                        worktree=worktree,
                        transport="omx",
                        phase="post_workflow_queue",
                    )

                self.assertTrue(validation.ok)
                self.assertEqual(validation.reason, "ok")

    def test_validate_omx_attach_target_fails_when_current_payload_points_elsewhere(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                rt = self._runtime(repo, runtime)
                worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")
                omx_root = self._expected_omx_root(worktree)
                state_path = omx_root / ".omx" / "state" / "session.json"
                state_path.parent.mkdir(parents=True, exist_ok=True)
                state_path.write_text(
                    json.dumps(
                        {
                            "session_id": "omx-abc123",
                            "native_session_id": "omx-current-session",
                            "cwd": str(repo),
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                attach_target = launch_support.PlanAgentAttachTarget(
                    repo_root=repo,
                    session_name="omx-stale-session",
                    window_name="%42",
                    attach_via="attach-session",
                    attach_command=("tmux", "attach", "-t", "omx-stale-session"),
                )

                with (
                    patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=True),
                    patch("envctl_engine.planning.plan_agent.omx_transport._tmux_display_message_succeeds", return_value=(True, "%42")),
                ):
                    validation = launch_support.validate_plan_agent_attach_target(
                        rt,
                        attach_target,
                        worktree=worktree,
                        transport="omx",
                        phase="post_workflow_queue",
                    )

            self.assertFalse(validation.ok)
            self.assertEqual(validation.reason, "omx_attach_target_stale")
            failed = self._events(rt, "planning.agent_launch.attach_validation.failed")[-1]
            self.assertEqual(failed["reason"], "omx_attach_target_stale")
            candidates = cast(list[str], failed["omx_session_candidates"])
            self.assertIn("omx-current-session", candidates)
            self.assertNotIn("omx-stale-session", candidates)

    def test_validate_omx_attach_target_ignores_wrong_worktree_payload_for_current_target(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                other_repo = Path(tmpdir) / "other"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                other_repo.mkdir(parents=True, exist_ok=True)
                rt = self._runtime(repo, runtime)
                worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")
                omx_root = self._expected_omx_root(worktree)
                state_path = omx_root / ".omx" / "state" / "session.json"
                state_path.parent.mkdir(parents=True, exist_ok=True)
                state_path.write_text(
                    json.dumps(
                        {
                            "session_id": "omx-abc123",
                            "native_session_id": "omx-wrong-worktree-session",
                            "cwd": str(other_repo),
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                attach_target = launch_support.PlanAgentAttachTarget(
                    repo_root=repo,
                    session_name="omx-wrong-worktree-session",
                    window_name="%42",
                    attach_via="attach-session",
                    attach_command=("tmux", "attach", "-t", "omx-wrong-worktree-session"),
                )

                with (
                    patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=True),
                    patch("envctl_engine.planning.plan_agent.omx_transport._tmux_display_message_succeeds", return_value=(True, "%42")),
                ):
                    validation = launch_support.validate_plan_agent_attach_target(
                        rt,
                        attach_target,
                        worktree=worktree,
                        transport="omx",
                        phase="post_workflow_queue",
                    )

                self.assertFalse(validation.ok)
                self.assertEqual(validation.reason, "omx_attach_target_stale")

    def test_validate_omx_attach_target_falls_back_when_no_payload_records_exist(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                rt = self._runtime(repo, runtime)
                worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")
                attach_target = launch_support.PlanAgentAttachTarget(
                    repo_root=repo,
                    session_name="omx-pane-discovered-session",
                    window_name="%42",
                    attach_via="attach-session",
                    attach_command=("tmux", "attach", "-t", "omx-pane-discovered-session"),
                )

                with (
                    patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=True),
                    patch("envctl_engine.planning.plan_agent.omx_transport._tmux_display_message_succeeds", return_value=(True, "%42")),
                ):
                    validation = launch_support.validate_plan_agent_attach_target(
                        rt,
                        attach_target,
                        worktree=worktree,
                        transport="omx",
                        phase="post_workflow_queue",
                    )

                self.assertTrue(validation.ok)
                self.assertEqual(validation.reason, "ok")
