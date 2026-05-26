from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import sys
import time
from typing import Any

from envctl_engine.startup.protocols import ProjectContextLike, StartupRuntime
from envctl_engine.startup.session import StartupSession
from envctl_engine.startup.finalization_run_state import _build_run_state
from envctl_engine.state.models import RunState
from envctl_engine.ui.color_policy import colors_enabled
from envctl_engine.ui.path_links import local_paths_in_text, render_paths_in_terminal_text
from envctl_engine.ui.status_symbols import STATUS_FAILURE


def build_failure_run_state(runtime: StartupRuntime, session: StartupSession, error: str) -> RunState:
    run_state = _build_run_state(runtime, session, failed=True)
    run_state.metadata["failed"] = True
    run_state.metadata["failure_message"] = error
    return run_state


@dataclass(frozen=True, slots=True)
class StartupFailureFinalizer:
    runtime: StartupRuntime
    session: StartupSession
    error: str
    ensure_run_id: Callable[[StartupSession], None]
    port_allocator: Callable[[StartupRuntime], object]
    emit_phase: Callable[..., None]
    render_final_failure_status: Callable[..., str]
    print_fn: Callable[[str], None] = print
    output_stream: Any = sys.stdout

    def finalize(self) -> int:
        self.ensure_run_id(self.session)
        final_error = self._final_error()
        self.session.failure_message = final_error
        self.session.errors.append(final_error)
        self._emit_failure(final_error)
        self._terminate_started_services()
        self._release_ports()
        self._write_failure_artifacts(final_error)
        self._print_final_status(final_error)
        return 1

    def _final_error(self) -> str:
        if "no free port found" in self.error.lower():
            return f"Port reservation failed: {self.error}"
        if self.error.startswith("Startup failed:"):
            return self.error
        return f"Startup failed: {self.error}"

    def _emit_failure(self, final_error: str) -> None:
        failure_payload: dict[str, object] = {
            "mode": self.session.runtime_mode,
            "command": self.session.effective_route.command,
            "error": final_error,
        }
        if self.session.strict_truth_failed:
            failure_payload["services"] = sorted(self.session.merged_services)
        self.runtime._emit("startup.failed", **failure_payload)

    def _terminate_started_services(self) -> None:
        started_services = {
            service_name: service
            for project_name in self.session.started_context_names
            for service_name, service in self.session.services_by_project.get(project_name, {}).items()
        }
        if started_services:
            self.runtime._terminate_started_services(started_services)

    def _release_ports(self) -> None:
        self.port_allocator(self.runtime).release_session()

    def _write_failure_artifacts(self, final_error: str) -> None:
        run_state = build_failure_run_state(self.runtime, self.session, final_error)
        artifacts_started = time.monotonic()
        self.runtime._write_artifacts(run_state, self.session.selected_contexts, errors=self.session.errors)
        self.emit_phase(self.session, "artifacts_write", artifacts_started, status="error")

    def _print_final_status(self, final_error: str) -> None:
        interactive_tty = failure_hyperlink_interactive_tty(self.runtime)
        rendered_error = self.render_final_failure_status(
            self.runtime,
            self.session,
            final_error,
            interactive_tty=interactive_tty,
        )
        self.print_fn(
            render_paths_in_terminal_text(
                rendered_error,
                paths=local_paths_in_text(rendered_error),
                env=self.runtime.env,
                stream=self.output_stream,
                interactive_tty=interactive_tty,
            )
        )


def finalize_failed_startup(
    *,
    runtime: StartupRuntime,
    session: StartupSession,
    error: str,
    ensure_run_id: Callable[[StartupSession], None],
    port_allocator: Callable[[StartupRuntime], object],
    emit_phase: Callable[..., None],
    render_final_failure_status: Callable[..., str],
) -> int:
    return StartupFailureFinalizer(
        runtime=runtime,
        session=session,
        error=error,
        ensure_run_id=ensure_run_id,
        port_allocator=port_allocator,
        emit_phase=emit_phase,
        render_final_failure_status=render_final_failure_status,
    ).finalize()


def failure_hyperlink_interactive_tty(runtime: StartupRuntime) -> bool | None:
    link_mode = str(runtime.env.get("ENVCTL_UI_HYPERLINK_MODE", "")).strip().lower()
    return True if link_mode == "on" else None


def render_final_failure_status(
    runtime: StartupRuntime,
    session: StartupSession,
    final_error: str,
    *,
    interactive_tty: bool | None,
) -> str:
    symbol = STATUS_FAILURE
    if colors_enabled(runtime.env, stream=sys.stdout, interactive_tty=bool(interactive_tty)):
        symbol = f"\033[31m{STATUS_FAILURE}\033[0m"
    rendered = f"{symbol} {final_error}"
    context_label = failure_context_label(session, final_error)
    if context_label and context_label not in rendered:
        rendered = f"{rendered} ({context_label})"
    return rendered


def failure_context_label(session: StartupSession, final_error: str) -> str | None:
    contexts: list[ProjectContextLike] = []
    seen_names: set[str] = set()
    for context in [*session.selected_contexts, *session.contexts_to_start]:
        name = str(getattr(context, "name", "") or "").strip()
        if not name or name in seen_names:
            continue
        contexts.append(context)
        seen_names.add(name)
    if not contexts:
        return None
    error_text = str(final_error or "")
    matches = [context for context in contexts if str(getattr(context, "name", "") or "").strip() in error_text]
    if matches:
        return format_failure_context_label(
            sorted(matches, key=lambda context: len(str(getattr(context, "name", "") or "")), reverse=True)[0]
        )
    if len(contexts) == 1:
        return format_failure_context_label(contexts[0])
    return None


def format_failure_context_label(context: ProjectContextLike) -> str:
    name = str(getattr(context, "name", "") or "").strip()
    root = Path(str(getattr(context, "root", "") or ""))
    kind = "worktree" if any(part == "trees" or part.startswith("trees-") for part in root.parts) else "project"
    return f"{kind}: {name}"
