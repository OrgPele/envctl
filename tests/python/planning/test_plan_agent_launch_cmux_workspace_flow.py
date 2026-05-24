# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *



class PlanAgentLaunchCmuxWorkspaceFlowTests(PlanAgentLaunchSupportTestCase):
    def test_launch_sequence_supports_opencode_and_default_implementation_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "ENVCTL_PLAN_AGENT_CLI": "opencode",
                    "ENVCTL_PLAN_AGENT_REQUIRE_CMUX_CONTEXT": "false",
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
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:12\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="Loading workspace...\n", stderr=""),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout='  ┃  Ask anything... "Fix broken tests"\n  ctrl+p commands\n  ~/repo  ⊙ 3 MCP /status    1.2.27\n',
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout=(
                            "  ┃ /implement_task                                                   ┃\n"
                            "  ┃ /implement_task.bak-20260313-192914                               ┃\n"
                            "  ┃ /implement_task.bak-20260315-173140                               ┃\n"
                            "  ┃                                                                 \n"
                            "  ┃  /implement_task                                                 \n"
                        ),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout=(
                            "  ┃                                                                 \n"
                            "  ┃  /implement_task                                                 \n"
                            "  ┃                                                                 \n"
                            "  ┃  Sisyphus (Ultraworker)                                          \n"
                        ),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None) as sleep_mock,
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter()),
                patch("envctl_engine.planning.plan_agent.cmux_transport.threading.Thread", _ImmediateThread),
            ):
                _ImmediateThread.created = []
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(rt.process_runner.calls[0], ["cmux", "list-workspaces"])
            self.assertEqual(rt.process_runner.calls[1], ["cmux", "new-surface", "--workspace", "workspace:8"])
            self.assertIn(
                ["cmux", "respawn-pane", "--workspace", "workspace:8", "--surface", "surface:12", "--command", "zsh"],
                rt.process_runner.calls,
            )
            self.assertIn(["cmux", "send", "--workspace", "workspace:8", "--surface", "surface:12", f"cd {repo}"], rt.process_runner.calls)
            self.assertIn(["cmux", "send-key", "--workspace", "workspace:8", "--surface", "surface:12", "enter"], rt.process_runner.calls)
            self.assertIn(["cmux", "send", "--workspace", "workspace:8", "--surface", "surface:12", "opencode"], rt.process_runner.calls)
            direct_prompt_calls = [
                call
                for call in rt.process_runner.calls
                if call[:4] == ["cmux", "set-buffer", "--name", "envctl-surface-12"]
            ]
            self.assertEqual(len(direct_prompt_calls), 1)
            self.assertTrue(str(direct_prompt_calls[0][-1]).startswith("/ulw-loop You are implementing real code"))
            self.assertIn(
                ["cmux", "paste-buffer", "--name", "envctl-surface-12", "--workspace", "workspace:8", "--surface", "surface:12"],
                rt.process_runner.calls,
            )
            self.assertEqual(len(_ImmediateThread.created), 1)
            self.assertTrue(_ImmediateThread.created[0].started)
            self.assertEqual(_ImmediateThread.created[0].daemon, False)
            self.assertGreaterEqual(rt.process_runner.calls.count(["cmux", "read-screen", "--workspace", "workspace:8", "--surface", "surface:12", "--lines", "80"]), 2)
            self.assertGreaterEqual(
                rt.process_runner.calls.count(
                    ["cmux", "send-key", "--workspace", "workspace:8", "--surface", "surface:12", "enter"]
                ),
                2,
            )
            self.assertNotIn(
                ["cmux", "send-key", "--workspace", "workspace:8", "--surface", "surface:12", "tab"],
                rt.process_runner.calls,
            )
            self.assertGreaterEqual(len(sleep_mock.call_args_list), 2)
            self.assertIn(0.15, [call.args[0] for call in sleep_mock.call_args_list])
            self.assertIn(0.1, [call.args[0] for call in sleep_mock.call_args_list[1:]])

    def test_created_default_workspace_reuses_single_starter_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "CMUX_WORKSPACE_ID": "workspace:4",
                    "ENVCTL_PLAN_AGENT_CODEX_GOAL_ENABLE": "false",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:4  envctl  [selected]\n  workspace:2  supportopia\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="workspace:9\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:77\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
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
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(rt.process_runner.calls[0], ["cmux", "list-workspaces"])
            self.assertEqual(rt.process_runner.calls[1], ["cmux", "new-workspace", "--cwd", str(repo.resolve())])
            self.assertEqual(rt.process_runner.calls[2], ["cmux", "current-workspace"])
            self.assertEqual(
                rt.process_runner.calls[3],
                ["cmux", "rename-workspace", "--workspace", "workspace:9", "envctl implementation"],
            )
            self.assertEqual(rt.process_runner.calls[4], ["cmux", "list-pane-surfaces", "--workspace", "workspace:9"])
            self.assertNotIn(["cmux", "new-surface", "--workspace", "workspace:9"], rt.process_runner.calls)
            self.assertIn(
                ["cmux", "rename-tab", "--workspace", "workspace:9", "--surface", "surface:77", "feature-a-1"],
                rt.process_runner.calls,
            )
            self.assertIn(
                ["cmux", "respawn-pane", "--workspace", "workspace:9", "--surface", "surface:77", "--command", "zsh"],
                rt.process_runner.calls,
            )
            self.assertIn(["cmux", "send", "--workspace", "workspace:9", "--surface", "surface:77", f"cd {repo}"], rt.process_runner.calls)
            self.assertIn(
                [
                    "cmux",
                    "send",
                    "--workspace",
                    "workspace:9",
                    "--surface",
                    "surface:77",
                    "codex --dangerously-bypass-approvals-and-sandbox",
                ],
                rt.process_runner.calls,
            )
            self.assertTrue(
                any(
                    call[:4] == ["cmux", "set-buffer", "--name", "envctl-surface-77"]
                    and str(call[-1]).startswith("You are implementing real code, end-to-end.")
                    for call in rt.process_runner.calls
                )
            )
            self.assertIn(
                ["cmux", "paste-buffer", "--name", "envctl-surface-77", "--workspace", "workspace:9", "--surface", "surface:77"],
                rt.process_runner.calls,
            )
            self.assertEqual(len(_ImmediateThread.created), 1)
