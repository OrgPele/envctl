# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *


class PlanAgentLaunchOmxSpawnTests(PlanAgentLaunchSupportTestCase):
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
