from pathlib import Path
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]


class RuntimeStructureLayoutTests(unittest.TestCase):
    def test_runtime_lifecycle_parity_tests_are_split_by_owner(self) -> None:
        runtime_tests = REPO_ROOT / "tests" / "python" / "runtime"
        expected = [
            "lifecycle_parity_test_support.py",
            "test_lifecycle_parity_blast.py",
            "test_lifecycle_parity_mode_scope.py",
            "test_lifecycle_parity_restore_startup.py",
            "test_lifecycle_parity_resume_legacy.py",
            "test_lifecycle_parity_resume_policy.py",
            "test_lifecycle_parity_state_actions.py",
            "test_lifecycle_parity_stop_health.py",
        ]

        for filename in expected:
            with self.subTest(path=filename):
                self.assertTrue((runtime_tests / filename).is_file())

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

    def test_process_runner_has_launch_and_lifecycle_owners(self) -> None:
        shared = REPO_ROOT / "python" / "envctl_engine" / "shared"
        runner = shared / "process_runner.py"
        launch_owner = shared / "process_launch_support.py"
        lifecycle_owner = shared / "process_lifecycle_probe.py"
        streaming_owner = shared / "process_streaming_support.py"

        self.assertTrue(launch_owner.is_file())
        self.assertTrue(lifecycle_owner.is_file())
        self.assertTrue(streaming_owner.is_file())
        launch_text = launch_owner.read_text(encoding="utf-8")
        lifecycle_text = lifecycle_owner.read_text(encoding="utf-8")
        streaming_text = streaming_owner.read_text(encoding="utf-8")
        runner_text = runner.read_text(encoding="utf-8")
        self.assertIn("class LaunchRecord", launch_text)
        self.assertIn("class ProcessLaunchMixin", launch_text)
        self.assertIn("def start_background", launch_text)
        self.assertIn("def launch_diagnostics_summary", launch_text)
        self.assertIn("class ProcessLifecycleProbeMixin", lifecycle_text)
        self.assertIn("def wait_for_port", lifecycle_text)
        self.assertIn("def process_tree_listener_pids", lifecycle_text)
        self.assertIn("def terminate_process_group", lifecycle_text)
        self.assertIn("class ProcessStreamingMixin", streaming_text)
        self.assertIn("def run_streaming", streaming_text)
        self.assertIn("ProcessLaunchMixin", runner_text)
        self.assertIn("ProcessLifecycleProbeMixin", runner_text)
        self.assertIn("ProcessStreamingMixin", runner_text)
        self.assertLessEqual(len(runner_text.splitlines()), 340)

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

    def test_runtime_feature_inventory_has_contract_owner(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "runtime_feature_contracts.py"
        definition_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime_feature_definitions.py"
        definition_schema = REPO_ROOT / "python" / "envctl_engine" / "runtime_feature_definition_schema.py"
        command_definitions = REPO_ROOT / "python" / "envctl_engine" / "runtime_feature_command_definitions.py"
        command_lifecycle_definitions = (
            REPO_ROOT / "python" / "envctl_engine" / "runtime_feature_lifecycle_command_definitions.py"
        )
        command_planning_definitions = (
            REPO_ROOT / "python" / "envctl_engine" / "runtime_feature_planning_command_definitions.py"
        )
        command_action_definitions = (
            REPO_ROOT / "python" / "envctl_engine" / "runtime_feature_action_command_definitions.py"
        )
        command_inspection_definitions = (
            REPO_ROOT / "python" / "envctl_engine" / "runtime_feature_inspection_command_definitions.py"
        )
        command_cli_definitions = REPO_ROOT / "python" / "envctl_engine" / "runtime_feature_cli_command_definitions.py"
        command_diagnostic_definitions = (
            REPO_ROOT / "python" / "envctl_engine" / "runtime_feature_diagnostic_command_definitions.py"
        )
        extra_definitions = REPO_ROOT / "python" / "envctl_engine" / "runtime_feature_extra_definitions.py"
        inventory = REPO_ROOT / "python" / "envctl_engine" / "runtime_feature_inventory.py"

        self.assertTrue(owner.is_file())
        self.assertTrue(definition_owner.is_file())
        self.assertTrue(definition_schema.is_file())
        self.assertTrue(command_definitions.is_file())
        self.assertTrue(command_lifecycle_definitions.is_file())
        self.assertTrue(command_planning_definitions.is_file())
        self.assertTrue(command_action_definitions.is_file())
        self.assertTrue(command_inspection_definitions.is_file())
        self.assertTrue(command_cli_definitions.is_file())
        self.assertTrue(command_diagnostic_definitions.is_file())
        self.assertTrue(extra_definitions.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        definition_owner_text = definition_owner.read_text(encoding="utf-8")
        definition_schema_text = definition_schema.read_text(encoding="utf-8")
        command_definitions_text = command_definitions.read_text(encoding="utf-8")
        extra_definitions_text = extra_definitions.read_text(encoding="utf-8")
        self.assertIn("def build_runtime_feature_matrix_from_definitions", owner_text)
        self.assertIn("def validate_runtime_feature_matrix_payload", owner_text)
        self.assertIn("def render_python_runtime_gap_closure_plan", owner_text)
        self.assertIn("class FeatureDefinition", definition_schema_text)
        self.assertIn("LIFECYCLE_COMMAND_DEFINITIONS", command_lifecycle_definitions.read_text(encoding="utf-8"))
        self.assertIn("PLANNING_COMMAND_DEFINITIONS", command_planning_definitions.read_text(encoding="utf-8"))
        self.assertIn("ACTION_COMMAND_DEFINITIONS", command_action_definitions.read_text(encoding="utf-8"))
        self.assertIn("INSPECTION_COMMAND_DEFINITIONS", command_inspection_definitions.read_text(encoding="utf-8"))
        self.assertIn("CLI_COMMAND_DEFINITIONS", command_cli_definitions.read_text(encoding="utf-8"))
        self.assertIn("DIAGNOSTIC_COMMAND_DEFINITIONS", command_diagnostic_definitions.read_text(encoding="utf-8"))
        self.assertIn(
            "from envctl_engine.runtime_feature_lifecycle_command_definitions import", command_definitions_text
        )
        self.assertIn(
            "from envctl_engine.runtime_feature_planning_command_definitions import", command_definitions_text
        )
        self.assertIn("from envctl_engine.runtime_feature_action_command_definitions import", command_definitions_text)
        self.assertIn(
            "from envctl_engine.runtime_feature_inspection_command_definitions import", command_definitions_text
        )
        self.assertIn("from envctl_engine.runtime_feature_cli_command_definitions import", command_definitions_text)
        self.assertIn(
            "from envctl_engine.runtime_feature_diagnostic_command_definitions import", command_definitions_text
        )
        self.assertIn("COMMAND_DEFINITIONS", command_definitions_text)
        self.assertIn("EXTRA_FEATURES", extra_definitions_text)
        self.assertIn("runtime_feature_definition_schema", definition_owner_text)
        self.assertIn("runtime_feature_command_definitions", definition_owner_text)
        self.assertIn("runtime_feature_extra_definitions", definition_owner_text)
        self.assertLessEqual(len(definition_owner_text.splitlines()), 35)
        self.assertLessEqual(len(command_definitions_text.splitlines()), 55)
        inventory_text = inventory.read_text(encoding="utf-8")
        self.assertIn("runtime_feature_contracts", inventory_text)
        self.assertIn("runtime_feature_definitions", inventory_text)
        self.assertLessEqual(len(inventory_text.splitlines()), 90)

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
        alias_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "command_alias_catalog.py"
        flag_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "command_flag_catalog.py"
        registry_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "command_catalog_registry.py"
        models_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "command_models.py"
        flag_storage_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "command_flag_storage.py"
        special_flags_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "command_special_flags.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "command_router.py"

        self.assertTrue(owner.is_file())
        self.assertTrue(alias_owner.is_file())
        self.assertTrue(flag_owner.is_file())
        self.assertTrue(registry_owner.is_file())
        self.assertTrue(models_owner.is_file())
        self.assertTrue(flag_storage_owner.is_file())
        self.assertTrue(special_flags_owner.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        alias_text = alias_owner.read_text(encoding="utf-8")
        flag_text = flag_owner.read_text(encoding="utf-8")
        registry_text = registry_owner.read_text(encoding="utf-8")
        models_text = models_owner.read_text(encoding="utf-8")
        flag_storage_text = flag_storage_owner.read_text(encoding="utf-8")
        special_flags_text = special_flags_owner.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.runtime.command_alias_catalog import", owner_text)
        self.assertIn("from envctl_engine.runtime.command_flag_catalog import", owner_text)
        self.assertIn("COMMAND_ALIASES", alias_text)
        self.assertIn("SUPPORTED_COMMANDS", alias_text)
        self.assertIn("BOOLEAN_FLAGS", flag_text)
        self.assertIn("def list_supported_flag_tokens", flag_text)
        self.assertIn("def unique_tokens", registry_text)
        self.assertIn("def unique_mapping", registry_text)
        self.assertIn("COMMAND_ALIASES", owner_text)
        self.assertIn("list_supported_flag_tokens as list_supported_flag_tokens", owner_text)
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
        self.assertLessEqual(len(owner_text.splitlines()), 120)
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

    def test_runtime_state_truth_has_cohesive_owner_modules(self) -> None:
        fingerprint_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "state_fingerprint_support.py"
        port_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "requirement_port_truth.py"
        status_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "requirement_status_truth.py"
        reconcile_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "requirement_reconcile_truth.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime_state_truth.py"

        self.assertTrue(fingerprint_owner.is_file())
        self.assertTrue(port_owner.is_file())
        self.assertTrue(status_owner.is_file())
        self.assertTrue(reconcile_owner.is_file())
        self.assertIn("def state_fingerprint", fingerprint_owner.read_text(encoding="utf-8"))
        port_text = port_owner.read_text(encoding="utf-8")
        self.assertIn("def reconcile_requirement_container_ports", port_text)
        self.assertIn("def expected_requirement_container_name", port_text)
        self.assertIn("def container_port_for_component", port_text)
        status_text = status_owner.read_text(encoding="utf-8")
        self.assertIn("def requirement_runtime_status", status_text)
        self.assertIn("def adopt_requirement_container", status_text)
        reconcile_text = reconcile_owner.read_text(encoding="utf-8")
        self.assertIn("def reconcile_requirements_truth", reconcile_text)
        self.assertIn("def reconcile_state_truth", reconcile_text)
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.runtime.state_fingerprint_support import", facade_text)
        self.assertIn("from envctl_engine.runtime.requirement_port_truth import", facade_text)
        self.assertIn("from envctl_engine.runtime.requirement_status_truth import", facade_text)
        self.assertIn("from envctl_engine.runtime.requirement_reconcile_truth import", facade_text)
        self.assertNotIn("ThreadPoolExecutor", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 90)

    def test_runtime_service_truth_has_cohesive_owner_modules(self) -> None:
        diagnostics_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "service_truth_diagnostics.py"
        listener_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "service_listener_truth.py"
        status_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "service_status_truth.py"
        post_start_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "service_post_start_truth.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "engine_runtime_service_truth.py"

        self.assertTrue(diagnostics_owner.is_file())
        self.assertTrue(listener_owner.is_file())
        self.assertTrue(status_owner.is_file())
        self.assertTrue(post_start_owner.is_file())
        diagnostics_text = diagnostics_owner.read_text(encoding="utf-8")
        self.assertIn("def command_result_error_text", diagnostics_text)
        self.assertIn("def service_listener_failure_detail", diagnostics_text)
        self.assertIn("def tail_log_error_line", diagnostics_text)
        listener_text = listener_owner.read_text(encoding="utf-8")
        self.assertIn("def wait_for_service_listener", listener_text)
        self.assertIn("def detect_service_actual_port", listener_text)
        self.assertIn("def service_truth_fallback_enabled", listener_text)
        status_text = status_owner.read_text(encoding="utf-8")
        self.assertIn("def service_truth_status", status_text)
        self.assertIn("def rebind_stale_service_pid", status_text)
        self.assertIn("def listener_pids_for_port", status_text)
        self.assertIn("def refresh_service_listener_pids", status_text)
        post_start_text = post_start_owner.read_text(encoding="utf-8")
        self.assertIn("def assert_project_services_post_start_truth", post_start_text)
        self.assertIn("service_listener_failure_detail", post_start_text)
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.runtime.service_truth_diagnostics import", facade_text)
        self.assertIn("from envctl_engine.runtime.service_listener_truth import", facade_text)
        self.assertIn("from envctl_engine.runtime.service_status_truth import", facade_text)
        self.assertIn("from envctl_engine.runtime.service_post_start_truth import", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 80)

    def test_terminal_session_has_tty_mode_owner(self) -> None:
        facade = REPO_ROOT / "python" / "envctl_engine" / "ui" / "terminal_session.py"
        owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "terminal_tty_modes.py"
        stream_owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "terminal_input_stream.py"
        command_reader_owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "terminal_command_readers.py"

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
        self.assertTrue(command_reader_owner.is_file())
        command_reader_text = command_reader_owner.read_text(encoding="utf-8")
        self.assertIn("class TerminalCommandReaderDeps", command_reader_text)
        self.assertIn("def read_command_line_fallback", command_reader_text)
        self.assertIn("def read_command_line_basic", command_reader_text)
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("from .terminal_command_readers import", facade_text)
        self.assertIn("from .terminal_tty_modes import", facade_text)
        self.assertIn("from . import terminal_input_stream", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 430)

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
        lifecycle_catalog = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "help_topic_lifecycle.py"
        planning_catalog = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "help_topic_planning.py"
        action_catalog = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "help_topic_actions.py"
        inspection_catalog = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "help_topic_inspection.py"
        maintenance_catalog = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "help_topic_maintenance.py"
        topics_owner = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "help_topics.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "runtime" / "help_text.py"

        self.assertTrue(metadata_owner.is_file())
        self.assertTrue(general_owner.is_file())
        self.assertTrue(rendering_owner.is_file())
        self.assertTrue(catalog_owner.is_file())
        self.assertTrue(lifecycle_catalog.is_file())
        self.assertTrue(planning_catalog.is_file())
        self.assertTrue(action_catalog.is_file())
        self.assertTrue(inspection_catalog.is_file())
        self.assertTrue(maintenance_catalog.is_file())
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
        self.assertIn("from envctl_engine.runtime.help_topic_lifecycle import", catalog_text)
        self.assertIn("from envctl_engine.runtime.help_topic_planning import", catalog_text)
        self.assertIn("from envctl_engine.runtime.help_topic_actions import", catalog_text)
        self.assertIn("from envctl_engine.runtime.help_topic_inspection import", catalog_text)
        self.assertIn("from envctl_engine.runtime.help_topic_maintenance import", catalog_text)
        self.assertLessEqual(len(catalog_text.splitlines()), 90)
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
