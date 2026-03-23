from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any


GAP_REPORT_RELATIVE_PATH = Path("contracts/python_runtime_gap_report.json")
FEATURE_MATRIX_RELATIVE_PATH = Path("contracts/runtime_feature_matrix.json")
PARITY_MANIFEST_RELATIVE_PATH = Path("contracts/python_engine_parity_manifest.json")


@dataclass(slots=True)
class RuntimeReadinessResult:
    passed: bool
    report_path: Path
    report_generated_at: str
    report_sha256: str
    matrix_path: Path
    matrix_generated_at: str
    matrix_sha256: str
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
    matrix_path = repo_root / FEATURE_MATRIX_RELATIVE_PATH
    manifest_path = repo_root / PARITY_MANIFEST_RELATIVE_PATH
    errors: list[str] = []
    warnings: list[str] = []

    report_payload = _load_json(report_path, label="runtime gap report", errors=errors)
    matrix_payload = _load_json(matrix_path, label="runtime feature matrix", errors=errors)
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

    matrix_generated_at = (
        str(matrix_payload.get("generated_at", "")).strip() if isinstance(matrix_payload, dict) else ""
    )
    matrix_text = _canonical_json_text(matrix_payload)
    matrix_sha256 = hashlib.sha256(matrix_text.encode("utf-8")).hexdigest() if matrix_text else ""
    report_matrix_generated_at = (
        str(report_payload.get("matrix_generated_at", "")).strip() if isinstance(report_payload, dict) else ""
    )
    report_matrix_sha256 = (
        str(report_payload.get("matrix_sha256", "")).strip() if isinstance(report_payload, dict) else ""
    )
    if matrix_generated_at and report_matrix_generated_at != matrix_generated_at:
        errors.append("runtime feature matrix generated_at mismatch between gap report and runtime feature matrix")
    if matrix_sha256 and report_matrix_sha256 != matrix_sha256:
        errors.append("runtime feature matrix sha256 mismatch between gap report and runtime feature matrix")

    report_text = report_path.read_text(encoding="utf-8") if report_path.is_file() else ""
    manifest_text = manifest_path.read_text(encoding="utf-8") if manifest_path.is_file() else ""
    report_generated_at = (
        str(report_payload.get("generated_at", "")).strip() if isinstance(report_payload, dict) else ""
    )
    manifest_generated_at = str(manifest_payload.get("generated_at", "")).strip() if isinstance(manifest_payload, dict) else ""

    return RuntimeReadinessResult(
        passed=not errors,
        report_path=report_path,
        report_generated_at=report_generated_at,
        report_sha256=hashlib.sha256(report_text.encode("utf-8")).hexdigest() if report_text else "",
        matrix_path=matrix_path,
        matrix_generated_at=matrix_generated_at,
        matrix_sha256=matrix_sha256,
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
        "passed": bool(getattr(result, "passed", False)),
        "errors": list(getattr(result, "errors", [])),
        "warnings": list(getattr(result, "warnings", [])),
        "gap_report": {
            "path": str(getattr(result, "report_path", Path())),
            "generated_at": str(getattr(result, "report_generated_at", "")),
            "sha256": str(getattr(result, "report_sha256", "")),
        },
        "feature_matrix": {
            "path": str(getattr(result, "matrix_path", Path())),
            "generated_at": str(getattr(result, "matrix_generated_at", "")),
            "sha256": str(getattr(result, "matrix_sha256", "")),
        },
        "parity_manifest": {
            "path": str(getattr(result, "parity_manifest_path", Path())),
            "generated_at": str(getattr(result, "parity_manifest_generated_at", "")),
            "sha256": str(getattr(result, "parity_manifest_sha256", "")),
        },
        "summary": {
            "blocking_gap_count": int(getattr(result, "blocking_gap_count", 0)),
            "high_gap_count": int(getattr(result, "high_gap_count", 0)),
            "medium_gap_count": int(getattr(result, "medium_gap_count", 0)),
            "low_gap_count": int(getattr(result, "low_gap_count", 0)),
            "total_gap_count": int(getattr(result, "total_gap_count", 0)),
        },
    }


def _canonical_json_text(payload: object) -> str:
    if not isinstance(payload, dict) or not payload:
        return ""
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


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
