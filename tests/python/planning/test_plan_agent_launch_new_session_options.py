# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *


class PlanAgentLaunchNewSessionOptionsTests(PlanAgentLaunchSupportTestCase):
    def test_new_session_flag_creates_suffixed_session_for_existing_worktree(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                worktree_root = repo / "trees" / "feature-a" / "1"
                worktree_root.mkdir(parents=True, exist_ok=True)
                worktree = CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md")
                rt = self._runtime(repo, runtime)
                rt._command_exists = lambda command: command in {"tmux", "opencode", "zsh"}  # type: ignore[assignment]
                base_session = _tmux_session_name_for_worktree(repo, worktree, cli="opencode")
                new_session = f"{base_session}-2"
                existing_attach_target = launch_support.PlanAgentAttachTarget(
                    repo_root=repo,
                    session_name=base_session,
                    window_name="feature-a-1",
                    attach_via="attach-session",
                    attach_command=("tmux", "attach", "-t", base_session),
                )
                launched_sessions: list[str] = []

                def launch_single(_runtime: object, **kwargs: object) -> launch_support.PlanAgentLaunchOutcome:
                    launched_sessions.append(str(kwargs["session_name"]))
                    return launch_support.PlanAgentLaunchOutcome(
                        worktree_name=worktree.name,
                        worktree_root=worktree.root,
                        surface_id=None,
                        status="launched",
                    )

                with (
                    patch("envctl_engine.planning.plan_agent.tmux_transport._find_existing_tmux_attach_target", return_value=existing_attach_target),
                    patch("envctl_engine.planning.plan_agent.tmux_transport._next_available_tmux_session_name", return_value=new_session) as next_session_mock,
                    patch("envctl_engine.planning.plan_agent.tmux_transport._launch_single_tmux_worktree", side_effect=launch_single),
                ):
                    result = launch_plan_agent_terminals(
                        rt,
                        route=parse_route(["--plan", "feature-a", "--tmux", "--opencode", "--new-session", "--headless"], env={}),
                        created_worktrees=(worktree,),
                    )

                self.assertEqual(result.status, "launched")
                self.assertEqual(launched_sessions, [new_session])
                next_session_mock.assert_called_once_with(rt, base_session)
                self.assertIsNotNone(result.attach_target)
                assert result.attach_target is not None
                self.assertEqual(result.attach_target.session_name, new_session)
                self.assertEqual(result.attach_target.attach_command, ("tmux", "attach", "-t", new_session))

    def test_new_session_command_preserves_ulw_flag(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                rt = self._runtime(repo, runtime)
                worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="feature-a.md")
                command = recovery._new_session_command_for_route(
                    rt,
                    route=parse_route(["--plan", "feature-a", "--tmux", "--opencode", "--ulw", "--headless"], env={}),
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
                        ulw_loop_prefix=True,
                        ulw_suffix=False,
                    ),
                    created_worktrees=(worktree,),
                )

            self.assertEqual(
                command,
                (
                    "ENVCTL_USE_REPO_WRAPPER=1",
                    str(repo.resolve() / "bin" / "envctl"),
                    "--plan",
                    "feature-a",
                    "--tmux",
                    "--opencode",
                    "--ulw",
                    "--new-session",
                    "--headless",
                ),
            )

    def test_new_session_command_preserves_no_ulw_loop_flag(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                rt = self._runtime(repo, runtime)
                worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="feature-a.md")
                command = recovery._new_session_command_for_route(
                    rt,
                    route=parse_route(["--plan", "feature-a", "--cmux", "--opencode", "--no-ulw-loop", "--headless"], env={}),
                    launch_config=launch_support.PlanAgentLaunchConfig(
                        enabled=True,
                        transport="cmux",
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
                    created_worktrees=(worktree,),
            )

            self.assertIn("--cmux", command)
            self.assertNotIn("--tmux", command)
            self.assertIn("--no-ulw-loop", command)
            self.assertLess(command.index("--no-ulw-loop"), command.index("--new-session"))
