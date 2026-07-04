from pathlib import Path
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]


class StructureLayoutTests(unittest.TestCase):
    def test_python_domain_directories_exist(self) -> None:
        expected = [
            "python/envctl_engine/actions",
            "python/envctl_engine/config",
            "python/envctl_engine/debug",
            "python/envctl_engine/planning",
            "python/envctl_engine/requirements",
            "python/envctl_engine/runtime",
            "python/envctl_engine/shared",
            "python/envctl_engine/startup",
            "python/envctl_engine/state",
            "python/envctl_engine/ui/dashboard",
            "python/envctl_engine/ui/textual/screens/selector",
        ]
        for rel in expected:
            self.assertTrue((REPO_ROOT / rel).is_dir(), rel)

    def test_test_domain_directories_exist(self) -> None:
        expected = [
            "tests/python/actions",
            "tests/python/config",
            "tests/python/debug",
            "tests/python/planning",
            "tests/python/requirements",
            "tests/python/runtime",
            "tests/python/shared",
            "tests/python/startup",
            "tests/python/state",
            "tests/python/test_output",
            "tests/python/ui",
        ]
        for rel in expected:
            self.assertTrue((REPO_ROOT / rel).is_dir(), rel)

    def test_shell_runtime_tree_is_absent(self) -> None:
        self.assertFalse((REPO_ROOT / "lib" / "engine" / "lib").exists())
        self.assertFalse((REPO_ROOT / "lib" / "engine" / "main.sh").exists())
        self.assertFalse((REPO_ROOT / "lib" / "envctl.sh").exists())

    def test_obsolete_breadcrumb_test_suites_are_removed(self) -> None:
        obsolete = [
            "tests/python/actions/test_actions_cli.py",
            "tests/python/planning/test_plan_agent_launch_cmux.py",
            "tests/python/planning/test_plan_agent_launch_cmux_workspace.py",
            "tests/python/planning/test_plan_agent_launch_omx.py",
            "tests/python/planning/test_plan_agent_launch_omx_attach.py",
            "tests/python/planning/test_plan_agent_launch_options.py",
            "tests/python/planning/test_plan_agent_launch_support.py",
            "tests/python/planning/test_plan_agent_launch_tmux.py",
            "tests/python/planning/test_plan_agent_launch_workflow.py",
            "tests/python/planning/test_planning_worktree_setup.py",
            "tests/python/requirements/test_requirements_adapters_real_contracts.py",
            "tests/python/requirements/test_requirements_supabase_stack_contracts.py",
            "tests/python/runtime/test_engine_runtime_command_parity.py",
            "tests/python/runtime/test_engine_runtime_env.py",
            "tests/python/runtime/test_lifecycle_parity.py",
            "tests/python/runtime/test_lifecycle_parity_resume_restore.py",
            "tests/python/runtime/test_prompt_install_support.py",
            "tests/python/startup/test_startup_orchestrator_flow.py",
            "tests/python/startup/test_startup_spinner_integration.py",
            "tests/python/ui/test_dashboard_orchestrator_pr_flow.py",
            "tests/python/ui/test_dashboard_orchestrator_restart_selector.py",
            "tests/python/ui/test_dashboard_orchestrator_target_selection.py",
            "tests/python/ui/test_dashboard_rendering_parity.py",
        ]

        for relative_path in obsolete:
            with self.subTest(path=relative_path):
                self.assertFalse((REPO_ROOT / relative_path).exists())

    def test_bats_harness_is_absent(self) -> None:
        self.assertFalse((REPO_ROOT / "tests" / "bats").exists())

    def test_removed_dead_leaf_modules_are_absent(self) -> None:
        stale_modules = [
            "python/envctl_engine/test_output/coverage.py",
            "python/envctl_engine/test_output/error_extractor.py",
            "python/envctl_engine/test_output/mode_handler.py",
            "python/envctl_engine/test_output/multi_project_runner.py",
            "python/envctl_engine/ui/input_adapter.py",
            "python/envctl_engine/ui/textual/screens/dashboard.py",
            "python/envctl_engine/ui/textual/widgets/service_table.py",
        ]

        for rel in stale_modules:
            with self.subTest(path=rel):
                self.assertFalse((REPO_ROOT / rel).exists())

        # These low-inbound modules are intentional string entry points or
        # compatibility facades and must not be swept up by this guard.
        retained_entrypoints = [
            "python/envctl_engine/test_output/pytest_progress_plugin.py",
            "python/envctl_engine/test_output/unittest_runner.py",
            "python/envctl_engine/ui/textual/selector_subprocess_entry.py",
            "python/envctl_engine/ui/textual/screens/selector/implementation.py",
        ]
        for rel in retained_entrypoints:
            with self.subTest(path=rel):
                self.assertTrue((REPO_ROOT / rel).is_file())

    def test_python_engine_architecture_inventory_exists(self) -> None:
        inventory = REPO_ROOT / "docs" / "reference" / "python-engine-architecture.md"

        self.assertTrue(inventory.is_file())
