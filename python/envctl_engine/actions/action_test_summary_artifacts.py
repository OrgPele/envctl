from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Callable

from envctl_engine.actions.action_test_summary_collection import (
    collect_failed_test_manifest_entries,
    collect_failed_tests,
    collect_generic_suite_failures,
    collect_suite_failure_contexts,
)
from envctl_engine.actions.action_test_summary_formatting import format_summary_error_lines
from envctl_engine.actions.action_test_summary_git import default_git_state_components
from envctl_engine.actions.action_test_support import load_failed_test_manifest
from envctl_engine.state.runtime_map import build_runtime_map
from envctl_engine.test_output.failure_summary import extract_failure_summary_excerpt
from envctl_engine.test_output.parser_base import strip_ansi


def short_failed_summary_path(*, run_dir: Path, project_name: str) -> Path:
    digest = hashlib.sha1(project_name.encode("utf-8")).hexdigest()[:10]
    run_root = run_dir.parent.parent
    return run_root / f"ft_{digest}.txt"


def persist_test_summary_artifacts(
    *,
    runtime: object,
    route: object,
    targets: list[object],
    outcomes: list[dict[str, object]],
    new_test_results_run_dir: Callable[[object, str], Path] | None = None,
    write_failed_tests_summary_fn: Callable[..., dict[str, object]] | None = None,
    runtime_map_builder: Callable[..., object] = build_runtime_map,
) -> dict[str, dict[str, object]]:
    if not targets:
        return {}

    project_roots = _project_roots_from_targets(targets)
    if not project_roots:
        project_roots = _project_roots_from_outcomes(outcomes)
    if not project_roots:
        return {}

    state = runtime.load_existing_state(mode=getattr(route, "mode", None))  # type: ignore[attr-defined]
    if state is None:
        return {}

    run_dir_builder = new_test_results_run_dir or new_test_results_run_dir_path
    run_dir = run_dir_builder(runtime, str(getattr(state, "run_id")))
    existing = getattr(state, "metadata", {}).get("project_test_summaries")
    metadata = dict(existing) if isinstance(existing, dict) else {}
    writer = write_failed_tests_summary_fn or write_failed_tests_summary
    summaries: dict[str, dict[str, object]] = {}
    for project_name, project_root in project_roots.items():
        previous_entry = metadata.get(project_name)
        summaries[project_name] = writer(
            run_dir=run_dir,
            project_name=project_name,
            project_root=project_root,
            outcomes=outcomes,
            previous_entry=previous_entry if isinstance(previous_entry, dict) else None,
        )

    metadata.update(summaries)
    state.metadata["project_test_summaries"] = metadata
    state.metadata["project_test_results_root"] = str(run_dir)
    state.metadata["project_test_results_updated_at"] = datetime.now(tz=UTC).isoformat()

    runtime.state_repository.save_resume_state(  # type: ignore[attr-defined]
        state=state,
        emit=runtime.emit,  # type: ignore[attr-defined]
        runtime_map_builder=runtime_map_builder,
    )
    runtime.emit(  # type: ignore[attr-defined]
        "test.summary.persisted",
        mode=getattr(route, "mode", None),
        projects=sorted(summaries),
        run_dir=str(run_dir),
    )
    return summaries


def new_test_results_run_dir_path(runtime: object, run_id: str) -> Path:
    results_root = runtime.state_repository.test_results_dir_path(run_id)  # type: ignore[attr-defined]
    results_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=UTC).strftime("run_%Y%m%d_%H%M%S")
    candidate = results_root / stamp
    if not candidate.exists():
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate
    suffix = 1
    while True:
        suffixed = results_root / f"{stamp}_{suffix}"
        if not suffixed.exists():
            suffixed.mkdir(parents=True, exist_ok=True)
            return suffixed
        suffix += 1


def _project_roots_from_targets(targets: list[object]) -> dict[str, Path]:
    project_roots: dict[str, Path] = {}
    for target in targets:
        name = str(getattr(target, "name", "")).strip()
        root_raw = str(getattr(target, "root", "")).strip()
        if not name or not root_raw:
            continue
        project_roots[name] = Path(root_raw)
    return project_roots


def _project_roots_from_outcomes(outcomes: list[dict[str, object]]) -> dict[str, Path]:
    project_roots: dict[str, Path] = {}
    for outcome in outcomes:
        name = str(outcome.get("project_name", "")).strip()
        root_raw = str(outcome.get("project_root", "")).strip()
        if not name or not root_raw:
            continue
        project_roots[name] = Path(root_raw)
    return project_roots


def write_failed_tests_summary(
    *,
    run_dir: Path,
    project_name: str,
    project_root: Path,
    outcomes: list[dict[str, object]],
    previous_entry: dict[str, object] | None = None,
    short_failed_summary_path: Callable[..., Path] = short_failed_summary_path,
    format_summary_error_lines: Callable[[str], list[str]] = format_summary_error_lines,
    git_state_components: Callable[[Path], tuple[str, str, int]] | None = None,
) -> dict[str, object]:
    safe_project = project_name.replace(" ", "_")
    output_dir = run_dir / safe_project
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "failed_tests_summary.txt"
    short_summary_path = short_failed_summary_path(run_dir=run_dir, project_name=project_name)
    state_path = output_dir / "test_state.txt"
    manifest_path = output_dir / "failed_tests_manifest.json"

    failures = collect_failed_tests(outcomes, project_name=project_name)
    generic_suite_failures = collect_generic_suite_failures(outcomes, project_name=project_name)
    suite_failure_contexts = collect_suite_failure_contexts(outcomes, project_name=project_name)
    manifest_entries = collect_failed_test_manifest_entries(outcomes, project_name=project_name)
    failed_only = any(
        bool(item.get("failed_only", False))
        for item in outcomes
        if str(item.get("project_name", "")).strip() == project_name
    )
    generated_at = datetime.now().astimezone()
    lines = [
        "# envctl Failed Test Summary",
        f"# Generated at: {generated_at.strftime('%a %b %d %H:%M:%S %Z %Y')}",
        "",
    ]
    if failures:
        for suite_name, failed_test, error_text in failures:
            clean_suite_name = strip_ansi(str(suite_name)).strip()
            clean_failed_test = strip_ansi(str(failed_test)).strip()
            lines.append(f"[{clean_suite_name}]")
            lines.append(f"- {clean_failed_test}")
            if error_text:
                for detail in format_summary_error_lines(str(error_text)):
                    lines.append(f"    {detail}")
            lines.append("")
        for suite_name, context_text in suite_failure_contexts:
            clean_suite_name = strip_ansi(str(suite_name)).strip()
            lines.append(f"[{clean_suite_name}]")
            lines.append("suite context:")
            for detail in format_summary_error_lines(str(context_text)):
                lines.append(f"    {detail}")
            lines.append("")
    elif generic_suite_failures:
        for suite_name, summary in generic_suite_failures:
            clean_suite_name = strip_ansi(str(suite_name)).strip()
            lines.append(f"[{clean_suite_name}]")
            lines.append("- suite failed before envctl could extract failed tests")
            for detail in format_summary_error_lines(str(summary)):
                lines.append(f"    {detail}")
            lines.append("")
    else:
        lines.append("No failed tests.")
        lines.append("")
    summary_text = "\n".join(lines)
    summary_path.write_text(summary_text, encoding="utf-8")
    short_summary_path.write_text(summary_text, encoding="utf-8")

    state_components = git_state_components or default_git_state_components
    head, status_hash, status_lines = state_components(project_root)
    state_path.write_text(
        f"state|{project_name}|{project_root}|{head}|{status_hash}|{status_lines}\n",
        encoding="utf-8",
    )
    manifest_payload = {
        "generated_at": generated_at.isoformat(),
        "project_name": project_name,
        "project_root": str(project_root),
        "git_state": {
            "head": head,
            "status_hash": status_hash,
            "status_lines": status_lines,
        },
        "entries": manifest_entries,
    }
    manifest_path.write_text(json.dumps(manifest_payload, indent=2, sort_keys=True), encoding="utf-8")

    preserve_previous = (
        failed_only
        and not failures
        and bool(generic_suite_failures)
        and not manifest_entries
        and previous_entry is not None
    )
    if preserve_previous:
        previous_manifest_path_raw = str(previous_entry.get("manifest_path", "") or "").strip()
        previous_manifest = (
            load_failed_test_manifest(Path(previous_manifest_path_raw)) if previous_manifest_path_raw else None
        )
        if previous_manifest is not None and previous_manifest.entries:
            preserved = dict(previous_entry)
            preserved["status"] = "failed"
            preserved["updated_at"] = generated_at.isoformat()
            preserved["preserved_after_failed_only_extraction_failure"] = True
            return preserved

    return {
        "summary_path": str(summary_path),
        "short_summary_path": str(short_summary_path),
        "state_path": str(state_path),
        "manifest_path": str(manifest_path),
        "status": "failed" if failures or generic_suite_failures else "passed",
        "failed_tests": len(failures),
        "failed_manifest_entries": len(manifest_entries),
        "summary_excerpt": extract_failure_summary_excerpt(summary_text, max_lines=3),
        "updated_at": generated_at.isoformat(),
    }


def persist_test_summary_artifacts_for_orchestrator(
    orchestrator: object,
    *,
    route: object,
    targets: list[object],
    outcomes: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    return persist_test_summary_artifacts(
        runtime=orchestrator.runtime,  # type: ignore[attr-defined]
        route=route,
        targets=targets,
        outcomes=outcomes,
        new_test_results_run_dir=lambda _runtime, run_id: new_test_results_run_dir_path(
            orchestrator.runtime,  # type: ignore[attr-defined]
            run_id,
        ),
        write_failed_tests_summary_fn=lambda **kwargs: write_failed_tests_summary_for_orchestrator(
            orchestrator,
            **kwargs,
        ),
        runtime_map_builder=build_runtime_map,
    )


def write_failed_tests_summary_for_orchestrator(
    orchestrator: object,
    *,
    run_dir: Path,
    project_name: str,
    project_root: Path,
    outcomes: list[dict[str, object]],
    previous_entry: dict[str, object] | None = None,
) -> dict[str, object]:
    from envctl_engine.actions import action_test_summary_support

    return action_test_summary_support.write_failed_tests_summary(
        run_dir=run_dir,
        project_name=project_name,
        project_root=project_root,
        outcomes=outcomes,
        previous_entry=previous_entry,
        short_failed_summary_path=short_failed_summary_path,
        format_summary_error_lines=format_summary_error_lines,
        git_state_components=default_git_state_components,
    )
