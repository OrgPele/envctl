from __future__ import annotations

# This module is a data owner for long generated-contract prose. Keep the text
# stable for contract generation; line wrapping would make the table harder to
# audit than the intentional long strings.
# ruff: noqa: E501

from envctl_engine.runtime_feature_definition_schema import FeatureDefinition


LIFECYCLE_COMMAND_DEFINITIONS: dict[str, FeatureDefinition] = {
    "start": FeatureDefinition(
        area="lifecycle",
        feature="Command: start main or tree services for the selected mode",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/runtime/engine_runtime.py",
            "python/envctl_engine/startup/startup_orchestrator.py",
            "python/envctl_engine/startup/service_env_support.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_engine_runtime_real_startup.py",
            "tests/python/runtime/test_lifecycle_parity.py",
        ),
        parity_status="verified_python",
        notes="Core startup flows are owned by Python and covered by runtime/lifecycle parity tests.",
    ),
    "resume": FeatureDefinition(
        area="lifecycle",
        feature="Command: resume the last saved run state for the selected mode",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/runtime/engine_runtime.py",
            "python/envctl_engine/startup/resume_orchestrator.py",
        ),
        evidence_tests=(
            "tests/python/state/test_state_roundtrip.py",
            "tests/python/runtime/test_lifecycle_parity.py",
        ),
        parity_status="verified_python",
        notes="Python resume is the current default path and is exercised by state/lifecycle tests.",
    ),
    "restart": FeatureDefinition(
        area="lifecycle",
        feature="Command: restart selected services or projects without losing the current run context",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/startup/startup_orchestrator.py",
            "python/envctl_engine/ui/dashboard/orchestrator.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_lifecycle_parity.py",
            "tests/python/startup/test_startup_spinner_integration.py",
        ),
        parity_status="verified_python",
        notes="Restart orchestration and selector behavior are covered in runtime and UI suites.",
    ),
    "stop": FeatureDefinition(
        area="lifecycle",
        feature="Command: stop selected services or projects",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/runtime/engine_runtime.py",
            "python/envctl_engine/runtime/lifecycle_cleanup_orchestrator.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_lifecycle_parity.py",
            "tests/python/runtime/test_lifecycle_cleanup_spinner_integration.py",
        ),
        parity_status="verified_python",
        notes="Targeted stop flows are covered by lifecycle parity and cleanup integration tests.",
    ),
    "stop-all": FeatureDefinition(
        area="lifecycle",
        feature="Command: stop all managed services for the current runtime scope",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/runtime/engine_runtime.py",
            "python/envctl_engine/runtime/lifecycle_cleanup_orchestrator.py",
        ),
        evidence_tests=("tests/python/runtime/test_lifecycle_parity.py",),
        parity_status="verified_python",
        notes="Python stop-all is covered by runtime parity and end-to-end tests.",
    ),
    "blast-all": FeatureDefinition(
        area="lifecycle",
        feature="Command: aggressively clean all managed runtime processes, ports, and dependency containers",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/runtime/engine_runtime.py",
            "python/envctl_engine/runtime/engine_runtime_lifecycle_support.py",
            "python/envctl_engine/runtime/lifecycle_blast_support.py",
            "python/envctl_engine/runtime/lifecycle_blast_ports.py",
            "python/envctl_engine/runtime/lifecycle_blast_processes.py",
            "python/envctl_engine/runtime/lifecycle_blast_docker.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_lifecycle_blast_support.py",
            "tests/python/runtime/test_engine_runtime_lifecycle_support.py",
        ),
        parity_status="verified_python",
        notes="Blast-all cleanup breadth is covered by lifecycle support tests.",
        current_behavior="Python blast-all works and is tested, but the shell path still carries legacy cleanup breadth for global runtime teardown.",
        missing_python_behavior="Prove and, where needed, close cleanup symmetry for ports, processes, Docker resources, and stale dependency artifacts across mixed failure states.",
        python_owner_module="python/envctl_engine/runtime/lifecycle_blast_support.py",
        proposed_tests=(
            "tests/python/runtime/test_lifecycle_blast_support.py",
            "tests/python/runtime/test_engine_runtime_lifecycle_support.py",
        ),
        severity="high",
        rollout_risk="Global cleanup regressions could leave orphaned processes, ports, or containers across repos.",
        wave="Wave B",
    ),
}
