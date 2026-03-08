from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import threading
import time
import uuid
from typing import Any

from ..debug.debug_contract import DEBUG_EVENT_SCHEMA_VERSION, apply_debug_event_contract
from ..debug.debug_utils import file_lock, hash_command, scrub_sensitive_text


@dataclass(slots=True)
class DebugRecorderConfig:
    runtime_scope_dir: Path
    runtime_scope_id: str
    run_id: str | None
    mode: str
    bundle_strict: bool
    capture_printable: bool
    ring_bytes: int
    max_events: int
    sample_rate: int
    session_id: str | None = None
    output_root: Path | None = None
    hash_salt: str | None = None
    retention_days: int = 7


class DebugFlightRecorder:
    def __init__(self, config: DebugRecorderConfig) -> None:
        self.config = config
        self._lock = threading.Lock()
        self._ring_lock = threading.Lock()
        self._seq = 0
        self._event_count = 0
        self._limit_emitted = False
        self._sample_index = 0
        self._ring = bytearray()
        self._max_raw_bytes = 256 * 1024
        self._dropped_input_bytes = 0
        self.session_id = config.session_id or self._new_session_id()
        self.hash_salt = config.hash_salt or uuid.uuid4().hex

        debug_root = config.output_root or (config.runtime_scope_dir / "debug")
        debug_root.mkdir(parents=True, exist_ok=True)
        self.debug_root = debug_root
        self.session_dir = debug_root / self.session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.session_dir / "events.debug.jsonl"
        self.input_ring_path = self.session_dir / "input_ring.hex"
        self._lock_path = debug_root / "debug.lock"
        self._sweep_old_sessions()
        self._ensure_session_metadata()
        self._write_latest_pointer()

    def set_run_id(self, run_id: str | None) -> None:
        if run_id is None:
            return
        self.config.run_id = run_id
        self._ensure_session_metadata()

    def record(self, event_name: str, component: str | None = None, **payload: object) -> None:
        if self.config.mode == "off":
            return
        with self._lock:
            if not self._should_record_sample():
                return
            if self._event_count >= max(0, int(self.config.max_events)):
                if not self._limit_emitted:
                    self._limit_emitted = True
                    self._write_event(
                        self._build_event(
                            "ui.anomaly.debug_limit_reached",
                            component="debug_flight_recorder",
                            evidence_seq=[self._seq],
                        )
                    )
                return
            event = self._build_event(event_name, component=component, payload=payload)
            self._write_event(event)
            self._event_count += 1

    def record_input_bytes(self, data: bytes, *, component: str, backend: str) -> None:
        if self.config.mode != "deep":
            return
        if not data:
            return
        payload = {
            "backend": backend,
            "bytes_read": len(data),
            "printable": _is_printable_bytes(data),
        }
        self.record("ui.input.read.byte", component=component, **payload)
        if self.config.bundle_strict and not self.config.capture_printable:
            return
        if self.config.bundle_strict and self.config.capture_printable:
            data = _mask_printable_bytes(data)
        with self._ring_lock:
            previous_len = len(self._ring)
            self._ring.extend(data)
            if len(self._ring) > self._max_raw_bytes:
                dropped = len(self._ring) - self._max_raw_bytes
                self._dropped_input_bytes += max(0, dropped)
                self._ring = self._ring[-self._max_raw_bytes :]
            if len(self._ring) > max(0, int(self.config.ring_bytes)):
                dropped = len(self._ring) - int(self.config.ring_bytes)
                self._dropped_input_bytes += max(0, dropped)
                self._ring = self._ring[-int(self.config.ring_bytes) :]
            if self._dropped_input_bytes > 0 and len(self._ring) != previous_len:
                self.record(
                    "ui.anomaly.debug_ring_dropped_bytes",
                    component="debug_flight_recorder",
                    dropped_bytes=self._dropped_input_bytes,
                )
        self.flush_input_ring()

    def flush_input_ring(self) -> None:
        if self.config.bundle_strict and not self.config.capture_printable:
            return
        with self._ring_lock:
            if not self._ring:
                return
            payload = self._ring.hex()
        self.input_ring_path.write_text(payload, encoding="utf-8")

    def write_tty_context(self, context: dict[str, object]) -> None:
        path = self.session_dir / "tty_context.json"
        path.write_text(json.dumps(context, indent=2, sort_keys=True), encoding="utf-8")

    def append_tty_state_transition(self, payload: dict[str, object]) -> None:
        path = self.session_dir / "tty_state_transitions.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")

    def append_anomaly(self, payload: dict[str, object]) -> None:
        path = self.session_dir / "anomalies.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")

    def flush(self) -> None:
        self.flush_input_ring()

    def _write_event(self, event: dict[str, object]) -> None:
        with file_lock(self._lock_path, timeout=1.0):
            with self.events_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, sort_keys=True) + "\n")

    def _build_event(
        self,
        event_name: str,
        *,
        component: str | None,
        payload: dict[str, object] | None = None,
        **extra: object,
    ) -> dict[str, object]:
        payload = dict(payload or {})
        if component is None:
            component = str(payload.pop("component", "engine_runtime._emit"))
        ts_wall = datetime.now(tz=UTC).isoformat()
        ts_mono_ns = time.monotonic_ns()
        self._seq += 1
        base = {
            "seq": self._seq,
            "session_id": self.session_id,
            "run_id": self.config.run_id,
            "pid": os.getpid(),
            "thread": threading.current_thread().name,
            "scope_id": self.config.runtime_scope_id,
            "mode": self.config.mode,
            "component": component,
            "trace_id": str(payload.get("command_id") or self.session_id),
            "ts_wall": ts_wall,
            "ts_mono_ns": ts_mono_ns,
        }
        redacted_payload = self._sanitize_payload(payload)
        if extra:
            redacted_payload.update(extra)
        return apply_debug_event_contract(
            event_name=event_name,
            payload={**base, **redacted_payload},
            timestamp=ts_wall,
            trace_id=str(base["trace_id"]),
        )

    def _sanitize_payload(self, payload: dict[str, object]) -> dict[str, object]:
        sanitized: dict[str, object] = {}
        for key, value in payload.items():
            if key == "command" and isinstance(value, str):
                command_hash, command_length = hash_command(value, self.hash_salt)
                sanitized["command_hash"] = command_hash
                sanitized["command_length"] = command_length
                continue
            if isinstance(value, str):
                sanitized[key] = scrub_sensitive_text(value)
                continue
            sanitized[key] = value
        return sanitized

    def _should_record_sample(self) -> bool:
        sample_rate = max(1, int(self.config.sample_rate))
        self._sample_index += 1
        return self._sample_index % sample_rate == 0

    def _ensure_session_metadata(self) -> None:
        payload = {
            "session_id": self.session_id,
            "run_id": self.config.run_id,
            "scope_id": self.config.runtime_scope_id,
            "mode": self.config.mode,
            "bundle_strict": self.config.bundle_strict,
            "capture_printable": self.config.capture_printable,
            "schema_version": DEBUG_EVENT_SCHEMA_VERSION,
            "retention_days": int(self.config.retention_days),
            "created_at": datetime.now(tz=UTC).isoformat(),
            "pid": os.getpid(),
        }
        (self.session_dir / "session.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        for filename in ("tty_context.json", "anomalies.jsonl", "tty_state_transitions.jsonl"):
            path = self.session_dir / filename
            if not path.exists():
                if filename.endswith(".json"):
                    path.write_text("{}", encoding="utf-8")
                else:
                    path.write_text("", encoding="utf-8")

    def _write_latest_pointer(self) -> None:
        try:
            (self.debug_root / "latest").write_text(self.session_id, encoding="utf-8")
        except OSError:
            return

    def _sweep_old_sessions(self) -> None:
        retention_days = max(1, int(self.config.retention_days))
        cutoff = time.time() - float(retention_days * 24 * 60 * 60)
        for candidate in self.debug_root.glob("session-*"):
            if not candidate.is_dir() or candidate == self.session_dir:
                continue
            try:
                mtime = candidate.stat().st_mtime
            except OSError:
                continue
            if mtime >= cutoff:
                continue
            try:
                for child in candidate.glob("**/*"):
                    if child.is_file():
                        child.unlink(missing_ok=True)
                for child in sorted(candidate.glob("**/*"), reverse=True):
                    if child.is_dir():
                        child.rmdir()
                candidate.rmdir()
            except OSError:
                continue

    @staticmethod
    def _new_session_id() -> str:
        return f"session-{datetime.now(tz=UTC).strftime('%Y%m%d%H%M%S')}-{os.getpid()}-{uuid.uuid4().hex[:4]}"


def _is_printable_bytes(data: bytes) -> bool:
    return all(32 <= value <= 126 for value in data)


def _mask_printable_bytes(data: bytes) -> bytes:
    masked = bytearray()
    for value in data:
        if 32 <= value <= 126:
            masked.append(ord("*"))
        else:
            masked.append(value)
    return bytes(masked)
