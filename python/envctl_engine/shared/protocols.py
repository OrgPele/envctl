from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence


class CommandResult(Protocol):
    returncode: int
    stdout: str
    stderr: str


class ProcessHandle(Protocol):
    pid: int | None


class ProcessRuntime(Protocol):
    def run(
        self,
        cmd: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> CommandResult: ...

    def start(
        self,
        cmd: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        stdout_path: str | Path | None = None,
        stderr_path: str | Path | None = None,
    ) -> ProcessHandle: ...

    def start_background(
        self,
        cmd: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        stdout_path: str | Path | None = None,
        stderr_path: str | Path | None = None,
    ) -> ProcessHandle: ...

    def terminate(self, pid: int, *, term_timeout: float, kill_timeout: float) -> bool: ...

    def is_pid_running(self, pid: int) -> bool: ...

    def wait_for_port(self, port: int, *, host: str = "127.0.0.1", timeout: float = 30.0) -> bool: ...

    def wait_for_pid_port(self, pid: int, port: int, *, host: str = "127.0.0.1", timeout: float = 30.0) -> bool: ...

    def pid_owns_port(self, pid: int, port: int) -> bool: ...

    def listener_pids_for_port(self, port: int) -> list[int]: ...

    def process_tree_listener_pids(self, root_pid: int, port: int) -> list[int]: ...

    def find_pid_listener_port(self, pid: int, preferred_port: int, *, max_delta: int = 200) -> int | None: ...

    def supports_process_tree_probe(self) -> bool: ...


class PortAllocator(Protocol):
    def reserve_next(self, start_port: int, owner: str) -> int: ...
    def update_final_port(self, plan: object, final_port: int, source: str = "retry") -> object: ...

    def release(self, port: int) -> None: ...

    def release_session(self) -> None: ...

    def release_all(self) -> None: ...


class StateRepository(Protocol):
    def save_run(
        self,
        *,
        state: object,
        contexts: list[object],
        errors: list[str],
        events: list[dict[str, object]],
        emit: Callable[..., None],
        runtime_map_builder: Callable[[object], dict[str, object]],
        write_runtime_readiness_report: Callable[[Path], None] | None = None,
    ) -> object: ...

    def save_resume_state(
        self,
        *,
        state: object,
        emit: Callable[..., None],
        runtime_map_builder: Callable[[object], dict[str, object]],
    ) -> dict[str, object]: ...

    def save_selected_stop_state(
        self,
        *,
        state: object,
        emit: Callable[..., None],
        runtime_map_builder: Callable[[object], dict[str, object]],
    ) -> dict[str, object]: ...

    def load_latest(self, *, mode: str | None = None, strict_mode_match: bool = False) -> object | None: ...

    def load_by_pointer(self, pointer_path: str) -> object: ...

    def purge(self, *, aggressive: bool = False) -> None: ...


class TerminalUI(Protocol):
    def planning_selection(
        self,
        planning_files: list[str],
        selected_counts: dict[str, int],
        existing_counts: dict[str, int],
    ) -> dict[str, int]: ...
