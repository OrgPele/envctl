from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, cast

from envctl_engine.config import EngineConfig
from envctl_engine.shared.protocols import PortAllocator, ProcessRuntime, StateRepository, TerminalUI


@dataclass(slots=True)
class RuntimeContext:
    config: EngineConfig
    env: dict[str, str]
    process_runtime: ProcessRuntime
    port_allocator: PortAllocator
    state_repository: StateRepository
    terminal_ui: TerminalUI
    emit: Callable[..., None]


def resolve_state_repository(runtime: object) -> StateRepository:
    runtime_context = getattr(runtime, "runtime_context", None)
    candidate = getattr(runtime_context, "state_repository", None)
    if candidate is None:
        candidate = getattr(runtime, "state_repository", None)
    if candidate is None:
        raise RuntimeError("state repository dependency is not configured")
    return cast(StateRepository, candidate)


def resolve_port_allocator(runtime: object) -> PortAllocator:
    runtime_context = getattr(runtime, "runtime_context", None)
    candidate = getattr(runtime_context, "port_allocator", None)
    if candidate is None:
        candidate = getattr(runtime, "port_planner", None)
    if candidate is None:
        raise RuntimeError("port allocator dependency is not configured")
    return cast(PortAllocator, candidate)


def resolve_process_runtime(runtime: object) -> ProcessRuntime:
    runtime_context = getattr(runtime, "runtime_context", None)
    candidate = getattr(runtime_context, "process_runtime", None)
    if candidate is None:
        candidate = getattr(runtime, "process_runner", None)
    if candidate is None:
        raise RuntimeError("process runtime dependency is not configured")
    return cast(ProcessRuntime, candidate)
