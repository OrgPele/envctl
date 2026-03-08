from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import re
import shutil
import socket
import uuid
from typing import Any

from envctl_engine.shared.parsing import parse_int


def run_state_path(runtime: Any) -> Path:
    return runtime.state_repository.run_state_path()


def run_dir_path(runtime: Any, run_id: str | None) -> Path:
    return runtime.state_repository.run_dir_path(run_id)


def runtime_map_path(runtime: Any) -> Path:
    return runtime.state_repository.runtime_map_path()


def ports_manifest_path(runtime: Any) -> Path:
    return runtime.state_repository.ports_manifest_path()


def error_report_path(runtime: Any) -> Path:
    return runtime.state_repository.error_report_path()


def lock_inventory(runtime: Any) -> list[str]:
    return sorted(lock_path.name for lock_path in runtime.port_planner.lock_dir.glob("*.lock"))


def new_run_id(runtime: Any) -> str:
    run_id = f"run-{datetime.now(tz=UTC).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    runtime._bind_debug_run_id(run_id)
    return run_id


def conflict_count(runtime: Any, suffix: str) -> int:
    return parse_int(runtime.env.get(f"ENVCTL_TEST_CONFLICT_{suffix}"), 0)


def probe_listener_support() -> bool:
    if shutil.which("lsof") is None:
        return False
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
        return True
    except OSError:
        return False


def normalize_log_line(line: str, *, no_color: bool) -> str:
    if not no_color:
        return line
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line)
