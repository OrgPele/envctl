from __future__ import annotations

from pathlib import Path
import subprocess
import unittest

from envctl_engine.planning.plan_agent.models import (
    CreatedPlanWorktree,
    PlanAgentLaunchConfig,
    _PlanAgentWorkflow,
    _PlanAgentWorkflowStep,
)
from envctl_engine.planning.plan_agent.superset_worktree_launch_support import (
    launch_single_superset_worktree,
)


def _launch_config(
    *,
    workspace: str = "",
    project: str = "proj-1",
    open_workspace: bool = False,
    host: str = "",
    local: bool = True,
) -> PlanAgentLaunchConfig:
    return PlanAgentLaunchConfig(
        enabled=True,
        transport="superset",
        cli="codex",
        cli_command="codex",
        preset="implementation",
        codex_cycles=1,
        codex_cycles_warning=None,
        shell="/bin/zsh",
        require_cmux_context=False,
        cmux_workspace="",
        direct_prompt_enabled=False,
        ulw_loop_prefix=True,
        ulw_suffix=True,
        superset_workspace=workspace,
        superset_project=project,
        superset_open=open_workspace,
        superset_host=host,
        superset_local=local,
    )


def _workflow() -> _PlanAgentWorkflow:
    return _PlanAgentWorkflow(
        mode="single",
        codex_cycles=1,
        steps=(_PlanAgentWorkflowStep(kind="submit_prompt", text="initial"),),
    )


def _worktree() -> CreatedPlanWorktree:
    return CreatedPlanWorktree(name="feature-a-1", root=Path("/repo/trees/feature-a/1"), plan_file="a.md")


class _Runner:
    def __init__(self, *outputs: subprocess.CompletedProcess[str]) -> None:
        self.outputs = list(outputs)
        self.calls: list[list[str]] = []

    def run(self, command, **_kwargs):  # noqa: ANN001, ANN003
        self.calls.append(list(command))
        return self.outputs.pop(0)


class _Runtime:
    def __init__(self, runner: _Runner) -> None:
        self.process_runner = runner
        self.env = {"ENVCTL_TEST": "1"}
        self.events: list[tuple[str, dict[str, object]]] = []
        self.persisted = 0

    def _emit(self, event: str, **payload: object) -> None:
        self.events.append((event, payload))


class PlanAgentSupersetWorktreeLaunchSupportTests(unittest.TestCase):
    def test_prompt_resolution_error_returns_failed_outcome(self) -> None:
        runtime = _Runtime(_Runner())

        outcome = launch_single_superset_worktree(
            runtime,
            launch_config=_launch_config(),
            workflow=_workflow(),
            worktree=_worktree(),
            base_payload={"plan": "a.md"},
            superset_initial_prompt_fn=lambda *_args, **_kwargs: ("", "prompt failed"),
            superset_agent_and_prompt_fn=lambda *_args, **_kwargs: ("agent", "prompt"),
            git_branch_name_fn=lambda *_args, **_kwargs: ("branch", None),
            superset_workspace_name_fn=lambda _worktree: "workspace-name",
            parse_superset_json_output_fn=lambda _stdout: None,
            workspace_id_from_superset_payload_fn=lambda _payload: None,
            bridge_superset_desktop_workspace_fn=lambda *_args, **_kwargs: False,
            open_superset_workspace_fn=lambda *_args, **_kwargs: None,
            verify_superset_desktop_workspace_fn=lambda *_args, **_kwargs: None,
            restart_superset_desktop_fn=lambda *_args, **_kwargs: False,
            completed_process_error_text_fn=lambda _result: "process failed",
            persist_runtime_events_snapshot_fn=lambda _runtime: None,
        )

        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.reason, "prompt failed")
        self.assertEqual(runtime.events[0][0], "planning.agent_launch.failed")
        self.assertEqual(runtime.events[0][1]["reason"], "prompt_resolution_failed")

    def test_workspace_launch_uses_public_agent_run_command(self) -> None:
        runtime = _Runtime(
            _Runner(
                subprocess.CompletedProcess(
                    args=["superset"],
                    returncode=0,
                    stdout='{"workspace":{"id":"ws-existing"}}',
                    stderr="",
                )
            )
        )

        outcome = launch_single_superset_worktree(
            runtime,
            launch_config=_launch_config(workspace="ws-existing", project=""),
            workflow=_workflow(),
            worktree=_worktree(),
            base_payload={},
            superset_initial_prompt_fn=lambda *_args, **_kwargs: ("prompt", None),
            superset_agent_and_prompt_fn=lambda *_args, **_kwargs: ("agent-1", "prompt"),
            git_branch_name_fn=lambda *_args, **_kwargs: ("branch", None),
            superset_workspace_name_fn=lambda _worktree: "workspace-name",
            parse_superset_json_output_fn=lambda _stdout: {"workspace": {"id": "ws-existing"}},
            workspace_id_from_superset_payload_fn=lambda _payload: "ws-existing",
            bridge_superset_desktop_workspace_fn=lambda *_args, **_kwargs: False,
            open_superset_workspace_fn=lambda *_args, **_kwargs: None,
            verify_superset_desktop_workspace_fn=lambda *_args, **_kwargs: None,
            restart_superset_desktop_fn=lambda *_args, **_kwargs: False,
            completed_process_error_text_fn=lambda _result: "process failed",
            persist_runtime_events_snapshot_fn=lambda _runtime: setattr(_runtime, "persisted", _runtime.persisted + 1),
        )

        self.assertEqual(outcome.status, "launched")
        self.assertEqual(outcome.surface_id, "ws-existing")
        self.assertEqual(
            runtime.process_runner.calls[0],
            [
                "superset",
                "agents",
                "run",
                "--workspace",
                "ws-existing",
                "--agent",
                "agent-1",
                "--prompt",
                "prompt",
                "--json",
            ],
        )
        self.assertEqual(runtime.persisted, 1)

    def test_project_launch_falls_back_to_worktree_name_when_branch_unavailable(self) -> None:
        runtime = _Runtime(
            _Runner(
                subprocess.CompletedProcess(
                    args=["superset"],
                    returncode=0,
                    stdout='{"workspace":{"id":"ws-123"}}',
                    stderr="",
                )
            )
        )

        outcome = launch_single_superset_worktree(
            runtime,
            launch_config=_launch_config(project="proj-1", open_workspace=False),
            workflow=_workflow(),
            worktree=_worktree(),
            base_payload={},
            superset_initial_prompt_fn=lambda *_args, **_kwargs: ("prompt", None),
            superset_agent_and_prompt_fn=lambda *_args, **_kwargs: ("agent-1", "prompt"),
            git_branch_name_fn=lambda _runtime, _root: ("", "not a branch"),
            superset_workspace_name_fn=lambda _worktree: "workspace-name",
            parse_superset_json_output_fn=lambda _stdout: {"workspace": {"id": "ws-123"}},
            workspace_id_from_superset_payload_fn=lambda _payload: "ws-123",
            bridge_superset_desktop_workspace_fn=lambda *_args, **_kwargs: False,
            open_superset_workspace_fn=lambda *_args, **_kwargs: None,
            verify_superset_desktop_workspace_fn=lambda *_args, **_kwargs: None,
            restart_superset_desktop_fn=lambda *_args, **_kwargs: False,
            completed_process_error_text_fn=lambda _result: "process failed",
            persist_runtime_events_snapshot_fn=lambda _runtime: setattr(_runtime, "persisted", _runtime.persisted + 1),
        )

        self.assertEqual(outcome.status, "launched")
        create_call = runtime.process_runner.calls[0]
        self.assertEqual(create_call[create_call.index("--branch") + 1], "feature-a-1")
        self.assertEqual(runtime.events[0][0], "planning.agent_launch.superset_branch_fallback")
        self.assertEqual(runtime.events[0][1]["fallback"], "feature-a-1")

    def test_non_json_success_returns_launched_without_workspace_id_and_debug_event(self) -> None:
        runtime = _Runtime(
            _Runner(subprocess.CompletedProcess(args=["superset"], returncode=0, stdout="created", stderr=""))
        )

        outcome = launch_single_superset_worktree(
            runtime,
            launch_config=_launch_config(project="proj-1"),
            workflow=_workflow(),
            worktree=_worktree(),
            base_payload={},
            superset_initial_prompt_fn=lambda *_args, **_kwargs: ("prompt", None),
            superset_agent_and_prompt_fn=lambda *_args, **_kwargs: ("agent-1", "prompt"),
            git_branch_name_fn=lambda _runtime, _root: ("branch", None),
            superset_workspace_name_fn=lambda _worktree: "workspace-name",
            parse_superset_json_output_fn=lambda _stdout: None,
            workspace_id_from_superset_payload_fn=lambda _payload: None,
            bridge_superset_desktop_workspace_fn=lambda *_args, **_kwargs: False,
            open_superset_workspace_fn=lambda *_args, **_kwargs: None,
            verify_superset_desktop_workspace_fn=lambda *_args, **_kwargs: None,
            restart_superset_desktop_fn=lambda *_args, **_kwargs: False,
            completed_process_error_text_fn=lambda _result: "process failed",
            persist_runtime_events_snapshot_fn=lambda _runtime: setattr(_runtime, "persisted", _runtime.persisted + 1),
        )

        self.assertEqual(outcome.status, "launched")
        self.assertIsNone(outcome.surface_id)
        self.assertEqual(runtime.events[-1][0], "planning.agent_launch.superset_debug_output")
        self.assertEqual(runtime.persisted, 1)


if __name__ == "__main__":
    unittest.main()
