from __future__ import annotations

# This module is a data owner for long generated-contract prose. Keep the text
# stable for contract generation; line wrapping would make the table harder to
# audit than the intentional long strings.
# ruff: noqa: E501

from envctl_engine.runtime_feature_definition_schema import FeatureDefinition


DIAGNOSTIC_COMMAND_DEFINITIONS: dict[str, FeatureDefinition] = {
    "doctor": FeatureDefinition(
        area="diagnostics",
        feature="Command: print readiness and runtime diagnostics",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/debug/doctor_orchestrator.py",
            "python/envctl_engine/runtime/engine_runtime.py",
        ),
        evidence_tests=("tests/python/runtime/test_engine_runtime_command_parity_doctor.py",),
        parity_status="verified_python",
        notes="Doctor is Python-owned and explicitly covered by runtime command parity tests.",
        current_behavior="Python doctor reports runtime readiness, parity, state health, and recent failure diagnostics without shell migration fields.",
        missing_python_behavior="Keep the doctor output contract focused on runtime readiness and state diagnostics, then cover those fields explicitly in Python tests.",
        python_owner_module="python/envctl_engine/debug/doctor_orchestrator.py",
        proposed_tests=("tests/python/runtime/test_engine_runtime_command_parity_doctor.py",),
        severity="low",
        rollout_risk="Doctor output drift is mostly a diagnostics/readiness concern, but it can confuse operators during cutover.",
        wave="Wave E",
    ),
    "debug-pack": FeatureDefinition(
        area="diagnostics",
        feature="Command: create a debug bundle pack from the Python runtime",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/debug/debug_bundle.py",
            "python/envctl_engine/runtime/engine_runtime_debug_support.py",
        ),
        evidence_tests=("tests/python/runtime/test_engine_runtime_debug_support.py",),
        parity_status="verified_python",
        notes="Debug-pack is intentionally Python-only and covered as part of the supported runtime diagnostics path.",
    ),
    "debug-report": FeatureDefinition(
        area="diagnostics",
        feature="Command: render the last generated debug report",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/debug/debug_bundle_support.py",
            "python/envctl_engine/runtime/engine_runtime_debug_support.py",
        ),
        evidence_tests=("tests/python/runtime/test_engine_runtime_debug_support.py",),
        parity_status="verified_python",
        notes="Debug-report is part of the Python-only diagnostics path.",
    ),
    "debug-last": FeatureDefinition(
        area="diagnostics",
        feature="Command: inspect the latest generated debug bundle",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/debug/debug_bundle_support.py",
            "python/envctl_engine/runtime/engine_runtime_debug_support.py",
        ),
        evidence_tests=("tests/python/runtime/test_engine_runtime_debug_support.py",),
        parity_status="verified_python",
        notes="Debug-last is Python-owned and covered by diagnostics tests.",
    ),
}
