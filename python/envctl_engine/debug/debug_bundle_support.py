from __future__ import annotations

import json
import shutil
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from envctl_engine.debug.debug_contract import DEBUG_EVENT_SCHEMA_VERSION, normalize_event_for_bundle
from envctl_engine.debug.debug_utils import hash_command, hash_value, scrub_sensitive_text


def sanitize_runtime_event(event: dict[str, object], salt: str) -> dict[str, object]:
    sanitized: dict[str, object] = {}
    name = str(event.get("event", ""))
    for key, value in event.items():
        if name == "ui.input.submit" and key == "command" and isinstance(value, str):
            command_hash, command_length = hash_command(value, salt)
            sanitized["command_hash"] = command_hash
            sanitized["command_length"] = command_length
            continue
        if name == "planning.selection.invalid" and key == "selection" and isinstance(value, str):
            sanitized["selection_hash"] = hash_value(value, salt)
            continue
        if isinstance(value, str):
            sanitized[key] = scrub_sensitive_text(value)
            continue
        sanitized[key] = value
    return normalize_event_for_bundle(sanitized)


def resolve_session_id(debug_root: Path, *, session_id: str | None, run_id: str | None) -> str:
    if session_id:
        return session_id
    if run_id:
        matches = sessions_for_run_id(debug_root, run_id)
        if not matches:
            raise FileNotFoundError(f"No debug sessions found for run_id={run_id}")
        return matches[0]
    latest = debug_root / "latest"
    if latest.is_file():
        candidate = latest.read_text(encoding="utf-8").strip()
        if candidate:
            return candidate
    raise FileNotFoundError("No debug session found; run with --debug-ui first")


def sessions_for_run_id(debug_root: Path, run_id: str) -> list[str]:
    sessions: list[tuple[float, str]] = []
    if not debug_root.is_dir():
        return []
    for candidate in debug_root.iterdir():
        if not candidate.is_dir() or not candidate.name.startswith("session-"):
            continue
        session_meta = candidate / "session.json"
        if not session_meta.is_file():
            continue
        try:
            payload = json.loads(session_meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(payload.get("run_id", "")) == run_id:
            try:
                stamp = float(candidate.stat().st_mtime)
            except OSError:
                stamp = 0.0
            sessions.append((stamp, candidate.name))
    sessions.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [name for _, name in sessions]


def copy_debug_session_files(
    session_dir: Path,
    staging_dir: Path,
    *,
    strict: bool,
    include_doctor: bool,
    doctor_text: str | None = None,
) -> None:
    required = [
        "events.debug.jsonl",
        "tty_context.json",
        "tty_state_transitions.jsonl",
        "anomalies.jsonl",
    ]
    optional = ["summary.md", "session.json"]
    if include_doctor:
        optional.append("doctor.txt")
    if not strict:
        optional.append("input_ring.hex")

    for name in required:
        source = session_dir / name
        if source.is_file():
            shutil.copy2(source, staging_dir / name)
        else:
            (staging_dir / name).write_text("" if name.endswith(".jsonl") else "{}", encoding="utf-8")

    for name in optional:
        source = session_dir / name
        if source.is_file():
            shutil.copy2(source, staging_dir / name)
        elif name == "doctor.txt" and include_doctor:
            payload = doctor_text if isinstance(doctor_text, str) else "doctor snapshot unavailable\n"
            (staging_dir / name).write_text(payload, encoding="utf-8")


def write_redacted_runtime_events(*, runtime_scope_dir: Path, output_path: Path, salt: str) -> None:
    runtime_events = runtime_scope_dir / "events.jsonl"
    if not runtime_events.is_file():
        output_path.write_text("", encoding="utf-8")
        return
    lines = runtime_events.read_text(encoding="utf-8").splitlines()
    with output_path.open("w", encoding="utf-8") as handle:
        for line in lines:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            sanitized = sanitize_runtime_event(payload, salt=salt)
            handle.write(json.dumps(sanitized, sort_keys=True) + "\n")


def write_timeline(staging_dir: Path) -> None:
    timeline: list[dict[str, Any]] = []
    for name, source in (("events.debug.jsonl", "debug"), ("events.runtime.redacted.jsonl", "runtime")):
        path = staging_dir / name
        if not path.is_file():
            continue
        for event in read_jsonl(path):
            item = normalize_event_for_bundle(event)
            item["source"] = source
            timeline.append(item)
    timeline.sort(key=event_sort_key)
    with (staging_dir / "timeline.jsonl").open("w", encoding="utf-8") as handle:
        for event in timeline:
            handle.write(json.dumps(event, sort_keys=True) + "\n")


def write_command_index(staging_dir: Path) -> None:
    index: dict[str, list[dict[str, Any]]] = {}
    for event in read_jsonl(staging_dir / "timeline.jsonl"):
        command_id = event.get("command_id")
        if not isinstance(command_id, str) or not command_id:
            continue
        index.setdefault(command_id, []).append(
            {
                "event": event.get("event"),
                "phase": event.get("phase"),
                "ts_mono_ns": event.get("ts_mono_ns"),
            }
        )
    (staging_dir / "command_index.json").write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")


def write_bundle_contract(staging_dir: Path, *, strict: bool) -> None:
    payload = {
        "contract_version": 1,
        "event_schema_version": DEBUG_EVENT_SCHEMA_VERSION,
        "generator": "envctl.debug_bundle",
        "strict": bool(strict),
        "generated_at": datetime.now(tz=UTC).isoformat(),
    }
    (staging_dir / "bundle_contract.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def ensure_summary(staging_dir: Path) -> None:
    summary_path = staging_dir / "summary.md"
    if summary_path.exists():
        return
    event_counts = count_events(staging_dir / "events.debug.jsonl")
    anomaly_counts = count_events(staging_dir / "anomalies.jsonl")
    content = [
        "# Debug Bundle Summary",
        "",
        f"Generated: {datetime.now(tz=UTC).isoformat()}",
        f"Debug events: {event_counts}",
        f"Anomalies: {anomaly_counts}",
        "",
    ]
    summary_path.write_text("\n".join(content), encoding="utf-8")


def write_manifest(staging_dir: Path, *, scope_id: str, strict: bool, session_id: str) -> None:
    files = []
    for path in sorted(staging_dir.iterdir()):
        if path.name == "manifest.json" or not path.is_file():
            continue
        files.append(
            {
                "path": path.name,
                "sha256": file_hash(path),
                "bytes": path.stat().st_size,
            }
        )
    payload = {
        "version": 1,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "scope_id": scope_id,
        "session_id": session_id,
        "strict": strict,
        "files": files,
    }
    (staging_dir / "manifest.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def create_tarball(bundle_path: Path, staging_dir: Path) -> None:
    with tarfile.open(bundle_path, "w:gz") as tar:
        for path in sorted(staging_dir.iterdir()):
            if path.is_file():
                tar.add(path, arcname=path.name)


def file_hash(path: Path) -> str:
    try:
        import hashlib

        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return ""


def count_events(path: Path) -> int:
    if not path.is_file():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def event_sort_key(event: Mapping[str, Any]) -> tuple[int, int, str]:
    ts_mono = event.get("ts_mono_ns")
    if isinstance(ts_mono, int):
        return (0, ts_mono, str(event.get("event", "")))
    ts_text = str(event.get("timestamp") or event.get("ts_wall") or "")
    return (1, 0, ts_text)


def count_jsonl_bytes(data: bytes) -> int:
    text = data.decode("utf-8", errors="replace")
    return sum(1 for line in text.splitlines() if line.strip())
