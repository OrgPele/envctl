# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *


class PlanAgentLaunchOmxAttachTests(PlanAgentLaunchSupportTestCase):
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

    def test_omx_new_session_wait_uses_previous_session_id_to_avoid_stale_attach(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")
            session_path = repo / ".omx" / "state" / "session.json"
            session_path.parent.mkdir(parents=True, exist_ok=True)
            session_path.write_text('{"session_id":"old-session","native_session_id":"old-native"}\n', encoding="utf-8")
            attach_target = launch_support.PlanAgentAttachTarget(
                repo_root=repo,
                session_name="omx-new-session",
                window_name="%42",
                attach_via="attach-session",
                attach_command=("tmux", "attach", "-t", "omx-new-session"),
            )

            def _discover_new_session(*_args: object, **_kwargs: object) -> launch_support.PlanAgentAttachTarget:
                session_path.write_text(
                    json.dumps(
                        {
                            "session_id": "new-session",
                            "native_session_id": "omx-new-session",
                            "cwd": str(repo),
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                return attach_target

            with (
                patch("envctl_engine.planning.plan_agent.omx_transport._find_existing_omx_attach_target", return_value=None),
                patch("envctl_engine.planning.plan_agent.omx_transport._spawn_omx_session_for_worktree", return_value=None),
                patch(
                    "envctl_engine.planning.plan_agent.omx_transport._wait_for_omx_attach_target",
                    side_effect=_discover_new_session,
                ) as wait_mock,
                patch("envctl_engine.planning.plan_agent.launch._run_tmux_existing_session_workflow", return_value=None),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a", "--omx", "--new-session"], env={}),
                    created_worktrees=(worktree,),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(wait_mock.call_args.kwargs["previous_session_id"], "old-session")

    def test_omx_wait_discovers_session_from_deterministic_omx_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md")
            omx_root = self._expected_omx_root(worktree)
            session_path = omx_root / ".omx" / "state" / "session.json"
            session_path.parent.mkdir(parents=True, exist_ok=True)
            session_path.write_text(
                json.dumps(
                    {
                        "session_id": "omx-new-session",
                        "native_session_id": "omx-feature-session",
                        "cwd": str(worktree_root.resolve()),
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=True),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_active_pane_id", return_value="%42"),
            ):
                attach_target = omx_transport._wait_for_omx_attach_target(
                    rt,
                    repo_root=repo,
                    worktree=worktree,
                    previous_session_id="old-session",
                    attach_via="attach-session",
                )

            self.assertIsNotNone(attach_target)
            assert attach_target is not None
            self.assertEqual(attach_target.session_name, "omx-feature-session")
            self.assertEqual(attach_target.window_name, "%42")

    def test_omx_wait_rejects_state_for_other_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            other_root = repo / "trees" / "other" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            other_root.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md")
            session_path = worktree_root / ".omx" / "state" / "session.json"
            session_path.parent.mkdir(parents=True, exist_ok=True)
            session_path.write_text(
                json.dumps(
                    {
                        "session_id": "omx-wrong-cwd",
                        "native_session_id": "omx-feature-session",
                        "cwd": str(other_root.resolve()),
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch("envctl_engine.planning.plan_agent.omx_transport._OMX_SESSION_READY_TIMEOUT_SECONDS", 0.02),
                patch("envctl_engine.planning.plan_agent.omx_transport._OMX_SESSION_READY_POLL_INTERVAL_SECONDS", 0.001),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=True),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_active_pane_id", return_value="%42"),
            ):
                attach_target = omx_transport._wait_for_omx_attach_target(
                    rt,
                    repo_root=repo,
                    worktree=worktree,
                    previous_session_id="",
                    attach_via="attach-session",
                )

            self.assertIsNone(attach_target)

    def test_find_existing_omx_attach_target_reads_deterministic_omx_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md")
            session_path = self._expected_omx_root(worktree) / ".omx" / "state" / "session.json"
            session_path.parent.mkdir(parents=True, exist_ok=True)
            session_path.write_text(
                json.dumps(
                    {
                        "session_id": "omx-abc123",
                        "native_session_id": "omx-feature-session",
                        "cwd": str(worktree_root.resolve()),
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=True),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_active_pane_id", return_value="%42"),
            ):
                attach_target = omx_transport._find_existing_omx_attach_target(
                    rt,
                    repo_root=repo,
                    created_worktrees=(worktree,),
                )

            self.assertIsNotNone(attach_target)
            assert attach_target is not None
            self.assertEqual(attach_target.session_name, "omx-feature-session")
            self.assertEqual(attach_target.window_name, "%42")

    def test_omx_new_session_wait_ignores_previous_session_id_from_selected_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md")
            session_path = self._expected_omx_root(worktree) / ".omx" / "state" / "session.json"
            session_path.parent.mkdir(parents=True, exist_ok=True)
            session_path.write_text(
                json.dumps(
                    {
                        "session_id": "old-session",
                        "native_session_id": "omx-feature-a-1-main-old",
                        "cwd": str(worktree_root.resolve()),
                    }
                ),
                encoding="utf-8",
            )

            def _write_new_session(_seconds: float) -> None:
                session_path.write_text(
                    json.dumps(
                        {
                            "session_id": "new-session",
                            "native_session_id": "new-native",
                            "cwd": str(worktree_root.resolve()),
                        }
                    ),
                    encoding="utf-8",
                )

            with (
                patch("envctl_engine.planning.plan_agent.omx_transport._OMX_SESSION_READY_TIMEOUT_SECONDS", 0.2),
                patch("envctl_engine.planning.plan_agent.omx_transport._OMX_SESSION_READY_POLL_INTERVAL_SECONDS", 0.001),
                patch("envctl_engine.planning.plan_agent.omx_transport.time.sleep", side_effect=_write_new_session),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=True),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_active_pane_id", return_value="%42"),
            ):
                attach_target = omx_transport._wait_for_omx_attach_target(
                    rt,
                    repo_root=repo,
                    worktree=worktree,
                    previous_session_id="old-session",
                    attach_via="attach-session",
                )

            self.assertIsNotNone(attach_target)
            assert attach_target is not None
            self.assertEqual(attach_target.session_name, "new-native")

    def test_omx_wait_falls_back_to_legacy_worktree_session_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md")
            session_path = worktree_root / ".omx" / "state" / "session.json"
            session_path.parent.mkdir(parents=True, exist_ok=True)
            session_path.write_text(
                json.dumps(
                    {
                        "session_id": "omx-legacy",
                        "native_session_id": "omx-legacy-session",
                        "cwd": str(worktree_root.resolve()),
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=True),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_active_pane_id", return_value="%43"),
            ):
                attach_target = omx_transport._wait_for_omx_attach_target(
                    rt,
                    repo_root=repo,
                    worktree=worktree,
                    previous_session_id="",
                    attach_via="attach-session",
                )

            self.assertIsNotNone(attach_target)
            assert attach_target is not None
            self.assertEqual(attach_target.session_name, "omx-legacy-session")
            self.assertEqual(attach_target.window_name, "%43")

    def test_omx_wait_falls_back_to_tmux_pane_path_for_matching_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["tmux"],
                        returncode=0,
                        stdout=f"omx-feature-a-1-main-abc|||ENVCTL_TMUX_PANE|||%77|||ENVCTL_TMUX_PATH|||{worktree_root}\n",
                        stderr="",
                    ),
                ]
            )
            worktree = CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md")
            session_path = self._expected_omx_root(worktree) / ".omx" / "state" / "session.json"
            session_path.parent.mkdir(parents=True, exist_ok=True)
            session_path.write_text(
                json.dumps(
                    {
                        "session_id": "omx-abc",
                        "cwd": str(worktree_root.resolve()),
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=False),
                patch("envctl_engine.planning.plan_agent.omx_transport._OMX_SESSION_READY_TIMEOUT_SECONDS", 0.02),
                patch("envctl_engine.planning.plan_agent.omx_transport._OMX_SESSION_READY_POLL_INTERVAL_SECONDS", 0.001),
            ):
                attach_target = omx_transport._wait_for_omx_attach_target(
                    rt,
                    repo_root=repo,
                    worktree=worktree,
                    previous_session_id="",
                    attach_via="attach-session",
                )

            self.assertIsNotNone(attach_target)
            assert attach_target is not None
            self.assertEqual(attach_target.session_name, "omx-feature-a-1-main-abc")
            self.assertEqual(attach_target.window_name, "%77")

    def test_omx_wait_falls_back_to_tmux_pane_path_without_session_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["tmux"],
                        returncode=0,
                        stdout=f"omx-feature-a-1-main-abc|||ENVCTL_TMUX_PANE|||%77|||ENVCTL_TMUX_PATH|||{worktree_root}\n",
                        stderr="",
                    ),
                ]
            )
            worktree = CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md")

            with (
                patch("envctl_engine.planning.plan_agent.omx_transport._OMX_SESSION_READY_TIMEOUT_SECONDS", 0.02),
                patch("envctl_engine.planning.plan_agent.omx_transport._OMX_SESSION_READY_POLL_INTERVAL_SECONDS", 0.001),
            ):
                attach_target = omx_transport._wait_for_omx_attach_target(
                    rt,
                    repo_root=repo,
                    worktree=worktree,
                    previous_session_id="",
                    attach_via="attach-session",
                )

            self.assertIsNotNone(attach_target)
            assert attach_target is not None
            self.assertEqual(attach_target.session_name, "omx-feature-a-1-main-abc")
            self.assertEqual(attach_target.window_name, "%77")

    def test_omx_new_session_wait_rejects_previous_pane_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["tmux"],
                        returncode=0,
                        stdout=f"omx-feature-a-1-main-old|||ENVCTL_TMUX_PANE|||%17|||ENVCTL_TMUX_PATH|||{worktree_root}\n",
                        stderr="",
                    ),
                ]
            )
            worktree = CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md")
            session_path = self._expected_omx_root(worktree) / ".omx" / "state" / "session.json"
            session_path.parent.mkdir(parents=True, exist_ok=True)
            session_path.write_text(
                json.dumps(
                    {
                        "session_id": "old-session",
                        "native_session_id": "omx-feature-a-1-main-old",
                        "cwd": str(worktree_root.resolve()),
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch("envctl_engine.planning.plan_agent.omx_transport._OMX_SESSION_READY_TIMEOUT_SECONDS", 0.02),
                patch("envctl_engine.planning.plan_agent.omx_transport._OMX_SESSION_READY_POLL_INTERVAL_SECONDS", 0.001),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=False),
            ):
                attach_target = omx_transport._wait_for_omx_attach_target(
                    rt,
                    repo_root=repo,
                    worktree=worktree,
                    previous_session_id="old-session",
                    previous_session_ids=("old-session",),
                    attach_via="attach-session",
                )

            self.assertIsNone(attach_target)

    def test_omx_new_session_wait_rejects_preexisting_pane_without_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["tmux"],
                        returncode=0,
                        stdout=f"omx-feature-a-1-main-old|||ENVCTL_TMUX_PANE|||%17|||ENVCTL_TMUX_PATH|||{worktree_root}\n",
                        stderr="",
                    ),
                ]
            )
            worktree = CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md")

            with (
                patch("envctl_engine.planning.plan_agent.omx_transport._OMX_SESSION_READY_TIMEOUT_SECONDS", 0.02),
                patch("envctl_engine.planning.plan_agent.omx_transport._OMX_SESSION_READY_POLL_INTERVAL_SECONDS", 0.001),
            ):
                attach_target = omx_transport._wait_for_omx_attach_target(
                    rt,
                    repo_root=repo,
                    worktree=worktree,
                    previous_session_id="",
                    previous_session_ids=(),
                    previous_tmux_session_names=("omx-feature-a-1-main-old",),
                    attach_via="attach-session",
                )

            self.assertIsNone(attach_target)

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

    def test_find_existing_omx_attach_target_records_active_pane_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            session_path = worktree_root / ".omx" / "state"
            session_path.mkdir(parents=True, exist_ok=True)
            (session_path / "session.json").write_text('{"session_id":"omx-abc123"}\n', encoding="utf-8")
            rt = self._runtime(repo, runtime)
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="%42\n", stderr=""),
                ]
            )

            attach_target = omx_transport._find_existing_omx_attach_target(
                rt,
                repo_root=repo,
                created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md"),),
            )

            self.assertIsNotNone(attach_target)
            assert attach_target is not None
            self.assertEqual(attach_target.session_name, omx_transport._omx_tmux_session_name(worktree_root, "omx-abc123"))
            self.assertEqual(attach_target.window_name, "%42")

    def test_cleanup_stale_omx_tmux_locks_ignores_fresh_lock_and_removes_old_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree_root = Path(tmpdir) / "worktree"
            lock_root = worktree_root / ".omx" / "state" / "tmux-extended-keys"
            fresh_lock = lock_root / "fresh.lock"
            stale_lock = lock_root / "stale.lock"
            fresh_lock.mkdir(parents=True, exist_ok=True)
            stale_lock.mkdir(parents=True, exist_ok=True)

            now = time.time()
            stale_time = now - (omx_transport._OMX_TMUX_LOCK_STALE_SECONDS + 10.0)
            fresh_time = now - 1.0
            os.utime(stale_lock, (stale_time, stale_time))
            os.utime(fresh_lock, (fresh_time, fresh_time))

            runtime = self._runtime(Path(tmpdir) / "repo", Path(tmpdir) / "runtime")

            omx_transport._cleanup_stale_omx_tmux_locks(runtime, worktree_root=worktree_root)

            self.assertFalse(stale_lock.exists())
            self.assertTrue(fresh_lock.exists())
            self.assertEqual(
                self._events(runtime, "planning.agent_launch.omx_lock_cleanup"),
                [
                    {
                        "event": "planning.agent_launch.omx_lock_cleanup",
                        "worktree": str(worktree_root.resolve()),
                        "transport": "omx",
                    }
                ],
            )
