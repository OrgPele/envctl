from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Iterable

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState
from envctl_engine.shared.parsing import parse_int
from envctl_engine.shared.process_probe import ProbeBackend, PsutilProbeBackend, ShellProbeBackend, psutil_available
from envctl_engine.shared.process_runner import ProcessRunner
from envctl_engine.state.repository import RuntimeStateRepository


def state_compat_mode(runtime: Any) -> str:
    raw = runtime.env.get("ENVCTL_STATE_COMPAT_MODE") or runtime.config.raw.get("ENVCTL_STATE_COMPAT_MODE")
    normalized = str(raw or "").strip().lower()
    if normalized in {
        RuntimeStateRepository.COMPAT_READ_WRITE,
        RuntimeStateRepository.COMPAT_READ_ONLY,
        RuntimeStateRepository.SCOPED_ONLY,
    }:
        return normalized
    return RuntimeStateRepository.COMPAT_READ_WRITE


def release_port_session(runtime: Any) -> None:
    try:
        runtime.port_planner.release_session()
    except AttributeError:
        try:
            runtime.port_planner.release_all()
        except AttributeError:
            return


def build_process_probe_backend(runtime: Any) -> ProbeBackend:
    if not isinstance(runtime.process_runner, ProcessRunner):
        return ShellProbeBackend(runtime.process_runner)
    if probe_psutil_enabled(runtime) and psutil_available():
        return PsutilProbeBackend()
    return ShellProbeBackend(runtime.process_runner)


def probe_psutil_enabled(runtime: Any) -> bool:
    raw = runtime.env.get("ENVCTL_PROBE_PSUTIL")
    if raw is None:
        raw = os.environ.get("ENVCTL_PROBE_PSUTIL")
    if raw is None:
        return psutil_available()
    value = str(raw).strip().lower()
    if value in {"0", "false", "no", "off"}:
        return False
    if value in {"1", "true", "yes", "on"}:
        return psutil_available()
    return psutil_available()


def tokens_set_mode(tokens: Iterable[str]) -> bool:
    for token in tokens:
        if token in {"--main", "main=true", "--tree", "--trees", "trees=true", "main=false", "trees=false"}:
            return True
    return False


def status_color(status: str, *, green: str, yellow: str, red: str) -> str:
    lowered = status.lower()
    if lowered in {"running", "healthy"}:
        return green
    if lowered in {"starting", "unknown"}:
        return yellow
    return red


def should_enter_post_start_interactive(runtime: Any, route: Route) -> bool:
    if route.command not in {"start", "plan", "restart"}:
        return False
    if batch_mode_requested(runtime, route):
        return False
    return runtime._can_interactive_tty()


def should_enter_dashboard_interactive(runtime: Any, route: Route) -> bool:
    if route.command != "dashboard":
        return False
    if batch_mode_requested(runtime, route):
        return False
    return runtime._can_interactive_tty()


def should_enter_resume_interactive(runtime: Any, route: Route) -> bool:
    if route.command != "resume":
        return False
    if batch_mode_requested(runtime, route):
        return False
    return runtime._can_interactive_tty()


def batch_mode_requested(runtime: Any, route: Route) -> bool:
    if bool(route.flags.get("batch")):
        return True
    if is_truthy(runtime.env.get("BATCH")):
        return True
    return is_truthy(os.environ.get("BATCH"))


def is_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def route_has_explicit_mode(route: Route, *, explicit_mode_tokens: set[str]) -> bool:
    for token in route.raw_args:
        if str(token).strip().lower() in explicit_mode_tokens:
            return True
    return False


def recent_failure_messages(runtime: Any, *, max_items: int = 5) -> list[str]:
    paths = [runtime._error_report_path(), runtime.runtime_legacy_root / "error_report.json"]
    failures: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for raw in payload.get("errors", []):
            text = str(raw).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            failures.append(text)
            if len(failures) >= max_items:
                return failures
    return failures


def print_logs(
    runtime: Any,
    state: RunState,
    *,
    tail: int,
    follow: bool = False,
    duration_seconds: float | None = None,
    no_color: bool = False,
) -> None:
    tracked: list[dict[str, object]] = []
    for service in state.services.values():
        if not service.log_path:
            print(f"{service.name}: log=n/a")
            continue
        log_path = Path(service.log_path)
        if not log_path.is_file():
            print(f"{service.name}: log missing at {log_path}")
            continue
        print(f"{service.name}: log={log_path}")
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines[-tail:]:
            print(runtime._normalize_log_line(line, no_color=no_color))
        tracked.append(
            {
                "name": service.name,
                "path": log_path,
                "offset": log_path.stat().st_size,
            }
        )

    should_follow = follow or (duration_seconds is not None and duration_seconds > 0)
    if not should_follow or not tracked:
        return

    deadline = time.monotonic() + duration_seconds if duration_seconds is not None and duration_seconds >= 0 else None
    try:
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                break
            emitted = False
            for item in tracked:
                path = item["path"]
                if not isinstance(path, Path) or not path.is_file():
                    continue
                offset = int(item["offset"])
                current_size = path.stat().st_size
                if current_size <= offset:
                    continue
                with path.open("r", encoding="utf-8", errors="replace") as handle:
                    handle.seek(offset)
                    chunk = handle.read()
                    item["offset"] = handle.tell()
                if not chunk:
                    continue
                emitted = True
                for line in chunk.splitlines():
                    print(runtime._normalize_log_line(line, no_color=no_color))
            if not emitted:
                time.sleep(0.2)
    except KeyboardInterrupt:
        print("Stopped log follow.")


def requirement_bind_max_retries(runtime: Any) -> int:
    return max(parse_int(runtime.env.get("ENVCTL_REQUIREMENT_BIND_MAX_RETRIES"), 8), 1)


def listener_truth_enforced(runtime: Any) -> bool:
    mode = runtime.config.runtime_truth_mode
    if mode == "strict":
        return True
    if mode == "best_effort":
        return False
    return runtime._listener_probe_supported


def requirement_enabled(runtime: Any, service_name: str, *, mode: str, route: Route | None = None) -> bool:
    return runtime._requirement_enabled_for_mode(mode, service_name, route=route)
