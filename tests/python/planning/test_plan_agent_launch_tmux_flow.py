# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *


class PlanAgentLaunchTmuxFlowTests(PlanAgentLaunchSupportTestCase):
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
