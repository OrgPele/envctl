from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .command_loop import run_dashboard_command_loop
    from .menu import MenuOption, MenuPresenter, build_menu_presenter
    from .target_selector import TargetSelection, TargetSelector
    from .terminal_session import TerminalSession, can_interactive_tty

__all__ = [
    "MenuOption",
    "MenuPresenter",
    "TerminalSession",
    "TargetSelection",
    "TargetSelector",
    "build_menu_presenter",
    "can_interactive_tty",
    "run_dashboard_command_loop",
]


def __getattr__(name: str) -> Any:
    if name == "run_dashboard_command_loop":
        from .command_loop import run_dashboard_command_loop

        return run_dashboard_command_loop
    if name in {"MenuOption", "MenuPresenter", "build_menu_presenter"}:
        from .menu import MenuOption, MenuPresenter, build_menu_presenter

        exports = {
            "MenuOption": MenuOption,
            "MenuPresenter": MenuPresenter,
            "build_menu_presenter": build_menu_presenter,
        }
        return exports[name]
    if name in {"TargetSelection", "TargetSelector"}:
        from .target_selector import TargetSelection, TargetSelector

        exports = {
            "TargetSelection": TargetSelection,
            "TargetSelector": TargetSelector,
        }
        return exports[name]
    if name in {"TerminalSession", "can_interactive_tty"}:
        from .terminal_session import TerminalSession, can_interactive_tty

        exports = {
            "TerminalSession": TerminalSession,
            "can_interactive_tty": can_interactive_tty,
        }
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
