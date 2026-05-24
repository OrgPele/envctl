from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import unittest

from envctl_engine.planning.plan_agent.models import (
    PlanAgentAttachValidation,
    PlanAgentLaunchOutcome,
    PlanAgentLaunchResult,
)
from envctl_engine.runtime.command_router import parse_route
from envctl_engine.startup.plan_agent_handoff import (
    emit_plan_agent_launch_state,
    launch_plan_agent_terminals_with_spinner,
    local_startup_failure_reason,
    plan_agent_launch_spinner_label,
    plan_agent_launch_spinner_message,
    plan_agent_launch_spinner_success_message,
    plan_agent_launch_failure_message,
    plan_agent_handoff_validation_required,
    prepare_and_launch_plan_agent_worktrees,
    prepare_plan_agent_dependencies_for_launch,
    record_plan_agent_handoff_local_startup_failure,
    record_stale_plan_agent_handoff,
    should_fail_for_plan_agent_launch_result,
    should_degrade_to_plan_agent_handoff,
    should_degrade_to_validated_plan_agent_handoff,
    validate_plan_agent_handoff,
)
from envctl_engine.startup.session import StartupSession


def _session(*, args: list[str] | None = None) -> StartupSession:
    route = parse_route(args or ["plan", "--tmux"], env={})
    return StartupSession(
        requested_route=route,
        effective_route=route,
        requested_command="plan",
        runtime_mode="trees",
        run_id="run-handoff",
    )


class PlanAgentHandoffTests(unittest.TestCase):
    def test_local_startup_failure_reason_classifies_missing_start_command(self) -> None:
        self.assertEqual(
            local_startup_failure_reason("missing_service_start_command: backend"),
            "missing_service_start_command",
        )
        self.assertIsNone(local_startup_failure_reason("database unavailable"))

    def test_record_local_startup_failure_marks_session_and_emits_handoff_events(self) -> None:
        session = _session(args=["plan", "--omx", "--ultragoal"])
        session.plan_agent_attach_target = SimpleNamespace(session_name="envctl-plan")
        session.plan_agent_launch_result = SimpleNamespace(status="launched")
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(_emit=lambda event, **payload: events.append((event, payload)))

        record_plan_agent_handoff_local_startup_failure(
            runtime,
            session,
            project_name="feature-a-1",
            error="missing_service_start_command: backend",
        )

        self.assertTrue(session.plan_agent_handoff_degraded)
        self.assertEqual(len(session.local_startup_failures), 1)
        self.assertEqual(session.local_startup_failures[0].reason, "missing_service_start_command")
        self.assertEqual(
            session.warnings,
            [
                "Implementation session is running, but local app startup failed for "
                "feature-a-1: missing_service_start_command: backend"
            ],
        )
        self.assertEqual(
            events,
            [
                (
                    "startup.project.warning",
                    {
                        "project": "feature-a-1",
                        "warning": session.warnings[0],
                        "reason": "plan_agent_handoff_local_startup_failed",
                        "implementation_session_running": True,
                        "local_startup_failed": True,
                        "session_name": "envctl-plan",
                    },
                ),
                (
                    "startup.plan_agent_handoff.degraded",
                    {
                        "project": "feature-a-1",
                        "error": "missing_service_start_command: backend",
                        "reason": "missing_service_start_command",
                        "implementation_session_running": True,
                        "session_name": "envctl-plan",
                        "route_transport": "omx",
                        "omx_workflow": "ultragoal",
                        "launch_status": "launched",
                    },
                ),
            ],
        )

    def test_record_local_startup_failure_defaults_unknown_reason_and_cmux_transport(self) -> None:
        session = _session(args=["plan"])
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(_emit=lambda event, **payload: events.append((event, payload)))

        record_plan_agent_handoff_local_startup_failure(
            runtime,
            session,
            project_name="feature-a-1",
            error="frontend unavailable",
        )

        self.assertEqual(session.local_startup_failures[0].reason, "local_startup_failed")
        self.assertEqual(events[-1][1]["route_transport"], "cmux")
        self.assertIsNone(events[-1][1]["omx_workflow"])

    def test_emit_plan_agent_launch_state_summarizes_launch_outcomes(self) -> None:
        session = _session(args=["plan", "--tmux"])
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(_emit=lambda event, **payload: events.append((event, payload)))
        launch_result = SimpleNamespace(
            status="partial",
            reason="one_failed",
            attach_target=SimpleNamespace(session_name="envctl-plan"),
            outcomes=(
                SimpleNamespace(status="launched", worktree_name="feature-a-1"),
                SimpleNamespace(status="failed", worktree_name="feature-a-2"),
                SimpleNamespace(status="skipped", worktree_name="feature-a-3"),
                SimpleNamespace(status="failed", worktree_name=""),
            ),
        )
        session.plan_agent_launch_result = launch_result

        emit_plan_agent_launch_state(runtime, session, launch_result)

        self.assertEqual(
            events,
            [
                (
                    "startup.plan_agent_launch_state",
                    {
                        "command": "plan",
                        "mode": "trees",
                        "status": "partial",
                        "reason": "one_failed",
                        "launched_worktrees": ["feature-a-1"],
                        "failed_worktrees": ["feature-a-2"],
                        "session_name": "envctl-plan",
                        "implementation_session_running": True,
                    },
                )
            ],
        )

    def test_should_fail_for_plan_agent_launch_result_requires_plan_request_and_no_attach(self) -> None:
        failed_result = SimpleNamespace(status="failed", attach_target=None, outcomes=())

        session = _session(args=["plan", "--tmux"])
        session.plan_agent_launch_requested = True
        self.assertTrue(should_fail_for_plan_agent_launch_result(session, failed_result))

        session.plan_agent_attach_target = SimpleNamespace(session_name="envctl-plan")
        self.assertFalse(should_fail_for_plan_agent_launch_result(session, failed_result))

        no_launch_session = _session(args=["plan", "--tmux"])
        self.assertFalse(should_fail_for_plan_agent_launch_result(no_launch_session, failed_result))

        start_session = _session(args=["--trees"])
        start_session.plan_agent_launch_requested = True
        self.assertFalse(should_fail_for_plan_agent_launch_result(start_session, failed_result))

    def test_plan_agent_handoff_validation_required_only_for_omx_plan_routes(self) -> None:
        self.assertTrue(plan_agent_handoff_validation_required(_session(args=["plan", "--omx"])))
        self.assertFalse(plan_agent_handoff_validation_required(_session(args=["plan", "--tmux"])))
        self.assertFalse(plan_agent_handoff_validation_required(_session(args=["--trees", "--omx"])))

    def test_should_degrade_to_plan_agent_handoff_requires_plan_session_and_known_error(self) -> None:
        session = _session(args=["plan", "--tmux", "--headless"])
        session.plan_agent_launch_result = SimpleNamespace(status="launched", outcomes=())

        self.assertTrue(
            should_degrade_to_plan_agent_handoff(
                session,
                error="missing_service_start_command: backend",
            )
        )
        self.assertFalse(should_degrade_to_plan_agent_handoff(session, error="backend crashed"))

        no_session = _session(args=["plan", "--tmux", "--headless"])
        self.assertFalse(
            should_degrade_to_plan_agent_handoff(
                no_session,
                error="missing_service_start_command: backend",
            )
        )

        interactive_session = _session(args=["plan", "--tmux"])
        interactive_session.plan_agent_launch_result = SimpleNamespace(status="launched", outcomes=())
        self.assertFalse(
            should_degrade_to_plan_agent_handoff(
                interactive_session,
                error="missing_service_start_command: backend",
            )
        )
        interactive_session.plan_agent_attach_target = SimpleNamespace(session_name="envctl-plan")
        self.assertTrue(
            should_degrade_to_plan_agent_handoff(
                interactive_session,
                error="missing_service_start_command: backend",
            )
        )

    def test_validate_plan_agent_handoff_skips_non_omx_routes_and_missing_targets(self) -> None:
        runtime = SimpleNamespace(config=SimpleNamespace(), env={}, _emit=lambda event, **payload: None)
        calls: list[object] = []
        session = _session(args=["plan", "--tmux"])
        session.plan_agent_attach_target = SimpleNamespace(session_name="tmux-session")

        validate_plan_agent_handoff(
            runtime,
            session,
            phase="post_launch",
            validate_attach_target_fn=lambda *args, **kwargs: calls.append((args, kwargs))
            or PlanAgentAttachValidation(True, "ok"),
        )

        self.assertEqual(calls, [])

        omx_session = _session(args=["plan", "--omx"])
        validate_plan_agent_handoff(
            runtime,
            omx_session,
            phase="post_launch",
            validate_attach_target_fn=lambda *args, **kwargs: calls.append((args, kwargs))
            or PlanAgentAttachValidation(True, "ok"),
        )

        self.assertEqual(calls, [])

    def test_should_degrade_to_validated_plan_agent_handoff_degrades_stale_omx_target(self) -> None:
        session = _session(args=["plan", "--omx", "--headless"])
        session.pending_plan_agent_worktrees = (SimpleNamespace(name="feature-a-1"),)
        session.plan_agent_attach_target = SimpleNamespace(
            session_name="stale-session",
            attach_command=("tmux", "attach", "-t", "stale-session"),
        )
        session.plan_agent_launch_result = PlanAgentLaunchResult(
            status="launched",
            reason="launched",
            outcomes=(
                PlanAgentLaunchOutcome(
                    worktree_name="feature-a-1",
                    worktree_root=Path("/tmp/feature-a-1"),
                    surface_id="surface-1",
                    status="launched",
                ),
            ),
            attach_target=session.plan_agent_attach_target,
        )
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(
            config=SimpleNamespace(),
            env={},
            _emit=lambda event, **payload: events.append((event, payload)),
        )

        result = should_degrade_to_validated_plan_agent_handoff(
            runtime,
            session,
            error="missing_service_start_command: backend",
            validate_attach_target_fn=lambda *args, **kwargs: PlanAgentAttachValidation(False, "omx_attach_target_stale"),
            record_stale_handoff_fn=lambda rt, sess, *, validation_reason: record_stale_plan_agent_handoff(
                rt,
                sess,
                validation_reason=validation_reason,
                resolve_launch_config_fn=lambda config, env, *, route: SimpleNamespace(transport="omx", cli="codex"),
                recovery_command_fn=lambda rt, *, route, launch_config, created_worktrees: ("envctl", "--plan"),
            ),
        )

        self.assertFalse(result)
        self.assertTrue(session.plan_agent_handoff_degraded)
        self.assertIsNone(session.plan_agent_attach_target)
        self.assertEqual(session.plan_agent_handoff_validation_reason, "attach_target_stale_after_launch")
        self.assertEqual(events[-1][0], "startup.plan_agent_handoff.validation_failed")

    def test_plan_agent_launch_failure_message_prefers_outcome_details(self) -> None:
        launch_result = SimpleNamespace(
            status="failed",
            reason="transport_failed",
            outcomes=(
                SimpleNamespace(worktree_name="feature-a-1", reason="missing cmux"),
                SimpleNamespace(worktree_name="feature-a-2", reason=""),
                SimpleNamespace(worktree_name="", reason="timeout"),
                SimpleNamespace(worktree_name="feature-a-3", reason="bad env"),
                SimpleNamespace(worktree_name="feature-a-4", reason="hidden fourth"),
            ),
        )

        self.assertEqual(
            plan_agent_launch_failure_message(launch_result),
            "Plan agent session failed to start: feature-a-1: missing cmux; timeout; feature-a-3: bad env",
        )

    def test_plan_agent_launch_failure_message_falls_back_to_result_reason(self) -> None:
        launch_result = SimpleNamespace(status="failed", reason="missing_executables", outcomes=())

        self.assertEqual(
            plan_agent_launch_failure_message(launch_result),
            "Plan agent session failed to start: missing_executables",
        )

    def test_plan_agent_launch_spinner_text_describes_transport_and_count(self) -> None:
        self.assertEqual(plan_agent_launch_spinner_label(SimpleNamespace(transport="omx", cli="codex")), "OMX-managed Codex")
        self.assertEqual(plan_agent_launch_spinner_label(SimpleNamespace(transport="tmux", cli="opencode")), "OpenCode")
        self.assertEqual(plan_agent_launch_spinner_label(SimpleNamespace(transport="cmux", cli="codex")), "Codex")
        self.assertEqual(plan_agent_launch_spinner_label(SimpleNamespace(transport="cmux", cli="unknown")), "AI")

        self.assertEqual(
            plan_agent_launch_spinner_message(SimpleNamespace(transport="tmux", cli="codex"), count=1),
            "Launching Codex AI session...",
        )
        self.assertEqual(
            plan_agent_launch_spinner_message(SimpleNamespace(transport="tmux", cli="codex"), count=2),
            "Launching Codex AI sessions...",
        )
        self.assertEqual(
            plan_agent_launch_spinner_success_message(SimpleNamespace(transport="omx", cli="codex"), count=1),
            "OMX-managed Codex AI session ready",
        )

    def test_launch_plan_agent_terminals_without_spinner_delegates_directly(self) -> None:
        route = parse_route(["plan", "--tmux"], env={})
        runtime = SimpleNamespace(env={}, _emit=lambda event, **payload: None)
        created_worktrees = (SimpleNamespace(name="feature-a-1"),)
        launch_config = SimpleNamespace(enabled=True, transport="tmux", cli="codex")
        calls: list[tuple[object, object, tuple[object, ...]]] = []
        launch_result = SimpleNamespace(status="launched", reason="ok")

        def _launch(rt: object, *, route: object, created_worktrees: tuple[object, ...]) -> object:
            calls.append((rt, route, created_worktrees))
            return launch_result

        result = launch_plan_agent_terminals_with_spinner(
            runtime,
            route=route,
            created_worktrees=created_worktrees,
            launch_config=launch_config,
            suppress_progress_output=True,
            launch_fn=_launch,
        )

        self.assertIs(result, launch_result)
        self.assertEqual(calls, [(runtime, route, created_worktrees)])

    def test_prepare_plan_agent_dependencies_for_launch_prepares_matching_worktrees(self) -> None:
        session = _session(args=["plan", "--tmux"])
        session.run_id = "run-123"
        context = SimpleNamespace(name="feature-a-1")
        session.selected_contexts = [context]
        created_worktrees = (SimpleNamespace(name="feature-a-1"), SimpleNamespace(name="missing"))
        events: list[tuple[str, dict[str, object]]] = []
        progress: list[tuple[str, str | None]] = []
        runtime = SimpleNamespace(
            env={},
            _emit=lambda event, **payload: events.append((event, payload)),
        )
        prepared = SimpleNamespace(
            backend=SimpleNamespace(manager="uv"),
            frontend=SimpleNamespace(manager="npm"),
            skipped=("db",),
        )
        prepare_calls: list[tuple[object, object, str]] = []

        prepare_plan_agent_dependencies_for_launch(
            runtime,
            session,
            created_worktrees=created_worktrees,
            launch_config=SimpleNamespace(enabled=True, cli="codex", transport="tmux"),
            report_progress=lambda route, message, project=None: progress.append((message, project)),
            prepare_fn=lambda rt, *, context, route, run_id: (
                prepare_calls.append((rt, context, run_id)) or prepared
            ),
            monotonic_fn=iter([1.0, 1.25, 2.0, 2.5]).__next__,
        )

        self.assertEqual(session.plan_agent_dependency_bootstrap_results, (prepared,))
        self.assertEqual(prepare_calls, [(runtime, context, "run-123")])
        self.assertEqual(
            progress,
            [
                ("Preparing dependencies for feature-a-1...", "feature-a-1"),
                ("Dependencies ready for feature-a-1: backend=uv frontend=npm", "feature-a-1"),
            ],
        )
        self.assertEqual(events[0][0], "planning.dependency_bootstrap.start")
        self.assertEqual(events[0][1]["projects"], ["feature-a-1", "missing"])
        self.assertEqual(events[1][0], "planning.dependency_bootstrap.project")
        self.assertEqual(events[1][1]["project"], "feature-a-1")
        self.assertEqual(events[1][1]["skipped"], ["db"])
        self.assertEqual(events[2][0], "planning.dependency_bootstrap.finish")
        self.assertEqual(events[2][1]["status"], "ok")
        self.assertEqual(events[2][1]["project_count"], 1)

    def test_prepare_and_launch_plan_agent_worktrees_runs_full_launch_lifecycle(self) -> None:
        session = _session(args=["plan", "--omx"])
        session.plan_agent_launch_requested = True
        session.pending_plan_agent_worktrees = (SimpleNamespace(name="feature-a-1"),)
        runtime = SimpleNamespace(config=SimpleNamespace(), env={}, _emit=lambda event, **payload: None)
        launch_result = SimpleNamespace(status="launched", reason="ok", attach_target=SimpleNamespace(session_name="s"))
        calls: list[tuple[str, object]] = []

        result = prepare_and_launch_plan_agent_worktrees(
            runtime,
            session,
            resolve_launch_config_fn=lambda config, env, *, route: SimpleNamespace(enabled=True),
            ensure_run_id=lambda sess: calls.append(("ensure_run_id", sess)),
            report_progress=lambda *args, **kwargs: calls.append(("progress", kwargs.get("project"))),
            prepare_dependencies_for_launch=lambda *args, **kwargs: calls.append(("prepare", kwargs["created_worktrees"])),
            launch_with_spinner=lambda *args, **kwargs: calls.append(("launch", kwargs["created_worktrees"]))
            or launch_result,
            suppress_progress_output=lambda route: False,
            validate_attach_target_fn=lambda *args, **kwargs: PlanAgentAttachValidation(True, "ok"),
            emit_launch_state=lambda rt, sess, launch: calls.append(("emit", launch)),
        )

        self.assertIsNone(result)
        self.assertIs(session.plan_agent_launch_result, launch_result)
        self.assertIs(session.plan_agent_attach_target, launch_result.attach_target)
        self.assertEqual(
            calls,
            [
                ("ensure_run_id", session),
                ("prepare", session.pending_plan_agent_worktrees),
                ("launch", session.pending_plan_agent_worktrees),
                ("emit", launch_result),
            ],
        )

    def test_prepare_and_launch_plan_agent_worktrees_raises_failed_launch_message(self) -> None:
        session = _session(args=["plan", "--tmux"])
        session.plan_agent_launch_requested = True
        failed_launch = SimpleNamespace(status="failed", reason="missing cmux", attach_target=None, outcomes=())
        runtime = SimpleNamespace(config=SimpleNamespace(), env={}, _emit=lambda event, **payload: None)

        with self.assertRaisesRegex(RuntimeError, "Plan agent session failed to start: missing cmux"):
            prepare_and_launch_plan_agent_worktrees(
                runtime,
                session,
                resolve_launch_config_fn=lambda config, env, *, route: SimpleNamespace(enabled=False),
                ensure_run_id=lambda session: None,
                report_progress=lambda *args, **kwargs: None,
                launch_with_spinner=lambda *args, **kwargs: failed_launch,
                suppress_progress_output=lambda route: False,
                validate_attach_target_fn=lambda *args, **kwargs: PlanAgentAttachValidation(True, "ok"),
                emit_launch_state=lambda *args, **kwargs: None,
            )

    def test_launch_plan_agent_terminals_with_spinner_emits_success_lifecycle(self) -> None:
        route = parse_route(["plan", "--tmux"], env={})
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(env={"ENVCTL_SPINNER": "1"}, _emit=lambda event, **payload: events.append((event, payload)))
        created_worktrees = (SimpleNamespace(name="feature-a-1"), SimpleNamespace(name="feature-a-2"))
        launch_config = SimpleNamespace(enabled=True, transport="tmux", cli="codex")
        spinner_actions: list[tuple[str, str]] = []
        launch_result = SimpleNamespace(status="launched", reason="ok")

        class _FakeSpinner:
            def __enter__(self) -> "_FakeSpinner":
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def succeed(self, message: str) -> None:
                spinner_actions.append(("success", message))

            def fail(self, message: str) -> None:
                spinner_actions.append(("fail", message))

        def _spinner(message: str, *, enabled: bool) -> _FakeSpinner:
            spinner_actions.append(("start", f"{message}:{enabled}"))
            return _FakeSpinner()

        @contextmanager
        def _use_policy(policy: object):
            yield

        def _launch(rt: object, *, route: object, created_worktrees: tuple[object, ...]) -> object:
            return launch_result

        result = launch_plan_agent_terminals_with_spinner(
            runtime,
            route=route,
            created_worktrees=created_worktrees,
            launch_config=launch_config,
            suppress_progress_output=False,
            launch_fn=_launch,
            resolve_spinner_policy_fn=lambda env: SimpleNamespace(enabled=True),
            emit_spinner_policy_fn=lambda emit, policy, context: emit("spinner.policy", **context),
            spinner_fn=_spinner,
            use_spinner_policy_fn=_use_policy,
        )

        self.assertIs(result, launch_result)
        self.assertIn(("start", "Launching Codex AI sessions...:True"), spinner_actions)
        self.assertIn(("success", "Codex AI sessions ready"), spinner_actions)
        lifecycle_events = [event for event in events if event[0] == "ui.spinner.lifecycle"]
        self.assertEqual([event[1]["state"] for event in lifecycle_events], ["start", "success", "stop"])

    def test_record_stale_plan_agent_handoff_rewrites_session_and_emits_validation_event(self) -> None:
        session = _session(args=["plan", "--omx", "--codex"])
        session.pending_plan_agent_worktrees = (SimpleNamespace(name="feature-a-1"),)
        session.plan_agent_attach_target = SimpleNamespace(
            session_name=" stale-session ",
            attach_command=("tmux", "attach", "-t", "stale-session"),
        )
        session.plan_agent_launch_result = PlanAgentLaunchResult(
            status="launched",
            reason="launched",
            outcomes=(
                PlanAgentLaunchOutcome(
                    worktree_name="feature-a-1",
                    worktree_root=Path("/tmp/feature-a-1"),
                    surface_id="surface-1",
                    status="launched",
                ),
            ),
            attach_target=session.plan_agent_attach_target,
        )
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(
            config=SimpleNamespace(),
            env={},
            _emit=lambda event, **payload: events.append((event, payload)),
        )

        record_stale_plan_agent_handoff(
            runtime,
            session,
            validation_reason="attach_target_stale_after_launch",
            resolve_launch_config_fn=lambda config, env, *, route: SimpleNamespace(transport="tmux", cli="codex"),
            recovery_command_fn=lambda rt, *, route, launch_config, created_worktrees: (
                "envctl",
                "--plan",
                "feature-a",
                "--tmux",
            ),
        )

        self.assertIsNone(session.plan_agent_attach_target)
        self.assertTrue(session.plan_agent_handoff_degraded)
        self.assertEqual(session.plan_agent_stale_session_name, "stale-session")
        self.assertEqual(session.plan_agent_stale_attach_command, "tmux attach -t stale-session")
        self.assertEqual(session.plan_agent_handoff_validation_reason, "attach_target_stale_after_launch")
        self.assertEqual(session.plan_agent_recovery_command, "envctl --plan feature-a --tmux")
        assert session.plan_agent_launch_result is not None
        self.assertEqual(session.plan_agent_launch_result.status, "failed")
        self.assertEqual(session.plan_agent_launch_result.reason, "attach_target_stale_after_launch")
        self.assertEqual(session.plan_agent_launch_result.attach_target, None)
        self.assertEqual(session.plan_agent_launch_result.outcomes[0].status, "failed")
        self.assertEqual(session.plan_agent_launch_result.outcomes[0].reason, "attach_target_stale_after_launch")
        self.assertEqual(session.plan_agent_launch_result.outcomes[0].surface_id, "surface-1")
        self.assertEqual(session.base_metadata["plan_agent_handoff_degraded"], True)
        self.assertEqual(session.base_metadata["implementation_session_running"], False)
        self.assertEqual(session.base_metadata["plan_agent_stale_session_name"], "stale-session")
        self.assertEqual(session.base_metadata["plan_agent_stale_attach_command"], "tmux attach -t stale-session")
        self.assertEqual(session.base_metadata["plan_agent_recovery_command"], "envctl --plan feature-a --tmux")
        self.assertEqual(
            events,
            [
                (
                    "startup.plan_agent_handoff.validation_failed",
                    {
                        "reason": "attach_target_stale_after_launch",
                        "stale_session_name": "stale-session",
                        "stale_attach_command": "tmux attach -t stale-session",
                        "recovery_command": "envctl --plan feature-a --tmux",
                    },
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
