from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class PreparedServiceLaunch:
    service_name: str
    cwd: Path
    log_path: str
    requested_port: int
    env: dict[str, str]
    command_source: str | None
    listener_expected: bool = True


@dataclass(slots=True)
class LaunchedServiceRuntime:
    service_name: str
    requested_port: int
    actual_port: int
    pid: int | None
    log_path: str
