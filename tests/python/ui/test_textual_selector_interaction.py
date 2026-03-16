from __future__ import annotations

from contextlib import ExitStack
import importlib
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.ui.textual.screens import selector
from envctl_engine.ui import prompt_toolkit_cursor_menu

prompt_toolkit_impl = importlib.import_module("envctl_engine.ui.textual.screens.selector.prompt_toolkit_impl")


class _RuntimeDeep:
    def __init__(self, mode: str) -> None:
        self.env = {"ENVCTL_DEBUG_UI_MODE": mode}
        self.events: list[tuple[str, dict[str, object]]] = []

    def _emit(self, event: str, **payload: object) -> None:
        self.events.append((event, dict(payload)))


class TextualSelectorInteractionTests(unittest.TestCase):
    @staticmethod
    def _prompt_toolkit_available() -> bool:
        try:
            import importlib.util

            return importlib.util.find_spec("prompt_toolkit") is not None
        except Exception:
            return False

    def setUp(self) -> None:
        self._original_selector_impl = os.environ.get("ENVCTL_UI_SELECTOR_IMPL")
        self._original_simple_menus = os.environ.get("ENVCTL_UI_SIMPLE_MENUS")
        self._original_term_program = os.environ.get("TERM_PROGRAM")

    def tearDown(self) -> None:
        if self._original_selector_impl is None:
            os.environ.pop("ENVCTL_UI_SELECTOR_IMPL", None)
        else:
            os.environ["ENVCTL_UI_SELECTOR_IMPL"] = self._original_selector_impl
        if self._original_simple_menus is None:
            os.environ.pop("ENVCTL_UI_SIMPLE_MENUS", None)
        else:
            os.environ["ENVCTL_UI_SIMPLE_MENUS"] = self._original_simple_menus
        if self._original_term_program is None:
            os.environ.pop("TERM_PROGRAM", None)
        else:
            os.environ["TERM_PROGRAM"] = self._original_term_program

    def test_selector_id_is_stable_and_normalized(self) -> None:
        self.assertEqual(selector._selector_id("Restart Targets"), "restart_targets")  # noqa: SLF001
        self.assertEqual(selector._selector_id("   "), "selector")  # noqa: SLF001

    def test_selector_impl_defaults_to_textual(self) -> None:
        os.environ.pop("ENVCTL_UI_SELECTOR_IMPL", None)
        os.environ.pop("TERM_PROGRAM", None)
        self.assertEqual(selector._selector_impl(), "textual")  # noqa: SLF001

    def test_selector_impl_legacy_alias_maps_to_textual(self) -> None:
        os.environ["ENVCTL_UI_SELECTOR_IMPL"] = "legacy"
        self.assertEqual(selector._selector_impl(), "textual")  # noqa: SLF001

    def test_selector_impl_planning_style_override(self) -> None:
        os.environ["ENVCTL_UI_SELECTOR_IMPL"] = "planning_style"
        self.assertEqual(selector._selector_impl(), "planning_style")  # noqa: SLF001

    def test_selector_impl_simple_menus_env_enables_planning_style(self) -> None:
        os.environ.pop("ENVCTL_UI_SELECTOR_IMPL", None)
        os.environ["ENVCTL_UI_SIMPLE_MENUS"] = "1"
        self.assertEqual(selector._selector_impl(), "planning_style")  # noqa: SLF001

    def test_selector_impl_simple_menus_env_can_force_textual(self) -> None:
        os.environ["ENVCTL_UI_SELECTOR_IMPL"] = "planning_style"
        os.environ["ENVCTL_UI_SIMPLE_MENUS"] = "0"
        self.assertEqual(selector._selector_impl(), "textual")  # noqa: SLF001

    def test_selector_impl_uses_textual_for_apple_terminal_by_default(self) -> None:
        os.environ.pop("ENVCTL_UI_SELECTOR_IMPL", None)
        os.environ["TERM_PROGRAM"] = "Apple_Terminal"
        self.assertEqual(selector._selector_impl(), "textual")  # noqa: SLF001

    def test_run_selector_with_impl_uses_textual_on_apple_terminal_when_prompt_toolkit_unavailable(self) -> None:
        options = [
            selector.SelectorItem(  # type: ignore[attr-defined]
                id="service:alpha",
                label="Alpha",
                kind="service",
                token="alpha",
                scope_signature=("service:alpha",),
            ),
        ]
        os.environ.pop("ENVCTL_UI_SELECTOR_IMPL", None)
        os.environ["TERM_PROGRAM"] = "Apple_Terminal"
        with (
            patch("envctl_engine.ui.textual.screens.selector.can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.textual.screens.selector.prompt_toolkit_available", return_value=False),
            patch("envctl_engine.ui.textual.screens.selector._run_textual_selector") as textual_selector_run,
        ):
            values = selector._run_selector_with_impl(  # noqa: SLF001
                prompt="Restart",
                options=options,
                multi=True,
                emit=None,
            )

        self.assertIs(values, textual_selector_run.return_value)
        self.assertEqual(textual_selector_run.call_count, 1)

    def test_deep_debug_enabled_uses_runtime_emit_binding(self) -> None:
        deep_rt = _RuntimeDeep("deep")
        standard_rt = _RuntimeDeep("standard")

        self.assertTrue(selector._deep_debug_enabled(deep_rt._emit))  # noqa: SLF001
        self.assertFalse(selector._deep_debug_enabled(standard_rt._emit))  # noqa: SLF001

    def test_emit_selector_debug_respects_enabled_flag(self) -> None:
        runtime = _RuntimeDeep("deep")
        selector._emit_selector_debug(  # noqa: SLF001
            runtime._emit,
            enabled=False,
            event="ui.selector.key",
            selector_id="restart",
            key="up",
        )
        self.assertEqual(runtime.events, [])

        selector._emit_selector_debug(  # noqa: SLF001
            runtime._emit,
            enabled=True,
            event="ui.selector.key",
            selector_id="restart",
            key="down",
        )
        self.assertEqual(len(runtime.events), 1)
        self.assertEqual(runtime.events[0][0], "ui.selector.key")

    def test_selector_bindings_cancel_on_escape(self) -> None:
        options = [
            selector.SelectorItem(  # type: ignore[attr-defined]
                id="service:alpha",
                label="Alpha",
                kind="service",
                token="alpha",
                scope_signature=("service:alpha",),
            ),
        ]
        app = selector._run_textual_selector(  # type: ignore[assignment]
            prompt="Restart",
            options=options,
            multi=True,
            emit=None,
            build_only=True,
        )
        if app is None:
            self.skipTest("textual is not installed")
        actions_by_key = {binding.key: binding.action for binding in app.BINDINGS}
        self.assertIn("escape", actions_by_key)
        self.assertEqual(actions_by_key["escape"], "cancel")

    def test_prompt_toolkit_selector_disabled_for_build_only(self) -> None:
        with (
            patch("envctl_engine.ui.textual.screens.selector.can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.textual.screens.selector.prompt_toolkit_available", return_value=True),
        ):
            self.assertFalse(selector._prompt_toolkit_selector_enabled(build_only=True))  # noqa: SLF001

    def test_prompt_toolkit_selector_respects_forced_textual_backend(self) -> None:
        with (
            patch.dict("os.environ", {"ENVCTL_UI_SELECTOR_BACKEND": "textual"}, clear=False),
            patch("envctl_engine.ui.textual.screens.selector.can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.textual.screens.selector.prompt_toolkit_available", return_value=True),
        ):
            self.assertFalse(selector._prompt_toolkit_selector_enabled(build_only=False))  # noqa: SLF001

    def test_prompt_toolkit_selector_defaults_on_when_available(self) -> None:
        with (
            patch.dict(
                "os.environ",
                {
                    "ENVCTL_UI_SELECTOR_BACKEND": "",
                    "ENVCTL_UI_PROMPT_TOOLKIT": "",
                },
                clear=False,
            ),
            patch("envctl_engine.ui.textual.screens.selector.can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.textual.screens.selector.prompt_toolkit_available", return_value=True),
        ):
            self.assertTrue(selector._prompt_toolkit_selector_enabled(build_only=False))  # noqa: SLF001

    def test_run_selector_with_impl_defaults_to_textual_engine(self) -> None:
        options = [
            selector.SelectorItem(  # type: ignore[attr-defined]
                id="service:alpha",
                label="Alpha",
                kind="service",
                token="alpha",
                scope_signature=("service:alpha",),
            ),
        ]
        with (
            patch.dict("os.environ", {"ENVCTL_UI_SELECTOR_IMPL": ""}, clear=False),
            patch(
                "envctl_engine.ui.textual.screens.selector._run_textual_selector", return_value=["alpha"]
            ) as textual_selector_run,
            patch(
                "envctl_engine.ui.textual.screens.selector.run_prompt_toolkit_cursor_menu",
                return_value=SimpleNamespace(values=["alpha"], cancelled=False),
            ) as planning_menu_run,
        ):
            values = selector._run_selector_with_impl(  # noqa: SLF001
                prompt="Restart",
                options=options,
                multi=True,
                emit=None,
            )

        self.assertEqual(values, ["alpha"])
        self.assertEqual(textual_selector_run.call_count, 1)
        self.assertTrue(bool(textual_selector_run.call_args.kwargs.get("force_textual_backend")))
        self.assertEqual(planning_menu_run.call_count, 0)

    def test_run_selector_with_impl_forwards_initial_tokens_to_textual(self) -> None:
        options = [
            selector.SelectorItem(  # type: ignore[attr-defined]
                id="service:alpha",
                label="Alpha",
                kind="service",
                token="alpha",
                scope_signature=("service:alpha",),
            ),
        ]
        with (
            patch.dict("os.environ", {"ENVCTL_UI_SELECTOR_IMPL": ""}, clear=False),
            patch("envctl_engine.ui.textual.screens.selector._run_textual_selector", return_value=["alpha"]),
        ):
            values = selector._run_selector_with_impl(  # noqa: SLF001
                prompt="Restart",
                options=options,
                multi=True,
                initial_tokens=["alpha"],
                emit=None,
            )

        self.assertEqual(values, ["alpha"])

    def test_cursor_menu_prompt_toolkit_io_prefers_native_auto_tty(self) -> None:
        if not self._prompt_toolkit_available():
            self.skipTest("prompt_toolkit is not installed")
        with (
            patch("sys.stdin.isatty", return_value=False),
            patch("sys.stdout.isatty", return_value=True),
            patch("prompt_toolkit.input.defaults.create_input", return_value=object()) as create_input,
            patch("prompt_toolkit.output.defaults.create_output", return_value=object()) as create_output,
        ):
            with ExitStack() as stack:
                _ptk_input, _ptk_output, source = prompt_toolkit_cursor_menu._create_prompt_toolkit_tty_io(  # noqa: SLF001
                    stack=stack
                )

        self.assertEqual(source, "auto_tty_stdout")
        self.assertEqual(create_input.call_count, 1)
        self.assertEqual(create_output.call_count, 1)
        self.assertTrue(create_input.call_args.kwargs["always_prefer_tty"])
        self.assertTrue(create_output.call_args.kwargs["always_prefer_tty"])

    def test_selector_prompt_toolkit_io_prefers_native_auto_tty(self) -> None:
        if not self._prompt_toolkit_available():
            self.skipTest("prompt_toolkit is not installed")
        with (
            patch("sys.stdin.isatty", return_value=False),
            patch("sys.stdout.isatty", return_value=True),
            patch("prompt_toolkit.input.defaults.create_input", return_value=object()) as create_input,
            patch("prompt_toolkit.output.defaults.create_output", return_value=object()) as create_output,
        ):
            with ExitStack() as stack:
                _ptk_input, _ptk_output, source = prompt_toolkit_impl._create_prompt_toolkit_tty_io(  # noqa: SLF001
                    stack=stack
                )

        self.assertEqual(source, "auto_tty_stdout")
        self.assertEqual(create_input.call_count, 1)
        self.assertEqual(create_output.call_count, 1)
        self.assertTrue(create_input.call_args.kwargs["always_prefer_tty"])
        self.assertTrue(create_output.call_args.kwargs["always_prefer_tty"])

    def test_run_selector_with_impl_uses_planning_style_when_env_override_set(self) -> None:
        options = [
            selector.SelectorItem(  # type: ignore[attr-defined]
                id="service:alpha",
                label="Alpha",
                kind="service",
                token="alpha",
                scope_signature=("service:alpha",),
            ),
        ]
        with (
            patch.dict("os.environ", {"ENVCTL_UI_SELECTOR_IMPL": "planning_style"}, clear=False),
            patch("envctl_engine.ui.textual.screens.selector.can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.textual.screens.selector.prompt_toolkit_available", return_value=True),
            patch(
                "envctl_engine.ui.textual.screens.selector.run_prompt_toolkit_cursor_menu",
                return_value=SimpleNamespace(values=["alpha"], cancelled=False),
            ) as planning_menu_run,
            patch("envctl_engine.ui.textual.screens.selector._run_textual_selector") as textual_selector_run,
        ):
            values = selector._run_selector_with_impl(  # noqa: SLF001
                prompt="Restart",
                options=options,
                multi=True,
                emit=None,
            )

        self.assertEqual(values, ["alpha"])
        self.assertEqual(planning_menu_run.call_count, 1)
        self.assertEqual(textual_selector_run.call_count, 0)

    def test_run_selector_with_impl_forwards_initial_tokens_to_planning_style(self) -> None:
        options = [
            selector.SelectorItem(  # type: ignore[attr-defined]
                id="service:alpha",
                label="Alpha",
                kind="service",
                token="alpha",
                scope_signature=("service:alpha",),
            ),
        ]
        with (
            patch.dict("os.environ", {"ENVCTL_UI_SELECTOR_IMPL": "planning_style"}, clear=False),
            patch("envctl_engine.ui.textual.screens.selector.can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.textual.screens.selector.prompt_toolkit_available", return_value=True),
            patch(
                "envctl_engine.ui.textual.screens.selector.run_prompt_toolkit_cursor_menu",
                return_value=SimpleNamespace(values=["alpha"], cancelled=False),
            ) as planning_menu_run,
        ):
            values = selector._run_selector_with_impl(  # noqa: SLF001
                prompt="Restart",
                options=options,
                multi=True,
                initial_tokens=["alpha"],
                emit=None,
            )

        self.assertEqual(values, ["alpha"])
        self.assertEqual(planning_menu_run.call_count, 1)
        self.assertEqual(planning_menu_run.call_args.kwargs.get("initial_tokens"), ["alpha"])

    def test_run_selector_with_impl_uses_textual_when_legacy_alias_set(self) -> None:
        options = [
            selector.SelectorItem(  # type: ignore[attr-defined]
                id="service:alpha",
                label="Alpha",
                kind="service",
                token="alpha",
                scope_signature=("service:alpha",),
            ),
        ]
        with (
            patch.dict("os.environ", {"ENVCTL_UI_SELECTOR_IMPL": "legacy"}, clear=False),
            patch(
                "envctl_engine.ui.textual.screens.selector._run_textual_selector", return_value=["alpha"]
            ) as textual_selector_run,
            patch("envctl_engine.ui.textual.screens.selector.run_prompt_toolkit_cursor_menu") as planning_menu_run,
        ):
            values = selector._run_selector_with_impl(  # noqa: SLF001
                prompt="Restart",
                options=options,
                multi=True,
                emit=None,
            )

        self.assertEqual(values, ["alpha"])
        self.assertEqual(textual_selector_run.call_count, 1)
        self.assertEqual(planning_menu_run.call_count, 0)

    def test_run_selector_with_impl_emits_engine_payload_fields(self) -> None:
        options = [
            selector.SelectorItem(  # type: ignore[attr-defined]
                id="service:alpha",
                label="Alpha",
                kind="service",
                token="alpha",
                scope_signature=("service:alpha",),
            ),
        ]
        runtime = _RuntimeDeep("deep")
        with (
            patch.dict("os.environ", {"ENVCTL_UI_SELECTOR_IMPL": ""}, clear=False),
            patch("envctl_engine.ui.textual.screens.selector._run_textual_selector", return_value=["alpha"]),
        ):
            values = selector._run_selector_with_impl(  # noqa: SLF001
                prompt="Restart",
                options=options,
                multi=True,
                emit=runtime._emit,
            )
        self.assertEqual(values, ["alpha"])
        engine_events = [payload for name, payload in runtime.events if name == "ui.selector.engine"]
        self.assertTrue(engine_events)
        payload = engine_events[-1]
        self.assertEqual(payload.get("requested_impl"), "default")
        self.assertEqual(payload.get("effective_engine"), "textual_plan_style")
        self.assertEqual(payload.get("rollback_used"), False)

    def test_run_textual_selector_forced_backend_bypasses_prompt_toolkit(self) -> None:
        options = [
            selector.SelectorItem(  # type: ignore[attr-defined]
                id="service:alpha",
                label="Alpha",
                kind="service",
                token="alpha",
                scope_signature=("service:alpha",),
            ),
        ]
        with (
            patch(
                "envctl_engine.ui.textual.screens.selector._selector_backend_decision",
            ) as backend_decision,
            patch(
                "envctl_engine.ui.textual.screens.selector._run_prompt_toolkit_selector",
            ) as prompt_toolkit_selector,
        ):
            app = selector._run_textual_selector(  # type: ignore[assignment]
                prompt="Restart",
                options=options,
                multi=True,
                emit=None,
                build_only=True,
                force_textual_backend=True,
            )
        if app is None:
            self.skipTest("textual is not installed")
        self.assertEqual(backend_decision.call_count, 0)
        self.assertEqual(prompt_toolkit_selector.call_count, 0)


if __name__ == "__main__":
    unittest.main()
