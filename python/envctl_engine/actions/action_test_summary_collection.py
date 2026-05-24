from __future__ import annotations

from envctl_engine.actions.action_test_support import (
    frontend_failed_files_from_failed_tests,
    sanitize_failed_test_identifiers,
)


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
