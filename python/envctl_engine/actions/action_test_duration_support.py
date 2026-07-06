from __future__ import annotations

import time
from typing import Any

from envctl_engine.test_output.symbols import format_duration


def started_test_timer() -> float:
    return time.monotonic()


def print_test_action_duration(orchestrator: Any, *, started_at: float, interactive_command: bool) -> None:
    text = f"Test action duration: {format_duration(max(time.monotonic() - started_at, 0.0))}"
    if interactive_command:
        orchestrator._emit_status(text)
    else:
        print(text)
