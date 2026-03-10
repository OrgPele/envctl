from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any


GAP_REPORT_RELATIVE_PATH = Path("contracts/python_runtime_gap_report.json")
PARITY_MANIFEST_RELATIVE_PATH = Path("contracts/python_engine_parity_manifest.json")


@dataclass(slots=True)
class RuntimeReadinessResult:
    passed: bool
    report_path: Path
    report_generated_at: str
    report_sha256: str
    parity_manifest_path: Path
    parity_manifest_generated_at: str
    parity_manifest_sha256: str
    blocking_gap_count: int
    high_gap_count: int
    medium_gap_count: int
    low_gap_count: int
    total_gap_count: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    report_payload: dict[str, Any] = field(default_factory=dict)


def evaluate_runtime_readiness(
    repo_root: Path,
    *,
    require_gap_free: bool = True,
    require_manifest_complete: bool = True,
) -> RuntimeReadinessResult:
    report_path = repo_root / GAP_REPORT_RELATIVE_PATH
    manifest_path = repo_root / PARITY_MANIFEST_RELATIVE_PATH
    errors: list[str] = []
    warnings: list[str] = []

    report_payload = _load_json(report_path, label="runtime gap report", errors=errors)
    manifest_payload = _load_json(manifest_path, label="parity manifest", errors=errors)

    report_summary = report_payload.get("summary", {}) if isinstance(report_payload, dict) else {}
    high_medium = _int_value(report_summary.get("high_or_medium_gap_count"))
    by_severity = report_summary.get("by_severity", {}) if isinstance(report_summary, dict) else {}
    high_count = _dict_int(by_severity, "high")
    medium_count = _dict_int(by_severity, "medium")
    low_count = _dict_int(by_severity, "low")
    gap_count = _int_value(report_summary.get("gap_count"))

    if require_gap_free and high_medium > 0:
        errors.append(f"python runtime gap report has blocking gaps: {high_medium}")

    if require_manifest_complete and not _manifest_is_complete(manifest_payload):
        errors.append("parity manifest is not fully python_complete")

    report_text = report_path.read_text(encoding="utf-8") if report_path.is_file() else ""
    manifest_text = manifest_path.read_text(encoding="utf-8") if manifest_path.is_file() else ""
    report_generated_at = str(report_payload.get("generated_at", "")).strip() if isinstance(report_payload, dict) else ""
    manifest_generated_at = str(manifest_payload.get("generated_at", "")).strip() if isinstance(manifest_payload, dict) else ""

    return RuntimeReadinessResult(
        passed=not errors,
        report_path=report_path,
        report_generated_at=report_generated_at,
        report_sha256=hashlib.sha256(report_text.encode("utf-8")).hexdigest() if report_text else "",
        parity_manifest_path=manifest_path,
        parity_manifest_generated_at=manifest_generated_at,
        parity_manifest_sha256=hashlib.sha256(manifest_text.encode("utf-8")).hexdigest() if manifest_text else "",
        blocking_gap_count=high_medium,
        high_gap_count=high_count,
        medium_gap_count=medium_count,
        low_gap_count=low_count,
        total_gap_count=gap_count,
        errors=errors,
        warnings=warnings,
        report_payload=report_payload if isinstance(report_payload, dict) else {},
    )


def build_runtime_readiness_report(result: RuntimeReadinessResult) -> dict[str, Any]:
    return {
        "passed": result.passed,
        "errors": list(result.errors),
        "warnings": list(result.warnings),
        "gap_report": {
            "path": str(result.report_path),
            "generated_at": result.report_generated_at,
            "sha256": result.report_sha256,
        },
        "parity_manifest": {
            "path": str(result.parity_manifest_path),
            "generated_at": result.parity_manifest_generated_at,
            "sha256": result.parity_manifest_sha256,
        },
        "summary": {
            "blocking_gap_count": result.blocking_gap_count,
            "high_gap_count": result.high_gap_count,
            "medium_gap_count": result.medium_gap_count,
            "low_gap_count": result.low_gap_count,
            "total_gap_count": result.total_gap_count,
        },
    }


def _load_json(path: Path, *, label: str, errors: list[str]) -> dict[str, Any]:
    if not path.is_file():
        errors.append(f"{label} missing: {path}")
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{label} unreadable: {exc}")
        return {}
    if not isinstance(payload, dict):
        errors.append(f"{label} must be a JSON object: {path}")
        return {}
    return payload


def _manifest_is_complete(payload: dict[str, Any]) -> bool:
    commands = payload.get("commands")
    modes = payload.get("modes")
    if not isinstance(commands, dict) or not isinstance(modes, dict):
        return False
    command_complete = all(str(status).strip() == "python_complete" for status in commands.values())
    mode_complete = True
    for mode_payload in modes.values():
        if not isinstance(mode_payload, dict):
            return False
        if not all(str(status).strip() == "python_complete" for status in mode_payload.values()):
            mode_complete = False
            break
    return command_complete and mode_complete


def _int_value(raw: object) -> int:
    try:
        return int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _dict_int(payload: object, key: str) -> int:
    if not isinstance(payload, dict):
        return 0
    return _int_value(payload.get(key))
