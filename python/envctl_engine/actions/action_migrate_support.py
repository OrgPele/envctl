from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
import sys

from envctl_engine.ui.color_policy import colors_enabled
from envctl_engine.ui.path_links import render_path_for_terminal, render_path_fragment_for_terminal


@dataclass(frozen=True)
class MigrateResultRecord:
    project_name: str
    status: str
    headline: str = ""
    hint_lines: tuple[str, ...] = ()
    report_path: str = ""


def migrate_result_records(
    *,
    load_existing_state: Callable[[str], object | None],
    mode: str,
    project_names: list[str],
    fallback_entries: Mapping[str, Mapping[str, object]] | None,
    migrate_failure_headline: Callable[[str], str],
) -> list[MigrateResultRecord]:
    state = load_existing_state(mode)
    metadata = state.metadata.get("project_action_reports") if state is not None else None  # type: ignore[attr-defined]
    fallback_map = dict(fallback_entries) if isinstance(fallback_entries, Mapping) else {}
    records: list[MigrateResultRecord] = []
    for project_name_raw in project_names:
        project_name = str(project_name_raw).strip()
        if not project_name:
            continue
        project_entry = metadata.get(project_name) if isinstance(metadata, Mapping) else None
        action_entry = project_entry.get("migrate") if isinstance(project_entry, Mapping) else None
        if not isinstance(action_entry, Mapping):
            action_entry = fallback_map.get(project_name)
        record = migrate_result_record(
            project_name=project_name,
            action_entry=action_entry,
            migrate_failure_headline=migrate_failure_headline,
        )
        if record is not None:
            records.append(record)
    return records


def migrate_result_record(
    *,
    project_name: str,
    action_entry: Mapping[str, object] | None,
    migrate_failure_headline: Callable[[str], str],
) -> MigrateResultRecord | None:
    if not isinstance(action_entry, Mapping):
        return None
    status = str(action_entry.get("status", "")).strip().lower()
    if status == "success":
        return MigrateResultRecord(project_name=project_name, status="success")
    if status != "failed":
        return None
    summary = str(action_entry.get("summary", "")).strip()
    headline = str(action_entry.get("headline", "")).strip()
    if not headline and summary:
        headline = migrate_failure_headline(summary)
    hint_lines: list[str] = []
    seen_hints: set[str] = set()
    for line in [item.strip() for item in summary.splitlines() if item.strip()]:
        if not line.lower().startswith("hint:"):
            continue
        if line in seen_hints:
            continue
        seen_hints.add(line)
        hint_lines.append(line)
    report_path = str(action_entry.get("report_path", "")).strip()
    return MigrateResultRecord(
        project_name=project_name,
        status="failed",
        headline=headline,
        hint_lines=tuple(hint_lines),
        report_path=report_path,
    )


def print_migrate_result_records(
    *,
    records: list[MigrateResultRecord],
    env: Mapping[str, str],
    interactive_tty: bool | None = None,
) -> None:
    failed_records = [record for record in records if record.status == "failed"]
    compact_failures = len(failed_records) > 1
    shared_hints = shared_migrate_hint_lines(failed_records) if compact_failures else ()
    use_color = colors_enabled(
        env,
        stream=sys.stdout,
        interactive_tty=bool(interactive_tty) if interactive_tty is not None else False,
    )
    for index, record in enumerate(records):
        project_name = render_migrate_project_name(record.project_name, index=index, use_color=use_color)
        if record.status == "success":
            success_symbol = render_migrate_symbol("✓", status="success", use_color=use_color)
            print(f"{success_symbol} migrate succeeded for {project_name}")
            continue
        if record.status != "failed":
            continue
        failure_symbol = render_migrate_symbol("✗", status="failed", use_color=use_color)
        if record.headline:
            print(f"{failure_symbol} migrate failed for {project_name}: {record.headline}")
        else:
            print(f"{failure_symbol} migrate failed for {project_name}")
        if compact_failures:
            continue
        for hint in visible_migrate_hint_lines(record.hint_lines):
            print(hint)
    for hint in shared_hints:
        print(hint)
    print_migrate_failure_logs(
        failed_records,
        env=env,
        interactive_tty=interactive_tty,
        compact=compact_failures,
        use_color=use_color,
        ordered_records=records,
    )


def shared_migrate_hint_lines(records: list[MigrateResultRecord]) -> tuple[str, ...]:
    if len(records) <= 1:
        return ()
    visible_hint_lists = [visible_migrate_hint_lines(record.hint_lines) for record in records]
    if not visible_hint_lists:
        return ()
    shared = set(visible_hint_lists[0])
    for hint_lines in visible_hint_lists[1:]:
        shared.intersection_update(hint_lines)
    if not shared:
        return ()
    ordered_shared = [hint for hint in visible_hint_lists[0] if hint in shared]
    return tuple(ordered_shared[:1])


def visible_migrate_hint_lines(hint_lines: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(hint for hint in hint_lines if not is_migrate_env_source_hint(hint))


def is_migrate_env_source_hint(hint_line: str) -> bool:
    return hint_line.lower().startswith("hint: backend env source:")


def print_migrate_failure_logs(
    records: list[MigrateResultRecord],
    *,
    env: Mapping[str, str],
    interactive_tty: bool | None,
    compact: bool,
    use_color: bool,
    ordered_records: list[MigrateResultRecord],
) -> None:
    report_records = [record for record in records if record.report_path]
    if not report_records:
        return
    if compact:
        print_compact_migrate_failure_logs(
            report_records,
            env=env,
            interactive_tty=interactive_tty,
            use_color=use_color,
            ordered_records=ordered_records,
        )
        return
    for record in report_records:
        project_name = render_migrate_project_name(
            record.project_name,
            index=record_index(ordered_records, record.project_name),
            use_color=use_color,
        )
        print(f"migrate failure log for {project_name}:")
        print(render_path_for_terminal(record.report_path, env=env, stream=sys.stdout, interactive_tty=interactive_tty))


def print_compact_migrate_failure_logs(
    records: list[MigrateResultRecord],
    *,
    env: Mapping[str, str],
    interactive_tty: bool | None,
    use_color: bool,
    ordered_records: list[MigrateResultRecord],
) -> None:
    print("migrate failure logs:")
    shared_parent = shared_report_parent(records)
    if shared_parent:
        print(render_path_for_terminal(shared_parent, env=env, stream=sys.stdout, interactive_tty=interactive_tty))
        for record in records:
            display_name = Path(record.report_path).name
            rendered_path = render_path_fragment_for_terminal(
                record.report_path,
                display_text=display_name,
                env=env,
                stream=sys.stdout,
                interactive_tty=interactive_tty,
            )
            project_name = render_migrate_project_name(
                record.project_name,
                index=record_index(ordered_records, record.project_name),
                use_color=use_color,
            )
            print(f"- {project_name}: {rendered_path}")
        return
    for record in records:
        rendered_path = render_path_for_terminal(
            record.report_path,
            env=env,
            stream=sys.stdout,
            interactive_tty=interactive_tty,
        )
        project_name = render_migrate_project_name(
            record.project_name,
            index=record_index(ordered_records, record.project_name),
            use_color=use_color,
        )
        print(f"- {project_name}: {rendered_path}")


def shared_report_parent(records: list[MigrateResultRecord]) -> str:
    parents: list[str] = []
    for record in records:
        try:
            parent = str(Path(record.report_path).parent)
        except (OSError, RuntimeError, ValueError):
            return ""
        if not parent:
            return ""
        if parent not in parents:
            parents.append(parent)
    if len(parents) != 1:
        return ""
    return parents[0]


def record_index(records: list[MigrateResultRecord], project_name: str) -> int:
    for index, record in enumerate(records):
        if record.project_name == project_name:
            return index
    return 0


def render_migrate_symbol(symbol: str, *, status: str, use_color: bool) -> str:
    if not use_color:
        return symbol
    color = "32" if status == "success" else "31"
    return f"\033[1;{color}m{symbol}\033[0m"


def render_migrate_project_name(project_name: str, *, index: int, use_color: bool) -> str:
    if not use_color:
        return project_name
    palette = ("34", "35", "36", "32", "33")
    color = palette[index % len(palette)]
    return f"\033[1;{color}m{project_name}\033[0m"
