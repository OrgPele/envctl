from __future__ import annotations

import unittest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.requirements.n8n import start_n8n_with_retry
from envctl_engine.requirements.postgres import start_postgres_with_retry
from envctl_engine.requirements.redis import start_redis_with_retry
from envctl_engine.requirements.orchestrator import FailureClass, RequirementsOrchestrator


class RequirementsRetryTests(unittest.TestCase):
    def _exercise_bind_retry(self, starter) -> None:
        calls: list[int] = []

        def start(port: int) -> tuple[bool, str | None]:
            calls.append(port)
            if len(calls) == 1:
                return False, "bind: address already in use"
            return True, None

        def reserve_next(port: int) -> int:
            return port

        result = starter(start=start, reserve_next=reserve_next, port=5432, max_retries=3)

        self.assertTrue(result.success)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(result.port, 5433)

    def test_postgres_retries_bind_conflicts(self) -> None:
        self._exercise_bind_retry(start_postgres_with_retry)

    def test_redis_retries_bind_conflicts(self) -> None:
        self._exercise_bind_retry(start_redis_with_retry)

    def test_n8n_retries_bind_conflicts(self) -> None:
        self._exercise_bind_retry(start_n8n_with_retry)

    def test_non_bind_failures_are_classified_without_retry(self) -> None:
        def start(port: int) -> tuple[bool, str | None]:
            _ = port
            return False, "permission denied"

        def reserve_next(port: int) -> int:
            self.fail(f"reserve_next should not be called, got {port}")

        result = start_postgres_with_retry(start=start, reserve_next=reserve_next, port=5432, max_retries=3)

        self.assertFalse(result.success)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.failure, "permission denied")

    def test_transient_probe_timeout_is_retryable_class(self) -> None:
        orchestrator = RequirementsOrchestrator()
        failure_class = orchestrator.classify_failure(
            "redis",
            "probe timeout waiting for readiness",
            strict=False,
        )
        self.assertEqual(failure_class, FailureClass.TRANSIENT_PROBE_TIMEOUT_RETRYABLE)

    def test_no_response_is_retryable_transient_class(self) -> None:
        orchestrator = RequirementsOrchestrator()
        failure_class = orchestrator.classify_failure(
            "postgres",
            "/var/run/postgresql:5432 - no response",
            strict=False,
        )
        self.assertEqual(failure_class, FailureClass.TRANSIENT_PROBE_TIMEOUT_RETRYABLE)


if __name__ == "__main__":
    unittest.main()
