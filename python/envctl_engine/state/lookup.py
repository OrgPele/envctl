from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from typing import Any


def call_state_loader(
    loader: Callable[..., Any],
    *,
    mode: str | None = None,
    strict_mode_match: bool = False,
    project_names: Sequence[str] | None = None,
) -> Any:
    """Call current and legacy state-loader adapters without injecting unsupported keywords."""

    accepts_any_keyword, accepted_keywords = _accepted_keywords(loader)
    options: dict[str, object] = {}
    for keyword, value in (
        ("mode", mode),
        ("strict_mode_match", strict_mode_match),
    ):
        if accepts_any_keyword or keyword in accepted_keywords:
            options[keyword] = value
    if project_names is not None:
        if not accepts_any_keyword and "project_names" not in accepted_keywords:
            raise TypeError("Targeted state lookup requires a loader that accepts project_names")
        options["project_names"] = project_names
    return loader(**options)


def _accepted_keywords(loader: Callable[..., Any]) -> tuple[bool, frozenset[str]]:
    try:
        parameters = tuple(inspect.signature(loader).parameters.values())
    except (TypeError, ValueError):
        return True, frozenset()
    return (
        any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters),
        frozenset(
            parameter.name
            for parameter in parameters
            if parameter.kind in {inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
        ),
    )


__all__ = ["call_state_loader"]
