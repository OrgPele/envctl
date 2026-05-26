from __future__ import annotations


def apply_planning_menu_key(
    *,
    key: str,
    cursor: int,
    planning_files: list[str],
    selected_counts: dict[str, int],
    existing_counts: dict[str, int],
) -> tuple[int, str, str]:
    if not planning_files:
        return cursor, "cancel", "No planning files available."

    max_index = len(planning_files) - 1
    cursor = max(0, min(cursor, max_index))
    current_plan = planning_files[cursor]

    if key == "up":
        return (cursor - 1) % len(planning_files), "continue", ""
    if key == "down":
        return (cursor + 1) % len(planning_files), "continue", ""
    if key in {"right", "inc"}:
        selected_counts[current_plan] = int(selected_counts.get(current_plan, 0)) + 1
        return cursor, "continue", ""
    if key in {"left", "dec"}:
        selected_counts[current_plan] = max(0, int(selected_counts.get(current_plan, 0)) - 1)
        return cursor, "continue", ""
    if key == "space":
        current = int(selected_counts.get(current_plan, 0))
        if current > 0:
            selected_counts[current_plan] = 0
        else:
            selected_counts[current_plan] = max(1, int(existing_counts.get(current_plan, 0)))
        return cursor, "continue", ""
    if key == "all":
        for plan_file in planning_files:
            selected_counts[plan_file] = max(1, int(selected_counts.get(plan_file, 0)))
        return cursor, "continue", ""
    if key == "none":
        for plan_file in planning_files:
            selected_counts[plan_file] = 0
        return cursor, "continue", ""
    if key == "enter":
        return cursor, "submit", ""
    if key in {"quit", "esc"}:
        return cursor, "cancel", ""
    return cursor, "continue", "Use arrows to navigate and adjust counts."


def submitted_planning_counts(
    *,
    planning_files: list[str],
    selected_counts: dict[str, int],
    existing_counts: dict[str, int],
) -> dict[str, int]:
    has_existing = any(int(existing_counts.get(plan_file, 0)) > 0 for plan_file in planning_files)
    if has_existing:
        return dict(selected_counts)
    return {plan_file: count for plan_file, count in selected_counts.items() if count > 0}
