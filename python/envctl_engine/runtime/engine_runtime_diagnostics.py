from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def parity_manifest_is_complete(runtime: Any) -> bool:
    payload = read_parity_manifest(runtime)
    if payload is None:
        return False
    commands = payload.get("commands")
    if not isinstance(commands, dict):
        return False
    return all(str(status) == "python_complete" for status in commands.values())


def parity_manifest_info(runtime: Any) -> dict[str, str]:
    manifest_path = runtime.config.base_dir / "contracts" / "python_engine_parity_manifest.json"
    if not manifest_path.is_file():
        return {
            "path": str(manifest_path),
            "generated_at": "missing",
            "sha256": "missing",
        }
    text = manifest_path.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
        generated_at = str(payload.get("generated_at", "unknown"))
    except (OSError, json.JSONDecodeError):
        generated_at = "invalid"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {
        "path": str(manifest_path),
        "generated_at": generated_at,
        "sha256": digest,
    }


def read_parity_manifest(runtime: Any) -> dict[str, object] | None:
    manifest_path = runtime.config.base_dir / "contracts" / "python_engine_parity_manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def lock_health_summary(runtime: Any) -> str:
    locks = list(runtime.port_planner.lock_dir.glob("*.lock"))
    stale = 0
    for lock_path in locks:
        if runtime.port_planner._lock_is_stale(lock_path):  # noqa: SLF001
            stale += 1
    return f"total={len(locks)} stale={stale}"


def pointer_status_summary(runtime: Any) -> str:
    pointers = [
        runtime.runtime_root / ".last_state",
        runtime.runtime_root / ".last_state.main",
        *sorted(runtime.runtime_root.glob(".last_state.trees.*")),
    ]
    valid = 0
    broken = 0
    for pointer in pointers:
        if not pointer.exists():
            continue
        try:
            first = _first_pointer_target(pointer)
            if not first:
                broken += 1
                continue
            target = Path(first).expanduser()
            if not target.is_absolute():
                target = (pointer.parent / target).resolve()
            if target.exists():
                valid += 1
            else:
                broken += 1
        except OSError:
            broken += 1
    return f"valid={valid} broken={broken}"


def _first_pointer_target(pointer: Path) -> str:
    for line in pointer.read_text(encoding="utf-8").splitlines():
        candidate = line.strip()
        if candidate:
            return candidate
    return ""
