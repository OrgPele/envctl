from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.requirements.orchestrator import FailureClass, RequirementsOrchestrator


class RequirementsOrchestratorTests(unittest.TestCase):
    def test_uniform_retry_classification_for_bind_conflict(self) -> None:
        orchestrator = RequirementsOrchestrator()

        def _starter_factory() -> tuple[list[int], object]:
            attempts: list[int] = []

            def start(port: int) -> tuple[bool, str | None]:
                attempts.append(port)
                if len(attempts) == 1:
                    return False, "bind: address already in use"
                return True, None

            return attempts, start

        for service_name in ("postgres", "redis", "supabase", "n8n"):
            calls, start = _starter_factory()
            outcome = orchestrator.start_requirement(
                service_name=service_name,
                port=5432,
                start=start,
                reserve_next=lambda next_port: next_port,
                max_retries=3,
            )
            self.assertTrue(outcome.success, msg=service_name)
            self.assertEqual(outcome.final_port, 5433, msg=service_name)
            self.assertEqual(calls, [5432, 5433], msg=service_name)

    def test_n8n_owner_bootstrap_404_is_soft_failure_by_default(self) -> None:
        orchestrator = RequirementsOrchestrator()
        cls = orchestrator.classify_failure("n8n", "HTTP 404 from /setup endpoint", strict=False)
        self.assertEqual(cls, FailureClass.BOOTSTRAP_SOFT_FAILURE)

    def test_n8n_owner_bootstrap_404_is_hard_failure_in_strict_mode(self) -> None:
        orchestrator = RequirementsOrchestrator()
        cls = orchestrator.classify_failure("n8n", "HTTP 404 from /setup endpoint", strict=True)
        self.assertEqual(cls, FailureClass.HARD_START_FAILURE)

    def test_postgres_no_response_is_transient_probe_failure(self) -> None:
        orchestrator = RequirementsOrchestrator()
        cls = orchestrator.classify_failure(
            "postgres",
            "/var/run/postgresql:5432 - no response",
            strict=False,
        )
        self.assertEqual(cls, FailureClass.TRANSIENT_PROBE_TIMEOUT_RETRYABLE)

    def test_transient_probe_retry_keeps_same_port(self) -> None:
        orchestrator = RequirementsOrchestrator()
        calls: list[int] = []

        def start(port: int) -> tuple[bool, str | None]:
            calls.append(port)
            if len(calls) == 1:
                return False, "probe timeout waiting for readiness"
            return True, None

        def reserve_next(_port: int) -> int:
            self.fail("reserve_next should not be called for transient probe retries")
            return 0

        outcome = orchestrator.start_requirement(
            service_name="postgres",
            port=5432,
            start=start,
            reserve_next=reserve_next,
            max_retries=3,
        )
        self.assertTrue(outcome.success)
        self.assertEqual(calls, [5432, 5432])
        self.assertEqual(outcome.final_port, 5432)
        self.assertEqual(outcome.retries, 1)

    def test_bind_conflict_exhausts_retries_and_returns_failure(self) -> None:
        orchestrator = RequirementsOrchestrator()
        calls: list[int] = []

        def start(port: int) -> tuple[bool, str | None]:
            calls.append(port)
            return False, "bind: address already in use"

        outcome = orchestrator.start_requirement(
            service_name="postgres",
            port=5432,
            start=start,
            reserve_next=lambda next_port: next_port,
            max_retries=1,
        )
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.failure_class, FailureClass.BIND_CONFLICT_RETRYABLE)
        self.assertEqual(outcome.retries, 1)
        self.assertEqual(calls, [5432, 5433])

    def test_bind_conflict_honors_explicit_bind_retry_budget_override(self) -> None:
        orchestrator = RequirementsOrchestrator()
        calls: list[int] = []

        def start(port: int) -> tuple[bool, str | None]:
            calls.append(port)
            if len(calls) <= 4:
                return False, "bind: address already in use"
            return True, None

        outcome = orchestrator.start_requirement(
            service_name="postgres",
            port=5432,
            start=start,
            reserve_next=lambda next_port: next_port,
            max_retries=1,
            max_bind_retries=4,
        )
        self.assertTrue(outcome.success)
        self.assertEqual(outcome.retries, 4)
        self.assertEqual(calls, [5432, 5433, 5434, 5435, 5436])

    def test_bind_conflict_retry_invokes_callback_with_port_rebinding(self) -> None:
        orchestrator = RequirementsOrchestrator()
        retries: list[tuple[str, int, int, int, str | None]] = []

        calls: list[int] = []

        def start(port: int) -> tuple[bool, str | None]:
            calls.append(port)
            if len(calls) == 1:
                return False, "bind: address already in use"
            return True, None

        outcome = orchestrator.start_requirement(
            service_name="postgres",
            port=5432,
            start=start,
            reserve_next=lambda next_port: next_port,
            max_retries=3,
            on_retry=lambda service, failed_port, retry_port, attempt, failure_class, error: retries.append(
                (service, failed_port, retry_port, attempt, error)
            ),
        )

        self.assertTrue(outcome.success)
        self.assertEqual(calls, [5432, 5433])
        self.assertEqual(retries, [("postgres", 5432, 5433, 1, "bind: address already in use")])

    def test_transient_probe_retry_invokes_callback_without_port_rebinding(self) -> None:
        orchestrator = RequirementsOrchestrator()
        retries: list[tuple[str, int, int, int, str | None]] = []
        calls: list[int] = []

        def start(port: int) -> tuple[bool, str | None]:
            calls.append(port)
            if len(calls) == 1:
                return False, "probe timeout waiting for readiness"
            return True, None

        outcome = orchestrator.start_requirement(
            service_name="redis",
            port=6379,
            start=start,
            reserve_next=lambda next_port: next_port,
            max_retries=3,
            on_retry=lambda service, failed_port, retry_port, attempt, failure_class, error: retries.append(
                (service, failed_port, retry_port, attempt, error)
            ),
        )

        self.assertTrue(outcome.success)
        self.assertEqual(calls, [6379, 6379])
        self.assertEqual(retries, [("redis", 6379, 6379, 1, "probe timeout waiting for readiness")])

    def test_transient_probe_retry_exhausts_retry_ceiling(self) -> None:
        orchestrator = RequirementsOrchestrator()
        calls: list[int] = []

        def start(port: int) -> tuple[bool, str | None]:
            calls.append(port)
            return False, "timeout waiting for readiness"

        outcome = orchestrator.start_requirement(
            service_name="redis",
            port=6379,
            start=start,
            reserve_next=lambda next_port: next_port,
            max_retries=2,
        )
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.failure_class, FailureClass.TRANSIENT_PROBE_TIMEOUT_RETRYABLE)
        self.assertEqual(outcome.retries, 2)
        self.assertEqual(calls, [6379, 6379, 6379])

    def test_unknown_failure_defaults_to_hard_start_failure(self) -> None:
        orchestrator = RequirementsOrchestrator()
        cls = orchestrator.classify_failure("postgres", "unexpected error", strict=False)
        self.assertEqual(cls, FailureClass.HARD_START_FAILURE)


if __name__ == "__main__":
    unittest.main()
