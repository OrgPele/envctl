from __future__ import annotations

from envctl_engine.runtime.engine_runtime_doctor_support import (
    doctor as runtime_doctor,
    doctor_readiness_gates as runtime_doctor_readiness_gates,
    doctor_should_check_tests as runtime_doctor_should_check_tests,
    enforce_runtime_readiness_contract as runtime_enforce_runtime_readiness_contract,
    evaluate_runtime_shipability as runtime_evaluate_runtime_shipability,
)


class RuntimeDoctorFacadeMixin:
    def _doctor(self) -> int:
        return runtime_doctor(self)

    def _doctor_readiness_gates(self) -> dict[str, bool]:
        return runtime_doctor_readiness_gates(self)

    def _evaluate_shipability(
        self,
        *,
        enforce_runtime_readiness_contract: bool = True,
    ) -> object:
        return runtime_evaluate_runtime_shipability(
            self,
            enforce_runtime_readiness_contract=enforce_runtime_readiness_contract,
        )

    def _doctor_should_check_tests(self) -> bool:
        return runtime_doctor_should_check_tests(self)

    def _enforce_runtime_readiness_contract(self, *, scope: str, strict_required: bool | None = None) -> bool:
        return runtime_enforce_runtime_readiness_contract(self, scope=scope, strict_required=strict_required)
