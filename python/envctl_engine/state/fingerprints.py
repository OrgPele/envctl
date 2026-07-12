from __future__ import annotations

import hashlib
import json
from pathlib import Path

from envctl_engine.state import state_to_dict
from envctl_engine.state.models import RunState


def text_fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def state_fingerprint(state: RunState) -> str:
    return text_fingerprint(json.dumps(state_to_dict(state), sort_keys=True))
