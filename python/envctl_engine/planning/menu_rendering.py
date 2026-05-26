from __future__ import annotations

import os
import shutil


def render_planning_selection_menu(
    *,
    planning_files: list[str],
    selected_counts: dict[str, int],
    existing_counts: dict[str, int],
    cursor: int,
    message: str,
    terminal_width: int | None = None,
    terminal_height: int | None = None,
) -> str:
    width, height = terminal_size()
    if terminal_width is not None:
        width = max(40, int(terminal_width))
    if terminal_height is not None:
        height = max(10, int(terminal_height))

    total = len(planning_files)
    cursor = max(0, min(cursor, max(total - 1, 0)))
    start, end = visible_row_window(total=total, cursor=cursor, height=height, message=message)

    no_color = bool(os.environ.get("NO_COLOR"))
    reset = "" if no_color else "\033[0m"
    bold = "" if no_color else "\033[1m"
    dim = "" if no_color else "\033[2m"
    cyan = "" if no_color else "\033[36m"
    blue = "" if no_color else "\033[34m"
    green = "" if no_color else "\033[32m"
    yellow = "" if no_color else "\033[33m"
    magenta = "" if no_color else "\033[35m"
    red = "" if no_color else "\033[31m"

    lines: list[str] = []
    lines.append(f"{bold}{cyan}Planning Selection{reset}")
    legend = "UP/DOWN or j/k move  LEFT/RIGHT or h/l count  Space/x toggle  a all  n none  Enter run  q cancel"
    lines.append(f"{dim}{truncate_text(legend, width)}{reset}")
    lines.append("")
    for index in range(start, end):
        plan_file = planning_files[index]
        is_cursor = index == cursor
        pointer = f"{magenta}▶{reset}" if is_cursor else " "
        selected = int(selected_counts.get(plan_file, 0))
        existing = int(existing_counts.get(plan_file, 0))
        count_color = green if selected > 0 else yellow
        label_color = blue if is_cursor else ""
        prefix_plain = f" {'▶' if is_cursor else ' '} [{selected}x] "
        detail_plain = f" (existing {existing}x)" if existing > 0 else ""
        name_budget = width - len(prefix_plain) - len(detail_plain)
        if name_budget < 8:
            detail_plain = ""
            name_budget = width - len(prefix_plain)
        name_display = truncate_text(plan_file, name_budget)
        detail = f"{dim}{detail_plain}{reset}" if detail_plain else ""
        lines.append(f" {pointer} {count_color}[{selected}x]{reset} {label_color}{name_display}{reset}{detail}")

    lines.append("")
    selected_total = sum(1 for value in selected_counts.values() if int(value) > 0)
    lines.append(f"{dim}Selected plans: {selected_total}  Showing {start + 1}-{end} of {total}{reset}")
    if message:
        lines.append(f"{red}{truncate_text(message, width)}{reset}")
    return "\n".join(lines)


def visible_row_window(*, total: int, cursor: int, height: int, message: str) -> tuple[int, int]:
    header_lines = 4
    footer_lines = 3 if message else 2
    visible_rows = max(5, height - header_lines - footer_lines)

    if total <= visible_rows:
        return 0, total

    half = visible_rows // 2
    start = max(0, cursor - half)
    end = start + visible_rows
    if end > total:
        end = total
        start = max(0, end - visible_rows)
    return start, end


def terminal_size() -> tuple[int, int]:
    size = shutil.get_terminal_size(fallback=(100, 24))
    width = max(40, int(getattr(size, "columns", 100)))
    height = max(10, int(getattr(size, "lines", 24)))
    return width, height


def truncate_text(value: str, max_len: int) -> str:
    if max_len <= 0:
        return ""
    if len(value) <= max_len:
        return value
    if max_len <= 3:
        return "." * max_len
    return value[: max_len - 3] + "..."


def to_terminal_lines(frame: str) -> str:
    return frame.replace("\n", "\r\n")
