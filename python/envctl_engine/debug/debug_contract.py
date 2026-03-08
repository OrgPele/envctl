from __future__ import annotations

from datetime import UTC, datetime
from typing import Mapping


DEBUG_EVENT_SCHEMA_VERSION = 2


_PHASE_PREFIX = (
    ("ui.input.read", "input"),
    ("ui.input.sanitize", "input"),
    ("ui.input.dispatch", "dispatch"),
    ("ui.spinner", "dispatch"),
    ("command.route", "route"),
    ("process.", "lifecycle"),
    ("service.", "lifecycle"),
    ("requirements.", "lifecycle"),
    ("state.", "state"),
    ("runtime_map.", "state"),
)


def infer_phase(event_name: str) -> str:
    lowered = event_name.strip().lower()
    for prefix, phase in _PHASE_PREFIX:
        if lowered.startswith(prefix):
            return phase
    return "runtime"


def apply_debug_event_contract(
    *,
    event_name: str,
    payload: Mapping[str, object],
    timestamp: str | None,
    trace_id: str,
    parent_trace_id: str | None = None,
) -> dict[str, object]:
    ts = timestamp or datetime.now(tz=UTC).isoformat()
    event: dict[str, object] = {
        "event": event_name,
        "timestamp": ts,
        "schema_version": DEBUG_EVENT_SCHEMA_VERSION,
        "trace_id": trace_id,
        "phase": infer_phase(event_name),
    }
    if parent_trace_id:
        event["parent_trace_id"] = parent_trace_id
    for key, value in payload.items():
        event[key] = value
    return event


def normalize_event_for_bundle(event: Mapping[str, object]) -> dict[str, object]:
    payload = dict(event)
    if "schema_version" not in payload:
        payload["schema_version"] = DEBUG_EVENT_SCHEMA_VERSION
    if "phase" not in payload and isinstance(payload.get("event"), str):
        payload["phase"] = infer_phase(str(payload["event"]))
    if "trace_id" not in payload:
        payload["trace_id"] = "legacy-trace"
    return payload
