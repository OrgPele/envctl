from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, Sequence, TypeVar


TRow = TypeVar("TRow")


@dataclass(slots=True)
class RenderCheckpoint:
    previous_model_index: int | None
    filter_has_focus: bool


class TextualListController(Generic[TRow]):
    def __init__(
        self,
        rows: Sequence[TRow],
        *,
        initial_model_index: int | None = None,
    ) -> None:
        self._rows = list(rows)
        self.index_map: list[int] = list(range(len(self._rows)))
        self._initial_model_index = initial_model_index

    def capture_render_checkpoint(
        self,
        *,
        view_index: int | None,
        filter_has_focus: bool,
    ) -> RenderCheckpoint:
        return RenderCheckpoint(
            previous_model_index=self.focused_model_index(view_index),
            filter_has_focus=filter_has_focus,
        )

    def restore_view_index(self, checkpoint: RenderCheckpoint) -> int | None:
        previous_model_index = checkpoint.previous_model_index
        if not self.index_map:
            return None
        if previous_model_index is not None and previous_model_index in self.index_map:
            return self.index_map.index(previous_model_index)
        if self._initial_model_index is not None and self._initial_model_index in self.index_map:
            return self.index_map.index(self._initial_model_index)
        return 0

    def finish_render(self) -> None:
        self._initial_model_index = None

    def focused_model_index(self, view_index: int | None) -> int | None:
        if view_index is None or view_index < 0 or view_index >= len(self.index_map):
            return None
        return self.index_map[view_index]

    def focused_row(self, view_index: int | None) -> TRow | None:
        model_index = self.focused_model_index(view_index)
        if model_index is None:
            return None
        return self._rows[model_index]

    def cursor_up(self, current_index: int | None) -> int | None:
        if not self.index_map:
            return None
        current = current_index if current_index is not None else 0
        return max(0, current - 1)

    def cursor_down(self, current_index: int | None) -> int | None:
        if not self.index_map:
            return None
        current = current_index if current_index is not None else 0
        return min(len(self.index_map) - 1, current + 1)

    def ensure_list_index(self, current_index: int | None) -> int | None:
        if not self.index_map:
            return None
        if current_index is None or current_index < 0:
            return 0
        if current_index >= len(self.index_map):
            return len(self.index_map) - 1
        return current_index

    @staticmethod
    def cycle_focus_target(*, current_target: str, focus_order: Sequence[str]) -> str:
        ordered_targets = [str(target).strip() for target in focus_order if str(target).strip()]
        if not ordered_targets:
            return current_target
        try:
            current_index = ordered_targets.index(current_target)
        except ValueError:
            return ordered_targets[0]
        return ordered_targets[(current_index + 1) % len(ordered_targets)]

    def apply_visible_toggle(
        self,
        *,
        is_visible: Callable[[TRow], bool],
        is_active: Callable[[TRow], bool],
        activate: Callable[[TRow], None],
        deactivate: Callable[[TRow], None],
    ) -> bool | None:
        visible_rows = [row for row in self._rows if is_visible(row)]
        if not visible_rows:
            return None
        should_activate = not all(is_active(row) for row in visible_rows)
        for row in visible_rows:
            if should_activate:
                activate(row)
            else:
                deactivate(row)
        return should_activate
