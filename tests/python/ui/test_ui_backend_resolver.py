from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.ui.backend_resolver import resolve_ui_backend


class UiBackendResolverTests(unittest.TestCase):
    def test_textual_backend_selected_when_forced_and_supported(self) -> None:
        with (
            patch("envctl_engine.ui.backend_resolver._textual_available", return_value=True),
            patch("envctl_engine.ui.backend_resolver._interactive_tty_available", return_value=True),
        ):
            result = resolve_ui_backend({"ENVCTL_UI_BACKEND": "textual"})

        self.assertEqual(result.backend, "textual")
        self.assertTrue(result.interactive)
        self.assertEqual(result.reason, "ok")

    def test_textual_backend_forced_without_tty_falls_back_non_interactive(self) -> None:
        with (
            patch("envctl_engine.ui.backend_resolver._textual_available", return_value=True),
            patch("envctl_engine.ui.backend_resolver._interactive_tty_available", return_value=False),
        ):
            result = resolve_ui_backend({"ENVCTL_UI_BACKEND": "textual"})

        self.assertEqual(result.backend, "non_interactive")
        self.assertFalse(result.interactive)
        self.assertEqual(result.reason, "non_tty")

    def test_legacy_backend_mode_selects_legacy_backend(self) -> None:
        with (
            patch("envctl_engine.ui.backend_resolver._textual_available", return_value=True),
            patch("envctl_engine.ui.backend_resolver._interactive_tty_available", return_value=True),
        ):
            result = resolve_ui_backend({"ENVCTL_UI_BACKEND": "legacy"})

        self.assertEqual(result.backend, "legacy")
        self.assertTrue(result.interactive)
        self.assertEqual(result.reason, "ok")

    def test_auto_backend_defaults_to_legacy_when_supported(self) -> None:
        with (
            patch("envctl_engine.ui.backend_resolver._textual_available", return_value=True),
            patch("envctl_engine.ui.backend_resolver._interactive_tty_available", return_value=True),
        ):
            result = resolve_ui_backend({"ENVCTL_UI_BACKEND": "auto"})

        self.assertEqual(result.backend, "legacy")
        self.assertTrue(result.interactive)
        self.assertEqual(result.reason, "default_legacy")

    def test_auto_backend_defaults_to_legacy_when_textual_missing(self) -> None:
        with (
            patch("envctl_engine.ui.backend_resolver._textual_available", return_value=False),
            patch("envctl_engine.ui.backend_resolver._interactive_tty_available", return_value=True),
        ):
            result = resolve_ui_backend({"ENVCTL_UI_BACKEND": "auto"})

        self.assertEqual(result.backend, "legacy")
        self.assertTrue(result.interactive)
        self.assertEqual(result.reason, "default_legacy")

    def test_auto_backend_experimental_opt_in_enables_textual_when_supported(self) -> None:
        with (
            patch("envctl_engine.ui.backend_resolver._textual_available", return_value=True),
            patch("envctl_engine.ui.backend_resolver._interactive_tty_available", return_value=True),
        ):
            result = resolve_ui_backend({"ENVCTL_UI_BACKEND": "auto", "ENVCTL_UI_EXPERIMENTAL_DASHBOARD": "1"})

        self.assertEqual(result.backend, "textual")
        self.assertTrue(result.interactive)
        self.assertEqual(result.reason, "experimental_opt_in")

    def test_textual_forced_without_textual_dependency_falls_back_to_legacy(self) -> None:
        with (
            patch("envctl_engine.ui.backend_resolver._textual_available", return_value=False),
            patch("envctl_engine.ui.backend_resolver._interactive_tty_available", return_value=True),
        ):
            result = resolve_ui_backend({"ENVCTL_UI_BACKEND": "textual"})

        self.assertEqual(result.backend, "legacy")
        self.assertTrue(result.interactive)
        self.assertEqual(result.reason, "textual_missing_fallback_legacy")
