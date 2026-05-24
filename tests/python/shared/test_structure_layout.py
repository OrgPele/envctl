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
        auth_owner = REPO_ROOT / "python" / "envctl_engine" / "requirements" / "supabase_lifecycle" / "auth_flow.py"
        db_owner = REPO_ROOT / "python" / "envctl_engine" / "requirements" / "supabase_lifecycle" / "db_flow.py"
        graph_owner = REPO_ROOT / "python" / "envctl_engine" / "requirements" / "supabase_lifecycle" / "graph_flow.py"
        service_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "requirements" / "supabase_lifecycle" / "service_resolution.py"
        )
        preflight_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "requirements" / "supabase_lifecycle" / "gateway_preflight.py"
        )
        facade = REPO_ROOT / "python" / "envctl_engine" / "requirements" / "supabase.py"

        self.assertTrue(owner.is_file())
        self.assertTrue(auth_owner.is_file())
        self.assertTrue(db_owner.is_file())
        self.assertTrue(graph_owner.is_file())
        self.assertTrue(service_owner.is_file())
        self.assertTrue(preflight_owner.is_file())
        self.assertIn("def complete_supabase_auth_startup", auth_owner.read_text(encoding="utf-8"))
        self.assertIn("def ensure_supabase_db_ready", db_owner.read_text(encoding="utf-8"))
        self.assertIn("def start_supabase_compose_graph", graph_owner.read_text(encoding="utf-8"))
        self.assertIn("def resolve_supabase_startup_services", service_owner.read_text(encoding="utf-8"))
        self.assertIn("def prepare_supabase_gateway_preflight", preflight_owner.read_text(encoding="utf-8"))
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

    def test_requirement_adapter_base_has_policy_and_cleanup_owners(self) -> None:
        policy_owner = REPO_ROOT / "python" / "envctl_engine" / "requirements" / "adapter_policy.py"
        cleanup_owner = REPO_ROOT / "python" / "envctl_engine" / "requirements" / "adapter_port_cleanup.py"
        model_owner = REPO_ROOT / "python" / "envctl_engine" / "requirements" / "adapter_lifecycle_models.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "requirements" / "adapter_base.py"

        self.assertTrue(policy_owner.is_file())
        self.assertTrue(cleanup_owner.is_file())
        self.assertTrue(model_owner.is_file())
        policy_text = policy_owner.read_text(encoding="utf-8")
        cleanup_text = cleanup_owner.read_text(encoding="utf-8")
        model_text = model_owner.read_text(encoding="utf-8")
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("def env_bool", policy_text)
        self.assertIn("def port_mismatch_policy", policy_text)
        self.assertIn("def cleanup_envctl_owned_port_containers", cleanup_text)
        self.assertIn("def format_bind_conflict_guidance", cleanup_text)
        self.assertIn("class AdapterLifecycleEvent", model_text)
        self.assertIn("class ContainerLifecycleTemplate", model_text)
        self.assertIn("from .adapter_policy import", facade_text)
        self.assertIn("from .adapter_port_cleanup import", facade_text)
        self.assertIn("from .adapter_lifecycle_models import", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 780)

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

    def test_action_test_support_has_spinner_owner(self) -> None:
        spinner_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_test_spinner_support.py"
        manifest_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_test_manifest_support.py"
        models_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_test_support_models.py"
        command_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_test_command_support.py"
        failed_spec_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_failed_test_spec_support.py"
        support = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_test_support.py"

        self.assertTrue(spinner_owner.is_file())
        self.assertTrue(manifest_owner.is_file())
        self.assertTrue(models_owner.is_file())
        self.assertTrue(command_owner.is_file())
        self.assertTrue(failed_spec_owner.is_file())
        owner_text = spinner_owner.read_text(encoding="utf-8")
        self.assertIn("class TestSuiteSpinnerGroup", owner_text)
        self.assertIn("def rich_progress_available", owner_text)
        manifest_text = manifest_owner.read_text(encoding="utf-8")
        self.assertIn("class FailedTestManifest", manifest_text)
        self.assertIn("def load_failed_test_manifest", manifest_text)
        self.assertIn("def sanitize_failed_test_identifiers", manifest_text)
        models_text = models_owner.read_text(encoding="utf-8")
        self.assertIn("class TestTargetContext", models_text)
        self.assertIn("class TestExecutionSpec", models_text)
        command_text = command_owner.read_text(encoding="utf-8")
        self.assertIn("def build_test_execution_specs", command_text)
        self.assertIn("def configured_or_default_test_spec", command_text)
        failed_spec_text = failed_spec_owner.read_text(encoding="utf-8")
        self.assertIn("def build_failed_test_execution_specs", failed_spec_text)
        self.assertIn("def failed_rerun_spec_for_entry", failed_spec_text)
        support_text = support.read_text(encoding="utf-8")
        self.assertIn("action_test_spinner_support", support_text)
        self.assertIn("action_test_manifest_support", support_text)
        self.assertIn("action_test_support_models", support_text)
        self.assertIn("action_test_command_support", support_text)
        self.assertIn("action_failed_test_spec_support", support_text)
        self.assertLessEqual(len(support_text.splitlines()), 220)

    def test_action_test_runner_has_progress_and_failure_owners(self) -> None:
        execution_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_test_execution_support.py"
        suite_execution_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_test_suite_execution_support.py"
        )
        progress_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_test_runner_progress.py"
        failure_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_test_runner_failures.py"
        runner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_test_runner.py"

        self.assertTrue(execution_owner.is_file())
        self.assertTrue(suite_execution_owner.is_file())
        self.assertTrue(progress_owner.is_file())
        self.assertTrue(failure_owner.is_file())
        execution_text = execution_owner.read_text(encoding="utf-8")
        suite_execution_text = suite_execution_owner.read_text(encoding="utf-8")
        progress_text = progress_owner.read_text(encoding="utf-8")
        failure_text = failure_owner.read_text(encoding="utf-8")
        self.assertIn("class TestActionExecutionPlan", execution_text)
        self.assertIn("def build_test_action_execution_plan", execution_text)
        self.assertIn("def resolve_suite_spinner_decision", execution_text)
        self.assertIn("class TestSuiteExecutionResult", suite_execution_text)
        self.assertIn("def execute_test_suites", suite_execution_text)
        self.assertIn("class _TestSuiteExecutor", suite_execution_text)
        self.assertIn("def format_live_progress_status", progress_text)
        self.assertIn("def format_live_progress_status_with_counts", progress_text)
        self.assertIn("def summarize_failure_output", failure_text)
        self.assertIn("def format_failure_output_for_artifact", failure_text)
        runner_text = runner.read_text(encoding="utf-8")
        self.assertIn("action_test_execution_support", runner_text)
        self.assertIn("action_test_suite_execution_support", runner_text)
        self.assertIn("action_test_runner_progress", runner_text)
        self.assertIn("action_test_runner_failures", runner_text)
        self.assertLessEqual(len(runner_text.splitlines()), 180)

    def test_actions_test_has_models_path_and_classification_owners(self) -> None:
        models_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "actions_test_models.py"
        path_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "actions_test_frontend_paths.py"
        classification_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "actions_test_classification.py"
        discovery = REPO_ROOT / "python" / "envctl_engine" / "actions" / "actions_test.py"

        self.assertTrue(models_owner.is_file())
        self.assertTrue(path_owner.is_file())
        self.assertTrue(classification_owner.is_file())
        self.assertIn("class TestCommandSpec", models_owner.read_text(encoding="utf-8"))
        self.assertIn("class TestPathSuggestion", models_owner.read_text(encoding="utf-8"))
        path_text = path_owner.read_text(encoding="utf-8")
        self.assertIn("def append_frontend_test_path", path_text)
        self.assertIn("def canonicalize_frontend_test_path", path_text)
        classification_text = classification_owner.read_text(encoding="utf-8")
        self.assertIn("def classify_test_command_source", classification_text)
        self.assertIn("def build_test_args", classification_text)
        discovery_text = discovery.read_text(encoding="utf-8")
        self.assertIn("actions_test_models", discovery_text)
        self.assertIn("actions_test_frontend_paths", discovery_text)
        self.assertIn("actions_test_classification", discovery_text)
        self.assertLessEqual(len(discovery_text.splitlines()), 540)

    def test_project_action_domain_has_output_and_artifact_owners(self) -> None:
        commit_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_commit_support.py"
        protected_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_protected_artifacts.py"
        pr_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_pr_message_support.py"
        review_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_review_output_support.py"
        review_plan_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_review_plan_support.py"
        git_state_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_git_state_support.py"
        ship_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_ship_support.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "actions" / "project_action_domain.py"

        self.assertTrue(commit_owner.is_file())
        self.assertTrue(protected_owner.is_file())
        self.assertTrue(pr_owner.is_file())
        self.assertTrue(review_owner.is_file())
        self.assertTrue(review_plan_owner.is_file())
        self.assertTrue(git_state_owner.is_file())
        self.assertTrue(ship_owner.is_file())
        commit_text = commit_owner.read_text(encoding="utf-8")
        self.assertIn("def run_commit_workflow", commit_text)
        self.assertIn("def resolve_commit_message", commit_text)
        self.assertIn("def advance_commit_ledger_pointer", commit_text)
        self.assertIn("partition_envctl_protected_paths", protected_owner.read_text(encoding="utf-8"))
        self.assertIn("pr_body", pr_owner.read_text(encoding="utf-8"))
        self.assertIn("print_review_completion", review_owner.read_text(encoding="utf-8"))
        self.assertIn("resolve_original_plan", review_plan_owner.read_text(encoding="utf-8"))
        git_state_text = git_state_owner.read_text(encoding="utf-8")
        self.assertIn("class DirtyWorktreeReport", git_state_text)
        self.assertIn("def probe_dirty_worktree", git_state_text)
        self.assertIn("def detect_default_branch", git_state_text)
        self.assertIn("def existing_pr_url", git_state_text)
        ship_text = ship_owner.read_text(encoding="utf-8")
        self.assertIn("ship_payload", ship_text)
        self.assertIn("def run_ship_workflow", ship_text)
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("action_commit_support", facade_text)
        self.assertIn("action_protected_artifacts", facade_text)
        self.assertIn("action_pr_message_support", facade_text)
        self.assertIn("action_review_output_support", facade_text)
        self.assertIn("action_review_plan_support", facade_text)
        self.assertIn("action_git_state_support", facade_text)
        self.assertIn("action_ship_support", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 700)

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

    def test_runtime_lifecycle_cleanup_has_blast_owner(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "lifecycle_blast_support.py"
        orchestrator = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "lifecycle_cleanup_orchestrator.py"

        self.assertTrue(owner.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        self.assertIn("class LifecycleBlastCleanupSupport", owner_text)
        self.assertIn("def blast_all_docker_cleanup", owner_text)
        self.assertIn("def blast_all_kill_orchestrator_processes", owner_text)
        orchestrator_text = orchestrator.read_text(encoding="utf-8")
        self.assertIn("LifecycleBlastCleanupSupport", orchestrator_text)
        self.assertLessEqual(len(orchestrator_text.splitlines()), 760)

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

    def test_runtime_env_tests_are_split_by_owner(self) -> None:
        runtime_tests = REPO_ROOT / "tests" / "python" / "runtime"
        expected = [
            "engine_runtime_env_test_support.py",
            "test_engine_runtime_env_external_dependencies.py",
            "test_engine_runtime_env_mode.py",
            "test_engine_runtime_env_readiness.py",
            "test_engine_runtime_env_service_projection.py",
            "test_engine_runtime_env_templates.py",
        ]

        for filename in expected:
            with self.subTest(path=filename):
                self.assertTrue((runtime_tests / filename).is_file())

        legacy = runtime_tests / "test_engine_runtime_env.py"
        self.assertLessEqual(len(legacy.read_text(encoding="utf-8").splitlines()), 20)

    def test_runtime_env_dependency_projection_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime_dependency_env.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime_env.py"

        self.assertTrue(owner.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        self.assertIn("def dependency_projector_env", owner_text)
        self.assertIn("def resolve_dependency_env_templates", owner_text)
        self.assertIn("def service_env_overlays", owner_text)
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.runtime.engine_runtime_dependency_env import", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 760)

    def test_prompt_install_support_tests_are_split_by_owner(self) -> None:
        runtime_tests = REPO_ROOT / "tests" / "python" / "runtime"
        expected = [
            "prompt_install_support_test_support.py",
            "test_prompt_install_support_direct_prompt.py",
            "test_prompt_install_support_install_flow.py",
            "test_prompt_install_support_skill_writes.py",
            "test_prompt_install_support_templates.py",
        ]

        for filename in expected:
            with self.subTest(path=filename):
                self.assertTrue((runtime_tests / filename).is_file())

        legacy = runtime_tests / "test_prompt_install_support.py"
        self.assertLessEqual(len(legacy.read_text(encoding="utf-8").splitlines()), 20)

    def test_prompt_install_support_is_split_by_owner(self) -> None:
        runtime = REPO_ROOT / "python" / "envctl_engine" / "runtime"
        expected = [
            "prompt_install_codex_skills.py",
            "prompt_install_direct_prompt.py",
            "prompt_install_flow.py",
            "prompt_install_models.py",
            "prompt_install_paths.py",
            "prompt_install_templates.py",
        ]

        for filename in expected:
            with self.subTest(path=filename):
                self.assertTrue((runtime / filename).is_file())

        facade = runtime / "prompt_install_support.py"
        self.assertLessEqual(len(facade.read_text(encoding="utf-8").splitlines()), 160)

    def test_action_test_summary_support_is_split_by_owner(self) -> None:
        actions = REPO_ROOT / "python" / "envctl_engine" / "actions"
        expected = [
            "action_test_summary_artifacts.py",
            "action_test_summary_collection.py",
            "action_test_summary_display.py",
            "action_test_summary_formatting.py",
            "action_test_summary_git.py",
        ]

        for filename in expected:
            with self.subTest(path=filename):
                self.assertTrue((actions / filename).is_file())

        facade = actions / "action_test_summary_support.py"
        self.assertLessEqual(len(facade.read_text(encoding="utf-8").splitlines()), 140)

    def test_state_action_orchestrator_has_log_owner(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "state" / "action_log_support.py"
        health_owner = REPO_ROOT / "python" / "envctl_engine" / "state" / "action_health_support.py"
        command_owner = REPO_ROOT / "python" / "envctl_engine" / "state" / "action_command_support.py"
        orchestrator = REPO_ROOT / "python" / "envctl_engine" / "state" / "action_orchestrator.py"

        self.assertTrue(owner.is_file())
        self.assertTrue(health_owner.is_file())
        self.assertTrue(command_owner.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        health_owner_text = health_owner.read_text(encoding="utf-8")
        command_owner_text = command_owner.read_text(encoding="utf-8")
        self.assertIn("class StateActionLogSupport", owner_text)
        self.assertIn("def logs_payload", owner_text)
        self.assertIn("def clear_service_logs", owner_text)
        self.assertIn("class StateActionHealthSupport", health_owner_text)
        self.assertIn("def health_payload", health_owner_text)
        self.assertIn("def health_service_rows", health_owner_text)
        self.assertIn("class StateActionCommandRunner", command_owner_text)
        self.assertIn("def execute_state_action", command_owner_text)
        orchestrator_text = orchestrator.read_text(encoding="utf-8")
        self.assertIn("StateActionLogSupport", orchestrator_text)
        self.assertIn("StateActionHealthSupport", orchestrator_text)
        self.assertIn("execute_state_action", orchestrator_text)
        self.assertLessEqual(len(orchestrator_text.splitlines()), 360)

    def test_runtime_feature_inventory_has_contract_owner(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "runtime_feature_contracts.py"
        definition_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime_feature_definitions.py"
        inventory = REPO_ROOT / "python" / "envctl_engine" / "runtime_feature_inventory.py"

        self.assertTrue(owner.is_file())
        self.assertTrue(definition_owner.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        definition_owner_text = definition_owner.read_text(encoding="utf-8")
        self.assertIn("def build_runtime_feature_matrix_from_definitions", owner_text)
        self.assertIn("def validate_runtime_feature_matrix_payload", owner_text)
        self.assertIn("def render_python_runtime_gap_closure_plan", owner_text)
        self.assertIn("class FeatureDefinition", definition_owner_text)
        self.assertIn("COMMAND_DEFINITIONS", definition_owner_text)
        self.assertIn("EXTRA_FEATURES", definition_owner_text)
        inventory_text = inventory.read_text(encoding="utf-8")
        self.assertIn("runtime_feature_contracts", inventory_text)
        self.assertIn("runtime_feature_definitions", inventory_text)
        self.assertLessEqual(len(inventory_text.splitlines()), 90)

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
            "test_plan_agent_launch_superset_desktop.py",
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

    def test_runtime_command_router_has_owned_catalog(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "command_catalog.py"
        models_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "command_models.py"
        flag_storage_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "command_flag_storage.py"
        special_flags_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "command_special_flags.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "command_router.py"

        self.assertTrue(owner.is_file())
        self.assertTrue(models_owner.is_file())
        self.assertTrue(flag_storage_owner.is_file())
        self.assertTrue(special_flags_owner.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        models_text = models_owner.read_text(encoding="utf-8")
        flag_storage_text = flag_storage_owner.read_text(encoding="utf-8")
        special_flags_text = special_flags_owner.read_text(encoding="utf-8")
        self.assertIn("COMMAND_ALIASES", owner_text)
        self.assertIn("def list_supported_flag_tokens", owner_text)
        self.assertIn("class Route", models_text)
        self.assertIn("class RouteError", models_text)
        self.assertIn("def boolean_flag_name", flag_storage_text)
        self.assertIn("def store_value_flag", flag_storage_text)
        self.assertIn("def handle_special_flag", special_flags_text)
        self.assertIn("def handle_env_assignment", special_flags_text)
        self.assertIn("def validate_plan_agent_cli_flags", special_flags_text)
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.runtime.command_catalog import", facade_text)
        self.assertIn("from envctl_engine.runtime.command_models import", facade_text)
        self.assertIn("from envctl_engine.runtime.command_flag_storage import", facade_text)
        self.assertIn("from envctl_engine.runtime.command_special_flags import", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 500)

    def test_runtime_inspection_has_startup_owner(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "startup_inspection_support.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "inspection_support.py"

        self.assertTrue(owner.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        self.assertIn("class StartupInspectionBuilder", owner_text)
        self.assertIn("def build_startup_explanation_payload", owner_text)
        self.assertIn("def build_preflight_payload", owner_text)
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.runtime.startup_inspection_support import", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 560)

    def test_runtime_planning_and_startup_facades_have_owned_mixins(self) -> None:
        planning_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime_planning_facade.py"
        startup_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime_startup_facade.py"
        action_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime_action_facade.py"
        truth_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime_truth_facade.py"
        lifecycle_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime_lifecycle_facade.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime.py"

        self.assertTrue(planning_owner.is_file())
        self.assertTrue(startup_owner.is_file())
        self.assertTrue(action_owner.is_file())
        self.assertTrue(truth_owner.is_file())
        self.assertTrue(lifecycle_owner.is_file())
        self.assertIn("RuntimePlanningFacadeMixin", planning_owner.read_text(encoding="utf-8"))
        self.assertIn("RuntimeStartupFacadeMixin", startup_owner.read_text(encoding="utf-8"))
        self.assertIn("RuntimeActionFacadeMixin", action_owner.read_text(encoding="utf-8"))
        self.assertIn("RuntimeTruthFacadeMixin", truth_owner.read_text(encoding="utf-8"))
        self.assertIn("RuntimeLifecycleFacadeMixin", lifecycle_owner.read_text(encoding="utf-8"))
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("RuntimePlanningFacadeMixin", facade_text)
        self.assertIn("RuntimeStartupFacadeMixin", facade_text)
        self.assertIn("RuntimeActionFacadeMixin", facade_text)
        self.assertIn("RuntimeTruthFacadeMixin", facade_text)
        self.assertIn("RuntimeLifecycleFacadeMixin", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 430)

    def test_dashboard_command_support_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "command_support.py"
        target_owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "project_target_support.py"
        selection_owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "target_selection_support.py"
        review_tab_owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "review_tab_support.py"
        pr_selection_owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "pr_selection_support.py"
        pr_commit_owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "pr_commit_support.py"
        pr_scope_owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "pr_scope_support.py"
        stop_owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "stop_scope_support.py"
        pr_facade = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "pr_and_target_support.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "orchestrator.py"

        self.assertTrue(owner.is_file())
        self.assertTrue(target_owner.is_file())
        self.assertTrue(selection_owner.is_file())
        self.assertTrue(review_tab_owner.is_file())
        self.assertTrue(pr_selection_owner.is_file())
        self.assertTrue(pr_commit_owner.is_file())
        self.assertTrue(pr_scope_owner.is_file())
        self.assertTrue(stop_owner.is_file())
        pr_facade_text = pr_facade.read_text(encoding="utf-8")
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("def dashboard_hidden_commands", owner.read_text(encoding="utf-8"))
        self.assertIn("def apply_interactive_target_selection", selection_owner.read_text(encoding="utf-8"))
        self.assertIn("def apply_pr_selection", pr_selection_owner.read_text(encoding="utf-8"))
        self.assertIn("def maybe_prepare_pr_commit", pr_commit_owner.read_text(encoding="utf-8"))
        self.assertIn("def dirty_pr_reports", pr_scope_owner.read_text(encoding="utf-8"))
        self.assertIn("def apply_stop_resource_tokens", stop_owner.read_text(encoding="utf-8"))
        self.assertIn("pr_selection_support", pr_facade_text)
        self.assertIn("pr_commit_support", pr_facade_text)
        self.assertIn("pr_scope_support", pr_facade_text)
        self.assertLessEqual(len(pr_facade_text.splitlines()), 210)
        self.assertIn("import envctl_engine.ui.dashboard.command_support as command_support", facade_text)
        self.assertIn("from envctl_engine.ui.dashboard import project_target_support", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 700)

    def test_dashboard_orchestrator_tests_are_split_by_owner(self) -> None:
        ui_tests = REPO_ROOT / "tests" / "python" / "ui"
        expected = [
            "dashboard_orchestrator_test_support.py",
            "test_dashboard_orchestrator_failure_details.py",
            "test_dashboard_orchestrator_pr_flow.py",
            "test_dashboard_orchestrator_pr_flow_dirty.py",
            "test_dashboard_orchestrator_pr_flow_failure_details.py",
            "test_dashboard_orchestrator_pr_flow_messages.py",
            "test_dashboard_orchestrator_pr_flow_selection.py",
            "test_dashboard_orchestrator_restart_selector.py",
            "test_dashboard_orchestrator_review_tab.py",
            "test_dashboard_orchestrator_stop_scope.py",
            "test_dashboard_orchestrator_target_selection.py",
        ]

        for filename in expected:
            with self.subTest(path=filename):
                self.assertTrue((ui_tests / filename).is_file())

        pr_flow_breadcrumb = ui_tests / "test_dashboard_orchestrator_pr_flow.py"
        self.assertLessEqual(len(pr_flow_breadcrumb.read_text(encoding="utf-8").splitlines()), 20)

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

    def test_dashboard_rendering_has_ai_session_owner(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "ai_session_rendering.py"
        rendering = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "rendering.py"

        self.assertTrue(owner.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        self.assertIn("def print_dashboard_ai_session_row", owner_text)
        self.assertIn("def dashboard_repo_root_for_project", owner_text)
        self.assertIn("def dashboard_current_tmux_target", owner_text)
        rendering_text = rendering.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.ui.dashboard import ai_session_rendering", rendering_text)
        self.assertLessEqual(len(rendering_text.splitlines()), 1100)

    def test_dashboard_rendering_has_dependency_owner(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "dependency_rendering.py"
        rendering = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "rendering.py"

        self.assertTrue(owner.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        self.assertIn("def print_dashboard_dependency_rows", owner_text)
        self.assertIn("def dashboard_dependency_scope", owner_text)
        self.assertIn("def requirements_has_dashboard_dependencies", owner_text)
        rendering_text = rendering.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.ui.dashboard import dependency_rendering", rendering_text)
        self.assertLessEqual(len(rendering_text.splitlines()), 1005)

    def test_dashboard_rendering_has_pr_link_owner(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "pr_link_rendering.py"
        rendering = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "rendering.py"

        self.assertTrue(owner.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        self.assertIn("def dashboard_project_pr_map", owner_text)
        self.assertIn("def dashboard_lookup_pr", owner_text)
        self.assertIn("def select_dashboard_pr", owner_text)
        rendering_text = rendering.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.ui.dashboard import pr_link_rendering", rendering_text)
        self.assertLessEqual(len(rendering_text.splitlines()), 850)

    def test_dashboard_rendering_has_service_owner(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "service_rendering.py"
        rendering = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "rendering.py"

        self.assertTrue(owner.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        self.assertIn("def print_dashboard_service_row", owner_text)
        self.assertIn("def print_dashboard_additional_service_rows", owner_text)
        self.assertIn("def dashboard_visible_stopped_service_count", owner_text)
        rendering_text = rendering.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.ui.dashboard import service_rendering", rendering_text)
        self.assertLessEqual(len(rendering_text.splitlines()), 745)

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

    def test_worktree_path_support_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_path_support.py"
        menu_owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_menu_terminal_support.py"
        spinner_owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_spinner_support.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_domain.py"

        self.assertTrue(owner.is_file())
        self.assertTrue(menu_owner.is_file())
        self.assertTrue(spinner_owner.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        menu_owner_text = menu_owner.read_text(encoding="utf-8")
        spinner_owner_text = spinner_owner.read_text(encoding="utf-8")
        self.assertIn("def preferred_tree_root_for_feature", owner_text)
        self.assertIn("def trees_root_for_worktree", owner_text)
        self.assertIn("def resolve_planning_selection_target", owner_text)
        self.assertIn("def setup_worktree_requested", owner_text)
        self.assertIn("def render_planning_selection_menu", menu_owner_text)
        self.assertIn("def planning_menu_apply_key", menu_owner_text)
        self.assertIn("def worktree_spinner_policy", spinner_owner_text)
        self.assertIn("def worktree_spinner_update", spinner_owner_text)
        self.assertIn("def worktree_spinner_stop", spinner_owner_text)
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.planning.worktree_path_support import", facade_text)
        self.assertIn("from envctl_engine.planning.worktree_menu_terminal_support import", facade_text)
        self.assertIn("from envctl_engine.planning.worktree_spinner_support import", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 920)

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

    def test_worktree_creation_flow_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_creation_flow.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_domain.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.planning.worktree_creation_flow import",
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
        facade_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime_action_facade.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime.py"

        self.assertTrue(owner.is_file())
        self.assertTrue(facade_owner.is_file())
        self.assertIn(
            "from envctl_engine.runtime.engine_runtime_action_support import",
            facade_owner.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "from envctl_engine.runtime.engine_runtime_action_facade import",
            facade.read_text(encoding="utf-8"),
        )

    def test_engine_runtime_cli_support_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime_cli_support.py"
        facade_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime_cli_facade.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime.py"

        self.assertTrue(owner.is_file())
        self.assertTrue(facade_owner.is_file())
        self.assertIn(
            "from envctl_engine.runtime.engine_runtime_cli_support import",
            facade_owner.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "RuntimeCliFacadeMixin",
            facade.read_text(encoding="utf-8"),
        )

    def test_runtime_help_rendering_has_metadata_and_general_owners(self) -> None:
        metadata_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "help_metadata.py"
        general_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "help_general.py"
        topics_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "help_topics.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "help_text.py"

        self.assertTrue(metadata_owner.is_file())
        self.assertTrue(general_owner.is_file())
        self.assertTrue(topics_owner.is_file())
        metadata_text = metadata_owner.read_text(encoding="utf-8")
        general_text = general_owner.read_text(encoding="utf-8")
        topics_text = topics_owner.read_text(encoding="utf-8")
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("def default_interactivity", metadata_text)
        self.assertIn("def ordered_known_commands", metadata_text)
        self.assertIn("def render_general_help", general_text)
        self.assertIn("COMMAND_HELP_TOPICS", topics_text)
        self.assertIn("def help_text_for_route", topics_text)
        self.assertIn("def render_command_help", topics_text)
        self.assertIn("from envctl_engine.runtime.help_general import render_general_help", facade_text)
        self.assertIn("from envctl_engine.runtime.help_metadata import", facade_text)
        self.assertIn("from envctl_engine.runtime.help_topics import", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 80)

    def test_engine_runtime_doctor_support_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime_doctor_support.py"
        facade_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime_doctor_facade.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime.py"

        self.assertTrue(owner.is_file())
        self.assertTrue(facade_owner.is_file())
        self.assertIn(
            "from envctl_engine.runtime.engine_runtime_doctor_support import",
            facade_owner.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "RuntimeDoctorFacadeMixin",
            facade.read_text(encoding="utf-8"),
        )

    def test_engine_runtime_debug_support_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime_debug_support.py"
        facade_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime_debug_facade.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime.py"

        self.assertTrue(owner.is_file())
        self.assertTrue(facade_owner.is_file())
        self.assertIn(
            "from envctl_engine.runtime.engine_runtime_debug_support import",
            facade_owner.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "RuntimeDebugFacadeMixin",
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

    def test_run_reuse_identity_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "run_reuse_identity.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "startup" / "run_reuse_support.py"

        self.assertTrue(owner.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        self.assertIn("class ProjectIdentity", owner_text)
        self.assertIn("def build_startup_identity_metadata", owner_text)
        self.assertIn("def _startup_identity_payload", owner_text)
        self.assertIn("def project_identities_from_state", owner_text)
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.startup.run_reuse_identity import", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 580)

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
        env_owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "service_env_support.py"
        runtime_state_owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "service_runtime_state_support.py"
        frontend_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "startup" / "service_frontend_bootstrap_support.py"
        )
        migration_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "startup" / "service_backend_migration_support.py"
        )
        facade = REPO_ROOT / "python" / "envctl_engine" / "startup" / "service_bootstrap_domain.py"

        self.assertTrue(env_owner.is_file())
        self.assertTrue(runtime_state_owner.is_file())
        self.assertTrue(frontend_owner.is_file())
        self.assertTrue(migration_owner.is_file())
        owner_text = env_owner.read_text(encoding="utf-8")
        self.assertIn("def _resolve_backend_env_contract", owner_text)
        self.assertIn("def _service_env_from_file", owner_text)
        runtime_state_text = runtime_state_owner.read_text(encoding="utf-8")
        self.assertIn("def _backend_runtime_prep_required", runtime_state_text)
        self.assertIn("def _frontend_runtime_prep_required", runtime_state_text)
        frontend_text = frontend_owner.read_text(encoding="utf-8")
        self.assertIn("def _prepare_frontend_runtime", frontend_text)
        self.assertIn("def _frontend_install_commands", frontend_text)
        migration_text = migration_owner.read_text(encoding="utf-8")
        self.assertIn("def _run_backend_migration_step", migration_text)
        self.assertIn("def _backend_migration_retry_env_for_async_driver_mismatch", migration_text)
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn(
            "from envctl_engine.startup.service_env_support import",
            facade_text,
        )
        self.assertIn(
            "from envctl_engine.startup.service_runtime_state_support import",
            facade_text,
        )
        self.assertIn(
            "from envctl_engine.startup.service_frontend_bootstrap_support import",
            facade_text,
        )
        self.assertIn(
            "from envctl_engine.startup.service_backend_migration_support import",
            facade_text,
        )
        self.assertLessEqual(len(facade_text.splitlines()), 500)

    def test_service_execution_policy_has_owned_module(self) -> None:
        env_owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "service_execution_environment.py"
        owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "service_execution_policy.py"
        records_owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "service_execution_records.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "startup" / "service_execution.py"

        self.assertTrue(env_owner.is_file())
        self.assertTrue(owner.is_file())
        self.assertTrue(records_owner.is_file())
        env_text = env_owner.read_text(encoding="utf-8")
        self.assertIn("def resolve_service_workdirs", env_text)
        self.assertIn("def configured_service_types_for_mode", env_text)
        self.assertIn("def make_service_dependency_emitter", env_text)
        self.assertIn("def make_service_retry_emitter", env_text)
        owner_text = owner.read_text(encoding="utf-8")
        self.assertIn("def resolve_command_env_builder", owner_text)
        self.assertIn("def ordered_service_layers", owner_text)
        self.assertIn("def service_attach_parallel_enabled", owner_text)
        self.assertIn("def _project_backend_cors_origin", owner_text)
        records_text = records_owner.read_text(encoding="utf-8")
        self.assertIn("class PreparedServiceLaunch", records_text)
        self.assertIn("def finalize_launched_service_records", records_text)
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.startup.service_execution_environment import", facade_text)
        self.assertIn("from envctl_engine.startup.service_execution_policy import", facade_text)
        self.assertIn("from envctl_engine.startup.service_execution_records import", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 760)

    def test_service_launch_diagnostics_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "service_launch_diagnostics.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "startup" / "service_execution.py"

        self.assertTrue(owner.is_file())
        self.assertIn("def record_runtime_launch_diagnostics", owner.read_text(encoding="utf-8"))
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.startup.service_launch_diagnostics import", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 760)

    def test_finalization_run_state_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "finalization_run_state.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "startup" / "finalization.py"

        self.assertTrue(owner.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        self.assertIn("def build_planning_dashboard_state", owner_text)
        self.assertIn("def _build_run_state", owner_text)
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.startup.finalization_run_state import", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 500)

    def test_resume_restore_policy_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "resume_restore_policy.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "startup" / "resume_restore_support.py"

        self.assertTrue(owner.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        self.assertIn("def _restore_parallel_config", owner_text)
        self.assertIn("def _requirements_reuse_decision", owner_text)
        self.assertIn("def _reserve_application_service_ports", owner_text)
        self.assertIn("def context_for_project", owner_text)
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.startup.resume_restore_policy import", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 650)

    def test_repo_local_launcher_is_python_script(self) -> None:
        launcher = REPO_ROOT / "bin" / "envctl"
        self.assertTrue(launcher.is_file())
        text = launcher.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("#!/usr/bin/env python3"))


if __name__ == "__main__":
    unittest.main()
