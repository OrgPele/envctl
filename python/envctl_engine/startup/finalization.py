from __future__ import annotations

from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.protocols import ProjectContextLike, StartupRuntime
from envctl_engine.startup.session import StartupSession
from envctl_engine.state.models import RunState


def build_success_run_state(runtime: StartupRuntime, session: StartupSession) -> RunState:
    return _build_run_state(runtime, session, failed=False)


def build_failure_run_state(runtime: StartupRuntime, session: StartupSession, error: str) -> RunState:
    run_state = _build_run_state(runtime, session, failed=True)
    run_state.metadata["failed"] = True
    run_state.metadata["failure_message"] = error
    return run_state


def build_planning_dashboard_state(
    runtime: StartupRuntime,
    *,
    route: Route,
    runtime_mode: str,
    run_id: str,
    project_contexts: list[ProjectContextLike],
    configured_service_types: list[str],
) -> RunState:
    run_state = RunState(
        run_id=run_id,
        mode=runtime_mode,
        services={},
        requirements={},
        pointers={},
        metadata={
            "command": route.command,
            "repo_scope_id": runtime.config.runtime_scope_id,
            "project_roots": {context.name: str(context.root) for context in project_contexts},
            "dashboard_configured_service_types": configured_service_types,
            "dashboard_hidden_commands": [
                "stop",
                "restart",
                "stop-all",
                "blast-all",
                "logs",
                "clear-logs",
                "health",
                "errors",
            ],
            "dashboard_runs_disabled": True,
            "dashboard_banner": (
                f"envctl runs are disabled for {runtime_mode}; planning and action commands remain available."
            ),
        },
    )
    run_state.pointers = _build_pointer_map(runtime, run_id)
    return run_state


def _build_run_state(runtime: StartupRuntime, session: StartupSession, *, failed: bool) -> RunState:
    run_state = RunState(
        run_id=session.run_id,
        mode=session.runtime_mode,
        services=session.merged_services,
        requirements=session.merged_requirements,
        pointers={},
        metadata={
            "command": session.effective_route.command,
            "repo_scope_id": runtime.config.runtime_scope_id,
            "project_roots": {context.name: str(context.root) for context in session.selected_contexts},
        },
    )
    if failed:
        run_state.metadata["failed"] = True
    run_state.pointers = _build_pointer_map(runtime, session.run_id)
    return run_state


def _build_pointer_map(runtime: StartupRuntime, run_id: str) -> dict[str, str]:
    run_dir = runtime._run_dir_path(run_id)
    return {
        "run_state": str(run_dir / "run_state.json"),
        "runtime_map": str(run_dir / "runtime_map.json"),
        "ports_manifest": str(run_dir / "ports_manifest.json"),
        "error_report": str(run_dir / "error_report.json"),
        "events": str(run_dir / "events.jsonl"),
        "runtime_readiness_report": str(run_dir / "runtime_readiness_report.json"),
    }
