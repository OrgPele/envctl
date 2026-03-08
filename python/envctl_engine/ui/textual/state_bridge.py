from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from typing import Any

from ...state.models import RunState


def render_dashboard_snapshot(*, runtime: Any, state: RunState) -> str:
    buffer = StringIO()
    with redirect_stdout(buffer):
        runtime._print_dashboard_snapshot(state)
    return buffer.getvalue().rstrip()
