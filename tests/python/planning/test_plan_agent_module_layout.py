import ast
import importlib
from pathlib import Path
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]
ENGINE_ROOT = REPO_ROOT / "python" / "envctl_engine"
PLAN_AGENT_ROOT = REPO_ROOT / "python" / "envctl_engine" / "planning" / "plan_agent"
FACADE = REPO_ROOT / "python" / "envctl_engine" / "planning" / "plan_agent_launch_support.py"

PUBLIC_FACADE_NAMES = {
    "AgentTerminalLaunchResult",
    "AiCliReadyResult",
    "CreatedPlanWorktree",
    "PlanAgentAttachTarget",
    "PlanAgentAttachValidation",
    "PlanAgentLaunchConfig",
    "PlanAgentLaunchOutcome",
    "PlanAgentLaunchResult",
    "PlanSelectionResult",
    "PlanWorktreeSyncResult",
    "ReviewAgentLaunchReadiness",
    "attach_plan_agent_terminal",
    "inspect_plan_agent_launch",
    "launch_plan_agent_terminals",
    "launch_review_agent_terminal",
    "plan_agent_launch_prereq_commands",
    "plan_agent_native_recovery_command",
    "resolve_plan_agent_launch_command",
    "resolve_plan_agent_launch_config",
    "review_agent_launch_readiness",
    "validate_plan_agent_attach_target",
}


class PlanAgentModuleLayoutTests(unittest.TestCase):
    def test_plan_agent_package_modules_exist(self) -> None:
        expected = {
            "__init__.py",
            "cmux_transport.py",
            "cmux_bootstrap_support.py",
            "cmux_goal_support.py",
            "cmux_worktree_launch_support.py",
            "cmux_review_launch_support.py",
            "config.py",
            "constants.py",
            "launch.py",
            "models.py",
            "omx_attach_support.py",
            "omx_lock_support.py",
            "omx_spawn_support.py",
            "omx_launch_support.py",
            "omx_transport.py",
            "omx_validation_support.py",
            "recovery.py",
            "superset_desktop_support.py",
            "superset_transport.py",
            "terminal_screen.py",
            "tmux_surface_support.py",
            "tmux_identity_support.py",
            "tmux_attach_support.py",
            "tmux_window_support.py",
            "tmux_health_support.py",
            "tmux_worktree_launch_support.py",
            "tmux_launch_support.py",
            "tmux_transport.py",
            "workflow.py",
            "workflow_build.py",
            "workflow_prompt_support.py",
            "workflow_queue_support.py",
        }
        actual = {path.name for path in PLAN_AGENT_ROOT.glob("*.py")}
        self.assertTrue(expected.issubset(actual))

    def test_legacy_module_is_small_compatibility_facade(self) -> None:
        text = FACADE.read_text(encoding="utf-8")
        self.assertLessEqual(len(text.splitlines()), 80)
        self.assertIn("__all__", text)
        self.assertNotIn("sys.modules[__name__]", text)

    def test_legacy_import_surface_is_public_reexport_layer(self) -> None:
        legacy = importlib.import_module("envctl_engine.planning.plan_agent_launch_support")
        launch = importlib.import_module("envctl_engine.planning.plan_agent.launch")
        self.assertIsNot(legacy, launch)
        self.assertEqual(PUBLIC_FACADE_NAMES, set(legacy.__all__))
        for name in PUBLIC_FACADE_NAMES:
            self.assertTrue(hasattr(legacy, name), name)
        private_exports = sorted(
            name
            for name in dir(legacy)
            if name.startswith("_") and not (name.startswith("__") and name.endswith("__"))
        )
        self.assertEqual([], private_exports)

    def test_launch_module_does_not_mirror_private_owner_symbols(self) -> None:
        text = (PLAN_AGENT_ROOT / "launch.py").read_text(encoding="utf-8")
        for forbidden in (
            "_PATCH_MIRROR_MODULES",
            "_export_owner_symbols",
            "_PlanAgentLaunchModule",
            "sys.modules[__name__].__class__",
        ):
            self.assertNotIn(forbidden, text)

    def test_production_modules_do_not_import_private_names_from_legacy_facade(self) -> None:
        violations: list[str] = []
        for path in ENGINE_ROOT.rglob("*.py"):
            if path == FACADE:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                if node.module != "envctl_engine.planning.plan_agent_launch_support":
                    continue
                for alias in node.names:
                    if alias.name.startswith("_"):
                        violations.append(f"{path.relative_to(REPO_ROOT)}: imports {alias.name}")
        self.assertEqual([], violations)

    def test_transport_modules_do_not_import_legacy_facade_or_each_other(self) -> None:
        transport_modules = {
            "cmux_transport.py",
            "omx_transport.py",
            "superset_transport.py",
            "tmux_transport.py",
        }
        violations: list[str] = []
        for filename in transport_modules:
            path = PLAN_AGENT_ROOT / filename
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                module = ""
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        name = alias.name
                        if name == "envctl_engine.planning.plan_agent_launch_support":
                            violations.append(f"{filename}: import legacy facade")
                        if name.startswith("envctl_engine.planning.plan_agent.") and name.rsplit(".", 1)[-1] in {
                            "cmux_transport",
                            "omx_transport",
                            "tmux_transport",
                        }:
                            violations.append(f"{filename}: import peer transport {name}")
                    continue
                if module == "envctl_engine.planning.plan_agent_launch_support":
                    violations.append(f"{filename}: import legacy facade")
                if module.startswith("envctl_engine.planning.plan_agent."):
                    peer = f"{module.rsplit('.', 1)[-1]}.py"
                    if peer in transport_modules:
                        violations.append(f"{filename}: import peer transport {module}")
                if isinstance(node, ast.Call):
                    call_name = ""
                    if isinstance(node.func, ast.Name):
                        call_name = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        call_name = node.func.attr
                    if call_name in {"import_module", "get"}:
                        for arg in node.args[:1]:
                            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                                value = arg.value
                                if value.startswith("envctl_engine.planning.plan_agent."):
                                    peer = f"{value.rsplit('.', 1)[-1]}.py"
                                    if peer in transport_modules:
                                        violations.append(f"{filename}: dynamic peer transport lookup {value}")
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    value = node.value
                    if value.startswith("envctl_engine.planning.plan_agent."):
                        peer = f"{value.rsplit('.', 1)[-1]}.py"
                        if peer in transport_modules:
                            violations.append(f"{filename}: string peer transport reference {value}")
        self.assertEqual([], violations)

    def test_launch_module_owns_public_dispatch_functions(self) -> None:
        launch_path = PLAN_AGENT_ROOT / "launch.py"
        text = launch_path.read_text(encoding="utf-8")
        self.assertLessEqual(len(text.splitlines()), 1500)
        tree = ast.parse(text, filename=str(launch_path))
        defs = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for name in (
            "inspect_plan_agent_launch",
            "launch_plan_agent_terminals",
        ):
            self.assertIn(name, defs)

    def test_core_helpers_live_in_owner_modules(self) -> None:
        expected = {
            "config.py": {
                "_parse_codex_cycles",
                "resolve_plan_agent_launch_config",
                "plan_agent_launch_prereq_commands",
            },
            "workflow_build.py": {
                "_build_plan_agent_workflow",
                "_browser_e2e_instruction_text",
                "_finalization_instruction_text",
                "_slash_command",
                "_tab_title_for_worktree",
                "PlanAgentWorkflowBuilder",
            },
            "workflow_prompt_support.py": {
                "_workflow_step_prompt_text",
                "_resolve_preset_submission_text",
                "_shape_prompt_text",
                "_runtime_addresses_prompt_section",
            },
            "workflow.py": {
                "_codex_goal_text_for_worktree",
                "_emit_codex_goal_event",
                "_wrap_omx_initial_prompt_for_workflow",
            },
            "workflow_queue_support.py": {
                "run_codex_workflow_queue",
            },
            "terminal_screen.py": {
                "_screen_looks_ready",
                "_codex_queue_screen_looks_ready",
                "_codex_queue_message_needs_tab",
            },
            "tmux_identity_support.py": {
                "next_available_tmux_session_name",
                "tmux_session_name_for_worktree",
                "tmux_window_name_for_worktree",
            },
            "tmux_attach_support.py": {
                "find_existing_tmux_attach_target",
                "resolve_tmux_attach_target",
            },
            "tmux_window_support.py": {
                "enable_tmux_mouse_scrollback",
                "ensure_tmux_window",
                "tmux_window_exists",
                "wait_for_tmux_window_ready",
            },
            "tmux_health_support.py": {
                "existing_tmux_session_health",
                "existing_tmux_session_looks_healthy",
            },
            "tmux_worktree_launch_support.py": {
                "launch_single_tmux_worktree",
            },
            "tmux_launch_support.py": {
                "launch_tmux_terminals",
            },
            "tmux_transport.py": {
                "_run_tmux_worktree_bootstrap",
            },
            "tmux_workflow_submission_support.py": {
                "launch_tmux_cli_bootstrap_commands",
                "maybe_submit_tmux_codex_goal",
                "queue_tmux_codex_message",
                "queue_tmux_codex_workflow_steps",
                "run_existing_tmux_session_workflow",
                "run_tmux_worktree_bootstrap",
                "submit_tmux_codex_goal",
                "submit_tmux_prompt_workflow_step",
                "wait_for_tmux_cli_ready",
                "wait_for_tmux_prompt_accepted",
                "wait_for_tmux_prompt_ready_after_goal",
            },
            "tmux_surface_support.py": {
                "read_tmux_screen",
                "run_tmux_command",
                "send_tmux_key",
                "send_tmux_prompt",
                "send_tmux_text",
                "tmux_target",
            },
            "cmux_transport.py": {
                "launch_review_agent_terminal",
            },
            "cmux_surface_support.py": {
                "create_surface",
                "prepare_surface",
                "run_cmux_command",
                "send_surface_key",
            },
            "cmux_bootstrap_support.py": {
                "complete_review_surface_bootstrap",
                "complete_surface_bootstrap",
                "run_review_surface_bootstrap",
                "run_surface_bootstrap",
                "start_background_review_surface_bootstrap",
                "start_background_surface_bootstrap",
            },
            "cmux_workflow_submission_support.py": {
                "launch_cli_bootstrap_commands",
                "queue_codex_workflow_steps",
                "submit_direct_prompt_workflow_step",
                "submit_prompt_workflow_step",
            },
            "cmux_goal_support.py": {
                "maybe_submit_surface_codex_goal",
                "submit_surface_codex_goal",
                "wait_for_surface_codex_goal_active",
            },
            "cmux_worktree_launch_support.py": {
                "launch_single_worktree",
            },
            "cmux_review_launch_support.py": {
                "launch_cmux_review_agent_terminal",
                "resolve_review_agent_launch_readiness",
            },
            "cmux_workspace_support.py": {
                "ensure_workspace_id",
                "workspace_entries_from_list_output",
                "surface_ids_from_list_output",
            },
            "omx_transport.py": {
                "_spawn_omx_session_for_worktree",
                "_find_existing_omx_attach_target",
                "validate_plan_agent_attach_target",
            },
            "omx_attach_support.py": {
                "attach_discovery_diagnostics",
                "attach_target_from_omx_record",
                "attach_target_from_omx_tmux_pane_fallback",
                "attach_target_state_check",
                "combined_omx_tmux_exclusions",
                "find_existing_omx_attach_target",
                "find_omx_tmux_panes_for_worktree",
                "omx_payload_candidates",
                "omx_session_records_for_worktree",
                "omx_session_state_path",
                "omx_session_state_path_for_root",
                "omx_worktree_tmux_prefixes",
                "previous_omx_tmux_session_names_for_worktree",
                "read_omx_session_id",
                "read_omx_session_ids",
                "read_omx_session_payload",
                "read_omx_session_payload_for_worktree",
                "read_omx_session_payload_from_path",
                "read_omx_session_payload_from_root",
                "record_cwd_matches_worktree",
                "wait_for_omx_attach_target",
            },
            "omx_lock_support.py": {
                "cleanup_stale_omx_tmux_locks",
                "cleanup_stale_omx_tmux_locks_under_root",
            },
            "omx_spawn_support.py": {
                "bounded_process_output_excerpt",
                "deterministic_omx_root_for_worktree",
                "omx_launch_env",
                "omx_spawn_failure_text",
                "omx_spawn_metadata_payload",
                "retain_omx_spawn_process",
                "retained_omx_spawn_event_payload",
                "retained_omx_spawn_process",
                "retained_omx_spawn_returncode",
                "sanitize_omx_tmux_token",
                "spawn_omx_session_for_worktree",
                "utc_timestamp_from_epoch",
            },
            "omx_validation_support.py": {
                "omx_late_spawn_exit_reason",
                "validate_omx_attach_target",
            },
            "omx_launch_support.py": {
                "launch_omx_terminals",
            },
            "superset_transport.py": {
                "_launch_plan_agent_superset_workspaces",
            },
            "superset_worktree_launch_support.py": {
                "launch_single_superset_worktree",
            },
            "superset_desktop_support.py": {
                "bridge_superset_desktop_workspace",
                "parse_superset_json_output",
                "print_superset_outcome_details",
                "restart_superset_desktop",
                "superset_completed_process_error_text",
                "verify_superset_desktop_workspace",
                "workspace_id_from_superset_payload",
                "workspace_payload_from_superset_payload",
            },
            "recovery.py": {
                "plan_agent_native_recovery_command",
                "_new_session_command_for_route",
                "_plan_selector_for_route",
                "_queue_failure_event_context",
            },
        }
        definitions: dict[str, set[str]] = {}
        for path in PLAN_AGENT_ROOT.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            definitions[path.name] = {
                node.name
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            }
        for filename, names in expected.items():
            missing = sorted(names - definitions.get(filename, set()))
            self.assertEqual([], missing, filename)
            for other_filename, other_defs in definitions.items():
                if other_filename == filename:
                    continue
                duplicates = sorted(names & other_defs)
                self.assertEqual([], duplicates, f"{filename} ownership duplicated in {other_filename}")

    def test_no_placeholder_extraction_modules_remain(self) -> None:
        for filename in ("config.py", "constants.py", "recovery.py"):
            text = (PLAN_AGENT_ROOT / filename).read_text(encoding="utf-8")
            self.assertNotIn("Extracted in later mechanical waves", text)
            self.assertNotIn("Constants stay in launch", text)


if __name__ == "__main__":
    unittest.main()
