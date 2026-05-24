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
            "config.py",
            "constants.py",
            "launch.py",
            "models.py",
            "omx_transport.py",
            "recovery.py",
            "superset_transport.py",
            "terminal_screen.py",
            "tmux_transport.py",
            "workflow.py",
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
            "workflow.py": {
                "_workflow_step_prompt_text",
                "_resolve_preset_submission_text",
                "_shape_prompt_text",
                "_runtime_addresses_prompt_section",
                "_codex_goal_text_for_worktree",
                "_emit_codex_goal_event",
                "_wrap_omx_initial_prompt_for_workflow",
            },
            "terminal_screen.py": {
                "_screen_looks_ready",
                "_codex_queue_screen_looks_ready",
                "_codex_queue_message_needs_tab",
            },
            "tmux_transport.py": {
                "_tmux_session_name_for_worktree",
                "_run_tmux_worktree_bootstrap",
                "_queue_tmux_codex_workflow_steps",
            },
            "cmux_transport.py": {
                "_prepare_surface",
                "_ensure_workspace_id",
                "launch_review_agent_terminal",
            },
            "cmux_surface_support.py": {
                "prepare_surface",
                "run_cmux_command",
                "send_surface_key",
            },
            "cmux_workflow_submission_support.py": {
                "queue_codex_workflow_steps",
                "submit_direct_prompt_workflow_step",
                "submit_prompt_workflow_step",
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
            "superset_transport.py": {
                "_launch_plan_agent_superset_workspaces",
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
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
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
