from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
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
    candidate = optional_state_repository(runtime)
    if candidate is None:
        raise RuntimeError("state repository dependency is not configured")
    return candidate


def resolve_port_allocator(runtime: object) -> PortAllocator:
    candidate = optional_port_allocator(runtime)
    if candidate is None:
        raise RuntimeError("port allocator dependency is not configured")
    return candidate


def resolve_process_runtime(runtime: object) -> ProcessRuntime:
    candidate = optional_process_runtime(runtime)
    if candidate is None:
        raise RuntimeError("process runtime dependency is not configured")
    return candidate


def optional_state_repository(runtime: object) -> StateRepository | None:
    return cast(StateRepository | None, _optional_runtime_dependency(runtime, "state_repository", "state_repository"))


def optional_port_allocator(runtime: object) -> PortAllocator | None:
    return cast(PortAllocator | None, _optional_runtime_dependency(runtime, "port_allocator", "port_planner"))


def optional_process_runtime(runtime: object) -> ProcessRuntime | None:
    return cast(ProcessRuntime | None, _optional_runtime_dependency(runtime, "process_runtime", "process_runner"))


def run_dir_path(runtime: object, run_id: str | None) -> Path:
    raw_run_id = str(run_id or "run")
    legacy_resolver = getattr(runtime, "_run_dir_path", None)
    if callable(legacy_resolver):
        return Path(legacy_resolver(raw_run_id))
    repository = optional_state_repository(runtime)
    repository_resolver = getattr(repository, "run_dir_path", None)
    if callable(repository_resolver):
        return Path(repository_resolver(raw_run_id))
    return Path(getattr(runtime, "runtime_root", ".")) / "runs" / raw_run_id


def test_results_dir_path(runtime: object, run_id: str | None) -> Path:
    raw_run_id = str(run_id or "run")
    repository = optional_state_repository(runtime)
    repository_resolver = getattr(repository, "test_results_dir_path", None)
    if callable(repository_resolver):
        return Path(repository_resolver(raw_run_id))
    return run_dir_path(runtime, raw_run_id) / "test-results"


def _optional_runtime_dependency(runtime: object, context_attr: str, legacy_attr: str) -> object | None:
    runtime_context = getattr(runtime, "runtime_context", None)
    candidate = getattr(runtime_context, context_attr, None)
    if candidate is None:
        candidate = getattr(runtime, legacy_attr, None)
    return candidate
