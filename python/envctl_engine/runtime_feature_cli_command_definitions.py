from __future__ import annotations

# This module is a data owner for long generated-contract prose. Keep the text
# stable for contract generation; line wrapping would make the table harder to
# audit than the intentional long strings.
# ruff: noqa: E501

from envctl_engine.runtime_feature_definition_schema import FeatureDefinition


CLI_COMMAND_DEFINITIONS: dict[str, FeatureDefinition] = {
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
    "migrate-hooks": FeatureDefinition(
        area="cli",
        feature="Command: migrate legacy shell hook functions into a Python .envctl_hooks.py module",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/shared/hooks.py",
            "python/envctl_engine/runtime/engine_runtime_cli_support.py",
            "python/envctl_engine/runtime/engine_runtime.py",
        ),
        evidence_tests=("tests/python/startup/test_hooks_bridge.py",),
        parity_status="verified_python",
        notes="Hook migration is Python-owned and provides an explicit path away from executable shell hooks.",
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
        proposed_tests=("tests/python/runtime/test_cli_router.py",),
        severity="medium",
        rollout_risk="Help text drift creates immediate confusion for installation and first-run workflows.",
        wave="Wave A",
    ),
    "list-commands": FeatureDefinition(
        area="cli",
        feature="Command: print the supported command inventory",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=("python/envctl_engine/runtime/command_router.py",),
        evidence_tests=("tests/python/runtime/test_engine_runtime_command_parity.py",),
        parity_status="verified_python",
        notes="List-commands is explicitly parity-tested against the shell inventory.",
    ),
    "install-prompts": FeatureDefinition(
        area="cli",
        feature="Command: install envctl-managed AI CLI prompt presets into user-local directories",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/runtime/command_router.py",
            "python/envctl_engine/runtime/prompt_install_support.py",
            "python/envctl_engine/runtime/engine_runtime_dispatch.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_prompt_install_support.py",
            "tests/python/runtime/test_engine_runtime_command_parity.py",
        ),
        parity_status="verified_python",
        notes="Install-prompts is Python-owned and intentionally excluded from dashboard interactive command entry.",
    ),
    "codex-tmux": FeatureDefinition(
        area="cli",
        feature="Command: launch or reuse the dedicated Codex tmux session for repo-local workflows",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/runtime/command_router.py",
            "python/envctl_engine/runtime/codex_tmux_support.py",
            "python/envctl_engine/runtime/utility_command_support.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_codex_tmux_support.py",
            "tests/python/runtime/test_engine_runtime_command_parity.py",
            "tests/python/runtime/test_command_exit_codes.py",
        ),
        parity_status="verified_python",
        notes="Codex tmux session launch and reuse are Python-owned utility flows with dedicated routing and subprocess coverage.",
    ),
    "ensure-worktree": FeatureDefinition(
        area="cli",
        feature="Command: create or reuse a single envctl-managed worktree without runtime startup",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/runtime/command_router.py",
            "python/envctl_engine/runtime/ensure_worktree_support.py",
            "python/envctl_engine/runtime/utility_command_support.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_ensure_worktree_command.py",
            "tests/python/runtime/test_engine_runtime_command_parity.py",
            "tests/python/runtime/test_command_dispatch_matrix.py",
        ),
        parity_status="verified_python",
        notes="Ensure-worktree is Python-owned and intentionally reuses existing planning/worktree creation mechanics without starting runtime services.",
    ),
    "supabase-user": FeatureDefinition(
        area="cli",
        feature="Command: manage Supabase Auth users for local E2E and explicit Admin API operations",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/runtime/command_router.py",
            "python/envctl_engine/runtime/command_policy.py",
            "python/envctl_engine/runtime/supabase_user_command_support.py",
            "python/envctl_engine/runtime/utility_command_support.py",
            "python/envctl_engine/requirements/supabase_auth_users.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_cli_router.py",
            "tests/python/runtime/test_command_exit_codes.py",
            "tests/python/runtime/test_supabase_user_command_support.py",
            "tests/python/runtime/test_engine_runtime_command_parity.py",
            "tests/python/requirements/test_supabase_auth_users.py",
        ),
        parity_status="verified_python",
        notes="Supabase Auth user management is Python-owned through the utility dispatcher and the dependency-free Auth Admin client.",
    ),
    "qa-user": FeatureDefinition(
        area="cli",
        feature="Command: ensure deterministic QA Auth users for an active project",
        user_visible=True,
        shell_source_of_truth=(),
        python_source_of_truth=(
            "python/envctl_engine/runtime/command_router.py",
            "python/envctl_engine/runtime/qa_user_command_support.py",
            "python/envctl_engine/runtime/supabase_user_command_support.py",
            "python/envctl_engine/state/project_runtime.py",
        ),
        evidence_tests=(
            "tests/python/runtime/test_qa_user_command_support.py",
            "tests/python/runtime/test_cli_router_parity.py",
            "tests/python/runtime/test_qa_user_supabase_smoke.py",
        ),
        parity_status="verified_python",
        notes="QA user ensure is Python-owned, scopes Supabase Auth operations through the active project runtime resolver, writes redacted artifacts/events, and mutates existing users only with explicit update flags.",
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
