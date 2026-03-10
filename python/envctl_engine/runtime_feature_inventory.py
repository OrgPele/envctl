from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from envctl_engine.runtime.command_router import list_supported_commands, list_supported_flag_tokens


@dataclass(frozen=True, slots=True)
class FeatureDefinition:
    area: str
    feature: str
    user_visible: bool
    shell_source_of_truth: tuple[str, ...]
    python_source_of_truth: tuple[str, ...]
    evidence_tests: tuple[str, ...]
    parity_status: str
    notes: str
    current_behavior: str = ""
    missing_python_behavior: str = ""
    python_owner_module: str = ""
    proposed_tests: tuple[str, ...] = ()
    severity: str = ""
    rollout_risk: str = ""
    wave: str = ""


_COMMAND_DEFINITIONS: dict[str, FeatureDefinition] = {
    "start": FeatureDefinition(
        area="lifecycle",
        feature="Command: start main or tree services for the selected mode",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/runtime/engine_runtime.py",
            "python/envctl_engine/startup/startup_orchestrator.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_engine_runtime_real_startup.py",
            "tests/python/runtime/test_lifecycle_parity.py",
        ),
        parity_status="verified_python",
        notes="Core startup flows are owned by Python and covered by runtime/lifecycle parity tests.",
    ),
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
        evidence_tests=(
            "tests/python/runtime/test_lifecycle_parity.py",
        ),
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
        ),
        evidence_tests=(
            "tests/python/runtime/test_engine_runtime_lifecycle_support.py",
        ),
        parity_status="verified_python",
        notes="Blast-all cleanup breadth is covered by lifecycle support tests and the blast-all contract BATS lane.",
        current_behavior="Python blast-all works and is tested, but the shell path still carries legacy cleanup breadth for global runtime teardown.",
        missing_python_behavior="Prove and, where needed, close cleanup symmetry for ports, processes, Docker resources, and stale dependency artifacts across mixed failure states.",
        python_owner_module="python/envctl_engine/runtime/engine_runtime_lifecycle_support.py",
        proposed_tests=(
            "tests/python/runtime/test_engine_runtime_lifecycle_support.py",
        ),
        severity="high",
        rollout_risk="Global cleanup regressions could leave orphaned processes, ports, or containers across repos.",
        wave="Wave B",
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
            "python/envctl_engine/runtime/engine_runtime_lifecycle_support.py",
            "python/envctl_engine/actions/action_worktree_runner.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_engine_runtime_lifecycle_support.py",
            "tests/python/actions/test_action_worktree_runner.py",
        ),
        parity_status="verified_python",
        notes="Blast-worktree cleanup, including legacy resource cleanup, is covered by lifecycle support and worktree action tests.",
        current_behavior="Python blast-worktree deletes trees and cleans most scoped resources, but full cleanup symmetry still relies on shell behavior as the oracle.",
        missing_python_behavior="Close any remaining tree-scoped cleanup gaps for processes, dependency containers, and legacy-named resources, then prove parity through focused lifecycle tests.",
        python_owner_module="python/envctl_engine/runtime/engine_runtime_lifecycle_support.py",
        proposed_tests=(
            "tests/python/runtime/test_engine_runtime_lifecycle_support.py",
            "tests/python/actions/test_action_worktree_runner.py",
        ),
        severity="high",
        rollout_risk="Partial tree cleanup can leave stale containers or listeners that later break planning or startup.",
        wave="Wave B",
    ),
    "test": FeatureDefinition(
        area="actions",
        feature="Command: run tests for selected projects and service scopes",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/actions/action_test_runner.py",
            "python/envctl_engine/actions/action_command_orchestrator.py",
        ),
        evidence_tests=(
            "tests/python/actions/test_actions_parity.py",
            "tests/python/actions/test_action_spinner_integration.py",
        ),
        parity_status="verified_python",
        notes="Python test execution, progress reporting, and failure summarization are covered by action and streaming fallback tests.",
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
    "pr": FeatureDefinition(
        area="actions",
        feature="Command: create pull requests for selected projects",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/actions/project_action_domain.py",
            "python/envctl_engine/actions/actions_git.py",
        ),
        evidence_tests=(
            "tests/python/actions/test_actions_cli.py",
            "tests/python/actions/test_actions_parity.py",
        ),
        parity_status="verified_python",
        notes="Python PR action flows are covered by CLI/action parity tests across native and helper-backed paths.",
        current_behavior="Python PR creation supports helper and gh-backed paths, but legacy helper assumptions still shape the contract.",
        missing_python_behavior="Finish defining the PR action contract so Python behavior is the source of truth for helper execution, output, and failure handling.",
        python_owner_module="python/envctl_engine/actions/project_action_domain.py",
        proposed_tests=(
            "tests/python/actions/test_actions_cli.py",
        ),
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
            "python/envctl_engine/actions/project_action_domain.py",
            "python/envctl_engine/actions/actions_git.py",
        ),
        evidence_tests=(
            "tests/python/actions/test_actions_cli.py",
            "tests/python/actions/test_actions_parity.py",
        ),
        parity_status="verified_python",
        notes="Python commit flows are covered by action CLI/parity tests, including message sourcing and non-interactive cases.",
        current_behavior="Python commit flows work for normal interactive and headless cases, but commit-message sourcing and helper assumptions are still mixed with legacy expectations.",
        missing_python_behavior="Make Python the clear source of truth for commit message discovery, non-interactive failure cases, and pushed-branch reporting.",
        python_owner_module="python/envctl_engine/actions/project_action_domain.py",
        proposed_tests=(
            "tests/python/actions/test_actions_cli.py",
        ),
        severity="medium",
        rollout_risk="Edge-case commit flows can still diverge from user expectations if legacy message-resolution behavior is not fully proven.",
        wave="Wave D",
    ),
    "review": FeatureDefinition(
        area="actions",
        feature="Command: generate a merge/readiness review bundle for selected projects",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/actions/project_action_domain.py",
            "python/envctl_engine/state/repository.py",
        ),
        evidence_tests=(
            "tests/python/actions/test_actions_cli.py",
            "tests/python/actions/test_actions_parity.py",
        ),
        parity_status="verified_python",
        notes="Python review now owns runtime-scoped artifacts, retained files, and output presentation, with CLI/parity coverage.",
        current_behavior="Python review produces runtime-scoped artifacts and improved output, but helper-backed review behavior is still anchored to the legacy analysis helper contract.",
        missing_python_behavior="Define and prove a stable Python-owned review contract for helper output, retained files, and output semantics so shell helper behavior is no longer the oracle.",
        python_owner_module="python/envctl_engine/actions/project_action_domain.py",
        proposed_tests=(
            "tests/python/actions/test_actions_cli.py",
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
        evidence_tests=(
            "tests/python/actions/test_actions_parity.py",
        ),
        parity_status="verified_python",
        notes="Python migrate dispatch and output semantics are covered by action parity tests.",
        current_behavior="Python migrate dispatch works, but behavior and output expectations are still inherited from legacy helper conventions.",
        missing_python_behavior="Lock down migrate target semantics, output reporting, and helper fallback behavior in Python tests and ownership docs.",
        python_owner_module="python/envctl_engine/actions/project_action_domain.py",
        proposed_tests=(
            "tests/python/actions/test_actions_parity.py",
        ),
        severity="medium",
        rollout_risk="Migration actions may remain brittle in mixed helper/native setups without a fully Python-owned contract.",
        wave="Wave D",
    ),
    "logs": FeatureDefinition(
        area="inspection",
        feature="Command: tail or follow logs for selected services",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/runtime/inspection_support.py",
            "python/envctl_engine/state/action_orchestrator.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_logs_parity.py",
        ),
        parity_status="verified_python",
        notes="Logs/follow behavior is covered by runtime parity tests and BATS.",
    ),
    "clear-logs": FeatureDefinition(
        area="inspection",
        feature="Command: clear accumulated runtime logs for selected services",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/state/action_orchestrator.py",
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
            "python/envctl_engine/runtime/engine_runtime_service_truth.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_runtime_health_truth.py",
        ),
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
            "python/envctl_engine/runtime/engine_runtime_service_truth.py",
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
            "python/envctl_engine/runtime/engine_runtime_env.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_engine_runtime_env.py",
        ),
        parity_status="verified_python",
        notes="Explain-startup is Python-owned and verified through env/runtime tests.",
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
    "config": FeatureDefinition(
        area="cli",
        feature="Command: open the configuration wizard or headless config editor",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/config/wizard_domain.py",
            "python/envctl_engine/config/command_support.py",
        ),
        evidence_tests=(
            "tests/python/config/test_config_wizard_domain.py",
            "tests/python/config/test_config_command_support.py",
        ),
        parity_status="verified_python",
        notes="Wizard/headless config flows are Python-owned and well covered by config tests.",
    ),
    "doctor": FeatureDefinition(
        area="diagnostics",
        feature="Command: print readiness and runtime diagnostics",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/debug/doctor_orchestrator.py",
            "python/envctl_engine/runtime/engine_runtime.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_engine_runtime_command_parity.py",
        ),
        parity_status="verified_python",
        notes="Doctor is Python-owned and explicitly covered by runtime command parity tests.",
        current_behavior="Python doctor reports runtime readiness, parity, state health, and recent failure diagnostics without shell migration fields.",
        missing_python_behavior="Keep the doctor output contract focused on runtime readiness and state diagnostics, then cover those fields explicitly in Python tests.",
        python_owner_module="python/envctl_engine/debug/doctor_orchestrator.py",
        proposed_tests=(
            "tests/python/runtime/test_engine_runtime_command_parity.py",
        ),
        severity="low",
        rollout_risk="Doctor output drift is mostly a diagnostics/readiness concern, but it can confuse operators during cutover.",
        wave="Wave E",
    ),
    "migrate-hooks": FeatureDefinition(
        area="cli",
        feature="Command: migrate legacy shell hook functions into a Python .envctl_hooks.py module",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/shared/hooks.py",
            "python/envctl_engine/runtime/hook_migration_support.py",
            "python/envctl_engine/runtime/engine_runtime.py",
        ),
        evidence_tests=(
            "tests/python/startup/test_hooks_bridge.py",
        ),
        parity_status="verified_python",
        notes="Hook migration is Python-owned and provides an explicit path away from executable shell hooks.",
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
        evidence_tests=(
            "tests/python/runtime/test_engine_runtime_debug_support.py",
        ),
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
        evidence_tests=(
            "tests/python/runtime/test_engine_runtime_debug_support.py",
        ),
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
        evidence_tests=(
            "tests/python/runtime/test_engine_runtime_debug_support.py",
        ),
        parity_status="verified_python",
        notes="Debug-last is Python-owned and covered by diagnostics tests.",
    ),
    "help": FeatureDefinition(
        area="cli",
        feature="Command: print runtime help and usage guidance",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/runtime/cli.py",
            "python/envctl_engine/runtime/command_router.py",
            "python/envctl_engine/runtime/launcher_cli.py",
            "python/envctl_engine/runtime/launcher_support.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_cli_router.py",
            "tests/python/runtime/test_engine_runtime_command_parity.py",
            "tests/python/runtime/test_command_exit_codes.py",
        ),
        parity_status="verified_python",
        notes="Help and usage guidance are now owned by Python for both the installed CLI and the top-level launcher wrapper.",
        current_behavior="Users can get help successfully, but top-level launcher usage and shell-backed help text still contribute to the final behavior.",
        missing_python_behavior="Make Python the unambiguous source of help/usage semantics while preserving the current user-visible content and examples.",
        python_owner_module="python/envctl_engine/runtime/cli.py",
        proposed_tests=(
            "tests/python/runtime/test_cli_router.py",
        ),
        severity="medium",
        rollout_risk="Help text drift creates immediate confusion for installation and first-run workflows.",
        wave="Wave A",
    ),
    "list-commands": FeatureDefinition(
        area="cli",
        feature="Command: print the supported command inventory",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/runtime/command_router.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_engine_runtime_command_parity.py",
        ),
        parity_status="verified_python",
        notes="List-commands is explicitly parity-tested against the shell inventory.",
    ),
    "list-targets": FeatureDefinition(
        area="cli",
        feature="Command: print available project and service targets",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/runtime/engine_runtime.py",
            "python/envctl_engine/runtime/command_router.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_engine_runtime_command_parity.py",
            "tests/python/runtime/test_engine_runtime_real_startup.py",
        ),
        parity_status="verified_python",
        notes="List-targets is Python-owned and tested through runtime discovery paths.",
    ),
    "list-trees": FeatureDefinition(
        area="cli",
        feature="Command: print available tree targets",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/runtime/engine_runtime.py",
            "python/envctl_engine/runtime/command_router.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_command_router_contract.py",
            "tests/python/runtime/test_engine_runtime_command_parity.py",
        ),
        parity_status="verified_python",
        notes="List-trees is Python-owned and covered by router/runtime tests.",
    ),
}

_EXTRA_FEATURES: tuple[FeatureDefinition, ...] = (
    FeatureDefinition(
        area="launcher",
        feature="Top-level envctl launcher resolves repo root, honors --repo, and forwards commands into the runtime",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/runtime/launcher_cli.py",
            "python/envctl_engine/runtime/launcher_support.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_command_exit_codes.py",
            "tests/python/runtime/test_cli_packaging.py",
        ),
        parity_status="verified_python",
        notes="The top-level launcher now delegates repo resolution, doctor, and forwarding behavior through the Python launcher module.",
        current_behavior="The shell launcher owns repo-root resolution and command forwarding before the Python runtime starts.",
        missing_python_behavior="Decide whether repo resolution should remain a launcher concern or move into Python, and then prove the chosen contract independently of shell behavior.",
        python_owner_module="python/envctl_engine/runtime/cli.py",
        proposed_tests=(
            "tests/python/runtime/test_command_exit_codes.py",
        ),
        severity="high",
        rollout_risk="Launcher regressions can make envctl unusable before Python runtime logic even begins.",
        wave="Wave A",
    ),
    FeatureDefinition(
        area="launcher",
        feature="envctl install writes a shell-file hook block that exposes envctl on PATH",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/runtime/launcher_cli.py",
            "python/envctl_engine/runtime/launcher_support.py",
            "python/envctl_engine/runtime/cli.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_command_exit_codes.py",
            "tests/python/runtime/test_cli_packaging.py",
        ),
        parity_status="verified_python",
        notes="Install is now implemented and tested in Python for both the installed CLI and the top-level launcher wrapper.",
        current_behavior="Install is implemented entirely in shell wrapper/installer code and remains outside Python runtime ownership.",
        missing_python_behavior="Define the long-term ownership model for install behavior and prove it with stable tests that do not assume shell runtime semantics.",
        python_owner_module="python/envctl_engine/runtime/cli.py",
        proposed_tests=(
            "tests/python/runtime/test_command_exit_codes.py",
        ),
        severity="high",
        rollout_risk="Install regressions directly affect package adoption and first-run UX.",
        wave="Wave A",
    ),
    FeatureDefinition(
        area="launcher",
        feature="envctl uninstall removes the shell-file hook block cleanly and idempotently",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/runtime/launcher_cli.py",
            "python/envctl_engine/runtime/launcher_support.py",
            "python/envctl_engine/runtime/cli.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_command_exit_codes.py",
            "tests/python/runtime/test_cli_packaging.py",
        ),
        parity_status="verified_python",
        notes="Uninstall is now implemented and tested in Python for both the installed CLI and the top-level launcher wrapper.",
        current_behavior="Uninstall is implemented by the shell installer path and has no Python-owned equivalent.",
        missing_python_behavior="Capture uninstall semantics as an explicit contract and prove idempotent removal behavior independent of shell runtime assumptions.",
        python_owner_module="python/envctl_engine/runtime/cli.py",
        proposed_tests=(
            "tests/python/runtime/test_command_exit_codes.py",
        ),
        severity="medium",
        rollout_risk="Uninstall drift is less severe than install drift but still affects trust in the package workflow.",
        wave="Wave A",
    ),
    FeatureDefinition(
        area="cli",
        feature="Python command parser remains aligned with the supported public command and flag surface",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/runtime/command_router.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_cli_router_parity.py",
            "tests/python/runtime/test_engine_runtime_command_parity.py",
        ),
        parity_status="verified_python",
        notes="Parser compatibility is now enforced against the Python-owned public command and documentation surface.",
    ),
    FeatureDefinition(
        area="planning",
        feature="Interactive planning selection and count synchronization preserve existing runs while adding or removing trees",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/planning/worktree_domain.py",
            "python/envctl_engine/startup/startup_orchestrator.py",
        ),
        evidence_tests=(
            "tests/python/planning/test_planning_textual_selector.py",
            "tests/python/runtime/test_engine_runtime_real_startup.py",
        ),
        parity_status="verified_python",
        notes="Planning add/remove/zero-scale synchronization, existing-run reuse, and archive behavior are covered by planning and real-startup tests.",
        current_behavior="Python plan selection handles scale-up/down and existing-run reuse, but these flows are still among the most behaviorally rich parts of the old shell runtime.",
        missing_python_behavior="Exhaustively prove plan selection, run reuse, and interactive handoff semantics across add/remove/zero-scale transitions so shell is no longer needed as a behavior oracle.",
        python_owner_module="python/envctl_engine/planning/worktree_domain.py",
        proposed_tests=(
            "tests/python/planning/test_planning_worktree_setup.py",
            "tests/python/runtime/test_engine_runtime_real_startup.py",
        ),
        severity="medium",
        rollout_risk="Plan-selection regressions create high user confusion because they can restart, remove, or preserve the wrong trees.",
        wave="Wave B",
    ),
    FeatureDefinition(
        area="planning",
        feature="Worktree setup flags reuse, recreate, and include-existing-worktrees behave consistently across planning workflows",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/planning/worktree_domain.py",
            "python/envctl_engine/runtime/command_router.py",
        ),
        evidence_tests=(
            "tests/python/planning/test_planning_worktree_setup.py",
            "tests/python/runtime/test_engine_runtime_real_startup.py",
        ),
        parity_status="verified_python",
        notes="Setup-worktree reuse, recreate, and include-existing flag behavior is covered by planning/runtime tests and the setup-worktree BATS lane.",
        current_behavior="Setup-worktree and include-existing-worktrees flags are present, but parity evidence is still mostly external and shell-era.",
        missing_python_behavior="Inventory and prove reuse/recreate/include flag semantics in Python planning/worktree tests so setup flows are no longer shell-defined by implication.",
        python_owner_module="python/envctl_engine/planning/worktree_domain.py",
        proposed_tests=(
            "tests/python/planning/test_planning_worktree_setup.py",
        ),
        severity="medium",
        rollout_risk="Worktree setup flags can be destructive, so parity gaps here risk accidental reuse or recreation of the wrong tree.",
        wave="Wave B",
    ),
    FeatureDefinition(
        area="requirements",
        feature="Dependency startup and cleanup remain symmetric for postgres, redis, supabase, and n8n across startup, stop, blast, and planning scale-down",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/requirements/orchestrator.py",
            "python/envctl_engine/runtime/engine_runtime_lifecycle_support.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_engine_runtime_lifecycle_support.py",
            "tests/python/requirements/test_requirements_orchestrator.py",
        ),
        parity_status="verified_python",
        notes="Dependency startup and cleanup symmetry is covered by runtime lifecycle, requirements orchestrator, and adapter parity tests.",
        current_behavior="Python requirement startup works, but the shell stack still represents the older complete behavior for cleanup symmetry across dependency families.",
        missing_python_behavior="Prove symmetric startup/cleanup behavior for every dependency family across startup, restart, blast-all, blast-worktree, and planning scale-down.",
        python_owner_module="python/envctl_engine/requirements/orchestrator.py",
        proposed_tests=(
            "tests/python/runtime/test_engine_runtime_lifecycle_support.py",
            "tests/python/requirements/test_requirements_orchestrator.py",
        ),
        severity="high",
        rollout_risk="Lifecycle asymmetry leaves dependency resources behind and is one of the fastest ways to make future runs unreliable.",
        wave="Wave C",
    ),
    FeatureDefinition(
        area="requirements",
        feature="Supabase lifecycle, project naming, and container cleanup remain stable for long project names and repeated plan cycles",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/requirements/supabase.py",
            "python/envctl_engine/requirements/common.py",
        ),
        evidence_tests=(
            "tests/python/requirements/test_supabase_requirements_reliability.py",
            "tests/python/requirements/test_requirements_common.py",
        ),
        parity_status="verified_python",
        notes="Supabase naming, cleanup, and repeated lifecycle behavior are covered by dedicated reliability and lifecycle tests.",
        current_behavior="Python Supabase support is real and tested, but legacy shell behavior is still the broader historical reference for repeated cleanup and naming edge cases.",
        missing_python_behavior="Fully prove long-name naming, stale-container cleanup, and repeated lifecycle behavior without needing shell as the fallback oracle.",
        python_owner_module="python/envctl_engine/requirements/supabase.py",
        proposed_tests=(
            "tests/python/requirements/test_supabase_requirements_reliability.py",
            "tests/python/runtime/test_engine_runtime_lifecycle_support.py",
        ),
        severity="high",
        rollout_risk="Supabase cleanup and naming bugs directly block startup and are expensive for users to diagnose manually.",
        wave="Wave C",
    ),
    FeatureDefinition(
        area="requirements",
        feature="Seed or copy-db-storage behavior for per-tree requirements remains consistent with existing workflows",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/requirements/supabase.py",
            "python/envctl_engine/runtime/command_router.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_engine_runtime_real_startup.py",
            "tests/python/requirements/test_requirements_orchestrator.py",
        ),
        parity_status="verified_python",
        notes="Seed and copy-db-storage behavior is covered by runtime startup/requirements tests and the adapter parity BATS lane.",
        current_behavior="Seed/copy-db flags still carry shell-era expectations and are not yet expressed as a full Python-owned contract.",
        missing_python_behavior="Define the exact retained seeding behavior and cover it with Python and end-to-end tests so the feature is no longer implicitly shell-defined.",
        python_owner_module="python/envctl_engine/requirements/supabase.py",
        proposed_tests=(
            "tests/python/requirements/test_requirements_orchestrator.py",
        ),
        severity="high",
        rollout_risk="Incorrect seeding semantics can corrupt developer expectations and destroy trust in tree isolation.",
        wave="Wave C",
    ),
    FeatureDefinition(
        area="artifacts",
        feature="Run state, runtime map, ports manifest, and error report remain the authoritative per-run artifact set",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/state/repository.py",
            "python/envctl_engine/runtime/engine_runtime_artifacts.py",
        ),
        evidence_tests=(
            "tests/python/state/test_state_repository_contract.py",
            "tests/python/runtime/test_engine_runtime_artifacts.py",
        ),
        parity_status="verified_python",
        notes="Core runtime artifacts are already Python-owned and well covered.",
    ),
    FeatureDefinition(
        area="artifacts",
        feature="Test results and review artifacts live under the scoped runtime /tmp tree and retain valid dashboard links",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/state/repository.py",
            "python/envctl_engine/actions/project_action_domain.py",
        ),
        evidence_tests=(
            "tests/python/state/test_state_repository_contract.py",
            "tests/python/actions/test_actions_cli.py",
            "tests/python/actions/test_actions_parity.py",
        ),
        parity_status="verified_python",
        notes="Artifact relocation into runtime scope is Python-owned and covered by focused tests.",
    ),
    FeatureDefinition(
        area="artifacts",
        feature="Artifact retention and cleanup remain correct across stop, blast, resume, and plan scale-down flows",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/state/repository.py",
            "python/envctl_engine/runtime/lifecycle_cleanup_orchestrator.py",
        ),
        evidence_tests=(
            "tests/python/state/test_state_repository_contract.py",
            "tests/python/runtime/test_lifecycle_parity.py",
        ),
        parity_status="verified_python",
        notes="Artifact retention and cleanup semantics are covered by state repository and lifecycle parity tests.",
        current_behavior="Python artifacts are scoped correctly, but retention and cleanup semantics across all lifecycle transitions are not yet expressed as a full parity contract.",
        missing_python_behavior="Codify artifact retention expectations for stop, blast, resume, and plan scale-down, then cover them with focused repository and lifecycle tests.",
        python_owner_module="python/envctl_engine/state/repository.py",
        proposed_tests=(
            "tests/python/state/test_state_repository_contract.py",
            "tests/python/runtime/test_lifecycle_parity.py",
        ),
        severity="medium",
        rollout_risk="Artifact cleanup regressions can leave stale state that confuses later runs and operator debugging.",
        wave="Wave E",
    ),
    FeatureDefinition(
        area="diagnostics",
        feature="Release or shipability checks reflect the retained product contract instead of historical shell migration governance",
        user_visible=False,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/shell/release_gate.py",
            "python/envctl_engine/debug/doctor_orchestrator.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_release_shipability_gate.py",
            "tests/python/runtime/test_cutover_gate_truth.py",
        ),
        parity_status="verified_python",
        notes="Release and cutover gate behavior is Python-owned and covered by release gate and cutover truth tests.",
        current_behavior="Release and doctor readiness checks now use the Python runtime readiness contract and parity manifest as their source of truth.",
        missing_python_behavior="Keep the release gate aligned with runtime readiness and parity freshness, then cover the retained contract directly in Python tests.",
        python_owner_module="python/envctl_engine/shell/release_gate.py",
        proposed_tests=(
            "tests/python/runtime/test_release_shipability_gate.py",
            "tests/python/runtime/test_cutover_gate_truth.py",
        ),
        severity="low",
        rollout_risk="This is mainly a developer-workflow risk, but confusing gates slow down confident cutover decisions.",
        wave="Wave E",
    ),
)

_FEATURE_DEFINITIONS: tuple[FeatureDefinition, ...] = tuple(_COMMAND_DEFINITIONS[command] for command in list_supported_commands()) + _EXTRA_FEATURES

_ALLOWED_PARITY_STATUSES = {"verified_python", "shell_only", "unverified", "python_partial"}
_ALLOWED_SEVERITIES = {"high", "medium", "low"}
_LEGACY_SHELL_FALLBACK_ENV = "ENVCTL_ENGINE_" + "SHELL_FALLBACK"


def _documented_flag_tokens(repo_root: Path) -> list[str]:
    docs_path = repo_root / "docs" / "reference" / "important-flags.md"
    if not docs_path.is_file():
        return []
    text = docs_path.read_text(encoding="utf-8")
    return sorted(set(re.findall(r"--[a-z0-9][a-z0-9-]*", text)))


def _feature_row(index: int, feature: FeatureDefinition, *, repo_root: Path, command: str | None = None) -> dict[str, Any]:
    shell_refs = [ref for ref in feature.shell_source_of_truth if (repo_root / ref).exists()]
    evidence_refs = [ref for ref in feature.evidence_tests if (repo_root / ref).exists()]
    row = {
        "id": f"F-{index:03d}",
        "area": feature.area,
        "feature": feature.feature,
        "user_visible": feature.user_visible,
        "shell_source_of_truth": shell_refs,
        "python_source_of_truth": list(feature.python_source_of_truth),
        "evidence_tests": evidence_refs,
        "parity_status": feature.parity_status,
        "notes": feature.notes,
    }
    if command is not None:
        row["command"] = command
    if feature.current_behavior:
        row["current_behavior"] = feature.current_behavior
    if feature.missing_python_behavior:
        row["missing_python_behavior"] = feature.missing_python_behavior
    if feature.python_owner_module:
        row["python_owner_module"] = feature.python_owner_module
    if feature.proposed_tests:
        row["proposed_tests"] = list(feature.proposed_tests)
    if feature.severity:
        row["severity"] = feature.severity
    if feature.rollout_risk:
        row["rollout_risk"] = feature.rollout_risk
    if feature.wave:
        row["wave"] = feature.wave
    return row


def build_runtime_feature_matrix(*, repo_root: Path, generated_at: str) -> dict[str, Any]:
    python_commands = list_supported_commands()
    python_flags = list_supported_flag_tokens()
    features: list[dict[str, Any]] = []
    index = 1
    for command in list_supported_commands():
        features.append(_feature_row(index, _COMMAND_DEFINITIONS[command], repo_root=repo_root, command=command))
        index += 1
    for definition in _EXTRA_FEATURES:
        features.append(_feature_row(index, definition, repo_root=repo_root))
        index += 1
    return {
        "version": 1,
        "generated_at": generated_at,
        "inventory_sources": {
            "python_supported_commands": python_commands,
            "python_supported_flag_tokens": python_flags,
            "documented_flag_tokens": _documented_flag_tokens(repo_root),
        },
        "summary": {
            "feature_count": len(features),
            "user_visible_feature_count": sum(1 for feature in features if bool(feature["user_visible"])),
            "areas": dict(sorted(Counter(str(feature["area"]) for feature in features).items())),
            "parity_status": dict(sorted(Counter(str(feature["parity_status"]) for feature in features).items())),
        },
        "features": features,
    }


def build_python_runtime_gap_report(*, repo_root: Path, generated_at: str, matrix_payload: dict[str, Any]) -> dict[str, Any]:
    features = matrix_payload.get("features", [])
    gaps: list[dict[str, Any]] = []
    for feature in features if isinstance(features, list) else []:
        if not isinstance(feature, dict):
            continue
        parity_status = str(feature.get("parity_status", "")).strip()
        if parity_status == "verified_python":
            continue
        gap = {
            "feature_id": str(feature.get("id", "")),
            "area": str(feature.get("area", "")),
            "feature": str(feature.get("feature", "")),
            "parity_status": parity_status,
            "current_behavior": str(feature.get("current_behavior", feature.get("notes", ""))).strip(),
            "missing_python_behavior": str(feature.get("missing_python_behavior", "")).strip(),
            "python_owner_module": str(feature.get("python_owner_module", "")).strip(),
            "proposed_tests": list(feature.get("proposed_tests", [])),
            "severity": str(feature.get("severity", "low")).strip().lower(),
            "rollout_risk": str(feature.get("rollout_risk", "")).strip(),
            "shell_source_of_truth": list(feature.get("shell_source_of_truth", [])),
            "python_source_of_truth": list(feature.get("python_source_of_truth", [])),
            "evidence_tests": list(feature.get("evidence_tests", [])),
            "notes": str(feature.get("notes", "")).strip(),
            "wave": str(feature.get("wave", "")).strip() or _wave_for_area(str(feature.get("area", ""))),
        }
        gaps.append(gap)

    severity_counts = Counter(str(gap["severity"]) for gap in gaps)
    status_counts = Counter(str(gap["parity_status"]) for gap in gaps)
    area_counts = Counter(str(gap["area"]) for gap in gaps)
    matrix_rendered = json.dumps(matrix_payload, indent=2, sort_keys=True) + "\n"
    shell_retirement_blockers = _shell_retirement_blockers(repo_root=repo_root)
    return {
        "version": 1,
        "generated_at": generated_at,
        "matrix_generated_at": matrix_payload.get("generated_at", ""),
        "matrix_sha256": hashlib.sha256(matrix_rendered.encode("utf-8")).hexdigest(),
        "summary": {
            "feature_count": len(features) if isinstance(features, list) else 0,
            "gap_count": len(gaps),
            "high_or_medium_gap_count": sum(1 for gap in gaps if str(gap["severity"]) in {"high", "medium"}),
            "by_status": dict(sorted(status_counts.items())),
            "by_severity": dict(sorted(severity_counts.items())),
            "by_area": dict(sorted(area_counts.items())),
        },
        "shell_retirement_blockers": shell_retirement_blockers,
        "gaps": gaps,
    }


def render_python_runtime_gap_closure_plan(*, report_payload: dict[str, Any]) -> str:
    gaps = [gap for gap in report_payload.get("gaps", []) if isinstance(gap, dict)]
    summary = report_payload.get("summary", {})
    wave_order = ["Wave A", "Wave B", "Wave C", "Wave D", "Wave E"]
    wave_titles = {
        "Wave A": "Launcher, Help, and Install Parity",
        "Wave B": "Lifecycle, Planning, and Worktree Parity",
        "Wave C": "Requirements and Dependency Lifecycle Parity",
        "Wave D": "Action Command Parity",
        "Wave E": "Diagnostics, Inspection, and Artifact Parity",
    }
    wave_scope = {
        "Wave A": "Close the remaining launcher-owned and help/install gaps without changing current user-visible behavior.",
        "Wave B": "Prove that lifecycle, planning, and worktree operations preserve the current behavior across startup, scale-down, and cleanup paths.",
        "Wave C": "Finish the risky dependency and cleanup parity areas that still make shell a compatibility oracle.",
        "Wave D": "Lock down action command contracts so test/review/pr/commit/migrate no longer depend on shell-era expectations.",
        "Wave E": "Retain only the diagnostics, dashboard, and artifact behavior that is truly part of the supported product contract.",
    }
    grouped: dict[str, list[dict[str, Any]]] = {wave: [] for wave in wave_order}
    for gap in gaps:
        wave = str(gap.get("wave", "")).strip() or _wave_for_area(str(gap.get("area", "")))
        grouped.setdefault(wave, []).append(gap)

    lines = [
        "# Python Runtime Gap Closure Plan",
        "",
        "## Summary",
        f"- Generated from `contracts/python_runtime_gap_report.json`.",
        f"- Total inventoried features: {summary.get('feature_count', 0)}",
        f"- Open gaps: {summary.get('gap_count', 0)}",
        f"- High or medium gaps: {summary.get('high_or_medium_gap_count', 0)}",
        "",
        "This plan keeps the current shell runtime available as a compatibility oracle while Python closes the remaining retained-behavior gaps. No shell deletion work should begin until all high and medium gaps below are closed or explicitly accepted.",
        "",
        "## Shared Rules",
        "- Preserve current user-visible behavior while implementing each wave.",
        "- Keep shell-backed verification where it is still the behavior oracle.",
        "- Mark a feature `verified_python` only after the behavior exists and the acceptance tests are in place.",
        "- Run full Python unittest discovery and the full BATS suite after each completed wave.",
        "",
        "## Wave Breakdown",
    ]
    for wave in wave_order:
        wave_gaps = grouped.get(wave, [])
        lines.extend(
            [
                "",
                f"### {wave}: {wave_titles[wave]}",
                wave_scope[wave],
            ]
        )
        if not wave_gaps:
            lines.append("")
            lines.append("No currently reported gaps in this wave.")
            continue
        lines.extend(
            [
                "",
                "| ID | Severity | Area | Gap | Python Owner | Proposed Tests |",
                "|----|----------|------|-----|--------------|----------------|",
            ]
        )
        for gap in wave_gaps:
            tests = ", ".join(str(item) for item in gap.get("proposed_tests", []))
            lines.append(
                f"| {gap.get('feature_id', '')} | {gap.get('severity', '')} | {gap.get('area', '')} | "
                f"{gap.get('feature', '')} | {gap.get('python_owner_module', '')} | {tests} |"
            )
        lines.extend(
            [
                "",
                "#### Required Work",
            ]
        )
        for gap in wave_gaps:
            lines.extend(
                [
                    f"- `{gap.get('feature_id', '')}` {gap.get('feature', '')}",
                    f"  Current behavior: {gap.get('current_behavior', '')}",
                    f"  Required Python work: {gap.get('missing_python_behavior', '')}",
                    f"  Rollout risk: {gap.get('rollout_risk', '')}",
                ]
            )
    lines.extend(
        [
            "",
            "## Completion Gate",
            "- All high and medium gaps are closed or explicitly accepted.",
            "- `contracts/runtime_feature_matrix.json` is updated so closed items are marked `verified_python`.",
            "- `contracts/python_runtime_gap_report.json` shows no remaining high or medium gaps.",
            "- Full Python unittest discovery passes.",
            "- Full BATS suite passes.",
            "",
            "## Follow-Up Boundary",
            "Only after this plan is complete should a separate shell-retirement plan be executed.",
            "",
        ]
    )
    return "\n".join(lines)


def _wave_for_area(area: str) -> str:
    if area in {"launcher", "cli"}:
        return "Wave A"
    if area in {"lifecycle", "planning"}:
        return "Wave B"
    if area == "requirements":
        return "Wave C"
    if area == "actions":
        return "Wave D"
    return "Wave E"


def _shell_retirement_blockers(*, repo_root: Path) -> dict[str, Any]:
    checks = {
        "runtime_selector_removed": _check_runtime_selector_removed(repo_root),
        "bash_launchers_removed": _check_bash_launchers_removed(repo_root),
        "shell_fallback_contract_removed": _check_shell_fallback_contract_removed(repo_root),
        "bash_hook_bridge_removed": _check_bash_hook_bridge_removed(repo_root),
        "shell_governance_removed": _check_shell_governance_removed(repo_root),
        "legacy_config_python_owned": _check_legacy_config_python_owned(repo_root),
        "bats_harness_removed": _check_bats_harness_removed(repo_root),
    }
    return {
        "ready_for_shell_retirement": all(bool(check["passed"]) for check in checks.values()),
        "checks": checks,
    }


def _check_runtime_selector_removed(repo_root: Path) -> dict[str, Any]:
    main_sh = repo_root / "lib" / "engine" / "main.sh"
    if not main_sh.is_file():
        return {"passed": True, "details": ["The legacy runtime selector bridge is already absent."]}
    text = main_sh.read_text(encoding="utf-8")
    passed = "exec_shell_engine" not in text
    details = (
        ["The legacy shell runtime selector no longer contains exec_shell_engine()."]
        if passed
        else ["The legacy shell runtime selector still contains exec_shell_engine()."]
    )
    return {"passed": passed, "details": details}


def _check_bash_launchers_removed(repo_root: Path) -> dict[str, Any]:
    paths = (
        Path("lib") / "envctl.sh",
        Path("lib") / "engine" / "main.sh",
        Path("scripts") / "install.sh",
    )
    lingering = [str(path) for path in paths if (repo_root / path).exists()]
    passed = not lingering
    details = (
        ["No tracked Bash launcher/install wrappers remain."]
        if passed
        else [f"Tracked Bash launcher/install files remain: {', '.join(lingering)}"]
    )
    return {"passed": passed, "details": details}


def _check_shell_fallback_contract_removed(repo_root: Path) -> dict[str, Any]:
    active_paths = (
        "README.md",
        "python/envctl_engine/runtime/launcher_cli.py",
        "python/envctl_engine/runtime/engine_runtime_debug_support.py",
        "python/envctl_engine/config/__init__.py",
        "docs/reference/configuration.md",
        "docs/reference/important-flags.md",
        "docs/user/getting-started.md",
        "docs/user/python-engine-guide.md",
        "docs/user/faq.md",
        "docs/operations/troubleshooting.md",
        "docs/developer/runtime-lifecycle.md",
        "docs/developer/architecture-overview.md",
        "docs/developer/command-surface.md",
    )
    matches = _path_matches(repo_root, active_paths, _LEGACY_SHELL_FALLBACK_ENV)
    passed = not matches
    details = (
        ["No active code/docs reference the legacy shell fallback environment variable."]
        if passed
        else [f"Active shell fallback references remain: {', '.join(matches)}"]
    )
    return {"passed": passed, "details": details}


def _check_bash_hook_bridge_removed(repo_root: Path) -> dict[str, Any]:
    hook_bridge = repo_root / "python" / "envctl_engine" / "shared" / "hooks.py"
    if not hook_bridge.is_file():
        return {"passed": False, "details": ["python/envctl_engine/shared/hooks.py is missing."]}
    text = hook_bridge.read_text(encoding="utf-8")
    forbidden_tokens = ('["bash", "-lc"', "source \"$ENVCTL_HOOK_FILE\"", "subprocess.run(")
    matches = [token for token in forbidden_tokens if token in text]
    passed = not matches
    details = (
        ["The hook bridge no longer shells out through bash."]
        if passed
        else [f"The hook bridge still contains Bash execution markers: {', '.join(matches)}"]
    )
    return {"passed": passed, "details": details}


def _check_shell_governance_removed(repo_root: Path) -> dict[str, Any]:
    deleted_paths = (
        Path("python") / "envctl_engine" / "shell" / ("shell" + "_prune.py"),
        Path("contracts") / ("envctl-shell" + "-ownership-ledger.json"),
        Path("scripts") / ("verify_shell" + "_prune_contract.py"),
        Path("scripts") / "report_unmigrated_shell.py",
        Path("scripts") / ("generate_shell" + "_ownership_ledger.py"),
        Path("tests") / "python" / "shell" / ("test_shell" + "_prune_contract.py"),
        Path("tests") / "python" / "shell" / "test_shell_ownership_ledger.py",
        Path("docs") / "developer" / "shell-compatibility.md",
    )
    lingering_files = [str(path) for path in deleted_paths if (repo_root / path).exists()]
    active_reference_paths = (
        "python/envctl_engine/runtime/engine_runtime.py",
        "python/envctl_engine/runtime/engine_runtime_artifacts.py",
        "python/envctl_engine/shared/protocols.py",
        "python/envctl_engine/state/repository.py",
        "python/envctl_engine/shell/release_gate.py",
        "python/envctl_engine/debug/doctor_orchestrator.py",
        "scripts/release_shipability_gate.py",
        "tests/python/runtime/test_engine_runtime_command_parity.py",
        "tests/python/runtime/test_release_shipability_gate.py",
        "tests/python/runtime/test_cutover_gate_truth.py",
        "tests/python/state/test_state_repository_contract.py",
        "docs/developer/python-runtime-guide.md",
        "docs/developer/debug-and-diagnostics.md",
    )
    active_refs = sorted(
        set(
            _path_matches(repo_root, active_reference_paths, "shell" + "_prune")
            + _path_matches(repo_root, active_reference_paths, "envctl-shell" + "-ownership-ledger")
        )
    )
    passed = not lingering_files and not active_refs
    details: list[str] = []
    if lingering_files:
        details.append(f"Shell governance files still exist: {', '.join(lingering_files)}")
    if active_refs:
        details.append(f"Active shell governance references remain: {', '.join(active_refs)}")
    if not details:
        details.append("Shell governance files are deleted and active references are gone.")
    return {"passed": passed, "details": details}


def _check_legacy_config_python_owned(repo_root: Path) -> dict[str, Any]:
    hook_bridge = repo_root / "python" / "envctl_engine" / "runtime" / "engine_runtime_hooks.py"
    passed = hook_bridge.is_file()
    details: list[str] = []
    if not hook_bridge.is_file():
        details.append("Python .envctl.sh compatibility hook is missing.")
    else:
        details.append("Python .envctl.sh compatibility hook exists.")
    config_loader_refs = _path_matches(
        repo_root,
        (
            "python",
            "scripts",
            "tests",
            "docs",
            "lib",
        ),
        "config_loader.sh",
    )
    # Ignore the shell tree itself; we only care whether active non-shell surfaces still rely on it.
    legacy_shell_tree_prefix = "lib/engine/" + "lib/"
    config_loader_refs = [
        ref
        for ref in config_loader_refs
        if not ref.startswith(legacy_shell_tree_prefix) and ref != "python/envctl_engine/runtime_feature_inventory.py"
    ]
    if config_loader_refs:
        passed = False
        details.append(f"Active non-shell references to config_loader.sh remain: {', '.join(config_loader_refs)}")
    else:
        details.append("No active non-shell surface references config_loader.sh.")
    return {"passed": passed, "details": details}


def _check_bats_harness_removed(repo_root: Path) -> dict[str, Any]:
    bats_dir = repo_root / "tests" / "bats"
    bats_files = sorted(str(path.relative_to(repo_root)) for path in bats_dir.rglob("*.bats")) if bats_dir.exists() else []
    passed = not bats_files
    details = (
        ["The BATS harness has been fully removed."]
        if passed
        else [f"Tracked BATS files remain: {', '.join(bats_files[:5])}" + (" ..." if len(bats_files) > 5 else "")]
    )
    return {"passed": passed, "details": details}


def _path_matches(repo_root: Path, relative_paths: tuple[str, ...], needle: str) -> list[str]:
    matches: list[str] = []
    for raw_path in relative_paths:
        path = repo_root / raw_path
        if not path.exists():
            continue
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if not child.is_file():
                    continue
                try:
                    text = child.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                if needle in text:
                    matches.append(str(child.relative_to(repo_root)))
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if needle in text:
            matches.append(str(path.relative_to(repo_root)))
    return sorted(set(matches))


def validate_runtime_feature_matrix_payload(payload: dict[str, Any], *, repo_root: Path) -> None:
    features = payload.get("features")
    if not isinstance(features, list):
        raise ValueError("features must be a list")
    seen_ids: set[str] = set()
    supported_commands = set(list_supported_commands())
    command_features = {
        str(feature.get("command", "")).strip()
        for feature in features
        if isinstance(feature, dict) and str(feature.get("command", "")).strip()
    }
    missing_commands = supported_commands.difference(command_features)
    if missing_commands:
        raise ValueError(f"missing command features: {', '.join(sorted(missing_commands))}")
    for feature in features:
        if not isinstance(feature, dict):
            raise ValueError("feature rows must be objects")
        feature_id = str(feature.get("id", "")).strip()
        if not feature_id or feature_id in seen_ids:
            raise ValueError(f"duplicate or missing feature id: {feature_id}")
        seen_ids.add(feature_id)
        parity_status = str(feature.get("parity_status", "")).strip()
        if parity_status not in _ALLOWED_PARITY_STATUSES:
            raise ValueError(f"invalid parity status for {feature_id}: {parity_status}")
        python_refs = [str(ref) for ref in feature.get("python_source_of_truth", [])]
        shell_refs = [str(ref) for ref in feature.get("shell_source_of_truth", [])]
        source_refs = shell_refs + python_refs
        if bool(feature.get("user_visible")) and not source_refs:
            raise ValueError(f"user-visible feature missing source references: {feature_id}")
        if not python_refs:
            raise ValueError(f"feature missing python source references: {feature_id}")
        for ref in python_refs:
            ref_path = repo_root / ref
            if not ref_path.exists():
                raise ValueError(f"missing referenced path for {feature_id}: {ref}")
        evidence_refs = [str(ref) for ref in feature.get("evidence_tests", [])]
        if parity_status == "verified_python" and not evidence_refs:
            raise ValueError(f"verified_python feature missing evidence tests: {feature_id}")
        if evidence_refs:
            existing_evidence = [ref for ref in evidence_refs if (repo_root / ref).exists()]
            if not existing_evidence:
                raise ValueError(f"no existing evidence tests remain for {feature_id}")


def validate_python_runtime_gap_report_payload(payload: dict[str, Any], *, matrix_payload: dict[str, Any]) -> None:
    gaps = payload.get("gaps")
    if not isinstance(gaps, list):
        raise ValueError("gaps must be a list")
    matrix_by_id = {
        str(feature.get("id", "")): feature
        for feature in matrix_payload.get("features", [])
        if isinstance(feature, dict)
    }
    for gap in gaps:
        if not isinstance(gap, dict):
            raise ValueError("gap rows must be objects")
        feature_id = str(gap.get("feature_id", "")).strip()
        if feature_id not in matrix_by_id:
            raise ValueError(f"gap references unknown feature id: {feature_id}")
        source_feature = matrix_by_id[feature_id]
        if str(source_feature.get("parity_status", "")) == "verified_python":
            raise ValueError(f"verified_python feature should not appear in gaps: {feature_id}")
        severity = str(gap.get("severity", "")).strip().lower()
        if severity not in _ALLOWED_SEVERITIES:
            raise ValueError(f"invalid severity for gap {feature_id}: {severity}")
        if not str(gap.get("python_owner_module", "")).strip():
            raise ValueError(f"gap missing python owner module: {feature_id}")
        if not list(gap.get("proposed_tests", [])):
            raise ValueError(f"gap missing proposed tests: {feature_id}")
    blockers = payload.get("shell_retirement_blockers")
    if not isinstance(blockers, dict):
        raise ValueError("shell_retirement_blockers must be an object")
    if not isinstance(blockers.get("ready_for_shell_retirement"), bool):
        raise ValueError("shell_retirement_blockers.ready_for_shell_retirement must be a boolean")
    checks = blockers.get("checks")
    if not isinstance(checks, dict):
        raise ValueError("shell_retirement_blockers.checks must be an object")
    required_checks = {
        "runtime_selector_removed",
        "bash_launchers_removed",
        "shell_fallback_contract_removed",
        "bash_hook_bridge_removed",
        "shell_governance_removed",
        "legacy_config_python_owned",
        "bats_harness_removed",
    }
    missing_checks = required_checks.difference(checks)
    if missing_checks:
        raise ValueError(f"missing shell retirement blocker checks: {', '.join(sorted(missing_checks))}")
    for name in required_checks:
        check = checks.get(name)
        if not isinstance(check, dict):
            raise ValueError(f"shell retirement blocker {name} must be an object")
        if not isinstance(check.get("passed"), bool):
            raise ValueError(f"shell retirement blocker {name}.passed must be a boolean")
        details = check.get("details")
        if not isinstance(details, list) or not all(isinstance(item, str) for item in details):
            raise ValueError(f"shell retirement blocker {name}.details must be a list of strings")


def default_timestamp() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()
