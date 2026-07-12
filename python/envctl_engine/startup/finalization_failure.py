from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
import sys
import time
from typing import Any

from envctl_engine.startup.protocols import ProjectContextLike, StartupRuntime
from envctl_engine.startup.session import StartupSession, unconfirmed_service_names
from envctl_engine.startup.finalization_run_state import _build_run_state
from envctl_engine.requirements.core import dependency_definitions
from envctl_engine.runtime.lifecycle_requirement_ports import component_port_values
from envctl_engine.state.models import RunState, ServiceRecord
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
        self._normalize_colliding_service_state()
        self._emit_failure(final_error)
        self._terminate_started_services()
        self._prepare_collision_failure_state()
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

    def _normalize_colliding_service_state(self) -> None:
        """Give every newly started process a unique durable storage key.

        This runs before cleanup so duplicate hook-provided names cannot be
        collapsed in the termination request. The ServiceRecord keeps its
        authoritative project/service metadata; only its storage identity is
        disambiguated.
        """

        replacement_maps = [*self.session.services_by_project.values(), self.session.unterminated_services]
        reserved_names = set(self.session.preserved_services)
        for services in replacement_maps:
            reserved_names.update(services)
        assigned_names = set(self.session.preserved_services)
        identity_records: dict[int, tuple[str, ServiceRecord]] = {}
        collision_rows = list(self.session.service_state_collision_rows)
        recorded_replacements = {
            str(row.get("replacement_name") or "").strip()
            for row in collision_rows
            if isinstance(row, dict)
        }

        def normalized_services(
            services: dict[str, ServiceRecord],
            *,
            fallback_project: str = "",
        ) -> dict[str, ServiceRecord]:
            normalized: dict[str, ServiceRecord] = {}
            for original_name, service in services.items():
                prior_record = identity_records.get(id(service))
                if prior_record is not None:
                    prior_name, prior_service = prior_record
                    normalized[prior_name] = prior_service
                    continue
                stored_name = original_name
                stored_service = service
                if stored_name in assigned_names:
                    stored_name = _collision_service_name(
                        original_name,
                        service,
                        reserved_names.union(assigned_names),
                    )
                    if isinstance(stored_service, ServiceRecord):
                        stored_service = replace(
                            stored_service,
                            name=stored_name,
                            project=stored_service.project or fallback_project or None,
                        )
                    self.session.service_state_collisions.add(original_name)
                    if stored_name not in recorded_replacements:
                        collision_rows.append(
                            {
                                "original_name": original_name,
                                "replacement_name": stored_name,
                                "replacement_pid": getattr(service, "pid", None),
                                "replacement_project": getattr(service, "project", None),
                            }
                        )
                        recorded_replacements.add(stored_name)
                assigned_names.add(stored_name)
                reserved_names.add(stored_name)
                identity_records[id(service)] = (stored_name, stored_service)
                normalized[stored_name] = stored_service
            return normalized

        normalized_by_project: dict[str, dict[str, ServiceRecord]] = {}
        for project, services in self.session.services_by_project.items():
            normalized_by_project[project] = normalized_services(
                dict(services),
                fallback_project=project,
            )
        self.session.services_by_project = normalized_by_project
        self.session.unterminated_services = normalized_services(
            dict(self.session.unterminated_services)
        )
        self.session.service_state_collision_rows = collision_rows

    def _emit_failure(self, final_error: str) -> None:
        failure_payload: dict[str, object] = {
            "mode": self.session.runtime_mode,
            "command": self.session.effective_route.command,
            "error": final_error,
        }
        if self.session.strict_truth_failed:
            failure_payload["services"] = sorted(self.session.merged_services)
        try:
            self.runtime._emit("startup.failed", **failure_payload)
        except Exception:  # noqa: BLE001
            pass

    def _terminate_started_services(self) -> None:
        started_services = dict(self.session.unterminated_services)
        started_services.update(
            {
                service_name: service
                for project_services in self.session.services_by_project.values()
                for service_name, service in project_services.items()
            }
        )
        if started_services:
            try:
                failed_names = unconfirmed_service_names(
                    self.runtime._terminate_started_services(started_services),
                    started_services,
                )
            except Exception:  # noqa: BLE001
                failed_names = set(started_services)
            for project_name in list(self.session.services_by_project):
                retained = {
                    name: service
                    for name, service in self.session.services_by_project[project_name].items()
                    if name in failed_names
                }
                if retained:
                    self.session.services_by_project[project_name] = retained
                else:
                    self.session.services_by_project.pop(project_name, None)
            self.session.unterminated_services = {
                name: service for name, service in started_services.items() if name in failed_names
            }
            for service in self.session.unterminated_services.values():
                service.status = "termination_failed"
                service.degraded = True

    def _prepare_collision_failure_state(self) -> None:
        collision_names = set(self.session.service_state_collisions)
        retained_service_names = set(self.session.unterminated_services)
        for services in self.session.services_by_project.values():
            retained_service_names.update(services)
        collision_rows: list[dict[str, object]] = []
        for row in self.session.service_state_collision_rows:
            normalized_row = dict(row)
            replacement_name = str(normalized_row.get("replacement_name") or "").strip()
            normalized_row["replacement_exit_unconfirmed"] = replacement_name in retained_service_names
            collision_rows.append(normalized_row)
        recorded_originals = {
            str(row.get("original_name") or "").strip()
            for row in collision_rows
            if isinstance(row, dict)
        }
        collision_rows.extend(
            {
                "original_name": name,
                "replacement_exit_unconfirmed": False,
            }
            for name in sorted(collision_names - recorded_originals)
        )

        occupied_projects = set(self.session.preserved_requirements).union(
            self.session.requirements_by_project
        )
        remapped_requirements = {}
        requirement_rows = list(self.session.requirement_state_collision_rows)
        for project, requirements in self.session.requirements_by_project.items():
            preserved = self.session.preserved_requirements.get(project)
            if preserved is None:
                remapped_requirements[project] = requirements
                continue
            if requirements == preserved:
                continue
            synthetic_project = _collision_project_name(project, occupied_projects)
            occupied_projects.add(synthetic_project)
            # The dictionary key is only a durable storage identity. Keep the
            # authoritative project on the value so later port release and
            # container cleanup use the owner that acquired the resources.
            remapped_requirements[synthetic_project] = requirements
            requirement_rows.append(
                {
                    "original_project": project,
                    "replacement_project": synthetic_project,
                    "replacement_requirements_retained": True,
                }
            )
        self.session.requirements_by_project = remapped_requirements
        collision_rows.extend(requirement_rows)
        if collision_rows:
            self.session.base_metadata["startup_state_collisions"] = collision_rows
        # A collision-aware failure state can now retain both the previous
        # authority and any replacement resource whose cleanup was unconfirmed.
        if collision_rows or collision_names:
            self.session.preserve_existing_state_on_failure = False

    def _release_ports(self) -> None:
        if self.session.unterminated_services or _has_retained_managed_requirements(self.session):
            try:
                self.runtime._emit(
                    "port.session_release.skipped",
                    reason=(
                        "unterminated_services"
                        if self.session.unterminated_services
                        else "started_requirements_remain_tracked"
                    ),
                    services=sorted(self.session.unterminated_services),
                )
            except Exception:  # noqa: BLE001
                pass
            return
        try:
            self.port_allocator(self.runtime).release_session()
        except Exception:  # noqa: BLE001
            pass

    def _write_failure_artifacts(self, final_error: str) -> None:
        artifacts_started = time.monotonic()
        if self.session.preserve_existing_state_on_failure:
            try:
                self.runtime._emit(
                    "state.failure_write.skipped",
                    reason="existing_runtime_state_remains_authoritative",
                    run_id=self.session.run_id,
                )
                self.emit_phase(self.session, "artifacts_write", artifacts_started, status="skipped")
            except Exception:  # noqa: BLE001
                pass
            return
        run_state = build_failure_run_state(self.runtime, self.session, final_error)
        self.runtime._write_artifacts(run_state, self.session.selected_contexts, errors=self.session.errors)
        try:
            self.emit_phase(self.session, "artifacts_write", artifacts_started, status="error")
        except Exception:  # noqa: BLE001
            pass

    def _print_final_status(self, final_error: str) -> None:
        try:
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
        except Exception:  # noqa: BLE001
            pass


def _collision_service_name(name: str, service: object, occupied: set[str]) -> str:
    pid = getattr(service, "pid", None)
    suffix = f"Restart Collision {pid}" if isinstance(pid, int) and pid > 0 else "Restart Collision"
    base = f"{name} {suffix}"
    candidate = base
    index = 2
    while candidate in occupied:
        candidate = f"{base} {index}"
        index += 1
    return candidate


def _collision_project_name(project: str, occupied: set[str]) -> str:
    base = f"{project} Restart Collision"
    candidate = base
    index = 2
    while candidate in occupied:
        candidate = f"{base} {index}"
        index += 1
    return candidate


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


def _has_retained_managed_requirements(session: StartupSession) -> bool:
    for requirements in session.requirements_by_project.values():
        for definition in dependency_definitions():
            component = requirements.component(definition.id)
            if not bool(component.get("enabled", False)):
                continue
            if bool(component.get("external", False)) or bool(component.get("simulated", False)):
                continue
            if not bool(component.get("success", False)) and not str(component.get("container_name") or "").strip():
                continue
            if component_port_values(component) or str(component.get("container_name") or "").strip():
                return True
    return False


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
