from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
from pathlib import Path
import subprocess
from typing import Any, Callable, Mapping

from envctl_engine.state.runtime_map import build_runtime_map
from envctl_engine.test_output.parser_base import strip_ansi

FailureSummaryBuilder = Callable[[str, str, Mapping[str, object] | None], list[str]]
MigrateHeadlineBuilder = Callable[[str], str]


def default_project_action_failure_summary_lines(
    command_name: str,  # noqa: ARG001
    error_output: str,
    migrate_env_metadata: Mapping[str, object] | None = None,  # noqa: ARG001
) -> list[str]:
    lines = [line.strip() for line in strip_ansi(error_output).splitlines() if line.strip()]
    return lines or ["Command failed."]


def default_migrate_failure_headline(error_output: str) -> str:
    lines = default_project_action_failure_summary_lines("migrate", error_output)
    return lines[0] if lines else "Command failed."


@dataclass(slots=True)
class ProjectActionReportWriter:
    runtime: Any
    migrate_env_contracts: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
    failure_summary_lines: FailureSummaryBuilder = default_project_action_failure_summary_lines
    migrate_failure_headline: MigrateHeadlineBuilder = default_migrate_failure_headline
    emit_status: Callable[[str], None] | None = None

    def success_handler(self, command_name: str, mode: str, interactive_command: bool) -> Callable[[Any, Any], None]:
        def handle_success(context: Any, completed: Any) -> None:
            clear_dashboard_pr_cache(self.runtime)
            status = project_action_success_status(command_name=command_name, completed=completed)
            extra_entry: dict[str, object] | None = None
            if command_name == "review" and status == "success":
                extra_entry = review_success_artifact_paths(
                    stdout=getattr(completed, "stdout", ""),
                    stderr=getattr(completed, "stderr", ""),
                )
            self.persist_result(
                command_name=command_name,
                mode=mode,
                project_name=str(getattr(context, "name", "")),
                status=status,
                error_output="",
                extra_entry=extra_entry,
            )
            if command_name != "pr" or not interactive_command or status != "success":
                return
            url = first_output_line(getattr(completed, "stdout", ""))
            if url:
                self._emit_status(f"PR created: {url}")

        return handle_success

    def failure_handler(self, command_name: str, mode: str) -> Callable[[Any, str], None]:
        def handle_failure(context: Any, error_output: str) -> None:
            self.persist_result(
                command_name=command_name,
                mode=mode,
                project_name=str(getattr(context, "name", "")),
                status="failed",
                error_output=error_output,
            )

        return handle_failure

    def persist_result(
        self,
        *,
        command_name: str,
        mode: str,
        project_name: str,
        status: str,
        error_output: str,
        extra_entry: Mapping[str, object] | None = None,
    ) -> None:
        state = self._load_existing_state(mode=mode)
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
        migrate_env_metadata = (
            dict(self.migrate_env_contracts.get(project_name, {})) if command_name == "migrate" else None
        )
        if migrate_env_metadata:
            entry["backend_env"] = migrate_env_metadata
        if isinstance(extra_entry, Mapping):
            entry.update({str(key): value for key, value in extra_entry.items()})
        if status == "failed":
            clean_output = strip_ansi(str(error_output or "")).strip()
            summary_lines = self.failure_summary_lines(command_name, clean_output, migrate_env_metadata)
            summary_text = "\n".join(summary_lines).strip() or "Command failed."
            report_path = write_project_action_failure_report(
                runtime=self.runtime,
                run_id=state.run_id,
                project_name=project_name,
                command_name=command_name,
                output=clean_output,
            )
            if command_name == "migrate":
                headline = self.migrate_failure_headline(clean_output)
                if headline:
                    entry["headline"] = headline
            entry["summary"] = summary_text
            entry["report_path"] = str(report_path)
        project_metadata[command_name] = entry
        metadata[project_name] = project_metadata
        state.metadata["project_action_reports"] = metadata
        self.runtime.state_repository.save_resume_state(
            state=state,
            emit=getattr(self.runtime, "emit", None),
            runtime_map_builder=build_runtime_map,
        )

    def _load_existing_state(self, *, mode: str) -> Any | None:
        load_state = getattr(self.runtime, "load_existing_state", None)
        if callable(load_state):
            return load_state(mode=mode)
        legacy = getattr(self.runtime, "_try_load_existing_state", None)
        if callable(legacy):
            return legacy(mode=mode)
        return None

    def _emit_status(self, message: str) -> None:
        if self.emit_status is not None:
            self.emit_status(message)
            return
        emit_status = getattr(self.runtime, "emit_status", None)
        if callable(emit_status):
            emit_status(message)
            return
        emit = getattr(self.runtime, "emit", None)
        if callable(emit):
            emit("ui.status", message=message)


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
    runtime: Any,
    run_id: str,
    project_name: str,
    command_name: str,
    output: str,
) -> Path:
    results_root = runtime.state_repository.run_dir_path(run_id)
    results_root.mkdir(parents=True, exist_ok=True)
    safe_project = project_name.replace(" ", "_")
    report_path = results_root / f"{safe_project}_{command_name}.txt"
    report_path.write_text((output or "Command failed.").rstrip() + "\n", encoding="utf-8")
    return report_path


def clear_dashboard_pr_cache(runtime: Any) -> None:
    runtime_raw = getattr(runtime, "raw_runtime", runtime)
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


def git_state_components(project_root: Path) -> tuple[str, str, int]:
    head = ""
    status = ""
    try:
        head_proc = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if head_proc.returncode == 0:
            head = (head_proc.stdout or "").strip()
        status_proc = subprocess.run(
            ["git", "-C", str(project_root), "status", "--porcelain=1"],
            capture_output=True,
            text=True,
            check=False,
        )
        if status_proc.returncode == 0:
            status = status_proc.stdout or ""
    except Exception:
        head = ""
        status = ""
    status_hash = hashlib.sha1(status.encode("utf-8")).hexdigest()
    status_lines = len([line for line in status.splitlines() if line.strip()])
    return head, status_hash, status_lines
