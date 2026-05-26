from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from envctl_engine.ui.textual.screens.selector import backend_policy


class _Runtime:
    def __init__(self, env: dict[str, str]) -> None:
        self.env = env

    def emit(self, event: str, **payload: object) -> None:
        _ = (event, payload)


class SelectorBackendPolicyTests(unittest.TestCase):
    def test_selector_impl_honors_simple_menu_aliases_before_selector_impl(self) -> None:
        with patch.dict(
            os.environ,
            {
                "ENVCTL_UI_SIMPLE_MENUS": "true",
                "ENVCTL_UI_SELECTOR_IMPL": "textual",
            },
            clear=False,
        ):
            self.assertEqual(backend_policy.selector_impl(), "planning_style")

        with patch.dict(
            os.environ,
            {
                "ENVCTL_UI_SIMPLE_MENUS": "false",
                "ENVCTL_UI_SELECTOR_IMPL": "planning_style",
            },
            clear=False,
        ):
            self.assertEqual(backend_policy.selector_impl(), "textual")

    def test_backend_decision_records_reason_and_falls_back_when_prompt_toolkit_forced_without_tty(self) -> None:
        with (
            patch.dict(os.environ, {"ENVCTL_UI_SELECTOR_BACKEND": "prompt_toolkit"}, clear=False),
            patch.object(backend_policy, "can_interactive_tty", return_value=False),
            patch.object(backend_policy, "prompt_toolkit_available", return_value=True),
        ):
            enabled, info = backend_policy.selector_backend_decision(build_only=False)

        self.assertFalse(enabled)
        self.assertEqual(info["reason"], "env_forced_prompt_toolkit")
        self.assertEqual(info["backend"], "textual")
        self.assertFalse(info["can_interactive_tty"])

    def test_backend_decision_uses_default_prompt_toolkit_when_available_on_tty(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(backend_policy, "can_interactive_tty", return_value=True),
            patch.object(backend_policy, "prompt_toolkit_available", return_value=True),
        ):
            enabled, info = backend_policy.selector_backend_decision(build_only=False)

        self.assertTrue(enabled)
        self.assertEqual(info["reason"], "default_prompt_toolkit")
        self.assertEqual(info["backend"], "prompt_toolkit")

    def test_debug_flags_prefer_runtime_env_over_process_env(self) -> None:
        runtime = _Runtime(
            {
                "ENVCTL_DEBUG_UI_MODE": "deep",
                "ENVCTL_DEBUG_SELECTOR_KEYS": "0",
                "ENVCTL_DEBUG_SELECTOR_DRIVER_KEYS": "",
                "ENVCTL_UI_SELECTOR_FOCUS_REPORTING": "enabled",
            }
        )

        with patch.dict(
            os.environ,
            {
                "ENVCTL_DEBUG_SELECTOR_KEYS": "1",
                "ENVCTL_UI_SELECTOR_FOCUS_REPORTING": "disabled",
            },
            clear=False,
        ):
            self.assertTrue(backend_policy.deep_debug_enabled(runtime.emit))
            self.assertFalse(backend_policy.selector_key_trace_enabled(runtime.emit))
            self.assertTrue(backend_policy.selector_driver_trace_enabled(runtime.emit))
            self.assertFalse(backend_policy.selector_disable_focus_reporting_enabled(runtime.emit))

    def test_selector_id_normalizes_prompt_to_stable_token(self) -> None:
        self.assertEqual(backend_policy.selector_id("Pick: Main + Trees!"), "pick_main_trees")
        self.assertEqual(backend_policy.selector_id("!!!"), "selector")


if __name__ == "__main__":
    unittest.main()
