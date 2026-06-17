from pathlib import Path
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]


class RequirementsStructureLayoutTests(unittest.TestCase):
    def test_supabase_startup_sequence_has_lifecycle_orchestrator(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "requirements" / "supabase_lifecycle" / "orchestrator.py"
        auth_owner = REPO_ROOT / "python" / "envctl_engine" / "requirements" / "supabase_lifecycle" / "auth_flow.py"
        db_owner = REPO_ROOT / "python" / "envctl_engine" / "requirements" / "supabase_lifecycle" / "db_flow.py"
        graph_owner = REPO_ROOT / "python" / "envctl_engine" / "requirements" / "supabase_lifecycle" / "graph_flow.py"
        compose_owner = REPO_ROOT / "python" / "envctl_engine" / "requirements" / "supabase_lifecycle" / "compose.py"
        native_db_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "requirements" / "supabase_lifecycle" / "native_db.py"
        )
        native_db_command_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "requirements" / "supabase_lifecycle" / "native_db_commands.py"
        )
        native_db_recovery_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "requirements" / "supabase_lifecycle" / "native_db_recovery.py"
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
        self.assertTrue(native_db_command_owner.is_file())
        self.assertTrue(native_db_recovery_owner.is_file())
        self.assertTrue(compose_handoff_owner.is_file())
        self.assertTrue(service_owner.is_file())
        self.assertTrue(preflight_owner.is_file())
        self.assertIn("def complete_supabase_auth_startup", auth_owner.read_text(encoding="utf-8"))
        self.assertIn("def ensure_supabase_db_ready", db_owner.read_text(encoding="utf-8"))
        self.assertIn("def start_supabase_compose_graph", graph_owner.read_text(encoding="utf-8"))
        self.assertIn("class NativeSupabaseDatabaseStarter", native_db_owner.read_text(encoding="utf-8"))
        self.assertIn("class SupabaseNativeDbCommandBuilder", native_db_command_owner.read_text(encoding="utf-8"))
        self.assertIn(
            "from envctl_engine.requirements.supabase_lifecycle.native_db_commands import",
            native_db_owner.read_text(encoding="utf-8"),
        )
        self.assertIn("def recover_native_db_start_timeout", native_db_recovery_owner.read_text(encoding="utf-8"))
        self.assertIn(
            "from envctl_engine.requirements.supabase_lifecycle.native_db_recovery import",
            native_db_owner.read_text(encoding="utf-8"),
        )
        self.assertLessEqual(len(native_db_owner.read_text(encoding="utf-8").splitlines()), 430)
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
            "test_requirements_supabase_stack_auth_contracts.py",
            "test_requirements_supabase_stack_core_contracts.py",
            "test_requirements_supabase_stack_db_probe_contracts.py",
            "test_requirements_supabase_stack_handoff_contracts.py",
            "test_requirements_supabase_stack_network_contracts.py",
        ]

        for filename in expected:
            with self.subTest(path=filename):
                self.assertTrue((requirements_tests / filename).is_file())

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
        self.assertIn("from envctl_engine.config.load_support import", facade_text)
        self.assertIn("from envctl_engine.config.service_parsing import", facade_text)
        self.assertIn("from envctl_engine.config.source_discovery import", facade_text)
        load_support = REPO_ROOT / "python" / "envctl_engine" / "config" / "load_support.py"
        self.assertTrue(load_support.is_file())
        load_support_text = load_support.read_text(encoding="utf-8")
        self.assertIn("def _apply_dependency_env_template_inferences", load_support_text)
        self.assertIn("def _startup_profile_from_resolved", load_support_text)
        self.assertIn("def _runtime_scope_id", load_support_text)
        self.assertIn("def _parse_runtime_truth_mode", load_support_text)
        self.assertNotIn(
            "dependency_ports: dict[str, dict[str, int]] = {}\n    dependency_ports: dict[str, dict[str, int]] = {}",
            facade_text,
        )
        self.assertNotIn(
            'mode: Literal["main", "trees"],\n    mode: Literal["main", "trees"],',
            facade_text,
        )
        self.assertLessEqual(len(facade_text.splitlines()), 560)

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

    def test_requirements_native_adapter_has_telemetry_owner(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "requirements_native_telemetry.py"
        adapter = REPO_ROOT / "python" / "envctl_engine" / "startup" / "requirements_native_adapter.py"

        self.assertTrue(owner.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        adapter_text = adapter.read_text(encoding="utf-8")
        self.assertIn("class CommandTimingRunnerProxy", owner_text)
        self.assertIn("class NativeAdapterTelemetryEmitter", owner_text)
        self.assertIn("def extract_probe_attempts", owner_text)
        self.assertIn("from envctl_engine.startup.requirements_native_telemetry import", adapter_text)
        self.assertLessEqual(len(adapter_text.splitlines()), 390)

    def test_requirements_common_has_docker_owner_modules(self) -> None:
        common = REPO_ROOT / "python" / "envctl_engine" / "requirements" / "common.py"
        contracts_owner = REPO_ROOT / "python" / "envctl_engine" / "requirements" / "common_contracts.py"
        runtime_owner = REPO_ROOT / "python" / "envctl_engine" / "requirements" / "docker_runtime.py"
        image_owner = REPO_ROOT / "python" / "envctl_engine" / "requirements" / "docker_image_support.py"
        container_owner = REPO_ROOT / "python" / "envctl_engine" / "requirements" / "container_state_support.py"

        self.assertTrue(contracts_owner.is_file())
        self.assertTrue(runtime_owner.is_file())
        self.assertTrue(image_owner.is_file())
        self.assertTrue(container_owner.is_file())
        common_text = common.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.requirements.common_contracts import", common_text)
        self.assertIn("from envctl_engine.requirements.docker_runtime import", common_text)
        self.assertIn("from envctl_engine.requirements.docker_image_support import", common_text)
        self.assertIn("from envctl_engine.requirements.container_state_support import", common_text)
        self.assertIn("class RetryResult", contracts_owner.read_text(encoding="utf-8"))
        self.assertIn("def run_docker", runtime_owner.read_text(encoding="utf-8"))
        self.assertIn("def ensure_docker_image_present", image_owner.read_text(encoding="utf-8"))
        self.assertIn("def container_host_port", container_owner.read_text(encoding="utf-8"))
        self.assertLessEqual(len(common_text.splitlines()), 140)

    def test_production_requirement_callers_use_owner_modules_not_common_facade(self) -> None:
        requirements_root = REPO_ROOT / "python" / "envctl_engine" / "requirements"
        allowed = {requirements_root / "common.py"}
        violations: list[str] = []
        for path in (REPO_ROOT / "python" / "envctl_engine").rglob("*.py"):
            if path in allowed:
                continue
            text = path.read_text(encoding="utf-8")
            if "requirements.common import" in text or "from .common import" in text or "from ..common import" in text:
                violations.append(str(path.relative_to(REPO_ROOT)))
        self.assertEqual([], violations)

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

    def test_requirements_execution_has_project_startup_owner(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "requirements_project_startup.py"
        facade = REPO_ROOT / "python" / "envctl_engine" / "startup" / "requirements_execution.py"

        self.assertTrue(owner.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("class RequirementProjectStarter", owner_text)
        self.assertIn("def start_requirements_for_project", owner_text)
        self.assertIn("from envctl_engine.startup.requirements_project_startup import", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 280)
