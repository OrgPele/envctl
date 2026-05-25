from __future__ import annotations

# This module is a data owner for long generated-contract prose. Keep the text
# stable for contract generation; line wrapping would make the table harder to
# audit than the intentional long strings.
# ruff: noqa: E501

from envctl_engine.runtime_feature_definition_schema import FeatureDefinition


INSPECTION_COMMAND_DEFINITIONS: dict[str, FeatureDefinition] = {
    "logs": FeatureDefinition(
        area="inspection",
        feature="Command: tail or follow logs for selected services",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/runtime/inspection_support.py",
            "python/envctl_engine/state/action_orchestrator.py",
            "python/envctl_engine/state/action_command_support.py",
            "python/envctl_engine/state/action_log_support.py",
        ),
        evidence_tests=("tests/python/runtime/test_logs_parity.py",),
        parity_status="verified_python",
        notes="Logs/follow behavior is covered by runtime parity tests.",
    ),
    "clear-logs": FeatureDefinition(
        area="inspection",
        feature="Command: clear accumulated runtime logs for selected services",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/state/action_orchestrator.py",
            "python/envctl_engine/state/action_command_support.py",
            "python/envctl_engine/state/action_log_support.py",
            "python/envctl_engine/runtime/inspection_support.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_logs_parity.py",
            "tests/python/runtime/test_command_dispatch_matrix.py",
        ),
        parity_status="verified_python",
        notes="Clear-logs is covered through state-action/log parity tests.",
    ),
    "health": FeatureDefinition(
        area="inspection",
        feature="Command: print current health for services and requirements",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/runtime/inspection_support.py",
            "python/envctl_engine/runtime/service_status_truth.py",
            "python/envctl_engine/runtime/service_post_start_truth.py",
            "python/envctl_engine/runtime/engine_runtime_service_truth.py",
            "python/envctl_engine/state/action_command_support.py",
            "python/envctl_engine/state/action_health_support.py",
        ),
        evidence_tests=("tests/python/runtime/test_runtime_health_truth.py",),
        parity_status="verified_python",
        notes="Health reporting is Python-owned and exercised by runtime truth tests.",
    ),
    "errors": FeatureDefinition(
        area="inspection",
        feature="Command: print current error diagnostics for the latest run",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/runtime/inspection_support.py",
            "python/envctl_engine/runtime/service_truth_diagnostics.py",
            "python/envctl_engine/runtime/service_status_truth.py",
            "python/envctl_engine/runtime/service_post_start_truth.py",
            "python/envctl_engine/runtime/engine_runtime_service_truth.py",
            "python/envctl_engine/state/action_command_support.py",
            "python/envctl_engine/state/action_log_support.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_runtime_health_truth.py",
            "tests/python/runtime/test_engine_runtime_dashboard_truth.py",
        ),
        parity_status="verified_python",
        notes="Error reporting is covered by runtime truth and dashboard tests.",
    ),
    "show-config": FeatureDefinition(
        area="inspection",
        feature="Command: print the effective local configuration",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/runtime/inspection_support.py",
            "python/envctl_engine/config/persistence.py",
        ),
        evidence_tests=(
            "tests/python/config/test_config_persistence.py",
            "tests/python/runtime/test_command_dispatch_matrix.py",
        ),
        parity_status="verified_python",
        notes="Config inspection is Python-owned and validated by config/runtime tests.",
    ),
    "show-state": FeatureDefinition(
        area="inspection",
        feature="Command: print the latest saved runtime state",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/runtime/inspection_support.py",
            "python/envctl_engine/state/repository.py",
        ),
        evidence_tests=(
            "tests/python/state/test_state_repository_contract.py",
            "tests/python/runtime/test_command_dispatch_matrix.py",
        ),
        parity_status="verified_python",
        notes="Show-state is backed by the scoped state repository and covered by state/runtime tests.",
    ),
    "explain-startup": FeatureDefinition(
        area="inspection",
        feature="Command: explain startup selection and gating without starting services",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/runtime/inspection_support.py",
            "python/envctl_engine/runtime/startup_inspection_support.py",
            "python/envctl_engine/runtime/engine_runtime_env.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_startup_inspection_support.py",
            "tests/python/runtime/test_engine_runtime_command_parity_explain.py",
            "tests/python/runtime/test_engine_runtime_env.py",
        ),
        parity_status="verified_python",
        notes="Explain-startup dispatch stays in inspection_support; startup selection/preflight payload ownership lives in startup_inspection_support.",
    ),
    "preflight": FeatureDefinition(
        area="inspection",
        feature="Command: emit a versioned startup-preflight contract without starting services",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/runtime/inspection_support.py",
            "python/envctl_engine/runtime/startup_inspection_support.py",
            "python/envctl_engine/runtime/command_router.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_startup_inspection_support.py",
            "tests/python/runtime/test_engine_runtime_command_parity_explain.py",
        ),
        parity_status="verified_python",
        notes="Preflight dispatch stays in inspection_support; versioned contract wrapping lives in startup_inspection_support.",
    ),
    "dashboard": FeatureDefinition(
        area="inspection",
        feature="Command: render the interactive dashboard and command loop",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/ui/dashboard/orchestrator.py",
            "python/envctl_engine/ui/command_loop.py",
        ),
        evidence_tests=(
            "tests/python/ui/test_terminal_ui_dashboard_loop.py",
            "tests/python/ui/test_dashboard_rendering_parity.py",
        ),
        parity_status="verified_python",
        notes="Python dashboard rendering and command-loop behavior are covered by dashboard rendering and terminal UI tests.",
        current_behavior="Python dashboard is the default and heavily tested, but shell-era UX expectations still influence some interaction and presentation decisions.",
        missing_python_behavior="Codify the remaining operator-facing dashboard behaviors that still rely on historical shell expectations and prove them in focused UI/runtime tests.",
        python_owner_module="python/envctl_engine/ui/dashboard/orchestrator.py",
        proposed_tests=(
            "tests/python/ui/test_terminal_ui_dashboard_loop.py",
            "tests/python/ui/test_dashboard_rendering_parity.py",
        ),
        severity="medium",
        rollout_risk="Small dashboard regressions are highly visible to operators even when core runtime behavior is correct.",
        wave="Wave E",
    ),
    "endpoints": FeatureDefinition(
        area="inspection",
        feature="Command: print project-scoped runtime endpoints and dependency ports",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/runtime/command_router.py",
            "python/envctl_engine/runtime/endpoints_command_support.py",
            "python/envctl_engine/state/project_runtime.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_endpoints_command_support.py",
            "tests/python/state/test_project_runtime_resolution.py",
            "tests/python/runtime/test_engine_runtime_command_parity.py",
            "tests/python/runtime/test_command_exit_codes.py",
        ),
        parity_status="verified_python",
        notes="Endpoints is Python-owned and uses fail-closed project runtime resolution with sanitized success/failure events before exposing URLs and dependency ports.",
    ),
    "session": FeatureDefinition(
        area="inspection",
        feature="Command: inspect, attach to, or terminate saved runtime sessions",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/runtime/inspection_support.py",
            "python/envctl_engine/runtime/session_management.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_engine_runtime_command_parity.py",
            "tests/python/runtime/test_command_dispatch_matrix.py",
        ),
        parity_status="verified_python",
        notes="Session inspection and session-management helpers are Python-owned direct inspection flows.",
    ),
}
