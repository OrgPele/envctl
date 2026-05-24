from __future__ import annotations

from collections.abc import Callable


def run_planning_selection_menu(
    *,
    planning_files: list[str],
    selected_counts: dict[str, int],
    existing_counts: dict[str, int],
    flush_pending_interactive_input: Callable[[], None],
    emit: Callable[..., None] | None,
    select_planning_counts: Callable[..., object],
) -> dict[str, int] | None:
    from envctl_engine.ui.terminal_session import _reset_terminal_escape_modes, normalize_standard_tty_state

    try:
        flush_pending_interactive_input()
        chosen = select_planning_counts(
            planning_files=planning_files,
            selected_counts=selected_counts,
            existing_counts=existing_counts,
            emit=emit,
        )
        if chosen is None:
            return None
        if not isinstance(chosen, dict):
            return None
        return {str(plan_file): int(count) for plan_file, count in chosen.items()}
    except Exception:
        return {str(plan_file): int(count) for plan_file, count in selected_counts.items() if int(count) > 0}
    finally:
        normalize_standard_tty_state(emit=emit, component="planning.worktree_domain")
        _reset_terminal_escape_modes(emit=emit)
