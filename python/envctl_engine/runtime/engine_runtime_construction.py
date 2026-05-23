from __future__ import annotations

import threading
from typing import Any, cast
import uuid

from envctl_engine.actions.action_command_orchestrator import ActionCommandOrchestrator
from envctl_engine.config import EngineConfig
from envctl_engine.debug.doctor_orchestrator import DoctorOrchestrator
from envctl_engine.requirements.orchestrator import RequirementsOrchestrator
from envctl_engine.runtime.lifecycle_cleanup_orchestrator import LifecycleCleanupOrchestrator
from envctl_engine.runtime.runtime_context import RuntimeContext
from envctl_engine.runtime.service_manager import ServiceManager
from envctl_engine.shared.parsing import parse_bool
from envctl_engine.shared.ports import PortPlanner
from envctl_engine.shared.process_probe import ProcessProbe
from envctl_engine.shared.process_runner import ProcessRunner
from envctl_engine.startup.resume_orchestrator import ResumeOrchestrator
from envctl_engine.startup.startup_orchestrator import StartupOrchestrator
from envctl_engine.state.action_orchestrator import StateActionOrchestrator
from envctl_engine.state.repository import RuntimeStateRepository
from envctl_engine.ui.backend import build_interactive_backend
from envctl_engine.ui.backend_resolver import resolve_ui_backend
from envctl_engine.ui.dashboard.orchestrator import DashboardOrchestrator
from envctl_engine.ui.dashboard.terminal_ui import RuntimeTerminalUI


def initialize_runtime_construction(runtime: Any, config: EngineConfig, *, env: dict[str, str] | None = None) -> None:
    runtime.config = config
    runtime.env = dict(env or {})
    runtime.runtime_legacy_root = config.runtime_dir / "python-engine"
    runtime.runtime_root = config.runtime_scope_dir
    runtime.runtime_legacy_root.mkdir(parents=True, exist_ok=True)
    runtime.runtime_root.mkdir(parents=True, exist_ok=True)
    runtime._ensure_legacy_lock_view()
    runtime.port_planner = PortPlanner(
        backend_base=config.backend_port_base,
        frontend_base=config.frontend_port_base,
        spacing=config.port_spacing,
        db_base=config.db_port_base,
        redis_base=config.redis_port_base,
        n8n_base=config.n8n_port_base,
        supabase_api_base=config.port_defaults.dependency_port("supabase", "api"),
        additional_service_bases={
            service.name: int(service.port_base)
            for service in getattr(config, "additional_services", ())
            if getattr(service, "port_base", None)
        },
        lock_dir=str(runtime.runtime_root / "locks"),
        event_handler=runtime._on_port_event,
        availability_mode=config.port_availability_mode,
        preferred_port_strategy=runtime.env.get(
            "ENVCTL_PORT_PREFERRED_STRATEGY",
            config.raw.get("ENVCTL_PORT_PREFERRED_STRATEGY", "project_slot"),
        ),
        scope_key=config.runtime_scope_id,
        dynamic_main_dependency_ports=parse_bool(
            runtime.env.get("ENVCTL_DYNAMIC_MAIN_DEPENDENCY_PORTS")
            or config.raw.get("ENVCTL_DYNAMIC_MAIN_DEPENDENCY_PORTS"),
            config.db_port_base == 5432 and config.redis_port_base == 6379,
        ),
    )
    runtime.requirements = RequirementsOrchestrator()
    runtime.services = ServiceManager()
    runtime.events = []
    runtime._emit_lock = threading.Lock()
    runtime._emit_listeners = []
    runtime._startup_warnings_lock = threading.Lock()
    runtime._startup_warnings_by_project = {}
    runtime._debug_hash_salt = uuid.uuid4().hex
    runtime._debug_recorder = None
    runtime._active_command_id = None
    runtime._last_debug_bundle_path = None
    runtime.process_runner = ProcessRunner(emit=runtime._emit)
    probe_backend_name = "psutil" if runtime._probe_psutil_enabled() else "shell"
    probe_backend = runtime._build_process_probe_backend()
    runtime.process_probe = ProcessProbe(probe_backend)
    runtime._emit("probe.backend", backend=probe_backend_name)
    runtime.terminal_ui = RuntimeTerminalUI()
    runtime._dashboard_truth_cache_run_id = None
    runtime._dashboard_truth_cache_expires_at = 0.0
    runtime._dashboard_truth_cache_missing_services = []
    runtime._listener_probe_supported = runtime._probe_listener_support()
    runtime._conflict_remaining = {
        "postgres": runtime._conflict_count("POSTGRES"),
        "redis": runtime._conflict_count("REDIS"),
        "supabase": runtime._conflict_count("SUPABASE"),
        "n8n": runtime._conflict_count("N8N"),
        "backend": runtime._conflict_count("BACKEND"),
        "frontend": runtime._conflict_count("FRONTEND"),
    }
    runtime.state_repository = RuntimeStateRepository(
        runtime_root=runtime.runtime_root,
        runtime_legacy_root=runtime.runtime_legacy_root,
        runtime_dir=runtime.config.runtime_dir,
        runtime_scope_id=runtime.config.runtime_scope_id,
        compat_mode=runtime._state_compat_mode(),
    )
    runtime.runtime_context = RuntimeContext(
        config=runtime.config,
        env=runtime.env,
        process_runtime=cast(Any, runtime.process_runner),
        port_allocator=cast(Any, runtime.port_planner),
        state_repository=cast(Any, runtime.state_repository),
        terminal_ui=runtime.terminal_ui,
        emit=runtime._emit,
    )
    runtime.planning_worktree_orchestrator = PlanningWorktreeOrchestrator(runtime)
    runtime.startup_orchestrator = StartupOrchestrator(runtime)
    runtime.resume_orchestrator = ResumeOrchestrator(runtime)
    runtime.doctor_orchestrator = DoctorOrchestrator(runtime)
    runtime.lifecycle_cleanup_orchestrator = LifecycleCleanupOrchestrator(runtime)
    runtime.dashboard_orchestrator = DashboardOrchestrator(runtime)
    runtime.state_action_orchestrator = StateActionOrchestrator(runtime)
    runtime.action_command_orchestrator = ActionCommandOrchestrator(runtime)
    runtime.ui_backend_resolution = resolve_ui_backend(runtime.env)
    runtime.ui_backend = build_interactive_backend(runtime.ui_backend_resolution)
    runtime._emit(
        "ui.backend.selected",
        backend=runtime.ui_backend_resolution.backend,
        requested_mode=runtime.ui_backend_resolution.requested_mode,
        interactive=runtime.ui_backend_resolution.interactive,
        reason=runtime.ui_backend_resolution.reason,
    )
    if not runtime.ui_backend_resolution.interactive:
        runtime._emit(
            "ui.fallback.non_interactive",
            reason=runtime.ui_backend_resolution.reason,
            backend=runtime.ui_backend_resolution.backend,
        )


from envctl_engine.planning.worktree_orchestrator import PlanningWorktreeOrchestrator  # noqa: E402
