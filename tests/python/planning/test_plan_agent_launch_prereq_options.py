# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *


class PlanAgentLaunchPrereqOptionsTests(PlanAgentLaunchSupportTestCase):
    def test_disabled_feature_returns_skipped_without_running_commands(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                rt = self._runtime(repo, runtime)

                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

                self.assertEqual(result.status, "skipped")
                self.assertEqual(result.reason, "disabled")
                self.assertEqual(rt.process_runner.calls, [])

    def test_enabled_feature_without_created_worktrees_returns_skipped(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                rt = self._runtime(
                    repo,
                    runtime,
                    env={
                        "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                        "ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT": "cmux",
                    },
                )

                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(),
                )

                self.assertEqual(result.status, "skipped")
                self.assertEqual(result.reason, "no_new_worktrees")
                self.assertEqual(rt.process_runner.calls, [])

    def test_missing_cmux_context_skips_when_required(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                rt = self._runtime(repo, runtime, env={"ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true"})

                buffer = StringIO()
                with redirect_stdout(buffer):
                    result = launch_plan_agent_terminals(
                        rt,
                        route=parse_route(["--plan", "feature-a"], env={}),
                        created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                    )

                self.assertEqual(result.status, "skipped")
                self.assertEqual(result.reason, "missing_cmux_context")
                self.assertIn("Plan agent launch skipped", buffer.getvalue())
                self.assertEqual(rt.process_runner.calls, [])

    def test_missing_cmux_executable_returns_failed(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                rt = self._runtime(
                    repo,
                    runtime,
                    env={
                        "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                        "CMUX_WORKSPACE_ID": "workspace:7",
                    },
                )
                rt._command_exists = lambda command: command in {"codex", "zsh"}  # type: ignore[assignment]

                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

                self.assertEqual(result.status, "failed")
                self.assertEqual(result.reason, "missing_executables")
                self.assertEqual(rt.process_runner.calls, [])

    def test_missing_selected_ai_cli_returns_failed(self) -> None:
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
                        "CMUX_WORKSPACE_ID": "workspace:7",
                    },
                )
                rt._command_exists = lambda command: command in {"cmux", "zsh"}  # type: ignore[assignment]

                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

                self.assertEqual(result.status, "failed")
                self.assertEqual(result.reason, "missing_executables")
                self.assertEqual(rt.process_runner.calls, [])

    def test_plan_agent_launch_prereqs_switch_to_tmux_for_tmux_route(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                config = load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                    }
                )

                prereqs = launch_support.plan_agent_launch_prereq_commands(
                    config,
                    {},
                    route=parse_route(["--plan", "feature-a", "--tmux", "--opencode"], env={}),
                )

            self.assertEqual(prereqs, ("tmux", "opencode"))

    def test_launch_plan_agent_terminals_rejects_ulw_without_opencode(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                rt = self._runtime(repo, runtime, env={"ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true"})

                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a", "--tmux", "--codex", "--ulw"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.reason, "unsupported_ulw_flag")
