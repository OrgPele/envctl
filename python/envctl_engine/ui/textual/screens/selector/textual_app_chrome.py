from __future__ import annotations

from envctl_engine.ui.textual.list_row_styles import selectable_list_row_css


SELECTOR_BINDINGS = [
    ("q", "cancel", "Cancel"),
    ("ctrl+c", "cancel", "Cancel"),
    ("enter", "submit", "Confirm", False, True),
    ("space", "toggle", "Toggle", False, True),
    ("a", "toggle_visible", "All", True, True),
    ("ctrl+a", "toggle_visible", "Toggle visible", False, True),
    ("/", "focus_filter", "Filter"),
    ("tab", "cycle_focus", "Focus"),
    ("escape", "cancel", "Cancel", False, True),
    ("up", "nav_up", "Up", False, True),
    ("down", "nav_down", "Down", False, True),
    ("j", "nav_down", "Down", False, True),
    ("s", "nav_down", "Down", False, True),
    ("k", "nav_up", "Up", False, True),
    ("w", "nav_up", "Up", False, True),
]

SELECTOR_ROW_STYLES_CSS = selectable_list_row_css("selector-row")

SELECTOR_CSS = (
    """
Screen {
    align: center middle;
}
#selector-shell {
    width: 94%;
    max-width: 140;
    height: 94%;
    border: round $accent;
    padding: 1 2;
}
#selector-prompt {
    margin-bottom: 1;
    text-style: bold;
}
#selector-filter {
    margin-bottom: 1;
}
#selector-status {
    margin-bottom: 1;
    color: $text-muted;
}
#selector-status.selector-status-error {
    color: $error;
    text-style: bold;
}
#selector-list {
    height: 1fr;
    border: round $surface;
}
#selector-actions {
    margin-top: 1;
    align-horizontal: right;
    height: auto;
}
"""
    + SELECTOR_ROW_STYLES_CSS
    + """
.kind-synthetic-untested Label {
    color: $warning;
}
"""
)
