import ast
import importlib
from pathlib import Path
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]
PLAN_AGENT_ROOT = REPO_ROOT / "python" / "envctl_engine" / "planning" / "plan_agent"
FACADE = REPO_ROOT / "python" / "envctl_engine" / "planning" / "plan_agent_launch_support.py"


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
            "terminal_screen.py",
            "tmux_transport.py",
            "workflow.py",
        }
        actual = {path.name for path in PLAN_AGENT_ROOT.glob("*.py")}
        self.assertTrue(expected.issubset(actual))

    def test_legacy_module_is_small_compatibility_facade(self) -> None:
        text = FACADE.read_text(encoding="utf-8")
        self.assertLessEqual(len(text.splitlines()), 80)
        self.assertIn("envctl_engine.planning.plan_agent.launch", text)

    def test_legacy_import_surface_uses_launch_module_identity(self) -> None:
        legacy = importlib.import_module("envctl_engine.planning.plan_agent_launch_support")
        launch = importlib.import_module("envctl_engine.planning.plan_agent.launch")
        self.assertIs(legacy, launch)

    def test_transport_modules_do_not_import_legacy_facade_or_each_other(self) -> None:
        transport_modules = {
            "cmux_transport.py",
            "omx_transport.py",
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
            "omx_transport.py": {
                "_spawn_omx_session_for_worktree",
                "_find_existing_omx_attach_target",
                "validate_plan_agent_attach_target",
            },
            "recovery.py": {
                "plan_agent_native_recovery_command",
                "_new_session_command_for_route",
                "_plan_selector_for_route",
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
