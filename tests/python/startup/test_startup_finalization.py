from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from envctl_engine.runtime.command_router import parse_route
from envctl_engine.startup.finalization import (
    failure_context_label,
    headless_plan_session_summary_lines,
    plan_agent_degraded_handoff_text,
    plan_session_summary_lines,
    render_final_failure_status,
)
from envctl_engine.startup.session import LocalStartupFailure, StartupSession


def _session(*, contexts: list[object], contexts_to_start: list[object] | None = None) -> StartupSession:
    route = parse_route(["start"], env={})
    return StartupSession(
        requested_route=route,
        effective_route=route,
        requested_command="start",
        runtime_mode="trees",
        run_id="run-finalization",
        selected_contexts=contexts,
        contexts_to_start=list(contexts_to_start or []),
    )


class StartupFinalizationTests(unittest.TestCase):
    def test_failure_context_label_prefers_named_context_from_error(self) -> None:
        alpha = SimpleNamespace(name="alpha", root=Path("/repo/trees/alpha/1"))
        beta = SimpleNamespace(name="beta", root=Path("/repo/beta"))
        session = _session(contexts=[alpha, beta])

        label = failure_context_label(session, "Startup failed: beta backend missing")

        self.assertEqual(label, "project: beta")

    def test_failure_context_label_uses_single_worktree_context_when_error_is_generic(self) -> None:
        context = SimpleNamespace(name="feature-a-1", root=Path("/repo/trees/feature-a/1"))
        session = _session(contexts=[context])

        label = failure_context_label(session, "Startup failed: no free port found")

        self.assertEqual(label, "worktree: feature-a-1")

    def test_render_final_failure_status_adds_context_once(self) -> None:
        context = SimpleNamespace(name="feature-a-1", root=Path("/repo/trees/feature-a/1"))
        session = _session(contexts=[context])
        runtime = SimpleNamespace(env={})

        rendered = render_final_failure_status(
            runtime,
            session,
            "Startup failed: missing command",
            interactive_tty=False,
        )

        self.assertEqual(rendered, "✗ Startup failed: missing command (worktree: feature-a-1)")

    def test_plan_session_summary_lines_render_attach_new_session_and_kill_guidance(self) -> None:
        session = _session(contexts=[])
        session.plan_agent_attach_target = SimpleNamespace(
            attach_command=("tmux", "attach", "-t", "envctl-plan"),
            new_session_command=("envctl", "plan", "--new-session"),
            session_name="envctl-plan",
        )

        lines = plan_session_summary_lines(session)

        self.assertEqual(
            lines,
            [
                "existing session: envctl did not create a new AI session because one already exists for this "
                "plan/workspace/CLI.",
                "attach: tmux attach -t envctl-plan",
                "new session: envctl plan --new-session",
                "kill: tmux kill-session -t envctl-plan",
            ],
        )

    def test_plan_agent_degraded_handoff_text_includes_failure_and_attach_guidance(self) -> None:
        session = _session(contexts=[])
        session.plan_agent_attach_target = SimpleNamespace(
            attach_command=("tmux", "attach", "-t", "envctl-plan"),
            new_session_command=(),
            session_name="envctl-plan",
        )
        session.local_startup_failures.append(
            LocalStartupFailure(
                project="feature-a-1",
                error="missing_service_start_command: backend",
                reason="missing_service_start_command",
            )
        )

        text = plan_agent_degraded_handoff_text(session)

        self.assertIn("Implementation session is running, but local app startup failed.", text)
        self.assertIn("  attach: tmux attach -t envctl-plan", text)
        self.assertIn("  project: feature-a-1", text)
        self.assertIn("  error: missing_service_start_command: backend", text)
        self.assertIn("  next: configure ENVCTL_BACKEND_START_CMD / ENVCTL_FRONTEND_START_CMD", text)

    def test_headless_plan_session_summary_lines_include_validation_failure_guidance(self) -> None:
        session = _session(contexts=[])
        session.plan_agent_handoff_validation_reason = "attach_target_stale_after_launch"
        session.plan_agent_stale_session_name = "envctl-stale"
        session.plan_agent_recovery_command = "envctl plan --omx --new-session"

        lines = headless_plan_session_summary_lines(session)

        self.assertEqual(
            lines,
            [
                "Plan agent launch did not leave an attachable AI session.",
                "reason: attach_target_stale_after_launch",
                "stale_session: envctl-stale",
                "recovery: envctl plan --omx --new-session",
            ],
        )


if __name__ == "__main__":
    unittest.main()
