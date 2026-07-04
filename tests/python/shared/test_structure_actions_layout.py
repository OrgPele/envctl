from pathlib import Path
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]


class ActionsStructureLayoutTests(unittest.TestCase):
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
        suite_presentation_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_test_suite_presentation.py"
        )
        suite_run_loop_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_test_suite_run_loop.py"
        )
        progress_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_test_runner_progress.py"
        failure_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_test_runner_failures.py"
        runner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_test_runner.py"

        self.assertTrue(execution_owner.is_file())
        self.assertTrue(suite_execution_owner.is_file())
        self.assertTrue(suite_event_owner.is_file())
        self.assertTrue(suite_outcome_owner.is_file())
        self.assertTrue(suite_presentation_owner.is_file())
        self.assertTrue(suite_run_loop_owner.is_file())
        self.assertTrue(progress_owner.is_file())
        self.assertTrue(failure_owner.is_file())
        execution_text = execution_owner.read_text(encoding="utf-8")
        suite_execution_text = suite_execution_owner.read_text(encoding="utf-8")
        suite_event_text = suite_event_owner.read_text(encoding="utf-8")
        suite_outcome_text = suite_outcome_owner.read_text(encoding="utf-8")
        suite_presentation_text = suite_presentation_owner.read_text(encoding="utf-8")
        suite_run_loop_text = suite_run_loop_owner.read_text(encoding="utf-8")
        progress_text = progress_owner.read_text(encoding="utf-8")
        failure_text = failure_owner.read_text(encoding="utf-8")
        self.assertIn("class TestActionExecutionPlan", execution_text)
        self.assertIn("class TestActionExecutionPlanBuilder", execution_text)
        self.assertIn("def build_test_action_execution_plan", execution_text)
        self.assertIn("def resolve_suite_spinner_decision", execution_text)
        self.assertIn("class TestSuiteExecutionResult", suite_execution_text)
        self.assertIn("def execute_test_suites", suite_execution_text)
        self.assertIn("class _TestSuiteExecutor", suite_execution_text)
        self.assertIn("class TestSuiteEventEmitter", suite_event_text)
        self.assertIn("def emit_summary", suite_event_text)
        self.assertIn("class TestSuiteOutcomeRecorder", suite_outcome_text)
        self.assertIn("def record", suite_outcome_text)
        self.assertIn("class TestSuitePresenter", suite_presentation_text)
        self.assertIn("def render_command", suite_presentation_text)
        self.assertIn("action_test_suite_presentation", suite_execution_text)
        self.assertIn("class TestSuiteRunLoop", suite_run_loop_text)
        self.assertIn("def _parallel_failures", suite_run_loop_text)
        self.assertIn("action_test_suite_run_loop", suite_execution_text)
        self.assertLessEqual(len(suite_execution_text.splitlines()), 330)
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
        status_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_test_status_support.py"
        policy_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_test_policy_support.py"
        command_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_test_command_support.py"

        plan_text = plan_owner.read_text(encoding="utf-8")
        service_text = service_owner.read_text(encoding="utf-8")
        status_text = status_owner.read_text(encoding="utf-8")
        policy_text = policy_owner.read_text(encoding="utf-8")
        command_text = command_owner.read_text(encoding="utf-8")
        self.assertIn("class TestExecutionPlanner", plan_text)
        self.assertIn("from envctl_engine.actions.action_test_status_support import", plan_text)
        self.assertIn("from envctl_engine.actions.action_test_policy_support import", plan_text)
        self.assertIn("from envctl_engine.actions.action_test_command_support import", plan_text)
        self.assertNotIn("class TestStatusRenderer", plan_text)
        self.assertNotIn("class TestExecutionPolicy", plan_text)
        self.assertIn("class TestStatusRenderer", status_text)
        self.assertIn("class TestExecutionPolicy", policy_text)
        self.assertIn("def is_legacy_tree_test_script", command_text)
        self.assertIn("def build(self) -> list[TestExecutionSpec]", plan_text)
        self.assertIn("class AdditionalServiceTestPlanner", service_text)
        self.assertIn("def build(self) -> list[TestExecutionSpec]", service_text)

    def test_project_action_domain_has_output_and_artifact_owners(self) -> None:
        commit_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_commit_support.py"
        protected_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_protected_artifacts.py"
        pr_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_pr_message_support.py"
        review_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_review_output_support.py"
        review_artifact_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_review_artifact_support.py"
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
        ship_check_queries_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_ship_check_queries.py"
        )
        ship_check_results_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_ship_check_results.py"
        )
        ship_failure_logs_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "actions" / "action_ship_failure_logs.py"
        )
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
        self.assertTrue(review_original_plan_owner.is_file())
        self.assertTrue(review_base_owner.is_file())
        self.assertTrue(review_iteration_owner.is_file())
        self.assertTrue(git_state_owner.is_file())
        self.assertTrue(ship_owner.is_file())
        self.assertTrue(ship_contract_owner.is_file())
        self.assertTrue(ship_conflicts_owner.is_file())
        self.assertTrue(ship_checks_owner.is_file())
        self.assertTrue(ship_check_queries_owner.is_file())
        self.assertTrue(ship_check_results_owner.is_file())
        self.assertTrue(ship_failure_logs_owner.is_file())
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
        self.assertIn("def ship_action_payload", ship_contract_owner.read_text(encoding="utf-8"))
        self.assertIn("def print_ship_result", ship_contract_owner.read_text(encoding="utf-8"))
        self.assertIn("def predicted_merge_conflict_report", ship_conflicts_owner.read_text(encoding="utf-8"))
        ship_checks_text = ship_checks_owner.read_text(encoding="utf-8")
        self.assertIn("class ShipCheckPoller", ship_checks_text)
        ship_check_queries_text = ship_check_queries_owner.read_text(encoding="utf-8")
        self.assertIn("def query_expected_head_pr_checks", ship_check_queries_text)
        self.assertIn("def query_github_pr_checks", ship_check_queries_text)
        self.assertIn("action_ship_check_queries", ship_checks_text)
        self.assertIn("def normalize_github_pr_checks", ship_check_results_owner.read_text(encoding="utf-8"))
        self.assertIn("def target_status_checks", ship_check_results_owner.read_text(encoding="utf-8"))
        self.assertIn("action_ship_check_results", ship_checks_text)
        ship_failure_logs_text = ship_failure_logs_owner.read_text(encoding="utf-8")
        self.assertIn("def failed_checks_with_log_excerpts", ship_failure_logs_text)
        self.assertIn("def failure_log_excerpt", ship_failure_logs_text)
        self.assertIn("action_ship_failure_logs", ship_checks_text)
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
        self.assertIn("action_review_base_support", facade_text)
        self.assertIn("action_review_iteration_support", facade_text)
        self.assertIn("action_review_original_plan_support", facade_text)
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
        execution_owner = REPO_ROOT / "python" / "envctl_engine" / "actions" / "project_action_execution_support.py"
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
        self.assertIn("class ProjectActionRunnerConfig", execution_text)
        self.assertIn("class ProjectActionRunnerDependencies", execution_text)
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

        artifacts_text = (actions / "action_test_summary_artifacts.py").read_text(encoding="utf-8")
        self.assertIn("class TestSummaryArtifactPersistor", artifacts_text)
        self.assertIn("class FailedTestSummaryWriter", artifacts_text)
        facade = actions / "action_test_summary_support.py"
        self.assertLessEqual(len(facade.read_text(encoding="utf-8").splitlines()), 140)
