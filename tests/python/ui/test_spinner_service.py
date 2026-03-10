from __future__ import annotations

import unittest
from unittest.mock import patch

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.ui.spinner import spinner, use_spinner_policy
from envctl_engine.ui.spinner_service import RichSpinnerOperation, SpinnerPolicy, resolve_spinner_policy


class SpinnerServicePolicyTests(unittest.TestCase):
    def test_spinner_defaults_to_dots_style(self) -> None:
        with patch("envctl_engine.ui.spinner_service._rich_available", return_value=True):
            policy = resolve_spinner_policy(
                {
                    "ENVCTL_UI_SPINNER_MODE": "auto",
                },
                stream_isatty=True,
            )
        self.assertEqual(policy.style, "dots")

    def test_spinner_mode_off_disables_with_env_reason(self) -> None:
        policy = resolve_spinner_policy(
            {
                "ENVCTL_UI_SPINNER_MODE": "off",
            },
            stream_isatty=True,
        )
        self.assertFalse(policy.enabled)
        self.assertEqual(policy.reason, "env_off")
        self.assertEqual(policy.mode, "off")

    def test_spinner_mode_on_overrides_ci_and_compat_flags_when_tty(self) -> None:
        with patch("envctl_engine.ui.spinner_service._rich_available", return_value=True):
            policy = resolve_spinner_policy(
                {
                    "ENVCTL_UI_SPINNER_MODE": "on",
                    "CI": "1",
                    "ENVCTL_UI_SPINNER": "false",
                },
                stream_isatty=True,
            )
        self.assertTrue(policy.enabled)
        self.assertEqual(policy.reason, "")
        self.assertEqual(policy.mode, "on")

    def test_spinner_auto_disables_in_ci(self) -> None:
        with patch("envctl_engine.ui.spinner_service._rich_available", return_value=True):
            policy = resolve_spinner_policy(
                {
                    "ENVCTL_UI_SPINNER_MODE": "auto",
                    "CI": "true",
                },
                stream_isatty=True,
            )
        self.assertFalse(policy.enabled)
        self.assertEqual(policy.reason, "ci_mode")
        self.assertEqual(policy.mode, "auto")

    def test_spinner_auto_uses_prompt_toolkit_when_rich_missing(self) -> None:
        with (
            patch("envctl_engine.ui.spinner_service._rich_available", return_value=False),
            patch("envctl_engine.ui.spinner_service._prompt_toolkit_available", return_value=True),
        ):
            policy = resolve_spinner_policy(
                {
                    "ENVCTL_UI_SPINNER_MODE": "auto",
                },
                stream_isatty=True,
            )
        self.assertTrue(policy.enabled)
        self.assertEqual(policy.backend, "prompt_toolkit")
        self.assertEqual(policy.reason, "")

    def test_spinner_disables_when_no_backend_available(self) -> None:
        with (
            patch("envctl_engine.ui.spinner_service._rich_available", return_value=False),
            patch("envctl_engine.ui.spinner_service._prompt_toolkit_available", return_value=False),
        ):
            policy = resolve_spinner_policy(
                {
                    "ENVCTL_UI_SPINNER_MODE": "auto",
                },
                stream_isatty=True,
            )
        self.assertFalse(policy.enabled)
        self.assertEqual(policy.reason, "spinner_backend_missing")

    def test_spinner_input_phase_guard_disables_even_when_otherwise_enabled(self) -> None:
        with patch("envctl_engine.ui.spinner_service._rich_available", return_value=True):
            policy = resolve_spinner_policy(
                {
                    "ENVCTL_UI_SPINNER_MODE": "on",
                },
                stream_isatty=True,
                input_phase=True,
            )
        self.assertFalse(policy.enabled)
        self.assertEqual(policy.reason, "input_phase_guard")

    def test_spinner_operation_supports_explicit_start_api(self) -> None:
        events: list[dict[str, object]] = []

        def emit(event_name: str, **payload: object) -> None:
            item = {"event": event_name}
            item.update(payload)
            events.append(item)

        op = RichSpinnerOperation(
            message="Running tests...",
            policy=SpinnerPolicy(
                mode="auto",
                enabled=False,
                reason="env_off",
                backend="rich",
                min_ms=0,
                verbose_events=False,
            ),
            emit=emit,
            start_immediately=False,
        )
        op.start()
        op.succeed("Done")
        op.end()

        lifecycle = [entry for entry in events if entry.get("event") == "ui.spinner.lifecycle"]
        self.assertTrue(any(entry.get("state") == "start" for entry in lifecycle))
        self.assertTrue(any(entry.get("state") == "success" for entry in lifecycle))
        self.assertTrue(any(entry.get("state") == "stop" for entry in lifecycle))

    def test_spinner_begin_forces_backend_start_even_with_min_delay(self) -> None:
        class _ProbeOperation(RichSpinnerOperation):
            def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
                self.force_calls: list[bool] = []
                super().__init__(*args, **kwargs)

            def _start_backend(self, *, force: bool = False) -> bool:  # type: ignore[override]
                self.force_calls.append(bool(force))
                return False

        operation = _ProbeOperation(
            message="Preparing startup...",
            policy=SpinnerPolicy(
                mode="auto",
                enabled=True,
                reason="",
                backend="rich",
                min_ms=120,
                verbose_events=False,
            ),
            start_immediately=True,
        )
        operation.end()

        self.assertTrue(operation.force_calls)
        self.assertTrue(operation.force_calls[0])

    def test_spinner_context_uses_caller_resolved_policy(self) -> None:
        captured: list[SpinnerPolicy] = []

        class _StubSpinner:
            def __init__(self, *, message: str, policy: SpinnerPolicy, start_immediately: bool) -> None:
                _ = message, start_immediately
                captured.append(policy)

            def end(self) -> None:
                return None

        policy = SpinnerPolicy(
            mode="on",
            enabled=True,
            reason="",
            backend="rich",
            min_ms=0,
            verbose_events=False,
            style="bouncingbar",
        )
        with (
            patch("envctl_engine.ui.spinner.Spinner", _StubSpinner),
            patch(
                "envctl_engine.ui.spinner.resolve_spinner_policy", side_effect=AssertionError("unexpected recompute")
            ),
        ):
            with use_spinner_policy(policy), spinner("Running...", enabled=True, start_immediately=False):
                pass

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].style, "bouncingbar")
        self.assertEqual(captured[0].mode, "on")


if __name__ == "__main__":
    unittest.main()
