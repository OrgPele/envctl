from __future__ import annotations

from pathlib import Path
from contextlib import suppress
import hashlib
from typing import Any, cast

from envctl_engine.actions.action_migrate_support import (
    migrate_failure_headline,
    migrate_result_record,
    print_migrate_result_records,
)
from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState
from envctl_engine.test_output.failure_summary import summary_excerpt_from_entry
from envctl_engine.ui.path_links import render_path_for_terminal
import sys


def print_interactive_failure_details(
    *,
    route: Route,
    state: RunState,
    code: int,
    runtime: Any,
    test_failure_details_available_fn: Any,
    print_test_failure_details_fn: Any,
    print_project_action_failure_details_fn: Any,
) -> None:
    if route.command == "test":
        if bool(route.flags.get("interactive_command")) and test_failure_details_available_fn(route, state):
            return
        printed = print_test_failure_details_fn(route, state)
        if printed:
            return
    printed = print_project_action_failure_details_fn(route, state)
    if printed:
        return
    print(f"Command failed (exit {code}).")


def failure_details_available(route: Route, state: RunState, *, project_names_from_state_fn: Any) -> bool:
    metadata = state.metadata.get("project_test_summaries")
    if not isinstance(metadata, dict):
        return False
    project_names = route.projects or project_names_from_state_fn(state)
    for project_name_raw in project_names:
        project_name = str(project_name_raw).strip()
        entry = metadata.get(project_name)
        if not isinstance(entry, dict):
            continue
        status = str(entry.get("status", "")).strip().lower()
        if status and status != "failed":
            continue
        if summary_display_path(project_name=project_name, entry=entry):
            return True
        if summary_excerpt_from_entry(entry, max_lines=3):
            return True
    return False


def print_test_failure_details(route: Route, state: RunState, *, runtime: Any, project_names_from_state_fn: Any) -> bool:
    metadata = state.metadata.get("project_test_summaries")
    if not isinstance(metadata, dict):
        return False
    project_names = route.projects or project_names_from_state_fn(state)
    printed = False
    env = getattr(runtime, "env", {})
    for project_name_raw in project_names:
        project_name = str(project_name_raw).strip()
        entry = metadata.get(project_name)
        if not isinstance(entry, dict):
            continue
        status = str(entry.get("status", "")).strip().lower()
        if status and status != "failed":
            continue
        summary_path = summary_display_path(project_name=project_name, entry=entry)
        excerpt_lines = summary_excerpt_from_entry(entry, max_lines=3)
        if not summary_path and not excerpt_lines:
            continue
        print(f"Test failure summary for {project_name}:")
        for line in excerpt_lines:
            print(line)
        if summary_path:
            print(
                render_path_for_terminal(
                    summary_path,
                    env=env,
                    stream=sys.stdout,
                    interactive_tty=True,
                )
            )
        printed = True
    return printed


def summary_display_path(*, project_name: str, entry: dict[str, object]) -> str:
    short_path = str(entry.get("short_summary_path", "") or "").strip()
    if short_path:
        resolved = ensure_short_test_summary_path(
            project_name=project_name,
            summary_path=short_path,
        )
        return resolved or short_path
    summary_path = str(entry.get("summary_path", "") or "").strip()
    if not summary_path:
        return ""
    resolved = ensure_short_test_summary_path(
        project_name=project_name, summary_path=summary_path
    )
    return resolved or summary_path


def ensure_short_test_summary_path(*, project_name: str, summary_path: str) -> str:
    path = Path(summary_path).expanduser()
    if not path.is_file():
        return summary_path
    if path.name.startswith("ft_") and path.suffix == ".txt":
        return str(path)
    parents = path.parents
    if len(parents) < 4:
        return summary_path
    run_root = parents[3]
    digest = hashlib.sha1(project_name.encode("utf-8")).hexdigest()[:10]
    short_path = run_root / f"ft_{digest}.txt"
    if not short_path.exists():
        with suppress(OSError):
            short_path.write_text(path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
    return str(short_path) if short_path.exists() else summary_path


def print_project_action_failure_details(route: Route, state: RunState, *, runtime: Any, project_names_from_state_fn: Any, project_name_list_fn: Any) -> bool:
    if route.command == "migrate":
        return print_migrate_result_details(route, state, runtime=runtime, project_names_from_state_fn=project_names_from_state_fn, project_name_list_fn=project_name_list_fn)
    metadata = state.metadata.get("project_action_reports")
    if not isinstance(metadata, dict):
        return False
    project_names = route.projects or project_name_list_fn(project_names_from_state_fn(state))
    printed = False
    env = getattr(runtime, "env", {})
    for project_name_raw in project_names:
        project_name = str(project_name_raw).strip()
        project_entry = metadata.get(project_name)
        if not isinstance(project_entry, dict):
            continue
        action_entry = project_entry.get(route.command)
        if not isinstance(action_entry, dict):
            continue
        if str(action_entry.get("status", "")).strip().lower() != "failed":
            continue
        summary = str(action_entry.get("summary", "")).strip()
        report_path = str(action_entry.get("report_path", "")).strip()
        if summary:
            summary_lines = [line.strip() for line in summary.splitlines() if line.strip()]
            first_line = summary_lines[0] if summary_lines else ""
            hint_lines = [line for line in summary_lines[1:] if line.lower().startswith("hint:")]
            if len(summary_lines) == 1 and len(first_line) <= 220:
                print(f"{route.command} failed for {project_name}: {first_line}")
            else:
                if first_line:
                    print(f"{route.command} failed for {project_name}: {first_line}")
                for hint in hint_lines:
                    print(hint)
                if report_path:
                    print(f"{route.command} failure log for {project_name}:")
                    print(
                        render_path_for_terminal(
                            report_path,
                            env=env,
                            stream=sys.stdout,
                            interactive_tty=True,
                        )
                    )
            printed = True
            continue
        if report_path:
            print(f"{route.command} failure log for {project_name}:")
            print(
                render_path_for_terminal(
                    report_path,
                    env=env,
                    stream=sys.stdout,
                    interactive_tty=True,
                )
            )
            printed = True
    return printed


def print_migrate_result_details(route: Route, state: RunState, *, runtime: Any, project_names_from_state_fn: Any, project_name_list_fn: Any) -> bool:
    metadata = state.metadata.get("project_action_reports")
    if not isinstance(metadata, dict):
        return False
    project_names = route.projects or project_name_list_fn(project_names_from_state_fn(state))
    records = []
    for project_name_raw in project_names:
        project_name = str(project_name_raw).strip()
        project_entry = metadata.get(project_name)
        action_entry = project_entry.get("migrate") if isinstance(project_entry, dict) else None
        record = migrate_result_record(
            failure_headline=migrate_failure_headline,
            project_name=project_name,
            action_entry=action_entry,
        )
        if record is None:
            continue
        records.append(record)
    if not records:
        return False
    print_migrate_result_records(
        records=records,
        env=getattr(runtime, "env", {}),
        interactive_tty=True,
    )
    return True
