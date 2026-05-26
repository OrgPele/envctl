from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from envctl_engine.runtime.runtime_context import (
    run_dir_path,
    save_resume_state,
)
from envctl_engine.shared.artifact_names import project_command_artifact_path
from envctl_engine.test_output.parser_base import strip_ansi


def build_project_action_success_handler(
    *,
    command_name: str,
    mode: str,
    interactive_command: bool,
    clear_dashboard_pr_cache: Callable[[], None],
    project_action_success_status_fn: Callable[..., str],
    review_success_artifact_paths_fn: Callable[..., dict[str, object]],
    persist_project_action_result_fn: Callable[..., None],
    first_output_line_fn: Callable[[object], str],
    emit_status: Callable[[str], None],
) -> Callable[[object, Any], None]:
    def handle_success(context: object, completed: Any) -> None:
        clear_dashboard_pr_cache()
        status = project_action_success_status_fn(command_name=command_name, completed=completed)
        extra_entry: dict[str, object] | None = None
        if command_name == "review" and status == "success":
            extra_entry = review_success_artifact_paths_fn(
                stdout=getattr(completed, "stdout", ""),
                stderr=getattr(completed, "stderr", ""),
            )
        persist_project_action_result_fn(
            command_name=command_name,
            mode=mode,
            project_name=str(getattr(context, "name")),
            status=status,
            error_output="",
            extra_entry=extra_entry,
        )
        if command_name != "pr" or not interactive_command or status != "success":
            return
        url = first_output_line_fn(getattr(completed, "stdout", ""))
        if url:
            emit_status(f"PR created: {url}")

    return handle_success


def build_project_action_failure_handler(
    *,
    command_name: str,
    mode: str,
    persist_project_action_result_fn: Callable[..., None],
) -> Callable[[object, str], None]:
    def handle_failure(context: object, error_output: str) -> None:
        persist_project_action_result_fn(
            command_name=command_name,
            mode=mode,
            project_name=str(getattr(context, "name")),
            status="failed",
            error_output=error_output,
        )

    return handle_failure


def review_success_artifact_paths(*, stdout: object, stderr: object) -> dict[str, object]:
    output_parts = [str(stdout or ""), str(stderr or "")]
    cleaned = strip_ansi("\n".join(part for part in output_parts if str(part or "").strip()))
    lines = [line.rstrip() for line in cleaned.splitlines()]
    label_map = {
        "output directory": "output_dir",
        "summary file": "summary_path",
        "full review bundle": "bundle_path",
    }
    artifact_labels = set(label_map)
    parsed: dict[str, object] = {}
    for index, raw_line in enumerate(lines):
        label = raw_line.strip().lower()
        key = label_map.get(label)
        if not key:
            continue
        for follow_line in lines[index + 1 :]:
            candidate = follow_line.strip()
            if not candidate:
                continue
            if candidate.lower() in artifact_labels:
                break
            parsed[key] = candidate
            break
    return parsed


def write_project_action_failure_report(
    runtime: Any,
    *,
    run_id: str,
    project_name: str,
    command_name: str,
    output: str,
) -> Path:
    results_root = run_dir_path(runtime, run_id)
    results_root.mkdir(parents=True, exist_ok=True)
    report_path = project_command_artifact_path(results_root, project_name=project_name, command_name=command_name)
    report_path.write_text((output or "Command failed.").rstrip() + "\n", encoding="utf-8")
    return report_path


def first_output_line(output: object) -> str:
    for raw in str(output or "").splitlines():
        text = raw.strip()
        if text:
            return text
    return ""


def ship_action_payload(output: object) -> dict[str, object]:
    text = strip_ansi(str(output or ""))
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            parsed, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and parsed.get("contract_version") == "envctl.ship.v1":
            return {str(key): value for key, value in parsed.items()}
    return {}


def ship_action_status(completed: Any) -> str:
    payload = ship_action_payload(getattr(completed, "stdout", ""))
    status = str(payload.get("status") or "").strip()
    return status or "success"


def ship_action_status_message(project_name: str, completed: Any) -> str:
    payload = ship_action_payload(getattr(completed, "stdout", ""))
    status = str(payload.get("status") or "").strip() or "success"
    operation_statuses = payload.get("operation_statuses")
    operation_parts: list[str] = []
    if isinstance(operation_statuses, Mapping):
        for key in ("commit", "push", "pr", "merge_conflicts", "checks"):
            value = str(operation_statuses.get(key) or "").strip()
            if value:
                operation_parts.append(f"{key}={value}")
    operations = f" ({', '.join(operation_parts)})" if operation_parts else ""
    pr_url = str(payload.get("pr_url") or "").strip()
    pr_suffix = f" {pr_url}" if pr_url else ""
    return f"ship handoff status for {project_name}: {status}{operations}{pr_suffix}"


def project_action_success_status(*, command_name: str, completed: Any) -> str:
    if command_name == "ship":
        return ship_action_status(completed)
    if command_name != "pr":
        return "success"
    output = strip_ansi(str(getattr(completed, "stdout", "") or ""))
    first_line = first_output_line(output)
    if first_line.startswith("Skipping ") and "detached HEAD" in output:
        return "skipped"
    return "success"


def persist_project_action_result(
    *,
    runtime: Any,
    command_name: str,
    mode: str,
    project_name: str,
    status: str,
    error_output: str,
    migrate_env_contracts: Mapping[str, Mapping[str, object]],
    failure_summary_lines: Callable[..., list[str]],
    failure_headline: Callable[[str], str],
    runtime_map_builder: Callable[[object], dict[str, object]],
    extra_entry: Mapping[str, object] | None = None,
) -> None:
    state = runtime.load_existing_state(mode=mode)
    if state is None:
        return
    metadata_raw = state.metadata.get("project_action_reports")
    metadata = dict(metadata_raw) if isinstance(metadata_raw, dict) else {}
    project_raw = metadata.get(project_name)
    project_metadata = dict(project_raw) if isinstance(project_raw, dict) else {}
    entry: dict[str, object] = {
        "status": status,
        "updated_at": datetime.now(tz=UTC).isoformat(),
    }
    migrate_env_metadata = dict(migrate_env_contracts.get(project_name, {})) if command_name == "migrate" else None
    if migrate_env_metadata:
        entry["backend_env"] = migrate_env_metadata
    if isinstance(extra_entry, Mapping):
        entry.update({str(key): value for key, value in extra_entry.items()})
    if status == "failed":
        clean_output = strip_ansi(str(error_output or "")).strip()
        summary_lines = failure_summary_lines(
            command_name=command_name,
            error_output=clean_output,
            migrate_env_metadata=migrate_env_metadata,
        )
        summary_text = "\n".join(summary_lines).strip() or "Command failed."
        report_path = write_project_action_failure_report(
            runtime,
            run_id=state.run_id,
            project_name=project_name,
            command_name=command_name,
            output=clean_output,
        )
        if command_name == "migrate":
            headline = failure_headline(clean_output)
            if headline:
                entry["headline"] = headline
        entry["summary"] = summary_text
        entry["report_path"] = str(report_path)
    project_metadata[command_name] = entry
    metadata[project_name] = project_metadata
    state.metadata["project_action_reports"] = metadata
    save_resume_state(
        runtime,
        state=state,
        runtime_map_builder=runtime_map_builder,
    )
