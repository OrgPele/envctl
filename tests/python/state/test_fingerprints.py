from __future__ import annotations

from pathlib import Path

from envctl_engine.runtime.state_fingerprint_support import (
    state_fingerprint as runtime_state_fingerprint,
)
from envctl_engine.state.fingerprints import file_fingerprint, state_fingerprint, text_fingerprint
from envctl_engine.state.models import RunState


def test_shared_fingerprint_helpers_agree_for_text_file_and_runtime_facade(tmp_path: Path) -> None:
    payload = "deterministic payload\n"
    path = tmp_path / "payload.txt"
    path.write_text(payload, encoding="utf-8")

    assert file_fingerprint(path) == text_fingerprint(payload)

    state = RunState(run_id="run-1", mode="trees", metadata={"project_names": ["alpha"]})
    assert runtime_state_fingerprint(state) == state_fingerprint(state)


def test_state_fingerprint_changes_with_serialized_state() -> None:
    first = RunState(run_id="run-1", mode="main")
    second = RunState(run_id="run-1", mode="main", metadata={"changed": True})

    assert state_fingerprint(first) != state_fingerprint(second)
