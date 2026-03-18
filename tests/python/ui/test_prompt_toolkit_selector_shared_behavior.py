from __future__ import annotations

from contextlib import contextmanager
import importlib.util
from types import ModuleType
import types
import unittest
from unittest.mock import patch

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.ui.prompt_toolkit_list import (
    PromptToolkitListConfig,
    PromptToolkitListResult,
    run_prompt_toolkit_list_selector,
)
from envctl_engine.ui.selector_model import SelectorItem


class PromptToolkitSelectorSharedBehaviorTests(unittest.TestCase):
    @staticmethod
    def _prompt_toolkit_available() -> bool:
        return importlib.util.find_spec("prompt_toolkit") is not None

    def test_runner_returns_empty_without_enabled_rows(self) -> None:
        result = run_prompt_toolkit_list_selector(
            PromptToolkitListConfig(
                prompt="Restart",
                options=[],
                multi=True,
                selector_id="restart",
                backend_label="prompt_toolkit",
                screen_name="selector_prompt_toolkit",
                focused_widget_id="selector-prompt-toolkit",
                deep_debug=False,
                driver_trace_enabled=False,
                wrap_navigation=False,
                cancel_on_escape=False,
            )
        )
        self.assertEqual(result, PromptToolkitListResult(values=[], cancelled=False))

    def test_runner_emits_lifecycle_for_configured_backend(self) -> None:
        if not self._prompt_toolkit_available():
            self.skipTest("prompt_toolkit is not installed")

        events: list[tuple[str, dict[str, object]]] = []
        debug_events: list[tuple[str, dict[str, object]]] = []
        options = [
            SelectorItem(
                id="service:alpha",
                label="Alpha",
                kind="service",
                token="alpha",
                scope_signature=("service:alpha",),
                section="Services",
            ),
            SelectorItem(
                id="service:beta",
                label="Beta",
                kind="service",
                token="beta",
                scope_signature=("service:beta",),
                section="Services",
            ),
        ]

        with patch(
            "prompt_toolkit.application.Application.run",
            return_value=PromptToolkitListResult(values=["alpha"], cancelled=False),
        ):
            result = run_prompt_toolkit_list_selector(
                PromptToolkitListConfig(
                    prompt="Restart",
                    options=options,
                    multi=True,
                    selector_id="restart",
                    backend_label="prompt_toolkit",
                    screen_name="selector_prompt_toolkit",
                    focused_widget_id="selector-prompt-toolkit",
                    deep_debug=True,
                    driver_trace_enabled=False,
                    wrap_navigation=False,
                    cancel_on_escape=False,
                    emit_event=lambda event, **payload: events.append((event, dict(payload))),
                    emit_debug=lambda event, **payload: debug_events.append((event, dict(payload))),
                )
            )

        self.assertEqual(result, PromptToolkitListResult(values=["alpha"], cancelled=False))
        self.assertIn("ui.screen.enter", [name for name, _payload in events])
        self.assertIn("ui.screen.exit", [name for name, _payload in events])
        self.assertIn("ui.selector.lifecycle", [name for name, _payload in debug_events])
        self.assertIn("ui.selector.key.summary", [name for name, _payload in debug_events])

    def test_runner_blocks_enter_without_explicit_multi_selection(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        debug_events: list[tuple[str, dict[str, object]]] = []
        options = [
            SelectorItem(
                id="service:alpha",
                label="Alpha",
                kind="service",
                token="alpha",
                scope_signature=("service:alpha",),
                section="Services",
            ),
            SelectorItem(
                id="service:beta",
                label="Beta",
                kind="service",
                token="beta",
                scope_signature=("service:beta",),
                section="Services",
            ),
        ]
        app_state = {"invalidated_after_enter": False}

        class _FakeBinding:
            def __init__(self, key: str, handler: object) -> None:
                self.keys = (types.SimpleNamespace(key=key),)
                self.handler = handler

        class _FakeKeyBindings:
            def __init__(self) -> None:
                self.bindings: list[_FakeBinding] = []

            def add(self, key: str):  # noqa: ANN202
                def _decorator(handler: object) -> object:
                    self.bindings.append(_FakeBinding(key, handler))
                    return handler

                return _decorator

        class _FakeApplication:
            def __init__(self, *, key_bindings: object, **_kwargs: object) -> None:
                self.key_bindings = key_bindings
                self.result: PromptToolkitListResult | None = None
                self.invalidated = False

            def exit(self, *, result: PromptToolkitListResult) -> None:
                self.result = result

            def invalidate(self) -> None:
                self.invalidated = True

            def run(self) -> PromptToolkitListResult | None:
                handlers = {binding.keys[0].key: binding.handler for binding in self.key_bindings.bindings}
                event = types.SimpleNamespace(app=self)
                handlers["enter"](event)
                app_state["invalidated_after_enter"] = self.invalidated
                if self.result is None:
                    handlers["q"](event)
                return self.result

        @contextmanager
        def _fake_instrument_prompt_toolkit_posix_io(**_kwargs: object):  # noqa: ANN003
            yield (lambda: {},)

        prompt_toolkit_module = ModuleType("prompt_toolkit")
        prompt_toolkit_module.__path__ = []  # type: ignore[attr-defined]
        application_module = ModuleType("prompt_toolkit.application")
        application_module.Application = _FakeApplication  # type: ignore[attr-defined]
        formatted_text_module = ModuleType("prompt_toolkit.formatted_text")
        formatted_text_module.ANSI = lambda text: text  # type: ignore[attr-defined]
        key_binding_module = ModuleType("prompt_toolkit.key_binding")
        key_binding_module.KeyBindings = _FakeKeyBindings  # type: ignore[attr-defined]
        layout_module = ModuleType("prompt_toolkit.layout")
        layout_module.Layout = lambda container: container  # type: ignore[attr-defined]
        layout_containers_module = ModuleType("prompt_toolkit.layout.containers")
        layout_containers_module.Window = lambda **kwargs: kwargs  # type: ignore[attr-defined]
        layout_controls_module = ModuleType("prompt_toolkit.layout.controls")
        layout_controls_module.FormattedTextControl = lambda **kwargs: kwargs  # type: ignore[attr-defined]

        fake_modules = {
            "prompt_toolkit": prompt_toolkit_module,
            "prompt_toolkit.application": application_module,
            "prompt_toolkit.formatted_text": formatted_text_module,
            "prompt_toolkit.key_binding": key_binding_module,
            "prompt_toolkit.layout": layout_module,
            "prompt_toolkit.layout.containers": layout_containers_module,
            "prompt_toolkit.layout.controls": layout_controls_module,
        }

        with (
            patch.dict(sys.modules, fake_modules, clear=False),
            patch(
                "envctl_engine.ui.prompt_toolkit_list.create_prompt_toolkit_tty_io",
                return_value=(object(), object(), "fake"),
            ),
            patch(
                "envctl_engine.ui.textual.screens.selector.support._instrument_prompt_toolkit_posix_io",
                _fake_instrument_prompt_toolkit_posix_io,
            ),
        ):
            result = run_prompt_toolkit_list_selector(
                PromptToolkitListConfig(
                    prompt="Restart",
                    options=options,
                    multi=True,
                    selector_id="restart",
                    backend_label="prompt_toolkit",
                    screen_name="selector_prompt_toolkit",
                    focused_widget_id="selector-prompt-toolkit",
                    deep_debug=True,
                    driver_trace_enabled=False,
                    wrap_navigation=False,
                    cancel_on_escape=False,
                    emit_event=lambda event, **payload: events.append((event, dict(payload))),
                    emit_debug=lambda event, **payload: debug_events.append((event, dict(payload))),
                )
            )

        self.assertEqual(result, PromptToolkitListResult(values=None, cancelled=True))
        self.assertIn(
            ("ui.selection.confirm", {"prompt": "Restart", "multi": True, "selected_count": 0, "blocked": True}),
            events,
        )
        self.assertIn(
            ("ui.selection.cancel", {"prompt": "Restart", "multi": True}),
            events,
        )
        self.assertIn(
            (
                "ui.selector.submit",
                {
                    "selector_id": "restart",
                    "selected_count": 0,
                    "blocked": True,
                    "cancelled": False,
                    "cause": "enter",
                },
            ),
            debug_events,
        )
        self.assertTrue(app_state["invalidated_after_enter"])

    def test_runner_submits_focused_row_on_enter_in_single_mode(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        debug_events: list[tuple[str, dict[str, object]]] = []
        options = [
            SelectorItem(
                id="service:alpha",
                label="Alpha",
                kind="service",
                token="alpha",
                scope_signature=("service:alpha",),
                section="Services",
            ),
            SelectorItem(
                id="service:beta",
                label="Beta",
                kind="service",
                token="beta",
                scope_signature=("service:beta",),
                section="Services",
            ),
        ]

        class _FakeBinding:
            def __init__(self, key: str, handler: object) -> None:
                self.keys = (types.SimpleNamespace(key=key),)
                self.handler = handler

        class _FakeKeyBindings:
            def __init__(self) -> None:
                self.bindings: list[_FakeBinding] = []

            def add(self, key: str):  # noqa: ANN202
                def _decorator(handler: object) -> object:
                    self.bindings.append(_FakeBinding(key, handler))
                    return handler

                return _decorator

        class _FakeApplication:
            def __init__(self, *, key_bindings: object, **_kwargs: object) -> None:
                self.key_bindings = key_bindings
                self.result: PromptToolkitListResult | None = None
                self.invalidated = False

            def exit(self, *, result: PromptToolkitListResult) -> None:
                self.result = result

            def invalidate(self) -> None:
                self.invalidated = True

            def run(self) -> PromptToolkitListResult | None:
                handlers = {binding.keys[0].key: binding.handler for binding in self.key_bindings.bindings}
                event = types.SimpleNamespace(app=self)
                handlers["down"](event)
                handlers["enter"](event)
                if self.result is None:
                    handlers["q"](event)
                return self.result

        @contextmanager
        def _fake_instrument_prompt_toolkit_posix_io(**_kwargs: object):  # noqa: ANN003
            yield (lambda: {},)

        prompt_toolkit_module = ModuleType("prompt_toolkit")
        prompt_toolkit_module.__path__ = []  # type: ignore[attr-defined]
        application_module = ModuleType("prompt_toolkit.application")
        application_module.Application = _FakeApplication  # type: ignore[attr-defined]
        formatted_text_module = ModuleType("prompt_toolkit.formatted_text")
        formatted_text_module.ANSI = lambda text: text  # type: ignore[attr-defined]
        key_binding_module = ModuleType("prompt_toolkit.key_binding")
        key_binding_module.KeyBindings = _FakeKeyBindings  # type: ignore[attr-defined]
        layout_module = ModuleType("prompt_toolkit.layout")
        layout_module.Layout = lambda container: container  # type: ignore[attr-defined]
        layout_containers_module = ModuleType("prompt_toolkit.layout.containers")
        layout_containers_module.Window = lambda **kwargs: kwargs  # type: ignore[attr-defined]
        layout_controls_module = ModuleType("prompt_toolkit.layout.controls")
        layout_controls_module.FormattedTextControl = lambda **kwargs: kwargs  # type: ignore[attr-defined]

        fake_modules = {
            "prompt_toolkit": prompt_toolkit_module,
            "prompt_toolkit.application": application_module,
            "prompt_toolkit.formatted_text": formatted_text_module,
            "prompt_toolkit.key_binding": key_binding_module,
            "prompt_toolkit.layout": layout_module,
            "prompt_toolkit.layout.containers": layout_containers_module,
            "prompt_toolkit.layout.controls": layout_controls_module,
        }

        with (
            patch.dict(sys.modules, fake_modules, clear=False),
            patch(
                "envctl_engine.ui.prompt_toolkit_list.create_prompt_toolkit_tty_io",
                return_value=(object(), object(), "fake"),
            ),
            patch(
                "envctl_engine.ui.textual.screens.selector.support._instrument_prompt_toolkit_posix_io",
                _fake_instrument_prompt_toolkit_posix_io,
            ),
        ):
            result = run_prompt_toolkit_list_selector(
                PromptToolkitListConfig(
                    prompt="Restart",
                    options=options,
                    multi=False,
                    selector_id="restart",
                    backend_label="prompt_toolkit",
                    screen_name="selector_prompt_toolkit",
                    focused_widget_id="selector-prompt-toolkit",
                    deep_debug=True,
                    driver_trace_enabled=False,
                    wrap_navigation=False,
                    cancel_on_escape=False,
                    emit_event=lambda event, **payload: events.append((event, dict(payload))),
                    emit_debug=lambda event, **payload: debug_events.append((event, dict(payload))),
                )
            )

        self.assertEqual(result, PromptToolkitListResult(values=["beta"], cancelled=False))
        self.assertIn(
            ("ui.selection.confirm", {"prompt": "Restart", "multi": False, "selected_count": 1}),
            events,
        )
        self.assertIn(
            (
                "ui.selector.submit",
                {
                    "selector_id": "restart",
                    "selected_count": 1,
                    "blocked": False,
                    "cancelled": False,
                    "cause": "enter",
                },
            ),
            debug_events,
        )

    def test_runner_exclusive_token_clears_other_multi_selections(self) -> None:
        options = [
            SelectorItem(
                id="scope:backend",
                label="Backend",
                kind="project",
                token="__PROJECT__:Backend",
                scope_signature=("scope:backend",),
                section="Scopes",
            ),
            SelectorItem(
                id="scope:frontend",
                label="Frontend",
                kind="project",
                token="__PROJECT__:Frontend",
                scope_signature=("scope:frontend",),
                section="Scopes",
            ),
            SelectorItem(
                id="scope:failed",
                label="Failed tests",
                kind="project",
                token="__PROJECT__:Failed tests",
                scope_signature=("scope:failed",),
                section="Scopes",
            ),
        ]

        class _FakeBinding:
            def __init__(self, key: str, handler: object) -> None:
                self.keys = (types.SimpleNamespace(key=key),)
                self.handler = handler

        class _FakeKeyBindings:
            def __init__(self) -> None:
                self.bindings: list[_FakeBinding] = []

            def add(self, key: str):  # noqa: ANN202
                def _decorator(handler: object) -> object:
                    self.bindings.append(_FakeBinding(key, handler))
                    return handler

                return _decorator

        class _FakeApplication:
            def __init__(self, *, key_bindings: object, **_kwargs: object) -> None:
                self.key_bindings = key_bindings
                self.result: PromptToolkitListResult | None = None

            def exit(self, *, result: PromptToolkitListResult) -> None:
                self.result = result

            def invalidate(self) -> None:
                return None

            def run(self) -> PromptToolkitListResult | None:
                handlers = {binding.keys[0].key: binding.handler for binding in self.key_bindings.bindings}
                event = types.SimpleNamespace(app=self)
                handlers[" "](event)
                handlers["down"](event)
                handlers[" "](event)
                handlers["down"](event)
                handlers[" "](event)
                handlers["enter"](event)
                return self.result

        @contextmanager
        def _fake_instrument_prompt_toolkit_posix_io(**_kwargs: object):  # noqa: ANN003
            yield (lambda: {},)

        prompt_toolkit_module = ModuleType("prompt_toolkit")
        prompt_toolkit_module.__path__ = []  # type: ignore[attr-defined]
        application_module = ModuleType("prompt_toolkit.application")
        application_module.Application = _FakeApplication  # type: ignore[attr-defined]
        formatted_text_module = ModuleType("prompt_toolkit.formatted_text")
        formatted_text_module.ANSI = lambda text: text  # type: ignore[attr-defined]
        key_binding_module = ModuleType("prompt_toolkit.key_binding")
        key_binding_module.KeyBindings = _FakeKeyBindings  # type: ignore[attr-defined]
        layout_module = ModuleType("prompt_toolkit.layout")
        layout_module.Layout = lambda container: container  # type: ignore[attr-defined]
        layout_containers_module = ModuleType("prompt_toolkit.layout.containers")
        layout_containers_module.Window = lambda **kwargs: kwargs  # type: ignore[attr-defined]
        layout_controls_module = ModuleType("prompt_toolkit.layout.controls")
        layout_controls_module.FormattedTextControl = lambda **kwargs: kwargs  # type: ignore[attr-defined]

        fake_modules = {
            "prompt_toolkit": prompt_toolkit_module,
            "prompt_toolkit.application": application_module,
            "prompt_toolkit.formatted_text": formatted_text_module,
            "prompt_toolkit.key_binding": key_binding_module,
            "prompt_toolkit.layout": layout_module,
            "prompt_toolkit.layout.containers": layout_containers_module,
            "prompt_toolkit.layout.controls": layout_controls_module,
        }

        with (
            patch.dict(sys.modules, fake_modules, clear=False),
            patch(
                "envctl_engine.ui.prompt_toolkit_list.create_prompt_toolkit_tty_io",
                return_value=(object(), object(), "fake"),
            ),
            patch(
                "envctl_engine.ui.textual.screens.selector.support._instrument_prompt_toolkit_posix_io",
                _fake_instrument_prompt_toolkit_posix_io,
            ),
        ):
            result = run_prompt_toolkit_list_selector(
                PromptToolkitListConfig(
                    prompt="Choose test scope",
                    options=options,
                    multi=True,
                    exclusive_token="__PROJECT__:Failed tests",
                    selector_id="test_scope",
                    backend_label="prompt_toolkit",
                    screen_name="selector_prompt_toolkit",
                    focused_widget_id="selector-prompt-toolkit",
                    deep_debug=False,
                    driver_trace_enabled=False,
                    wrap_navigation=False,
                    cancel_on_escape=False,
                )
            )

        self.assertEqual(result, PromptToolkitListResult(values=["__PROJECT__:Failed tests"], cancelled=False))

    def test_runner_a_key_toggles_all_visible_rows_in_multi_mode(self) -> None:
        options = [
            SelectorItem(
                id="service:alpha",
                label="Alpha",
                kind="service",
                token="alpha",
                scope_signature=("service:alpha",),
                section="Services",
            ),
            SelectorItem(
                id="service:beta",
                label="Beta",
                kind="service",
                token="beta",
                scope_signature=("service:beta",),
                section="Services",
            ),
        ]

        class _FakeBinding:
            def __init__(self, key: str, handler: object) -> None:
                self.keys = (types.SimpleNamespace(key=key),)
                self.handler = handler

        class _FakeKeyBindings:
            def __init__(self) -> None:
                self.bindings: list[_FakeBinding] = []

            def add(self, key: str):  # noqa: ANN202
                def _decorator(handler: object) -> object:
                    self.bindings.append(_FakeBinding(key, handler))
                    return handler

                return _decorator

        class _FakeApplication:
            def __init__(self, *, key_bindings: object, **_kwargs: object) -> None:
                self.key_bindings = key_bindings
                self.result: PromptToolkitListResult | None = None

            def exit(self, *, result: PromptToolkitListResult) -> None:
                self.result = result

            def invalidate(self) -> None:
                return None

            def run(self) -> PromptToolkitListResult | None:
                handlers = {binding.keys[0].key: binding.handler for binding in self.key_bindings.bindings}
                event = types.SimpleNamespace(app=self)
                handlers["a"](event)
                handlers["enter"](event)
                return self.result

        @contextmanager
        def _fake_instrument_prompt_toolkit_posix_io(**_kwargs: object):  # noqa: ANN003
            yield (lambda: {},)

        prompt_toolkit_module = ModuleType("prompt_toolkit")
        prompt_toolkit_module.__path__ = []  # type: ignore[attr-defined]
        application_module = ModuleType("prompt_toolkit.application")
        application_module.Application = _FakeApplication  # type: ignore[attr-defined]
        formatted_text_module = ModuleType("prompt_toolkit.formatted_text")
        formatted_text_module.ANSI = lambda text: text  # type: ignore[attr-defined]
        key_binding_module = ModuleType("prompt_toolkit.key_binding")
        key_binding_module.KeyBindings = _FakeKeyBindings  # type: ignore[attr-defined]
        layout_module = ModuleType("prompt_toolkit.layout")
        layout_module.Layout = lambda container: container  # type: ignore[attr-defined]
        layout_containers_module = ModuleType("prompt_toolkit.layout.containers")
        layout_containers_module.Window = lambda **kwargs: kwargs  # type: ignore[attr-defined]
        layout_controls_module = ModuleType("prompt_toolkit.layout.controls")
        layout_controls_module.FormattedTextControl = lambda **kwargs: kwargs  # type: ignore[attr-defined]

        fake_modules = {
            "prompt_toolkit": prompt_toolkit_module,
            "prompt_toolkit.application": application_module,
            "prompt_toolkit.formatted_text": formatted_text_module,
            "prompt_toolkit.key_binding": key_binding_module,
            "prompt_toolkit.layout": layout_module,
            "prompt_toolkit.layout.containers": layout_containers_module,
            "prompt_toolkit.layout.controls": layout_controls_module,
        }

        with (
            patch.dict(sys.modules, fake_modules, clear=False),
            patch(
                "envctl_engine.ui.prompt_toolkit_list.create_prompt_toolkit_tty_io",
                return_value=(object(), object(), "fake"),
            ),
            patch(
                "envctl_engine.ui.textual.screens.selector.support._instrument_prompt_toolkit_posix_io",
                _fake_instrument_prompt_toolkit_posix_io,
            ),
        ):
            result = run_prompt_toolkit_list_selector(
                PromptToolkitListConfig(
                    prompt="Restart",
                    options=options,
                    multi=True,
                    selector_id="restart",
                    backend_label="prompt_toolkit",
                    screen_name="selector_prompt_toolkit",
                    focused_widget_id="selector-prompt-toolkit",
                    deep_debug=False,
                    driver_trace_enabled=False,
                    wrap_navigation=False,
                    cancel_on_escape=False,
                )
            )

        self.assertEqual(result, PromptToolkitListResult(values=["alpha", "beta"], cancelled=False))


if __name__ == "__main__":
    unittest.main()
