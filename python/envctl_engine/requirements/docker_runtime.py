from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterator, Mapping

from envctl_engine.debug.debug_utils import file_lock
from envctl_engine.shared.protocols import CommandResult, ProcessRuntime

_DOCKER_PORT_PUBLISH_THREAD_LOCK = threading.RLock()


def run_docker(
    process_runner: ProcessRuntime,
    args: list[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float = 60.0,
) -> tuple[CommandResult | None, str | None]:
    try:
        result = process_runner.run(
            ["docker", *args],
            cwd=cwd,
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return (
            None,
            "Command timed out after "
            f"{timeout:.1f}s: "
            f"{' '.join(exc.cmd if isinstance(exc.cmd, list) else ['docker', *args])}",
        )
    except OSError as exc:
        return None, f"docker unavailable: {exc}"
    return result, None


def run_result_error(result: CommandResult, fallback: str) -> str:
    stderr = result.stderr
    stdout = result.stdout
    returncode = result.returncode
    text = (stderr or stdout or f"exit:{returncode}").strip()
    return text or fallback


def _env_value(env: Mapping[str, str] | None, key: str) -> str | None:
    raw = (env or {}).get(key)
    if raw is None:
        raw = os.environ.get(key)
    return raw


def _parse_env_bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    normalized = str(raw).strip().lower()
    if not normalized:
        return default
    return normalized not in {"0", "false", "no", "off", "disable", "disabled"}


def _env_bool(env: Mapping[str, str] | None, key: str, default: bool) -> bool:
    return _parse_env_bool(_env_value(env, key), default)


def _env_float(env: Mapping[str, str] | None, key: str, default: float, *, minimum: float) -> float:
    raw = _env_value(env, key)
    try:
        parsed = float(str(raw).strip()) if raw is not None else default
    except ValueError:
        parsed = default
    return max(parsed, minimum)


def _docker_port_publish_lock_default_enabled() -> bool:
    # Docker Desktop for macOS can reserve published ports without making them reachable
    # when several port-publishing container operations race each other.
    return sys.platform == "darwin"


def _docker_port_publish_lock_enabled(env: Mapping[str, str] | None) -> bool:
    raw = _env_value(env, "ENVCTL_DOCKER_PORT_PUBLISH_LOCK")
    normalized = str(raw).strip().lower() if raw is not None else ""
    if not normalized or normalized == "auto":
        return _docker_port_publish_lock_default_enabled()
    return _parse_env_bool(raw, default=True)


@contextmanager
def docker_port_publish_lock(env: Mapping[str, str] | None) -> Iterator[None]:
    if not _docker_port_publish_lock_enabled(env):
        yield
        return
    runtime_root = (
        (env or {}).get("RUN_SH_RUNTIME_DIR")
        or os.environ.get("RUN_SH_RUNTIME_DIR")
        or str(Path(tempfile.gettempdir()) / "envctl-runtime")
    )
    lock_timeout = _env_float(env, "ENVCTL_DOCKER_PORT_PUBLISH_LOCK_TIMEOUT_SECONDS", 180.0, minimum=1.0)
    with _DOCKER_PORT_PUBLISH_THREAD_LOCK:
        with file_lock(Path(runtime_root) / "docker-port-publish.lock", timeout=lock_timeout):
            yield
