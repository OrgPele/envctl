# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *



class PlanAgentLaunchCmuxWorkspaceCreatedTests(PlanAgentLaunchSupportTestCase):
    def test_created_named_workspace_reuses_single_starter_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "brand-new-workspace",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:1  envctl  [selected]\n  workspace:2  supportopia\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="workspace:3\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:44\n", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._start_background_surface_bootstrap", return_value=None),
            ):
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
                ["cmux", "rename-workspace", "--workspace", "workspace:3", "brand-new-workspace"],
            )
            self.assertEqual(rt.process_runner.calls[4], ["cmux", "list-pane-surfaces", "--workspace", "workspace:3"])
            self.assertNotIn(["cmux", "new-surface", "--workspace", "workspace:3"], rt.process_runner.calls)

    def test_created_workspace_emits_probe_and_reused_surface_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "brand-new-workspace",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:1  envctl  [selected]\n  workspace:2  supportopia\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="workspace:3\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:44\n", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._start_background_surface_bootstrap", return_value=None),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            probe_events = self._events(rt, "planning.agent_launch.workspace_surface_probe")
            self.assertEqual(
                probe_events,
                [
                    {
                        "event": "planning.agent_launch.workspace_surface_probe",
                        "workspace_id": "workspace:3",
                        "result": "single",
                        "surface_count": 1,
                        "surface_id": "surface:44",
                    }
                ],
            )
            self.assertEqual(self._events(rt, "planning.agent_launch.surface_fallback"), [])
            self.assertEqual(
                self._events(rt, "planning.agent_launch.surface_created"),
                [
                    {
                        "event": "planning.agent_launch.surface_created",
                        "workspace_id": "workspace:3",
                        "surface_id": "surface:44",
                        "worktree": "feature-a-1",
                        "source": "starter_reused",
                    }
                ],
            )

    def test_created_workspace_falls_back_to_new_surface_when_starter_probe_is_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "brand-new-workspace",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:1  envctl  [selected]\n  workspace:2  supportopia\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="workspace:3\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:44\nsurface:45\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:46\n", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._start_background_surface_bootstrap", return_value=None),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(rt.process_runner.calls[4], ["cmux", "list-pane-surfaces", "--workspace", "workspace:3"])
            self.assertEqual(rt.process_runner.calls[5], ["cmux", "new-surface", "--workspace", "workspace:3"])

    def test_created_workspace_emits_probe_and_fallback_events_when_probe_is_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "brand-new-workspace",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:1  envctl  [selected]\n  workspace:2  supportopia\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="workspace:3\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:44\nsurface:45\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:46\n", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._start_background_surface_bootstrap", return_value=None),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(
                self._events(rt, "planning.agent_launch.workspace_surface_probe"),
                [
                    {
                        "event": "planning.agent_launch.workspace_surface_probe",
                        "workspace_id": "workspace:3",
                        "result": "ambiguous",
                        "surface_count": 2,
                    }
                ],
            )
            self.assertEqual(
                self._events(rt, "planning.agent_launch.surface_fallback"),
                [
                    {
                        "event": "planning.agent_launch.surface_fallback",
                        "workspace_id": "workspace:3",
                        "reason": "ambiguous",
                    }
                ],
            )
            self.assertEqual(
                self._events(rt, "planning.agent_launch.surface_created"),
                [
                    {
                        "event": "planning.agent_launch.surface_created",
                        "workspace_id": "workspace:3",
                        "surface_id": "surface:46",
                        "worktree": "feature-a-1",
                        "source": "new_surface",
                    }
                ],
            )
