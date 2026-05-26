from __future__ import annotations

import shlex
from collections.abc import Callable
from typing import TextIO, cast

from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree
from envctl_engine.shared.services import service_display_name
from envctl_engine.startup.protocols import StartupRuntime
from envctl_engine.startup.session import StartupSession
from envctl_engine.ui.path_links import local_paths_in_text, render_paths_in_terminal_text


def plan_dry_run_preview_lines(session: StartupSession, *, created_names: set[str]) -> list[str]:
    lines = ["Dry run: no worktrees, git state, or services were modified."]
    for context in session.selected_contexts:
        action = "create" if context.name in created_names else "reuse"
        lines.append(f"{context.name}: {action}")
    return lines


def print_plan_dry_run_preview(
    runtime: StartupRuntime,
    session: StartupSession,
    *,
    print_fn: Callable[[str], None],
) -> None:
    route = session.effective_route
    if route.command != "plan" or not bool(route.flags.get("dry_run")):
        return
    planning_orchestrator = getattr(runtime, "planning_worktree_orchestrator", None)
    selection_getter = getattr(planning_orchestrator, "last_plan_selection_result", None)
    selection_result = selection_getter() if callable(selection_getter) else None
    created_names = {
        worktree.name
        for worktree in getattr(selection_result, "created_worktrees", ())
        if isinstance(worktree, CreatedPlanWorktree)
    }
    for line in plan_dry_run_preview_lines(session, created_names=created_names):
        print_fn(line)


def import_dry_run_preview_lines(runtime: StartupRuntime, session: StartupSession) -> list[str]:
    route = session.effective_route
    if route.command != "import" or not bool(route.flags.get("dry_run")):
        return []
    planning_orchestrator = getattr(runtime, "planning_worktree_orchestrator", None)
    preview_getter = getattr(planning_orchestrator, "last_import_dry_run_result", None)
    preview = preview_getter() if callable(preview_getter) else None
    lines = ["Dry run: no worktrees, git state, services, or AI sessions were modified."]
    if preview is None:
        for context in session.selected_contexts:
            lines.append(f"{context.name}: action=preview path={context.root}")
        return lines
    ref = getattr(preview, "ref", None)
    worktree = getattr(preview, "worktree", None)
    name = str(getattr(worktree, "name", "") or "").strip()
    path = getattr(worktree, "root", "")
    action = str(getattr(preview, "action", "") or "preview").strip()
    remote_ref = str(getattr(ref, "remote_ref", "") or "").strip()
    local_branch = str(getattr(ref, "local_branch", "") or "").strip()
    lines.append(
        f"{name}: action={action} remote_ref={remote_ref} local_branch={local_branch} project={name} path={path}"
    )
    return lines


def print_import_dry_run_preview(
    runtime: StartupRuntime,
    session: StartupSession,
    *,
    print_fn: Callable[[str], None],
) -> None:
    for line in import_dry_run_preview_lines(runtime, session):
        print_fn(line)


def resolve_plan_dry_run(
    runtime: StartupRuntime,
    session: StartupSession,
    *,
    print_fn: Callable[[str], None],
) -> int | None:
    route = session.effective_route
    if route.command != "plan" or not bool(route.flags.get("dry_run")):
        return None
    print_plan_dry_run_preview(runtime, session, print_fn=print_fn)
    return 0


def resolve_import_dry_run(
    runtime: StartupRuntime,
    session: StartupSession,
    *,
    print_fn: Callable[[str], None],
) -> int | None:
    route = session.effective_route
    if route.command != "import" or not bool(route.flags.get("dry_run")):
        return None
    print_import_dry_run_preview(runtime, session, print_fn=print_fn)
    return 0


def restart_port_rebound_summary_lines(
    session: StartupSession,
    events: list[dict[str, object]],
) -> list[str]:
    route = session.effective_route
    if session.requested_command != "restart" or not bool(route.flags.get("interactive_command")):
        return []
    lines: list[str] = []
    seen: set[tuple[str, str, int, int]] = set()
    for event in events[session.startup_event_index :]:
        if event.get("event") != "port.rebound":
            continue
        previous = event.get("restart_preferred_port")
        current = event.get("port")
        project = str(event.get("project") or "").strip()
        service = str(event.get("service") or "").strip()
        if not project or not service:
            continue
        if not isinstance(previous, int) or previous <= 0:
            continue
        if not isinstance(current, int) or current <= 0 or current == previous:
            continue
        key = (project, service, previous, current)
        if key in seen:
            continue
        seen.add(key)
        lines.append(
            f"Port changed: {project} {service_display_name(service)} "
            f"{previous} -> {current} (previous port still in use)"
        )
    return lines


def print_restart_port_rebound_summary(
    runtime: StartupRuntime,
    session: StartupSession,
    *,
    print_fn: Callable[[str], None],
) -> None:
    for line in restart_port_rebound_summary_lines(session, runtime.events):
        print_fn(line)


def headless_plan_output_only(session: StartupSession) -> bool:
    route = session.effective_route
    return route.command == "plan" and bool(route.flags.get("batch"))


def plan_session_summary_lines(
    session: StartupSession,
    *,
    attach_target: object | None = None,
) -> list[str]:
    resolved_target = attach_target or session.plan_agent_attach_target
    if resolved_target is None:
        return []
    lines: list[str] = []
    attach_command = " ".join(
        str(part).strip() for part in getattr(resolved_target, "attach_command", ()) if str(part).strip()
    )
    new_session_command = " ".join(
        str(part).strip() for part in getattr(resolved_target, "new_session_command", ()) if str(part).strip()
    )
    session_name = str(getattr(resolved_target, "session_name", "")).strip()
    if new_session_command:
        lines.append(
            "existing session: envctl did not create a new AI session because one already exists for this "
            "plan/workspace/CLI."
        )
    if attach_command:
        lines.append(f"attach: {attach_command}")
    if new_session_command:
        lines.append(f"new session: {new_session_command}")
    if session_name:
        lines.append(f"kill: tmux kill-session -t {shlex.quote(session_name)}")
    return lines


def headless_plan_session_summary_lines(
    session: StartupSession,
    *,
    attach_target: object | None = None,
) -> list[str]:
    lines = plan_session_summary_lines(session, attach_target=attach_target)
    if attach_target is not None or session.plan_agent_attach_target is not None:
        return lines
    reason = str(session.plan_agent_handoff_validation_reason or "").strip()
    if not reason:
        return lines
    lines.append("Plan agent launch did not leave an attachable AI session.")
    lines.append(f"reason: {reason}")
    stale_name = str(session.plan_agent_stale_session_name or "").strip()
    if stale_name:
        lines.append(f"stale_session: {stale_name}")
    recovery_command = str(session.plan_agent_recovery_command or "").strip()
    if recovery_command:
        lines.append(f"recovery: {recovery_command}")
    return lines


def print_headless_plan_session_summary(
    session: StartupSession,
    *,
    validate_plan_agent_handoff: Callable[..., None],
    print_fn: Callable[[str], None],
    attach_target: object | None = None,
) -> None:
    if attach_target is None:
        validate_plan_agent_handoff(session, phase="headless_output")
    for line in headless_plan_session_summary_lines(session, attach_target=attach_target):
        print_fn(line)


def render_plan_agent_degraded_handoff_for_terminal(
    runtime: StartupRuntime,
    session: StartupSession,
    *,
    stream: object,
    print_fn: Callable[[str], None],
) -> None:
    print_fn(format_degraded_handoff_text_for_terminal(runtime, session, stream=stream))


def maybe_attach_plan_agent_terminal(
    *,
    runtime: StartupRuntime,
    session: StartupSession,
    validate_plan_agent_handoff: Callable[..., None],
    attach_plan_agent_terminal: Callable[[StartupRuntime, object], int],
    print_headless_plan_session_summary: Callable[..., None],
) -> int | None:
    validate_plan_agent_handoff(session, phase="interactive_attach")
    attach_target = session.plan_agent_attach_target
    if attach_target is None:
        return None
    session.plan_agent_attach_target = None
    attach_code = attach_plan_agent_terminal(runtime, attach_target)
    if attach_code != 0:
        print_headless_plan_session_summary(session, attach_target=attach_target)
        return 0
    return attach_code


def plan_agent_degraded_handoff_text(session: StartupSession) -> str:
    lines = [
        "Implementation session is running, but local app startup failed.",
        "",
        "AI session:",
    ]
    session_lines = plan_session_summary_lines(session)
    if session_lines:
        lines.extend(f"  {line}" for line in session_lines)
    else:
        lines.append("  status: running (attach guidance unavailable for this launch transport)")
    failures = list(session.local_startup_failures)
    if failures:
        lines.append("")
        if len(failures) == 1:
            failure = failures[0]
            lines.extend(
                [
                    "Local app startup:",
                    f"  project: {failure.project}",
                    f"  error: {failure.error}",
                    (
                        "  effect: backend/frontend services were not started; the AI implementation session "
                        "can continue."
                    ),
                    (
                        "  next: configure ENVCTL_BACKEND_START_CMD / ENVCTL_FRONTEND_START_CMD if this "
                        "worktree should start services, or disable tree startup when you only want AI "
                        "implementation sessions."
                    ),
                ]
            )
        else:
            lines.append("Local app startup:")
            for failure in failures:
                lines.extend(
                    [
                        f"  project: {failure.project}",
                        f"  error: {failure.error}",
                        (
                            "  effect: backend/frontend services were not started; the AI implementation "
                            "session can continue."
                        ),
                    ]
                )
            lines.append(
                "  next: configure ENVCTL_BACKEND_START_CMD / ENVCTL_FRONTEND_START_CMD if these worktrees "
                "should start services, or disable tree startup when you only want AI implementation sessions."
            )
    return "\n".join(lines)


def format_degraded_handoff_text_for_terminal(
    runtime: StartupRuntime,
    session: StartupSession,
    *,
    stream: object | None,
) -> str:
    text = plan_agent_degraded_handoff_text(session)
    link_mode = str(runtime.env.get("ENVCTL_UI_HYPERLINK_MODE", "")).strip().lower()
    return render_paths_in_terminal_text(
        text,
        paths=local_paths_in_text(text),
        env=runtime.env,
        stream=cast(TextIO | None, stream),
        interactive_tty=(True if link_mode == "on" else None),
    )
