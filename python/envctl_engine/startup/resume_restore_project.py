from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.startup.resume_restore_policy import (
    _configured_restore_service_types,
    _requirements_reuse_decision,
    _reserve_application_service_ports,
    _resume_terminate_aggressive,
    _route_for_partial_service_restore,
    _service_types_for_names,
)


@dataclass(slots=True)
class ResumeProjectRestoreRunner:
    orchestrator: object
    rt: object
    state: RunState
    missing_services: list[str]
    route_for_startup: Route
    total_projects: int
    use_project_spinner_group: bool
    project_spinner_group: object
    use_single_spinner: bool
    active_spinner: object
    port_allocator: object

    def restore_project(self, index: int, project: str) -> dict[str, object]:
        project_started = time.monotonic()
        step_durations_ms: dict[str, float] = {}
        prefix = f"[{index}/{self.total_projects}]"
        project_route_for_startup = self.route_for_startup
        self._report_progress(
            project,
            f"{prefix} Restoring stale services...",
            emit_lifecycle=True,
        )

        def mark_step(
            step: str,
            *,
            status: str = "ok",
            duration_ms: float | None = None,
            **extra: object,
        ) -> None:
            if duration_ms is None:
                duration_ms = _round_ms(time.monotonic() - project_started)
            step_durations_ms[step] = duration_ms
            self.rt._emit(  # type: ignore[attr-defined]
                "resume.restore.step",
                run_id=self.state.run_id,
                project=project,
                step=step,
                status=status,
                duration_ms=duration_ms,
                **extra,
            )

        self._report_progress(
            project,
            f"{prefix} Resolving runtime context...",
            single_message=f"{prefix} Resolving runtime context for {project}...",
        )
        context_started = time.monotonic()
        context = self.rt._resume_context_for_project(self.state, project)  # type: ignore[attr-defined]
        if context is None:
            mark_step(
                "resolve_context",
                status="error",
                duration_ms=_round_ms(time.monotonic() - context_started),
                context_found=False,
            )
            self._mark_failure(
                project,
                f"{prefix} Context not found",
                single_message=f"{prefix} Context not found for {project}",
            )
            project_total = _round_ms(time.monotonic() - project_started)
            self._emit_project_timing(
                project=project,
                total_ms=project_total,
                status="error",
                steps=step_durations_ms,
                error="project_root_not_found",
            )
            return {
                "project": project,
                "error": "project root not found",
                "steps": step_durations_ms,
                "total_ms": project_total,
            }
        mark_step(
            "resolve_context",
            duration_ms=_round_ms(time.monotonic() - context_started),
            context_found=True,
        )
        project_service_names = [
            name
            for name in list(self.state.services.keys())
            if self.rt._project_name_from_service(name).lower() == project.lower()  # type: ignore[attr-defined]
        ]
        original_services: dict[str, ServiceRecord] = {
            name: self.state.services[name] for name in project_service_names if name in self.state.services
        }
        missing_set = set(self.missing_services)
        missing_project_service_names = [name for name in project_service_names if name in missing_set]
        original_requirements = self.state.requirements.get(project)
        context_root = getattr(context, "root", None)
        requirements_reused, requirements_reuse_reason = _requirements_reuse_decision(
            self.orchestrator,
            self.rt,
            project=project,
            requirements=original_requirements,
            project_root=context_root if isinstance(context_root, Path) else None,
        )
        requirements_for_services = original_requirements if requirements_reused else None
        self.rt._emit(  # type: ignore[attr-defined]
            "resume.restore.requirements_reuse",
            run_id=self.state.run_id,
            project=project,
            reused=requirements_reused,
            reason=requirements_reuse_reason,
        )
        configured_service_types = _configured_restore_service_types(self.rt, mode=self.state.mode, context=context)
        original_service_types = _service_types_for_names(
            project=project,
            service_names=project_service_names,
            services=original_services,
        )
        absent_service_types = configured_service_types.difference(original_service_types)
        selected_service_names = missing_project_service_names if requirements_reused else project_service_names
        selected_service_types = _service_types_for_names(
            project=project,
            service_names=selected_service_names,
            services=original_services,
        )
        if requirements_reused:
            selected_service_types.update(absent_service_types)
        elif configured_service_types:
            selected_service_types = set(configured_service_types)

        existing_requirements = original_requirements
        if existing_requirements is not None and not requirements_reused:
            self._report_progress(
                project,
                f"{prefix} Releasing previous requirement ports...",
                single_message=f"{prefix} Releasing previous requirement ports for {project}...",
            )
            release_started = time.monotonic()
            self.rt._release_requirement_ports(existing_requirements)  # type: ignore[attr-defined]
            mark_step(
                "release_requirement_ports",
                duration_ms=_round_ms(time.monotonic() - release_started),
            )

        try:
            if requirements_reused and requirements_for_services is not None:
                requirements = requirements_for_services
                mark_step("start_requirements", duration_ms=0.0, status="reused")
            else:
                project_route_for_startup = self._route_with_spinner_updates(project, prefix)
                requirements_started = time.monotonic()
                requirements = self.rt._start_requirements_for_project(
                    context, mode=self.state.mode, route=project_route_for_startup
                )  # type: ignore[attr-defined]
                mark_step(
                    "start_requirements",
                    duration_ms=_round_ms(time.monotonic() - requirements_started),
                )
                if not self.rt._requirements_ready(requirements):  # type: ignore[attr-defined]
                    error_message = "requirements unavailable: " + (
                        ", ".join(requirements.failures) or "unknown requirements failure"
                    )
                    self._mark_failure(
                        project,
                        f"{prefix} Requirements unavailable",
                        single_message=f"{prefix} Requirements unavailable for {project}",
                    )
                    project_total = _round_ms(time.monotonic() - project_started)
                    self._emit_project_timing(
                        project=project,
                        total_ms=project_total,
                        status="error",
                        steps=step_durations_ms,
                        error="requirements_unavailable",
                    )
                    return {
                        "project": project,
                        "error": error_message,
                        "steps": step_durations_ms,
                        "total_ms": project_total,
                    }

            self._report_progress(
                project,
                f"{prefix} Stopping stale services...",
                single_message=f"{prefix} Stopping stale services for {project}...",
            )
            stop_started = time.monotonic()
            terminated_count = self._stop_stale_services(
                service_names=selected_service_names,
                original_services=original_services,
            )
            mark_step(
                "stop_stale_services",
                duration_ms=_round_ms(time.monotonic() - stop_started),
                stale_service_count=len(selected_service_names),
                terminated_count=terminated_count,
                aggressive=_resume_terminate_aggressive(self.orchestrator, self.rt),
            )

            self._report_progress(
                project,
                f"{prefix} Reserving service ports...",
                single_message=f"{prefix} Reserving service ports for {project}...",
            )
            reserve_started = time.monotonic()
            if selected_service_types:
                _reserve_application_service_ports(
                    self.orchestrator,
                    self.rt,
                    context,
                    self.port_allocator,
                    selected_service_types=selected_service_types,
                )
            elif not requirements_reused:
                self.rt._reserve_project_ports(context)  # type: ignore[attr-defined]
            mark_step(
                "reserve_ports",
                duration_ms=_round_ms(time.monotonic() - reserve_started),
                selected_service_types=sorted(selected_service_types),
            )

            project_route_for_startup = _route_for_partial_service_restore(
                project_route_for_startup,
                selected_service_types=selected_service_types,
            )
            self._report_progress(
                project,
                f"{prefix} Starting app services...",
                single_message=f"{prefix} Starting app services for {project}...",
            )
            services_started = time.monotonic()
            project_services = self.rt._start_project_services(  # type: ignore[attr-defined]
                context,
                requirements=requirements,
                run_id=self.state.run_id,
                route=project_route_for_startup,
            )
            mark_step(
                "start_services",
                duration_ms=_round_ms(time.monotonic() - services_started),
                restored_service_count=len(project_services),
            )
            self._mark_success(project, f"{prefix} restored", single_message=f"{prefix} {project} restored")
            project_total = _round_ms(time.monotonic() - project_started)
            self._emit_project_timing(
                project=project,
                total_ms=project_total,
                status="ok",
                steps=step_durations_ms,
            )
            return {
                "project": project,
                "error": None,
                "steps": step_durations_ms,
                "total_ms": project_total,
                "project_services": project_services,
                "requirements": requirements,
                "remove_service_names": selected_service_names,
            }
        except RuntimeError as exc:
            mark_step("exception", status="error", error=str(exc))
            self._mark_failure(
                project,
                f"{prefix} Restore failed: {exc}",
                single_message=f"{prefix} Restore failed for {project}: {exc}",
            )
            project_total = _round_ms(time.monotonic() - project_started)
            self._emit_project_timing(
                project=project,
                total_ms=project_total,
                status="error",
                steps=step_durations_ms,
                error=str(exc),
            )
            return {
                "project": project,
                "error": str(exc),
                "steps": step_durations_ms,
                "total_ms": project_total,
            }

    def _route_with_spinner_updates(self, project: str, prefix: str) -> Route:
        if self.use_project_spinner_group:
            return Route(
                command=self.route_for_startup.command,
                mode=self.route_for_startup.mode,
                raw_args=self.route_for_startup.raw_args,
                passthrough_args=self.route_for_startup.passthrough_args,
                projects=self.route_for_startup.projects,
                flags={
                    **self.route_for_startup.flags,
                    "_spinner_update_project": (
                        lambda _project, message, *, _project_name=project: (
                            self.project_spinner_group.update_project(
                                _project_name,
                                f"{prefix} {message}",
                            )
                        )
                    ),
                },
            )
        if self.use_single_spinner:
            return Route(
                command=self.route_for_startup.command,
                mode=self.route_for_startup.mode,
                raw_args=self.route_for_startup.raw_args,
                passthrough_args=self.route_for_startup.passthrough_args,
                projects=self.route_for_startup.projects,
                flags={
                    **self.route_for_startup.flags,
                    "_spinner_update": (lambda message: self.active_spinner.update(f"{prefix} {message}")),
                },
            )
        return self.route_for_startup

    def _stop_stale_services(
        self,
        *,
        service_names: list[str],
        original_services: dict[str, ServiceRecord],
    ) -> int:
        terminated_count = 0
        aggressive_terminate = _resume_terminate_aggressive(self.orchestrator, self.rt)
        for service_name in service_names:
            service = original_services.get(service_name)
            if service is None:
                continue
            terminated = self.rt._terminate_service_record(  # type: ignore[attr-defined]
                service,
                aggressive=aggressive_terminate,
                verify_ownership=True,
            )
            if terminated:
                terminated_count += 1
                port = self.rt._service_port(service)  # type: ignore[attr-defined]
                if port is not None:
                    self.port_allocator.release(port)  # type: ignore[attr-defined]
        return terminated_count

    def _report_progress(
        self,
        project: str,
        message: str,
        *,
        single_message: str | None = None,
        emit_lifecycle: bool = False,
    ) -> None:
        if self.use_project_spinner_group:
            self.project_spinner_group.update_project(project, message)
        elif self.use_single_spinner:
            rendered_message = single_message or message
            self.active_spinner.update(rendered_message)
            if emit_lifecycle:
                self.rt._emit(  # type: ignore[attr-defined]
                    "ui.spinner.lifecycle",
                    component="resume.restore",
                    op_id="resume.restore",
                    state="update",
                    message=rendered_message,
                )
        else:
            print(message)

    def _mark_success(self, project: str, message: str, *, single_message: str) -> None:
        if self.use_project_spinner_group:
            self.project_spinner_group.mark_success(project, message)
        elif self.use_single_spinner:
            self.active_spinner.update(single_message)

    def _mark_failure(self, project: str, message: str, *, single_message: str | None = None) -> None:
        if self.use_project_spinner_group:
            self.project_spinner_group.mark_failure(project, message)
        elif self.use_single_spinner:
            self.active_spinner.update(single_message or message)

    def _emit_project_timing(
        self,
        *,
        project: str,
        total_ms: float,
        status: str,
        steps: dict[str, float],
        error: str | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "run_id": self.state.run_id,
            "project": project,
            "total_ms": total_ms,
            "status": status,
            "steps": steps,
        }
        if error is not None:
            payload["error"] = error
        self.rt._emit("resume.restore.project_timing", **payload)  # type: ignore[attr-defined]


def _round_ms(value_seconds: float) -> float:
    return round(value_seconds * 1000.0, 2)
