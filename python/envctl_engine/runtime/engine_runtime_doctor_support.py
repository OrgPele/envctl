from __future__ import annotations

from typing import Any

from envctl_engine.runtime.release_gate import evaluate_shipability


def doctor(runtime: Any) -> int:
    return runtime.doctor_orchestrator.execute()


def doctor_readiness_gates(runtime: Any) -> dict[str, bool]:
    return runtime.doctor_orchestrator.readiness_gates()


def evaluate_runtime_shipability(
    runtime: Any,
    *,
    enforce_runtime_readiness_contract: bool = True,
) -> object:
    return evaluate_shipability(
        repo_root=runtime.config.base_dir,
        check_tests=doctor_should_check_tests(runtime),
        enforce_runtime_readiness_contract=enforce_runtime_readiness_contract,
    )


def doctor_should_check_tests(runtime: Any) -> bool:
    return runtime.doctor_orchestrator.doctor_should_check_tests()


def enforce_runtime_readiness_contract(
    runtime: Any,
    *,
    scope: str,
    strict_required: bool | None = None,
) -> bool:
    return runtime.doctor_orchestrator.enforce_runtime_readiness_contract(
        scope=scope,
        strict_required=strict_required,
    )
