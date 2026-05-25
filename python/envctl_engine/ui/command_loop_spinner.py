from __future__ import annotations

from dataclasses import dataclass
import sys
from typing import Any, Callable, Mapping

from .path_links import local_paths_in_text, render_paths_in_terminal_text
from .spinner import Spinner


@dataclass
class CommandSpinnerTracker:
    started: bool = False
    failed: bool = False
    failure_message: str = ""
    suppressed_by_suite_group: bool = False


def command_supports_spinner(command: str) -> bool:
    return command in {
        "stop",
        "restart",
        "test",
        "pr",
        "commit",
        "review",
        "migrate",
        "config",
        "logs",
        "clear-logs",
        "health",
        "errors",
        "stop-all",
        "blast-all",
        "blast-worktree",
    }


def command_spinner_message(command: str | None) -> str:
    messages = {
        "stop": "Stopping selected services...",
        "restart": "Preparing restart...",
        "test": "Preparing tests...",
        "pr": "Preparing pull request workflow...",
        "commit": "Preparing commit workflow...",
        "review": "Preparing review...",
        "migrate": "Preparing migrations...",
        "config": "Opening configuration...",
        "logs": "Loading logs...",
        "clear-logs": "Clearing logs...",
        "health": "Checking service health...",
        "errors": "Inspecting runtime errors...",
        "stop-all": "Stopping all services...",
        "blast-all": "Blasting all runtime processes...",
        "blast-worktree": "Blasting selected worktree...",
    }
    if command is None:
        return "Running command..."
    return messages.get(command, f"Running {command}...")


def command_success_message(command: str | None, *, exiting: bool) -> str | None:
    if exiting:
        return "Command finished; leaving interactive mode..."
    if command is None:
        return "Command complete"
    if command == "pr":
        # PR output already includes concise status lines; suppress redundant
        # spinner success footer ("+ pr complete").
        return None
    return f"{command} complete"


def command_label(command: str | None) -> str:
    if not command:
        return "Command"
    return command


def install_spinner_event_bridge(
    *,
    runtime: Any,
    active_spinner: Spinner,
    tracker: CommandSpinnerTracker,
    command_id: str,
) -> Callable[[], None]:
    _ = command_id
    add_listener = getattr(runtime, "add_emit_listener", None)
    if callable(add_listener):

        def listener(event_name: str, payload: Mapping[str, object]) -> None:
            apply_spinner_event(
                runtime=runtime,
                active_spinner=active_spinner,
                tracker=tracker,
                event_name=event_name,
                payload=payload,
            )

        remove = add_listener(listener)
        if callable(remove):

            def restore_from_listener() -> None:
                remove()

            return restore_from_listener
        return noop_restore

    emit = getattr(runtime, "_emit", None)
    if not callable(emit):
        return noop_restore

    def bridged_emit(event_name: str, **payload: object) -> None:
        emit(event_name, **payload)
        apply_spinner_event(
            runtime=runtime,
            active_spinner=active_spinner,
            tracker=tracker,
            event_name=event_name,
            payload=payload,
        )

    try:
        setattr(runtime, "_emit", bridged_emit)
    except Exception:
        return noop_restore

    def restore() -> None:
        try:
            setattr(runtime, "_emit", emit)
        except Exception:
            pass

    return restore


def apply_spinner_event(
    *,
    runtime: Any,
    active_spinner: Spinner,
    tracker: CommandSpinnerTracker,
    event_name: str,
    payload: Mapping[str, object],
) -> None:
    if suite_spinner_group_enabled_event(event_name, payload):
        tracker.suppressed_by_suite_group = True
        if tracker.started:
            spinner_end(active_spinner)
            tracker.started = False
        return
    if tracker.suppressed_by_suite_group and event_name == "ui.status":
        return
    if spinner_starts_for_event(event_name) and not tracker.started:
        active_spinner.start()
        tracker.started = True
    message = spinner_message_for_event(event_name, payload)
    if message and tracker.started:
        active_spinner.update(render_spinner_message(runtime=runtime, event_name=event_name, message=message))
    failure_message = spinner_failure_message_for_event(event_name, payload)
    if failure_message and not tracker.failed:
        tracker.failed = True
        tracker.failure_message = failure_message
        if tracker.started:
            active_spinner.update(failure_message)


def render_spinner_message(*, runtime: object, event_name: str, message: str) -> str:
    if event_name != "ui.status":
        return message
    return render_paths_in_terminal_text(
        message,
        paths=local_paths_in_text(message),
        env=getattr(runtime, "env", {}),
        stream=sys.stdout,
        interactive_tty=True,
    )


def spinner_message_for_event(event_name: str, payload: Mapping[str, object]) -> str | None:
    if event_name == "ui.status":
        message = payload_text(payload, "message")
        return message or None
    if event_name == "startup.execution":
        mode = payload_text(payload, "mode")
        project_count = payload_count(payload, "projects")
        workers = payload_text(payload, "workers")
        if project_count is not None and mode and workers:
            return f"Starting {project_count} project(s) in {mode} mode ({workers} workers)..."
        if project_count is not None and mode:
            return f"Starting {project_count} project(s) in {mode} mode..."
        return f"Starting services ({mode})..." if mode else "Starting services..."
    if event_name == "planning.projects.start":
        project_count = payload_count(payload, "projects")
        if project_count is None:
            return "Preparing planning PRs..."
        return f"Preparing planning PRs for {project_count} project(s)..."
    if event_name == "state.resume":
        return "Resuming previous runtime state..."
    if event_name == "state.action.start":
        command = payload_text(payload, "command")
        service_count = payload_count(payload, "service_count")
        if command == "logs":
            return state_action_progress_message("Loading logs", service_count)
        if command == "clear-logs":
            return state_action_progress_message("Clearing logs", service_count)
        if command == "health":
            return state_action_progress_message("Checking health", service_count)
        if command == "errors":
            return state_action_progress_message("Inspecting errors", service_count)
        return f"Running {command}..." if command else "Running state action..."
    if event_name == "config.command.start":
        return "Opening configuration..."
    if event_name == "requirements.start":
        service = payload_text(payload, "service") or "dependency"
        project = payload_text(payload, "project")
        port = payload_text(payload, "port")
        if project and port:
            return f"Starting {service} for {project} on port {port}..."
        return f"Starting {service} for {project}..." if project else f"Starting {service}..."
    if event_name == "requirements.healthy":
        service = payload_text(payload, "service") or "dependency"
        project = payload_text(payload, "project")
        return f"{service} healthy for {project}..." if project else f"{service} healthy..."
    if event_name == "service.bootstrap":
        service = payload_text(payload, "service") or "service"
        step = payload_text(payload, "step")
        if step:
            return f"Bootstrapping {service} ({step})..."
        return f"Bootstrapping {service}..."
    if event_name == "service.start":
        service = payload_text(payload, "service") or "service"
        project = payload_text(payload, "project")
        port = payload_text(payload, "port")
        retry = payload_text(payload, "retry").lower() in {"1", "true", "yes", "on"}
        prefix = "Retrying" if retry else "Starting"
        if project and port:
            return f"{prefix} {service} for {project} on port {port}..."
        return f"{prefix} {service} for {project}..." if project else f"{prefix} {service}..."
    if event_name == "service.bind.actual":
        service = payload_text(payload, "service") or "service"
        port = payload_text(payload, "actual_port")
        if port:
            return f"{service} bound on port {port}..."
        return f"Binding {service}..."
    if event_name == "cleanup.stop":
        return "Stopping selected services..."
    if event_name == "cleanup.stop_all":
        return "Stopping all services..."
    if event_name == "cleanup.blast":
        return "Blasting all services and containers..."
    if event_name == "cleanup.stop_all.remove_volumes":
        return "Removing Docker volumes..."
    if event_name == "action.command.start":
        command = payload_text(payload, "command")
        return f"Running {command}..." if command else "Running command..."
    if event_name == "action.command.finish":
        command = payload_text(payload, "command")
        code = coerce_int(payload.get("code"))
        if code == 0:
            return f"{command} completed..." if command else "Command completed..."
    return None


def spinner_starts_for_event(event_name: str) -> bool:
    return event_name in {
        "ui.status",
        "action.command.start",
        "startup.execution",
        "state.resume",
        "state.action.start",
        "config.command.start",
        "requirements.start",
        "service.bootstrap",
        "service.start",
        "cleanup.stop",
        "cleanup.stop_all",
        "cleanup.blast",
        "cleanup.stop_all.remove_volumes",
    }


def spinner_failure_message_for_event(event_name: str, payload: Mapping[str, object]) -> str | None:
    if event_name == "action.command.finish":
        code = coerce_int(payload.get("code"))
        if code is not None and code != 0:
            command = payload_text(payload, "command") or "command"
            return f"{command} failed (exit {code})"
    if event_name == "state.action.finish":
        code = coerce_int(payload.get("code"))
        if code is not None and code != 0:
            command = payload_text(payload, "command") or "state action"
            return f"{command} failed (exit {code})"
    if event_name == "config.command.finish":
        code = coerce_int(payload.get("code"))
        if code is not None and code != 0:
            return f"config failed (exit {code})"
    if event_name == "planning.projects.finish":
        code = coerce_int(payload.get("code"))
        if code is not None and code != 0:
            return f"Planning PR workflow failed (exit {code})"
    if event_name == "planning.projects.duplicate":
        return "Planning project selection failed"
    if event_name == "startup.failed":
        return "Startup failed"
    return None


def suite_spinner_group_enabled_event(event_name: str, payload: Mapping[str, object]) -> bool:
    if event_name != "test.suite_spinner_group.policy":
        return False
    enabled = payload.get("enabled")
    if isinstance(enabled, bool):
        return enabled
    text = str(enabled).strip().lower()
    return text in {"1", "true", "yes", "on"}


def spinner_end(active_spinner: Spinner) -> None:
    try:
        end = getattr(active_spinner, "end", None)
        if callable(end):
            end()
    except Exception:
        return


def payload_text(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if value is None:
        return ""
    return str(value).strip()


def payload_count(payload: Mapping[str, object], key: str) -> int | None:
    value = payload.get(key)
    if isinstance(value, list):
        return len(value)
    if isinstance(value, tuple):
        return len(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return int(stripped)
    return None


def state_action_progress_message(prefix: str, count: int | None) -> str:
    if count is None:
        return f"{prefix}..."
    return f"{prefix} for {service_count_label(count)}..."


def service_count_label(count: int | None) -> str:
    if count is None:
        return "selected service(s)"
    return f"{count} service(s)"


def coerce_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit() or (stripped.startswith("-") and stripped[1:].isdigit()):
            return int(stripped)
    return None


def noop_restore() -> None:
    return None
