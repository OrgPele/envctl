from __future__ import annotations

from types import SimpleNamespace
import unittest

from envctl_engine.runtime.command_router import parse_route
from envctl_engine.startup.finalization_plan_output import (
    headless_plan_session_summary_lines,
    maybe_attach_plan_agent_terminal,
    plan_agent_degraded_handoff_text,
    plan_dry_run_preview_lines,
    restart_port_rebound_summary_lines,
)
from envctl_engine.startup.session import LocalStartupFailure, StartupSession


def _session(args: list[str] | None = None) -> StartupSession:
    route = parse_route(args or ["start"], env={})
    return StartupSession(
        requested_route=route,
        effective_route=route,
        requested_command=route.command,
        runtime_mode=route.mode,
        run_id="run-plan-output",
        selected_contexts=[],
        contexts_to_start=[],
    )


class FinalizationPlanOutputTests(unittest.TestCase):
    def test_plan_dry_run_preview_lines_marks_created_and_reused_contexts(self) -> None:
        session = _session(["plan", "--dry-run"])
        session.selected_contexts = [
            SimpleNamespace(name="feature-a-1"),
            SimpleNamespace(name="feature-b-1"),
        ]

        self.assertEqual(
            plan_dry_run_preview_lines(session, created_names={"feature-b-1"}),
            [
                "Dry run: no worktrees, git state, or services were modified.",
                "feature-a-1: reuse",
                "feature-b-1: create",
            ],
        )

    def test_restart_rebound_summary_lines_deduplicate_valid_rebounds(self) -> None:
        session = _session(["restart"])
        session.effective_route = parse_route(["restart", "--batch"], env={})
        session.effective_route.flags = {**session.effective_route.flags, "interactive_command": True}
        events = [
            {"event": "ignored"},
            {
                "event": "port.rebound",
                "project": "Main",
                "service": "backend",
                "restart_preferred_port": 8000,
                "port": 8001,
            },
            {
                "event": "port.rebound",
                "project": "Main",
                "service": "backend",
                "restart_preferred_port": 8000,
                "port": 8001,
            },
            {
                "event": "port.rebound",
                "project": "Main",
                "service": "frontend",
                "restart_preferred_port": 3000,
                "port": 3000,
            },
        ]

        self.assertEqual(
            restart_port_rebound_summary_lines(session, events),
            ["Port changed: Main Backend 8000 -> 8001 (previous port still in use)"],
        )

    def test_headless_plan_session_summary_lines_include_attach_or_recovery_guidance(self) -> None:
        attach_target = SimpleNamespace(
            attach_command=("tmux", "attach", "-t", "envctl-plan"),
            new_session_command=(),
            session_name="envctl-plan",
        )
        attached_session = _session(["plan", "--headless"])
        attached_session.plan_agent_attach_target = attach_target

        self.assertEqual(
            headless_plan_session_summary_lines(attached_session),
            ["attach: tmux attach -t envctl-plan", "kill: tmux kill-session -t envctl-plan"],
        )

        stale_session = _session(["plan", "--headless"])
        stale_session.plan_agent_handoff_validation_reason = "attach_target_stale_after_launch"
        stale_session.plan_agent_stale_session_name = "envctl-stale"
        stale_session.plan_agent_recovery_command = "envctl plan --omx --new-session"

        self.assertEqual(
            headless_plan_session_summary_lines(stale_session),
            [
                "Plan agent launch did not leave an attachable AI session.",
                "reason: attach_target_stale_after_launch",
                "stale_session: envctl-stale",
                "recovery: envctl plan --omx --new-session",
            ],
        )

    def test_maybe_attach_plan_agent_terminal_clears_target_and_prints_fallback_on_failure(self) -> None:
        session = _session(["plan"])
        attach_target = SimpleNamespace(attach_command=("tmux", "attach", "-t", "envctl-plan"))
        session.plan_agent_attach_target = attach_target
        printed: list[object] = []

        result = maybe_attach_plan_agent_terminal(
            runtime=SimpleNamespace(),
            session=session,
            validate_plan_agent_handoff=lambda session, *, phase: None,
            attach_plan_agent_terminal=lambda runtime, target: 2,
            print_headless_plan_session_summary=lambda session, *, attach_target: printed.append(attach_target),
        )

        self.assertEqual(result, 0)
        self.assertIsNone(session.plan_agent_attach_target)
        self.assertEqual(printed, [attach_target])

    def test_plan_agent_degraded_handoff_text_includes_multi_failure_guidance(self) -> None:
        session = _session(["plan"])
        session.local_startup_failures.extend(
            [
                LocalStartupFailure(project="feature-a-1", error="missing backend", reason="missing_service_start_command"),
                LocalStartupFailure(project="feature-b-1", error="missing frontend", reason="missing_service_start_command"),
            ]
        )

        text = plan_agent_degraded_handoff_text(session)

        self.assertIn("Implementation session is running, but local app startup failed.", text)
        self.assertIn("project: feature-a-1", text)
        self.assertIn("project: feature-b-1", text)
        self.assertIn("disable tree startup", text)


if __name__ == "__main__":
    unittest.main()
