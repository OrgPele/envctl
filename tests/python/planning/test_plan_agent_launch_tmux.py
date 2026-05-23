# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *


class PlanAgentLaunchTmuxTests(PlanAgentLaunchSupportTestCase):
    def test_launch_sequence_uses_tmux_commands_for_opencode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            rt._command_exists = lambda command: command in {"tmux", "opencode", "zsh"}  # type: ignore[assignment]
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=1, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="feature-a-1\n", stderr=""),
                    subprocess.CompletedProcess(
                        args=["tmux"],
                        returncode=0,
                        stdout="ask anything\n/status\n> ",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="envctl-test-session\n", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="feature-a-1\n", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="", stderr=""),
                ]
            )

            attach_target = launch_support.PlanAgentAttachTarget(
                repo_root=repo,
                session_name="envctl-test-session",
                window_name="feature-a-1",
                attach_via="attach-session",
                attach_command=("tmux", "attach", "-t", "envctl-test-session"),
            )

            with (
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.tmux_transport._wait_for_tmux_cli_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent.tmux_transport._submit_tmux_prompt_workflow_step", return_value=None),
                patch("envctl_engine.planning.plan_agent.tmux_transport._resolve_tmux_attach_target", return_value=attach_target),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a", "--tmux", "--opencode"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertIsNotNone(result.attach_target)
            assert result.attach_target is not None
            expected_attach_session = _tmux_session_name_for_worktree(
                repo,
                CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),
                cli="opencode",
            )
            self.assertEqual(result.attach_target.attach_command, ("tmux", "attach", "-t", expected_attach_session))
            expected_session_name = next(call[3] for call in rt.process_runner.calls if call[:3] == ["tmux", "has-session", "-t"])
            self.assertIn(["tmux", "has-session", "-t", expected_session_name], rt.process_runner.calls)
            self.assertEqual(expected_session_name, expected_attach_session)
            launch_calls = [call for call in rt.process_runner.calls if call[:2] in (["tmux", "new-session"], ["tmux", "new-window"])]
            self.assertTrue(launch_calls)
            self.assertTrue(any(call[0:5] == ["tmux", "new-session", "-d", "-s", expected_session_name] or call[0:5] == ["tmux", "new-window", "-d", "-t", expected_session_name] for call in launch_calls))
            self.assertIn(["tmux", "set-option", "-t", expected_session_name, "mouse", "on"], rt.process_runner.calls)
            self.assertIn(["tmux", "send-keys", "-t", f"{expected_session_name}:feature-a-1", "-l", f"cd {shlex.quote(str(repo))}"], rt.process_runner.calls)
            self.assertIn(["tmux", "send-keys", "-t", f"{expected_session_name}:feature-a-1", "Enter"], rt.process_runner.calls)
            self.assertIn(["tmux", "send-keys", "-t", f"{expected_session_name}:feature-a-1", "-l", "opencode"], rt.process_runner.calls)

    def test_tmux_opencode_launch_fails_when_cli_never_becomes_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            rt._command_exists = lambda command: command in {"tmux", "opencode", "zsh"}  # type: ignore[assignment]
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["tmux"], returncode=1, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=1, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="feature-a-1\n", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="", stderr=""),
                ]
            )

            with (
                redirect_stdout(StringIO()) as buffer,
                patch(
                    "envctl_engine.planning.plan_agent.tmux_transport._wait_for_tmux_cli_ready",
                    return_value=launch_support.AiCliReadyResult(
                        ready=False,
                        reason="opencode_ready_timeout",
                        screen_excerpt="zsh: command not found: opencode",
                    ),
                ),
                patch("envctl_engine.planning.plan_agent.tmux_transport._submit_tmux_prompt_workflow_step", return_value=None) as submit_mock,
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a", "--tmux", "--opencode"], env={}),
                    created_worktrees=(
                        CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="feature-a.md"),
                    ),
                )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "launch_failed")
        self.assertEqual(len(result.outcomes), 1)
        self.assertEqual(result.outcomes[0].status, "failed")
        self.assertIn("opencode_ready_timeout", str(result.outcomes[0].reason))
        self.assertIn("zsh: command not found: opencode", str(result.outcomes[0].reason))
        self.assertIn("opencode_ready_timeout", buffer.getvalue())
        submit_mock.assert_not_called()

    def test_tmux_codex_workflow_queue_failure_emits_fallback_with_step_context(self) -> None:
        self.assertIsNotNone(_run_tmux_worktree_bootstrap)
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")
            launch_config = launch_support.PlanAgentLaunchConfig(
                enabled=True,
                transport="tmux",
                cli="codex",
                cli_command="codex --dangerously-bypass-approvals-and-sandbox",
                preset="implement_task",
                codex_cycles=1,
                codex_cycles_warning=None,
                shell="zsh",
                require_cmux_context=True,
                cmux_workspace="",
                direct_prompt_enabled=False,
                ulw_loop_prefix=False,
                ulw_suffix=False,
            )
            workflow = _build_plan_agent_workflow(cli="codex", preset="implement_task", codex_cycles=1)

            def resolve_step(*_args, step, **_kwargs):
                return (f"resolved::{step.kind}::{step.text}", None)

            with (
                patch("envctl_engine.planning.plan_agent.tmux_transport._launch_tmux_cli_bootstrap_commands", return_value=[None]),
                patch("envctl_engine.planning.plan_agent.tmux_transport._wait_for_tmux_cli_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent.tmux_transport._workflow_step_prompt_text", side_effect=resolve_step),
                patch("envctl_engine.planning.plan_agent.tmux_transport._submit_tmux_prompt_workflow_step", return_value=None),
                patch("envctl_engine.planning.plan_agent.tmux_transport._send_tmux_prompt", return_value=None),
                patch("envctl_engine.planning.plan_agent.tmux_transport._queue_tmux_codex_message", return_value=False),
            ):
                error = _run_tmux_worktree_bootstrap(
                    rt,
                    session_name="envctl-test-session",
                    window_name="feature-a-1",
                    launch_config=launch_config,
                    workflow=workflow,
                    worktree=worktree,
                )

            self.assertIsNone(error)
            expected = {
                "session_name": "envctl-test-session",
                "window_name": "feature-a-1",
                "worktree": "feature-a-1",
                "cli": "codex",
                "workflow_mode": "codex_cycles",
                "codex_cycles": 1,
                "reason": "queue_goal_not_ready",
                "transport": "tmux",
                "queue_failed_step_index": 0,
                "queue_failed_step_kind": "queue_direct_prompt",
            }
            self.assertEqual(
                self._events(rt, "planning.agent_launch.workflow_queue_failed"),
                [{"event": "planning.agent_launch.workflow_queue_failed", **expected}],
            )
            self.assertEqual(
                self._events(rt, "planning.agent_launch.workflow_fallback"),
                [{"event": "planning.agent_launch.workflow_fallback", **expected}],
            )

    def test_tmux_target_accepts_pane_id_directly(self) -> None:
        self.assertEqual(tmux_transport._tmux_target("omx-feature-session", "%42"), "%42")

    def test_tmux_launch_reuses_existing_session_for_matching_worktree_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            rt._command_exists = lambda command: command in {"tmux", "opencode", "zsh"}  # type: ignore[assignment]
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="envctl-existing\n", stderr=""),
                    subprocess.CompletedProcess(
                        args=["tmux"],
                        returncode=0,
                        stdout=f"feature-a-1|||ENVCTL_TMUX_PATH|||{worktree_root}\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(
                        args=["tmux"],
                        returncode=0,
                        stdout='  ┃  Ask anything... "Fix broken tests"\n  ctrl+p commands\n  ~/repo /status\n',
                        stderr="",
                    ),
                ]
            )

            result = launch_plan_agent_terminals(
                rt,
                route=parse_route(["--plan", "feature-a", "--tmux", "--opencode"], env={}),
                created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md"),),
            )

            self.assertEqual(result.status, "failed")
            self.assertIsNotNone(result.attach_target)
            assert result.attach_target is not None
            expected_session = _tmux_session_name_for_worktree(
                repo,
                CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md"),
                cli="opencode",
            )
            self.assertEqual(result.attach_target.session_name, expected_session)
            self.assertEqual(result.attach_target.attach_command, ("tmux", "attach", "-t", expected_session))
            self.assertEqual(rt.process_runner.calls[0], ["tmux", "has-session", "-t", expected_session])
            self.assertEqual(rt.process_runner.calls[1], ["tmux", "list-windows", "-t", expected_session, "-F", "#{window_name}|||ENVCTL_TMUX_PATH|||#{pane_current_path}"])

    def test_tmux_existing_opencode_session_requires_ready_pane(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            rt._command_exists = lambda command: command in {"tmux", "opencode", "zsh"}  # type: ignore[assignment]
            expected_session = _tmux_session_name_for_worktree(
                repo,
                CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md"),
                cli="opencode",
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout=f"{expected_session}\n", stderr=""),
                    subprocess.CompletedProcess(
                        args=["tmux"],
                        returncode=0,
                        stdout=f"feature-a-1|||ENVCTL_TMUX_PATH|||{worktree_root}\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(
                        args=["tmux"],
                        returncode=0,
                        stdout='  ┃  Ask anything... "Fix broken tests"\n  ctrl+p commands\n  ~/repo /status\n',
                        stderr="",
                    ),
                ]
            )

            with patch(
                "envctl_engine.planning.plan_agent.tmux_transport._read_tmux_screen",
                return_value="$ cd repo\n$ opencode\nzsh: command not found: opencode\n$ ",
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a", "--tmux", "--opencode"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md"),),
                )

        self.assertEqual(result.status, "failed")
        self.assertIn("existing_opencode_session_unhealthy", result.reason)
        self.assertEqual(len(result.outcomes), 1)
        self.assertIn("zsh: command not found: opencode", str(result.outcomes[0].reason))
        self.assertIsNone(result.attach_target)

    def test_tmux_existing_opencode_session_accepts_active_agent_screen(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            rt._command_exists = lambda command: command in {"tmux", "opencode", "zsh"}  # type: ignore[assignment]
            expected_session = _tmux_session_name_for_worktree(
                repo,
                CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md"),
                cli="opencode",
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout=f"{expected_session}\n", stderr=""),
                    subprocess.CompletedProcess(
                        args=["tmux"],
                        returncode=0,
                        stdout=f"feature-a-1|||ENVCTL_TMUX_PATH|||{worktree_root}\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="Sisyphus is working...\nEsc to interrupt\n", stderr=""),
                ]
            )

            result = launch_plan_agent_terminals(
                rt,
                route=parse_route(["--plan", "feature-a", "--tmux", "--opencode"], env={}),
                created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md"),),
            )

        self.assertEqual(result.status, "failed")
        self.assertIsNotNone(result.attach_target)

    def test_tmux_existing_session_prompt_yes_attaches_without_launching_new_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            rt._command_exists = lambda command: command in {"tmux", "opencode", "zsh"}  # type: ignore[assignment]
            rt._can_interactive_tty = lambda: True  # type: ignore[assignment]
            rt._read_interactive_command_line = lambda prompt: "y"  # type: ignore[assignment]
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="envctl-existing\n", stderr=""),
                    subprocess.CompletedProcess(
                        args=["tmux"],
                        returncode=0,
                        stdout=f"feature-a-1|||ENVCTL_TMUX_PATH|||{worktree_root}\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(
                        args=["tmux"],
                        returncode=0,
                        stdout='  ┃  Ask anything... "Fix broken tests"\n  ctrl+p commands\n  ~/repo /status\n',
                        stderr="",
                    ),
                ]
            )

            result = launch_plan_agent_terminals(
                rt,
                route=parse_route(["--plan", "feature-a", "--tmux", "--opencode"], env={}),
                created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md"),),
            )

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.reason, "existing_tmux_session_attach")
            self.assertIsNotNone(result.attach_target)
            assert result.attach_target is not None
            expected_session = _tmux_session_name_for_worktree(
                repo,
                CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md"),
                cli="opencode",
            )
            self.assertEqual(result.attach_target.session_name, expected_session)
            self.assertEqual(result.attach_target.attach_command, ("tmux", "attach", "-t", expected_session))
            self.assertEqual(len(rt.process_runner.calls), 3)

    def test_existing_tmux_session_prompt_explains_no_creates_new_session(self) -> None:
        prompt_target = launch_support.PlanAgentAttachTarget(
            repo_root=Path("/tmp/repo"),
            session_name="envctl-existing",
            window_name="feature-a-1",
            attach_via="attach-session",
            attach_command=("tmux", "attach", "-t", "envctl-existing"),
        )
        captured: list[str] = []
        runtime = self._runtime(Path("/tmp/repo"), Path("/tmp/runtime"))

        def fake_read(prompt: str) -> str:
            captured.append(prompt)
            return "n"

        runtime._read_interactive_command_line = fake_read  # type: ignore[assignment]

        action = tmux_session._prompt_existing_tmux_session_action(runtime, attach_target=prompt_target)

        self.assertEqual(action, "new")
        self.assertEqual(len(captured), 1)
        self.assertIn("Y=attach / n=create new session", captured[0])

    def test_find_existing_tmux_attach_target_parses_custom_separator_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="envctl-existing\n", stderr=""),
                    subprocess.CompletedProcess(
                        args=["tmux"],
                        returncode=0,
                        stdout=f"feature-a-1|||ENVCTL_TMUX_PATH|||{worktree_root}\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(
                        args=["tmux"],
                        returncode=0,
                        stdout='  ┃  Ask anything... "Fix broken tests"\n  ctrl+p commands\n  ~/repo /status\n',
                        stderr="",
                    ),
                ]
            )

            attach_target = tmux_transport._find_existing_tmux_attach_target(
                rt,
                repo_root=repo,
                created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md"),),
                cli="opencode",
            )

            self.assertIsNotNone(attach_target)
            assert attach_target is not None
            expected_session = _tmux_session_name_for_worktree(
                repo,
                CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md"),
                cli="opencode",
            )
            self.assertEqual(attach_target.session_name, expected_session)
            self.assertEqual(attach_target.window_name, "feature-a-1")

    def test_tmux_session_name_is_different_for_different_worktrees(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            worktree_a = repo / "trees" / "feature-a" / "1"
            worktree_b = repo / "trees" / "feature-b" / "1"
            worktree_a.mkdir(parents=True, exist_ok=True)
            worktree_b.mkdir(parents=True, exist_ok=True)

            session_a = _tmux_session_name_for_worktree(
                repo,
                CreatedPlanWorktree(name="feature-a-1", root=worktree_a, plan_file="a.md"),
                cli="opencode",
            )
            session_b = _tmux_session_name_for_worktree(
                repo,
                CreatedPlanWorktree(name="feature-b-1", root=worktree_b, plan_file="b.md"),
                cli="opencode",
            )

            self.assertNotEqual(session_a, session_b)

    def test_tmux_session_name_is_different_for_same_worktree_but_different_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            worktree = repo / "trees" / "feature-a" / "1"
            worktree.mkdir(parents=True, exist_ok=True)

            session_opencode = _tmux_session_name_for_worktree(
                repo,
                CreatedPlanWorktree(name="feature-a-1", root=worktree, plan_file="a.md"),
                cli="opencode",
            )
            session_codex = _tmux_session_name_for_worktree(
                repo,
                CreatedPlanWorktree(name="feature-a-1", root=worktree, plan_file="a.md"),
                cli="codex",
            )

            self.assertNotEqual(session_opencode, session_codex)

    def test_ensure_tmux_window_waits_until_window_list_contains_created_window(self) -> None:
        self.assertIsNotNone(_ensure_tmux_window)
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            rt._command_exists = lambda command: command in {"tmux", "opencode", "zsh"}  # type: ignore[assignment]
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["tmux"], returncode=1, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="other\n", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="feature-a-1\n", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
            ):
                error = _ensure_tmux_window(
                    rt,
                    session_name="envctl-test-session",
                    window_name="feature-a-1",
                    launch_config=launch_support.PlanAgentLaunchConfig(
                        enabled=True,
                        transport="tmux",
                        cli="opencode",
                        cli_command="opencode",
                        preset="implement_task",
                        codex_cycles=0,
                        codex_cycles_warning=None,
                        shell="zsh",
                        require_cmux_context=True,
                        cmux_workspace="",
                        direct_prompt_enabled=True,
                        ulw_loop_prefix=False,
                        ulw_suffix=False,
                    ),
                    worktree=CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),
                )

            self.assertIsNone(error)
            list_windows_calls = [
                call
                for call in rt.process_runner.calls
                if len(call) >= 6
                and call[0:3] == ["tmux", "list-windows", "-t"]
                and call[3] == "envctl-test-session"
                and call[4] == "-F"
            ]
            self.assertGreaterEqual(len(list_windows_calls), 2)
            self.assertIn(["tmux", "set-option", "-t", "envctl-test-session", "mouse", "on"], rt.process_runner.calls)

    def test_tmux_codex_queue_confirms_message_after_tab(self) -> None:
        sent_keys: list[str] = []
        queued_text = "Direct queued prompt body"
        state = {"stage": "typed"}
        queue_hint_screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "  Direct queued prompt body\n"
            "  tab to queue message\n"
        )
        committed_screen = "• Queued follow-up messages\n"
        runtime = _RuntimeHarness(
            config=load_config({"RUN_REPO_ROOT": "/tmp/repo", "RUN_SH_RUNTIME_DIR": "/tmp/runtime"}),
            env={},
            process_runner=_RecordingRunner(),
        )

        def fake_send_key(*_args, key, **_kwargs):  # noqa: ANN202, ANN001
            sent_keys.append(key)
            if key == "tab":
                state["stage"] = "committed"
            return None

        def fake_read_screen(*_args, **_kwargs):  # noqa: ANN202, ANN001
            return queue_hint_screen if state["stage"] == "typed" else committed_screen

        with (
            patch("envctl_engine.planning.plan_agent.tmux_transport._send_tmux_key", side_effect=fake_send_key),
            patch("envctl_engine.planning.plan_agent.tmux_transport._read_tmux_screen", side_effect=fake_read_screen),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter(step=0.1)),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
        ):
            queued = tmux_transport._queue_tmux_codex_message(
                runtime, session_name="envctl-test", window_name="feature-a-1", text=queued_text, require_text_match=False
            )

        self.assertTrue(queued)
        self.assertEqual(sent_keys, ["tab"])

    def test_tmux_codex_queue_fails_when_message_remains_in_textbox_after_tab(self) -> None:
        sent_keys: list[str] = []
        queued_text = "Direct queued prompt body"
        stuck_screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "  Direct queued prompt body\n"
            "  tab to queue message\n"
        )
        runtime = _RuntimeHarness(
            config=load_config({"RUN_REPO_ROOT": "/tmp/repo", "RUN_SH_RUNTIME_DIR": "/tmp/runtime"}),
            env={},
            process_runner=_RecordingRunner(),
        )

        def fake_send_key(*_args, key, **_kwargs):  # noqa: ANN202, ANN001
            sent_keys.append(key)
            return None

        with (
            patch("envctl_engine.planning.plan_agent.tmux_transport._send_tmux_key", side_effect=fake_send_key),
            patch("envctl_engine.planning.plan_agent.tmux_transport._read_tmux_screen", return_value=stuck_screen),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter(step=0.1)),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
        ):
            queued = tmux_transport._queue_tmux_codex_message(
                runtime, session_name="envctl-test", window_name="feature-a-1", text=queued_text, require_text_match=False
            )

        self.assertFalse(queued)
        self.assertEqual(sent_keys, ["tab", "tab"])

    def test_tmux_codex_queue_accepts_pasted_content_only_after_post_tab_confirmation(self) -> None:
        sent_keys: list[str] = []
        queued_text = "Direct queued prompt body\nwith multiple lines"
        state = {"stage": "typed"}
        queue_hint_screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "› [Pasted Content 6674 chars]\n"
            "  tab to queue message\n"
        )
        committed_screen = "• Queued follow-up messages\n"
        runtime = _RuntimeHarness(
            config=load_config({"RUN_REPO_ROOT": "/tmp/repo", "RUN_SH_RUNTIME_DIR": "/tmp/runtime"}),
            env={},
            process_runner=_RecordingRunner(),
        )

        def fake_send_key(*_args, key, **_kwargs):  # noqa: ANN202, ANN001
            sent_keys.append(key)
            if key == "tab":
                state["stage"] = "committed"
            return None

        with (
            patch("envctl_engine.planning.plan_agent.tmux_transport._send_tmux_key", side_effect=fake_send_key),
            patch(
                "envctl_engine.planning.plan_agent.tmux_transport._read_tmux_screen",
                side_effect=lambda *_args, **_kwargs: queue_hint_screen if state["stage"] == "typed" else committed_screen,
            ),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter(step=0.1)),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
        ):
            queued = tmux_transport._queue_tmux_codex_message(
                runtime, session_name="envctl-test", window_name="feature-a-1", text=queued_text, require_text_match=False
            )

        self.assertTrue(queued)
        self.assertEqual(sent_keys, ["tab"])

    def test_tmux_opencode_ready_wait_allows_slow_cold_start(self) -> None:
        self.assertIsNotNone(_wait_for_tmux_cli_ready)
        clock = {"now": 0.0}
        runtime = _RuntimeHarness(
            config=load_config(
                {
                    "RUN_REPO_ROOT": "/tmp/repo",
                    "RUN_SH_RUNTIME_DIR": "/tmp/runtime",
                }
            ),
            env={},
            process_runner=_RecordingRunner(),
        )

        def monotonic() -> float:
            return clock["now"]

        def sleep(seconds: float) -> None:
            clock["now"] += float(seconds)

        def screen(*_args: object, **_kwargs: object) -> str:
            if clock["now"] >= 8.0:
                return '  ┃  Ask anything... "Fix broken tests"\n  ctrl+p commands\n  ~/repo /status\n'
            return "Loading workspace...\n"

        with (
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=monotonic),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", side_effect=sleep),
            patch("envctl_engine.planning.plan_agent.tmux_transport._read_tmux_screen", side_effect=screen),
        ):
            ready = _wait_for_tmux_cli_ready(
                runtime,
                session_name="envctl-test",
                window_name="feature-a",
                cli="opencode",
            )

        self.assertTrue(ready.ready)
        self.assertEqual(ready.reason, "ready")
        self.assertGreaterEqual(clock["now"], 8.0)

    def test_tmux_opencode_ready_wait_reports_timeout(self) -> None:
        self.assertIsNotNone(_wait_for_tmux_cli_ready)
        clock = {"now": 0.0}
        runtime = _RuntimeHarness(
            config=load_config(
                {
                    "RUN_REPO_ROOT": "/tmp/repo",
                    "RUN_SH_RUNTIME_DIR": "/tmp/runtime",
                }
            ),
            env={},
            process_runner=_RecordingRunner(),
        )

        def monotonic() -> float:
            return clock["now"]

        def sleep(seconds: float) -> None:
            clock["now"] += float(seconds)

        def screen(*_args: object, **_kwargs: object) -> str:
            return "Loading workspace...\n"

        with (
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=monotonic),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", side_effect=sleep),
            patch("envctl_engine.planning.plan_agent.tmux_transport._read_tmux_screen", side_effect=screen),
        ):
            ready = _wait_for_tmux_cli_ready(
                runtime,
                session_name="envctl-test",
                window_name="feature-a",
                cli="opencode",
            )

        self.assertFalse(ready.ready)
        self.assertEqual(ready.reason, "opencode_ready_timeout")
        self.assertIn("Loading workspace", ready.screen_excerpt)
