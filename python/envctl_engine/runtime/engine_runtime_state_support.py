from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from envctl_engine.state.models import RunState
from envctl_engine.state import state_to_dict


def state_has_synthetic_services(state: RunState) -> bool:
    for service in state.services.values():
        if bool(getattr(service, "synthetic", False)):
            return True
        status = str(getattr(service, "status", "") or "").strip().lower()
        if status in {"simulated", "synthetic"}:
            return True
    return False


def on_port_event(runtime: Any, event_name: str, payload: dict[str, object]) -> None:
    runtime._emit(event_name, **payload)


def load_state_artifact(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_state_to_json(state: RunState) -> str:
    return json.dumps(state_to_dict(state), sort_keys=True)
