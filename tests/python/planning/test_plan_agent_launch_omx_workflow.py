# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *


class PlanAgentLaunchOmxWorkflowTests(PlanAgentLaunchSupportTestCase):
    def test_omx_goal_then_workflow_then_cycle_queue_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_dir = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            for workflow_name in ("ralph", "ultragoal"):
                with self.subTest(workflow_name=workflow_name):
                    rt = self._runtime(repo, runtime_dir)
                    worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="features/a.md")
                    launch_config = launch_support.PlanAgentLaunchConfig(
                        enabled=True,
                        transport="omx",
                        cli="codex",
                        cli_command="codex",
                        preset="implement_task",
                        codex_cycles=1,
                        codex_cycles_warning=None,
                        shell="zsh",
                        require_cmux_context=True,
                        cmux_workspace="",
                        direct_prompt_enabled=False,
                        ulw_loop_prefix=False,
                        ulw_suffix=False,
                        omx_workflow=workflow_name,
                        codex_goal_enable=True,
                    )
                    workflow = _build_plan_agent_workflow(cli="codex", preset="implement_task", codex_cycles=1)
                    goals: list[str] = []
                    submitted: list[str] = []
                    queued: list[str] = []

                    def fake_submit_goal(*_args, goal_text, **_kwargs):  # noqa: ANN202, ANN001
                        goals.append(goal_text)
                        return None

                    def fake_submit(*_args, prompt_text, **_kwargs):  # noqa: ANN202, ANN001
                        submitted.append(prompt_text)
                        return None

                    def fake_queue(*_args, queued_steps, **_kwargs):  # noqa: ANN202, ANN001
                        queued.extend(step.kind for step in queued_steps)
                        return None

                    with (
                        patch("envctl_engine.planning.plan_agent.tmux_transport._wait_for_tmux_cli_ready", return_value=None),
                        patch("envctl_engine.planning.plan_agent.tmux_transport._submit_tmux_codex_goal", side_effect=fake_submit_goal),
                        patch("envctl_engine.planning.plan_agent.tmux_transport._submit_tmux_prompt_workflow_step", side_effect=fake_submit),
                        patch("envctl_engine.planning.plan_agent.tmux_transport._queue_tmux_codex_workflow_steps", side_effect=fake_queue),
                        patch("envctl_engine.planning.plan_agent.tmux_transport._workflow_step_prompt_text", side_effect=lambda *_args, step, **_kwargs: (f"resolved::{step.kind}::{step.text}", None)),
                    ):
                        error = tmux_transport._run_tmux_existing_session_workflow(
                            rt,
                            session_name="session",
                            window_name="window",
                            launch_config=launch_config,
                            workflow=workflow,
                            worktree=worktree,
                        )

                    self.assertIsNone(error)
                    self.assertEqual(len(goals), 1)
                    self.assertIn(f"OMX: ${workflow_name} completion contract remains active.", goals[0])
                    self.assertEqual(len(submitted), 1)
                    self.assertTrue(submitted[0].startswith(f"${workflow_name}"))
                    self.assertEqual(queued, ["queue_direct_prompt"])

    def test_omx_goal_fallback_still_submits_ralph_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_dir = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime_dir)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="features/a.md")
            launch_config = launch_support.PlanAgentLaunchConfig(
                enabled=True,
                transport="omx",
                cli="codex",
                cli_command="codex",
                preset="implement_task",
                codex_cycles=0,
                codex_cycles_warning=None,
                shell="zsh",
                require_cmux_context=True,
                cmux_workspace="",
                direct_prompt_enabled=False,
                ulw_loop_prefix=False,
                ulw_suffix=False,
                omx_workflow="ralph",
                codex_goal_enable=True,
            )
            workflow = _build_plan_agent_workflow(cli="codex", preset="implement_task", codex_cycles=0)
            submitted: list[str] = []

            with (
                patch("envctl_engine.planning.plan_agent.tmux_transport._wait_for_tmux_cli_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent.tmux_transport._submit_tmux_codex_goal", return_value="codex_goal_ready_timeout"),
                patch("envctl_engine.planning.plan_agent.tmux_transport._submit_tmux_prompt_workflow_step", side_effect=lambda *_args, prompt_text, **_kwargs: submitted.append(prompt_text) or None),
                patch("envctl_engine.planning.plan_agent.tmux_transport._queue_tmux_codex_workflow_steps", return_value=None),
                patch("envctl_engine.planning.plan_agent.tmux_transport._workflow_step_prompt_text", side_effect=lambda *_args, step, **_kwargs: (f"resolved::{step.kind}::{step.text}", None)),
            ):
                error = tmux_transport._run_tmux_existing_session_workflow(
                    rt,
                    session_name="session",
                    window_name="window",
                    launch_config=launch_config,
                    workflow=workflow,
                    worktree=worktree,
                )

        self.assertIsNone(error)
        self.assertTrue(submitted[0].startswith("$ralph"))
        self.assertEqual(
            self._events(rt, "planning.agent_launch.codex_goal_fallback")[0]["reason"],
            "codex_goal_ready_timeout",
        )

    def test_omx_workflow_launch_wraps_initial_prompt_with_workflow_keyword(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            for workflow_name in ("ultragoal", "ralph", "team"):
                with self.subTest(workflow_name=workflow_name):
                    rt = self._runtime(repo, runtime)
                    worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")
                    launch_config = launch_support.PlanAgentLaunchConfig(
                        enabled=True,
                        transport="omx",
                        cli="codex",
                        cli_command="codex --dangerously-bypass-approvals-and-sandbox",
                        preset="implement_task",
                        codex_cycles=0,
                        codex_cycles_warning=None,
                        shell="zsh",
                        require_cmux_context=True,
                        cmux_workspace="",
                        direct_prompt_enabled=False,
                        ulw_loop_prefix=False,
                        ulw_suffix=False,
                        omx_workflow=workflow_name,
                        codex_goal_enable=False,
                    )
                    workflow = _build_plan_agent_workflow(cli="codex", preset="implement_task", codex_cycles=0)
                    submitted_prompts: list[str] = []

                    with (
                        patch("envctl_engine.planning.plan_agent.tmux_transport._wait_for_tmux_cli_ready", return_value=None),
                        patch("envctl_engine.planning.plan_agent.tmux_transport._workflow_step_prompt_text", return_value=("IMPLEMENT TASK BODY", None)),
                        patch(
                            "envctl_engine.planning.plan_agent.tmux_transport._submit_tmux_prompt_workflow_step",
                            side_effect=lambda *_args, prompt_text, **_kwargs: submitted_prompts.append(prompt_text) or None,
                        ),
                    ):
                        error = tmux_transport._run_tmux_existing_session_workflow(
                            rt,
                            session_name="omx-feature-session",
                            window_name="%42",
                            launch_config=launch_config,
                            workflow=workflow,
                            worktree=worktree,
                        )

                    self.assertIsNone(error)
                    self.assertEqual(submitted_prompts, [f"${workflow_name}\n\nIMPLEMENT TASK BODY"])

    def test_omx_workflow_launch_does_not_double_wrap_existing_keyword(self) -> None:
        for workflow_name in ("ultragoal", "ralph", "team"):
            with self.subTest(workflow_name=workflow_name):
                prompt = f"${workflow_name}\n\nIMPLEMENT TASK BODY"
                self.assertEqual(
                    workflow._wrap_omx_initial_prompt_for_workflow(prompt, workflow=workflow_name),
                    prompt,
                )

    def test_omx_team_spawn_forces_worker_bypass_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")
            launch_config = launch_support.PlanAgentLaunchConfig(
                enabled=True,
                transport="omx",
                cli="codex",
                cli_command="codex --model gpt-5.4 --dangerously-bypass-approvals-and-sandbox",
                preset="implement_task",
                codex_cycles=0,
                codex_cycles_warning=None,
                shell="zsh",
                require_cmux_context=True,
                cmux_workspace="",
                direct_prompt_enabled=False,
                ulw_loop_prefix=False,
                ulw_suffix=False,
                omx_workflow="team",
            )
            popen_calls: list[dict[str, object]] = []

            class _DummyPopen:
                def __init__(self, cmd, **kwargs):  # noqa: ANN001
                    popen_calls.append({"cmd": list(cmd), **kwargs})
                    session_path = Path(str(kwargs["cwd"])) / ".omx" / "state" / "session.json"
                    session_path.parent.mkdir(parents=True, exist_ok=True)
                    session_path.write_text('{"session_id":"omx-abc123"}\n', encoding="utf-8")

                def poll(self):
                    return 0

            with patch("envctl_engine.planning.plan_agent.omx_transport.subprocess.Popen", _DummyPopen):
                error = omx_transport._spawn_omx_session_for_worktree(
                    rt,
                    launch_config=launch_config,
                    worktree=worktree,
                )

            self.assertIsNone(error)
            self.assertEqual(popen_calls[0]["cmd"], ["script", "-qfc", "omx --tmux --madmax", "/dev/null"])
            self.assertEqual(
                cast(dict[str, str], popen_calls[0]["env"])["OMX_TEAM_WORKER_LAUNCH_ARGS"],
                "--dangerously-bypass-approvals-and-sandbox",
            )
