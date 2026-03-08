from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

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
