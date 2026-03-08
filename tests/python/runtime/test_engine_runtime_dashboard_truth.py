from __future__ import annotations

import unittest
from types import SimpleNamespace

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.runtime.engine_runtime_dashboard_truth import (  # noqa: E402
    dashboard_reconcile_for_snapshot,
    dashboard_truth_refresh_seconds,
)
from envctl_engine.state.models import RunState  # noqa: E402


class EngineRuntimeDashboardTruthTests(unittest.TestCase):
    def test_dashboard_truth_refresh_seconds_defaults_and_parses(self) -> None:
        default_runtime = SimpleNamespace(env={}, config=SimpleNamespace(raw={}))
        custom_runtime = SimpleNamespace(
            env={"ENVCTL_DASHBOARD_TRUTH_REFRESH_SECONDS": "2.5"},
            config=SimpleNamespace(raw={}),
        )

        self.assertEqual(dashboard_truth_refresh_seconds(default_runtime), 1.0)
        self.assertEqual(dashboard_truth_refresh_seconds(custom_runtime), 2.5)

    def test_dashboard_reconcile_for_snapshot_uses_cache_until_expiry(self) -> None:
        state = RunState(run_id="run-1", mode="main", services={})
        reconcile_calls: list[str] = []

        def reconcile(_state):  # noqa: ANN001
            reconcile_calls.append("called")
            return ["Main Backend"]

        runtime = SimpleNamespace(
            env={"ENVCTL_DASHBOARD_TRUTH_REFRESH_SECONDS": "10"},
            config=SimpleNamespace(raw={}),
            _reconcile_state_truth=reconcile,
            _dashboard_truth_cache_run_id=None,
            _dashboard_truth_cache_expires_at=0.0,
            _dashboard_truth_cache_missing_services=[],
        )

        first = dashboard_reconcile_for_snapshot(runtime, state)
        second = dashboard_reconcile_for_snapshot(runtime, state)

        self.assertEqual(first, ["Main Backend"])
        self.assertEqual(second, ["Main Backend"])
        self.assertEqual(reconcile_calls, ["called"])

    def test_dashboard_reconcile_for_snapshot_disables_cache_when_zero(self) -> None:
        state = RunState(run_id="run-1", mode="main", services={})
        reconcile_calls: list[str] = []

        def reconcile(_state):  # noqa: ANN001
            reconcile_calls.append("called")
            return ["Main Backend"]

        runtime = SimpleNamespace(
            env={"ENVCTL_DASHBOARD_TRUTH_REFRESH_SECONDS": "0"},
            config=SimpleNamespace(raw={}),
            _reconcile_state_truth=reconcile,
            _dashboard_truth_cache_run_id="run-1",
            _dashboard_truth_cache_expires_at=999999999.0,
            _dashboard_truth_cache_missing_services=["stale"],
        )

        first = dashboard_reconcile_for_snapshot(runtime, state)
        second = dashboard_reconcile_for_snapshot(runtime, state)

        self.assertEqual(first, ["Main Backend"])
        self.assertEqual(second, ["Main Backend"])
        self.assertEqual(reconcile_calls, ["called", "called"])
        self.assertIsNone(runtime._dashboard_truth_cache_run_id)
        self.assertEqual(runtime._dashboard_truth_cache_missing_services, [])


if __name__ == "__main__":
    unittest.main()
