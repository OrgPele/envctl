from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Callable

from envctl_engine.actions.action_test_support import (
    frontend_failed_files_from_failed_tests,
    load_failed_test_manifest,
    sanitize_failed_test_identifiers,
)
from envctl_engine.test_output.failure_summary import extract_failure_summary_excerpt
from envctl_engine.test_output.parser_base import strip_ansi


def short_failed_summary_path(*, run_dir: Path, project_name: str) -> Path:
    digest = hashlib.sha1(project_name.encode("utf-8")).hexdigest()[:10]
    run_root = run_dir.parent.parent
    return run_root / f"ft_{digest}.txt"


def write_failed_tests_summary(
    *,
    run_dir: Path,
    project_name: str,
    project_root: Path,
    outcomes: list[dict[str, object]],
    previous_entry: dict[str, object] | None = None,
    short_failed_summary_path: Callable[..., Path] = short_failed_summary_path,
    format_summary_error_lines: Callable[[str], list[str]],
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


def collect_failed_tests(
    outcomes: list[dict[str, object]],
    *,
    project_name: str | None = None,
) -> list[tuple[str, str, str]]:
    collected: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    ordered = sorted(outcomes, key=lambda value: int(value.get("index", 0)))
    for item in ordered:
        if project_name is not None:
            item_project_name = str(item.get("project_name", "")).strip()
            if item_project_name != project_name:
                continue
        source = str(item.get("suite", "suite"))
        parsed = item.get("parsed")
        failed_tests = list(getattr(parsed, "failed_tests", []) or []) if parsed is not None else []
        error_details = dict(getattr(parsed, "error_details", {}) or {}) if parsed is not None else {}
        suite_name = suite_display_name(source, failed_only=bool(item.get("failed_only", False)))
        for failed_test in failed_tests:
            test_name = str(failed_test).strip()
            if not test_name:
                continue
            dedupe_key = (suite_name, test_name)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            error_text = resolve_failed_test_error(error_details, test_name)
            collected.append((suite_name, test_name, error_text))
    return collected


def collect_failed_test_manifest_entries(
    outcomes: list[dict[str, object]],
    *,
    project_name: str | None = None,
) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    ordered = sorted(outcomes, key=lambda value: int(value.get("index", 0)))
    for item in ordered:
        if project_name is not None:
            item_project_name = str(item.get("project_name", "")).strip()
            if item_project_name != project_name:
                continue
        source = str(item.get("suite", "")).strip()
        if not source:
            continue
        parsed = item.get("parsed")
        raw_failed_tests = (
            [
                str(failed_test).strip()
                for failed_test in list(getattr(parsed, "failed_tests", []) or [])
                if str(failed_test).strip()
            ]
            if parsed is not None
            else []
        )
        failed_tests, invalid_failed_tests = sanitize_failed_test_identifiers(
            source=source,
            failed_tests=raw_failed_tests,
        )
        failed_files = (
            frontend_failed_files_from_failed_tests(failed_tests)
            if source in {"frontend_package_test", "package_test"}
            else []
        )
        if not failed_tests and not failed_files:
            continue
        entries.append(
            {
                "suite": suite_display_name(source, failed_only=bool(item.get("failed_only", False))),
                "source": source,
                "failed_tests": list(failed_tests),
                "failed_files": failed_files,
                "invalid_failed_tests": invalid_failed_tests,
            }
        )
    return entries


def collect_generic_suite_failures(
    outcomes: list[dict[str, object]],
    *,
    project_name: str | None = None,
) -> list[tuple[str, str]]:
    collected: list[tuple[str, str]] = []
    ordered = sorted(outcomes, key=lambda value: int(value.get("index", 0)))
    for item in ordered:
        if project_name is not None:
            item_project_name = str(item.get("project_name", "")).strip()
            if item_project_name != project_name:
                continue
        if int(item.get("returncode", 0) or 0) == 0:
            continue
        parsed = item.get("parsed")
        failed_tests = list(getattr(parsed, "failed_tests", []) or []) if parsed is not None else []
        if failed_tests:
            continue
        summary = str(item.get("failure_details", "") or item.get("failure_summary", "") or "").strip()
        if not summary:
            summary = "Test command failed before envctl could extract failed tests."
        suite_name = suite_display_name(
            str(item.get("suite", "suite")),
            failed_only=bool(item.get("failed_only", False)),
        )
        collected.append((suite_name, summary))
    return collected


def collect_suite_failure_contexts(
    outcomes: list[dict[str, object]],
    *,
    project_name: str | None = None,
) -> list[tuple[str, str]]:
    collected: list[tuple[str, str]] = []
    ordered = sorted(outcomes, key=lambda value: int(value.get("index", 0)))
    for item in ordered:
        if project_name is not None:
            item_project_name = str(item.get("project_name", "")).strip()
            if item_project_name != project_name:
                continue
        if int(item.get("returncode", 0) or 0) == 0:
            continue
        parsed = item.get("parsed")
        failed_tests = list(getattr(parsed, "failed_tests", []) or []) if parsed is not None else []
        if not failed_tests:
            continue
        context_text = str(item.get("failure_details", "") or "").strip()
        if not context_text:
            continue
        suite_name = suite_display_name(
            str(item.get("suite", "suite")),
            failed_only=bool(item.get("failed_only", False)),
        )
        collected.append((suite_name, context_text))
    return collected


def resolve_failed_test_error(error_details: dict[str, object], test_name: str) -> str:
    direct = error_details.get(test_name)
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    if "::" in test_name:
        file_key = test_name.split("::", 1)[0]
        file_error = error_details.get(file_key)
        if isinstance(file_error, str) and file_error.strip():
            return file_error.strip()
    return ""


def default_git_state_components(project_root: Path) -> tuple[str, str, int]:
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


def suite_display_name(source: str, *, failed_only: bool = False) -> str:
    if source == "backend_pytest":
        return "Backend (pytest, failed only)" if failed_only else "Backend (pytest)"
    if source == "root_pytest":
        return "Repository tests (pytest, failed only)" if failed_only else "Repository tests (pytest)"
    if source == "configured_backend":
        return "Backend (failed only)" if failed_only else "Backend"
    if source == "frontend_package_test":
        return "Frontend (package test, failed only)" if failed_only else "Frontend (package test)"
    if source == "configured_frontend":
        return "Frontend (failed only)" if failed_only else "Frontend"
    if source == "root_unittest":
        return "Repository tests (unittest, failed only)" if failed_only else "Repository tests (unittest)"
    if source == "package_test":
        return "Repository package test (failed only)" if failed_only else "Repository package test"
    if source == "configured":
        return "Test command (failed only)" if failed_only else "Test command"
    return source.replace("_", " ")
