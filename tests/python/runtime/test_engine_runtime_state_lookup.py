from __future__ import annotations

import unittest
from types import SimpleNamespace

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.engine_runtime_state_lookup import (  # noqa: E402
    state_matches_scope,
    try_load_existing_state,
)
from envctl_engine.state.models import RunState  # noqa: E402


class EngineRuntimeStateLookupTests(unittest.TestCase):
    def test_try_load_existing_state_emits_fingerprint_after_reload(self) -> None:
        state = RunState(run_id="run-1", mode="main")
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(
            state_repository=SimpleNamespace(load_latest=lambda **kwargs: state),
            _emit=lambda event, **payload: events.append((event, payload)),
            _state_fingerprint=lambda loaded: f"fp:{loaded.run_id}",
        )

        loaded = try_load_existing_state(runtime, mode="main", strict_mode_match=True)

        self.assertIs(loaded, state)
        self.assertEqual(
            events,
            [("state.fingerprint.after_reload", {"run_id": "run-1", "state_fingerprint": "fp:run-1"})],
        )

    def test_state_matches_scope_accepts_missing_scope_and_matches_exact_scope(self) -> None:
        runtime = SimpleNamespace(config=SimpleNamespace(runtime_scope_id="repo-123"))
        missing_scope = RunState(run_id="run-1", mode="main")
        matching_scope = RunState(run_id="run-1", mode="main", metadata={"repo_scope_id": "repo-123"})
        wrong_scope = RunState(run_id="run-1", mode="main", metadata={"repo_scope_id": "repo-999"})

        self.assertTrue(state_matches_scope(runtime, missing_scope))
        self.assertTrue(state_matches_scope(runtime, matching_scope))
        self.assertFalse(state_matches_scope(runtime, wrong_scope))


if __name__ == "__main__":
    unittest.main()
