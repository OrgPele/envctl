from __future__ import annotations

import hashlib
import json

from envctl_engine.state import state_to_dict
from envctl_engine.state.models import RunState


def state_fingerprint(state: RunState) -> str:
    payload = json.dumps(state_to_dict(state), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
