import ast
from pathlib import Path
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]
ENGINE_ROOT = REPO_ROOT / "python" / "envctl_engine"

DEPRECATED_IMPORTS = {
    "envctl_engine.action_command_orchestrator",
    "envctl_engine.action_command_support",
    "envctl_engine.action_target_support",
    "envctl_engine.action_test_runner",
    "envctl_engine.action_test_support",
    "envctl_engine.action_utils",
    "envctl_engine.action_worktree_runner",
    "envctl_engine.actions_analysis",
    "envctl_engine.actions_cli",
    "envctl_engine.actions_git",
    "envctl_engine.actions_test",
    "envctl_engine.actions_worktree",
    "envctl_engine.cli",
    "envctl_engine.command_resolution",
    "envctl_engine.command_router",
    "envctl_engine.config_command_support",
    "envctl_engine.config_persistence",
    "envctl_engine.config_wizard_domain",
    "envctl_engine.dashboard_orchestrator",
    "envctl_engine.dashboard_rendering_domain",
    "envctl_engine.debug_bundle",
    "envctl_engine.debug_contract",
    "envctl_engine.debug_utils",
    "envctl_engine.dependency_compose_assets",
    "envctl_engine.doctor_orchestrator",
    "envctl_engine.engine_runtime",
    "envctl_engine.engine_runtime_artifacts",
    "envctl_engine.engine_runtime_commands",
    "envctl_engine.engine_runtime_dashboard_truth",
    "envctl_engine.engine_runtime_debug_support",
    "envctl_engine.engine_runtime_diagnostics",
    "envctl_engine.engine_runtime_dispatch",
    "envctl_engine.engine_runtime_env",
    "envctl_engine.engine_runtime_event_support",
    "envctl_engine.engine_runtime_hooks",
    "envctl_engine.engine_runtime_lifecycle_support",
    "envctl_engine.engine_runtime_misc_support",
    "envctl_engine.engine_runtime_runtime_support",
    "envctl_engine.engine_runtime_service_policy",
    "envctl_engine.engine_runtime_service_truth",
    "envctl_engine.engine_runtime_startup_support",
    "envctl_engine.engine_runtime_state_lookup",
    "envctl_engine.engine_runtime_state_support",
    "envctl_engine.engine_runtime_state_truth",
    "envctl_engine.engine_runtime_ui_bridge",
    "envctl_engine.env_access",
    "envctl_engine.hooks",
    "envctl_engine.lifecycle_cleanup_orchestrator",
    "envctl_engine.models",
    "envctl_engine.node_tooling",
    "envctl_engine.parsing",
    "envctl_engine.planning_menu",
    "envctl_engine.ports",
    "envctl_engine.process_probe",
    "envctl_engine.process_runner",
    "envctl_engine.project_action_domain",
    "envctl_engine.protocols",
    "envctl_engine.reason_codes",
    "envctl_engine.release_gate",
    "envctl_engine.requirements_orchestrator",
    "envctl_engine.requirements_startup_domain",
    "envctl_engine.resume_orchestrator",
    "envctl_engine.runtime_context",
    "envctl_engine.runtime_map",
    "envctl_engine.service_bootstrap_domain",
    "envctl_engine.service_manager",
    "envctl_engine.services",
    "envctl_engine.shell_adapter",
    "envctl_engine.startup_orchestrator",
    "envctl_engine.state_action_orchestrator",
    "envctl_engine.state_repository",
    "envctl_engine.terminal_ui",
    "envctl_engine.worktree_planning_domain",
}

PACKAGE_ROOTS = [
    ENGINE_ROOT / "actions",
    ENGINE_ROOT / "config",
    ENGINE_ROOT / "debug",
    ENGINE_ROOT / "planning",
    ENGINE_ROOT / "runtime",
    ENGINE_ROOT / "shared",
    ENGINE_ROOT / "startup",
    ENGINE_ROOT / "state",
    ENGINE_ROOT / "ui" / "dashboard",
    ENGINE_ROOT / "ui" / "textual" / "screens" / "selector",
]

OWNERSHIP_RULES = {
    "textual_importable": {ENGINE_ROOT / "ui" / "capabilities.py"},
    "prompt_toolkit_disabled": {ENGINE_ROOT / "ui" / "capabilities.py"},
    "prompt_toolkit_selector_enabled": {ENGINE_ROOT / "ui" / "capabilities.py"},
    "interactive_selection_allowed": {ENGINE_ROOT / "ui" / "selection_support.py"},
    "project_names_from_state": {ENGINE_ROOT / "ui" / "selection_support.py"},
    "services_from_selection": {ENGINE_ROOT / "ui" / "selection_support.py"},
    "sanitize_interactive_input": {
        ENGINE_ROOT / "ui" / "command_parsing.py",
        ENGINE_ROOT / "runtime" / "engine_runtime_ui_bridge.py",
        ENGINE_ROOT / "ui" / "dashboard" / "command_support.py",
        ENGINE_ROOT / "ui" / "dashboard" / "command_input_support.py",
    },
    "recover_single_letter_command_from_escape_fragment": {
        ENGINE_ROOT / "ui" / "command_parsing.py",
        ENGINE_ROOT / "runtime" / "engine_runtime_ui_bridge.py",
        ENGINE_ROOT / "ui" / "dashboard" / "command_support.py",
        ENGINE_ROOT / "ui" / "dashboard" / "command_input_support.py",
    },
    "parse_interactive_command": {
        ENGINE_ROOT / "ui" / "command_parsing.py",
        ENGINE_ROOT / "runtime" / "engine_runtime_ui_bridge.py",
        ENGINE_ROOT / "ui" / "dashboard" / "command_support.py",
        ENGINE_ROOT / "ui" / "dashboard" / "command_input_support.py",
    },
    "tokens_set_mode": {
        ENGINE_ROOT / "ui" / "command_parsing.py",
        ENGINE_ROOT / "runtime" / "engine_runtime_misc_support.py",
        ENGINE_ROOT / "ui" / "dashboard" / "command_support.py",
        ENGINE_ROOT / "ui" / "dashboard" / "command_input_support.py",
    },
    "_textual_importable": {
        ENGINE_ROOT / "ui" / "textual" / "screens" / "selector" / "support.py",
    },
    "_prompt_toolkit_disabled": set(),
    "_interactive_selection_allowed": {
        ENGINE_ROOT / "actions" / "action_command_orchestrator.py",
        ENGINE_ROOT / "runtime" / "lifecycle_cleanup_orchestrator.py",
        ENGINE_ROOT / "state" / "action_orchestrator.py",
    },
    "_project_names_from_state": {
        ENGINE_ROOT / "runtime" / "lifecycle_cleanup_orchestrator.py",
        ENGINE_ROOT / "state" / "action_orchestrator.py",
        ENGINE_ROOT / "state" / "repository.py",
        ENGINE_ROOT / "ui" / "dashboard" / "orchestrator.py",
        ENGINE_ROOT / "ui" / "dashboard" / "orchestrator_target_mixin.py",
    },
    "_services_from_selection": {
        ENGINE_ROOT / "runtime" / "lifecycle_cleanup_orchestrator.py",
        ENGINE_ROOT / "state" / "action_orchestrator.py",
    },
    "start_requirements_for_project": {
        ENGINE_ROOT / "startup" / "requirements_execution.py",
        ENGINE_ROOT / "startup" / "startup_orchestrator.py",
        ENGINE_ROOT / "startup" / "protocols.py",
    },
    "start_project_services": {
        ENGINE_ROOT / "startup" / "service_execution.py",
        ENGINE_ROOT / "startup" / "startup_orchestrator.py",
        ENGINE_ROOT / "startup" / "protocols.py",
    },
    "_screen_looks_ready": {
        ENGINE_ROOT / "planning" / "plan_agent" / "terminal_screen.py",
    },
    "_build_plan_agent_workflow": {
        ENGINE_ROOT / "planning" / "plan_agent" / "workflow.py",
        ENGINE_ROOT / "planning" / "plan_agent" / "workflow_build.py",
    },
    "_spawn_omx_session_for_worktree": {
        ENGINE_ROOT / "planning" / "plan_agent" / "omx_transport.py",
    },
    "_ensure_tmux_window": {
        ENGINE_ROOT / "planning" / "plan_agent" / "tmux_transport.py",
    },
    "_prepare_surface": {
        ENGINE_ROOT / "planning" / "plan_agent" / "cmux_transport.py",
    },
    "resolve_plan_agent_launch_config": {
        ENGINE_ROOT / "planning" / "plan_agent" / "config.py",
    },
    "plan_agent_launch_prereq_commands": {
        ENGINE_ROOT / "planning" / "plan_agent" / "config.py",
    },
    "_workflow_step_prompt_text": {
        ENGINE_ROOT / "planning" / "plan_agent" / "workflow.py",
        ENGINE_ROOT / "planning" / "plan_agent" / "workflow_prompt_support.py",
    },
    "_resolve_preset_submission_text": {
        ENGINE_ROOT / "planning" / "plan_agent" / "workflow.py",
        ENGINE_ROOT / "planning" / "plan_agent" / "workflow_prompt_support.py",
    },
    "_codex_queue_screen_looks_ready": {
        ENGINE_ROOT / "planning" / "plan_agent" / "terminal_screen.py",
    },
    "_tmux_session_name_for_worktree": {
        ENGINE_ROOT / "planning" / "plan_agent" / "tmux_transport.py",
    },
    "_run_tmux_worktree_bootstrap": {
        ENGINE_ROOT / "planning" / "plan_agent" / "tmux_transport.py",
    },
    "_ensure_workspace_id": {
        ENGINE_ROOT / "planning" / "plan_agent" / "cmux_transport.py",
    },
    "launch_review_agent_terminal": {
        ENGINE_ROOT / "planning" / "plan_agent" / "cmux_transport.py",
    },
    "_find_existing_omx_attach_target": {
        ENGINE_ROOT / "planning" / "plan_agent" / "omx_transport.py",
    },
    "validate_plan_agent_attach_target": {
        ENGINE_ROOT / "planning" / "plan_agent" / "omx_transport.py",
    },
    "plan_agent_native_recovery_command": {
        ENGINE_ROOT / "planning" / "plan_agent" / "recovery.py",
    },
    "_new_session_command_for_route": {
        ENGINE_ROOT / "planning" / "plan_agent" / "recovery.py",
    },
    "_codex_goal_text_for_worktree": {
        ENGINE_ROOT / "planning" / "plan_agent" / "workflow.py",
    },
    "_emit_codex_goal_event": {
        ENGINE_ROOT / "planning" / "plan_agent" / "workflow.py",
    },
    "_wrap_omx_initial_prompt_for_workflow": {
        ENGINE_ROOT / "planning" / "plan_agent" / "workflow.py",
    },
    "_queue_failure_event_context": {
        ENGINE_ROOT / "planning" / "plan_agent" / "recovery.py",
    },
}


class ImportAuditTests(unittest.TestCase):
    def test_domain_packages_do_not_depend_on_flat_shim_modules(self) -> None:
        violations: list[str] = []
        for package_root in PACKAGE_ROOTS:
            for path in package_root.rglob("*.py"):
                tree = ast.parse(path.read_text(), filename=str(path))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name in DEPRECATED_IMPORTS:
                                violations.append(f"{path}: import {alias.name}")
                    elif isinstance(node, ast.ImportFrom) and node.module in DEPRECATED_IMPORTS:
                        violations.append(f"{path}: from {node.module} import ...")
        self.assertEqual([], violations)

    def test_consolidated_helper_ownership_stays_in_approved_modules(self) -> None:
        violations: list[str] = []
        for path in ENGINE_ROOT.rglob("*.py"):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                allowed_paths = OWNERSHIP_RULES.get(node.name)
                if allowed_paths is None:
                    continue
                if path not in allowed_paths:
                    violations.append(f"{path}: def {node.name}")
        self.assertEqual([], violations)


if __name__ == "__main__":
    unittest.main()
