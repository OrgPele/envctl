from __future__ import annotations

import concurrent.futures
from contextlib import nullcontext
from dataclasses import dataclass
import time
from typing import Callable, Mapping

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState
from envctl_engine.startup.resume_restore_project import ResumeProjectRestoreRunner, _round_ms
from envctl_engine.startup.resume_restore_results import apply_restore_result
from envctl_engine.startup.resume_restore_policy import (
    _port_allocator as _port_allocator,
    _restore_parallel_config as _restore_parallel_config,
    _restore_timing_enabled as _restore_timing_enabled,
)
from envctl_engine.startup.resume_progress import ResumeProjectSpinnerGroup as _ResumeProjectSpinnerGroup
from envctl_engine.ui.spinner import spinner, spinner_enabled, use_spinner_policy
from envctl_engine.ui.spinner_service import emit_spinner_policy, resolve_spinner_policy


@dataclass(frozen=True, slots=True)
class ResumeRestoreDependencies:
    spinner_factory: Callable[..., object] = spinner
    spinner_enabled_fn: Callable[[Mapping[str, str] | None], bool] = spinner_enabled
    use_spinner_policy_fn: Callable[[object], object] = use_spinner_policy
    emit_spinner_policy_fn: Callable[..., None] = emit_spinner_policy
    resolve_spinner_policy_fn: Callable[[Mapping[str, str] | None], object] = resolve_spinner_policy
    project_spinner_group_cls: type[_ResumeProjectSpinnerGroup] = _ResumeProjectSpinnerGroup


@dataclass(slots=True)
class ResumeRestoreRunner:
    orchestrator: object
    state: RunState
    missing_services: list[str]
    route: Route | None = None
    dependencies: ResumeRestoreDependencies = ResumeRestoreDependencies()

    def execute(self) -> list[str]:
        return _execute_restore_missing(
            self.orchestrator,
            self.state,
            self.missing_services,
            route=self.route,
            spinner_factory=self.dependencies.spinner_factory,
            spinner_enabled_fn=self.dependencies.spinner_enabled_fn,
            use_spinner_policy_fn=self.dependencies.use_spinner_policy_fn,
            emit_spinner_policy_fn=self.dependencies.emit_spinner_policy_fn,
            resolve_spinner_policy_fn=self.dependencies.resolve_spinner_policy_fn,
            project_spinner_group_cls=self.dependencies.project_spinner_group_cls,
        )

def _execute_restore_missing(
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
    sorted_projects = _projects_to_restore(rt, state=state, missing_services=missing_services)
    if not sorted_projects:
        return []

    errors: list[str] = []
    timing_enabled = _restore_timing_enabled(orchestrator, route)
    total_started = time.monotonic()
    project_totals_ms: dict[str, float] = {}
    timing_lines: list[str] = []
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
    route_for_startup = _route_for_resume_restore(route, state=state, suppress_timing_output=suppress_timing_output)
    if use_single_spinner:
        rt._emit(  # type: ignore[attr-defined]
            "ui.spinner.lifecycle",
            component="resume.restore",
            op_id="resume.restore",
            state="start",
            message=initial_message,
        )
    group_context = project_spinner_group if use_project_spinner_group else nullcontext(project_spinner_group)


    with (
        use_spinner_policy_fn(spinner_policy),
        spinner_factory(
            initial_message,
            enabled=use_single_spinner,
        ) as active_spinner,
    ):
        with group_context:
            project_restore_runner = ResumeProjectRestoreRunner(
                orchestrator=orchestrator,
                rt=rt,
                state=state,
                missing_services=missing_services,
                route_for_startup=route_for_startup,
                total_projects=total_projects,
                use_project_spinner_group=use_project_spinner_group,
                project_spinner_group=project_spinner_group,
                use_single_spinner=use_single_spinner,
                active_spinner=active_spinner,
                port_allocator=port_allocator,
            )
            project_results = _run_restore_jobs(
                sorted_projects=sorted_projects,
                parallel_enabled=parallel_enabled,
                parallel_workers=parallel_workers,
                restore_project=project_restore_runner.restore_project,
            )

            for project in sorted_projects:
                result = project_results.get(project) or {}
                apply_restore_result(
                    state,
                    project=project,
                    result=result,
                    errors=errors,
                    timing_enabled=timing_enabled,
                    timing_lines=timing_lines,
                    project_totals_ms=project_totals_ms,
                )

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


def _projects_to_restore(rt: object, *, state: RunState, missing_services: list[str]) -> list[str]:
    projects_to_restore: set[str] = set()
    for service_name in missing_services:
        project = rt._project_name_from_service(service_name)  # type: ignore[attr-defined]
        if project:
            projects_to_restore.add(project)
    for project, requirements in state.requirements.items():
        if not rt._requirements_ready(requirements):  # type: ignore[attr-defined]
            projects_to_restore.add(project)
    return sorted(projects_to_restore)


def _route_for_resume_restore(
    route: Route | None,
    *,
    state: RunState,
    suppress_timing_output: bool,
) -> Route:
    route_for_startup = route or Route(
        command="resume",
        mode=state.mode,
        raw_args=[],
        passthrough_args=[],
        projects=[],
        flags={},
    )
    flags: dict[str, object] = {
        **route_for_startup.flags,
        "_resume_restore": True,
    }
    if suppress_timing_output:
        flags["_suppress_timing_print"] = True
    return Route(
        command=route_for_startup.command,
        mode=route_for_startup.mode,
        raw_args=route_for_startup.raw_args,
        passthrough_args=route_for_startup.passthrough_args,
        projects=route_for_startup.projects,
        flags=flags,
    )


def _run_restore_jobs(
    *,
    sorted_projects: list[str],
    parallel_enabled: bool,
    parallel_workers: int,
    restore_project: Callable[[int, str], dict[str, object]],
) -> dict[str, dict[str, object]]:
    if not parallel_enabled:
        return {project: restore_project(index, project) for index, project in enumerate(sorted_projects, start=1)}

    project_results: dict[str, dict[str, object]] = {}
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
    return project_results
