from __future__ import annotations

import contextlib
import importlib
import os
import unittest
from unittest.mock import patch

from envctl_engine.ui.textual.compat import apply_textual_driver_compat, textual_run_policy

selector_impl = importlib.import_module("envctl_engine.ui.textual.screens.selector.textual_impl")


class TextualCompatTests(unittest.TestCase):
    def test_textual_run_policy_defaults_to_mouse_enabled(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            policy = textual_run_policy(screen="selector")
        self.assertTrue(policy.mouse)
        self.assertEqual(policy.reason, "default")

    def test_textual_run_policy_disables_mouse_for_apple_terminal(self) -> None:
        with patch.dict(os.environ, {"TERM_PROGRAM": "Apple_Terminal"}, clear=True):
            policy = textual_run_policy(screen="selector")
        self.assertFalse(policy.mouse)
        self.assertEqual(policy.reason, "apple_terminal_selector_compat")

    def test_textual_run_policy_respects_env_override(self) -> None:
        with patch.dict(
            os.environ,
            {"TERM_PROGRAM": "Apple_Terminal", "ENVCTL_UI_TEXTUAL_MOUSE": "1"},
            clear=True,
        ):
            policy = textual_run_policy(screen="selector")
        self.assertTrue(policy.mouse)
        self.assertEqual(policy.reason, "env_override_on")

    def test_selector_run_uses_apple_terminal_mouse_compat_policy(self) -> None:
        options = []
        from envctl_engine.ui.selector_model import SelectorItem

        options.append(
            SelectorItem(
                id="service:alpha",
                label="Alpha",
                kind="service",
                token="alpha",
                scope_signature=("service:alpha",),
            )
        )

        class _App:
            explicit_cancel = False

            def fallback_values(self):  # pragma: no cover - defensive
                return []

            def run(self, **kwargs):
                self.kwargs = kwargs
                return ["alpha"]

        app = _App()

        @contextlib.contextmanager
        def _guard(**_kwargs):
            yield

        @contextlib.contextmanager
        def _instrument(**_kwargs):
            yield lambda: {}

        with (
            patch.dict(os.environ, {"TERM_PROGRAM": "Apple_Terminal"}, clear=True),
            patch.object(selector_impl, "_textual_importable", return_value=True),
            patch.object(selector_impl, "_guard_textual_nonblocking_read", _guard),
            patch.object(selector_impl, "_instrument_textual_parser_keys", _instrument),
            patch.object(selector_impl, "create_selector_app", return_value=app),
            patch.object(selector_impl, "_selector_backend_decision", return_value=(False, {})),
        ):
            result = selector_impl.run_textual_selector(
                prompt="Run tests for",
                options=options,
                multi=False,
                emit=None,
                force_textual_backend=True,
            )

        self.assertEqual(result, ["alpha"])
        self.assertEqual(app.kwargs.get("mouse"), False)

    def test_selector_run_enters_tty_character_mode_during_direct_textual_handoff(self) -> None:
        options = []
        from envctl_engine.ui.selector_model import SelectorItem

        options.append(
            SelectorItem(
                id="service:alpha",
                label="Alpha",
                kind="service",
                token="alpha",
                scope_signature=("service:alpha",),
            )
        )

        class _App:
            explicit_cancel = False

            def fallback_values(self):  # pragma: no cover - defensive
                return []

            def run(self, **_kwargs):
                return ["alpha"]

        app = _App()
        character_mode_calls: list[int] = []

        @contextlib.contextmanager
        def _guard(**_kwargs):
            yield

        @contextlib.contextmanager
        def _instrument(**_kwargs):
            yield lambda: {}

        @contextlib.contextmanager
        def _character_mode(*, fd: int, emit=None):  # noqa: ANN001
            _ = emit
            character_mode_calls.append(fd)
            yield True

        class _FakeStdin:
            def fileno(self) -> int:
                return 0

        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(selector_impl, "_textual_importable", return_value=True),
            patch.object(selector_impl, "_guard_textual_nonblocking_read", _guard),
            patch.object(selector_impl, "_instrument_textual_parser_keys", _instrument),
            patch.object(selector_impl, "create_selector_app", return_value=app),
            patch.object(selector_impl, "_selector_backend_decision", return_value=(False, {})),
            patch.object(selector_impl, "temporary_tty_character_mode", _character_mode),
            patch.object(selector_impl.os, "isatty", return_value=True),
            patch.object(selector_impl.sys, "stdin", _FakeStdin()),
        ):
            result = selector_impl.run_textual_selector(
                prompt="Run tests for",
                options=options,
                multi=False,
                emit=None,
                force_textual_backend=True,
            )

        self.assertEqual(result, ["alpha"])
        self.assertEqual(character_mode_calls, [0])

    def test_apply_textual_driver_compat_disables_mouse_protocols(self) -> None:
        writes: list[str] = []

        class _Driver:
            def write(self, data: str) -> None:
                writes.append(data)

            def flush(self) -> None:
                writes.append("<flush>")

        apply_textual_driver_compat(
            driver=_Driver(),
            screen="selector",
            mouse_enabled=False,
            disable_focus_reporting=True,
            emit=None,
            selector_id="run_tests_for",
        )

        rendered = "".join(part for part in writes if part != "<flush>")
        self.assertIn("\x1b[?1000l", rendered)
        self.assertIn("\x1b[?1006l", rendered)
        self.assertIn("\x1b[?1004l", rendered)
        self.assertIn("\x1b[?2004l", rendered)
