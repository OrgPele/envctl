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

    def test_supabase_startup_sequence_has_lifecycle_orchestrator(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "requirements" / "supabase_lifecycle" / "orchestrator.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "requirements" / "supabase.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.requirements.supabase_lifecycle.orchestrator import start_supabase_stack",
            facade.read_text(encoding="utf-8"),
        )

    def test_requirement_adapter_contract_tests_are_split_by_owner(self) -> None:
        requirements_tests = REPO_ROOT / "tests" / "python" / "requirements"
        expected = [
            "requirements_adapter_contract_support.py",
            "test_requirements_n8n_adapter_contracts.py",
            "test_requirements_postgres_adapter_contracts.py",
            "test_requirements_redis_adapter_contracts.py",
            "test_requirements_supabase_compose_contracts.py",
            "test_requirements_supabase_native_contracts.py",
            "test_requirements_supabase_stack_contracts.py",
            "test_requirements_supabase_stack_auth_contracts.py",
            "test_requirements_supabase_stack_core_contracts.py",
            "test_requirements_supabase_stack_db_probe_contracts.py",
            "test_requirements_supabase_stack_handoff_contracts.py",
            "test_requirements_supabase_stack_network_contracts.py",
        ]

        for filename in expected:
            with self.subTest(path=filename):
                self.assertTrue((requirements_tests / filename).is_file())

        legacy = requirements_tests / "test_requirements_adapters_real_contracts.py"
        self.assertLessEqual(len(legacy.read_text(encoding="utf-8").splitlines()), 20)
        legacy_stack = requirements_tests / "test_requirements_supabase_stack_contracts.py"
        self.assertLessEqual(len(legacy_stack.read_text(encoding="utf-8").splitlines()), 20)

    def test_action_cli_tests_are_split_by_owner(self) -> None:
        actions_tests = REPO_ROOT / "tests" / "python" / "actions"
        expected = [
            "actions_cli_test_support.py",
            "test_actions_cli_analyze.py",
            "test_actions_cli_commit.py",
            "test_actions_cli_pr.py",
            "test_actions_cli_review_completion.py",
            "test_actions_cli_ship.py",
        ]

        for filename in expected:
            with self.subTest(path=filename):
                self.assertTrue((actions_tests / filename).is_file())

        legacy = actions_tests / "test_actions_cli.py"
        self.assertLessEqual(len(legacy.read_text(encoding="utf-8").splitlines()), 20)

    def test_action_command_orchestrator_has_facade_mixins(self) -> None:
        test_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_command_test_facade.py"
        project_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_command_project_facade.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_command_orchestrator.py"

        self.assertTrue(test_owner.is_file())
        self.assertTrue(project_owner.is_file())
        self.assertIn("ActionCommandTestFacadeMixin", test_owner.read_text(encoding="utf-8"))
        self.assertIn("ActionCommandProjectFacadeMixin", project_owner.read_text(encoding="utf-8"))
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("ActionCommandTestFacadeMixin", facade_text)
        self.assertIn("ActionCommandProjectFacadeMixin", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 180)

    def test_project_action_domain_has_output_and_artifact_owners(self) -> None:
        protected_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_protected_artifacts.py"
        pr_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_pr_message_support.py"
        review_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_review_output_support.py"
        ship_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_ship_support.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "actions" / "project_action_domain.py"

        self.assertTrue(protected_owner.is_file())
        self.assertTrue(pr_owner.is_file())
        self.assertTrue(review_owner.is_file())
        self.assertTrue(ship_owner.is_file())
        self.assertIn("partition_envctl_protected_paths", protected_owner.read_text(encoding="utf-8"))
        self.assertIn("pr_body", pr_owner.read_text(encoding="utf-8"))
        self.assertIn("print_review_completion", review_owner.read_text(encoding="utf-8"))
        self.assertIn("ship_payload", ship_owner.read_text(encoding="utf-8"))
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("action_protected_artifacts", facade_text)
        self.assertIn("action_pr_message_support", facade_text)
        self.assertIn("action_review_output_support", facade_text)
        self.assertIn("action_ship_support", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 1350)

    def test_runtime_lifecycle_parity_tests_are_split_by_owner(self) -> None:
        runtime_tests = REPO_ROOT / "tests" / "python" / "runtime"
        expected = [
            "lifecycle_parity_test_support.py",
            "test_lifecycle_parity_blast.py",
            "test_lifecycle_parity_mode_scope.py",
            "test_lifecycle_parity_restore_startup.py",
            "test_lifecycle_parity_resume_legacy.py",
            "test_lifecycle_parity_resume_policy.py",
            "test_lifecycle_parity_resume_restore.py",
            "test_lifecycle_parity_state_actions.py",
            "test_lifecycle_parity_stop_health.py",
        ]

        for filename in expected:
            with self.subTest(path=filename):
                self.assertTrue((runtime_tests / filename).is_file())

        legacy = runtime_tests / "test_lifecycle_parity.py"
        self.assertLessEqual(len(legacy.read_text(encoding="utf-8").splitlines()), 20)
        resume_restore_breadcrumb = runtime_tests / "test_lifecycle_parity_resume_restore.py"
        self.assertLessEqual(len(resume_restore_breadcrumb.read_text(encoding="utf-8").splitlines()), 20)

    def test_runtime_command_parity_tests_are_split_by_owner(self) -> None:
        runtime_tests = REPO_ROOT / "tests" / "python" / "runtime"
        expected = [
            "engine_runtime_command_parity_test_support.py",
            "test_engine_runtime_command_parity_delegates.py",
            "test_engine_runtime_command_parity_doctor.py",
            "test_engine_runtime_command_parity_explain.py",
            "test_engine_runtime_command_parity_help.py",
            "test_engine_runtime_command_parity_state_config.py",
        ]

        for filename in expected:
            with self.subTest(path=filename):
                self.assertTrue((runtime_tests / filename).is_file())

        legacy = runtime_tests / "test_engine_runtime_command_parity.py"
        self.assertLessEqual(len(legacy.read_text(encoding="utf-8").splitlines()), 20)

    def test_plan_agent_launch_tests_are_split_by_transport_owner(self) -> None:
        planning_tests = REPO_ROOT / "tests" / "python" / "planning"
        expected = [
            "plan_agent_launch_support_test_support.py",
            "test_plan_agent_launch_cmux.py",
            "test_plan_agent_launch_cmux_cycles.py",
            "test_plan_agent_launch_cmux_goal.py",
            "test_plan_agent_launch_cmux_review.py",
            "test_plan_agent_launch_cmux_workspace.py",
            "test_plan_agent_launch_omx.py",
            "test_plan_agent_launch_omx_attach.py",
            "test_plan_agent_launch_omx_config.py",
            "test_plan_agent_launch_omx_spawn.py",
            "test_plan_agent_launch_omx_workflow.py",
            "test_plan_agent_launch_options.py",
            "test_plan_agent_launch_readiness.py",
            "test_plan_agent_launch_superset.py",
            "test_plan_agent_launch_tmux.py",
            "test_plan_agent_launch_workflow.py",
            "test_plan_agent_launch_workflow_build.py",
            "test_plan_agent_launch_workflow_prompt.py",
            "test_plan_agent_launch_workflow_queue.py",
            "test_plan_agent_launch_workflow_titles.py",
        ]

        for filename in expected:
            with self.subTest(path=filename):
                self.assertTrue((planning_tests / filename).is_file())

        legacy = planning_tests / "test_plan_agent_launch_support.py"
        self.assertLessEqual(len(legacy.read_text(encoding="utf-8").splitlines()), 20)
        cmux_breadcrumb = planning_tests / "test_plan_agent_launch_cmux.py"
        self.assertLessEqual(len(cmux_breadcrumb.read_text(encoding="utf-8").splitlines()), 20)
        omx_breadcrumb = planning_tests / "test_plan_agent_launch_omx.py"
        self.assertLessEqual(len(omx_breadcrumb.read_text(encoding="utf-8").splitlines()), 20)
        workflow_breadcrumb = planning_tests / "test_plan_agent_launch_workflow.py"
        self.assertLessEqual(len(workflow_breadcrumb.read_text(encoding="utf-8").splitlines()), 20)

    def test_planning_worktree_setup_tests_are_split_by_owner(self) -> None:
        planning_tests = REPO_ROOT / "tests" / "python" / "planning"
        expected = [
            "planning_worktree_setup_test_support.py",
            "test_planning_worktree_setup_archival.py",
            "test_planning_worktree_setup_code_intelligence.py",
            "test_planning_worktree_setup_fresh_ai_spinner.py",
            "test_planning_worktree_setup_git_hooks_recovery.py",
            "test_planning_worktree_setup_provenance.py",
            "test_planning_worktree_setup_selection.py",
        ]

        for filename in expected:
            with self.subTest(path=filename):
                self.assertTrue((planning_tests / filename).is_file())

        legacy = planning_tests / "test_planning_worktree_setup.py"
        self.assertLessEqual(len(legacy.read_text(encoding="utf-8").splitlines()), 20)

    def test_startup_orchestrator_flow_tests_are_split_by_phase_owner(self) -> None:
        startup_tests = REPO_ROOT / "tests" / "python" / "startup"
        expected = [
            "startup_orchestrator_flow_test_support.py",
            "test_startup_orchestrator_flow_bootstrap.py",
            "test_startup_orchestrator_flow_disabled.py",
            "test_startup_orchestrator_flow_failure.py",
            "test_startup_orchestrator_flow_handoff.py",
            "test_startup_orchestrator_flow_reuse.py",
        ]

        for filename in expected:
            with self.subTest(path=filename):
                self.assertTrue((startup_tests / filename).is_file())

        legacy = startup_tests / "test_startup_orchestrator_flow.py"
        self.assertLessEqual(len(legacy.read_text(encoding="utf-8").splitlines()), 20)

    def test_startup_spinner_tests_are_split_by_behavior_owner(self) -> None:
        startup_tests = REPO_ROOT / "tests" / "python" / "startup"
        expected = [
            "startup_spinner_integration_test_support.py",
            "test_startup_dashboard_stopped_restore.py",
            "test_startup_fingerprint_replacement.py",
            "test_startup_restart_port_preservation.py",
            "test_startup_restart_service_scope.py",
            "test_startup_spinner_display.py",
            "test_startup_spinner_parallel_progress.py",
        ]

        for filename in expected:
            with self.subTest(path=filename):
                self.assertTrue((startup_tests / filename).is_file())

        legacy = startup_tests / "test_startup_spinner_integration.py"
        self.assertLessEqual(len(legacy.read_text(encoding="utf-8").splitlines()), 20)

    def test_service_bootstrap_tests_are_split_by_env_owner(self) -> None:
        startup_tests = REPO_ROOT / "tests" / "python" / "startup"
        bootstrap_suite = startup_tests / "test_service_bootstrap_domain.py"
        env_suite = startup_tests / "test_service_env_support.py"

        self.assertTrue(bootstrap_suite.is_file())
        self.assertTrue(env_suite.is_file())
        env_text = env_suite.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.startup.service_env_support import", env_text)
        self.assertIn("class ServiceEnvSupportTests", env_text)
        self.assertLessEqual(len(bootstrap_suite.read_text(encoding="utf-8").splitlines()), 600)

    def test_runtime_service_facade_wrappers_have_owned_mixin(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime_service_facade.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime.py"

        self.assertTrue(owner.is_file())
        self.assertIn("RuntimeServiceFacadeMixin", owner.read_text(encoding="utf-8"))
        self.assertIn("RuntimeServiceFacadeMixin", facade.read_text(encoding="utf-8"))
        self.assertLessEqual(len(facade.read_text(encoding="utf-8").splitlines()), 1300)

    def test_runtime_construction_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime_construction.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime.py"

        self.assertTrue(owner.is_file())
        self.assertIn("def initialize_runtime_construction", owner.read_text(encoding="utf-8"))
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("initialize_runtime_construction(self, config, env=env)", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 1050)

    def test_runtime_planning_and_startup_facades_have_owned_mixins(self) -> None:
        planning_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime_planning_facade.py"
        startup_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime_startup_facade.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime.py"

        self.assertTrue(planning_owner.is_file())
        self.assertTrue(startup_owner.is_file())
        self.assertIn("RuntimePlanningFacadeMixin", planning_owner.read_text(encoding="utf-8"))
        self.assertIn("RuntimeStartupFacadeMixin", startup_owner.read_text(encoding="utf-8"))
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("RuntimePlanningFacadeMixin", facade_text)
        self.assertIn("RuntimeStartupFacadeMixin", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 800)

    def test_dashboard_command_support_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "command_support.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "orchestrator.py"

        self.assertTrue(owner.is_file())
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("import envctl_engine.ui.dashboard.command_support as command_support", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 900)

    def test_dashboard_rendering_parity_tests_are_split_by_owner(self) -> None:
        ui_tests = REPO_ROOT / "tests" / "python" / "ui"
        expected = [
            "dashboard_rendering_parity_test_support.py",
            "test_dashboard_rendering_parity_ai_sessions.py",
            "test_dashboard_rendering_parity_dependencies.py",
            "test_dashboard_rendering_parity_links.py",
            "test_dashboard_rendering_parity_services.py",
        ]

        for filename in expected:
            with self.subTest(path=filename):
                self.assertTrue((ui_tests / filename).is_file())

        legacy = ui_tests / "test_dashboard_rendering_parity.py"
        self.assertLessEqual(len(legacy.read_text(encoding="utf-8").splitlines()), 20)

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

    def test_engine_runtime_cli_support_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime_cli_support.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.runtime.engine_runtime_cli_support import",
            facade.read_text(encoding="utf-8"),
        )

    def test_engine_runtime_doctor_support_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime_doctor_support.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.runtime.engine_runtime_doctor_support import",
            facade.read_text(encoding="utf-8"),
        )

    def test_engine_runtime_bookkeeping_support_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime_bookkeeping_support.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.runtime.engine_runtime_bookkeeping_support import",
            facade.read_text(encoding="utf-8"),
        )

    def test_startup_selection_support_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "startup_selection_support.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "startup" / "startup_orchestrator.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.startup.startup_selection_support import",
            facade.read_text(encoding="utf-8"),
        )

    def test_startup_context_selection_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "context_selection.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "startup" / "startup_orchestrator.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.startup.context_selection import",
            facade.read_text(encoding="utf-8"),
        )

    def test_selected_context_startup_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "selected_context_startup.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "startup" / "startup_orchestrator.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.startup.selected_context_startup import",
            facade.read_text(encoding="utf-8"),
        )

    def test_post_start_reconcile_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "post_start_reconcile.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "startup" / "startup_orchestrator.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.startup.post_start_reconcile import",
            facade.read_text(encoding="utf-8"),
        )

    def test_startup_session_lifecycle_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "session_lifecycle.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "startup" / "startup_orchestrator.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.startup.session_lifecycle import",
            facade.read_text(encoding="utf-8"),
        )

    def test_startup_run_reuse_resolution_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "run_reuse_resolution.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "startup" / "startup_orchestrator.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.startup.run_reuse_resolution import",
            facade.read_text(encoding="utf-8"),
        )

    def test_disabled_startup_resolution_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "disabled_startup_resolution.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "startup" / "startup_orchestrator.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.startup.disabled_startup_resolution import",
            facade.read_text(encoding="utf-8"),
        )

    def test_startup_execution_preparation_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "execution_preparation.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "startup" / "startup_orchestrator.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.startup.execution_preparation import",
            facade.read_text(encoding="utf-8"),
        )

    def test_service_bootstrap_env_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "service_env_support.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "startup" / "service_bootstrap_domain.py"

        self.assertTrue(owner.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        self.assertIn("def _resolve_backend_env_contract", owner_text)
        self.assertIn("def _service_env_from_file", owner_text)
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn(
            "from envctl_engine.startup.service_env_support import",
            facade_text,
        )
        self.assertLessEqual(len(facade_text.splitlines()), 1400)

    def test_repo_local_launcher_is_python_script(self) -> None:
        launcher = REPO_ROOT / "bin" / "envctl"
        self.assertTrue(launcher.is_file())
        text = launcher.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("#!/usr/bin/env python3"))


if __name__ == "__main__":
    unittest.main()
