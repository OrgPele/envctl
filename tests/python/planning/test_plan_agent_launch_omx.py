# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *


class PlanAgentLaunchOmxTests(PlanAgentLaunchSupportTestCase):
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
                    submitted: list[str] = []
                    queued: list[str] = []

                    def fake_submit(*_args, prompt_text, **_kwargs):  # noqa: ANN202, ANN001
                        submitted.append(prompt_text)
                        return None

                    def fake_queue(*_args, queued_steps, **_kwargs):  # noqa: ANN202, ANN001
                        queued.extend(step.kind for step in queued_steps)
                        return None

                    with (
                        patch("envctl_engine.planning.plan_agent.tmux_transport._wait_for_tmux_cli_ready", return_value=None),
                        patch("envctl_engine.planning.plan_agent.tmux_transport._submit_tmux_codex_goal", return_value=None),
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
                    self.assertEqual(len(submitted), 1)
                    self.assertTrue(submitted[0].startswith(f"${workflow_name}"))
                    self.assertEqual(queued, ["queue_direct_prompt", "queue_message", "queue_message"])

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

    def test_plan_agent_launch_prereqs_switch_to_omx_for_omx_route(self) -> None:
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
                route=parse_route(["--plan", "feature-a", "--omx", "--codex"], env={}),
            )

        self.assertEqual(prereqs, ("omx", "tmux", "script", "codex"))

    def test_resolve_plan_agent_launch_config_accepts_omx_route_flag(self) -> None:
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

            launch_config = launch_support.resolve_plan_agent_launch_config(
                config,
                {},
                route=parse_route(["--plan", "feature-a", "--omx", "--codex"], env={}),
            )

        self.assertEqual(launch_config.transport, "omx")
        self.assertEqual(launch_config.cli, "codex")
        self.assertTrue(launch_config.enabled)

    def test_resolve_plan_agent_launch_config_records_omx_workflow_flag(self) -> None:
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

            for token, workflow_name in (("--ultragoal", "ultragoal"), ("--ralph", "ralph"), ("--team", "team")):
                with self.subTest(token=token):
                    launch_config = launch_support.resolve_plan_agent_launch_config(
                        config,
                        {},
                        route=parse_route(["--plan", "feature-a", "--omx", token], env={}),
                    )

                    self.assertEqual(launch_config.transport, "omx")
                    self.assertEqual(launch_config.cli, "codex")
                    self.assertEqual(launch_config.omx_workflow, workflow_name)
                    self.assertEqual(launch_config.codex_cycles, 2)

    def test_resolve_plan_agent_launch_config_keeps_cycles_for_plain_omx(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_CODEX_CYCLES": "3",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(
                config,
                {},
                route=parse_route(["--plan", "feature-a", "--omx"], env={}),
            )

        self.assertEqual(launch_config.transport, "omx")
        self.assertEqual(launch_config.cli, "codex")
        self.assertEqual(launch_config.codex_cycles, 3)
        self.assertIsNone(launch_config.codex_cycles_warning)

    def test_resolve_plan_agent_launch_config_keeps_cycles_for_omx_workflows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_CODEX_CYCLES": "3",
                }
            )

            for token, workflow_name in (("--ultragoal", "ultragoal"), ("--ralph", "ralph"), ("--team", "team")):
                with self.subTest(token=token):
                    launch_config = launch_support.resolve_plan_agent_launch_config(
                        config,
                        {},
                        route=parse_route(["--plan", "feature-a", "--omx", token], env={}),
                    )
                    workflow = _build_plan_agent_workflow(
                        cli=launch_config.cli,
                        preset=launch_config.preset,
                        codex_cycles=launch_config.codex_cycles,
                        direct_prompt_enabled=launch_config.direct_prompt_enabled,
                    )

                    self.assertEqual(launch_config.omx_workflow, workflow_name)
                    self.assertEqual(launch_config.codex_cycles, 3)
                    self.assertIsNone(launch_config.codex_cycles_warning)
                    self.assertEqual(workflow.mode, "codex_cycles")
                    self.assertEqual(workflow.codex_cycles, 3)
                    self.assertEqual(len(workflow.steps), 10)
                    self.assertEqual(workflow.steps[1].text, _first_cycle_completion_instruction_text())
                    self.assertEqual(workflow.steps[-2].text, _browser_e2e_instruction_text())
                    self.assertEqual(workflow.steps[-1].text, _pr_review_comments_instruction_text())

    def test_resolve_plan_agent_launch_config_forces_codex_for_omx_when_env_prefers_opencode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_CLI": "opencode",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(
                config,
                {},
                route=parse_route(["--plan", "feature-a", "--omx"], env={}),
            )

        self.assertEqual(launch_config.transport, "omx")
        self.assertEqual(launch_config.cli, "codex")
        self.assertEqual(launch_config.cli_command, "codex --dangerously-bypass-approvals-and-sandbox")

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

    def test_omx_launch_records_late_spawn_exit_diagnostics(self) -> None:
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

            class _ExitedProcess:
                pid = 4242
                args = ["script", "-qfc", "omx --tmux", "/dev/null"]

                def poll(self) -> int:
                    return 7

            rt._omx_spawn_processes = [_ExitedProcess()]  # type: ignore[attr-defined]

            with (
                patch("envctl_engine.planning.plan_agent.omx_transport._find_existing_omx_attach_target", return_value=None),
                patch("envctl_engine.planning.plan_agent.omx_transport._spawn_omx_session_for_worktree", return_value=None),
                patch("envctl_engine.planning.plan_agent.omx_transport._wait_for_omx_attach_target", return_value=attach_target),
                patch("envctl_engine.planning.plan_agent.launch._run_tmux_existing_session_workflow", return_value=None),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=True),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_active_pane_id", return_value="%42"),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a", "--omx", "--codex"], env={}),
                    created_worktrees=(worktree,),
                )

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.outcomes[0].reason, "omx_session_exited")
            exited_events = self._events(rt, "planning.agent_launch.omx_spawn.exited_early")
            self.assertEqual(exited_events[-1]["pid"], 4242)
            self.assertEqual(exited_events[-1]["returncode"], 7)
            self.assertEqual(exited_events[-1]["command"], ["script", "-qfc", "omx --tmux", "/dev/null"])
            self.assertEqual(exited_events[-1]["worktree"], "feature-a-1")
            self.assertEqual(exited_events[-1]["worktree_root"], str(repo.resolve()))
            self.assertEqual(exited_events[-1]["omx_root"], str(self._expected_omx_root(worktree)))

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

    def test_missing_launch_commands_includes_script_for_omx(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            launch_config = launch_support.resolve_plan_agent_launch_config(
                cast(Any, rt.config),
                rt.env,
                route=parse_route(["--plan", "feature-a", "--omx"], env={}),
            )

            with patch.object(rt, "_command_exists", side_effect=lambda command: command != "script"):
                missing = config._missing_launch_commands(rt, launch_config)

            self.assertEqual(missing, ["script"])

    def test_omx_spawn_emits_started_event_with_sanitized_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime, env={"ENVCTL_SECRET_TOKEN": "do-not-log"})
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
                omx_workflow="ralph",
            )

            class _RunningPopen:
                pid = 5151

                def __init__(self, _cmd, **_kwargs):  # noqa: ANN001
                    self.stdin = None
                    self.stdout = None
                    self.stderr = None

                def poll(self):
                    return None

            with patch("envctl_engine.planning.plan_agent.omx_transport.subprocess.Popen", _RunningPopen):
                error = omx_transport._spawn_omx_session_for_worktree(
                    rt,
                    launch_config=launch_config,
                    worktree=worktree,
                )

            self.assertIsNone(error)
            event = self._events(rt, "planning.agent_launch.omx_spawn.started")[-1]
            self.assertEqual(event["pid"], 5151)
            self.assertEqual(event["command"], ["omx", "--tmux", "--madmax"])
            self.assertEqual(event["popen_command"], ["script", "-qfc", "omx --tmux --madmax", "/dev/null"])
            self.assertEqual(event["worktree"], "feature-a-1")
            self.assertEqual(event["worktree_root"], str(repo.resolve()))
            self.assertEqual(event["omx_root"], str(self._expected_omx_root(worktree)))
            self.assertEqual(event["transport"], "omx")
            self.assertTrue(event["madmax"])
            self.assertNotIn("env", event)
            self.assertNotIn("do-not-log", json.dumps(event))

    def test_omx_spawn_immediate_failure_emits_bounded_output_and_command_metadata(self) -> None:
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
                omx_workflow="",
            )
            long_stdout = "stdout-line\n" + ("x" * 2000)
            long_stderr = "stderr-line\n" + ("y" * 2000)

            class _ExitedPopen:
                pid = 6161
                returncode = 9

                def __init__(self, _cmd, **_kwargs):  # noqa: ANN001
                    pass

                def poll(self):
                    return self.returncode

                def communicate(self, timeout=None):  # noqa: ANN001
                    _ = timeout
                    return long_stdout, long_stderr

            with patch("envctl_engine.planning.plan_agent.omx_transport.subprocess.Popen", _ExitedPopen):
                error = omx_transport._spawn_omx_session_for_worktree(
                    rt,
                    launch_config=launch_config,
                    worktree=worktree,
                )

            self.assertEqual(error, "stderr-line")
            event = self._events(rt, "planning.agent_launch.omx_spawn.failed")[-1]
            self.assertEqual(event["pid"], 6161)
            self.assertEqual(event["returncode"], 9)
            self.assertEqual(event["command"], ["omx", "--tmux", "--madmax"])
            self.assertEqual(event["worktree"], "feature-a-1")
            self.assertEqual(event["omx_root"], str(self._expected_omx_root(worktree)))
            self.assertEqual(event["stdout_excerpt"], long_stdout[:1000])
            self.assertEqual(event["stderr_excerpt"], long_stderr[:1000])
            self.assertNotIn("env", event)

    def test_omx_spawn_sets_deterministic_omx_root_for_madmax_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            inherited_root = Path(tmpdir) / "inherited-omx"
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "OMX_ROOT": str(inherited_root),
                    "OMX_STATE_ROOT": str(Path(tmpdir) / "stale-state"),
                    "TMUX": "/tmp/tmux-0/default,1,0",
                    "TMUX_PANE": "%7",
                },
            )
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
                omx_workflow="ralph",
            )
            popen_calls: list[dict[str, object]] = []

            class _RunningPopen:
                def __init__(self, cmd, **kwargs):  # noqa: ANN001
                    popen_calls.append({"cmd": list(cmd), **kwargs})
                    self.stdin = None
                    self.stdout = None
                    self.stderr = None

                def poll(self):
                    return None

            with patch("envctl_engine.planning.plan_agent.omx_transport.subprocess.Popen", _RunningPopen):
                error = omx_transport._spawn_omx_session_for_worktree(
                    rt,
                    launch_config=launch_config,
                    worktree=worktree,
                )

            self.assertIsNone(error)
            self.assertEqual(popen_calls[0]["cmd"], ["script", "-qfc", "omx --tmux --madmax", "/dev/null"])
            env = cast(dict[str, str], popen_calls[0]["env"])
            self.assertEqual(env["OMX_ROOT"], str(self._expected_omx_root(worktree)))
            self.assertNotEqual(env["OMX_ROOT"], str(inherited_root))
            self.assertEqual(env["OMX_LAUNCH_POLICY"], "detached-tmux")
            self.assertNotIn("TMUX", env)
            self.assertNotIn("TMUX_PANE", env)
            self.assertEqual(
                self._events(rt, "planning.agent_launch.omx_state_root_selected"),
                [
                    {
                        "event": "planning.agent_launch.omx_state_root_selected",
                        "worktree": "feature-a-1",
                        "omx_root": str(self._expected_omx_root(worktree)),
                        "transport": "omx",
                    }
                ],
            )

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

    def test_omx_spawn_keeps_pseudo_terminal_input_alive_until_attach_target_is_ready(self) -> None:
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
                omx_workflow="",
            )
            popen_instances: list[object] = []
            popen_calls: list[dict[str, object]] = []

            class _Pipe:
                def __init__(self) -> None:
                    self.closed = False

                def close(self) -> None:
                    self.closed = True

            class _RunningPopen:
                def __init__(self, cmd, **kwargs):  # noqa: ANN001
                    popen_calls.append({"cmd": list(cmd), **kwargs})
                    self.stdin = _Pipe()
                    self.stdout = _Pipe()
                    self.stderr = _Pipe()
                    popen_instances.append(self)

                def poll(self):
                    return None

            with patch("envctl_engine.planning.plan_agent.omx_transport.subprocess.Popen", _RunningPopen):
                error = omx_transport._spawn_omx_session_for_worktree(
                    rt,
                    launch_config=launch_config,
                    worktree=worktree,
                )

            self.assertIsNone(error)
            self.assertEqual(popen_calls[0]["stdin"], subprocess.PIPE)
            self.assertEqual(cast(dict[str, str], popen_calls[0]["env"])["OMX_LAUNCH_POLICY"], "detached-tmux")
            process = cast(Any, popen_instances[0])
            self.assertFalse(process.stdin.closed)
            self.assertTrue(process.stdout.closed)
            self.assertTrue(process.stderr.closed)
            self.assertEqual(cast(Any, rt)._omx_spawn_processes[0].process, process)

    def test_omx_spawn_preserves_codex_config_discovery_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            home = Path(tmpdir) / "home"
            codex_home = home / ".codex"
            repo.mkdir(parents=True, exist_ok=True)
            codex_home.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "TMUX": "/tmp/tmux-0/default,1,0",
                    "TMUX_PANE": "%7",
                    "ENVCTL_ONLY": "yes",
                },
            )
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
                omx_workflow="ralph",
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

            with (
                patch.dict(os.environ, {"HOME": str(home)}, clear=True),
                patch("envctl_engine.planning.plan_agent.omx_transport.subprocess.Popen", _DummyPopen),
            ):
                error = omx_transport._spawn_omx_session_for_worktree(
                    rt,
                    launch_config=launch_config,
                    worktree=worktree,
                )

            self.assertIsNone(error)
            env = cast(dict[str, str], popen_calls[0]["env"])
            self.assertEqual(env["HOME"], str(home))
            self.assertEqual(env["CODEX_HOME"], str(codex_home))
            self.assertEqual(env["ENVCTL_ONLY"], "yes")
            self.assertNotIn("TMUX", env)
            self.assertNotIn("TMUX_PANE", env)

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

    def test_omx_launch_reports_spawn_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                },
            )

            buffer = StringIO()
            with (
                redirect_stdout(buffer),
                patch("envctl_engine.planning.plan_agent.omx_transport._find_existing_omx_attach_target", return_value=None),
                patch("envctl_engine.planning.plan_agent.omx_transport._spawn_omx_session_for_worktree", return_value="omx exited before creating a managed session"),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a", "--omx", "--codex"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.reason, "launch_failed")
            self.assertEqual(len(result.outcomes), 1)
            self.assertEqual(result.outcomes[0].reason, "omx exited before creating a managed session")
            self.assertIn("omx exited before creating a managed session", buffer.getvalue())

    def test_new_session_command_preserves_omx_workflow_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="feature-a.md")
            for token, workflow_name in (("--ultragoal", "ultragoal"), ("--ralph", "ralph"), ("--team", "team")):
                with self.subTest(token=token):
                    command = recovery._new_session_command_for_route(
                        rt,
                        route=parse_route(["--plan", "feature-a", "--omx", token, "--headless"], env={}),
                        launch_config=launch_support.PlanAgentLaunchConfig(
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
                            omx_workflow=cast(Any, workflow_name),
                        ),
                        created_worktrees=(worktree,),
                    )

                    self.assertIn(token, command)
                    self.assertLess(command.index(token), command.index("--new-session"))
