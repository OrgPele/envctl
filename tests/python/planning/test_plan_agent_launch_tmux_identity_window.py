# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *


class PlanAgentLaunchTmuxIdentityWindowTests(PlanAgentLaunchSupportTestCase):
    def test_tmux_target_accepts_pane_id_directly(self) -> None:
        self.assertEqual(tmux_transport._tmux_target("omx-feature-session", "%42"), "%42")

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
