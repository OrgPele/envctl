from __future__ import annotations

import re
import sys
import time
from collections.abc import Mapping
from pathlib import Path

from .types import _SupabaseStartupBudget, SupabaseAuthHealthProbeResult
from .config import _auth_probe_timeout_seconds
from .inspect import _inspect_auth_gateway_services
from .formatting import _format_auth_service_states, _is_python_traceback_noise



def _compose_service_state_failed(service_state: Mapping[str, object]) -> bool:
    status = str(service_state.get("status") or "").strip().lower()
    health = str(service_state.get("health") or "").strip().lower()
    return status in {"exited", "dead", "removing"} or health == "unhealthy"


def _auth_services_progressing(service_states: list[dict[str, object]]) -> bool:
    if not service_states:
        return False
    for service_state in service_states:
        if _compose_service_state_failed(service_state):
            return False
        if service_state.get("inspect_error"):
            return False
        status = str(service_state.get("status") or "").strip().lower()
        if status in {"missing", "unknown", ""}:
            return False
    return True


def _wait_for_auth_health_while_progressing(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    secondary_services: list[str],
    public_port: int,
    health_url: str,
    startup_budget: _SupabaseStartupBudget,
    stage_events: list[dict[str, object]],
) -> SupabaseAuthHealthProbeResult:
    sleeper = getattr(process_runner, "sleep", time.sleep)
    last_probe: SupabaseAuthHealthProbeResult | None = None
    all_attempts: list[dict[str, object]] = []
    while startup_budget.remaining_seconds() > 0:
        remaining = startup_budget.remaining_seconds()
        probe_timeout = min(_auth_probe_timeout_seconds(env), max(0.1, remaining))
        probe_env = _env_with_float_override(env, "ENVCTL_SUPABASE_AUTH_PROBE_TIMEOUT_SECONDS", probe_timeout)
        probe = _probe_supabase_auth_health_with_attempts(
            process_runner=process_runner,
            public_port=public_port,
            health_url=health_url,
            env=probe_env,
            attempts=1,
            action="progress_wait",
        )
        all_attempts.extend(probe.attempts)
        probe.attempts = list(all_attempts)
        if probe.ready:
            stage_events.append(
                {
                    "stage": "supabase.auth.wait_progress",
                    "reason": "ready",
                    "detail": health_url,
                    "startup_budget_s": startup_budget.timeout_seconds,
                    "elapsed_ms": startup_budget.elapsed_ms(),
                }
            )
            return probe
        last_probe = probe
        states = _inspect_auth_gateway_services(
            process_runner=process_runner,
            compose_root=compose_root,
            compose_project_name=compose_project_name,
            compose_path=compose_path,
            env=env,
            service_names=secondary_services,
        )
        if not _auth_services_progressing(states):
            stage_events.append(
                {
                    "stage": "supabase.auth.wait_progress",
                    "reason": "not_progressing",
                    "detail": _format_auth_service_states(states),
                    "startup_budget_s": startup_budget.timeout_seconds,
                    "elapsed_ms": startup_budget.elapsed_ms(),
                }
            )
            break
        sleep_seconds = min(0.25, startup_budget.remaining_seconds())
        if sleep_seconds <= 0:
            break
        sleeper(sleep_seconds)
    if last_probe is not None:
        last_probe.attempts = all_attempts
        return last_probe
    return SupabaseAuthHealthProbeResult(
        ready=False,
        phase="listener",
        health_url=health_url,
        attempts=all_attempts,
        last_error="Supabase Auth/Kong health probe did not run before startup budget expired",
        listener_ready=False,
    )


def _env_with_float_override(
    env: Mapping[str, str] | None,
    key: str,
    value: float,
) -> Mapping[str, str]:
    merged = dict(env or {})
    merged[key] = f"{max(0.1, value):g}"
    return merged


def _probe_db_listener(
    *,
    process_runner,
    db_port: int,
    timeout_seconds: float,
    attempts: int,
) -> bool:
    for _ in range(max(1, attempts)):
        if bool(process_runner.wait_for_port(db_port, timeout=timeout_seconds)):
            return True
    return False


def _record_db_probe_stage(
    stage_events: list[dict[str, object]],
    *,
    db_port: int,
    attempts: int,
    action: str,
    ready: bool,
    timeout_seconds: float,
    startup_budget: _SupabaseStartupBudget | None = None,
) -> None:
    event: dict[str, object] = {
        "stage": "supabase.db.probe",
        "reason": "ready" if ready else "failed",
        "detail": (
            f"action={action} port={db_port} attempts={max(1, attempts)} "
            f"timeout_s={timeout_seconds:g}"
        ),
    }
    if startup_budget is not None:
        event["startup_budget_s"] = startup_budget.timeout_seconds
        event["elapsed_ms"] = startup_budget.elapsed_ms()
    stage_events.append(event)


def _record_compose_network_recovery_stage(stage_events: list[dict[str, object]], error: str | None) -> None:
    if not _is_compose_network_recovery_marker(error):
        return
    detail = str(error).split("network_recovery=", 1)[1].strip()
    if not detail:
        return
    stage_events.append(
        {
            "stage": "supabase.compose.network_recovery",
            "reason": "recovered",
            "detail": detail,
        }
    )


def _is_compose_network_recovery_marker(error: str | None) -> bool:
    return bool(error and str(error).startswith("network_recovery="))


def _probe_supabase_auth_health(
    *,
    process_runner,
    public_port: int,
    health_url: str,
    env: Mapping[str, str] | None,
) -> tuple[bool, str | None]:
    result = _probe_supabase_auth_health_with_attempts(
        process_runner=process_runner,
        public_port=public_port,
        health_url=health_url,
        env=env,
        attempts=1,
        action="probe",
    )
    return result.ready, result.last_error


def _probe_supabase_auth_health_with_attempts(
    *,
    process_runner,
    public_port: int,
    health_url: str,
    env: Mapping[str, str] | None,
    attempts: int,
    action: str,
) -> SupabaseAuthHealthProbeResult:
    last_result: SupabaseAuthHealthProbeResult | None = None
    all_attempts: list[dict[str, object]] = []
    for index in range(max(1, attempts)):
        result = _probe_supabase_auth_health_once(
            process_runner=process_runner,
            public_port=public_port,
            health_url=health_url,
            env=env,
            action=action,
            action_attempt=index + 1,
        )
        all_attempts.extend(result.attempts)
        if result.ready:
            result.attempts = all_attempts
            return result
        last_result = result
    if last_result is None:
        return SupabaseAuthHealthProbeResult(
            ready=False,
            phase="listener",
            health_url=health_url,
            attempts=all_attempts,
            last_error="Supabase Auth/Kong health probe did not run",
            listener_ready=False,
        )
    last_result.attempts = all_attempts
    return last_result


def _probe_supabase_auth_health_once(
    *,
    process_runner,
    public_port: int,
    health_url: str,
    env: Mapping[str, str] | None,
    action: str,
    action_attempt: int,
) -> SupabaseAuthHealthProbeResult:
    probe_attempts: list[dict[str, object]] = []
    timeout_seconds = _auth_probe_timeout_seconds(env)
    if public_port > 0 and not bool(process_runner.wait_for_port(public_port, timeout=timeout_seconds)):
        error = f"listener probe failed on port {public_port}"
        probe_attempts.append(
            {
                "phase": "listener",
                "action": action,
                "action_attempt": action_attempt,
                "port": public_port,
                "health_url": health_url,
                "ready": False,
                "error": error,
            }
        )
        return SupabaseAuthHealthProbeResult(
            ready=False,
            phase="listener",
            health_url=health_url,
            attempts=probe_attempts,
            last_error=error,
            listener_ready=False,
        )
    probe_attempts.append(
        {
            "phase": "listener",
            "action": action,
            "action_attempt": action_attempt,
            "port": public_port,
            "health_url": health_url,
            "ready": True,
        }
    )
    probe_code = (
        "import sys, urllib.error, urllib.request; "
        "url=sys.argv[1]; "
        "timeout=float(sys.argv[2]); "
        "req=urllib.request.Request(url, headers={'Accept':'application/json'}); "
        "\ntry:\n"
        "    resp=urllib.request.urlopen(req, timeout=timeout)\n"
        "except urllib.error.HTTPError as exc:\n"
        "    print(f'HTTPError: {exc.code} {exc.reason}', file=sys.stderr)\n"
        "    raise SystemExit(0 if 200 <= exc.code < 500 else 1)\n"
        "except Exception as exc:\n"
        "    print(f'HTTP health probe failed: {type(exc).__name__}: {exc}', file=sys.stderr)\n"
        "    raise SystemExit(1)\n"
        "raise SystemExit(0 if 200 <= resp.status < 500 else 1)"
    )
    deadline = time.monotonic() + timeout_seconds
    sleeper = getattr(process_runner, "sleep", time.sleep)
    last_error = "HTTP health probe failed"
    http_attempt = 0
    while True:
        http_attempt += 1
        remaining = max(0.1, deadline - time.monotonic())
        result = process_runner.run(
            [sys.executable, "-c", probe_code, health_url, str(min(timeout_seconds, remaining))],
            env=env,
            timeout=min(timeout_seconds, remaining) + 1.0,
        )
        if getattr(result, "returncode", 1) == 0:
            probe_attempts.append(
                {
                    "phase": "http",
                    "action": action,
                    "action_attempt": action_attempt,
                    "attempt": http_attempt,
                    "health_url": health_url,
                    "ready": True,
                    "returncode": 0,
                }
            )
            return SupabaseAuthHealthProbeResult(
                ready=True,
                phase="http",
                health_url=health_url,
                attempts=probe_attempts,
                listener_ready=True,
            )
        last_error = _condense_probe_error(str(
            getattr(result, "stderr", "") or getattr(result, "stdout", "") or "HTTP health probe failed"
        ).strip())
        probe_attempts.append(
            {
                "phase": "http",
                "action": action,
                "action_attempt": action_attempt,
                "attempt": http_attempt,
                "health_url": health_url,
                "ready": False,
                "returncode": int(getattr(result, "returncode", 1) or 1),
                "error": last_error,
            }
        )
        if time.monotonic() >= deadline:
            return SupabaseAuthHealthProbeResult(
                ready=False,
                phase="http",
                health_url=health_url,
                attempts=probe_attempts,
                last_error=last_error,
                listener_ready=True,
            )
        sleeper(min(0.25, max(0.0, deadline - time.monotonic())))


def _condense_probe_error(error: str) -> str:
    lines = [line.strip() for line in str(error or "").splitlines() if line.strip()]
    if not lines:
        return "HTTP health probe failed"
    for line in reversed(lines):
        if "urlopen error" in line.lower():
            match = re.search(r"urlopen error [^>]+", line, re.IGNORECASE)
            return match.group(0) if match else line
    for line in reversed(lines):
        lowered = line.lower()
        if _is_python_traceback_noise(line):
            continue
        if "connectionrefusederror" in lowered or "connection refused" in lowered:
            return line
        if "timed out" in lowered or "timeout" in lowered:
            return line
        if "httperror" in lowered or "http error" in lowered:
            return line
        if re.search(r"\b(?:status(?: code)?|http status|response status)[= :]+[45]\d\d\b", lowered):
            return line
    for line in reversed(lines):
        if not _is_python_traceback_noise(line):
            return line
    return "HTTP health probe failed"


