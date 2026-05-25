from __future__ import annotations

# This module is a data owner for long generated-contract prose. Keep the text
# stable for contract generation; line wrapping would make the table harder to
# audit than the intentional long strings.
# ruff: noqa: E501

from envctl_engine.runtime_feature_definition_schema import FeatureDefinition


PLANNING_COMMAND_DEFINITIONS: dict[str, FeatureDefinition] = {
    "plan": FeatureDefinition(
        area="planning",
        feature="Command: create or sync planning-driven worktrees and start or attach to the selected environment",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/planning/worktree_domain.py",
            "python/envctl_engine/startup/startup_orchestrator.py",
        ),
        evidence_tests=(
            "tests/python/planning/test_planning_worktree_setup.py",
            "tests/python/runtime/test_engine_runtime_real_startup.py",
        ),
        parity_status="verified_python",
        notes="Plan creation, sync, scale-down, and disabled-run dashboard flows are implemented in Python.",
    ),
    "delete-worktree": FeatureDefinition(
        area="planning",
        feature="Command: delete selected worktree directories after scoped cleanup",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/actions/action_worktree_runner.py",
            "python/envctl_engine/planning/worktree_domain.py",
        ),
        evidence_tests=(
            "tests/python/actions/test_action_worktree_runner.py",
            "tests/python/planning/test_planning_worktree_setup.py",
        ),
        parity_status="verified_python",
        notes="Delete-worktree flows are Python-owned and exercised by action/planning tests.",
    ),
    "blast-worktree": FeatureDefinition(
        area="planning",
        feature="Command: aggressively clean tree-scoped processes and dependency resources before deleting worktrees",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/runtime/lifecycle_worktree_cleanup.py",
            "python/envctl_engine/runtime/lifecycle_worktree_metadata.py",
            "python/envctl_engine/runtime/lifecycle_worktree_processes.py",
            "python/envctl_engine/runtime/lifecycle_worktree_containers.py",
            "python/envctl_engine/runtime/engine_runtime_lifecycle_support.py",
            "python/envctl_engine/actions/action_worktree_runner.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_lifecycle_worktree_cleanup.py",
            "tests/python/runtime/test_engine_runtime_lifecycle_support.py",
            "tests/python/actions/test_action_worktree_runner.py",
        ),
        parity_status="verified_python",
        notes="Blast-worktree cleanup, including legacy resource cleanup, is covered by lifecycle support and worktree action tests.",
        current_behavior="Python blast-worktree deletes trees and cleans most scoped resources, but full cleanup symmetry still relies on shell behavior as the oracle.",
        missing_python_behavior="Close any remaining tree-scoped cleanup gaps for processes, dependency containers, and legacy-named resources, then prove parity through focused lifecycle tests.",
        python_owner_module="python/envctl_engine/runtime/lifecycle_worktree_cleanup.py",
        proposed_tests=(
            "tests/python/runtime/test_lifecycle_worktree_cleanup.py",
            "tests/python/runtime/test_engine_runtime_lifecycle_support.py",
            "tests/python/actions/test_action_worktree_runner.py",
        ),
        severity="high",
        rollout_risk="Partial tree cleanup can leave stale containers or listeners that later break planning or startup.",
        wave="Wave B",
    ),
    "self-destruct-worktree": FeatureDefinition(
        area="planning",
        feature="Command: destroy the current worktree after scoped cleanup using the active run context",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/actions/action_command_orchestrator.py",
            "python/envctl_engine/actions/action_worktree_runner.py",
        ),
        evidence_tests=(
            "tests/python/actions/test_action_worktree_runner.py",
            "tests/python/runtime/test_command_router_contract.py",
            "tests/python/runtime/test_command_dispatch_matrix.py",
        ),
        parity_status="verified_python",
        notes="Self-destruct-worktree is Python-owned and routes through the action orchestrator using existing scoped cleanup behavior.",
    ),
}
