from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Mapping

from .capabilities import interactive_tty_available, textual_importable
from envctl_engine.shared.parsing import parse_bool


@dataclass(slots=True)
class UiBackendResolution:
    requested_mode: str
    backend: str
    interactive: bool
    reason: str


def _textual_available() -> bool:
    return textual_importable()


def _interactive_tty_available() -> bool:
    return interactive_tty_available()


def resolve_ui_backend(env: Mapping[str, str] | None = None) -> UiBackendResolution:
    return resolve_ui_backend_with_capabilities(env)


def resolve_ui_backend_with_capabilities(
    env: Mapping[str, str] | None = None,
    *,
    interactive_tty: bool | None = None,
    textual_available: bool | None = None,
) -> UiBackendResolution:
    merged = dict(os.environ)
    if env:
        merged.update(env)

    requested = str(merged.get("ENVCTL_UI_BACKEND", "auto")).strip().lower()
    if requested not in {"auto", "textual", "non_interactive", "legacy"}:
        requested = "auto"

    if requested == "non_interactive":
        return UiBackendResolution(
            requested_mode=requested,
            backend="non_interactive",
            interactive=False,
            reason="env_forced_non_interactive",
        )

    tty_ok_raw = _interactive_tty_available() if interactive_tty is None else bool(interactive_tty)
    tty_ok = tty_ok_raw or parse_bool(merged.get("ENVCTL_UI_TEXTUAL_HEADLESS_ALLOWED"), False)
    if not tty_ok:
        return UiBackendResolution(
            requested_mode=requested,
            backend="non_interactive",
            interactive=False,
            reason="non_tty",
        )

    textual_ok = _textual_available() if textual_available is None else bool(textual_available)
    experimental_dashboard = parse_bool(merged.get("ENVCTL_UI_EXPERIMENTAL_DASHBOARD"), False)

    if requested == "legacy":
        return UiBackendResolution(
            requested_mode=requested,
            backend="legacy",
            interactive=True,
            reason="ok",
        )

    if requested == "textual":
        if textual_ok:
            return UiBackendResolution(
                requested_mode=requested,
                backend="textual",
                interactive=True,
                reason="ok",
            )
        return UiBackendResolution(
            requested_mode=requested,
            backend="legacy",
            interactive=True,
            reason="textual_missing_fallback_legacy",
        )

    # auto: legacy is the default interactive dashboard.
    if experimental_dashboard and textual_ok:
        return UiBackendResolution(
            requested_mode=requested,
            backend="textual",
            interactive=True,
            reason="experimental_opt_in",
        )
    return UiBackendResolution(
        requested_mode=requested,
        backend="legacy",
        interactive=True,
        reason="default_legacy",
    )
