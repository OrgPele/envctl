# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *


class PlanAgentLaunchTmuxExistingSessionTests(PlanAgentLaunchSupportTestCase):
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
