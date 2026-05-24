from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.planning.plan_agent.models import (
    CreatedPlanWorktree,
    PlanAgentAttachTarget,
)
from envctl_engine.planning.plan_agent import omx_validation_support


class _Runtime:
    def __init__(self) -> None:
        self.events: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def _emit(self, *args: object, **kwargs: object) -> None:
        self.events.append((args, kwargs))


class PlanAgentOmxValidationSupportTests(unittest.TestCase):
    def test_validate_attach_target_rejects_missing_session_name(self) -> None:
        runtime = _Runtime()

        validation = omx_validation_support.validate_omx_attach_target(
            runtime,
            None,
            worktree=None,
            transport="omx",
            phase="handoff",
            tmux_session_exists_fn=lambda _runtime, _session_name: True,
            tmux_display_message_succeeds_fn=lambda _runtime, _session_name: (True, "%1"),
            attach_target_state_check_fn=lambda *_args, **_kwargs: (None, {}),
            omx_late_spawn_exit_reason_fn=lambda *_args, **_kwargs: None,
        )

        self.assertFalse(validation.ok)
        self.assertEqual(validation.reason, "omx_session_unavailable")
        self.assertEqual(runtime.events[0][0], ("planning.agent_launch.attach_validation.failed",))

    def test_validate_attach_target_rejects_removed_worktree_before_tmux_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree_root = Path(tmpdir) / "missing"
            worktree = CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md")
            runtime = _Runtime()
            calls: list[str] = []

            validation = omx_validation_support.validate_omx_attach_target(
                runtime,
                PlanAgentAttachTarget(
                    repo_root=Path(tmpdir),
                    session_name="omx-feature",
                    window_name="%1",
                    attach_via="attach-session",
                    attach_command=("tmux", "attach", "-t", "omx-feature"),
                ),
                worktree=worktree,
                transport="omx",
                phase="post_workflow_queue",
                tmux_session_exists_fn=lambda *_args: calls.append("tmux") or True,
                tmux_display_message_succeeds_fn=lambda *_args: (True, "%1"),
                attach_target_state_check_fn=lambda *_args, **_kwargs: (None, {}),
                omx_late_spawn_exit_reason_fn=lambda *_args, **_kwargs: None,
            )

        self.assertFalse(validation.ok)
        self.assertEqual(validation.reason, "worktree_removed_after_launch")
        self.assertEqual(calls, [])
        self.assertEqual(runtime.events[0][0], ("planning.agent_launch.worktree_missing_after_launch",))

    def test_late_spawn_exit_reason_prunes_exited_records_and_emits_payload(self) -> None:
        runtime = _Runtime()
        runtime._omx_spawn_processes = [SimpleNamespace(code=0), SimpleNamespace(code=None)]
        worktree = CreatedPlanWorktree(name="feature-a-1", root=Path("."), plan_file="a.md")

        reason = omx_validation_support.omx_late_spawn_exit_reason(
            runtime,
            session_name="omx-feature",
            worktree=worktree,
            retained_returncode_fn=lambda record: record.code,
            retained_event_payload_fn=lambda record, **kwargs: {"code": record.code, **kwargs},
        )

        self.assertEqual(reason, "omx_session_exited")
        self.assertEqual([record.code for record in runtime._omx_spawn_processes], [None])
        self.assertEqual(runtime.events[0][0], ("planning.agent_launch.omx_spawn.exited_early",))
        self.assertEqual(runtime.events[0][1]["session_name"], "omx-feature")


if __name__ == "__main__":
    unittest.main()
