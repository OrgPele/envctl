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
        compose_owner = REPO_ROOT / "python" / "envctl_engine" / "requirements" / "supabase_lifecycle" / "compose.py"
        native_db_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "requirements" / "supabase_lifecycle" / "native_db.py"
        )
        compose_handoff_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "requirements" / "supabase_lifecycle" / "compose_handoff.py"
        )
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
        self.assertTrue(native_db_owner.is_file())
        self.assertTrue(compose_handoff_owner.is_file())
        self.assertTrue(service_owner.is_file())
        self.assertTrue(preflight_owner.is_file())
        self.assertIn("def complete_supabase_auth_startup", auth_owner.read_text(encoding="utf-8"))
        self.assertIn("def ensure_supabase_db_ready", db_owner.read_text(encoding="utf-8"))
        self.assertIn("def start_supabase_compose_graph", graph_owner.read_text(encoding="utf-8"))
        self.assertIn("class NativeSupabaseDatabaseStarter", native_db_owner.read_text(encoding="utf-8"))
        self.assertIn("compose_handoff", compose_owner.read_text(encoding="utf-8"))
        self.assertIn("def compose_up_handoff", compose_handoff_owner.read_text(encoding="utf-8"))
        self.assertLessEqual(len(compose_owner.read_text(encoding="utf-8").splitlines()), 340)
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
        docker_owner = REPO_ROOT / "python" / "envctl_engine" / "requirements" / "container_lifecycle_docker.py"
        state_owner = REPO_ROOT / "python" / "envctl_engine" / "requirements" / "container_lifecycle_state.py"
        probe_owner = REPO_ROOT / "python" / "envctl_engine" / "requirements" / "container_lifecycle_probe_phase.py"
        lifecycle_owner = REPO_ROOT / "python" / "envctl_engine" / "requirements" / "container_lifecycle_execution.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "requirements" / "adapter_base.py"

        self.assertTrue(policy_owner.is_file())
        self.assertTrue(cleanup_owner.is_file())
        self.assertTrue(model_owner.is_file())
        self.assertTrue(docker_owner.is_file())
        self.assertTrue(state_owner.is_file())
        self.assertTrue(probe_owner.is_file())
        self.assertTrue(lifecycle_owner.is_file())
        policy_text = policy_owner.read_text(encoding="utf-8")
        cleanup_text = cleanup_owner.read_text(encoding="utf-8")
        model_text = model_owner.read_text(encoding="utf-8")
        docker_text = docker_owner.read_text(encoding="utf-8")
        state_text = state_owner.read_text(encoding="utf-8")
        probe_text = probe_owner.read_text(encoding="utf-8")
        lifecycle_text = lifecycle_owner.read_text(encoding="utf-8")
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("def env_bool", policy_text)
        self.assertIn("def port_mismatch_policy", policy_text)
        self.assertIn("def cleanup_envctl_owned_port_containers", cleanup_text)
        self.assertIn("def format_bind_conflict_guidance", cleanup_text)
        self.assertIn("class AdapterLifecycleEvent", model_text)
        self.assertIn("class ContainerLifecycleTemplate", model_text)
        self.assertIn("class ContainerLifecycleDockerClient", docker_text)
        self.assertIn("class ContainerLifecycleState", state_text)
        self.assertIn("class ContainerLifecycleRecorder", state_text)
        self.assertIn("class ContainerLifecycleProbePhase", probe_text)
        self.assertIn("from envctl_engine.requirements.container_lifecycle_docker import", lifecycle_text)
        self.assertIn("from .container_lifecycle_probe_phase import", lifecycle_text)
        self.assertIn("from envctl_engine.requirements.container_lifecycle_state import", lifecycle_text)
        self.assertNotIn("class ContainerLifecycleDockerClient", lifecycle_text)
        self.assertNotIn("class ContainerLifecycleProbePhase", lifecycle_text)
        self.assertNotIn("class ContainerLifecycleRecorder", lifecycle_text)
        self.assertIn("class ContainerLifecycleExecutor", lifecycle_text)
        self.assertIn("def run_container_lifecycle", lifecycle_text)
        self.assertIn("def _run_readiness_probe_phase", lifecycle_text)
        self.assertIn("def _restart_after_probe_failure", lifecycle_text)
        self.assertIn("def _recreate_after_restart_failure", lifecycle_text)
        self.assertIn("from .adapter_policy import", facade_text)
        self.assertIn("from .adapter_port_cleanup import", facade_text)
        self.assertIn("from .adapter_lifecycle_models import", facade_text)
        self.assertIn("from .container_lifecycle_execution import", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 80)

    def test_external_dependency_facade_has_component_owners(self) -> None:
        mode_owner = REPO_ROOT / "python" / "envctl_engine" / "requirements" / "external_mode.py"
        env_owner = REPO_ROOT / "python" / "envctl_engine" / "requirements" / "external_env.py"
        probe_owner = REPO_ROOT / "python" / "envctl_engine" / "requirements" / "external_probe.py"
        outcome_owner = REPO_ROOT / "python" / "envctl_engine" / "requirements" / "external_outcome.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "requirements" / "external.py"

        self.assertTrue(mode_owner.is_file())
        self.assertTrue(env_owner.is_file())
        self.assertTrue(probe_owner.is_file())
        self.assertTrue(outcome_owner.is_file())

        mode_text = mode_owner.read_text(encoding="utf-8")
        env_text = env_owner.read_text(encoding="utf-8")
        probe_text = probe_owner.read_text(encoding="utf-8")
        outcome_text = outcome_owner.read_text(encoding="utf-8")
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("class ExternalDependencyModePolicy", mode_text)
        self.assertIn("class ExternalDependencyEnvResolver", env_text)
        self.assertIn("class ExternalDependencyProbe", probe_text)
        self.assertIn("def external_dependency_outcome", outcome_text)
        self.assertIn("from .external_mode import", facade_text)
        self.assertIn("from .external_env import", facade_text)
        self.assertIn("from .external_probe import", facade_text)
        self.assertIn("from .external_outcome import", facade_text)
        self.assertNotIn("socket.create_connection", facade_text)
        self.assertNotIn("urlopen(", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 80)

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
        self.assertNotIn("lambda worktree_root", facade_text)
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
        self.assertIn("class SharedTestCommandPlanner", command_text)
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
        suite_event_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_test_suite_event_support.py"
        suite_outcome_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_test_suite_outcome_support.py"
        )
        progress_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_test_runner_progress.py"
        failure_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_test_runner_failures.py"
        runner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_test_runner.py"

        self.assertTrue(execution_owner.is_file())
        self.assertTrue(suite_execution_owner.is_file())
        self.assertTrue(suite_event_owner.is_file())
        self.assertTrue(suite_outcome_owner.is_file())
        self.assertTrue(progress_owner.is_file())
        self.assertTrue(failure_owner.is_file())
        execution_text = execution_owner.read_text(encoding="utf-8")
        suite_execution_text = suite_execution_owner.read_text(encoding="utf-8")
        suite_event_text = suite_event_owner.read_text(encoding="utf-8")
        suite_outcome_text = suite_outcome_owner.read_text(encoding="utf-8")
        progress_text = progress_owner.read_text(encoding="utf-8")
        failure_text = failure_owner.read_text(encoding="utf-8")
        self.assertIn("class TestActionExecutionPlan", execution_text)
        self.assertIn("def build_test_action_execution_plan", execution_text)
        self.assertIn("def resolve_suite_spinner_decision", execution_text)
        self.assertIn("class TestSuiteExecutionResult", suite_execution_text)
        self.assertIn("class TestSuiteRunLoop", suite_execution_text)
        self.assertIn("def execute_test_suites", suite_execution_text)
        self.assertIn("class _TestSuiteExecutor", suite_execution_text)
        self.assertIn("class TestSuiteEventEmitter", suite_event_text)
        self.assertIn("def emit_summary", suite_event_text)
        self.assertIn("class TestSuiteOutcomeRecorder", suite_outcome_text)
        self.assertIn("def record", suite_outcome_text)
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
        command_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "actions_test_command_discovery.py"
        python_command_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "actions_test_python_discovery.py"
        package_command_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "actions_test_package_discovery.py"
        suggestion_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "actions_test_suggestions.py"
        bootstrap_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "actions_test_bootstrap.py"
        discovery = REPO_ROOT / "python" / "envctl_engine" / "actions" / "actions_test.py"

        self.assertTrue(models_owner.is_file())
        self.assertTrue(path_owner.is_file())
        self.assertTrue(classification_owner.is_file())
        self.assertTrue(command_owner.is_file())
        self.assertTrue(python_command_owner.is_file())
        self.assertTrue(package_command_owner.is_file())
        self.assertTrue(suggestion_owner.is_file())
        self.assertTrue(bootstrap_owner.is_file())
        self.assertIn("class TestCommandSpec", models_owner.read_text(encoding="utf-8"))
        self.assertIn("class TestPathSuggestion", models_owner.read_text(encoding="utf-8"))
        path_text = path_owner.read_text(encoding="utf-8")
        self.assertIn("def append_frontend_test_path", path_text)
        self.assertIn("def canonicalize_frontend_test_path", path_text)
        classification_text = classification_owner.read_text(encoding="utf-8")
        self.assertIn("def classify_test_command_source", classification_text)
        self.assertIn("def build_test_args", classification_text)
        command_text = command_owner.read_text(encoding="utf-8")
        self.assertIn("def test_command_suggestions", command_text)
        self.assertIn("def default_test_commands", command_text)
        self.assertIn("from envctl_engine.actions.actions_test_python_discovery import", command_text)
        self.assertIn("from envctl_engine.actions.actions_test_package_discovery import", command_text)
        self.assertIn("from envctl_engine.actions.actions_test_suggestions import", command_text)
        self.assertLessEqual(len(command_text.splitlines()), 330)
        python_command_text = python_command_owner.read_text(encoding="utf-8")
        self.assertIn("def backend_pytest_command", python_command_text)
        self.assertIn("def root_pytest_command", python_command_text)
        self.assertIn("def root_unittest_discover_command", python_command_text)
        package_command_text = package_command_owner.read_text(encoding="utf-8")
        self.assertIn("def package_manager_test_command", package_command_text)
        self.assertIn("def frontend_package_manager_test_command", package_command_text)
        self.assertIn("def package_manager_test_command_for_root", package_command_text)
        suggestion_text = suggestion_owner.read_text(encoding="utf-8")
        self.assertIn("def command_text", suggestion_text)
        self.assertIn("def test_command_suggestion", suggestion_text)
        bootstrap_text = bootstrap_owner.read_text(encoding="utf-8")
        self.assertIn("def ensure_repo_local_test_prereqs", bootstrap_text)
        self.assertIn("def bootstrap_python_executable", bootstrap_text)
        discovery_text = discovery.read_text(encoding="utf-8")
        self.assertIn("actions_test_models", discovery_text)
        self.assertIn("actions_test_frontend_paths", discovery_text)
        self.assertIn("actions_test_classification", discovery_text)
        self.assertIn("actions_test_command_discovery", discovery_text)
        self.assertIn("actions_test_bootstrap", discovery_text)
        self.assertLessEqual(len(discovery_text.splitlines()), 260)

    def test_action_test_planning_uses_explicit_planner_objects(self) -> None:
        plan_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_test_plan_support.py"
        service_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_test_service_support.py"

        plan_text = plan_owner.read_text(encoding="utf-8")
        service_text = service_owner.read_text(encoding="utf-8")
        self.assertIn("class TestExecutionPlanner", plan_text)
        self.assertIn("def build(self) -> list[TestExecutionSpec]", plan_text)
        self.assertIn("class AdditionalServiceTestPlanner", service_text)
        self.assertIn("def build(self) -> list[TestExecutionSpec]", service_text)

    def test_project_action_domain_has_output_and_artifact_owners(self) -> None:
        commit_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_commit_support.py"
        protected_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_protected_artifacts.py"
        pr_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_pr_message_support.py"
        review_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_review_output_support.py"
        review_artifact_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_review_artifact_support.py"
        )
        review_plan_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_review_plan_support.py"
        review_original_plan_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_review_original_plan_support.py"
        )
        review_base_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_review_base_support.py"
        review_iteration_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_review_iteration_support.py"
        )
        git_state_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_git_state_support.py"
        ship_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_ship_support.py"
        ship_contract_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_ship_contract.py"
        ship_conflicts_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_ship_conflicts.py"
        ship_checks_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_ship_checks.py"
        workflow_factory_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "actions" / "project_action_workflow_factory.py"
        )
        workflow_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "project_action_workflows.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "actions" / "project_action_domain.py"

        self.assertTrue(commit_owner.is_file())
        self.assertTrue(protected_owner.is_file())
        self.assertTrue(pr_owner.is_file())
        self.assertTrue(review_owner.is_file())
        self.assertTrue(review_artifact_owner.is_file())
        self.assertTrue(review_plan_owner.is_file())
        self.assertTrue(review_original_plan_owner.is_file())
        self.assertTrue(review_base_owner.is_file())
        self.assertTrue(review_iteration_owner.is_file())
        self.assertTrue(git_state_owner.is_file())
        self.assertTrue(ship_owner.is_file())
        self.assertTrue(ship_contract_owner.is_file())
        self.assertTrue(ship_conflicts_owner.is_file())
        self.assertTrue(ship_checks_owner.is_file())
        self.assertTrue(workflow_factory_owner.is_file())
        self.assertTrue(workflow_owner.is_file())
        commit_text = commit_owner.read_text(encoding="utf-8")
        self.assertIn("class CommitWorkflowRunner", commit_text)
        self.assertIn("class CommitWorkflowDependencies", commit_text)
        self.assertIn("def run_commit_workflow", commit_text)
        self.assertIn("def resolve_commit_message", commit_text)
        self.assertIn("def advance_commit_ledger_pointer", commit_text)
        self.assertIn("partition_envctl_protected_paths", protected_owner.read_text(encoding="utf-8"))
        pr_text = pr_owner.read_text(encoding="utf-8")
        self.assertIn("class PullRequestMessageBuilder", pr_text)
        self.assertIn("def pr_body", pr_text)
        self.assertIn("print_review_completion", review_owner.read_text(encoding="utf-8"))
        review_artifact_text = review_artifact_owner.read_text(encoding="utf-8")
        self.assertIn("def tree_changelog_path", review_artifact_text)
        self.assertIn("def summary_output_path", review_artifact_text)
        self.assertIn("def write_markdown_lines", review_artifact_text)
        self.assertIn("resolve_original_plan", review_original_plan_owner.read_text(encoding="utf-8"))
        self.assertIn("resolve_review_base", review_base_owner.read_text(encoding="utf-8"))
        self.assertIn("run_analyze_helper", review_iteration_owner.read_text(encoding="utf-8"))
        review_plan_text = review_plan_owner.read_text(encoding="utf-8")
        self.assertIn("action_review_original_plan_support", review_plan_text)
        self.assertIn("action_review_base_support", review_plan_text)
        self.assertIn("action_review_iteration_support", review_plan_text)
        self.assertLessEqual(len(review_plan_text.splitlines()), 180)
        git_state_text = git_state_owner.read_text(encoding="utf-8")
        self.assertIn("class DirtyWorktreeReport", git_state_text)
        self.assertIn("def probe_dirty_worktree", git_state_text)
        self.assertIn("def detect_default_branch", git_state_text)
        self.assertIn("def existing_pr_url", git_state_text)
        ship_text = ship_owner.read_text(encoding="utf-8")
        self.assertIn("class ShipWorkflowRunner", ship_text)
        self.assertIn("class ShipWorkflowDependencies", ship_text)
        self.assertIn("class ShipWorkflowState", ship_text)
        self.assertIn("def run_ship_workflow", ship_text)
        self.assertIn("def _run_commit_phase", ship_text)
        self.assertIn("def _run_pr_phase", ship_text)
        self.assertIn("def _run_checks_phase", ship_text)
        self.assertIn("action_ship_contract", ship_text)
        self.assertIn("action_ship_conflicts", ship_text)
        self.assertIn("action_ship_checks", ship_text)
        self.assertIn("def ship_payload", ship_contract_owner.read_text(encoding="utf-8"))
        self.assertIn("def print_ship_result", ship_contract_owner.read_text(encoding="utf-8"))
        self.assertIn("def predicted_merge_conflict_report", ship_conflicts_owner.read_text(encoding="utf-8"))
        self.assertIn("def normalize_github_pr_checks", ship_checks_owner.read_text(encoding="utf-8"))
        self.assertLessEqual(len(ship_text.splitlines()), 320)
        workflow_text = workflow_owner.read_text(encoding="utf-8")
        workflow_factory_text = workflow_factory_owner.read_text(encoding="utf-8")
        self.assertIn("class ProjectActionWorkflowFactory", workflow_factory_text)
        self.assertIn("class ProjectActionWorkflowRunner", workflow_text)
        self.assertIn("class ProjectActionGitWorkflowDependencies", workflow_text)
        self.assertIn("class ProjectActionCommitWorkflowDependencies", workflow_text)
        self.assertIn("class ProjectActionPullRequestWorkflowDependencies", workflow_text)
        self.assertIn("class ProjectActionReviewWorkflowDependencies", workflow_text)
        self.assertIn("def run_commit_action", workflow_text)
        self.assertIn("def run_pr_action", workflow_text)
        self.assertIn("def run_ship_action", workflow_text)
        self.assertIn("def run_review_action", workflow_text)
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("action_commit_support", facade_text)
        self.assertIn("action_protected_artifacts", facade_text)
        self.assertIn("action_pr_message_support", facade_text)
        self.assertIn("action_review_artifact_support", facade_text)
        self.assertIn("action_review_output_support", facade_text)
        self.assertIn("action_review_plan_support", facade_text)
        self.assertIn("action_git_state_support", facade_text)
        self.assertIn("action_ship_support", facade_text)
        self.assertIn("project_action_workflow_factory", facade_text)
        self.assertIn("project_action_workflows", facade_text)
        self.assertNotIn("class ProjectActionWorkflowFactory", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 480)

    def test_action_migrate_support_is_split_by_responsibility(self) -> None:
        context_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_migrate_context_support.py"
        failure_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_migrate_failure_support.py"
        result_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_migrate_result_support.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_migrate_support.py"

        self.assertTrue(context_owner.is_file())
        self.assertTrue(failure_owner.is_file())
        self.assertTrue(result_owner.is_file())
        self.assertIn("def migrate_project_context", context_owner.read_text(encoding="utf-8"))
        self.assertIn("def migrate_failure_hint_lines", failure_owner.read_text(encoding="utf-8"))
        self.assertIn("def print_migrate_result_records", result_owner.read_text(encoding="utf-8"))
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("action_migrate_context_support", facade_text)
        self.assertIn("action_migrate_failure_support", facade_text)
        self.assertIn("action_migrate_result_support", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 120)

    def test_project_action_support_has_report_owner(self) -> None:
        env_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "project_action_env_support.py"
        execution_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "actions" / "project_action_execution_support.py"
        )
        report_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "project_action_report_support.py"
        owner_facade = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_project_report_owner.py"
        support = REPO_ROOT / "python" / "envctl_engine" / "actions" / "project_action_support.py"

        self.assertTrue(env_owner.is_file())
        self.assertTrue(execution_owner.is_file())
        self.assertTrue(report_owner.is_file())
        env_text = env_owner.read_text(encoding="utf-8")
        self.assertIn("def action_env", env_text)
        self.assertIn("def test_action_extra_env", env_text)
        self.assertIn("def migrate_action_env", env_text)
        execution_text = execution_owner.read_text(encoding="utf-8")
        self.assertIn("class ProjectActionRunner", execution_text)
        self.assertIn("def run_project_action", execution_text)
        self.assertIn("def resolve_command", execution_text)
        self.assertIn("def process_run", execution_text)
        report_text = report_owner.read_text(encoding="utf-8")
        self.assertIn("def build_project_action_success_handler", report_text)
        self.assertIn("def persist_project_action_result", report_text)
        self.assertIn("def review_success_artifact_paths", report_text)
        self.assertIn("def write_project_action_failure_report", report_text)
        self.assertIn("project_action_report_support", owner_facade.read_text(encoding="utf-8"))
        support_text = support.read_text(encoding="utf-8")
        self.assertIn("project_action_env_support", support_text)
        self.assertIn("project_action_execution_support", support_text)
        self.assertIn("project_action_report_support", support_text)
        self.assertLessEqual(len(support_text.splitlines()), 60)

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
        docker_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "lifecycle_blast_docker.py"
        process_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "lifecycle_blast_processes.py"
        orchestrator = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "lifecycle_cleanup_orchestrator.py"

        self.assertTrue(owner.is_file())
        self.assertTrue(docker_owner.is_file())
        self.assertTrue(process_owner.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        docker_owner_text = docker_owner.read_text(encoding="utf-8")
        process_owner_text = process_owner.read_text(encoding="utf-8")
        self.assertIn("class LifecycleBlastCleanupSupport", owner_text)
        self.assertIn("from envctl_engine.runtime.lifecycle_blast_docker import", owner_text)
        self.assertIn("from envctl_engine.runtime.lifecycle_blast_processes import", owner_text)
        self.assertIn("def blast_all_docker_cleanup", docker_owner_text)
        self.assertIn("def blast_all_kill_orchestrator_processes", process_owner_text)
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

    def test_config_dependency_env_templates_have_owned_module(self) -> None:
        models_owner = REPO_ROOT / "python" / "envctl_engine" / "config" / "models.py"
        command_defaults_owner = REPO_ROOT / "python" / "envctl_engine" / "config" / "command_defaults.py"
        defaults_owner = REPO_ROOT / "python" / "envctl_engine" / "config" / "defaults.py"
        service_parsing_owner = REPO_ROOT / "python" / "envctl_engine" / "config" / "service_parsing.py"
        persistence_values_owner = REPO_ROOT / "python" / "envctl_engine" / "config" / "persistence_values.py"
        persistence_payload_owner = REPO_ROOT / "python" / "envctl_engine" / "config" / "persistence_payload.py"
        persistence_rendering_owner = REPO_ROOT / "python" / "envctl_engine" / "config" / "persistence_rendering.py"
        source_discovery_owner = REPO_ROOT / "python" / "envctl_engine" / "config" / "source_discovery.py"
        persistence_facade = REPO_ROOT / "python" / "envctl_engine" / "config" / "persistence.py"
        owner = REPO_ROOT / "python" / "envctl_engine" / "config" / "dependency_env_templates.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "config" / "__init__.py"

        self.assertTrue(models_owner.is_file())
        self.assertTrue(command_defaults_owner.is_file())
        self.assertTrue(defaults_owner.is_file())
        self.assertTrue(service_parsing_owner.is_file())
        self.assertTrue(persistence_values_owner.is_file())
        self.assertTrue(persistence_payload_owner.is_file())
        self.assertTrue(persistence_rendering_owner.is_file())
        self.assertTrue(source_discovery_owner.is_file())
        self.assertTrue(owner.is_file())
        models_text = models_owner.read_text(encoding="utf-8")
        self.assertIn("class EngineConfig", models_text)
        self.assertIn("class LocalConfigState", models_text)
        self.assertIn("class StartupProfile", models_text)
        command_defaults_text = command_defaults_owner.read_text(encoding="utf-8")
        self.assertIn("def resolved_backend_dir_name", command_defaults_text)
        self.assertIn("def resolved_backend_test_cmd", command_defaults_text)
        self.assertIn("def resolved_frontend_test_path", command_defaults_text)
        defaults_text = defaults_owner.read_text(encoding="utf-8")
        self.assertIn("DEFAULTS: dict[str, str]", defaults_text)
        self.assertIn("MANAGED_CONFIG_KEYS", defaults_text)
        service_parsing_text = service_parsing_owner.read_text(encoding="utf-8")
        self.assertIn("def _parse_additional_services", service_parsing_text)
        self.assertIn("def _parse_supabase_auth_users", service_parsing_text)
        self.assertIn("def _validate_additional_service_dependencies", service_parsing_text)
        persistence_values_text = persistence_values_owner.read_text(encoding="utf-8")
        self.assertIn("class ManagedConfigValues", persistence_values_text)
        self.assertIn("def managed_values_from_payload", persistence_values_text)
        self.assertIn("def validate_managed_values", persistence_values_text)
        persistence_payload_text = persistence_payload_owner.read_text(encoding="utf-8")
        self.assertIn("class ConfigPayloadHydrator", persistence_payload_text)
        self.assertIn("def hydrate", persistence_payload_text)
        persistence_rendering_text = persistence_rendering_owner.read_text(encoding="utf-8")
        self.assertIn("def render_managed_block", persistence_rendering_text)
        self.assertIn("def merge_managed_block", persistence_rendering_text)
        self.assertIn("def config_review_text", persistence_rendering_text)
        source_discovery_text = source_discovery_owner.read_text(encoding="utf-8")
        self.assertIn("def discover_local_config_state", source_discovery_text)
        self.assertIn("def generated_worktree_control_root", source_discovery_text)
        self.assertIn("def parse_envctl_text", source_discovery_text)
        persistence_facade_text = persistence_facade.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.config.persistence_values import", persistence_facade_text)
        self.assertIn("from envctl_engine.config.persistence_rendering import", persistence_facade_text)
        self.assertLessEqual(len(persistence_facade_text.splitlines()), 260)
        owner_text = owner.read_text(encoding="utf-8")
        self.assertIn("class DependencyEnvTemplateEntry", owner_text)
        self.assertIn("def parse_dependency_env_section", owner_text)
        self.assertIn("def ensure_dependency_env_section", owner_text)
        self.assertIn("def _strip_template_sections", owner_text)
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.config.dependency_env_templates import", facade_text)
        self.assertIn("from envctl_engine.config.models import", facade_text)
        self.assertIn("from envctl_engine.config.command_defaults import", facade_text)
        self.assertIn("from envctl_engine.config.defaults import", facade_text)
        self.assertIn("from envctl_engine.config.service_parsing import", facade_text)
        self.assertIn("from envctl_engine.config.source_discovery import", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 685)

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

    def test_process_runner_has_launch_and_lifecycle_owners(self) -> None:
        shared = REPO_ROOT / "python" / "envctl_engine" / "shared"
        runner = shared / "process_runner.py"
        launch_owner = shared / "process_launch_support.py"
        lifecycle_owner = shared / "process_lifecycle_probe.py"

        self.assertTrue(launch_owner.is_file())
        self.assertTrue(lifecycle_owner.is_file())
        launch_text = launch_owner.read_text(encoding="utf-8")
        lifecycle_text = lifecycle_owner.read_text(encoding="utf-8")
        runner_text = runner.read_text(encoding="utf-8")
        self.assertIn("class LaunchRecord", launch_text)
        self.assertIn("class ProcessLaunchMixin", launch_text)
        self.assertIn("def start_background", launch_text)
        self.assertIn("def launch_diagnostics_summary", launch_text)
        self.assertIn("class ProcessLifecycleProbeMixin", lifecycle_text)
        self.assertIn("def wait_for_port", lifecycle_text)
        self.assertIn("def process_tree_listener_pids", lifecycle_text)
        self.assertIn("def terminate_process_group", lifecycle_text)
        self.assertIn("ProcessLaunchMixin", runner_text)
        self.assertIn("ProcessLifecycleProbeMixin", runner_text)
        self.assertLessEqual(len(runner_text.splitlines()), 340)

    def test_debug_bundle_diagnostics_has_selector_and_startup_owners(self) -> None:
        debug = REPO_ROOT / "python" / "envctl_engine" / "debug"
        facade = debug / "debug_bundle_diagnostics.py"
        selector_owner = debug / "debug_bundle_selector_diagnostics.py"
        startup_owner = debug / "debug_bundle_startup_diagnostics.py"

        self.assertTrue(selector_owner.is_file())
        self.assertTrue(startup_owner.is_file())
        selector_text = selector_owner.read_text(encoding="utf-8")
        startup_text = startup_owner.read_text(encoding="utf-8")
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("class SelectorDiagnostics", selector_text)
        self.assertIn("def analyze_selector_diagnostics", selector_text)
        self.assertIn("class StartupDiagnostics", startup_text)
        self.assertIn("def analyze_startup_diagnostics", startup_text)
        self.assertIn("analyze_selector_diagnostics", facade_text)
        self.assertIn("analyze_startup_diagnostics", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 380)

    def test_command_loop_has_spinner_owner(self) -> None:
        ui = REPO_ROOT / "python" / "envctl_engine" / "ui"
        loop = ui / "command_loop.py"
        owner = ui / "command_loop_spinner.py"

        self.assertTrue(owner.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        self.assertIn("class CommandSpinnerTracker", owner_text)
        self.assertIn("def install_spinner_event_bridge", owner_text)
        self.assertIn("def spinner_message_for_event", owner_text)
        self.assertIn("def spinner_failure_message_for_event", owner_text)
        loop_text = loop.read_text(encoding="utf-8")
        self.assertIn("command_loop_spinner", loop_text)
        self.assertNotIn("class _SpinnerTracker", loop_text)
        self.assertLessEqual(len(loop_text.splitlines()), 500)

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
        policy_owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "plan_agent" / "launch_policy.py"
        config_facade = REPO_ROOT / "python" / "envctl_engine" / "planning" / "plan_agent" / "config.py"
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
            "test_plan_agent_launch_policy.py",
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

        self.assertTrue(policy_owner.is_file())
        self.assertIn("class PlanAgentLaunchPolicy", policy_owner.read_text(encoding="utf-8"))
        config_text = config_facade.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.planning.plan_agent.launch_policy import", config_text)
        self.assertLessEqual(len(config_text.splitlines()), 140)

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
        input_owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "command_input_support.py"
        command_mixin = (
            REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "orchestrator_command_mixin.py"
        )
        failure_mixin = (
            REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "orchestrator_failure_mixin.py"
        )
        target_mixin = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "orchestrator_target_mixin.py"
        stop_mixin = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "orchestrator_stop_mixin.py"
        pr_mixin = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "orchestrator_pr_mixin.py"
        restart_mixin = (
            REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "orchestrator_restart_mixin.py"
        )
        target_owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "project_target_support.py"
        selection_owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "target_selection_support.py"
        service_catalog_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "target_service_catalog.py"
        )
        review_tab_owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "review_tab_support.py"
        pr_selection_owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "pr_selection_support.py"
        pr_commit_owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "pr_commit_support.py"
        pr_scope_owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "pr_scope_support.py"
        stop_owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "stop_scope_support.py"
        pr_facade = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "pr_and_target_support.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "orchestrator.py"

        self.assertTrue(owner.is_file())
        self.assertTrue(input_owner.is_file())
        self.assertTrue(command_mixin.is_file())
        self.assertTrue(failure_mixin.is_file())
        self.assertTrue(target_mixin.is_file())
        self.assertTrue(stop_mixin.is_file())
        self.assertTrue(pr_mixin.is_file())
        self.assertTrue(restart_mixin.is_file())
        self.assertTrue(target_owner.is_file())
        self.assertTrue(selection_owner.is_file())
        self.assertTrue(service_catalog_owner.is_file())
        self.assertTrue(review_tab_owner.is_file())
        self.assertTrue(pr_selection_owner.is_file())
        self.assertTrue(pr_commit_owner.is_file())
        self.assertTrue(pr_scope_owner.is_file())
        self.assertTrue(stop_owner.is_file())
        pr_facade_text = pr_facade.read_text(encoding="utf-8")
        facade_text = facade.read_text(encoding="utf-8")
        owner_text = owner.read_text(encoding="utf-8")
        input_owner_text = input_owner.read_text(encoding="utf-8")
        command_mixin_text = command_mixin.read_text(encoding="utf-8")
        failure_mixin_text = failure_mixin.read_text(encoding="utf-8")
        target_mixin_text = target_mixin.read_text(encoding="utf-8")
        stop_mixin_text = stop_mixin.read_text(encoding="utf-8")
        pr_mixin_text = pr_mixin.read_text(encoding="utf-8")
        restart_mixin_text = restart_mixin.read_text(encoding="utf-8")
        self.assertIn("def run_interactive_command", owner_text)
        self.assertIn("def dashboard_hidden_commands", owner_text)
        self.assertIn("command_input_support", owner_text)
        self.assertIn("def prompt_text_dialog", input_owner_text)
        self.assertIn("def dispatch_kill_session", input_owner_text)
        self.assertIn("def repo_root_for_project", input_owner_text)
        self.assertIn("class DashboardCommandMixin", command_mixin_text)
        self.assertIn("def _run_interactive_command", command_mixin_text)
        self.assertIn("def _sanitize_interactive_input", command_mixin_text)
        self.assertIn("class DashboardFailureDetailMixin", failure_mixin_text)
        self.assertIn("def _print_interactive_failure_details", failure_mixin_text)
        self.assertIn("def _print_migrate_result_details", failure_mixin_text)
        self.assertIn("class DashboardTargetSelectionMixin", target_mixin_text)
        self.assertIn("def _select_dashboard_projects", target_mixin_text)
        self.assertIn("class DashboardStopScopeMixin", stop_mixin_text)
        self.assertIn("def _apply_stop_scope_selection", stop_mixin_text)
        self.assertIn("class DashboardPrFlowMixin", pr_mixin_text)
        self.assertIn("def _apply_pr_selection", pr_mixin_text)
        self.assertIn("class DashboardRestartSelectionMixin", restart_mixin_text)
        self.assertIn("def _apply_restart_selection", restart_mixin_text)
        selection_owner_text = selection_owner.read_text(encoding="utf-8")
        service_catalog_text = service_catalog_owner.read_text(encoding="utf-8")
        self.assertIn("def apply_interactive_target_selection", selection_owner_text)
        self.assertIn("class DashboardServiceCatalog", service_catalog_text)
        self.assertIn("def available_service_types", service_catalog_text)
        self.assertIn("def service_names_for_types", service_catalog_text)
        self.assertIn("def apply_pr_selection", pr_selection_owner.read_text(encoding="utf-8"))
        self.assertIn("def maybe_prepare_pr_commit", pr_commit_owner.read_text(encoding="utf-8"))
        self.assertIn("def dirty_pr_reports", pr_scope_owner.read_text(encoding="utf-8"))
        self.assertIn("class DashboardPrDependencies", pr_facade_text)
        self.assertNotIn("pr_and_target_support.probe_dirty_worktree =", facade_text)
        self.assertNotIn("pr_and_target_support.launch_review_agent_terminal =", facade_text)
        self.assertNotIn("pr_and_target_support._run_selector_with_impl =", facade_text)
        self.assertNotIn("target_selection_support._tree_preselected_projects_from_state_impl =", facade_text)
        self.assertIn("def apply_stop_resource_tokens", stop_owner.read_text(encoding="utf-8"))
        self.assertIn("pr_selection_support", pr_facade_text)
        self.assertIn("pr_commit_support", pr_facade_text)
        self.assertIn("pr_scope_support", pr_facade_text)
        self.assertLessEqual(len(pr_facade_text.splitlines()), 235)
        self.assertLessEqual(len(owner_text.splitlines()), 220)
        self.assertIn("DashboardCommandMixin", facade_text)
        self.assertIn("DashboardFailureDetailMixin", facade_text)
        self.assertIn("DashboardTargetSelectionMixin", facade_text)
        self.assertIn("DashboardStopScopeMixin", facade_text)
        self.assertIn("DashboardPrFlowMixin", facade_text)
        self.assertIn("DashboardRestartSelectionMixin", facade_text)
        self.assertNotIn("from envctl_engine.ui.dashboard import project_target_support", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 120)

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
            "test_dashboard_snapshot_support.py",
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
        snapshot_owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "snapshot_support.py"
        rendering = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "rendering.py"

        self.assertTrue(owner.is_file())
        self.assertTrue(snapshot_owner.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        self.assertIn("def print_dashboard_service_row", owner_text)
        self.assertIn("def print_dashboard_additional_service_rows", owner_text)
        self.assertIn("def dashboard_visible_stopped_service_count", owner_text)
        snapshot_text = snapshot_owner.read_text(encoding="utf-8")
        self.assertIn("class DashboardSnapshotModel", snapshot_text)
        self.assertIn("def build_dashboard_snapshot_model", snapshot_text)
        rendering_text = rendering.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.ui.dashboard import service_rendering", rendering_text)
        self.assertLessEqual(len(rendering_text.splitlines()), 745)

    def test_dashboard_rendering_has_snapshot_printer_owner(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "snapshot_rendering.py"
        rendering = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "rendering.py"

        self.assertTrue(owner.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        self.assertIn("class DashboardSnapshotPrinter", owner_text)
        self.assertIn("class DashboardSnapshotRenderHooks", owner_text)
        self.assertIn("def print_snapshot", owner_text)
        self.assertIn("from envctl_engine.ui.dashboard.snapshot_support import build_dashboard_snapshot_model", owner_text)
        rendering_text = rendering.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.ui.dashboard import snapshot_rendering", rendering_text)
        self.assertIn("DashboardSnapshotRenderHooks", rendering_text)
        self.assertLessEqual(len(rendering_text.splitlines()), 540)

    def test_bats_harness_is_absent(self) -> None:
        self.assertFalse((REPO_ROOT / "tests" / "bats").exists())

    def test_terminal_session_has_tty_mode_owner(self) -> None:
        facade = REPO_ROOT / "python" / "envctl_engine" / "ui" / "terminal_session.py"
        owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "terminal_tty_modes.py"
        stream_owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "terminal_input_stream.py"

        self.assertTrue(owner.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        self.assertIn("def restore_terminal_after_input", owner_text)
        self.assertIn("def temporary_tty_character_mode", owner_text)
        self.assertIn("def normalize_standard_tty_state", owner_text)
        self.assertIn("def temporary_standard_output_pendin", owner_text)
        self.assertIn("def _standard_output_tty_fds", owner_text)
        self.assertTrue(stream_owner.is_file())
        stream_text = stream_owner.read_text(encoding="utf-8")
        self.assertIn("class TerminalInputBuffer", stream_text)
        self.assertIn("def read_line_from_fd", stream_text)
        self.assertIn("def discard_stale_control_sequences", stream_text)
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("from .terminal_tty_modes import", facade_text)
        self.assertIn("from . import terminal_input_stream", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 620)

    def test_textual_planning_selector_has_model_owner(self) -> None:
        selector = REPO_ROOT / "python" / "envctl_engine" / "ui" / "textual" / "screens" / "planning_selector.py"
        model_owner = (
            REPO_ROOT
            / "python"
            / "envctl_engine"
            / "ui"
            / "textual"
            / "screens"
            / "planning_selector_model.py"
        )

        self.assertTrue(model_owner.is_file())
        selector_text = selector.read_text(encoding="utf-8")
        model_text = model_owner.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.ui.textual.screens.planning_selector_model import", selector_text)
        self.assertIn("class PlanningRow", model_text)
        self.assertIn("class PlanningSelectionModel", model_text)
        self.assertIn("def render_entries", model_text)
        self.assertIn("def status_text", model_text)
        self.assertIn("def result", model_text)
        self.assertLessEqual(len(selector_text.splitlines()), 560)

    def test_textual_config_wizard_has_field_owner(self) -> None:
        screen = REPO_ROOT / "python" / "envctl_engine" / "ui" / "textual" / "screens" / "config_wizard.py"
        app_owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "textual" / "screens" / "config_wizard_app.py"
        component_owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "textual" / "screens" / "config_wizard_components.py"
        component_actions_owner = (
            REPO_ROOT
            / "python"
            / "envctl_engine"
            / "ui"
            / "textual"
            / "screens"
            / "config_wizard_component_actions.py"
        )
        action_bundle_owner = (
            REPO_ROOT
            / "python"
            / "envctl_engine"
            / "ui"
            / "textual"
            / "screens"
            / "config_wizard_action_bundle.py"
        )
        owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "textual" / "screens" / "config_wizard_fields.py"
        hint_owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "textual" / "screens" / "config_wizard_hints.py"
        form_owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "textual" / "screens" / "config_wizard_form.py"
        value_owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "textual" / "screens" / "config_wizard_values.py"
        status_owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "textual" / "screens" / "config_wizard_status.py"
        layout_owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "textual" / "screens" / "config_wizard_layout.py"
        navigation_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "ui" / "textual" / "screens" / "config_wizard_navigation.py"
        )
        list_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "ui" / "textual" / "screens" / "config_wizard_list_rendering.py"
        )
        step_owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "textual" / "screens" / "config_wizard_step_flow.py"
        suggestion_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "ui" / "textual" / "screens" / "config_wizard_suggestions.py"
        )
        suggestion_actions_owner = (
            REPO_ROOT
            / "python"
            / "envctl_engine"
            / "ui"
            / "textual"
            / "screens"
            / "config_wizard_suggestion_actions.py"
        )
        flow_actions_owner = (
            REPO_ROOT
            / "python"
            / "envctl_engine"
            / "ui"
            / "textual"
            / "screens"
            / "config_wizard_flow_actions.py"
        )
        focus_actions_owner = (
            REPO_ROOT
            / "python"
            / "envctl_engine"
            / "ui"
            / "textual"
            / "screens"
            / "config_wizard_focus_actions.py"
        )
        body_actions_owner = (
            REPO_ROOT
            / "python"
            / "envctl_engine"
            / "ui"
            / "textual"
            / "screens"
            / "config_wizard_body_actions.py"
        )

        self.assertTrue(app_owner.is_file())
        self.assertTrue(component_owner.is_file())
        self.assertTrue(component_actions_owner.is_file())
        self.assertTrue(action_bundle_owner.is_file())
        self.assertTrue(owner.is_file())
        self.assertTrue(hint_owner.is_file())
        self.assertTrue(form_owner.is_file())
        self.assertTrue(value_owner.is_file())
        self.assertTrue(status_owner.is_file())
        self.assertTrue(layout_owner.is_file())
        self.assertTrue(navigation_owner.is_file())
        self.assertTrue(list_owner.is_file())
        self.assertTrue(step_owner.is_file())
        self.assertTrue(suggestion_owner.is_file())
        self.assertTrue(suggestion_actions_owner.is_file())
        self.assertTrue(flow_actions_owner.is_file())
        self.assertTrue(focus_actions_owner.is_file())
        self.assertTrue(body_actions_owner.is_file())
        app_text = app_owner.read_text(encoding="utf-8")
        component_text = component_owner.read_text(encoding="utf-8")
        component_actions_text = component_actions_owner.read_text(encoding="utf-8")
        action_bundle_text = action_bundle_owner.read_text(encoding="utf-8")
        owner_text = owner.read_text(encoding="utf-8")
        hint_text = hint_owner.read_text(encoding="utf-8")
        form_text = form_owner.read_text(encoding="utf-8")
        value_text = value_owner.read_text(encoding="utf-8")
        status_text = status_owner.read_text(encoding="utf-8")
        layout_text = layout_owner.read_text(encoding="utf-8")
        navigation_text = navigation_owner.read_text(encoding="utf-8")
        list_text = list_owner.read_text(encoding="utf-8")
        step_text = step_owner.read_text(encoding="utf-8")
        suggestion_text = suggestion_owner.read_text(encoding="utf-8")
        suggestion_actions_text = suggestion_actions_owner.read_text(encoding="utf-8")
        flow_actions_text = flow_actions_owner.read_text(encoding="utf-8")
        focus_actions_text = focus_actions_owner.read_text(encoding="utf-8")
        body_actions_text = body_actions_owner.read_text(encoding="utf-8")
        self.assertIn("class ConfigWizardResult", app_text)
        self.assertIn("def build_config_wizard_app", app_text)
        self.assertIn("class ConfigWizardApp", app_text)
        self.assertIn("class ComponentRow", component_text)
        self.assertIn("class ConfigWizardComponentInteraction", component_text)
        self.assertIn("def toggle_component_at", component_text)
        self.assertIn("def toggle_split_at", component_text)
        self.assertIn("def component_rows", component_text)
        self.assertIn("def toggle_service_startup_value", component_text)
        self.assertIn("class ConfigWizardComponentActions", component_actions_text)
        self.assertIn("def toggle_components_row", component_actions_text)
        self.assertIn("def toggle_service_startup_row", component_actions_text)
        self.assertIn("def component_split_available", component_actions_text)
        self.assertIn("class ConfigWizardActionBundle", action_bundle_text)
        self.assertIn("def body", action_bundle_text)
        self.assertIn("def component", action_bundle_text)
        self.assertIn("def suggestions", action_bundle_text)
        self.assertIn("def flow", action_bundle_text)
        self.assertIn("def focus", action_bundle_text)
        self.assertIn("def _hydrate_wizard_values", owner_text)
        self.assertIn("def _visible_directory_fields", owner_text)
        self.assertIn("def _additional_service_field_value", owner_text)
        self.assertIn("def build_additional_service_from_input_values", owner_text)
        self.assertIn("class ConfigWizardHintResolver", hint_text)
        self.assertIn("def directory_validation_error", hint_text)
        self.assertIn("def field_hint_text", hint_text)
        self.assertIn("class ConfigWizardFormController", form_text)
        self.assertIn("def sync_directory_inputs", form_text)
        self.assertIn("def apply_additional_service_inputs", form_text)
        self.assertIn("def apply_port_inputs", form_text)
        self.assertIn("class ConfigWizardValueApplyResult", value_text)
        self.assertIn("def wizard_field_value", value_text)
        self.assertIn("def apply_text_field_values", value_text)
        self.assertIn("def apply_port_field_values", value_text)
        self.assertIn("def status_for_valid_config_step", status_text)
        self.assertIn("def resolve_config_wizard_status", status_text)
        self.assertIn("def resolve_config_wizard_action_state", status_text)
        self.assertIn("CONFIG_WIZARD_APP_CSS", layout_text)
        self.assertIn("def compose_config_wizard_layout", layout_text)
        self.assertIn("class ConfigWizardKeyDecision", navigation_text)
        self.assertIn("def resolve_config_wizard_key", navigation_text)
        self.assertIn("def move_config_wizard_list_index", navigation_text)
        self.assertIn("def render_components_list", list_text)
        self.assertIn("def sync_wizard_steps", step_text)
        self.assertIn("def build_config_wizard_suggestions", suggestion_text)
        self.assertIn("def cycle_config_wizard_suggestion", suggestion_text)
        self.assertIn("def emit_detected_config_wizard_suggestions", suggestion_text)
        self.assertIn("class ConfigWizardSuggestionActions", suggestion_actions_text)
        self.assertIn("def focused_suggestion_field", suggestion_actions_text)
        self.assertIn("def cycle_command_suggestion", suggestion_actions_text)
        self.assertIn("class ConfigWizardFlowActions", flow_actions_text)
        self.assertIn("def submit_or_next", flow_actions_text)
        self.assertIn("def advance", flow_actions_text)
        self.assertIn("class ConfigWizardFocusActions", focus_actions_text)
        self.assertIn("def focus_current_step", focus_actions_text)
        self.assertIn("class ConfigWizardBodyActions", body_actions_text)
        self.assertIn("def refresh_body", body_actions_text)
        screen_text = screen.read_text(encoding="utf-8")
        self.assertIn("from .config_wizard_app import ConfigWizardResult, _emit, build_config_wizard_app", screen_text)
        self.assertIn("from . import config_wizard_components as component_policy", app_text)
        self.assertIn("from .config_wizard_action_bundle import ConfigWizardActionBundle", app_text)
        self.assertIn("from .config_wizard_component_actions import ConfigWizardComponentActions", action_bundle_text)
        self.assertIn("from . import config_wizard_values as value_policy", app_text)
        self.assertIn("from .config_wizard_fields import", screen_text)
        self.assertIn("from .config_wizard_fields import", app_text)
        self.assertIn("from .config_wizard_form import ConfigWizardFormController", app_text)
        self.assertIn("from .config_wizard_hints import", app_text)
        self.assertIn("from .config_wizard_layout import", app_text)
        self.assertIn("from .config_wizard_navigation import", app_text)
        self.assertIn("from .config_wizard_status import", app_text)
        self.assertIn("from .config_wizard_list_rendering import", app_text)
        self.assertIn("from .config_wizard_step_flow import", app_text)
        self.assertIn(
            "from .config_wizard_suggestion_actions import ConfigWizardSuggestionActions", action_bundle_text
        )
        self.assertIn("from .config_wizard_suggestions import", app_text)
        self.assertIn("from .config_wizard_flow_actions import ConfigWizardFlowActions", action_bundle_text)
        self.assertIn("from .config_wizard_focus_actions import ConfigWizardFocusActions", action_bundle_text)
        self.assertIn("from .config_wizard_body_actions import ConfigWizardBodyActions", action_bundle_text)
        self.assertLessEqual(len(screen_text.splitlines()), 90)
        self.assertLessEqual(len(app_text.splitlines()), 825)

    def test_textual_selector_has_backend_policy_owner(self) -> None:
        selector = REPO_ROOT / "python" / "envctl_engine" / "ui" / "textual" / "screens" / "selector"
        support = selector / "support.py"
        io_probe = selector / "io_probe.py"
        backend_policy = selector / "backend_policy.py"
        read_guard = selector / "read_guard.py"
        textual_driver = selector / "textual_driver_instrumentation.py"
        prompt_toolkit_io = selector / "prompt_toolkit_io_instrumentation.py"
        app_key_trace = selector / "textual_app_key_trace.py"
        focus_actions = selector / "textual_app_focus_actions.py"
        key_actions = selector / "textual_app_key_actions.py"
        initial_navigation = selector / "textual_app_initial_navigation.py"
        navigation_actions = selector / "textual_app_navigation_actions.py"
        selection_actions = selector / "textual_app_selection_actions.py"
        key_telemetry = selector / "textual_key_telemetry.py"
        textual_app = selector / "textual_app.py"
        selection_state = selector / "selection_state.py"
        app_runtime = selector / "textual_app_runtime.py"
        key_policy = selector / "textual_key_policy.py"

        self.assertTrue(support.is_file())
        self.assertTrue(io_probe.is_file())
        self.assertTrue(backend_policy.is_file())
        self.assertTrue(read_guard.is_file())
        self.assertTrue(textual_driver.is_file())
        self.assertTrue(prompt_toolkit_io.is_file())
        self.assertTrue(app_key_trace.is_file())
        self.assertTrue(focus_actions.is_file())
        self.assertTrue(key_actions.is_file())
        self.assertTrue(initial_navigation.is_file())
        self.assertTrue(navigation_actions.is_file())
        self.assertTrue(selection_actions.is_file())
        self.assertTrue(key_telemetry.is_file())
        self.assertTrue(textual_app.is_file())
        self.assertTrue(selection_state.is_file())
        self.assertTrue(app_runtime.is_file())
        self.assertTrue(key_policy.is_file())
        support_text = support.read_text(encoding="utf-8")
        io_probe_text = io_probe.read_text(encoding="utf-8")
        backend_text = backend_policy.read_text(encoding="utf-8")
        read_guard_text = read_guard.read_text(encoding="utf-8")
        textual_driver_text = textual_driver.read_text(encoding="utf-8")
        prompt_toolkit_text = prompt_toolkit_io.read_text(encoding="utf-8")
        app_key_trace_text = app_key_trace.read_text(encoding="utf-8")
        focus_actions_text = focus_actions.read_text(encoding="utf-8")
        key_actions_text = key_actions.read_text(encoding="utf-8")
        initial_navigation_text = initial_navigation.read_text(encoding="utf-8")
        navigation_actions_text = navigation_actions.read_text(encoding="utf-8")
        selection_actions_text = selection_actions.read_text(encoding="utf-8")
        key_telemetry_text = key_telemetry.read_text(encoding="utf-8")
        app_text = textual_app.read_text(encoding="utf-8")
        selection_text = selection_state.read_text(encoding="utf-8")
        runtime_text = app_runtime.read_text(encoding="utf-8")
        key_policy_text = key_policy.read_text(encoding="utf-8")
        self.assertIn("class SelectorIoProbe", io_probe_text)
        self.assertIn("def termios_snapshot", io_probe_text)
        self.assertIn("def pending_bytes_snapshot", io_probe_text)
        self.assertIn("class SelectorBackendDecision", backend_text)
        self.assertIn("def selector_backend_decision", backend_text)
        self.assertIn("def selector_impl", backend_text)
        self.assertIn("def selector_driver_thread_snapshot", backend_text)
        self.assertIn("from .backend_policy import", support_text)
        self.assertIn("from .io_probe import SelectorIoProbe", support_text)
        self.assertIn("from .read_guard import", support_text)
        self.assertIn("from .textual_driver_instrumentation import", support_text)
        self.assertIn("from .prompt_toolkit_io_instrumentation import", support_text)
        self.assertIn("def _selector_backend_decision", support_text)
        self.assertIn("def guard_textual_nonblocking_read", read_guard_text)
        self.assertIn("def instrument_textual_parser_keys", textual_driver_text)
        self.assertIn("def instrument_prompt_toolkit_posix_io", prompt_toolkit_text)
        self.assertIn("def emit_app_key_trace", app_key_trace_text)
        self.assertIn("class SelectorFocusActions", focus_actions_text)
        self.assertIn("def focus_list", focus_actions_text)
        self.assertIn("def cycle_focus", focus_actions_text)
        self.assertIn("class SelectorKeyActions", key_actions_text)
        self.assertIn("def handle_key", key_actions_text)
        self.assertIn("def handle_filter_focus_key", key_actions_text)
        self.assertIn("from envctl_engine.ui.textual.screens.selector.textual_key_policy import", key_actions_text)
        self.assertIn("class SelectorInitialNavigationRunner", initial_navigation_text)
        self.assertIn("class SelectorNavigationActions", navigation_actions_text)
        self.assertIn("def nav_down", navigation_actions_text)
        self.assertIn("def ignore_escape", navigation_actions_text)
        self.assertIn("class SelectorSelectionActions", selection_actions_text)
        self.assertIn("def handle_list_selection", selection_actions_text)
        self.assertIn("def selector_row_model_index_from_widget", selection_actions_text)
        self.assertIn("class SelectorKeyTelemetry", key_telemetry_text)
        self.assertIn("def record_raw_key", key_telemetry_text)
        self.assertIn("def emit_snapshot", key_telemetry_text)
        self.assertIn("from envctl_engine.ui.textual.screens.selector.textual_key_telemetry import", runtime_text)
        self.assertIn("def build_selector_rows", selection_text)
        self.assertIn("def apply_selector_filter", selection_text)
        self.assertIn("def selector_visibility_counts", selection_text)
        self.assertIn("def selector_submit_values", selection_text)
        self.assertIn("def toggle_selector_model_index", selection_text)
        self.assertIn("def fallback_selector_values", selection_text)
        self.assertIn("class SelectorStatusPresenter", runtime_text)
        self.assertIn("class SelectorStatusController", runtime_text)
        self.assertIn("class SelectorFocusController", runtime_text)
        self.assertIn("class SelectorEventController", runtime_text)
        self.assertIn('"SelectorKeyTelemetry"', runtime_text)
        self.assertIn("class SelectorKeyDecision", key_policy_text)
        self.assertIn("class SelectorFilterKeyDecision", key_policy_text)
        self.assertIn("def resolve_selector_key", key_policy_text)
        self.assertIn("def resolve_selector_filter_key", key_policy_text)
        self.assertIn("def emit_selector_key_trace", key_policy_text)
        self.assertIn("from envctl_engine.ui.textual.screens.selector import selection_state", app_text)
        self.assertIn("from envctl_engine.ui.textual.screens.selector.textual_app_focus_actions import", app_text)
        self.assertIn("from envctl_engine.ui.textual.screens.selector.textual_app_key_actions import", app_text)
        self.assertIn("from envctl_engine.ui.textual.screens.selector.textual_app_key_trace import", app_text)
        self.assertIn("from envctl_engine.ui.textual.screens.selector.textual_app_initial_navigation import", app_text)
        self.assertIn("from envctl_engine.ui.textual.screens.selector.textual_app_navigation_actions import", app_text)
        self.assertIn("from envctl_engine.ui.textual.screens.selector.textual_app_selection_actions import", app_text)
        self.assertIn("from envctl_engine.ui.textual.screens.selector.textual_key_telemetry import", app_text)
        self.assertIn("from envctl_engine.ui.textual.screens.selector.textual_app_runtime import", app_text)
        self.assertIn("SelectorStatusController", app_text)
        self.assertLessEqual(len(support_text.splitlines()), 180)
        self.assertLessEqual(len(app_text.splitlines()), 725)

    def test_ui_backend_has_selector_handoff_owner(self) -> None:
        backend = REPO_ROOT / "python" / "envctl_engine" / "ui" / "backend.py"
        selector_owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "backend_selector_support.py"
        debug_owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "backend_selector_debug.py"
        tty_owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "backend_selector_tty.py"
        subprocess_owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "backend_selector_subprocess.py"

        self.assertTrue(selector_owner.is_file())
        self.assertTrue(debug_owner.is_file())
        self.assertTrue(tty_owner.is_file())
        self.assertTrue(subprocess_owner.is_file())
        backend_text = backend.read_text(encoding="utf-8")
        selector_text = selector_owner.read_text(encoding="utf-8")
        debug_text = debug_owner.read_text(encoding="utf-8")
        tty_text = tty_owner.read_text(encoding="utf-8")
        subprocess_text = subprocess_owner.read_text(encoding="utf-8")
        self.assertIn("from .backend_selector_support import", backend_text)
        self.assertIn("class TextualInteractiveBackend", backend_text)
        self.assertIn("def select_project_targets_via_textual", selector_text)
        self.assertIn("def select_grouped_targets_via_textual", selector_text)
        self.assertIn("from envctl_engine.ui.backend_selector_subprocess import", selector_text)
        self.assertIn("from envctl_engine.ui.backend_selector_tty import", selector_text)
        self.assertIn("def debug_tty_group_enabled", debug_text)
        self.assertIn("def emit_parent_selector_thread_snapshot", debug_text)
        self.assertIn("def run_selector_preflight", selector_text)
        self.assertIn("def stdin_tty_fd", tty_text)
        self.assertIn("def drain_stdin_escape_tail", tty_text)
        self.assertIn("def run_selector_subprocess", subprocess_text)
        self.assertLessEqual(len(selector_text.splitlines()), 230)
        self.assertLessEqual(len(backend_text.splitlines()), 240)

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
        coordinator = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_code_intelligence.py"
        cgc_owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_code_intelligence_cgc.py"
        config_owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_code_intelligence_config.py"
        files_owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_code_intelligence_files.py"
        metadata_owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_code_intelligence_metadata.py"
        models_owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_code_intelligence_models.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_domain.py"

        self.assertTrue(coordinator.is_file())
        self.assertTrue(cgc_owner.is_file())
        self.assertTrue(config_owner.is_file())
        self.assertTrue(files_owner.is_file())
        self.assertTrue(metadata_owner.is_file())
        self.assertTrue(models_owner.is_file())
        coordinator_text = coordinator.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.planning.worktree_code_intelligence_cgc import", coordinator_text)
        self.assertIn("from envctl_engine.planning.worktree_code_intelligence_config import", coordinator_text)
        self.assertIn("from envctl_engine.planning.worktree_code_intelligence_files import", coordinator_text)
        self.assertIn("from envctl_engine.planning.worktree_code_intelligence_metadata import", coordinator_text)
        self.assertIn(
            "from envctl_engine.planning.worktree_code_intelligence import",
            facade.read_text(encoding="utf-8"),
        )

    def test_worktree_path_support_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_path_support.py"
        menu_owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_menu_terminal_support.py"
        spinner_owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_spinner_support.py"
        runtime_bridge = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_runtime_bridge.py"
        selection_runtime_bridge = (
            REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_selection_runtime_bridge.py"
        )
        sync_runtime_bridge = (
            REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_sync_runtime_bridge.py"
        )
        protocols = REPO_ROOT / "python" / "envctl_engine" / "planning" / "protocols.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_domain.py"

        self.assertTrue(owner.is_file())
        self.assertTrue(menu_owner.is_file())
        self.assertTrue(spinner_owner.is_file())
        self.assertTrue(runtime_bridge.is_file())
        self.assertTrue(selection_runtime_bridge.is_file())
        self.assertTrue(sync_runtime_bridge.is_file())
        self.assertTrue(protocols.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        menu_owner_text = menu_owner.read_text(encoding="utf-8")
        spinner_owner_text = spinner_owner.read_text(encoding="utf-8")
        runtime_bridge_text = runtime_bridge.read_text(encoding="utf-8")
        selection_runtime_bridge_text = selection_runtime_bridge.read_text(encoding="utf-8")
        sync_runtime_bridge_text = sync_runtime_bridge.read_text(encoding="utf-8")
        setup_coordinator_text = (
            REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_setup_coordinator.py"
        ).read_text(encoding="utf-8")
        sync_orchestration_text = (
            REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_sync_orchestration.py"
        ).read_text(encoding="utf-8")
        self.assertIn("def preferred_tree_root_for_feature", owner_text)
        self.assertIn("def trees_root_for_worktree", owner_text)
        self.assertIn("def resolve_planning_selection_target", owner_text)
        self.assertIn("def setup_worktree_requested", owner_text)
        self.assertIn("def render_planning_selection_menu", menu_owner_text)
        self.assertIn("def planning_menu_apply_key", menu_owner_text)
        self.assertIn("class WorktreeSpinnerLifecycle", spinner_owner_text)
        self.assertIn("def worktree_spinner_policy", spinner_owner_text)
        self.assertIn("def worktree_spinner_update", spinner_owner_text)
        self.assertIn("def worktree_spinner_stop", spinner_owner_text)
        self.assertIn("class PlanningRuntimeBridge", runtime_bridge_text)
        self.assertIn("class WorktreeSelectionRuntimeBridge", selection_runtime_bridge_text)
        self.assertIn("class WorktreeSyncRuntimeBridge", sync_runtime_bridge_text)
        self.assertIn("def create_planning_runtime_bridge", runtime_bridge_text)
        self.assertIn("def create_single_worktree", runtime_bridge_text)
        self.assertIn("def selection_bridge", runtime_bridge_text)
        self.assertIn("def sync_bridge", runtime_bridge_text)
        self.assertIn("def select_plan_projects", selection_runtime_bridge_text)
        self.assertIn("def prompt_planning_selection", selection_runtime_bridge_text)
        self.assertIn("def run_planning_selection_menu", selection_runtime_bridge_text)
        self.assertIn("def sync_plan_worktrees_from_plan_counts", sync_runtime_bridge_text)
        self.assertIn("def delete_feature_worktrees", sync_runtime_bridge_text)
        self.assertNotIn("def _worktree_spinner_update", setup_coordinator_text)
        self.assertNotIn("def _spinner_update", sync_orchestration_text)
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.planning.worktree_path_support import", facade_text)
        self.assertIn("from envctl_engine.planning.worktree_menu_terminal_support import", facade_text)
        self.assertIn("from envctl_engine.planning.worktree_spinner_support import", facade_text)
        self.assertIn("from envctl_engine.planning.worktree_runtime_bridge import create_planning_runtime_bridge", facade_text)
        top_level_imports = "\n".join(line for line in facade_text.splitlines() if line.startswith("from "))
        self.assertNotIn("from envctl_engine.actions.actions_worktree import", top_level_imports)
        self.assertNotIn("from envctl_engine.runtime.runtime_context import", top_level_imports)
        self.assertIn("def delete_worktree_path", facade_text)
        self.assertIn("def select_planning_counts_textual", facade_text)
        self.assertIn("from envctl_engine.planning.protocols import ProjectContextLike", facade_text)
        self.assertNotIn("class ProjectContextLike(Protocol)", facade_text)
        self.assertNotIn("return _coerce_setup_entries_impl(flags=route.flags, flag_name=flag_name, value_name=value_name)\n    return _coerce_setup_entries_impl", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 720)

    def test_startup_helpers_share_project_context_protocol(self) -> None:
        helper_paths = [
            REPO_ROOT / "python" / "envctl_engine" / "startup" / "service_bootstrap_domain.py",
            REPO_ROOT / "python" / "envctl_engine" / "startup" / "service_frontend_bootstrap_support.py",
            REPO_ROOT / "python" / "envctl_engine" / "startup" / "requirements_startup_domain.py",
            REPO_ROOT / "python" / "envctl_engine" / "startup" / "requirements_component_startup.py",
            REPO_ROOT / "python" / "envctl_engine" / "startup" / "requirements_native_adapter.py",
            REPO_ROOT / "python" / "envctl_engine" / "startup" / "service_execution_records.py",
        ]

        for helper_path in helper_paths:
            with self.subTest(path=helper_path.name):
                text = helper_path.read_text(encoding="utf-8")
                self.assertIn("from envctl_engine.startup.protocols import ProjectContextLike", text)
                self.assertNotIn("class ProjectContextLike(Protocol)", text)
                self.assertNotIn("class _ProjectContextLike(Protocol)", text)

    def test_requirements_startup_has_native_adapter_owner(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "requirements_native_adapter.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "startup" / "requirements_startup_domain.py"

        self.assertTrue(owner.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("class NativeAdapterStartResult", owner_text)
        self.assertIn("def start_requirement_with_native_adapter", owner_text)
        self.assertIn("from envctl_engine.startup.requirements_native_adapter import", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 510)

    def test_requirements_startup_has_component_owner(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "requirements_component_startup.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "startup" / "requirements_startup_domain.py"

        self.assertTrue(owner.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("class RequirementComponentStarter", owner_text)
        self.assertIn("def start_requirement_component", owner_text)
        self.assertIn("from envctl_engine.startup.requirements_component_startup import", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 180)

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
        creation_bridge = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_creation_runtime_bridge.py"

        self.assertTrue(owner.is_file())
        self.assertTrue(creation_bridge.is_file())
        self.assertIn(
            "from envctl_engine.planning.worktree_creation_flow import",
            creation_bridge.read_text(encoding="utf-8"),
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
        protocols = REPO_ROOT / "python" / "envctl_engine" / "planning" / "protocols.py"
        selection_bridge = (
            REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_selection_runtime_bridge.py"
        )

        self.assertTrue(owner.is_file())
        self.assertTrue(protocols.is_file())
        self.assertIn(
            "from envctl_engine.planning.worktree_plan_project_selection import",
            selection_bridge.read_text(encoding="utf-8"),
        )
        self.assertIn("from envctl_engine.planning.protocols import ProjectContextLike", owner.read_text(encoding="utf-8"))
        self.assertNotIn("class ProjectContextLike(Protocol)", owner.read_text(encoding="utf-8"))

    def test_worktree_prompt_selection_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_prompt_selection.py"
        selection_bridge = (
            REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_selection_runtime_bridge.py"
        )

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.planning.worktree_prompt_selection import",
            selection_bridge.read_text(encoding="utf-8"),
        )

    def test_worktree_planning_menu_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_planning_menu.py"
        selection_bridge = (
            REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_selection_runtime_bridge.py"
        )

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.planning.worktree_planning_menu import",
            selection_bridge.read_text(encoding="utf-8"),
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
        protocols = REPO_ROOT / "python" / "envctl_engine" / "planning" / "protocols.py"
        setup_bridge = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_setup_runtime_bridge.py"

        self.assertTrue(owner.is_file())
        self.assertTrue(protocols.is_file())
        self.assertTrue(setup_bridge.is_file())
        self.assertIn(
            "from envctl_engine.planning.worktree_setup_coordinator import",
            setup_bridge.read_text(encoding="utf-8"),
        )
        self.assertIn("from envctl_engine.planning.protocols import ProjectContextLike", owner.read_text(encoding="utf-8"))
        self.assertNotIn("class ProjectContextLike(Protocol)", owner.read_text(encoding="utf-8"))

    def test_worktree_runtime_setup_bridge_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_setup_runtime_bridge.py"
        creation_owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_creation_runtime_bridge.py"
        runtime_bridge = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_runtime_bridge.py"

        self.assertTrue(owner.is_file())
        self.assertTrue(creation_owner.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        creation_owner_text = creation_owner.read_text(encoding="utf-8")
        self.assertIn("class WorktreeSetupRuntimeBridge", owner_text)
        self.assertIn("def apply_setup_worktree_selection", owner_text)
        self.assertIn("def apply_multi_setup_entry", owner_text)
        self.assertIn("def apply_single_setup_entry", owner_text)
        self.assertIn("class WorktreeCreationRuntimeBridge", creation_owner_text)
        self.assertIn("def create_single_worktree", creation_owner_text)
        self.assertIn("def create_feature_worktrees_result", creation_owner_text)
        self.assertIn("def run_worktree_add", creation_owner_text)
        runtime_bridge_text = runtime_bridge.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.planning.worktree_setup_runtime_bridge import", runtime_bridge_text)
        self.assertIn("from envctl_engine.planning.worktree_creation_runtime_bridge import", runtime_bridge_text)
        self.assertIn("from envctl_engine.planning.worktree_selection_runtime_bridge import", runtime_bridge_text)
        self.assertLessEqual(len(runtime_bridge_text.splitlines()), 380)

    def test_worktree_sync_deletion_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_sync_deletion.py"
        sync_bridge = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_sync_runtime_bridge.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.planning.worktree_sync_deletion import",
            sync_bridge.read_text(encoding="utf-8"),
        )

    def test_worktree_sync_orchestration_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_sync_orchestration.py"
        sync_bridge = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_sync_runtime_bridge.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.planning.worktree_sync_orchestration import",
            sync_bridge.read_text(encoding="utf-8"),
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
        utility_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "utility_command_support.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime.py"

        self.assertTrue(owner.is_file())
        self.assertTrue(facade_owner.is_file())
        self.assertTrue(utility_owner.is_file())
        self.assertFalse((REPO_ROOT / "python" / "envctl_engine" / "runtime" / "hook_migration_support.py").exists())
        self.assertIn("def run_hook_migration", owner.read_text(encoding="utf-8"))
        utility_text = utility_owner.read_text(encoding="utf-8")
        self.assertIn("def utility_command_handlers", utility_text)
        self.assertIn("def dispatch_utility_command", utility_text)
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
        rendering_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "help_topic_rendering.py"
        catalog_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "help_topic_catalog.py"
        topics_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "help_topics.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "help_text.py"

        self.assertTrue(metadata_owner.is_file())
        self.assertTrue(general_owner.is_file())
        self.assertTrue(rendering_owner.is_file())
        self.assertTrue(catalog_owner.is_file())
        self.assertTrue(topics_owner.is_file())
        metadata_text = metadata_owner.read_text(encoding="utf-8")
        general_text = general_owner.read_text(encoding="utf-8")
        rendering_text = rendering_owner.read_text(encoding="utf-8")
        catalog_text = catalog_owner.read_text(encoding="utf-8")
        topics_text = topics_owner.read_text(encoding="utf-8")
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("def default_interactivity", metadata_text)
        self.assertIn("def ordered_known_commands", metadata_text)
        self.assertIn("def render_general_help", general_text)
        self.assertIn("class CommandHelpTopic", rendering_text)
        self.assertIn("def render_command_help", rendering_text)
        self.assertIn("COMMAND_HELP_TOPICS", catalog_text)
        self.assertIn("CommandHelpTopic(", catalog_text)
        self.assertIn("def help_text_for_route", topics_text)
        self.assertIn("from envctl_engine.runtime.help_topic_catalog import", topics_text)
        self.assertIn("from envctl_engine.runtime.help_topic_rendering import", topics_text)
        self.assertLessEqual(len(topics_text.splitlines()), 80)
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
        attach_owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "service_attach_execution.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "startup" / "service_execution.py"

        self.assertTrue(env_owner.is_file())
        self.assertTrue(owner.is_file())
        self.assertTrue(records_owner.is_file())
        self.assertTrue(attach_owner.is_file())
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
        attach_text = attach_owner.read_text(encoding="utf-8")
        self.assertIn("class ServiceAttachRunner", attach_text)
        self.assertIn("def start_backend", attach_text)
        self.assertIn("def detect_additional_actual", attach_text)
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.startup.service_attach_execution import", facade_text)
        self.assertIn("from envctl_engine.startup.service_execution_environment import", facade_text)
        self.assertIn("from envctl_engine.startup.service_execution_policy import", facade_text)
        self.assertIn("from envctl_engine.startup.service_execution_records import", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 420)

    def test_service_launch_diagnostics_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "service_launch_diagnostics.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "startup" / "service_execution.py"

        self.assertTrue(owner.is_file())
        self.assertIn("def record_runtime_launch_diagnostics", owner.read_text(encoding="utf-8"))
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.startup.service_launch_diagnostics import", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 420)

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
        execution_owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "resume_restore_execution.py"
        project_owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "resume_restore_project.py"
        result_owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "resume_restore_results.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "startup" / "resume_restore_support.py"

        self.assertTrue(owner.is_file())
        self.assertTrue(execution_owner.is_file())
        self.assertTrue(project_owner.is_file())
        self.assertTrue(result_owner.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        self.assertIn("def _restore_parallel_config", owner_text)
        self.assertIn("def _requirements_reuse_decision", owner_text)
        self.assertIn("def _reserve_application_service_ports", owner_text)
        self.assertIn("def context_for_project", owner_text)
        self.assertIn("from envctl_engine.runtime.runtime_context import", owner_text)
        self.assertNotIn("class _StateRepositoryProtocol(Protocol)", owner_text)
        self.assertNotIn("class _PortAllocatorProtocol(Protocol)", owner_text)
        execution_owner_text = execution_owner.read_text(encoding="utf-8")
        self.assertIn("class ResumeRestoreDependencies", execution_owner_text)
        self.assertIn("class ResumeRestoreRunner", execution_owner_text)
        self.assertNotIn("class ResumeProjectRestoreRunner", execution_owner_text)
        self.assertIn("def _execute_restore_missing", execution_owner_text)
        self.assertIn("def _run_restore_jobs", execution_owner_text)
        project_owner_text = project_owner.read_text(encoding="utf-8")
        self.assertIn("class ResumeProjectRestoreRunner", project_owner_text)
        self.assertIn("def _round_ms", project_owner_text)
        result_owner_text = result_owner.read_text(encoding="utf-8")
        self.assertIn("def apply_restore_result", result_owner_text)
        self.assertIn("def format_project_timing_line", result_owner_text)
        self.assertIn("def mark_restore_failure_requirements", result_owner_text)
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.startup.resume_restore_execution import", facade_text)
        self.assertIn("from envctl_engine.startup.resume_restore_policy import", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 120)

    def test_runtime_dependency_accessors_use_shared_runtime_context_helpers(self) -> None:
        cleanup_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "lifecycle_cleanup_orchestrator.py"
        worktree_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "actions_worktree.py"

        cleanup_text = cleanup_owner.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.runtime.runtime_context import", cleanup_text)
        self.assertNotIn("class _StateRepositoryProtocol(Protocol)", cleanup_text)
        self.assertNotIn("class _ProcessRuntimeProtocol(Protocol)", cleanup_text)

        worktree_text = worktree_owner.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.shared.protocols import ProcessRuntime", worktree_text)
        self.assertNotIn("class _ProcessRunnerProtocol(Protocol)", worktree_text)

    def test_repo_local_launcher_is_python_script(self) -> None:
        launcher = REPO_ROOT / "bin" / "envctl"
        self.assertTrue(launcher.is_file())
        text = launcher.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("#!/usr/bin/env python3"))


if __name__ == "__main__":
    unittest.main()
