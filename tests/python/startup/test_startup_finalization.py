from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from envctl_engine.config import load_config
from envctl_engine.runtime.command_router import parse_route
from envctl_engine.startup.finalization import (
    emit_preserved_service_merge,
    failure_context_label,
    finalize_failed_startup,
    finalize_plan_agent_degraded_handoff,
    finalize_successful_startup,
    format_degraded_handoff_text_for_terminal,
    headless_plan_session_summary_lines,
    maybe_attach_plan_agent_terminal,
    plan_dry_run_preview_lines,
    plan_agent_degraded_handoff_text,
    plan_session_summary_lines,
    print_headless_plan_session_summary,
    print_plan_dry_run_preview,
    print_restart_port_rebound_summary,
    render_final_failure_status,
    render_project_startup_warnings_for_route,
    render_project_startup_warnings,
    restart_port_rebound_summary_lines,
)
from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree
from envctl_engine.startup.session import LocalStartupFailure, StartupSession
from envctl_engine.state.models import RunState


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


def _runtime_stub(**overrides: object) -> SimpleNamespace:
    with tempfile.TemporaryDirectory() as tmpdir:
        config = load_config(
            {
                "RUN_REPO_ROOT": str(Path(tmpdir) / "repo"),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir) / "runtime"),
            }
        )
    values: dict[str, object] = {
        "config": config,
        "env": {},
        "events": [],
        "runtime_root": Path("/tmp/envctl-runtime"),
        "_requirement_enabled": lambda requirement_name, *, mode, route=None: False,
        "_run_dir_path": lambda run_id: Path("/tmp/envctl-runtime") / "runs" / str(run_id),
        "_service_enabled_for_mode": lambda mode, service_name: False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class StartupFinalizationTests(unittest.TestCase):
    def test_finalize_failed_startup_writes_error_artifacts_and_releases_ports(self) -> None:
        context = SimpleNamespace(name="Main")
        session = _session(contexts=[context])
        session.started_context_names.append("Main")
        service = SimpleNamespace(name="Main Backend")
        session.services_by_project["Main"] = {"Main Backend": service}
        events: list[tuple[str, dict[str, object]]] = []
        writes: list[tuple[RunState, list[object], list[str]]] = []
        terminated: list[dict[str, object]] = []
        released = {"value": False}
        rendered_statuses: list[str] = []

        runtime = _runtime_stub(
            env={},
            _emit=lambda event, **payload: events.append((event, payload)),
            _write_artifacts=lambda state, contexts, *, errors: writes.append((state, list(contexts), list(errors))),
            _terminate_started_services=lambda services: terminated.append(dict(services)),
        )

        result = finalize_failed_startup(
            runtime=runtime,
            session=session,
            error="no free port found for owner=Main",
            ensure_run_id=lambda session: None,
            port_allocator=lambda runtime: SimpleNamespace(release_session=lambda: released.__setitem__("value", True)),
            emit_phase=lambda session, phase, started_at, **extra: events.append((f"phase:{phase}", dict(extra))),
            render_final_failure_status=lambda runtime, session, error, *, interactive_tty: rendered_statuses.append(error)
            or error,
        )

        self.assertEqual(result, 1)
        self.assertTrue(released["value"])
        self.assertEqual(terminated, [{"Main Backend": service}])
        self.assertEqual(session.failure_message, "Port reservation failed: no free port found for owner=Main")
        self.assertEqual(session.errors, ["Port reservation failed: no free port found for owner=Main"])
        self.assertIn(
            (
                "startup.failed",
                {
                    "mode": "trees",
                    "command": "start",
                    "error": "Port reservation failed: no free port found for owner=Main",
                },
            ),
            events,
        )
        self.assertEqual(
            writes[0][0].metadata["failure_message"],
            "Port reservation failed: no free port found for owner=Main",
        )
        self.assertEqual(writes[0][1], [context])
        self.assertEqual(writes[0][2], ["Port reservation failed: no free port found for owner=Main"])
        self.assertIn(("phase:artifacts_write", {"status": "error"}), events)
        self.assertEqual(rendered_statuses, ["Port reservation failed: no free port found for owner=Main"])

    def test_finalize_failed_startup_preserves_existing_startup_failure_prefix_and_strict_truth_services(
        self,
    ) -> None:
        session = _session(contexts=[])
        session.strict_truth_failed = True
        session.preserved_services = {"zeta": object(), "alpha": object()}
        events: list[tuple[str, dict[str, object]]] = []

        runtime = _runtime_stub(
            env={"ENVCTL_UI_HYPERLINK_MODE": "on"},
            _emit=lambda event, **payload: events.append((event, payload)),
            _write_artifacts=lambda *args, **kwargs: None,
            _terminate_started_services=lambda services: None,
        )

        result = finalize_failed_startup(
            runtime=runtime,
            session=session,
            error="Startup failed: backend crashed",
            ensure_run_id=lambda session: None,
            port_allocator=lambda runtime: SimpleNamespace(release_session=lambda: None),
            emit_phase=lambda *args, **kwargs: None,
            render_final_failure_status=lambda runtime, session, error, *, interactive_tty: error,
        )

        self.assertEqual(result, 1)
        self.assertEqual(session.errors, ["Startup failed: backend crashed"])
        self.assertIn(
            (
                "startup.failed",
                {
                    "mode": "trees",
                    "command": "start",
                    "error": "Startup failed: backend crashed",
                    "services": ["alpha", "zeta"],
                },
            ),
            events,
        )

    def test_finalize_successful_startup_writes_artifacts_summary_snapshot_and_returns_zero(self) -> None:
        context = SimpleNamespace(name="Main")
        session = _session(contexts=[context])
        run_state = RunState(run_id="run-finalization", mode="trees")
        writes: list[tuple[RunState, list[object], list[str]]] = []
        events: list[tuple[str, dict[str, object]]] = []
        snapshots: list[tuple[str, dict[str, object]]] = []
        restart_summaries: list[StartupSession] = []
        summaries: list[tuple[RunState, list[object]]] = []

        runtime = SimpleNamespace(
            _write_artifacts=lambda state, contexts, *, errors: writes.append((state, list(contexts), list(errors))),
            _emit=lambda event, **payload: events.append((event, payload)),
            _print_summary=lambda state, contexts: summaries.append((state, list(contexts))),
            _should_enter_post_start_interactive=lambda route: False,
        )

        result = finalize_successful_startup(
            runtime=runtime,
            session=session,
            ensure_run_id=lambda session: None,
            validate_plan_agent_handoff=lambda session, *, phase: None,
            build_success_run_state=lambda runtime, session: run_state,
            emit_preserved_service_merge=lambda session: None,
            emit_phase=lambda session, phase, started_at, **extra: events.append((f"phase:{phase}", dict(extra))),
            requirements_timing_enabled=lambda route: False,
            suppress_timing_output=lambda route: False,
            print_startup_summary=lambda **kwargs: None,
            startup_breakdown_enabled=lambda route: False,
            suppress_progress_output=lambda route: False,
            print_restart_port_rebound_summary=restart_summaries.append,
            emit_snapshot=lambda session, checkpoint, **payload: snapshots.append((checkpoint, payload)),
            headless_plan_output_only=lambda session: False,
            print_headless_plan_session_summary=lambda session: None,
            maybe_attach_plan_agent_terminal=lambda session: None,
            finalize_plan_agent_degraded_handoff=lambda session: self.fail("degraded handoff should not run"),
        )

        self.assertEqual(result, 0)
        self.assertEqual(writes, [(run_state, [context], [])])
        self.assertIn(("phase:artifacts_write", {"status": "ok"}), events)
        self.assertEqual(restart_summaries, [session])
        self.assertEqual(summaries, [(run_state, [context])])
        self.assertEqual(snapshots[0][0], "before_dashboard_entry")
        self.assertEqual(snapshots[0][1]["service_count"], 0)

    def test_finalize_successful_startup_delegates_degraded_plan_agent_handoff(self) -> None:
        session = _session(contexts=[])
        session.plan_agent_handoff_degraded = True

        result = finalize_successful_startup(
            runtime=SimpleNamespace(),
            session=session,
            ensure_run_id=lambda session: self.fail("normal finalization should not run"),
            validate_plan_agent_handoff=lambda session, *, phase: None,
            build_success_run_state=lambda runtime, session: RunState(run_id="unused", mode="trees"),
            emit_preserved_service_merge=lambda session: None,
            emit_phase=lambda *args, **kwargs: None,
            requirements_timing_enabled=lambda route: False,
            suppress_timing_output=lambda route: False,
            print_startup_summary=lambda **kwargs: None,
            startup_breakdown_enabled=lambda route: False,
            suppress_progress_output=lambda route: False,
            print_restart_port_rebound_summary=lambda session: None,
            emit_snapshot=lambda *args, **kwargs: None,
            headless_plan_output_only=lambda session: False,
            print_headless_plan_session_summary=lambda session: None,
            maybe_attach_plan_agent_terminal=lambda session: None,
            finalize_plan_agent_degraded_handoff=lambda session: 7,
        )

        self.assertEqual(result, 7)

    def test_finalize_plan_agent_degraded_handoff_writes_artifacts_and_attach_result(self) -> None:
        session = _session(contexts=[])
        run_state = RunState(run_id="run-finalization", mode="trees")
        writes: list[tuple[RunState, list[object], list[str]]] = []
        events: list[tuple[str, dict[str, object]]] = []
        rendered: list[StartupSession] = []
        headless_checks: list[StartupSession] = []
        attach_checks: list[StartupSession] = []

        runtime = SimpleNamespace(
            _write_artifacts=lambda state, contexts, *, errors: writes.append((state, list(contexts), list(errors))),
        )

        result = finalize_plan_agent_degraded_handoff(
            runtime=runtime,
            session=session,
            ensure_run_id=lambda session: None,
            validate_plan_agent_handoff=lambda session, *, phase: events.append(("validate", {"phase": phase})),
            build_success_run_state=lambda runtime, session: run_state,
            emit_phase=lambda session, phase, started_at, **extra: events.append((f"phase:{phase}", dict(extra))),
            render_plan_agent_degraded_handoff=rendered.append,
            headless_plan_output_only=lambda session: headless_checks.append(session) or False,
            maybe_attach_plan_agent_terminal=lambda session: attach_checks.append(session) or 5,
        )

        self.assertEqual(result, 5)
        self.assertEqual(writes, [(run_state, [], [])])
        self.assertIn(("validate", {"phase": "degraded_finalization"}), events)
        self.assertIn(("phase:artifacts_write", {"status": "degraded"}), events)
        self.assertEqual(rendered, [session])
        self.assertEqual(headless_checks, [session])
        self.assertEqual(attach_checks, [session])

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

    def test_print_headless_plan_session_summary_validates_when_no_attach_target_override(self) -> None:
        session = _session(contexts=[])
        session.plan_agent_handoff_validation_reason = "attach_target_stale_after_launch"
        session.plan_agent_stale_session_name = "envctl-stale"
        session.plan_agent_recovery_command = "envctl plan --tmux --new-session"
        validations: list[tuple[StartupSession, str]] = []
        lines: list[str] = []

        print_headless_plan_session_summary(
            session,
            validate_plan_agent_handoff=lambda session, *, phase: validations.append((session, phase)),
            print_fn=lines.append,
        )

        self.assertEqual(validations, [(session, "headless_output")])
        self.assertEqual(
            lines,
            [
                "Plan agent launch did not leave an attachable AI session.",
                "reason: attach_target_stale_after_launch",
                "stale_session: envctl-stale",
                "recovery: envctl plan --tmux --new-session",
            ],
        )

    def test_print_headless_plan_session_summary_uses_attach_target_override_without_validation(self) -> None:
        session = _session(contexts=[])
        attach_target = SimpleNamespace(
            attach_command=("tmux", "attach", "-t", "envctl-plan"),
            new_session_command=(),
            session_name="envctl-plan",
        )
        lines: list[str] = []

        print_headless_plan_session_summary(
            session,
            attach_target=attach_target,
            validate_plan_agent_handoff=lambda session, *, phase: self.fail("override attach target should skip validation"),
            print_fn=lines.append,
        )

        self.assertEqual(lines, ["attach: tmux attach -t envctl-plan", "kill: tmux kill-session -t envctl-plan"])

    def test_maybe_attach_plan_agent_terminal_clears_target_and_returns_attach_code(self) -> None:
        session = _session(contexts=[])
        attach_target = SimpleNamespace(attach_command=("tmux", "attach", "-t", "envctl-plan"))
        session.plan_agent_attach_target = attach_target
        validations: list[tuple[StartupSession, str]] = []
        attach_calls: list[object] = []

        result = maybe_attach_plan_agent_terminal(
            runtime=SimpleNamespace(),
            session=session,
            validate_plan_agent_handoff=lambda session, *, phase: validations.append((session, phase)),
            attach_plan_agent_terminal=lambda runtime, target: attach_calls.append(target) or 0,
            print_headless_plan_session_summary=lambda session, *, attach_target: self.fail(
                "successful attach should not print fallback summary"
            ),
        )

        self.assertEqual(result, 0)
        self.assertIsNone(session.plan_agent_attach_target)
        self.assertEqual(validations, [(session, "interactive_attach")])
        self.assertEqual(attach_calls, [attach_target])

    def test_maybe_attach_plan_agent_terminal_prints_summary_when_attach_fails(self) -> None:
        session = _session(contexts=[])
        attach_target = SimpleNamespace(attach_command=("tmux", "attach", "-t", "envctl-plan"))
        session.plan_agent_attach_target = attach_target
        printed: list[object] = []

        result = maybe_attach_plan_agent_terminal(
            runtime=SimpleNamespace(),
            session=session,
            validate_plan_agent_handoff=lambda session, *, phase: None,
            attach_plan_agent_terminal=lambda runtime, target: 42,
            print_headless_plan_session_summary=lambda session, *, attach_target: printed.append(attach_target),
        )

        self.assertEqual(result, 0)
        self.assertIsNone(session.plan_agent_attach_target)
        self.assertEqual(printed, [attach_target])

    def test_maybe_attach_plan_agent_terminal_returns_none_without_attach_target(self) -> None:
        session = _session(contexts=[])
        validations: list[tuple[StartupSession, str]] = []

        result = maybe_attach_plan_agent_terminal(
            runtime=SimpleNamespace(),
            session=session,
            validate_plan_agent_handoff=lambda session, *, phase: validations.append((session, phase)),
            attach_plan_agent_terminal=lambda runtime, target: self.fail("missing attach target should not attach"),
            print_headless_plan_session_summary=lambda session, *, attach_target: self.fail(
                "missing attach target should not print fallback summary"
            ),
        )

        self.assertIsNone(result)
        self.assertEqual(validations, [(session, "interactive_attach")])

    def test_format_degraded_handoff_text_for_terminal_applies_path_links(self) -> None:
        session = _session(contexts=[])
        session.plan_agent_attach_target = SimpleNamespace(
            attach_command=("tmux", "attach", "-t", "envctl-plan"),
            new_session_command=(),
            session_name="envctl-plan",
        )
        session.local_startup_failures.append(
            LocalStartupFailure(
                project="feature-a-1",
                error="missing_service_start_command: /tmp/envctl/missing backend",
                reason="missing_service_start_command",
            )
        )
        runtime = SimpleNamespace(env={"ENVCTL_UI_HYPERLINK_MODE": "off"})

        rendered = format_degraded_handoff_text_for_terminal(runtime, session, stream=None)

        self.assertIn("Implementation session is running, but local app startup failed.", rendered)
        self.assertIn("missing_service_start_command: /tmp/envctl/missing backend", rendered)

    def test_emit_preserved_service_merge_reports_preserved_and_replaced_state(self) -> None:
        session = _session(contexts=[])
        session.preserved_services = {"alpha Backend": object(), "alpha Frontend": object()}
        session.preserved_requirements = {"alpha": object()}
        session.services_by_project = {"alpha": {"alpha Backend": object()}, "beta": {"beta Frontend": object()}}
        session.requirements_by_project = {"alpha": object(), "beta": object()}
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(_emit=lambda event, **payload: events.append((event, payload)))

        emit_preserved_service_merge(runtime, session)

        self.assertEqual(
            events,
            [
                (
                    "runtime.state.merge_preserved_services",
                    {
                        "preserved_services": ["alpha Backend", "alpha Frontend"],
                        "replaced_services": ["alpha Backend", "beta Frontend"],
                        "preserved_requirements": ["alpha"],
                        "replaced_requirements": ["alpha", "beta"],
                    },
                )
            ],
        )

    def test_plan_dry_run_preview_lines_render_create_and_reuse_actions(self) -> None:
        session = _session(
            contexts=[
                SimpleNamespace(name="feature-a-1", root=Path("/repo/trees/feature-a/1")),
                SimpleNamespace(name="feature-b-1", root=Path("/repo/trees/feature-b/1")),
            ]
        )

        lines = plan_dry_run_preview_lines(session, created_names={"feature-b-1"})

        self.assertEqual(
            lines,
            [
                "Dry run: no worktrees, git state, or services were modified.",
                "feature-a-1: reuse",
                "feature-b-1: create",
            ],
        )

    def test_print_plan_dry_run_preview_reads_created_worktrees_from_runtime_orchestrator(self) -> None:
        route = parse_route(["plan", "--dry-run"], env={})
        session = StartupSession(
            requested_route=route,
            effective_route=route,
            requested_command="plan",
            runtime_mode="trees",
            run_id="run-finalization",
            selected_contexts=[
                SimpleNamespace(name="feature-a-1", root=Path("/repo/trees/feature-a/1")),
                SimpleNamespace(name="feature-b-1", root=Path("/repo/trees/feature-b/1")),
            ],
        )
        selection_result = SimpleNamespace(
            created_worktrees=(
                CreatedPlanWorktree(
                    name="feature-b-1",
                    root=Path("/repo/trees/feature-b/1"),
                    plan_file="/repo/todo/plans/feature-b.md",
                ),
                SimpleNamespace(name="ignored"),
            )
        )
        runtime = SimpleNamespace(
            planning_worktree_orchestrator=SimpleNamespace(last_plan_selection_result=lambda: selection_result)
        )
        lines: list[str] = []

        print_plan_dry_run_preview(runtime, session, print_fn=lines.append)

        self.assertEqual(
            lines,
            [
                "Dry run: no worktrees, git state, or services were modified.",
                "feature-a-1: reuse",
                "feature-b-1: create",
            ],
        )

    def test_print_plan_dry_run_preview_skips_non_plan_or_non_dry_run_routes(self) -> None:
        session = _session(contexts=[])
        lines: list[str] = []

        print_plan_dry_run_preview(SimpleNamespace(), session, print_fn=lines.append)

        self.assertEqual(lines, [])

    def test_restart_port_rebound_summary_lines_deduplicate_port_changes(self) -> None:
        route = parse_route(["restart"], env={})
        route.flags["interactive_command"] = True
        session = StartupSession(
            requested_route=route,
            effective_route=route,
            requested_command="restart",
            runtime_mode="trees",
            run_id="run-finalization",
            startup_event_index=1,
        )
        events = [
            {"event": "port.rebound", "project": "ignored", "service": "backend", "restart_preferred_port": 1, "port": 2},
            {
                "event": "port.rebound",
                "project": "feature-a-1",
                "service": "backend",
                "restart_preferred_port": 8000,
                "port": 8100,
            },
            {
                "event": "port.rebound",
                "project": "feature-a-1",
                "service": "backend",
                "restart_preferred_port": 8000,
                "port": 8100,
            },
        ]

        lines = restart_port_rebound_summary_lines(session, events)

        self.assertEqual(
            lines,
            ["Port changed: feature-a-1 Backend 8000 -> 8100 (previous port still in use)"],
        )

    def test_print_restart_port_rebound_summary_prints_rebound_lines_from_runtime_events(self) -> None:
        route = parse_route(["restart"], env={})
        route.flags["interactive_command"] = True
        session = StartupSession(
            requested_route=route,
            effective_route=route,
            requested_command="restart",
            runtime_mode="trees",
            run_id="run-finalization",
            startup_event_index=0,
        )
        runtime = SimpleNamespace(
            events=[
                {
                    "event": "port.rebound",
                    "project": "feature-a-1",
                    "service": "frontend",
                    "restart_preferred_port": 3000,
                    "port": 3100,
                }
            ]
        )
        lines: list[str] = []

        print_restart_port_rebound_summary(runtime, session, print_fn=lines.append)

        self.assertEqual(lines, ["Port changed: feature-a-1 Frontend 3000 -> 3100 (previous port still in use)"])

    def test_render_project_startup_warnings_prefers_spinner_detail(self) -> None:
        details: list[tuple[str, str]] = []
        spinner = SimpleNamespace(print_detail=lambda project, line: details.append((project, line)))
        runtime = SimpleNamespace(env={}, _emit=lambda *_args, **_kwargs: None)
        context = SimpleNamespace(name="feature-a-1")

        render_project_startup_warnings(
            runtime,
            context=context,
            warnings=["  first warning  ", "", "second warning"],
            suppress_progress=False,
            project_spinner_group=spinner,
        )

        self.assertEqual(details, [("feature-a-1", "first warning"), ("feature-a-1", "second warning")])

    def test_render_project_startup_warnings_emits_status_when_progress_is_suppressed(self) -> None:
        emitted: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(env={}, _emit=lambda event, **payload: emitted.append((event, payload)))
        context = SimpleNamespace(name="feature-a-1")

        render_project_startup_warnings(
            runtime,
            context=context,
            warnings=["first warning", "second warning"],
            suppress_progress=True,
            project_spinner_group=None,
        )

        self.assertEqual(
            emitted,
            [
                ("ui.status", {"message": "first warning"}),
                ("ui.status", {"message": "second warning"}),
            ],
        )

    def test_render_project_startup_warnings_for_route_resolves_suppression(self) -> None:
        emitted: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(env={}, _emit=lambda event, **payload: emitted.append((event, payload)))
        context = SimpleNamespace(name="feature-a-1")
        route = parse_route(["start", "--headless"], env={})
        checked_routes: list[object] = []

        render_project_startup_warnings_for_route(
            runtime,
            context=context,
            warnings=["first warning"],
            route=route,
            project_spinner_group=None,
            suppress_progress_output=lambda route: checked_routes.append(route) or True,
        )

        self.assertEqual(checked_routes, [route])
        self.assertEqual(emitted, [("ui.status", {"message": "first warning"})])


if __name__ == "__main__":
    unittest.main()
