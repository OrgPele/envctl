from __future__ import annotations

from pathlib import Path
import subprocess
from types import SimpleNamespace
import tempfile
import unittest

from envctl_engine.planning.plan_agent.models import (
    AiCliReadyResult,
    CreatedPlanWorktree,
    PlanAgentAttachTarget,
)
from envctl_engine.planning.plan_agent.tmux_attach_support import (
    find_existing_tmux_attach_target,
    resolve_tmux_attach_target,
)


class PlanAgentTmuxAttachSupportTests(unittest.TestCase):
    def test_resolve_tmux_attach_target_returns_existing_worktree_match_first(self) -> None:
        existing = PlanAgentAttachTarget(
            repo_root=Path("/repo"),
            session_name="envctl-existing",
            window_name="feature-a-1",
            attach_via="attach-session",
            attach_command=("tmux", "attach", "-t", "envctl-existing"),
        )

        result = resolve_tmux_attach_target(
            runtime=SimpleNamespace(),
            repo_root=Path("/repo"),
            session_name="envctl-new",
            window_name="feature-a-1",
            attach_via="attach-session",
            created_worktrees=(),
            cli="codex",
            find_existing_attach_target_fn=lambda *_args, **_kwargs: existing,
            tmux_session_exists_fn=lambda *_args, **_kwargs: False,
            tmux_window_exists_fn=lambda *_args, **_kwargs: False,
            guidance_attach_command_fn=lambda session_name: ("tmux", "attach", "-t", session_name),
        )

        self.assertIs(result, existing)

    def test_resolve_tmux_attach_target_falls_back_to_requested_session(self) -> None:
        result = resolve_tmux_attach_target(
            runtime=SimpleNamespace(),
            repo_root=Path("/repo"),
            session_name="envctl-new",
            window_name="feature-a-1",
            attach_via="switch-client",
            created_worktrees=(),
            cli="codex",
            find_existing_attach_target_fn=lambda *_args, **_kwargs: None,
            tmux_session_exists_fn=lambda _runtime, session_name: session_name == "envctl-new",
            tmux_window_exists_fn=lambda _runtime, *, session_name, window_name: (
                session_name,
                window_name,
            )
            == ("envctl-new", "feature-a-1"),
            guidance_attach_command_fn=lambda session_name: ("tmux", "attach", "-t", session_name),
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.session_name, "envctl-new")
        self.assertEqual(result.window_name, "feature-a-1")
        self.assertEqual(result.attach_via, "switch-client")
        self.assertEqual(result.attach_command, ("tmux", "attach", "-t", "envctl-new"))

    def test_find_existing_tmux_attach_target_reports_unhealthy_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="feature-a.md")
            emitted: list[tuple[str, dict[str, object]]] = []
            runtime = SimpleNamespace(
                config=SimpleNamespace(base_dir=repo),
                _emit=lambda event, **payload: emitted.append((event, payload)),
            )

            result = find_existing_tmux_attach_target(
                runtime=runtime,
                repo_root=repo,
                created_worktrees=(worktree,),
                cli="codex",
                session_name_for_worktree_fn=lambda *_args, **_kwargs: "envctl-session",
                window_name_for_worktree_fn=lambda _worktree: "feature-a-1",
                tmux_session_exists_fn=lambda _runtime, session_name: session_name == "envctl-session",
                run_tmux_probe_fn=lambda *_args, **_kwargs: subprocess.CompletedProcess(
                    args=["tmux"],
                    returncode=0,
                    stdout=f"feature-a-1|||ENVCTL_TMUX_PATH|||{worktree_root}\n",
                    stderr="",
                ),
                existing_session_health_fn=lambda *_args, **_kwargs: AiCliReadyResult(
                    ready=False,
                    reason="codex_ready_timeout",
                    screen_excerpt="not ready",
                ),
                format_ai_cli_ready_failure_fn=lambda result: f"{result.reason}: {result.screen_excerpt}",
                guidance_attach_command_fn=lambda session_name: ("tmux", "attach", "-t", session_name),
            )

        self.assertIsNone(result)
        self.assertEqual(runtime._last_unhealthy_existing_tmux_session_reason, "existing_codex_session_unhealthy")
        self.assertEqual(len(runtime._last_unhealthy_existing_tmux_session_outcomes), 1)
        self.assertEqual(
            emitted,
            [
                (
                    "planning.agent_launch.existing_session_unhealthy",
                    {
                        "session_name": "envctl-session",
                        "window_name": "feature-a-1",
                        "cli": "codex",
                        "reason": "existing_codex_session_unhealthy: not ready",
                    },
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
