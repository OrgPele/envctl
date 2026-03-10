from __future__ import annotations

import time
import unittest
from types import SimpleNamespace

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.engine_runtime_service_policy import (  # noqa: E402
    service_listener_timeout,
    service_rebound_max_delta,
    service_startup_grace_seconds,
    service_truth_timeout,
    service_within_startup_grace,
)


class EngineRuntimeServicePolicyTests(unittest.TestCase):
    def test_service_rebound_max_delta_defaults_and_parses(self) -> None:
        default_runtime = SimpleNamespace(env={}, config=SimpleNamespace(raw={}))
        custom_runtime = SimpleNamespace(env={"ENVCTL_SERVICE_REBOUND_MAX_DELTA": "75"}, config=SimpleNamespace(raw={}))

        self.assertEqual(service_rebound_max_delta(default_runtime), 200)
        self.assertEqual(service_rebound_max_delta(custom_runtime), 75)

    def test_service_listener_timeout_depends_on_listener_truth(self) -> None:
        strict_runtime = SimpleNamespace(
            env={},
            config=SimpleNamespace(raw={}),
            _listener_truth_enforced=lambda: True,
        )
        best_effort_runtime = SimpleNamespace(
            env={},
            config=SimpleNamespace(raw={}),
            _listener_truth_enforced=lambda: False,
        )

        self.assertEqual(service_listener_timeout(strict_runtime), 10.0)
        self.assertEqual(service_listener_timeout(best_effort_runtime), 3.0)

    def test_service_truth_timeout_and_startup_grace_parse_overrides(self) -> None:
        runtime = SimpleNamespace(
            env={
                "ENVCTL_SERVICE_TRUTH_TIMEOUT": "1.25",
                "ENVCTL_SERVICE_STARTUP_GRACE_SECONDS": "22",
            },
            config=SimpleNamespace(raw={}),
            _listener_truth_enforced=lambda: True,
        )

        self.assertEqual(service_truth_timeout(runtime), 1.25)
        self.assertEqual(service_startup_grace_seconds(runtime), 22.0)

    def test_service_within_startup_grace_uses_started_at(self) -> None:
        runtime = SimpleNamespace(
            env={"ENVCTL_SERVICE_STARTUP_GRACE_SECONDS": "20"},
            config=SimpleNamespace(raw={}),
            _listener_truth_enforced=lambda: True,
        )
        fresh = SimpleNamespace(started_at=time.time() - 5)
        stale = SimpleNamespace(started_at=time.time() - 30)

        self.assertTrue(service_within_startup_grace(runtime, fresh))
        self.assertFalse(service_within_startup_grace(runtime, stale))


if __name__ == "__main__":
    unittest.main()
