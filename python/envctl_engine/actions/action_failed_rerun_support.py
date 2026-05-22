from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping

from envctl_engine.actions.action_test_support import (
    FailedTestManifest,
    TestExecutionSpec,
    TestTargetContext,
    build_failed_test_execution_specs,
    load_failed_test_manifest,
)


def build_failed_test_execution_specs_from_state(
    *,
    state: object | None,
    target_contexts: list[TestTargetContext],
    repo_root: Path,
    shared_raw_command: str | None,
    backend_raw_command: str | None,
    frontend_raw_command: str | None,
    emit_status: Callable[[str], None],
) -> list[TestExecutionSpec]:
    if state is None:
        raise RuntimeError("No saved failed-test data is available yet. Run the full test suite first.")
    summaries_raw = getattr(state, "metadata", {}).get("project_test_summaries")
    summaries = summaries_raw if isinstance(summaries_raw, dict) else {}
    manifests_by_project: dict[str, FailedTestManifest] = {}
    invalid_selector_counts: dict[str, int] = {}
    non_rerunnable_projects: list[str] = []
    extraction_failed_projects: list[str] = []
    for target in target_contexts:
        entry = summaries.get(target.project_name)
        if not isinstance(entry, dict):
            continue
        manifest_path_raw = str(entry.get("manifest_path", "") or "").strip()
        if not manifest_path_raw:
            _record_non_rerunnable_entry(
                entry=entry,
                project_name=target.project_name,
                non_rerunnable_projects=non_rerunnable_projects,
                extraction_failed_projects=extraction_failed_projects,
            )
            continue
        manifest = load_failed_test_manifest(Path(manifest_path_raw))
        if manifest is None or not manifest.entries:
            _record_non_rerunnable_entry(
                entry=entry,
                project_name=target.project_name,
                non_rerunnable_projects=non_rerunnable_projects,
                extraction_failed_projects=extraction_failed_projects,
            )
            continue
        invalid_count = sum(item.invalid_failed_tests for item in manifest.entries)
        if invalid_count > 0:
            invalid_selector_counts[target.project_name] = invalid_count
        manifests_by_project[target.project_name] = manifest
    for project_name, invalid_count in sorted(invalid_selector_counts.items()):
        noun = "selector" if invalid_count == 1 else "selectors"
        message = (
            f"Skipping {invalid_count} invalid saved pytest {noun} for {project_name}; "
            "rerunning the remaining failed tests."
        )
        emit_status(message)
        print(message)
    if non_rerunnable_projects:
        projects = ", ".join(sorted(non_rerunnable_projects))
        if extraction_failed_projects and sorted(extraction_failed_projects) == sorted(non_rerunnable_projects):
            print(f"No rerunnable failed tests were extracted for: {projects}")
        else:
            print(f"No rerunnable failed tests remain for: {projects}")
    if not manifests_by_project:
        if extraction_failed_projects and sorted(extraction_failed_projects) == sorted(non_rerunnable_projects):
            raise RuntimeError(
                "No rerunnable failed tests were found for the selected target(s). "
                "The last full run failed before envctl could derive rerunnable test selectors. "
                "See the saved failure summary."
            )
        if non_rerunnable_projects:
            raise RuntimeError(
                "No rerunnable failed tests were found for the selected target(s). "
                "Saved failures could not be converted into rerunnable selectors. Run the full suite first."
            )
        raise RuntimeError("No saved failed tests were found for the selected target(s). Run the full suite first.")
    execution_specs = build_failed_test_execution_specs(
        target_contexts=target_contexts,
        repo_root=repo_root,
        manifests_by_project=manifests_by_project,
        shared_raw_command=shared_raw_command,
        backend_raw_command=backend_raw_command,
        frontend_raw_command=frontend_raw_command,
    )
    if execution_specs:
        return execution_specs
    if manifests_by_project:
        projects = ", ".join(sorted(manifests_by_project))
        print(f"No rerunnable failed tests remain for: {projects}")
    if non_rerunnable_projects:
        raise RuntimeError(
            "No rerunnable failed tests were found for the selected target(s). "
            "Saved failures could not be converted into rerunnable selectors. See the saved failure summary."
        )
    raise RuntimeError("No rerunnable failed tests were found for the selected target(s).")


def summary_indicates_extraction_failure(entry: Mapping[str, object]) -> bool:
    for key in ("short_summary_path", "summary_path"):
        raw = str(entry.get(key, "") or "").strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "suite failed before envctl could extract failed tests" in text:
            return True
    return False


def _record_non_rerunnable_entry(
    *,
    entry: Mapping[str, object],
    project_name: str,
    non_rerunnable_projects: list[str],
    extraction_failed_projects: list[str],
) -> None:
    if str(entry.get("status", "") or "").strip().lower() != "failed":
        return
    non_rerunnable_projects.append(project_name)
    if summary_indicates_extraction_failure(entry):
        extraction_failed_projects.append(project_name)
