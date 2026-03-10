from __future__ import annotations

import concurrent.futures
from contextlib import nullcontext
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Protocol, cast

from envctl_engine.runtime.command_router import Route
from envctl_engine.requirements.core import dependency_definitions
from envctl_engine.shared.parsing import parse_bool
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord
from envctl_engine.startup.resume_progress import ResumeProjectSpinnerGroup as _ResumeProjectSpinnerGroup
from envctl_engine.ui.spinner import spinner, spinner_enabled, use_spinner_policy
from envctl_engine.ui.spinner_service import emit_spinner_policy, resolve_spinner_policy


class _StateRepositoryProtocol(Protocol):
    def save_resume_state(
        self,
        *,
        state: RunState,
        emit: Callable[..., None],
        runtime_map_builder: Callable[[RunState], dict[str, object]],
    ) -> dict[str, object]: ...


class _PortAllocatorProtocol(Protocol):
    def reserve_next(self, _preferred: int, *, _owner: str) -> int: ...
    def update_final_port(self, _plan: object, _final_port: int, *, _source: str) -> None: ...
    def release(self, _port: int) -> None: ...


def restore_missing(
    orchestrator,
    state: RunState,
    missing_services: list[str],
    *,
    route: Route | None = None,
    spinner_factory: Callable[..., object] = spinner,
    spinner_enabled_fn: Callable[[Mapping[str, str] | None], bool] = spinner_enabled,
    use_spinner_policy_fn: Callable[[object], object] = use_spinner_policy,
    emit_spinner_policy_fn: Callable[..., None] = emit_spinner_policy,
    resolve_spinner_policy_fn: Callable[[Mapping[str, str] | None], object] = resolve_spinner_policy,
    project_spinner_group_cls: type[_ResumeProjectSpinnerGroup] = _ResumeProjectSpinnerGroup,
) -> list[str]:
    rt = orchestrator.runtime
    port_allocator = _port_allocator(rt)
    projects_to_restore: set[str] = set()
    for service_name in missing_services:
        project = rt._project_name_from_service(service_name)  # type: ignore[attr-defined]
        if project:
            projects_to_restore.add(project)
    for project, requirements in state.requirements.items():
        if not rt._requirements_ready(requirements):  # type: ignore[attr-defined]
            projects_to_restore.add(project)

    if not projects_to_restore:
        return []

    errors: list[str] = []
    timing_enabled = _restore_timing_enabled(orchestrator, route)
    total_started = time.monotonic()
    project_totals_ms: dict[str, float] = {}
    timing_lines: list[str] = []
    sorted_projects = sorted(projects_to_restore)
    total_projects = len(sorted_projects)
    spinner_policy = resolve_spinner_policy_fn(getattr(rt, "env", {}))
    emit_spinner_policy_fn(
        getattr(rt, "_emit", None),
        spinner_policy,
        context={"component": "resume.restore", "op_id": "resume.restore"},
    )
    use_spinner = spinner_enabled_fn(getattr(rt, "env", {}))
    parallel_enabled, parallel_workers = _restore_parallel_config(
        orchestrator,
        route=route,
        mode=state.mode,
        project_count=total_projects,
    )
    rt._emit(  # type: ignore[attr-defined]
        "resume.restore.execution",
        mode="parallel" if parallel_enabled else "sequential",
        workers=parallel_workers,
        projects=sorted_projects,
    )
    use_project_spinner_group = (
        use_spinner
        and total_projects > 1
        and bool(getattr(spinner_policy, "enabled", False))
        and str(getattr(spinner_policy, "backend", "")) == "rich"
    )
    project_spinner_group = project_spinner_group_cls(
        projects=sorted_projects,
        enabled=use_project_spinner_group,
        policy=spinner_policy,
        emit=getattr(rt, "_emit", None),
        env=getattr(rt, "env", {}),
    )
    initial_message = f"Preparing stale restore for {total_projects} project(s)..."
    use_single_spinner = use_spinner and not use_project_spinner_group
    suppress_timing_output = use_project_spinner_group or use_single_spinner
    route_for_startup = route
    if route_for_startup is None:
        route_for_startup = Route(
            command="resume",
            mode=state.mode,
            raw_args=[],
            passthrough_args=[],
            projects=[],
            flags={},
        )
    if suppress_timing_output:
        route_for_startup = Route(
            command=route_for_startup.command,
            mode=route_for_startup.mode,
            raw_args=route_for_startup.raw_args,
            passthrough_args=route_for_startup.passthrough_args,
            projects=route_for_startup.projects,
            flags={
                **route_for_startup.flags,
                "_suppress_timing_print": True,
                "_resume_restore": True,
            },
        )
    else:
        route_for_startup = Route(
            command=route_for_startup.command,
            mode=route_for_startup.mode,
            raw_args=route_for_startup.raw_args,
            passthrough_args=route_for_startup.passthrough_args,
            projects=route_for_startup.projects,
            flags={
                **route_for_startup.flags,
                "_resume_restore": True,
            },
        )
    if use_single_spinner:
        rt._emit(  # type: ignore[attr-defined]
            "ui.spinner.lifecycle",
            component="resume.restore",
            op_id="resume.restore",
            state="start",
            message=initial_message,
        )
    group_context = project_spinner_group if use_project_spinner_group else nullcontext(project_spinner_group)

    def restore_project(index: int, project: str) -> dict[str, object]:
        project_started = time.monotonic()
        step_durations_ms: dict[str, float] = {}
        prefix = f"[{index}/{total_projects}]"
        project_route_for_startup = route_for_startup
        message = f"{prefix} Restoring stale services..."
        if use_project_spinner_group:
            project_spinner_group.update_project(project, message)
        elif use_single_spinner:
            active_spinner.update(message)
            rt._emit(  # type: ignore[attr-defined]
                "ui.spinner.lifecycle",
                component="resume.restore",
                op_id="resume.restore",
                state="update",
                message=message,
            )
        else:
            print(message)

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
            rt._emit(  # type: ignore[attr-defined]
                "resume.restore.step",
                run_id=state.run_id,
                project=project,
                step=step,
                status=status,
                duration_ms=duration_ms,
                **extra,
            )

        if use_project_spinner_group:
            project_spinner_group.update_project(project, f"{prefix} Resolving runtime context...")
        elif use_single_spinner:
            active_spinner.update(f"{prefix} Resolving runtime context for {project}...")
        context_started = time.monotonic()
        context = rt._resume_context_for_project(state, project)  # type: ignore[attr-defined]
        if context is None:
            mark_step(
                "resolve_context",
                status="error",
                duration_ms=_round_ms(time.monotonic() - context_started),
                context_found=False,
            )
            if use_project_spinner_group:
                project_spinner_group.mark_failure(project, f"{prefix} Context not found")
            elif use_single_spinner:
                active_spinner.update(f"{prefix} Context not found for {project}")
            project_total = _round_ms(time.monotonic() - project_started)
            rt._emit(  # type: ignore[attr-defined]
                "resume.restore.project_timing",
                run_id=state.run_id,
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
            for name in list(state.services.keys())
            if rt._project_name_from_service(name).lower() == project.lower()  # type: ignore[attr-defined]
        ]
        original_services: dict[str, ServiceRecord] = {
            name: state.services[name] for name in project_service_names if name in state.services
        }
        original_requirements = state.requirements.get(project)
        context_root = getattr(context, "root", None)
        requirements_reused, requirements_reuse_reason = _requirements_reuse_decision(
            orchestrator,
            rt,
            project=project,
            requirements=original_requirements,
            project_root=context_root if isinstance(context_root, Path) else None,
        )
        requirements_for_services = original_requirements if requirements_reused else None
        rt._emit(  # type: ignore[attr-defined]
            "resume.restore.requirements_reuse",
            run_id=state.run_id,
            project=project,
            reused=requirements_reused,
            reason=requirements_reuse_reason,
        )
        if use_project_spinner_group:
            project_spinner_group.update_project(project, f"{prefix} Stopping stale services...")
        elif use_single_spinner:
            active_spinner.update(f"{prefix} Stopping stale services for {project}...")
        stop_started = time.monotonic()
        terminated_count = 0
        aggressive_terminate = _resume_terminate_aggressive(orchestrator, rt)
        for service in original_services.values():
            terminated = rt._terminate_service_record(  # type: ignore[attr-defined]
                service,
                aggressive=aggressive_terminate,
                verify_ownership=True,
            )
            if terminated:
                terminated_count += 1
                port = rt._service_port(service)  # type: ignore[attr-defined]
                if port is not None:
                    port_allocator.release(port)  # type: ignore[attr-defined]
        mark_step(
            "stop_stale_services",
            duration_ms=_round_ms(time.monotonic() - stop_started),
            stale_service_count=len(project_service_names),
            terminated_count=terminated_count,
            aggressive=aggressive_terminate,
        )

        existing_requirements = original_requirements
        if existing_requirements is not None and not requirements_reused:
            if use_project_spinner_group:
                project_spinner_group.update_project(
                    project,
                    f"{prefix} Releasing previous requirement ports...",
                )
            elif use_single_spinner:
                active_spinner.update(f"{prefix} Releasing previous requirement ports for {project}...")
            release_started = time.monotonic()
            rt._release_requirement_ports(existing_requirements)  # type: ignore[attr-defined]
            mark_step(
                "release_requirement_ports",
                duration_ms=_round_ms(time.monotonic() - release_started),
            )

        try:
            if use_project_spinner_group:
                project_spinner_group.update_project(project, f"{prefix} Reserving service ports...")
            elif use_single_spinner:
                active_spinner.update(f"{prefix} Reserving service ports for {project}...")
            reserve_started = time.monotonic()
            if requirements_reused:
                _reserve_application_service_ports(orchestrator, rt, context, port_allocator)
            else:
                rt._reserve_project_ports(context)  # type: ignore[attr-defined]
            mark_step(
                "reserve_ports",
                duration_ms=_round_ms(time.monotonic() - reserve_started),
            )

            if requirements_reused and requirements_for_services is not None:
                requirements = requirements_for_services
                mark_step("start_requirements", duration_ms=0.0, status="reused")
            else:
                if use_project_spinner_group:
                    project_route_for_startup = Route(
                        command=route_for_startup.command,
                        mode=route_for_startup.mode,
                        raw_args=route_for_startup.raw_args,
                        passthrough_args=route_for_startup.passthrough_args,
                        projects=route_for_startup.projects,
                        flags={
                            **route_for_startup.flags,
                            "_spinner_update_project": (
                                lambda _project, message, *, _project_name=project: (
                                    project_spinner_group.update_project(
                                        _project_name,
                                        f"{prefix} {message}",
                                    )
                                )
                            ),
                        },
                    )
                elif use_single_spinner:
                    project_route_for_startup = Route(
                        command=route_for_startup.command,
                        mode=route_for_startup.mode,
                        raw_args=route_for_startup.raw_args,
                        passthrough_args=route_for_startup.passthrough_args,
                        projects=route_for_startup.projects,
                        flags={
                            **route_for_startup.flags,
                            "_spinner_update": (lambda message: active_spinner.update(f"{prefix} {message}")),
                        },
                    )
                requirements_started = time.monotonic()
                requirements = rt._start_requirements_for_project(
                    context, mode=state.mode, route=project_route_for_startup
                )  # type: ignore[attr-defined]
                mark_step(
                    "start_requirements",
                    duration_ms=_round_ms(time.monotonic() - requirements_started),
                )
                if not rt._requirements_ready(requirements):  # type: ignore[attr-defined]
                    error_message = "requirements unavailable: " + (
                        ", ".join(requirements.failures) or "unknown requirements failure"
                    )
                    if use_project_spinner_group:
                        project_spinner_group.mark_failure(project, f"{prefix} Requirements unavailable")
                    elif use_single_spinner:
                        active_spinner.update(f"{prefix} Requirements unavailable for {project}")
                    project_total = _round_ms(time.monotonic() - project_started)
                    rt._emit(  # type: ignore[attr-defined]
                        "resume.restore.project_timing",
                        run_id=state.run_id,
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

            if use_project_spinner_group:
                project_spinner_group.update_project(project, f"{prefix} Starting app services...")
            elif use_single_spinner:
                active_spinner.update(f"{prefix} Starting app services for {project}...")
            services_started = time.monotonic()
            project_services = rt._start_project_services(  # type: ignore[attr-defined]
                context,
                requirements=requirements,
                run_id=state.run_id,
                route=project_route_for_startup,
            )
            mark_step(
                "start_services",
                duration_ms=_round_ms(time.monotonic() - services_started),
                restored_service_count=len(project_services),
            )
            if use_project_spinner_group:
                project_spinner_group.mark_success(project, f"{prefix} restored")
            elif use_single_spinner:
                active_spinner.update(f"{prefix} {project} restored")
            project_total = _round_ms(time.monotonic() - project_started)
            rt._emit(  # type: ignore[attr-defined]
                "resume.restore.project_timing",
                run_id=state.run_id,
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
                "remove_service_names": project_service_names,
            }
        except RuntimeError as exc:
            mark_step("exception", status="error", error=str(exc))
            if use_project_spinner_group:
                project_spinner_group.mark_failure(project, f"{prefix} Restore failed: {exc}")
            elif use_single_spinner:
                active_spinner.update(f"{prefix} Restore failed for {project}: {exc}")
            project_total = _round_ms(time.monotonic() - project_started)
            rt._emit(  # type: ignore[attr-defined]
                "resume.restore.project_timing",
                run_id=state.run_id,
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

    with (
        use_spinner_policy_fn(spinner_policy),
        spinner_factory(
            initial_message,
            enabled=use_single_spinner,
        ) as active_spinner,
    ):
        with group_context:
            project_results: dict[str, dict[str, object]] = {}
            if parallel_enabled:
                with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_workers) as executor:
                    future_map = {
                        executor.submit(restore_project, index, project): project
                        for index, project in enumerate(sorted_projects, start=1)
                    }
                    for future in concurrent.futures.as_completed(future_map):
                        project_name = future_map[future]
                        try:
                            project_results[project_name] = future.result()
                        except Exception as exc:  # noqa: BLE001
                            project_results[project_name] = {
                                "project": project_name,
                                "error": str(exc),
                                "steps": {"exception": 0.0},
                                "total_ms": 0.0,
                            }
            else:
                for index, project in enumerate(sorted_projects, start=1):
                    project_results[project] = restore_project(index, project)

            for project in sorted_projects:
                result = project_results.get(project) or {}
                project_total = float(result.get("total_ms", 0.0))
                project_totals_ms[project] = project_total
                steps = result.get("steps")
                step_map = steps if isinstance(steps, dict) else {}
                if timing_enabled:
                    timing_lines.append(_format_project_timing_line(project, step_map, project_total))

                error_message = str(result.get("error") or "").strip()
                if error_message:
                    _mark_restore_failure_requirements(state, project=project, error=error_message)
                    errors.append(f"{project}: {error_message}")
                    continue

                remove_names_raw = result.get("remove_service_names")
                if isinstance(remove_names_raw, list):
                    for service_name in remove_names_raw:
                        if isinstance(service_name, str):
                            state.services.pop(service_name, None)
                project_services_raw = result.get("project_services")
                if isinstance(project_services_raw, dict):
                    for service_name, record in project_services_raw.items():
                        if isinstance(service_name, str) and isinstance(record, ServiceRecord):
                            state.services[service_name] = record
                requirements_result = result.get("requirements")
                if isinstance(requirements_result, RequirementsResult):
                    state.requirements[project] = requirements_result

        if use_single_spinner:
            if errors:
                active_spinner.fail(f"stale restore failed for {len(errors)} project(s)")
                rt._emit(  # type: ignore[attr-defined]
                    "ui.spinner.lifecycle",
                    component="resume.restore",
                    op_id="resume.restore",
                    state="fail",
                    message=f"stale restore failed for {len(errors)} project(s)",
                )
            else:
                active_spinner.succeed("stale services restored")
                rt._emit(  # type: ignore[attr-defined]
                    "ui.spinner.lifecycle",
                    component="resume.restore",
                    op_id="resume.restore",
                    state="success",
                    message="stale services restored",
                )
    if use_single_spinner:
        rt._emit("ui.spinner.lifecycle", component="resume.restore", op_id="resume.restore", state="stop")  # type: ignore[attr-defined]
    total_ms = _round_ms(time.monotonic() - total_started)
    slowest_project = ""
    slowest_ms = 0.0
    if project_totals_ms:
        slowest_project, slowest_ms = max(project_totals_ms.items(), key=lambda item: item[1])
    rt._emit(  # type: ignore[attr-defined]
        "resume.restore.timing",
        run_id=state.run_id,
        total_ms=total_ms,
        project_count=total_projects,
        errored_count=len(errors),
        slowest_project=slowest_project,
        slowest_ms=slowest_ms,
    )
    if timing_enabled and timing_lines and not suppress_timing_output:
        print("Restore timing summary:")
        for line in timing_lines:
            print(line)
        print(
            f"Total restore time: {total_ms:.1f} ms"
            + (f" (slowest: {slowest_project} {slowest_ms:.1f} ms)" if slowest_project else "")
        )
    return errors


def _mark_restore_failure_requirements(state: RunState, *, project: str, error: str) -> None:
    existing = state.requirements.get(project)
    if not isinstance(existing, RequirementsResult):
        return
    existing.health = "degraded"
    existing.failures = [str(error).strip() or "resume restore failed"]
    for component in existing.components.values():
        if not isinstance(component, dict):
            continue
        if bool(component.get("enabled", False)):
            component["runtime_status"] = "unreachable"


def _round_ms(value_seconds: float) -> float:
    return round(value_seconds * 1000.0, 2)


def _format_project_timing_line(project: str, steps: Mapping[str, float], total_ms: float) -> str:
    ordered_steps = (
        "resolve_context",
        "stop_stale_services",
        "release_requirement_ports",
        "reserve_ports",
        "start_requirements",
        "start_services",
        "exception",
    )
    parts: list[str] = [f"{project}"]
    for step in ordered_steps:
        duration = steps.get(step)
        if duration is None:
            continue
        parts.append(f"{step}={duration:.1f}ms")
    parts.append(f"total={total_ms:.1f}ms")
    return "  - " + " ".join(parts)


def _restore_parallel_config(
    orchestrator,
    *,
    route: Route | None,
    mode: str,
    project_count: int,
) -> tuple[bool, int]:
    rt = orchestrator.runtime
    if route is None:
        route = Route(
            command="resume",
            mode=mode,
            raw_args=[],
            passthrough_args=[],
            projects=[],
            flags={},
        )
    source_command = str(route.flags.get("_resume_source_command") or route.command).strip().lower()
    if (
        source_command == "plan"
        and route.flags.get("parallel_trees") is None
        and not bool(route.flags.get("sequential"))
    ):
        route = Route(
            command=route.command,
            mode=route.mode,
            raw_args=route.raw_args,
            passthrough_args=route.passthrough_args,
            projects=route.projects,
            flags={
                **route.flags,
                "parallel_trees": True,
            },
        )
    return rt._tree_parallel_startup_config(mode=mode, route=route, project_count=project_count)  # type: ignore[attr-defined]


def _restore_timing_enabled(orchestrator, route: Route | None) -> bool:
    rt = orchestrator.runtime
    raw_force = rt.env.get("ENVCTL_DEBUG_RESTORE_TIMING") or rt.config.raw.get("ENVCTL_DEBUG_RESTORE_TIMING")  # type: ignore[attr-defined]
    if parse_bool(raw_force, False):
        return True
    if route is not None:
        if bool(route.flags.get("debug_ui")) or bool(route.flags.get("debug_ui_deep")):
            return True
    raw_mode = (rt.env.get("ENVCTL_DEBUG_UI_MODE") or rt.config.raw.get("ENVCTL_DEBUG_UI_MODE") or "").strip().lower()  # type: ignore[attr-defined]
    return raw_mode in {"standard", "deep"}


def _requirements_reuse_decision(
    orchestrator,
    rt: Any,
    *,
    project: str,
    requirements: RequirementsResult | None,
    project_root: Path | None = None,
) -> tuple[bool, str]:
    if requirements is None:
        return False, "bootstrap_cache_miss"
    if not rt._requirements_ready(requirements):  # type: ignore[attr-defined]
        return False, "dependency_endpoint_changed"
    reconcile = getattr(rt, "_reconcile_project_requirement_truth", None)
    if callable(reconcile):
        try:
            issues = reconcile(project, requirements, project_root=project_root)
        except Exception:
            return False, "dependency_endpoint_changed"
        return (not bool(issues), "service_stale_only" if not issues else "dependency_endpoint_changed")
    return True, "service_stale_only"


def _resume_terminate_aggressive(orchestrator, rt: Any) -> bool:
    raw = rt.env.get("ENVCTL_RESUME_AGGRESSIVE_TERMINATE") or rt.config.raw.get("ENVCTL_RESUME_AGGRESSIVE_TERMINATE")  # type: ignore[attr-defined]
    return parse_bool(raw, True)


def _reserve_application_service_ports(
    orchestrator,
    rt: Any,
    context: object,
    port_allocator: _PortAllocatorProtocol,
) -> None:
    context_name = str(getattr(context, "name", ""))
    ports = getattr(context, "ports", {})
    if not isinstance(ports, dict):
        return
    for service_name in ("backend", "frontend"):
        plan = ports.get(service_name)
        if plan is None:
            continue
        assigned = getattr(plan, "assigned", None)
        final = getattr(plan, "final", None)
        if not isinstance(assigned, int) or assigned <= 0:
            continue
        owner = f"{context_name}:{service_name}"
        reserved = port_allocator.reserve_next(assigned, owner=owner)
        if reserved != final:
            port_allocator.update_final_port(plan, reserved, source="retry")
            rt._emit("port.rebound", project=context_name, service=service_name, port=reserved)  # type: ignore[attr-defined]
        else:
            plan.assigned = reserved
            plan.final = reserved
        rt._emit("port.reserved", project=context_name, service=service_name, port=reserved)  # type: ignore[attr-defined]


def context_for_project(orchestrator, state: RunState, project: str) -> object | None:
    rt = orchestrator.runtime
    discovered = rt._discover_projects(mode=state.mode)  # type: ignore[attr-defined]
    for context in discovered:
        if context.name.lower() == project.lower():
            orchestrator.apply_ports_to_context(context, state)
            return context

    root = orchestrator.project_root(state, project)
    if root is None:
        return None
    contexts = rt._contexts_from_raw_projects([(project, root)])  # type: ignore[attr-defined]
    if not contexts:
        return None
    context = contexts[0]
    orchestrator.apply_ports_to_context(context, state)
    return context


def project_root(orchestrator, state: RunState, project: str) -> Path | None:
    rt = orchestrator.runtime
    metadata_roots = state.metadata.get("project_roots")
    if isinstance(metadata_roots, Mapping):
        root_value = metadata_roots.get(project)
        if isinstance(root_value, str) and root_value.strip():
            candidate = Path(root_value).expanduser()
            if not candidate.is_absolute():
                candidate = (rt.config.base_dir / candidate).resolve()  # type: ignore[attr-defined]
            if candidate.is_dir():
                return candidate

    if project == "Main":
        return rt.config.base_dir  # type: ignore[attr-defined]

    for service_name, service in state.services.items():
        if rt._project_name_from_service(service_name).lower() != project.lower():  # type: ignore[attr-defined]
            continue
        cwd_raw = getattr(service, "cwd", None)
        if not isinstance(cwd_raw, str) or not cwd_raw.strip():
            continue
        candidate = Path(cwd_raw).expanduser()
        if not candidate.is_absolute():
            candidate = (rt.config.base_dir / candidate).resolve()  # type: ignore[attr-defined]
        if candidate.name in {"backend", "frontend"}:
            candidate = candidate.parent
        if candidate.is_dir():
            return candidate

    return None


def apply_ports_to_context(orchestrator, context: object, state: RunState) -> None:
    rt = orchestrator.runtime
    project = str(getattr(context, "name", ""))
    context_ports = getattr(context, "ports", {})
    if not isinstance(context_ports, dict):
        return

    requirements = state.requirements.get(project)
    if requirements is not None:
        for definition in dependency_definitions():
            plan = context_ports.get(definition.resources[0].legacy_port_key)
            if plan is None:
                continue
            rt._set_plan_port_from_component(plan, requirements.component(definition.id))  # type: ignore[attr-defined]

    for service_name, service in state.services.items():
        if rt._project_name_from_service(service_name).lower() != project.lower():  # type: ignore[attr-defined]
            continue
        service_type = (getattr(service, "type", "") or "").strip().lower()
        port = getattr(service, "actual_port", None)
        if not isinstance(port, int) or port <= 0:
            port = getattr(service, "requested_port", None)
        if not isinstance(port, int) or port <= 0:
            continue
        if service_type == "backend":
            rt._set_plan_port(context_ports["backend"], port)  # type: ignore[attr-defined]
        elif service_type == "frontend":
            rt._set_plan_port(context_ports["frontend"], port)  # type: ignore[attr-defined]


def _state_repository(runtime: object) -> _StateRepositoryProtocol:
    runtime_context = getattr(runtime, "runtime_context", None)
    candidate = getattr(runtime_context, "state_repository", None)
    if candidate is None:
        candidate = getattr(runtime, "state_repository", None)
    if candidate is None:
        raise RuntimeError("state repository dependency is not configured")
    return cast(_StateRepositoryProtocol, candidate)


def _port_allocator(runtime: object) -> _PortAllocatorProtocol:
    runtime_context = getattr(runtime, "runtime_context", None)
    candidate = getattr(runtime_context, "port_allocator", None)
    if candidate is None:
        candidate = getattr(runtime, "port_planner", None)
    if candidate is None:
        raise RuntimeError("port allocator dependency is not configured")
    return cast(_PortAllocatorProtocol, candidate)
