from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from envctl_engine.runtime.engine_runtime_doctor_support import (
    doctor,
    doctor_readiness_gates,
    doctor_should_check_tests,
    enforce_runtime_readiness_contract,
    evaluate_runtime_shipability,
)


class EngineRuntimeDoctorSupportTests(unittest.TestCase):
    def test_doctor_delegates_to_doctor_orchestrator(self) -> None:
        runtime = SimpleNamespace(doctor_orchestrator=SimpleNamespace(execute=lambda: 7))

        self.assertEqual(doctor(runtime), 7)

    def test_readiness_and_runtime_readiness_contract_delegate_to_doctor_orchestrator(self) -> None:
        seen: dict[str, object] = {}
        expected = {"command_parity": True}
        runtime = SimpleNamespace(
            doctor_orchestrator=SimpleNamespace(
                readiness_gates=lambda: expected,
                enforce_runtime_readiness_contract=lambda *, scope, strict_required=None: seen.update(
                    {"scope": scope, "strict_required": strict_required}
                )
                or False,
            )
        )

        self.assertEqual(doctor_readiness_gates(runtime), expected)
        self.assertFalse(enforce_runtime_readiness_contract(runtime, scope="resume", strict_required=True))
        self.assertEqual(seen, {"scope": "resume", "strict_required": True})

    def test_evaluate_runtime_shipability_uses_runtime_repo_and_doctor_test_policy(self) -> None:
        runtime = SimpleNamespace(
            config=SimpleNamespace(base_dir=Path("/repo")),
            doctor_orchestrator=SimpleNamespace(doctor_should_check_tests=lambda: True),
        )
        expected = SimpleNamespace(passed=True)

        with patch(
            "envctl_engine.runtime.engine_runtime_doctor_support.evaluate_shipability",
            return_value=expected,
        ) as gate:
            result = evaluate_runtime_shipability(runtime, enforce_runtime_readiness_contract=False)

        self.assertIs(result, expected)
        gate.assert_called_once_with(
            repo_root=Path("/repo"),
            check_tests=True,
            enforce_runtime_readiness_contract=False,
        )

    def test_doctor_should_check_tests_delegates_to_doctor_orchestrator(self) -> None:
        runtime = SimpleNamespace(doctor_orchestrator=SimpleNamespace(doctor_should_check_tests=lambda: True))

        self.assertTrue(doctor_should_check_tests(runtime))


if __name__ == "__main__":
    unittest.main()
