from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from envctl_engine.startup.run_reuse_support import (
    build_startup_identity_metadata as build_startup_identity_metadata_impl,
    evaluate_run_reuse as evaluate_run_reuse_impl,
    mark_run_reused as mark_run_reused_impl,
    state_has_resumable_services as state_has_resumable_services_impl,
)
from envctl_engine.state.models import PortPlan, RunState
from envctl_engine.shared.parsing import parse_bool, parse_int
from envctl_engine.planning import discover_tree_projects


def effective_start_mode(runtime: Any, route: object) -> str:
    if route.mode == "main" and runtime._setup_worktree_requested(route):
        return "trees"
    return route.mode


def auto_resume_start_enabled(route: object) -> bool:
    if route.command not in {"start", "plan"}:
        return False
    if bool(route.flags.get("no_resume")):
        return False
    if bool(route.flags.get("planning_prs")):
        return False
    if bool(route.flags.get("setup_worktree")) or bool(route.flags.get("setup_worktrees")):
        return False
    return True


def build_startup_identity_metadata(
    runtime: Any,
    *,
    runtime_mode: str,
    project_contexts: list[object],
    base_metadata: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return build_startup_identity_metadata_impl(
        runtime,
        runtime_mode=runtime_mode,
        project_contexts=project_contexts,
        base_metadata=base_metadata,
    )


def evaluate_run_reuse(runtime: Any, *, runtime_mode: str, route: object, contexts: list[object]) -> object:
    return evaluate_run_reuse_impl(runtime, runtime_mode=runtime_mode, route=route, contexts=contexts)


def mark_run_reused(metadata: Mapping[str, object] | None, *, reason: str) -> dict[str, object]:
    return mark_run_reused_impl(metadata, reason=reason)


def state_has_resumable_services(runtime: Any, state: RunState) -> bool:
    return state_has_resumable_services_impl(runtime, state)


def load_auto_resume_state(runtime: Any, runtime_mode: str) -> RunState | None:
    state = runtime._try_load_existing_state(mode=runtime_mode, strict_mode_match=True)
    if state is None:
        return None
    if state.mode != runtime_mode:
        return None
    if bool(state.metadata.get("failed", False)):
        return None
    return state


def tree_parallel_startup_config(runtime: Any, *, mode: str, route: object, project_count: int) -> tuple[bool, int]:
    if mode != "trees" or project_count <= 1:
        return False, 1

    flag_value = route.flags.get("parallel_trees")
    if isinstance(flag_value, bool):
        enabled = flag_value
    else:
        if route.command == "plan":
            enabled = True
        else:
            raw_default = runtime.env.get("RUN_SH_OPT_PARALLEL_TREES") or runtime.config.raw.get(
                "RUN_SH_OPT_PARALLEL_TREES"
            )
            enabled = parse_bool(raw_default, True)
    if bool(route.flags.get("sequential")):
        enabled = False

    raw_workers = route.flags.get("parallel_trees_max")
    if raw_workers is None:
        raw_workers = runtime.env.get("RUN_SH_OPT_PARALLEL_TREES_MAX") or runtime.config.raw.get(
            "RUN_SH_OPT_PARALLEL_TREES_MAX"
        )
    max_workers = parse_int(str(raw_workers) if raw_workers is not None else None, 4)
    max_workers = max(1, max_workers)
    workers = min(max_workers, project_count)
    if not enabled:
        return False, 1
    return workers > 1, workers


def contexts_from_raw_projects(
    runtime: Any,
    raw_projects: list[tuple[str, Path]],
    *,
    context_factory: Callable[..., object],
) -> list[object]:
    contexts: list[object] = []
    for index, (name, tree_dir) in enumerate(raw_projects):
        plans = runtime.port_planner.plan_project_stack(name, index=index)
        contexts.append(context_factory(name=name, root=tree_dir, ports=plans))
    return contexts


def duplicate_project_context_error(contexts: list[object]) -> str | None:
    grouped: dict[str, list[str]] = {}
    for context in contexts:
        grouped.setdefault(context.name.lower(), []).append(str(context.root))
    duplicates = {name: roots for name, roots in grouped.items() if len(roots) > 1}
    if not duplicates:
        return None
    parts = []
    for name in sorted(duplicates):
        roots = ", ".join(sorted(duplicates[name]))
        parts.append(f"{name}: {roots}")
    return "Duplicate project identities detected; rename conflicting worktrees: " + " | ".join(parts)


def sanitize_legacy_resume_state(runtime: Any, state: RunState) -> None:
    sanitized = 0
    for service in state.services.values():
        pid = getattr(service, "pid", None)
        if isinstance(pid, int) and pid > 0 and hasattr(service, "pid"):
            setattr(service, "pid", None)
            sanitized += 1
        if hasattr(service, "listener_pids"):
            setattr(service, "listener_pids", None)
    state.metadata["legacy_pids_sanitized"] = True
    runtime._emit(
        "resume.legacy_state.sanitized",
        run_id=state.run_id,
        service_count=len(state.services),
        sanitized_pids=sanitized,
    )


def set_plan_port(plan: PortPlan, port: int) -> None:
    plan.requested = port
    plan.assigned = port
    plan.final = port
    plan.source = "resume"


def set_plan_port_from_component(plan: PortPlan, component: Mapping[str, object]) -> None:
    port = component.get("final")
    if not isinstance(port, int) or port <= 0:
        port = component.get("requested")
    if isinstance(port, int) and port > 0:
        set_plan_port(plan, port)


def discover_projects(runtime: Any, *, mode: str, context_factory: Callable[..., object]) -> list[object]:
    if mode == "main":
        ports = runtime.port_planner.plan_project_stack("Main", index=0)
        return [context_factory(name="Main", root=runtime.config.base_dir, ports=ports)]

    contexts: list[object] = []
    projects = discover_tree_projects(runtime.config.base_dir, runtime.config.trees_dir_name)
    for index, (name, tree_dir) in enumerate(projects):
        plans = runtime.port_planner.plan_project_stack(name, index=index)
        contexts.append(context_factory(name=name, root=tree_dir, ports=plans))
    runtime._emit(
        "planning.projects.discovered",
        mode=mode,
        count=len(contexts),
        projects=[context.name for context in contexts],
    )
    return contexts


def reserve_project_ports(runtime: Any, context: object) -> None:
    for service_name, plan in context.ports.items():
        owner = f"{context.name}:{service_name}"
        try:
            reserved = runtime.port_planner.reserve_next(plan.assigned, owner=owner)
        except RuntimeError as exc:
            runtime._emit(
                "port.reservation.failed",
                project=context.name,
                service=service_name,
                start_port=plan.assigned,
                max_port=runtime.port_planner.max_port,
                availability_mode=runtime.port_planner.availability_mode,
                lock_inventory=runtime._lock_inventory(),
                error=str(exc),
            )
            raise
        if reserved != plan.final:
            runtime.port_planner.update_final_port(plan, reserved, source="retry")
            runtime._emit("port.rebound", project=context.name, service=service_name, port=reserved)
        else:
            plan.assigned = reserved
            plan.final = reserved
        runtime._emit("port.reserved", project=context.name, service=service_name, port=reserved)
