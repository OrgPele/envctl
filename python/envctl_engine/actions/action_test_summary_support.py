from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable

from envctl_engine.actions.action_test_support import (
    frontend_failed_files_from_failed_tests,
    load_failed_test_manifest,
    sanitize_failed_test_identifiers,
)
from envctl_engine.test_output.failure_summary import extract_failure_summary_excerpt
from envctl_engine.test_output.parser_base import strip_ansi
from envctl_engine.test_output.symbols import format_duration
from envctl_engine.ui.path_links import render_path_for_terminal
from envctl_engine.state.runtime_map import build_runtime_map


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


def format_summary_error_lines(error_text: str) -> list[str]:
    cleaned = strip_ansi(error_text)
    lines: list[str] = []
    for raw_line in cleaned.splitlines():
        compact = compact_summary_line(raw_line)
        if compact:
            lines.append(compact)
    if not lines:
        return []

    max_lines = 60
    if len(lines) <= max_lines:
        return lines
    structured = structured_summary_lines(lines)
    if not structured:
        structured = lines[:]
    merged = structured[:]
    seen = set(merged)
    for line in lines:
        if len(merged) >= max_lines:
            break
        if line in seen:
            continue
        merged.append(line)
        seen.add(line)
    if len(lines) > len(merged):
        merged.append(f"... ({len(lines) - len(merged)} more lines omitted)")
    return merged[: max_lines + 1]


def compact_summary_line(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return ""
    if re.fullmatch(r"[-=]{6,}", stripped):
        return ""
    if looks_like_terminal_chrome(stripped):
        return ""
    stripped = re.sub(r"( not found in )(['\"]).*", r"\1<omitted output>", stripped)
    stripped = re.sub(r"( not found: )(['\"]).*", r"\1<omitted output>", stripped)
    stripped = re.sub(r"(result(?:ed)? in )(['\"]).*", r"\1<omitted output>", stripped, flags=re.IGNORECASE)
    if len(stripped) > 220:
        stripped = f"{stripped[:217].rstrip()}..."
    return stripped


def structured_summary_lines(lines: list[str]) -> list[str]:
    assembled: list[str] = []
    seen: set[str] = set()

    def append_block(block: list[str], *, allow_gap: bool = False) -> None:
        nonlocal assembled
        block = [line for line in block if line]
        if not block:
            return
        if allow_gap and assembled and assembled[-1] != "...":
            assembled.append("...")
        for line in block:
            if line in seen:
                continue
            assembled.append(line)
            seen.add(line)

    traceback_header = next((line for line in lines if line.startswith("Traceback (most recent call last):")), "")
    if traceback_header:
        append_block([traceback_header])

    for block in user_code_frame_blocks(lines):
        append_block(block, allow_gap=bool(assembled))

    context_markers = exception_context_markers(lines)
    if context_markers:
        append_block(context_markers, allow_gap=bool(assembled))

    exception_body = exception_body_block(lines)
    if exception_body:
        append_block(exception_body, allow_gap=bool(assembled))

    captured_blocks = captured_output_blocks(lines)
    for block in captured_blocks:
        append_block(block, allow_gap=bool(assembled))

    max_lines = 24
    if assembled:
        return assembled[:max_lines]
    return []


def user_code_frame_blocks(lines: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    file_indexes = [index for index, line in enumerate(lines) if line.startswith('File "')]
    for index in file_indexes:
        if not is_user_code_frame(lines[index]):
            continue
        block = [lines[index]]
        cursor = index + 1
        while cursor < len(lines):
            line = lines[cursor]
            if line.startswith('File "') or is_captured_output_header(line):
                break
            if is_exception_start(line):
                break
            block.append(line)
            cursor += 1
        blocks.append(block[:3])
    return blocks


def exception_body_block(lines: list[str]) -> list[str]:
    start = -1
    for index in range(len(lines) - 1, -1, -1):
        if is_exception_start(lines[index]):
            start = index
            break
    if start < 0:
        return []
    block = [lines[start]]
    cursor = start + 1
    while cursor < len(lines):
        line = lines[cursor]
        if line.startswith('File "') or is_captured_output_header(line):
            break
        block.append(line)
        cursor += 1
    return block[:5]


def captured_output_blocks(lines: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not is_captured_output_header(line):
            index += 1
            continue
        block = [line]
        cursor = index + 1
        while cursor < len(lines):
            candidate = lines[cursor]
            if is_captured_output_header(candidate):
                break
            if candidate.startswith('File "') and is_user_code_frame(candidate):
                break
            if candidate == "Traceback (most recent call last):":
                break
            if is_exception_context_marker(candidate):
                break
            block.append(candidate)
            cursor += 1
        blocks.append(block[:5])
        index = cursor
    return blocks


def exception_context_markers(lines: list[str]) -> list[str]:
    return [line for line in lines if is_exception_context_marker(line)][:3]


def is_user_code_frame(line: str) -> bool:
    match = re.match(r'^File "([^"]+)"', line)
    if match is None:
        return False
    path = match.group(1)
    stdlib_markers = (
        "/Cellar/python@",
        "/Frameworks/Python.framework/",
        "/lib/python",
        "/site-packages/",
        "/asyncio/",
        "/unittest/",
    )
    return not any(marker in path for marker in stdlib_markers)


def is_exception_start(line: str) -> bool:
    return bool(
        re.match(
            r"^(?:AssertionError|[A-Za-z_][\w.]*(?:Error|Exception|Failure|Exit|Interrupt|Warning))(?:\b|:)",
            line,
        )
    )


def is_exception_context_marker(line: str) -> bool:
    lowered = line.strip().lower()
    return "during handling of the above exception" in lowered or "the above exception was the direct cause" in lowered


def is_captured_output_header(line: str) -> bool:
    lowered = line.strip().lower()
    return (
        lowered.startswith("captured stdout")
        or lowered.startswith("captured stderr")
        or lowered.startswith("captured log")
        or lowered in {"stdout:", "stderr:"}
    )


def looks_like_terminal_chrome(line: str) -> bool:
    if "RESULT_SERVICES=" in line or "Run tests for" in line or "Filter targets..." in line:
        return True
    box_chars = "╭╮╰╯│▊▎▔▁▄▅▇"
    box_count = sum(1 for char in line if char in box_chars)
    if box_count >= 4:
        return True
    if len(line) >= 40 and sum(1 for char in line if char == " ") > len(line) * 0.55 and box_count >= 1:
        return True
    return False


def print_test_suite_overview(
    outcomes: list[dict[str, object]],
    *,
    summary_metadata: dict[str, dict[str, object]] | None = None,
    env: dict[str, str] | None = None,
    colorize: Callable[..., str],
) -> None:
    if not outcomes:
        return
    print("")
    print(colorize("======================================================================", fg="cyan"))
    print(colorize("Test Suite Summary", fg="cyan", bold=True))
    print(colorize("======================================================================", fg="cyan"))
    project_labels = {
        str(item.get("project_name", "")).strip() for item in outcomes if str(item.get("project_name", "")).strip()
    }
    multi_project = len(project_labels) > 1
    total_passed = 0
    total_failed = 0
    total_skipped = 0
    total_known = 0
    total_duration = 0.0
    grouped_outcomes: dict[str, list[dict[str, object]]] = {}
    for item in sorted(
        outcomes,
        key=lambda value: (
            str(value.get("project_name", "")).lower(),
            int(value.get("index", 0)),
        ),
    ):
        project_name = str(item.get("project_name", "")).strip() or "Main"
        grouped_outcomes.setdefault(project_name, []).append(item)

    for project_name, project_items in grouped_outcomes.items():
        if multi_project:
            print(colorize(project_name, fg="blue", bold=True))
        for item in project_items:
            source = str(item.get("suite", "suite"))
            label = suite_display_name(source, failed_only=bool(item.get("failed_only", False)))
            label_rendered = colorize(label, fg="cyan", bold=True)
            if multi_project:
                label_rendered = f"  {label_rendered}"
            returncode = int(item.get("returncode", 1))
            parsed = item.get("parsed")
            parsed_total = int(getattr(parsed, "total", 0) or 0) if parsed is not None else 0
            counts_detected = bool(getattr(parsed, "counts_detected", False)) if parsed is not None else False
            passed = int(getattr(parsed, "passed", 0) or 0) if parsed is not None else 0
            failed = int(getattr(parsed, "failed", 0) or 0) if parsed is not None else 0
            skipped = int(getattr(parsed, "skipped", 0) or 0) if parsed is not None else 0
            duration_ms = float(item.get("duration_ms", 0.0) or 0.0)
            duration_text = format_duration(max(duration_ms / 1000.0, 0.0))

            icon = colorize("✓", fg="green", bold=True) if returncode == 0 else colorize("✗", fg="red", bold=True)
            if counts_detected:
                total_passed += passed
                total_failed += failed
                total_skipped += skipped
                total_known += parsed_total
                total_duration += max(duration_ms / 1000.0, 0.0)
                passed_text = colorize(f"{passed} passed", fg="green")
                failed_text = colorize(f"{failed} failed", fg="red")
                skipped_text = colorize(f"{skipped} skipped", fg="yellow")
                print(
                    f"{icon} {label_rendered}: {passed_text}, {failed_text}, {skipped_text}"
                    f" (total {parsed_total}, duration {duration_text})"
                )
            else:
                total_duration += max(duration_ms / 1000.0, 0.0)
                if returncode == 0:
                    print(
                        f"{icon} {label_rendered}: "
                        f"{colorize('completed', fg='green', bold=True)} "
                        f"(no parsed test counts, duration {duration_text})"
                    )
                else:
                    print(
                        f"{icon} {label_rendered}: "
                        f"{colorize('failed', fg='red', bold=True)} "
                        f"(no parsed test counts, duration {duration_text})"
                    )
        summary_entry = summary_metadata.get(project_name) if isinstance(summary_metadata, dict) else None
        if isinstance(summary_entry, dict) and str(summary_entry.get("status", "")).strip().lower() == "failed":
            summary_path = str(
                summary_entry.get("short_summary_path") or summary_entry.get("summary_path") or ""
            ).strip()
            if summary_path:
                prefix = "  " if multi_project else ""
                label = colorize("failure summary:", fg="gray")
                print(f"{prefix}{label}")
                summary_env = dict(env or {})
                hyperlink_mode = str(summary_env.get("ENVCTL_UI_HYPERLINK_MODE", "")).strip().lower()
                if hyperlink_mode not in {"off", "false", "no", "0"}:
                    summary_env["ENVCTL_UI_HYPERLINK_MODE"] = "on"
                rendered_path = render_path_for_terminal(summary_path, env=summary_env, stream=sys.stdout)
                print(f"{prefix}{rendered_path}")
        if multi_project:
            print("")

    if total_known > 0:
        overall_prefix = colorize("Overall:", fg="cyan", bold=True)
        overall_passed = colorize(f"{total_passed} passed", fg="green")
        overall_failed = colorize(f"{total_failed} failed", fg="red")
        overall_skipped = colorize(f"{total_skipped} skipped", fg="yellow")
        print(
            f"{overall_prefix} {overall_passed}, {overall_failed}, {overall_skipped}"
            f" (total {total_known}, duration {format_duration(total_duration)})"
        )
    print(colorize("======================================================================", fg="cyan"))


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
