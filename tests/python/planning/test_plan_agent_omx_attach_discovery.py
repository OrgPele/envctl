# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *


class PlanAgentOmxAttachDiscoveryTests(PlanAgentLaunchSupportTestCase):
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

    def test_omx_new_session_wait_checks_state_written_by_final_sleep(self) -> None:
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
                            "native_session_id": "old-native",
                            "cwd": str(worktree_root.resolve()),
                        }
                    ),
                    encoding="utf-8",
                )
                clock_values = [0.0, 0.0, 1.0]

                def _monotonic() -> float:
                    if clock_values:
                        return clock_values.pop(0)
                    return 1.0

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
                    patch("envctl_engine.planning.plan_agent.omx_transport.time.monotonic", side_effect=_monotonic),
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
