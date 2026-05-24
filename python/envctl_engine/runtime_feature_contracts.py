from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from envctl_engine.runtime.command_router import list_supported_commands, list_supported_flag_tokens


ALLOWED_PARITY_STATUSES = {"verified_python", "shell_only", "unverified", "python_partial"}
ALLOWED_SEVERITIES = {"high", "medium", "low"}


def _documented_flag_tokens(repo_root: Path) -> list[str]:
    docs_path = repo_root / "docs" / "reference" / "important-flags.md"
    if not docs_path.is_file():
        return []
    text = docs_path.read_text(encoding="utf-8")
    return sorted(set(re.findall(r"--[a-z0-9][a-z0-9-]*", text)))


def _feature_row(index: int, feature: Any, *, repo_root: Path, command: str | None = None) -> dict[str, Any]:
    shell_refs = [ref for ref in feature.shell_source_of_truth if (repo_root / ref).exists()]
    evidence_refs = [ref for ref in feature.evidence_tests if (repo_root / ref).exists()]
    row = {
        "id": f"F-{index:03d}",
        "area": feature.area,
        "feature": feature.feature,
        "user_visible": feature.user_visible,
        "shell_source_of_truth": shell_refs,
        "python_source_of_truth": list(feature.python_source_of_truth),
        "evidence_tests": evidence_refs,
        "parity_status": feature.parity_status,
        "notes": feature.notes,
    }
    if command is not None:
        row["command"] = command
    if feature.current_behavior:
        row["current_behavior"] = feature.current_behavior
    if feature.missing_python_behavior:
        row["missing_python_behavior"] = feature.missing_python_behavior
    if feature.python_owner_module:
        row["python_owner_module"] = feature.python_owner_module
    if feature.proposed_tests:
        row["proposed_tests"] = list(feature.proposed_tests)
    if feature.severity:
        row["severity"] = feature.severity
    if feature.rollout_risk:
        row["rollout_risk"] = feature.rollout_risk
    if feature.wave:
        row["wave"] = feature.wave
    return row


def build_runtime_feature_matrix_from_definitions(
    *,
    repo_root: Path,
    generated_at: str,
    command_definitions: dict[str, Any],
    extra_features: tuple[Any, ...],
) -> dict[str, Any]:
    python_commands = list_supported_commands()
    python_flags = list_supported_flag_tokens()
    features: list[dict[str, Any]] = []
    index = 1
    for command in list_supported_commands():
        features.append(_feature_row(index, command_definitions[command], repo_root=repo_root, command=command))
        index += 1
    for definition in extra_features:
        features.append(_feature_row(index, definition, repo_root=repo_root))
        index += 1
    return {
        "version": 1,
        "generated_at": generated_at,
        "inventory_sources": {
            "python_supported_commands": python_commands,
            "python_supported_flag_tokens": python_flags,
            "documented_flag_tokens": _documented_flag_tokens(repo_root),
        },
        "summary": {
            "feature_count": len(features),
            "user_visible_feature_count": sum(1 for feature in features if bool(feature["user_visible"])),
            "areas": dict(sorted(Counter(str(feature["area"]) for feature in features).items())),
            "parity_status": dict(sorted(Counter(str(feature["parity_status"]) for feature in features).items())),
        },
        "features": features,
    }


def build_python_runtime_gap_report(
    *, repo_root: Path, generated_at: str, matrix_payload: dict[str, Any]
) -> dict[str, Any]:
    del repo_root
    features = matrix_payload.get("features", [])
    gaps: list[dict[str, Any]] = []
    for feature in features if isinstance(features, list) else []:
        if not isinstance(feature, dict):
            continue
        parity_status = str(feature.get("parity_status", "")).strip()
        if parity_status == "verified_python":
            continue
        gap = {
            "feature_id": str(feature.get("id", "")),
            "area": str(feature.get("area", "")),
            "feature": str(feature.get("feature", "")),
            "parity_status": parity_status,
            "current_behavior": str(feature.get("current_behavior", feature.get("notes", ""))).strip(),
            "missing_python_behavior": str(feature.get("missing_python_behavior", "")).strip(),
            "python_owner_module": str(feature.get("python_owner_module", "")).strip(),
            "proposed_tests": list(feature.get("proposed_tests", [])),
            "severity": str(feature.get("severity", "low")).strip().lower(),
            "rollout_risk": str(feature.get("rollout_risk", "")).strip(),
            "shell_source_of_truth": list(feature.get("shell_source_of_truth", [])),
            "python_source_of_truth": list(feature.get("python_source_of_truth", [])),
            "evidence_tests": list(feature.get("evidence_tests", [])),
            "notes": str(feature.get("notes", "")).strip(),
            "wave": str(feature.get("wave", "")).strip() or _wave_for_area(str(feature.get("area", ""))),
        }
        gaps.append(gap)

    severity_counts = Counter(str(gap["severity"]) for gap in gaps)
    status_counts = Counter(str(gap["parity_status"]) for gap in gaps)
    area_counts = Counter(str(gap["area"]) for gap in gaps)
    matrix_rendered = json.dumps(matrix_payload, indent=2, sort_keys=True) + "\n"
    return {
        "version": 1,
        "generated_at": generated_at,
        "matrix_generated_at": matrix_payload.get("generated_at", ""),
        "matrix_sha256": hashlib.sha256(matrix_rendered.encode("utf-8")).hexdigest(),
        "summary": {
            "feature_count": len(features) if isinstance(features, list) else 0,
            "gap_count": len(gaps),
            "high_or_medium_gap_count": sum(1 for gap in gaps if str(gap["severity"]) in {"high", "medium"}),
            "by_status": dict(sorted(status_counts.items())),
            "by_severity": dict(sorted(severity_counts.items())),
            "by_area": dict(sorted(area_counts.items())),
        },
        "gaps": gaps,
    }


def render_python_runtime_gap_closure_plan(*, report_payload: dict[str, Any]) -> str:
    gaps = [gap for gap in report_payload.get("gaps", []) if isinstance(gap, dict)]
    summary = report_payload.get("summary", {})
    wave_order = ["Wave A", "Wave B", "Wave C", "Wave D", "Wave E"]
    wave_titles = {
        "Wave A": "Launcher, Help, and Install Parity",
        "Wave B": "Lifecycle, Planning, and Worktree Parity",
        "Wave C": "Requirements and Dependency Lifecycle Parity",
        "Wave D": "Action Command Parity",
        "Wave E": "Diagnostics, Inspection, and Artifact Parity",
    }
    wave_scope = {
        "Wave A": (
            "Close the remaining launcher-owned and help/install gaps without changing current user-visible behavior."
        ),
        "Wave B": (
            "Prove that lifecycle, planning, and worktree operations preserve the current behavior across startup, "
            "scale-down, and cleanup paths."
        ),
        "Wave C": "Finish the risky dependency and cleanup parity areas that still make shell a compatibility oracle.",
        "Wave D": (
            "Lock down action command contracts so test/review/pr/commit/migrate no longer depend on shell-era "
            "expectations."
        ),
        "Wave E": (
            "Retain only the diagnostics, dashboard, and artifact behavior that is truly part of the supported "
            "product contract."
        ),
    }
    grouped: dict[str, list[dict[str, Any]]] = {wave: [] for wave in wave_order}
    for gap in gaps:
        wave = str(gap.get("wave", "")).strip() or _wave_for_area(str(gap.get("area", "")))
        grouped.setdefault(wave, []).append(gap)

    lines = [
        "# Python Runtime Gap Closure Plan",
        "",
        "## Summary",
        "- Generated from `contracts/python_runtime_gap_report.json`.",
        f"- Total inventoried features: {summary.get('feature_count', 0)}",
        f"- Open gaps: {summary.get('gap_count', 0)}",
        f"- High or medium gaps: {summary.get('high_or_medium_gap_count', 0)}",
        "",
        (
            "This plan records the retained-behavior gaps that had to close before shell runtime retirement. "
            "Keep these contracts green without reintroducing shell governance."
        ),
        "",
        "## Shared Rules",
        "- Preserve current user-visible behavior while implementing each wave.",
        "- Mark a feature `verified_python` only after the behavior exists and the acceptance tests are in place.",
        "- Run full Python unittest discovery after each completed wave.",
        "",
        "## Wave Breakdown",
    ]
    for wave in wave_order:
        wave_gaps = grouped.get(wave, [])
        lines.extend(["", f"### {wave}: {wave_titles[wave]}", wave_scope[wave]])
        if not wave_gaps:
            lines.extend(["", "No currently reported gaps in this wave."])
            continue
        lines.extend(
            [
                "",
                "| ID | Severity | Area | Gap | Python Owner | Proposed Tests |",
                "|----|----------|------|-----|--------------|----------------|",
            ]
        )
        for gap in wave_gaps:
            tests = ", ".join(str(item) for item in gap.get("proposed_tests", []))
            lines.append(
                f"| {gap.get('feature_id', '')} | {gap.get('severity', '')} | {gap.get('area', '')} | "
                f"{gap.get('feature', '')} | {gap.get('python_owner_module', '')} | {tests} |"
            )
        lines.extend(["", "#### Required Work"])
        for gap in wave_gaps:
            lines.extend(
                [
                    f"- `{gap.get('feature_id', '')}` {gap.get('feature', '')}",
                    f"  Current behavior: {gap.get('current_behavior', '')}",
                    f"  Required Python work: {gap.get('missing_python_behavior', '')}",
                    f"  Rollout risk: {gap.get('rollout_risk', '')}",
                ]
            )
    lines.extend(
        [
            "",
            "## Completion Gate",
            "- All high and medium gaps are closed or explicitly accepted.",
            "- `contracts/runtime_feature_matrix.json` is updated so closed items are marked `verified_python`.",
            "- `contracts/python_runtime_gap_report.json` shows no remaining high or medium gaps.",
            "- Full Python unittest discovery passes.",
            "",
            "## Follow-Up Boundary",
            "Shell-runtime retirement follow-up should stay mechanical and must not reintroduce shell-era governance.",
            "",
        ]
    )
    return "\n".join(lines)


def _wave_for_area(area: str) -> str:
    if area in {"launcher", "cli"}:
        return "Wave A"
    if area in {"lifecycle", "planning"}:
        return "Wave B"
    if area == "requirements":
        return "Wave C"
    if area == "actions":
        return "Wave D"
    return "Wave E"


def validate_runtime_feature_matrix_payload(payload: dict[str, Any], *, repo_root: Path) -> None:
    features = payload.get("features")
    if not isinstance(features, list):
        raise ValueError("features must be a list")
    seen_ids: set[str] = set()
    supported_commands = set(list_supported_commands())
    command_features = {
        str(feature.get("command", "")).strip()
        for feature in features
        if isinstance(feature, dict) and str(feature.get("command", "")).strip()
    }
    missing_commands = supported_commands.difference(command_features)
    if missing_commands:
        raise ValueError(f"missing command features: {', '.join(sorted(missing_commands))}")
    for feature in features:
        if not isinstance(feature, dict):
            raise ValueError("feature rows must be objects")
        feature_id = str(feature.get("id", "")).strip()
        if not feature_id or feature_id in seen_ids:
            raise ValueError(f"duplicate or missing feature id: {feature_id}")
        seen_ids.add(feature_id)
        parity_status = str(feature.get("parity_status", "")).strip()
        if parity_status not in ALLOWED_PARITY_STATUSES:
            raise ValueError(f"invalid parity status for {feature_id}: {parity_status}")
        python_refs = [str(ref) for ref in feature.get("python_source_of_truth", [])]
        shell_refs = [str(ref) for ref in feature.get("shell_source_of_truth", [])]
        source_refs = shell_refs + python_refs
        if bool(feature.get("user_visible")) and not source_refs:
            raise ValueError(f"user-visible feature missing source references: {feature_id}")
        if not python_refs:
            raise ValueError(f"feature missing python source references: {feature_id}")
        for ref in python_refs:
            ref_path = repo_root / ref
            if not ref_path.exists():
                raise ValueError(f"missing referenced path for {feature_id}: {ref}")
        evidence_refs = [str(ref) for ref in feature.get("evidence_tests", [])]
        if parity_status == "verified_python" and not evidence_refs:
            raise ValueError(f"verified_python feature missing evidence tests: {feature_id}")
        if evidence_refs:
            existing_evidence = [ref for ref in evidence_refs if (repo_root / ref).exists()]
            if not existing_evidence:
                raise ValueError(f"no existing evidence tests remain for {feature_id}")


def validate_python_runtime_gap_report_payload(payload: dict[str, Any], *, matrix_payload: dict[str, Any]) -> None:
    gaps = payload.get("gaps")
    if not isinstance(gaps, list):
        raise ValueError("gaps must be a list")
    matrix_by_id = {
        str(feature.get("id", "")): feature
        for feature in matrix_payload.get("features", [])
        if isinstance(feature, dict)
    }
    for gap in gaps:
        if not isinstance(gap, dict):
            raise ValueError("gap rows must be objects")
        feature_id = str(gap.get("feature_id", "")).strip()
        if feature_id not in matrix_by_id:
            raise ValueError(f"gap references unknown feature id: {feature_id}")
        source_feature = matrix_by_id[feature_id]
        if str(source_feature.get("parity_status", "")) == "verified_python":
            raise ValueError(f"verified_python feature should not appear in gaps: {feature_id}")
        severity = str(gap.get("severity", "")).strip().lower()
        if severity not in ALLOWED_SEVERITIES:
            raise ValueError(f"invalid severity for gap {feature_id}: {severity}")
        if not str(gap.get("python_owner_module", "")).strip():
            raise ValueError(f"gap missing python owner module: {feature_id}")
        if not list(gap.get("proposed_tests", [])):
            raise ValueError(f"gap missing proposed tests: {feature_id}")


def default_timestamp() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()
