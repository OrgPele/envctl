from __future__ import annotations

from typing import Any

from .command_policy import dispatch_family_for_command
from envctl_engine.runtime.inspection_support import dispatch_direct_inspection
from envctl_engine.runtime.utility_command_support import dispatch_utility_command


def dispatch_command(runtime: Any, route: object) -> int:
    command = str(getattr(route, "command", "")).strip()
    family = dispatch_family_for_command(command)
    if family == "help":
        runtime._print_help()
        return 0
    if family == "direct_inspection":
        return dispatch_direct_inspection(runtime, route)
    if family == "utility":
        return dispatch_utility_command(runtime, route)
    if command == "debug-pack":
        return runtime._debug_pack(route)
    if command == "debug-last":
        return runtime._debug_last(route)
    if command == "debug-report":
        return runtime._debug_report(route)
    if family == "lifecycle_cleanup":
        return runtime.lifecycle_cleanup_orchestrator.execute(route)
    if family == "resume":
        return runtime.resume_orchestrator.execute(route)
    if family == "doctor":
        if bool(getattr(route, "flags", {}).get("json")):
            return runtime.doctor_orchestrator.execute(json_output=True)
        return runtime.doctor_orchestrator.execute()
    if family == "dashboard":
        return runtime.dashboard_orchestrator.execute(route)
    if family == "config":
        return runtime._config(route)
    if family == "migrate_hooks":
        return runtime._migrate_hooks(route)
    if family == "state_action":
        return runtime.state_action_orchestrator.execute(route)
    if family == "action":
        return runtime.action_command_orchestrator.execute(route)
    if family == "startup":
        return runtime.startup_orchestrator.execute(route)
    return runtime._unsupported_command(command)
