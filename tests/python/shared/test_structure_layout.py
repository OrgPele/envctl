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

    def test_worktree_code_intelligence_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_code_intelligence.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_domain.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.planning.worktree_code_intelligence import",
            facade.read_text(encoding="utf-8"),
        )

    def test_worktree_provenance_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_provenance.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_domain.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.planning.worktree_provenance import",
            facade.read_text(encoding="utf-8"),
        )

    def test_worktree_git_hooks_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_git_hooks.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_domain.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.planning.worktree_git_hooks import",
            facade.read_text(encoding="utf-8"),
        )

    def test_worktree_main_task_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_main_task.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_domain.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.planning.worktree_main_task import",
            facade.read_text(encoding="utf-8"),
        )

    def test_worktree_selection_memory_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_selection_memory.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_domain.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.planning.worktree_selection_memory import",
            facade.read_text(encoding="utf-8"),
        )

    def test_worktree_project_catalog_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_project_catalog.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_domain.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.planning.worktree_project_catalog import",
            facade.read_text(encoding="utf-8"),
        )

    def test_worktree_shared_artifacts_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_shared_artifacts.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_domain.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.planning.worktree_shared_artifacts import",
            facade.read_text(encoding="utf-8"),
        )

    def test_worktree_creation_recovery_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_creation_recovery.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_domain.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.planning.worktree_creation_recovery import",
            facade.read_text(encoding="utf-8"),
        )

    def test_worktree_creation_commands_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_creation_commands.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_domain.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.planning.worktree_creation_commands import",
            facade.read_text(encoding="utf-8"),
        )

    def test_worktree_plan_selection_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_plan_selection.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_domain.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.planning.worktree_plan_selection import",
            facade.read_text(encoding="utf-8"),
        )

    def test_worktree_plan_project_selection_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_plan_project_selection.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_domain.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.planning.worktree_plan_project_selection import",
            facade.read_text(encoding="utf-8"),
        )

    def test_worktree_prompt_selection_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_prompt_selection.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_domain.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.planning.worktree_prompt_selection import",
            facade.read_text(encoding="utf-8"),
        )

    def test_worktree_planning_menu_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_planning_menu.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_domain.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.planning.worktree_planning_menu import",
            facade.read_text(encoding="utf-8"),
        )

    def test_worktree_setup_entries_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_setup_entries.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_domain.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.planning.worktree_setup_entries import",
            facade.read_text(encoding="utf-8"),
        )

    def test_worktree_setup_coordinator_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_setup_coordinator.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_domain.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.planning.worktree_setup_coordinator import",
            facade.read_text(encoding="utf-8"),
        )

    def test_worktree_sync_deletion_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_sync_deletion.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_domain.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.planning.worktree_sync_deletion import",
            facade.read_text(encoding="utf-8"),
        )

    def test_worktree_sync_orchestration_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_sync_orchestration.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_domain.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.planning.worktree_sync_orchestration import",
            facade.read_text(encoding="utf-8"),
        )

    def test_worktree_identity_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_identity.py"
        creation_commands = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_creation_commands.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.planning.worktree_identity import",
            creation_commands.read_text(encoding="utf-8"),
        )

    def test_python_engine_architecture_inventory_exists(self) -> None:
        inventory = REPO_ROOT / "docs" / "reference" / "python-engine-architecture.md"

        self.assertTrue(inventory.is_file())

    def test_engine_runtime_action_support_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime_action_support.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.runtime.engine_runtime_action_support import",
            facade.read_text(encoding="utf-8"),
        )

    def test_repo_local_launcher_is_python_script(self) -> None:
        launcher = REPO_ROOT / "bin" / "envctl"
        self.assertTrue(launcher.is_file())
        text = launcher.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("#!/usr/bin/env python3"))


if __name__ == "__main__":
    unittest.main()
