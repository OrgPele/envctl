from __future__ import annotations

from envctl_engine.state.fingerprints import state_fingerprint as _state_fingerprint
from envctl_engine.state.models import RunState


def state_fingerprint(state: RunState) -> str:
    return _state_fingerprint(state)
