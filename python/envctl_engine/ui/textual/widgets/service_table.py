from __future__ import annotations

from ..state_bridge import render_dashboard_snapshot


def dashboard_snapshot_text(*, runtime, state) -> str:  # noqa: ANN001
    return render_dashboard_snapshot(runtime=runtime, state=state)
