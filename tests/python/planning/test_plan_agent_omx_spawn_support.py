from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree, PlanAgentLaunchConfig
from envctl_engine.planning.plan_agent.omx_spawn_support import (
    deterministic_omx_root_for_worktree,
    omx_spawn_failure_text,
    spawn_omx_session_for_worktree,
)


def _launch_config(*, cli_command: str = "codex --dangerously-bypass-approvals-and-sandbox") -> PlanAgentLaunchConfig:
    return PlanAgentLaunchConfig(
        enabled=True,
        transport="omx",
        cli="codex",
        cli_command=cli_command,
        preset="implementation",
        codex_cycles=0,
        codex_cycles_warning=None,
        shell="/bin/zsh",
        require_cmux_context=False,
        cmux_workspace="",
        direct_prompt_enabled=False,
        ulw_loop_prefix=True,
        ulw_suffix=True,
        omx_workflow="team",
    )


class PlanAgentOmxSpawnSupportTests(unittest.TestCase):
    def test_deterministic_root_is_under_worktree_state(self) -> None:
        worktree = CreatedPlanWorktree(name="Feature A/1", root=Path("/repo/trees/feature-a/1"), plan_file="a.md")

        self.assertEqual(
            deterministic_omx_root_for_worktree(worktree),
            Path("/repo/trees/feature-a/1/.envctl-state/omx/feature-a-1"),
        )

    def test_spawn_failure_text_prefers_stderr_then_stdout_then_status(self) -> None:
        self.assertEqual(omx_spawn_failure_text(returncode=7, stdout="stdout-line\nx", stderr="stderr-line\ny"), "stderr-line")
        self.assertEqual(omx_spawn_failure_text(returncode=7, stdout="stdout-line\nx", stderr=""), "stdout-line")
        self.assertEqual(omx_spawn_failure_text(returncode=7, stdout="", stderr=""), "omx exited with status 7")

    def test_spawn_sets_omx_root_and_bounded_failure_event(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        retained: list[object] = []
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree_root = Path(tmpdir) / "worktree"
            worktree_root.mkdir()
            omx_root = Path(tmpdir) / "omx-root"
            worktree = CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md")
            runtime = SimpleNamespace(
                env={"ENVCTL_SECRET_TOKEN": "do-not-log"},
                _emit=lambda event, **payload: events.append((event, payload)),
            )

            class _ExitedPopen:
                pid = 5151
                returncode = 9

                def __init__(self, cmd, **kwargs):  # noqa: ANN001
                    self.args = cmd
                    self.kwargs = kwargs
                    self.stdin = None
                    self.stdout = None
                    self.stderr = None

                def poll(self):
                    return self.returncode

                def communicate(self, timeout=None):  # noqa: ANN001
                    _ = timeout
                    return "stdout-line\n" + ("x" * 2000), "stderr-line\n" + ("y" * 2000)

            error = spawn_omx_session_for_worktree(
                runtime,
                launch_config=_launch_config(),
                worktree=worktree,
                omx_runtime_root_for_worktree_fn=lambda _runtime, _worktree: omx_root,
                cleanup_stale_locks_fn=lambda *_args, **_kwargs: None,
                omx_launch_env_fn=lambda _runtime: {"HOME": "/Users/example"},
                utc_timestamp_from_epoch_fn=lambda: "2026-05-24T00:00:00Z",
                read_omx_session_id_fn=lambda *_args, **_kwargs: "",
                retain_omx_spawn_process_fn=lambda _runtime, record: retained.append(record),
                popen_factory=_ExitedPopen,
            )

        self.assertEqual(error, "stderr-line")
        self.assertEqual(events[0][0], "planning.agent_launch.omx_state_root_selected")
        self.assertEqual(events[1][0], "planning.agent_launch.omx_spawn.started")
        self.assertEqual(events[2][0], "planning.agent_launch.omx_spawn.failed")
        failed_payload = events[2][1]
        self.assertEqual(failed_payload["pid"], 5151)
        self.assertEqual(failed_payload["returncode"], 9)
        self.assertEqual(failed_payload["command"], ["omx", "--tmux", "--madmax"])
        self.assertEqual(failed_payload["popen_command"], ["script", "-qfc", "omx --tmux --madmax", "/dev/null"])
        self.assertEqual(failed_payload["stdout_excerpt"], "stdout-line\n" + ("x" * 988))
        self.assertEqual(failed_payload["stderr_excerpt"], "stderr-line\n" + ("y" * 988))
        self.assertNotIn("do-not-log", json.dumps(failed_payload))
        self.assertEqual(retained, [])


if __name__ == "__main__":
    unittest.main()
