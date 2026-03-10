from __future__ import annotations

from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime import engine_runtime_ui_bridge as bridge  # noqa: E402
from envctl_engine.state.models import RunState  # noqa: E402


class _BackendStub:
    __module__ = "tests.backend_stub"

    def __init__(self) -> None:
        self.dashboard_calls = 0
        self.project_calls = 0
        self.grouped_calls = 0

    def run_dashboard_loop(self, *, state: RunState, runtime: object) -> int:  # noqa: ARG002
        self.dashboard_calls += 1
        return 11

    def select_project_targets(self, **kwargs):  # noqa: ANN003
        self.project_calls += 1
        return kwargs["prompt"]

    def select_grouped_targets(self, **kwargs):  # noqa: ANN003
        self.grouped_calls += 1
        return kwargs["prompt"]


class EngineRuntimeUiBridgeTests(unittest.TestCase):
    def test_parse_interactive_command_returns_none_for_invalid_syntax(self) -> None:
        self.assertIsNone(bridge.parse_interactive_command('"unterminated'))

    def test_read_interactive_command_line_uses_terminal_session(self) -> None:
        runtime = SimpleNamespace(
            env={"ENVCTL_UI_BASIC_INPUT": "1"},
            _emit=lambda *_args, **_kwargs: None,
            _debug_recorder=None,
        )

        class _SessionStub:
            def __init__(self, env, *, prefer_basic_input: bool, emit, debug_recorder) -> None:  # noqa: ANN001
                self.env = env
                self.prefer_basic_input = prefer_basic_input
                self.emit = emit
                self.debug_recorder = debug_recorder

            def read_command_line(self, prompt: str) -> str:
                return f"{prompt}|{self.prefer_basic_input}"

        with patch("envctl_engine.ui.terminal_session.TerminalSession", _SessionStub):
            value = bridge.read_interactive_command_line(runtime, "Enter command: ")

        self.assertEqual(value, "Enter command: |True")

    def test_current_ui_backend_refreshes_when_resolution_changes(self) -> None:
        class _RefreshBackend(_BackendStub):
            __module__ = "envctl_engine.ui.backend"

        backend = _RefreshBackend()
        selected_events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(
            env={},
            ui_backend=backend,
            ui_backend_resolution=SimpleNamespace(backend="legacy", reason="ok", interactive=True),
            _can_interactive_tty=lambda: True,
            _emit=lambda event, **payload: selected_events.append((event, payload)),
        )
        new_resolution = SimpleNamespace(
            backend="textual",
            reason="textual_available",
            interactive=True,
            requested_mode="auto",
        )
        replacement_backend = object()

        with (
            patch(
                "envctl_engine.runtime.engine_runtime_ui_bridge.resolve_ui_backend_with_capabilities",
                return_value=new_resolution,
            ),
            patch(
                "envctl_engine.runtime.engine_runtime_ui_bridge.build_interactive_backend",
                return_value=replacement_backend,
            ),
        ):
            resolved = bridge.current_ui_backend(runtime)

        self.assertIs(resolved, replacement_backend)
        self.assertIs(runtime.ui_backend, replacement_backend)
        self.assertTrue(any(event == "ui.backend.selected" for event, _ in selected_events))

    def test_dashboard_and_selection_helpers_delegate_to_backend(self) -> None:
        backend = _BackendStub()
        runtime = SimpleNamespace(
            ui_backend=backend,
            ui_backend_resolution=SimpleNamespace(backend="legacy", reason="ok", interactive=True),
            env={},
            _can_interactive_tty=lambda: True,
            _emit=lambda *_args, **_kwargs: None,
        )

        code = bridge.run_interactive_dashboard_loop(runtime, RunState(run_id="run-1", mode="main"))
        selected_project = bridge.select_project_targets(
            runtime,
            prompt="Select project",
            projects=[],
            allow_all=True,
            allow_untested=False,
            multi=True,
        )
        selected_group = bridge.select_grouped_targets(
            runtime,
            prompt="Select group",
            projects=[],
            services=[],
            allow_all=True,
            multi=True,
        )

        self.assertEqual(code, 11)
        self.assertEqual(selected_project, "Select project")
        self.assertEqual(selected_group, "Select group")
        self.assertEqual(backend.dashboard_calls, 1)
        self.assertEqual(backend.project_calls, 1)
        self.assertEqual(backend.grouped_calls, 1)


if __name__ == "__main__":
    unittest.main()
