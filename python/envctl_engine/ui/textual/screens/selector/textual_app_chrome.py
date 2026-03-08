from __future__ import annotations


SELECTOR_BINDINGS = [
    ("q", "cancel", "Cancel"),
    ("ctrl+c", "cancel", "Cancel"),
    ("enter", "submit", "Confirm", False, True),
    ("space", "toggle", "Toggle", False, True),
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


SELECTOR_CSS = """
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
#selector-list {
    height: 1fr;
    border: round $surface;
}
#selector-actions {
    margin-top: 1;
    align-horizontal: right;
    height: auto;
}
ListItem.-highlight {
    background: $warning 14%;
    border-left: wide $warning;
    color: $text;
}
.selector-row {
    padding: 0 1;
    width: 100%;
}
.selector-row-selected {
    background: $success 12%;
    border-left: wide $success;
}
.selector-row-unselected.-highlight {
    background: $warning 18%;
    border-left: wide $warning;
}
.selector-row-selected.-highlight {
    background: $accent 30%;
    border-left: wide $accent;
}
.selector-row-selected Label {
    color: $success;
    text-style: bold;
}
.selector-row-selected.-highlight Label {
    color: $text;
    text-style: bold underline;
}
.selector-row-unselected Label {
    color: $text;
}
.kind-synthetic-all Label,
.kind-synthetic-untested Label {
    color: $warning;
}
"""
