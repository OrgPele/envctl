from __future__ import annotations

import unittest
from unittest.mock import patch

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.ui import backend as ui_backend
from envctl_engine.ui.selection_types import TargetSelection


class _RuntimeStub:
    def __init__(self) -> None:
        self.flush_calls = 0
        self.events: list[tuple[str, dict[str, object]]] = []
        self.env: dict[str, str] = {}
        self.runtime_root = Path("/tmp/envctl-runtime-test")

    def _flush_pending_interactive_input(self) -> None:
        self.flush_calls += 1

    def _emit(self, event: str, **payload: object) -> None:
        self.events.append((event, dict(payload)))

    def _current_session_id(self) -> str:
        return "session-test"


class SelectorInputPreflightTests(unittest.TestCase):
    def test_preflight_emits_tty_transition_without_flush_or_drain_by_default(self) -> None:
        runtime = _RuntimeStub()
        with (
            patch("envctl_engine.ui.backend._stdin_tty_fd", return_value=7),
            patch("envctl_engine.ui.backend._normalize_stdin_line_mode", return_value=True),
            patch("envctl_engine.ui.backend._drain_stdin_escape_tail", return_value=5),
        ):
            ui_backend._run_selector_preflight(  # noqa: SLF001
                runtime,
                selector_kind="grouped",
                prompt="Restart",
                multi=True,
            )

        self.assertEqual(runtime.flush_calls, 0)
        names = [name for name, _payload in runtime.events]
        self.assertIn("ui.selector.preflight", names)
        self.assertIn("ui.tty.transition", names)
        end_events = [
            payload
            for name, payload in runtime.events
            if name == "ui.selector.preflight" and str(payload.get("stage", "")) == "end"
        ]
        self.assertTrue(end_events)
        self.assertEqual(int(end_events[-1].get("drained_bytes", 0)), 0)
        self.assertTrue(bool(end_events[-1].get("normalized", False)))
        self.assertFalse(bool(end_events[-1].get("flushed", True)))
        self.assertFalse(bool(end_events[-1].get("drain_enabled", True)))

    def test_preflight_flush_and_drain_can_be_enabled_explicitly(self) -> None:
        runtime = _RuntimeStub()
        with (
            patch.dict(
                "os.environ",
                {
                    "ENVCTL_UI_SELECTOR_PREFLIGHT_FLUSH": "1",
                    "ENVCTL_UI_SELECTOR_PREFLIGHT_DRAIN": "1",
                },
                clear=False,
            ),
            patch("envctl_engine.ui.backend._stdin_tty_fd", return_value=7),
            patch("envctl_engine.ui.backend._normalize_stdin_line_mode", return_value=True),
            patch("envctl_engine.ui.backend._drain_stdin_escape_tail", return_value=5),
        ):
            ui_backend._run_selector_preflight(  # noqa: SLF001
                runtime,
                selector_kind="grouped",
                prompt="Restart",
                multi=True,
            )

        self.assertEqual(runtime.flush_calls, 1)
        end_events = [
            payload
            for name, payload in runtime.events
            if name == "ui.selector.preflight" and str(payload.get("stage", "")) == "end"
        ]
        self.assertTrue(end_events)
        self.assertEqual(int(end_events[-1].get("drained_bytes", 0)), 5)
        self.assertTrue(bool(end_events[-1].get("flushed", False)))
        self.assertTrue(bool(end_events[-1].get("drain_enabled", False)))

    def test_preflight_flush_and_drain_default_on_apple_terminal_remains_disabled(self) -> None:
        runtime = _RuntimeStub()
        with (
            patch.dict("os.environ", {"TERM_PROGRAM": "Apple_Terminal"}, clear=False),
            patch("envctl_engine.ui.backend._selector_subprocess_enabled", return_value=False),
            patch("envctl_engine.ui.backend._stdin_tty_fd", return_value=7),
            patch("envctl_engine.ui.backend._normalize_stdin_line_mode", return_value=True),
            patch("envctl_engine.ui.backend._drain_stdin_escape_tail", return_value=3),
        ):
            ui_backend._run_selector_preflight(  # noqa: SLF001
                runtime,
                selector_kind="grouped",
                prompt="Restart",
                multi=True,
            )

        self.assertEqual(runtime.flush_calls, 0)
        end_events = [
            payload
            for name, payload in runtime.events
            if name == "ui.selector.preflight" and str(payload.get("stage", "")) == "end"
        ]
        self.assertTrue(end_events)
        self.assertEqual(int(end_events[-1].get("drained_bytes", 0)), 0)
        self.assertFalse(bool(end_events[-1].get("flushed", False)))
        self.assertFalse(bool(end_events[-1].get("drain_enabled", False)))

    def test_preflight_preserves_output_tty_state_on_apple_terminal_selector_subprocess(self) -> None:
        runtime = _RuntimeStub()
        with (
            patch.dict("os.environ", {"TERM_PROGRAM": "Apple_Terminal"}, clear=False),
            patch("envctl_engine.ui.backend._selector_subprocess_enabled", return_value=True),
            patch("envctl_engine.ui.backend._stdin_tty_fd", return_value=7),
            patch("envctl_engine.ui.backend._normalize_stdin_line_mode", return_value=True),
        ):
            ui_backend._run_selector_preflight(  # noqa: SLF001
                runtime,
                selector_kind="grouped",
                prompt="Restart",
                multi=True,
            )

        end_events = [
            payload
            for name, payload in runtime.events
            if name == "ui.selector.preflight" and str(payload.get("stage", "")) == "end"
        ]
        self.assertTrue(end_events)
        self.assertTrue(bool(end_events[-1].get("preserved_output_tty_state", False)))

    def test_preflight_tty_termios_group_skips_output_normalization_when_disabled(self) -> None:
        runtime = _RuntimeStub()
        runtime.env = {
            "ENVCTL_DEBUG_PLAN_ORCH_GROUP": "tty",
            "ENVCTL_DEBUG_PLAN_TTY_GROUP": "reader",
        }
        with (
            patch.dict("os.environ", {"TERM_PROGRAM": "Apple_Terminal"}, clear=False),
            patch("envctl_engine.ui.terminal_session.normalize_standard_tty_state") as normalize_tty,
            patch("envctl_engine.ui.backend._stdin_tty_fd", return_value=7),
            patch("envctl_engine.ui.backend._normalize_stdin_line_mode", return_value=True),
        ):
            ui_backend._run_selector_preflight(  # noqa: SLF001
                runtime,
                selector_kind="grouped",
                prompt="Restart",
                multi=True,
            )

        normalize_tty.assert_not_called()
        tty_events = [
            payload
            for name, payload in runtime.events
            if name == "startup.debug_tty_group"
        ]
        self.assertTrue(
            any(
                str(payload.get("group", "")) == "termios"
                and str(payload.get("action", "")) == "normalize_standard_tty_state"
                and payload.get("enabled") is False
                for payload in tty_events
            )
        )

    def test_preflight_tty_reader_group_can_skip_stdin_restore_and_drain(self) -> None:
        runtime = _RuntimeStub()
        runtime.env = {
            "ENVCTL_DEBUG_PLAN_ORCH_GROUP": "tty",
            "ENVCTL_DEBUG_PLAN_TTY_GROUP": "termios",
        }
        with (
            patch("envctl_engine.ui.backend._stdin_tty_fd", return_value=7),
            patch("envctl_engine.ui.backend._normalize_stdin_line_mode") as normalize_stdin,
            patch("envctl_engine.ui.backend._drain_stdin_escape_tail") as drain_tail,
        ):
            ui_backend._run_selector_preflight(  # noqa: SLF001
                runtime,
                selector_kind="grouped",
                prompt="Restart",
                multi=True,
            )

        normalize_stdin.assert_not_called()
        drain_tail.assert_not_called()
        end_events = [
            payload
            for name, payload in runtime.events
            if name == "ui.selector.preflight" and str(payload.get("stage", "")) == "end"
        ]
        self.assertTrue(end_events)
        self.assertFalse(bool(end_events[-1].get("normalized", True)))
        self.assertFalse(bool(end_events[-1].get("drain_enabled", True)))
        tty_events = [
            payload
            for name, payload in runtime.events
            if name == "startup.debug_tty_group"
        ]
        self.assertTrue(
            any(
                str(payload.get("group", "")) == "reader"
                and str(payload.get("action", "")) == "stdin_restore_and_drain"
                and payload.get("enabled") is False
                for payload in tty_events
            )
        )

    def test_preflight_non_tty_still_emits_begin_end(self) -> None:
        runtime = _RuntimeStub()
        with patch("envctl_engine.ui.backend._stdin_tty_fd", return_value=None):
            ui_backend._run_selector_preflight(  # noqa: SLF001
                runtime,
                selector_kind="project",
                prompt="Test targets",
                multi=False,
            )

        self.assertEqual(runtime.flush_calls, 0)
        end_events = [
            payload
            for name, payload in runtime.events
            if name == "ui.selector.preflight" and str(payload.get("stage", "")) == "end"
        ]
        self.assertTrue(end_events)
        self.assertFalse(bool(end_events[-1].get("tty", True)))
        self.assertEqual(int(end_events[-1].get("drained_bytes", -1)), 0)

    def test_textual_backend_project_and_grouped_paths_call_preflight(self) -> None:
        runtime = _RuntimeStub()
        backend = ui_backend.TextualInteractiveBackend()
        with (
            patch("envctl_engine.ui.backend._run_selector_preflight") as preflight,
            patch(
                "envctl_engine.ui.textual.screens.selector.select_project_targets_textual",
                return_value=object(),
            ),
            patch(
                "envctl_engine.ui.textual.screens.selector.select_grouped_targets_textual",
                return_value=object(),
            ),
        ):
            backend.select_project_targets(
                prompt="Select test target",
                projects=[],
                allow_all=True,
                allow_untested=True,
                multi=True,
                runtime=runtime,
            )
            backend.select_grouped_targets(
                prompt="Restart",
                projects=[],
                services=[],
                allow_all=True,
                multi=True,
                runtime=runtime,
            )

        self.assertEqual(preflight.call_count, 2)

    def test_legacy_backend_project_and_grouped_paths_call_preflight(self) -> None:
        runtime = _RuntimeStub()
        backend = ui_backend.LegacyInteractiveBackend()
        with (
            patch("envctl_engine.ui.backend._run_selector_preflight") as preflight,
            patch(
                "envctl_engine.ui.textual.screens.selector.select_project_targets_textual",
                return_value=object(),
            ),
            patch(
                "envctl_engine.ui.textual.screens.selector.select_grouped_targets_textual",
                return_value=object(),
            ),
        ):
            backend.select_project_targets(
                prompt="Select test target",
                projects=[],
                allow_all=True,
                allow_untested=True,
                multi=True,
                runtime=runtime,
            )
            backend.select_grouped_targets(
                prompt="Restart",
                projects=[],
                services=[],
                allow_all=True,
                multi=True,
                runtime=runtime,
            )

        self.assertEqual(preflight.call_count, 2)

    def test_character_mode_launch_enabled_for_selector_handoff(self) -> None:
        self.assertFalse(ui_backend._selector_launch_character_mode_enabled())  # noqa: SLF001

    def test_character_mode_launch_can_be_enabled_explicitly(self) -> None:
        with patch.dict("os.environ", {"ENVCTL_UI_SELECTOR_CHARACTER_MODE": "1"}, clear=False):
            self.assertTrue(ui_backend._selector_launch_character_mode_enabled())  # noqa: SLF001

    def test_selector_subprocess_enabled_by_default_on_apple_terminal(self) -> None:
        runtime = _RuntimeStub()
        with patch.dict("os.environ", {"TERM_PROGRAM": "Apple_Terminal"}, clear=False):
            self.assertTrue(ui_backend._selector_subprocess_enabled(runtime))  # noqa: SLF001

    def test_selector_subprocess_can_be_disabled_explicitly(self) -> None:
        runtime = _RuntimeStub()
        with patch.dict(
            "os.environ",
            {"TERM_PROGRAM": "Apple_Terminal", "ENVCTL_UI_TEXTUAL_SELECTOR_SUBPROCESS": "0"},
            clear=False,
        ):
            self.assertFalse(ui_backend._selector_subprocess_enabled(runtime))  # noqa: SLF001

    def test_grouped_selector_uses_subprocess_when_enabled(self) -> None:
        runtime = _RuntimeStub()
        backend = ui_backend.TextualInteractiveBackend()
        projects = [type("Project", (), {"name": "Project A"})()]
        with (
            patch("envctl_engine.ui.backend._run_selector_preflight"),
            patch("envctl_engine.ui.backend._selector_subprocess_enabled", return_value=True),
            patch(
                "envctl_engine.ui.backend._run_selector_subprocess",
                return_value=TargetSelection(service_names=["Project A Backend"]),
            ) as run_subprocess,
        ):
            selection = backend.select_grouped_targets(
                prompt="Run tests for",
                projects=projects,
                services=["Project A Backend"],
                allow_all=True,
                multi=True,
                runtime=runtime,
            )
        self.assertEqual(selection.service_names, ["Project A Backend"])
        run_subprocess.assert_called_once()

    def test_selector_subprocess_does_not_force_character_mode(self) -> None:
        runtime = _RuntimeStub()
        runtime.env = {"TERM_PROGRAM": "Apple_Terminal"}
        payload = {
            "kind": "grouped",
            "prompt": "Run tests for",
            "project_names": ["Project A"],
            "services": ["Project A Backend"],
            "allow_all": True,
            "multi": True,
        }
        with (
            patch("envctl_engine.ui.backend.subprocess.run") as run_subprocess,
            patch("envctl_engine.ui.backend.tempfile.TemporaryDirectory") as tmpdir_factory,
            patch("envctl_engine.ui.backend.Path.write_text"),
            patch("envctl_engine.ui.backend.Path.read_text", return_value='{"cancelled": true}'),
            patch("envctl_engine.ui.terminal_session.temporary_tty_character_mode") as char_mode,
        ):
            tmpdir_factory.return_value.__enter__.return_value = "/tmp/envctl-selector-test"
            tmpdir_factory.return_value.__exit__.return_value = False
            ui_backend._run_selector_subprocess(runtime=runtime, payload=payload)  # noqa: SLF001

        run_subprocess.assert_called_once()
        char_mode.assert_not_called()

    def test_selector_subprocess_tty_termios_group_can_skip_pendin_wrapper(self) -> None:
        runtime = _RuntimeStub()
        runtime.env = {
            "TERM_PROGRAM": "Apple_Terminal",
            "ENVCTL_DEBUG_PLAN_ORCH_GROUP": "tty",
            "ENVCTL_DEBUG_PLAN_TTY_GROUP": "reader",
        }
        payload = {
            "kind": "grouped",
            "prompt": "Run tests for",
            "project_names": ["Project A"],
            "services": ["Project A Backend"],
            "allow_all": True,
            "multi": True,
        }
        with (
            patch("envctl_engine.ui.backend.subprocess.run") as run_subprocess,
            patch("envctl_engine.ui.backend.tempfile.TemporaryDirectory") as tmpdir_factory,
            patch("envctl_engine.ui.backend.Path.write_text"),
            patch("envctl_engine.ui.backend.Path.read_text", return_value='{"cancelled": true}'),
            patch("envctl_engine.ui.terminal_session.temporary_standard_output_pendin") as pendin_mode,
        ):
            tmpdir_factory.return_value.__enter__.return_value = "/tmp/envctl-selector-test"
            tmpdir_factory.return_value.__exit__.return_value = False
            ui_backend._run_selector_subprocess(runtime=runtime, payload=payload)  # noqa: SLF001

        run_subprocess.assert_called_once()
        pendin_mode.assert_not_called()

    def test_escape_tail_drain_is_nonblocking(self) -> None:
        with (
            patch(
                "envctl_engine.ui.backend.select.select",
                side_effect=[([9], [], []), ([], [], [])],
            ) as select_call,
            patch("envctl_engine.ui.backend.os.read", return_value=b"x"),
        ):
            drained = ui_backend._drain_stdin_escape_tail(  # noqa: SLF001
                fd=9,
                max_window_seconds=0.03,
                max_bytes=8,
            )

        self.assertEqual(drained, 1)
        self.assertGreaterEqual(select_call.call_count, 1)
        for call in select_call.call_args_list:
            self.assertEqual(call.args[3], 0)


if __name__ == "__main__":
    unittest.main()
