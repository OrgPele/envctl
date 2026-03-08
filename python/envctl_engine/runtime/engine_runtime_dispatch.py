from __future__ import annotations

from typing import Any

from envctl_engine.runtime.command_router import list_supported_commands
from envctl_engine.runtime.inspection_support import dispatch_direct_inspection


def dispatch_command(runtime: Any, route: object) -> int:
    command = str(getattr(route, "command", "")).strip()
    if command == "help":
        runtime._print_help()
        return 0
    if command == "list-commands":
        return dispatch_direct_inspection(runtime, route)
    if command in {"list-targets", "list-trees", "show-config", "show-state", "explain-startup"}:
        return dispatch_direct_inspection(runtime, route)
    if command == "debug-pack":
        return runtime._debug_pack(route)
    if command == "debug-last":
        return runtime._debug_last(route)
    if command == "debug-report":
        return runtime._debug_report(route)
    if command in {"stop", "stop-all", "blast-all"}:
        return runtime.lifecycle_cleanup_orchestrator.execute(route)
    if command == "resume":
        return runtime.resume_orchestrator.execute(route)
    if command == "doctor":
        if bool(getattr(route, "flags", {}).get("json")):
            return runtime.doctor_orchestrator.execute(json_output=True)
        return runtime.doctor_orchestrator.execute()
    if command == "dashboard":
        return runtime.dashboard_orchestrator.execute(route)
    if command == "config":
        return runtime._config(route)
    if command in {"logs", "clear-logs", "health", "errors"}:
        return runtime.state_action_orchestrator.execute(route)
    if command in {"test", "delete-worktree", "blast-worktree", "pr", "commit", "analyze", "migrate"}:
        return runtime.action_command_orchestrator.execute(route)
    if command in {"restart", "plan", "start"}:
        return runtime.startup_orchestrator.execute(route)
    return runtime._unsupported_command(command)
