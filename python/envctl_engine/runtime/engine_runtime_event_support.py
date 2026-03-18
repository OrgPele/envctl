from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping

from envctl_engine.runtime.command_router import Route
from envctl_engine.debug.debug_contract import apply_debug_event_contract
from envctl_engine.debug.debug_utils import debug_env_value, hash_command, hash_value
from envctl_engine.shared.parsing import parse_bool, parse_int
from envctl_engine.ui.debug_flight_recorder import DebugFlightRecorder, DebugRecorderConfig


def sanitize_emit_payload(runtime: Any, event_name: str, payload: dict[str, object]) -> dict[str, object]:
    safe = dict(payload)
    if "command_id" not in safe and isinstance(runtime._active_command_id, str) and runtime._active_command_id:
        safe["command_id"] = runtime._active_command_id
    if event_name == "ui.input.submit" and "command" in safe:
        raw = safe.pop("command")
        if "command_hash" not in safe and isinstance(raw, str):
            command_hash, command_length = hash_command(raw, runtime._debug_hash_salt)
            safe["command_hash"] = command_hash
            safe["command_length"] = command_length
    if event_name == "planning.selection.invalid" and "selection" in safe:
        selection = safe.pop("selection")
        if "selection_hash" not in safe and isinstance(selection, str):
            safe["selection_hash"] = hash_value(selection, runtime._debug_hash_salt)
    return safe


def debug_trace_id_mode(runtime: Any) -> str:
    raw = runtime.env.get("ENVCTL_DEBUG_TRACE_ID_MODE") or runtime.config.raw.get("ENVCTL_DEBUG_TRACE_ID_MODE")
    value = str(raw or "per-command").strip().lower()
    if value in {"per-command", "per-session"}:
        return value
    return "per-command"


def event_trace_id(runtime: Any, *, event_name: str, payload: Mapping[str, object]) -> str:
    trace_mode = debug_trace_id_mode(runtime)
    if trace_mode == "per-command":
        command_id = payload.get("command_id")
        if isinstance(command_id, str) and command_id.strip():
            return command_id.strip()
    run_id = runtime.env.get("ENVCTL_DEBUG_UI_RUN_ID")
    if isinstance(run_id, str) and run_id.strip():
        return run_id.strip()
    if isinstance(runtime._active_command_id, str) and runtime._active_command_id:
        return runtime._active_command_id
    return f"trace-{event_name}"


def emit(runtime: Any, event_name: str, **payload: object) -> None:
    safe_payload = sanitize_emit_payload(runtime, event_name, payload)
    trace_id = event_trace_id(runtime, event_name=event_name, payload=safe_payload)
    event = apply_debug_event_contract(
        event_name=event_name,
        payload=safe_payload,
        timestamp=datetime.now(tz=UTC).isoformat(),
        trace_id=trace_id,
        parent_trace_id=str(safe_payload.get("parent_trace_id"))
        if isinstance(safe_payload.get("parent_trace_id"), str)
        else None,
    )
    with runtime._emit_lock:
        runtime.events.append(event)
    if runtime._debug_recorder is not None:
        recorder_payload = dict(safe_payload)
        component_value = recorder_payload.pop("component", None)
        component: str | None = component_value if isinstance(component_value, str) else None
        runtime._debug_recorder.record(event_name, component=component, **recorder_payload)
    for listener in list(runtime._emit_listeners):
        try:
            listener(event_name, dict(safe_payload))
        except Exception:
            continue


def debug_should_auto_pack(runtime: Any, *, reason: str) -> bool:
    policy = (
        (runtime.env.get("ENVCTL_DEBUG_AUTO_PACK") or runtime.config.raw.get("ENVCTL_DEBUG_AUTO_PACK") or "off")
        .strip()
        .lower()
    )
    if policy == "off":
        return False
    if policy == "always":
        return True
    if policy == "crash":
        return reason in {"interactive_exception", "dispatch_exception"}
    if policy == "anomaly":
        return reason in {"interactive_exception", "dispatch_exception", "spinner_anomaly", "input_anomaly"}
    return False


def auto_debug_pack(runtime: Any, *, reason: str) -> None:
    if not debug_should_auto_pack(runtime, reason=reason):
        return
    route = Route(
        command="debug-pack",
        mode="main",
        raw_args=["--debug-pack"],
        passthrough_args=[],
        projects=[],
        flags={},
    )
    code = runtime._debug_pack(route)
    runtime._emit("debug.auto_pack", reason=reason, success=(code == 0), bundle_path=runtime._last_debug_bundle_path)


def persist_events_snapshot(runtime: Any) -> None:
    events_text = "".join(json.dumps(event, sort_keys=True) + "\n" for event in runtime.events)
    (runtime.runtime_root / "events.jsonl").write_text(events_text, encoding="utf-8")
    runtime.runtime_legacy_root.mkdir(parents=True, exist_ok=True)
    (runtime.runtime_legacy_root / "events.jsonl").write_text(events_text, encoding="utf-8")
    run_dir = _current_run_dir(runtime)
    if run_dir is not None and run_dir.is_dir():
        (run_dir / "events.jsonl").write_text(events_text, encoding="utf-8")


def _current_run_dir(runtime: Any) -> Path | None:
    env = getattr(runtime, "env", None)
    if not isinstance(env, dict):
        return None
    raw_run_id = env.get("ENVCTL_DEBUG_UI_RUN_ID")
    if not isinstance(raw_run_id, str):
        return None
    run_id = raw_run_id.strip()
    if not run_id:
        return None
    run_dir_resolver = getattr(runtime, "_run_dir_path", None)
    if callable(run_dir_resolver):
        try:
            candidate = run_dir_resolver(run_id)
        except Exception:
            return None
        return candidate if isinstance(candidate, Path) else Path(candidate)
    state_repository = getattr(runtime, "state_repository", None)
    run_dir_resolver = getattr(state_repository, "run_dir_path", None)
    if not callable(run_dir_resolver):
        return None
    try:
        candidate = run_dir_resolver(run_id)
    except Exception:
        return None
    return candidate if isinstance(candidate, Path) else Path(candidate)


def current_session_id(runtime: Any) -> str | None:
    recorder = runtime._debug_recorder
    if recorder is None:
        return None
    session_id = getattr(recorder, "session_id", None)
    if not isinstance(session_id, str):
        return None
    normalized = session_id.strip()
    if not normalized:
        return None
    return normalized


def debug_mode_from_route(runtime: Any, route: Route) -> str:
    capture = route.flags.get("debug_capture")
    if isinstance(capture, str):
        lowered = capture.strip().lower()
        if lowered in {"off", "standard", "deep"}:
            return lowered
    env_mode = (debug_env_value(runtime.env, "ENVCTL_DEBUG_UI_MODE") or "").strip().lower()
    if route.flags.get("debug_ui_deep") or route.flags.get("key_debug"):
        return "deep"
    if route.flags.get("debug_ui") or route.flags.get("debug_trace"):
        return "standard"
    if env_mode in {"standard", "deep"}:
        return env_mode
    return "off"


def debug_output_root(runtime: Any) -> Path | None:
    raw = debug_env_value(runtime.env, "ENVCTL_DEBUG_UI_PATH")
    if raw is None:
        return None
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    return (runtime.config.base_dir / path).resolve()


def debug_recorder_config(runtime: Any, *, mode: str) -> DebugRecorderConfig:
    strict_raw = debug_env_value(runtime.env, "ENVCTL_DEBUG_UI_BUNDLE_STRICT")
    strict = parse_bool(strict_raw, True)
    capture_raw = debug_env_value(runtime.env, "ENVCTL_DEBUG_UI_CAPTURE_PRINTABLE")
    capture_printable = parse_bool(capture_raw, False)
    ring_raw = debug_env_value(runtime.env, "ENVCTL_DEBUG_UI_RING_BYTES")
    max_events_raw = debug_env_value(runtime.env, "ENVCTL_DEBUG_UI_MAX_EVENTS")
    sample_raw = debug_env_value(runtime.env, "ENVCTL_DEBUG_UI_SAMPLE_RATE")
    retention_raw = debug_env_value(runtime.env, "ENVCTL_DEBUG_RETENTION_DAYS")
    run_id = debug_env_value(runtime.env, "ENVCTL_DEBUG_UI_RUN_ID")
    output_root = debug_output_root(runtime)
    return DebugRecorderConfig(
        runtime_scope_dir=runtime.runtime_root,
        runtime_scope_id=runtime.config.runtime_scope_id,
        run_id=run_id,
        mode=mode,
        bundle_strict=strict,
        capture_printable=capture_printable,
        ring_bytes=parse_int(ring_raw, 32768),
        max_events=parse_int(max_events_raw, 20000),
        sample_rate=parse_int(sample_raw, 1),
        retention_days=max(parse_int(retention_raw, 7), 1),
        output_root=output_root,
        hash_salt=runtime._debug_hash_salt,
    )


def configure_debug_recorder(runtime: Any, route: Route) -> None:
    mode = debug_mode_from_route(runtime, route)
    runtime.env["ENVCTL_DEBUG_UI_MODE"] = mode
    auto_pack_flag = route.flags.get("debug_auto_pack")
    if isinstance(auto_pack_flag, str) and auto_pack_flag.strip():
        runtime.env["ENVCTL_DEBUG_AUTO_PACK"] = auto_pack_flag.strip().lower()
    config = debug_recorder_config(runtime, mode=mode)
    if runtime._debug_recorder is None:
        runtime._debug_recorder = DebugFlightRecorder(config)
    else:
        runtime._debug_recorder.config.mode = config.mode
        runtime._debug_recorder.config.bundle_strict = config.bundle_strict
        runtime._debug_recorder.config.capture_printable = config.capture_printable
        runtime._debug_recorder.config.ring_bytes = config.ring_bytes
        runtime._debug_recorder.config.max_events = config.max_events
        runtime._debug_recorder.config.sample_rate = config.sample_rate
    runtime._debug_recorder.set_run_id(config.run_id)


def bind_debug_run_id(runtime: Any, run_id: str | None) -> None:
    if not isinstance(run_id, str):
        return
    value = run_id.strip()
    if not value:
        return
    runtime.env["ENVCTL_DEBUG_UI_RUN_ID"] = value
    if runtime._debug_recorder is not None:
        runtime._debug_recorder.set_run_id(value)
