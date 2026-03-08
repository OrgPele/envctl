from __future__ import annotations

from typing import Callable, Iterable, Mapping, Sequence

from .selection_types import TargetSelection
from .textual.screens.selector import select_grouped_targets_textual, select_project_targets_textual


class TargetSelector:
    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        menu: object | None = None,
        emit: Callable[..., None] | None = None,
    ) -> None:
        self._env = dict(env or {})
        self._menu = menu
        self._emit = emit
        if menu is not None and callable(emit):
            emit(
                "ui.selector.legacy_menu.deprecated",
                component="ui.target_selector",
                backend="textual",
            )

    def select_project_targets(
        self,
        *,
        prompt: str,
        projects: Iterable[object],
        allow_all: bool,
        allow_untested: bool,
        multi: bool,
        initial_project_names: Sequence[str] | None = None,
    ) -> TargetSelection:
        _ = self._env, self._menu
        return select_project_targets_textual(
            prompt=prompt,
            projects=list(projects),
            allow_all=allow_all,
            allow_untested=allow_untested,
            multi=multi,
            initial_project_names=initial_project_names,
            emit=self._emit,
        )

    def select_grouped_targets(
        self,
        *,
        prompt: str,
        projects: Iterable[object],
        services: Sequence[str],
        allow_all: bool,
        multi: bool,
    ) -> TargetSelection:
        _ = self._env, self._menu
        return select_grouped_targets_textual(
            prompt=prompt,
            projects=list(projects),
            services=list(services),
            allow_all=allow_all,
            multi=multi,
            emit=self._emit,
        )
