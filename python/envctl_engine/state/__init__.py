from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord
from envctl_engine.requirements.core import dependency_ids
from envctl_engine.shared.parsing import parse_bool, parse_float_or_none, parse_int_or_none


class StateValidationError(ValueError):
    pass


def load_state(path: str, *, allowed_root: str | None = None) -> RunState:
    state_path = Path(path)
    _validate_state_path(state_path, allowed_root=allowed_root)
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StateValidationError(f"invalid JSON in state file: {state_path}") from exc
    _validate_state_payload(data)
    services = {
        name: ServiceRecord(
            name=name,
            type=svc.get("type", "unknown"),
            cwd=svc.get("cwd", ""),
            pid=svc.get("pid"),
            requested_port=svc.get("requested_port"),
            actual_port=svc.get("actual_port"),
            log_path=svc.get("log_path"),
            status=svc.get("status", "unknown"),
            synthetic=bool(svc.get("synthetic", False)),
            started_at=parse_float_or_none(svc.get("started_at")),
            listener_pids=_parse_listener_pids(svc.get("listener_pids")),
        )
        for name, svc in data.get("services", {}).items()
    }
    requirements = {}
    for name, req in data.get("requirements", {}).items():
        payload = dict(req)
        components = payload.get("components")
        if not isinstance(components, dict):
            components = {
                "postgres": payload.get("db", {}),
                "redis": payload.get("redis", {}),
                "supabase": payload.get("supabase", {}),
                "n8n": payload.get("n8n", {}),
            }
        requirements[name] = RequirementsResult(
            project=name,
            components=components,
            health=str(payload.get("health", "unknown") or "unknown"),
            failures=list(payload.get("failures", [])),
        )
    return RunState(
        run_id=data["run_id"],
        mode=data["mode"],
        services=services,
        requirements=requirements,
        pointers=dict(data.get("pointers", {})),
        metadata=dict(data.get("metadata", {})),
    )


def load_legacy_shell_state(path: str, *, allowed_root: str | None = None) -> RunState:
    state_path = Path(path)
    _validate_state_path(state_path, allowed_root=allowed_root)

    key_values, arrays, assoc = _parse_shell_state_payload(state_path.read_text(encoding="utf-8"))

    run_id = key_values.get("RUN_ID") or key_values.get("SESSION_ID") or key_values.get("TIMESTAMP") or state_path.stem
    trees_mode = parse_bool(key_values.get("TREES_MODE"), False)
    mode = "trees" if trees_mode else "main"

    services = _services_from_declare_payload(arrays, assoc)
    services.update(_services_from_flat_legacy_assignments(key_values))

    pointers = {"legacy_state_path": str(state_path)}
    if "RUN_LOGS_DIR" in key_values:
        pointers["legacy_logs_dir"] = key_values["RUN_LOGS_DIR"]

    return RunState(
        run_id=run_id,
        mode=mode,
        services=services,
        requirements={},
        pointers=pointers,
        metadata={"legacy_state": True},
    )


def load_state_from_pointer(pointer_path: str, *, allowed_root: str | None = None) -> RunState:
    pointer = Path(pointer_path)
    _validate_state_path(pointer, allowed_root=allowed_root)

    raw = pointer.read_text(encoding="utf-8").splitlines()
    target_line = ""
    for line in raw:
        stripped = line.strip()
        if stripped:
            target_line = stripped
            break
    if not target_line:
        raise StateValidationError(f"pointer file is empty: {pointer}")

    target_path = Path(target_line).expanduser()
    if not target_path.is_absolute():
        target_path = (pointer.parent / target_path).resolve()

    if target_path.suffix == ".json":
        return load_state(str(target_path), allowed_root=allowed_root)
    return load_legacy_shell_state(str(target_path), allowed_root=allowed_root)


def merge_states(states: list[RunState]) -> RunState:
    if not states:
        raise StateValidationError("at least one state is required")
    merged_services: dict[str, ServiceRecord] = {}
    merged_requirements: dict[str, RequirementsResult] = {}
    merged_pointers: dict[str, str] = {}
    merged_metadata: dict[str, object] = {}
    for state in states:
        merged_services.update(state.services)
        merged_requirements.update(state.requirements)
        merged_pointers.update(state.pointers)
        merged_metadata.update(state.metadata)
    latest = states[-1]
    merged = RunState(
        run_id=latest.run_id,
        mode=latest.mode,
        services=merged_services,
        requirements=merged_requirements,
        pointers=merged_pointers,
        metadata=merged_metadata,
    )
    # Deterministic key order for stable writes and debugging diffs.
    merged.services = dict(sorted(merged.services.items(), key=lambda item: item[0]))
    merged.requirements = dict(sorted(merged.requirements.items(), key=lambda item: item[0]))
    merged.pointers = dict(sorted(merged.pointers.items(), key=lambda item: item[0]))
    merged.metadata = dict(sorted(merged.metadata.items(), key=lambda item: item[0]))
    return merged


def dump_state(state: RunState, path: str) -> None:
    serializable = state_to_dict(state)
    Path(path).write_text(json.dumps(serializable, indent=2, sort_keys=True), encoding="utf-8")


def state_to_dict(state: RunState) -> dict[str, object]:
    return {
        "schema_version": 1,
        "run_id": state.run_id,
        "mode": state.mode,
        "services": {
            name: {
                "type": svc.type,
                "cwd": svc.cwd,
                "pid": svc.pid,
                "requested_port": svc.requested_port,
                "actual_port": svc.actual_port,
                "log_path": svc.log_path,
                "status": svc.status,
                "synthetic": svc.synthetic,
                "started_at": svc.started_at,
                "listener_pids": svc.listener_pids,
            }
            for name, svc in state.services.items()
        },
        "requirements": {
            project: {
                "components": {dependency_id: req.component(dependency_id) for dependency_id in dependency_ids()},
                "db": req.db,
                "redis": req.redis,
                "supabase": req.supabase,
                "n8n": req.n8n,
                "health": req.health,
                "failures": req.failures,
            }
            for project, req in state.requirements.items()
        },
        "pointers": state.pointers,
        "metadata": state.metadata,
    }


def _validate_state_payload(payload: object) -> None:
    if not isinstance(payload, dict):
        raise StateValidationError("state payload must be a JSON object")

    schema_version = payload.get("schema_version")
    if schema_version != 1:
        raise StateValidationError("state schema_version must be 1")

    if not isinstance(payload.get("run_id"), str) or not payload["run_id"].strip():
        raise StateValidationError("state run_id is required")

    mode = payload.get("mode")
    if mode not in {"main", "trees"}:
        raise StateValidationError("state mode must be 'main' or 'trees'")

    if "services" in payload and not isinstance(payload["services"], dict):
        raise StateValidationError("state services must be an object")
    if "requirements" in payload and not isinstance(payload["requirements"], dict):
        raise StateValidationError("state requirements must be an object")
    if "pointers" in payload and not isinstance(payload["pointers"], dict):
        raise StateValidationError("state pointers must be an object")
    if "metadata" in payload and not isinstance(payload["metadata"], dict):
        raise StateValidationError("state metadata must be an object")


def _validate_state_path(state_path: Path, *, allowed_root: str | None) -> None:
    if not state_path.exists():
        raise StateValidationError(f"state file does not exist: {state_path}")
    if allowed_root is None:
        return
    root = Path(allowed_root).resolve()
    resolved = state_path.resolve()
    if root not in resolved.parents and resolved != root:
        raise StateValidationError("state path is outside allowed_root")


def _parse_listener_pids(value: object) -> list[int] | None:
    if not isinstance(value, list):
        return None
    parsed: list[int] = []
    for item in value:
        try:
            pid = int(item)
        except (TypeError, ValueError):
            continue
        if pid > 0:
            parsed.append(pid)
    if not parsed:
        return None
    return sorted(set(parsed))


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _parse_shell_state_payload(raw: str) -> tuple[dict[str, str], dict[str, list[str]], dict[str, dict[str, str]]]:
    key_values: dict[str, str] = {}
    arrays: dict[str, list[str]] = {}
    assoc: dict[str, dict[str, str]] = {}
    lines = raw.splitlines()

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line or line.startswith("#"):
            continue

        declare_array_match = re.match(r"^declare\s+-a\s+([A-Za-z_][A-Za-z0-9_]*)=\($", line)
        if declare_array_match:
            name = declare_array_match.group(1)
            values: list[str] = []
            while i < len(lines):
                item_line = lines[i].strip()
                i += 1
                if item_line == ")":
                    break
                if not item_line:
                    continue
                values.append(_decode_shell_token(item_line))
            arrays[name] = values
            continue

        declare_assoc_match = re.match(r"^declare\s+-A\s+([A-Za-z_][A-Za-z0-9_]*)=\($", line)
        if declare_assoc_match:
            name = declare_assoc_match.group(1)
            values: dict[str, str] = {}
            while i < len(lines):
                item_line = lines[i].strip()
                i += 1
                if item_line == ")":
                    break
                if not item_line:
                    continue
                entry_match = re.match(r"^\[(.+?)\]=(.*)$", item_line)
                if not entry_match:
                    continue
                key = _decode_shell_token(entry_match.group(1).strip())
                value = _decode_shell_token(entry_match.group(2).strip())
                values[key] = value
            assoc[name] = values
            continue

        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key_values[key.strip()] = _decode_shell_token(value.strip())

    return key_values, arrays, assoc


def _decode_shell_token(token: str) -> str:
    stripped = token.strip()
    if not stripped:
        return ""
    try:
        parsed = shlex.split(stripped, posix=True)
    except ValueError:
        return _strip_quotes(stripped).replace("\\ ", " ")
    if not parsed:
        return ""
    if len(parsed) == 1:
        return parsed[0]
    return " ".join(parsed)


def _service_type_from_name(name: str) -> str:
    lowered = name.lower()
    if lowered.endswith(" backend"):
        return "backend"
    if lowered.endswith(" frontend"):
        return "frontend"
    return "unknown"


def _service_name_from_service_entry(entry: str) -> str:
    if "|" in entry:
        name = entry.split("|", 1)[0].strip()
        if name:
            return name
    return entry.strip()


def _service_rows_from_flat_legacy_assignments(key_values: dict[str, str]) -> dict[str, dict[str, str]]:
    service_rows: dict[str, dict[str, str]] = {}
    pattern = re.compile(r"^SERVICE_(?P<name>.+)_(?P<field>TYPE|CWD|PID|REQUESTED_PORT|ACTUAL_PORT|STATUS|LOG_PATH)$")
    for key, value in key_values.items():
        match = pattern.match(key)
        if not match:
            continue
        raw_name = match.group("name")
        field = match.group("field").lower()
        service_rows.setdefault(raw_name, {})[field] = value
    return service_rows


def _services_from_flat_legacy_assignments(key_values: dict[str, str]) -> dict[str, ServiceRecord]:
    service_rows = _service_rows_from_flat_legacy_assignments(key_values)
    services: dict[str, ServiceRecord] = {}
    for raw_name, row in service_rows.items():
        display_name = raw_name.replace("_", " ")
        services[display_name] = ServiceRecord(
            name=display_name,
            type=row.get("type", _service_type_from_name(display_name)),
            cwd=row.get("cwd", ""),
            pid=parse_int_or_none(row.get("pid")),
            requested_port=parse_int_or_none(row.get("requested_port")),
            actual_port=parse_int_or_none(row.get("actual_port")),
            log_path=row.get("log_path"),
            status=row.get("status", "unknown"),
        )
    return services


def _services_from_declare_payload(
    arrays: dict[str, list[str]],
    assoc: dict[str, dict[str, str]],
) -> dict[str, ServiceRecord]:
    services: dict[str, ServiceRecord] = {}
    service_entries = arrays.get("services", [])
    service_info = assoc.get("service_info", {})
    actual_ports = assoc.get("actual_ports", {})

    for entry in service_entries:
        name = _service_name_from_service_entry(entry)
        if not name:
            continue
        info_fields = (service_info.get(name, "") or "").split("|")
        pid = parse_int_or_none(info_fields[0] if len(info_fields) > 0 else None)
        requested_port = parse_int_or_none(info_fields[1] if len(info_fields) > 1 else None)
        log_path = info_fields[2] if len(info_fields) > 2 and info_fields[2] else None
        service_type = info_fields[3] if len(info_fields) > 3 and info_fields[3] else _service_type_from_name(name)
        cwd = info_fields[4] if len(info_fields) > 4 else ""
        actual_port = parse_int_or_none(actual_ports.get(name))
        if actual_port is None:
            actual_port = requested_port
        services[name] = ServiceRecord(
            name=name,
            type=service_type,
            cwd=cwd,
            pid=pid,
            requested_port=requested_port,
            actual_port=actual_port,
            log_path=log_path,
            status="running" if pid is not None else "unknown",
        )

    for name, info in service_info.items():
        if name in services:
            continue
        info_fields = info.split("|")
        pid = parse_int_or_none(info_fields[0] if len(info_fields) > 0 else None)
        requested_port = parse_int_or_none(info_fields[1] if len(info_fields) > 1 else None)
        log_path = info_fields[2] if len(info_fields) > 2 and info_fields[2] else None
        service_type = info_fields[3] if len(info_fields) > 3 and info_fields[3] else _service_type_from_name(name)
        cwd = info_fields[4] if len(info_fields) > 4 else ""
        actual_port = parse_int_or_none(actual_ports.get(name))
        if actual_port is None:
            actual_port = requested_port
        services[name] = ServiceRecord(
            name=name,
            type=service_type,
            cwd=cwd,
            pid=pid,
            requested_port=requested_port,
            actual_port=actual_port,
            log_path=log_path,
            status="running" if pid is not None else "unknown",
        )

    return services
