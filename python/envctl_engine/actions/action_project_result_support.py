from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from envctl_engine.state.runtime_map import build_runtime_map
from envctl_engine.test_output.parser_base import strip_ansi


def clear_dashboard_pr_cache(runtime_raw: object) -> None:
    cache = getattr(runtime_raw, "_dashboard_pr_url_cache", None)
    if isinstance(cache, dict):
        cache.clear()


def first_output_line(output: object) -> str:
    for raw in str(output or "").splitlines():
        text = raw.strip()
        if text:
            return text
    return ""


def project_action_success_status(*, command_name: str, completed: Any) -> str:
    if command_name != "pr":
        return "success"
    output = strip_ansi(str(getattr(completed, "stdout", "") or ""))
    first_line = first_output_line(output)
    if first_line.startswith("Skipping ") and "detached HEAD" in output:
        return "skipped"
    return "success"


def review_success_artifact_paths(*, stdout: object, stderr: object) -> dict[str, object]:
    output_parts = [str(stdout or ""), str(stderr or "")]
    cleaned = strip_ansi("\n".join(part for part in output_parts if str(part or "").strip()))
    lines = [line.rstrip() for line in cleaned.splitlines()]
    label_map = {
        "output directory": "output_dir",
        "summary file": "summary_path",
        "full review bundle": "bundle_path",
    }
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
            parsed[key] = candidate
            break
    return parsed


def write_project_action_failure_report(
    *,
    state_repository: object,
    run_id: str,
    project_name: str,
    command_name: str,
    output: str,
) -> Path:
    results_root = state_repository.run_dir_path(run_id)  # type: ignore[attr-defined]
    results_root.mkdir(parents=True, exist_ok=True)
    safe_project = project_name.replace(" ", "_")
    report_path = results_root / f"{safe_project}_{command_name}.txt"
    report_path.write_text((output or "Command failed.").rstrip() + "\n", encoding="utf-8")
    return report_path


def persist_project_action_result(
    *,
    command_name: str,
    mode: str,
    project_name: str,
    status: str,
    error_output: str,
    extra_entry: Mapping[str, object] | None,
    load_existing_state: Callable[[str], object | None],
    state_repository: object,
    emit: Callable[..., None],
    migrate_env_metadata: Mapping[str, object] | None,
    failure_summary_lines: Callable[..., list[str]],
    migrate_failure_headline: Callable[[str], str],
) -> None:
    state = load_existing_state(mode)
    if state is None:
        return
    metadata_raw = state.metadata.get("project_action_reports")  # type: ignore[attr-defined]
    metadata = dict(metadata_raw) if isinstance(metadata_raw, dict) else {}
    project_raw = metadata.get(project_name)
    project_metadata = dict(project_raw) if isinstance(project_raw, dict) else {}
    entry: dict[str, object] = {
        "status": status,
        "updated_at": datetime.now(tz=UTC).isoformat(),
    }
    migrate_metadata = dict(migrate_env_metadata) if isinstance(migrate_env_metadata, Mapping) else None
    if migrate_metadata:
        entry["backend_env"] = migrate_metadata
    if isinstance(extra_entry, Mapping):
        entry.update({str(key): value for key, value in extra_entry.items()})
    if status == "failed":
        clean_output = strip_ansi(str(error_output or "")).strip()
        summary_lines = failure_summary_lines(
            command_name=command_name,
            error_output=clean_output,
            migrate_env_metadata=migrate_metadata,
        )
        summary_text = "\n".join(summary_lines).strip() or "Command failed."
        report_path = write_project_action_failure_report(
            state_repository=state_repository,
            run_id=state.run_id,  # type: ignore[attr-defined]
            project_name=project_name,
            command_name=command_name,
            output=clean_output,
        )
        if command_name == "migrate":
            headline = migrate_failure_headline(clean_output)
            if headline:
                entry["headline"] = headline
        entry["summary"] = summary_text
        entry["report_path"] = str(report_path)
    project_metadata[command_name] = entry
    metadata[project_name] = project_metadata
    state.metadata["project_action_reports"] = metadata  # type: ignore[attr-defined]
    state_repository.save_resume_state(  # type: ignore[attr-defined]
        state=state,
        emit=emit,
        runtime_map_builder=build_runtime_map,
    )
