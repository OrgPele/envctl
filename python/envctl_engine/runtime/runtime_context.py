from __future__ import annotations

from dataclasses import dataclass
import os
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
        legacy_path = _path_from_candidate(legacy_resolver(raw_run_id))
        if legacy_path is not None:
            return legacy_path
    repository = optional_state_repository(runtime)
    repository_resolver = getattr(repository, "run_dir_path", None)
    if callable(repository_resolver):
        repository_path = _path_from_candidate(repository_resolver(raw_run_id))
        if repository_path is not None:
            return repository_path
    runtime_root = _path_from_candidate(getattr(runtime, "runtime_root", ".")) or Path(".")
    return runtime_root / "runs" / raw_run_id


def test_results_dir_path(runtime: object, run_id: str | None) -> Path:
    raw_run_id = str(run_id or "run")
    repository = optional_state_repository(runtime)
    repository_resolver = getattr(repository, "test_results_dir_path", None)
    if callable(repository_resolver):
        repository_path = _path_from_candidate(repository_resolver(raw_run_id))
        if repository_path is not None:
            return repository_path
    return run_dir_path(runtime, raw_run_id) / "test-results"


def save_resume_state(
    runtime: object,
    *,
    state: object,
    runtime_map_builder: Callable[[object], dict[str, object]],
) -> dict[str, object]:
    return resolve_state_repository(runtime).save_resume_state(
        state=state,
        emit=getattr(runtime, "emit"),
        runtime_map_builder=runtime_map_builder,
    )


def _optional_runtime_dependency(runtime: object, context_attr: str, legacy_attr: str) -> object | None:
    runtime_context = getattr(runtime, "runtime_context", None)
    candidate = getattr(runtime_context, context_attr, None)
    if candidate is None:
        candidate = getattr(runtime, legacy_attr, None)
    return candidate


def _path_from_candidate(candidate: object) -> Path | None:
    if isinstance(candidate, Path):
        return candidate
    if isinstance(candidate, str):
        return Path(candidate)
    if isinstance(candidate, os.PathLike):
        raw = candidate.__fspath__()
        if isinstance(raw, str):
            return Path(raw)
    return None
