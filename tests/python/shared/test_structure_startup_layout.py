from pathlib import Path
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]


class StartupStructureLayoutTests(unittest.TestCase):
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
        resume_owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "run_reuse_resume.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "startup" / "startup_orchestrator.py"

        self.assertTrue(owner.is_file())
        self.assertTrue(resume_owner.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        resume_owner_text = resume_owner.read_text(encoding="utf-8")
        self.assertIn("class StartupRunReuseResolver", owner_text)
        self.assertIn("class StartupRunReuseResumeHandler", resume_owner_text)
        self.assertIn(
            "from envctl_engine.startup.run_reuse_resume import",
            owner_text,
        )
        self.assertIn(
            "from envctl_engine.startup.run_reuse_resolution import",
            facade.read_text(encoding="utf-8"),
        )

    def test_run_reuse_identity_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "run_reuse_identity.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "startup" / "run_reuse_support.py"
        decision_owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "run_reuse_decision.py"
        dashboard_owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "run_reuse_dashboard_restore.py"
        fresh_start_owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "run_reuse_fresh_start.py"

        self.assertTrue(owner.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        self.assertIn("class ProjectIdentity", owner_text)
        self.assertIn("def build_startup_identity_metadata", owner_text)
        self.assertIn("def _startup_identity_payload", owner_text)
        self.assertIn("def project_identities_from_state", owner_text)
        self.assertTrue(decision_owner.is_file())
        self.assertIn("class RunReuseEvaluator", decision_owner.read_text(encoding="utf-8"))
        self.assertTrue(dashboard_owner.is_file())
        self.assertIn("class DashboardStoppedServiceRestorer", dashboard_owner.read_text(encoding="utf-8"))
        self.assertTrue(fresh_start_owner.is_file())
        self.assertIn("class FreshStartServiceReplacer", fresh_start_owner.read_text(encoding="utf-8"))
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.startup.run_reuse_identity import", facade_text)
        self.assertIn("from envctl_engine.startup.run_reuse_decision import", facade_text)
        self.assertIn("from envctl_engine.startup.run_reuse_dashboard_restore import", facade_text)
        self.assertIn("from envctl_engine.startup.run_reuse_fresh_start import", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 180)

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
        frontend_owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "service_frontend_bootstrap_support.py"
        migration_owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "service_backend_migration_support.py"
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

    def test_browser_diagnostics_has_cohesive_owner_modules(self) -> None:
        env_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "browser_env_preview.py"
        cors_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "browser_cors_diagnostics.py"
        runtime_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "browser_runtime_diagnostics.py"
        startup_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "browser_startup_projection.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "browser_diagnostics.py"

        self.assertTrue(env_owner.is_file())
        self.assertTrue(cors_owner.is_file())
        self.assertTrue(runtime_owner.is_file())
        self.assertTrue(startup_owner.is_file())
        self.assertIn("def safe_env_preview", env_owner.read_text(encoding="utf-8"))
        self.assertIn("def cors_payload", cors_owner.read_text(encoding="utf-8"))
        self.assertIn("def build_runtime_diagnostics", runtime_owner.read_text(encoding="utf-8"))
        self.assertIn("def build_startup_env_projection", startup_owner.read_text(encoding="utf-8"))
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.runtime.browser_env_preview import", facade_text)
        self.assertIn("from envctl_engine.runtime.browser_cors_diagnostics import", facade_text)
        self.assertIn("from envctl_engine.runtime.browser_runtime_diagnostics import", facade_text)
        self.assertIn("from envctl_engine.runtime.browser_startup_projection import", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 90)

    def test_finalization_run_state_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "finalization_run_state.py"
        failure_owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "finalization_failure.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "startup" / "finalization.py"

        self.assertTrue(owner.is_file())
        self.assertTrue(failure_owner.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        failure_owner_text = failure_owner.read_text(encoding="utf-8")
        self.assertIn("def build_planning_dashboard_state", owner_text)
        self.assertIn("def _build_run_state", owner_text)
        self.assertIn("class StartupFailureFinalizer", failure_owner_text)
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.startup.finalization_run_state import", facade_text)
        self.assertIn("from envctl_engine.startup.finalization_failure import", facade_text)
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
