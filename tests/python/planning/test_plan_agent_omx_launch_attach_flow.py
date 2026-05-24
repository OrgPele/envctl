# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *


class PlanAgentOmxLaunchAttachFlowTests(PlanAgentLaunchSupportTestCase):
    def test_omx_launch_spawns_managed_session_and_bootstraps_existing_tmux_session(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                provenance_path = repo / ".envctl-state" / "worktree-provenance.json"
                provenance_path.parent.mkdir(parents=True, exist_ok=True)
                provenance_path.write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "plan_file": "a.md",
                            "created_for_fresh_ai_launch": True,
                            "fresh_ai_launch_status": "launching",
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                rt = self._runtime(
                    repo,
                    runtime,
                    env={
                        "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    },
                )
                worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")
                attach_target = launch_support.PlanAgentAttachTarget(
                    repo_root=repo,
                    session_name="omx-feature-session",
                    window_name="%42",
                    attach_via="attach-session",
                    attach_command=("tmux", "attach", "-t", "omx-feature-session"),
                )

                with (
                    patch("envctl_engine.planning.plan_agent.omx_transport._find_existing_omx_attach_target", return_value=None),
                    patch("envctl_engine.planning.plan_agent.omx_transport._spawn_omx_session_for_worktree", return_value=None) as spawn_mock,
                    patch("envctl_engine.planning.plan_agent.omx_transport._wait_for_omx_attach_target", return_value=attach_target) as wait_mock,
                    patch("envctl_engine.planning.plan_agent.launch._run_tmux_existing_session_workflow", return_value=None) as workflow_mock,
                ):
                    result = launch_plan_agent_terminals(
                        rt,
                        route=parse_route(["--plan", "feature-a", "--omx", "--codex"], env={}),
                        created_worktrees=(worktree,),
                    )

                self.assertEqual(result.status, "launched")
                spawn_mock.assert_called_once()
                wait_mock.assert_called_once()
                workflow_mock.assert_called_once()
                self.assertIsNotNone(result.attach_target)
                assert result.attach_target is not None
                self.assertEqual(result.attach_target.session_name, "omx-feature-session")
                self.assertEqual(result.attach_target.window_name, "%42")
                self.assertEqual(result.attach_target.attach_command, ("tmux", "attach", "-t", "omx-feature-session"))
                provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
                self.assertEqual(provenance["fresh_ai_launch_status"], "launched")
                self.assertEqual(provenance["launch_transport"], "omx")
                self.assertEqual(provenance["session_name"], "omx-feature-session")

    def test_omx_launch_fails_when_attach_target_disappears_after_workflow_queue(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                rt = self._runtime(repo, runtime, env={"ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true"})
                worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")
                attach_target = launch_support.PlanAgentAttachTarget(
                    repo_root=repo,
                    session_name="omx-feature-session",
                    window_name="%42",
                    attach_via="attach-session",
                    attach_command=("tmux", "attach", "-t", "omx-feature-session"),
                )

                with (
                    patch("envctl_engine.planning.plan_agent.omx_transport._find_existing_omx_attach_target", return_value=None),
                    patch("envctl_engine.planning.plan_agent.omx_transport._spawn_omx_session_for_worktree", return_value=None),
                    patch("envctl_engine.planning.plan_agent.omx_transport._wait_for_omx_attach_target", return_value=attach_target),
                    patch("envctl_engine.planning.plan_agent.launch._run_tmux_existing_session_workflow", return_value=None),
                    patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=False),
                ):
                    result = launch_plan_agent_terminals(
                        rt,
                        route=parse_route(["--plan", "feature-a", "--omx", "--codex"], env={}),
                        created_worktrees=(worktree,),
                    )

                self.assertEqual(result.status, "failed")
                self.assertEqual(result.reason, "launch_failed")
                self.assertIsNone(result.attach_target)
                self.assertEqual(result.outcomes[0].status, "failed")
                self.assertEqual(result.outcomes[0].reason, "omx_attach_target_stale")
                self.assertEqual(
                    self._events(rt, "planning.agent_launch.attach_validation.failed")[-1]["reason"],
                    "omx_attach_target_stale",
                )

    def test_omx_launch_validation_failure_prints_native_recovery_command(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                rt = self._runtime(repo, runtime, env={"ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true"})
                worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")
                attach_target = launch_support.PlanAgentAttachTarget(
                    repo_root=repo,
                    session_name="omx-feature-session",
                    window_name="%42",
                    attach_via="attach-session",
                    attach_command=("tmux", "attach", "-t", "omx-feature-session"),
                )

                with (
                    patch("envctl_engine.planning.plan_agent.omx_transport._find_existing_omx_attach_target", return_value=None),
                    patch("envctl_engine.planning.plan_agent.omx_transport._spawn_omx_session_for_worktree", return_value=None),
                    patch("envctl_engine.planning.plan_agent.omx_transport._wait_for_omx_attach_target", return_value=attach_target),
                    patch("envctl_engine.planning.plan_agent.launch._run_tmux_existing_session_workflow", return_value=None),
                    patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=False),
                ):
                    out = StringIO()
                    with redirect_stdout(out):
                        result = launch_plan_agent_terminals(
                            rt,
                            route=parse_route(
                                ["--plan", "feature-a", "--omx", "--codex", "--ralph", "--entire-system", "--headless"],
                                env={},
                            ),
                            created_worktrees=(worktree,),
                        )

                self.assertEqual(result.status, "failed")
                rendered = out.getvalue()
                self.assertIn("recovery: ENVCTL_PLAN_AGENT_CODEX_CYCLES=2", rendered)
                self.assertIn(f"ENVCTL_USE_REPO_WRAPPER=1 {repo / 'bin' / 'envctl'} --plan feature-a --tmux", rendered)
                self.assertIn("--codex", rendered)
                self.assertIn("--entire-system", rendered)
                self.assertIn("--headless", rendered)
                self.assertIn("--new-session", rendered)
                self.assertNotIn("--omx", rendered)
                self.assertNotIn("--ralph", rendered)
                self.assertNotIn("--ultragoal", rendered)
                self.assertNotIn("--team", rendered)

    def test_omx_launch_fails_when_worktree_removed_after_attach_target_discovered(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                rt = self._runtime(repo, runtime, env={"ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true"})
                worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")
                attach_target = launch_support.PlanAgentAttachTarget(
                    repo_root=repo,
                    session_name="omx-feature-session",
                    window_name="%42",
                    attach_via="attach-session",
                    attach_command=("tmux", "attach", "-t", "omx-feature-session"),
                )

                def _queue_then_remove_worktree(*_args: object, **_kwargs: object) -> None:
                    repo.rmdir()
                    return None

                with (
                    patch("envctl_engine.planning.plan_agent.omx_transport._find_existing_omx_attach_target", return_value=None),
                    patch("envctl_engine.planning.plan_agent.omx_transport._spawn_omx_session_for_worktree", return_value=None),
                    patch("envctl_engine.planning.plan_agent.omx_transport._wait_for_omx_attach_target", return_value=attach_target),
                    patch("envctl_engine.planning.plan_agent.launch._run_tmux_existing_session_workflow", side_effect=_queue_then_remove_worktree),
                    patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=True),
                    patch("envctl_engine.planning.plan_agent.omx_transport._tmux_active_pane_id", return_value="%42"),
                ):
                    result = launch_plan_agent_terminals(
                        rt,
                        route=parse_route(["--plan", "feature-a", "--omx", "--codex"], env={}),
                        created_worktrees=(worktree,),
                    )

                self.assertEqual(result.status, "failed")
                self.assertIsNone(result.attach_target)
                self.assertEqual(result.outcomes[0].reason, "worktree_removed_after_launch")

    def test_omx_unavailable_event_includes_state_root_diagnostics(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                rt = self._runtime(
                    repo,
                    runtime,
                    env={"ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true"},
                )
                worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")

                with (
                    redirect_stdout(StringIO()),
                    patch("envctl_engine.planning.plan_agent.omx_transport._find_existing_omx_attach_target", return_value=None),
                    patch("envctl_engine.planning.plan_agent.omx_transport._spawn_omx_session_for_worktree", return_value=None),
                    patch("envctl_engine.planning.plan_agent.omx_transport._OMX_SESSION_READY_TIMEOUT_SECONDS", 0.02),
                    patch("envctl_engine.planning.plan_agent.omx_transport._OMX_SESSION_READY_POLL_INTERVAL_SECONDS", 0.001),
                ):
                    result = launch_plan_agent_terminals(
                        rt,
                        route=parse_route(["--plan", "feature-a", "--omx", "--codex"], env={}),
                        created_worktrees=(worktree,),
                    )

                self.assertEqual(result.status, "failed")
                failed_events = self._events(rt, "planning.agent_launch.failed")
                unavailable_events = [event for event in failed_events if event.get("reason") == "omx_session_unavailable"]
                self.assertEqual(len(unavailable_events), 1)
                event = unavailable_events[0]
                self.assertEqual(event.get("omx_root"), str(self._expected_omx_root(worktree)))
                self.assertEqual(event.get("session_state_exists"), False)
                self.assertEqual(event.get("session_id_present"), False)
                self.assertIn("tmux_candidates_checked", event)
                self.assertIn("worktree_panes_found", event)
