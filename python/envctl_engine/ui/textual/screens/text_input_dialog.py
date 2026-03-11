from __future__ import annotations

from typing import Callable

from envctl_engine.ui.capabilities import textual_importable as _textual_importable
from envctl_engine.ui.textual.compat import apply_textual_driver_compat, textual_run_policy


def _emit(emit: Callable[..., None] | None, event: str, **payload: object) -> None:
    if callable(emit):
        emit(event, component="ui.textual.text_input_dialog", **payload)


def run_text_input_dialog_textual(
    *,
    title: str,
    help_text: str,
    placeholder: str = "",
    initial_value: str = "",
    emit: Callable[..., None] | None = None,
    build_only: bool = False,
) -> str | None | object:
    if not _textual_importable():
        _emit(emit, "ui.fallback.non_interactive", reason="textual_missing", command="text_input_dialog")
        return None

    run_policy = textual_run_policy(screen="text_input_dialog")

    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical
    from textual.widgets import Button, Footer, Static, TextArea

    class TextInputDialogApp(App[str | None]):
        CSS = """
        Screen {
            align: center middle;
            background: #121212;
        }

        #dialog {
            width: 78;
            max-width: 88%;
            padding: 1 2;
            background: #181818;
            border: solid #fea62b;
            height: auto;
        }

        #dialog-title {
            color: #e0e0e0;
            text-style: bold;
            margin-bottom: 1;
        }

        #dialog-help {
            color: #b0b0b0;
            margin-bottom: 1;
        }

        #dialog-input {
            margin-bottom: 1;
            min-height: 8;
            height: 8;
            max-height: 8;
        }

        #dialog-buttons {
            height: auto;
            align-horizontal: right;
        }

        #dialog-buttons Button {
            margin-left: 1;
        }
        """

        BINDINGS = [
            Binding("escape", "cancel", "Cancel"),
            Binding("q", "cancel", "Cancel"),
            Binding("ctrl+c", "cancel", "Cancel"),
            Binding("ctrl+enter", "save", "Save"),
        ]

        def compose(self) -> ComposeResult:
            with Vertical(id="dialog"):
                yield Static(title, id="dialog-title")
                yield Static(help_text, id="dialog-help")
                yield TextArea(initial_value, id="dialog-input")
                with Horizontal(id="dialog-buttons"):
                    yield Button("Cancel", id="cancel")
                    yield Button("Use default", id="default")
                    yield Button("Save", id="save", variant="success")
                yield Footer()

        def on_mount(self) -> None:
            try:
                apply_textual_driver_compat(
                    driver=self.driver,
                    screen="text_input_dialog",
                    mouse_enabled=run_policy.mouse,
                    disable_focus_reporting=True,
                    emit=emit,
                    selector_id="text-input-dialog",
                )
            except Exception:
                pass
            text_area = self.query_one("#dialog-input", TextArea)
            text_area.tooltip = placeholder
            text_area.focus()

        def action_cancel(self) -> None:
            self.exit(None)

        def action_save(self) -> None:
            self.exit(self.query_one("#dialog-input", TextArea).text)

        def on_button_pressed(self, event: Button.Pressed) -> None:
            button_id = str(getattr(event.button, "id", "") or "")
            if button_id == "cancel":
                self.exit(None)
                return
            if button_id == "default":
                self.exit("")
                return
            if button_id == "save":
                self.exit(self.query_one("#dialog-input", TextArea).text)
                return

    app = TextInputDialogApp()
    if build_only:
        return app
    return app.run()
