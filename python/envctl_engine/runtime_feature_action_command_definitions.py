from __future__ import annotations

# This module is a data owner for long generated-contract prose. Keep the text
# stable for contract generation; line wrapping would make the table harder to
# audit than the intentional long strings.
# ruff: noqa: E501

from envctl_engine.runtime_feature_definition_schema import FeatureDefinition


ACTION_COMMAND_DEFINITIONS: dict[str, FeatureDefinition] = {
    "test": FeatureDefinition(
        area="actions",
        feature="Command: run tests for selected projects and service scopes",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/actions/action_test_runner.py",
            "python/envctl_engine/actions/action_test_execution_support.py",
            "python/envctl_engine/actions/action_test_suite_execution_support.py",
            "python/envctl_engine/actions/action_command_orchestrator.py",
        ),
        evidence_tests=(
            "tests/python/actions/test_actions_parity.py",
            "tests/python/actions/test_action_spinner_integration.py",
        ),
        parity_status="verified_python",
        notes=(
            "Python test planning, suite execution, progress reporting, and failure summarization are covered by "
            "action and streaming fallback tests."
        ),
        current_behavior="Python test execution works across native and helper-backed paths, but the shell runtime still embodies older test-runner edge semantics.",
        missing_python_behavior="Stabilize target selection, helper integration, streaming/progress output, and failure summarization so shell is no longer needed as the fallback oracle.",
        python_owner_module="python/envctl_engine/actions/action_test_runner.py",
        proposed_tests=(
            "tests/python/actions/test_actions_parity.py",
            "tests/python/test_output/test_test_runner_streaming_fallback.py",
        ),
        severity="medium",
        rollout_risk="Users could see confusing test selection or incomplete error propagation in interactive flows.",
        wave="Wave D",
    ),
    "test-focused": FeatureDefinition(
        area="actions",
        feature="Command: run focused validation commands from changed files",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/actions/test_plan_action.py",
            "python/envctl_engine/actions/action_command_orchestrator.py",
        ),
        evidence_tests=(
            "tests/python/actions/test_test_plan_action.py",
            "tests/python/runtime/test_cli_router_parity.py",
        ),
        parity_status="verified_python",
        notes="Focused validation planning is Python-owned and maps changed files to deterministic test and ruff commands.",
    ),
    "pr": FeatureDefinition(
        area="actions",
        feature="Command: create pull requests for selected projects",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/actions/action_pr_message_support.py",
            "python/envctl_engine/actions/action_protected_artifacts.py",
            "python/envctl_engine/actions/action_ship_support.py",
            "python/envctl_engine/actions/project_action_domain.py",
            "python/envctl_engine/actions/actions_git.py",
        ),
        evidence_tests=(
            "tests/python/actions/test_actions_cli_pr.py",
            "tests/python/actions/test_actions_parity.py",
        ),
        parity_status="verified_python",
        notes="Python PR action flows are covered by CLI/action parity tests across native and helper-backed paths.",
        current_behavior="Python PR creation supports helper and gh-backed paths, but legacy helper assumptions still shape the contract.",
        missing_python_behavior="Finish defining the PR action contract so Python behavior is the source of truth for helper execution, output, and failure handling.",
        python_owner_module="python/envctl_engine/actions/project_action_domain.py",
        proposed_tests=("tests/python/actions/test_actions_cli_pr.py",),
        severity="medium",
        rollout_risk="PR workflows may still depend on helper-specific assumptions that are not fully captured in Python tests.",
        wave="Wave D",
    ),
    "commit": FeatureDefinition(
        area="actions",
        feature="Command: stage, commit, and push selected project changes",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/actions/action_pr_message_support.py",
            "python/envctl_engine/actions/action_protected_artifacts.py",
            "python/envctl_engine/actions/project_action_domain.py",
            "python/envctl_engine/actions/actions_git.py",
        ),
        evidence_tests=(
            "tests/python/actions/test_actions_cli_commit.py",
            "tests/python/actions/test_actions_parity.py",
        ),
        parity_status="verified_python",
        notes="Python commit flows are covered by action CLI/parity tests, including message sourcing and non-interactive cases.",
        current_behavior="Python commit flows work for normal interactive and headless cases, but commit-message sourcing and helper assumptions are still mixed with legacy expectations.",
        missing_python_behavior="Make Python the clear source of truth for commit message discovery, non-interactive failure cases, and pushed-branch reporting.",
        python_owner_module="python/envctl_engine/actions/project_action_domain.py",
        proposed_tests=("tests/python/actions/test_actions_cli_commit.py",),
        severity="medium",
        rollout_risk="Edge-case commit flows can still diverge from user expectations if legacy message-resolution behavior is not fully proven.",
        wave="Wave D",
    ),
    "ship": FeatureDefinition(
        area="actions",
        feature="Command: commit, push, create or reuse PRs, and report GitHub checks",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/actions/action_protected_artifacts.py",
            "python/envctl_engine/actions/action_ship_checks.py",
            "python/envctl_engine/actions/action_ship_conflicts.py",
            "python/envctl_engine/actions/action_ship_contract.py",
            "python/envctl_engine/actions/action_ship_support.py",
            "python/envctl_engine/actions/project_action_domain.py",
            "python/envctl_engine/actions/actions_git.py",
        ),
        evidence_tests=(
            "tests/python/actions/test_action_ship_owner_support.py",
            "tests/python/actions/test_action_ship_support.py",
            "tests/python/actions/test_actions_cli_ship.py",
            "tests/python/runtime/test_cli_router_parity.py",
        ),
        parity_status="verified_python",
        notes="Ship is a narrow Python handoff action that reuses commit/PR behavior and adds structured check status.",
    ),
    "review": FeatureDefinition(
        area="actions",
        feature="Command: generate a merge/readiness review bundle for selected projects",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/actions/action_review_output_support.py",
            "python/envctl_engine/actions/project_action_domain.py",
            "python/envctl_engine/state/repository.py",
        ),
        evidence_tests=(
            "tests/python/actions/test_actions_cli_review_completion.py",
            "tests/python/actions/test_actions_parity.py",
        ),
        parity_status="verified_python",
        notes="Python review now owns runtime-scoped artifacts, retained files, and output presentation, with CLI/parity coverage.",
        current_behavior="Python review produces runtime-scoped artifacts and improved output, but helper-backed review behavior is still anchored to the legacy analysis helper contract.",
        missing_python_behavior="Define and prove a stable Python-owned review contract for helper output, retained files, and output semantics so shell helper behavior is no longer the oracle.",
        python_owner_module="python/envctl_engine/actions/project_action_domain.py",
        proposed_tests=(
            "tests/python/actions/test_actions_cli_review_completion.py",
            "tests/python/actions/test_actions_parity.py",
        ),
        severity="medium",
        rollout_risk="Review output and retained artifacts can still drift if helper behavior changes independently of Python expectations.",
        wave="Wave D",
    ),
    "migrate": FeatureDefinition(
        area="actions",
        feature="Command: run project migration actions on selected targets",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/actions/project_action_domain.py",
            "python/envctl_engine/actions/actions_analysis.py",
        ),
        evidence_tests=("tests/python/actions/test_actions_parity.py",),
        parity_status="verified_python",
        notes="Python migrate dispatch and output semantics are covered by action parity tests.",
        current_behavior="Python migrate dispatch works, but behavior and output expectations are still inherited from legacy helper conventions.",
        missing_python_behavior="Lock down migrate target semantics, output reporting, and helper fallback behavior in Python tests and ownership docs.",
        python_owner_module="python/envctl_engine/actions/project_action_domain.py",
        proposed_tests=("tests/python/actions/test_actions_parity.py",),
        severity="medium",
        rollout_risk="Migration actions may remain brittle in mixed helper/native setups without a fully Python-owned contract.",
        wave="Wave D",
    ),
    "playwright": FeatureDefinition(
        area="actions",
        feature="Command: run browser validation against an active project frontend endpoint",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/runtime/command_router.py",
            "python/envctl_engine/runtime/playwright_command_support.py",
            "python/envctl_engine/runtime/endpoints_command_support.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_playwright_command_support.py",
            "tests/python/runtime/test_cli_router_parity.py",
            "tests/python/runtime/test_command_exit_codes.py",
        ),
        parity_status="verified_python",
        notes="Playwright passthrough is Python-owned and exports QA_BASE_URL plus ENVCTL_ENDPOINTS_JSON from endpoint truth without starting a second dev server.",
    ),
}
