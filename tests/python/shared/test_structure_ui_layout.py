from pathlib import Path
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]


class UIStructureLayoutTests(unittest.TestCase):
    def test_dashboard_command_support_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "command_support.py"
        input_owner = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "command_input_support.py"
        command_mixin = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "orchestrator_command_mixin.py"
        failure_mixin = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "orchestrator_failure_mixin.py"
        target_mixin = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "orchestrator_target_mixin.py"
        stop_mixin = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "orchestrator_stop_mixin.py"
        pr_mixin = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "orchestrator_pr_mixin.py"
        restart_mixin = REPO_ROOT / "python" / "envctl_engine" / "ui" / "dashboard" / "orchestrator_restart_mixin.py"
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
            "test_dashboard_orchestrator_pr_flow_dirty.py",
            "test_dashboard_orchestrator_pr_flow_failure_details.py",
            "test_dashboard_orchestrator_pr_flow_messages.py",
            "test_dashboard_orchestrator_pr_flow_selection.py",
            "test_dashboard_orchestrator_restart_configured_missing.py",
            "test_dashboard_orchestrator_restart_resources.py",
            "test_dashboard_orchestrator_restart_selection_basic.py",
            "test_dashboard_orchestrator_review_tab.py",
            "test_dashboard_orchestrator_stop_scope.py",
            "test_dashboard_orchestrator_target_return_flow.py",
            "test_dashboard_orchestrator_target_service_scope.py",
            "test_dashboard_orchestrator_target_shortcuts.py",
            "test_dashboard_orchestrator_target_single_project.py",
            "test_dashboard_orchestrator_target_trees.py",
        ]

        for filename in expected:
            with self.subTest(path=filename):
                self.assertTrue((ui_tests / filename).is_file())

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
        self.assertIn(
            "from envctl_engine.ui.dashboard.snapshot_support import build_dashboard_snapshot_model", owner_text
        )
        rendering_text = rendering.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.ui.dashboard import snapshot_rendering", rendering_text)
        self.assertIn("DashboardSnapshotRenderHooks", rendering_text)
        self.assertLessEqual(len(rendering_text.splitlines()), 540)

    def test_textual_planning_selector_has_model_owner(self) -> None:
        selector = REPO_ROOT / "python" / "envctl_engine" / "ui" / "textual" / "screens" / "planning_selector.py"
        model_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "ui" / "textual" / "screens" / "planning_selector_model.py"
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
        component_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "ui" / "textual" / "screens" / "config_wizard_components.py"
        )
        component_actions_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "ui" / "textual" / "screens" / "config_wizard_component_actions.py"
        )
        action_bundle_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "ui" / "textual" / "screens" / "config_wizard_action_bundle.py"
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
        step_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "ui" / "textual" / "screens" / "config_wizard_step_flow.py"
        )
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
            REPO_ROOT / "python" / "envctl_engine" / "ui" / "textual" / "screens" / "config_wizard_flow_actions.py"
        )
        focus_actions_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "ui" / "textual" / "screens" / "config_wizard_focus_actions.py"
        )
        body_actions_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "ui" / "textual" / "screens" / "config_wizard_body_actions.py"
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
        self.assertIn("from .config_wizard_suggestion_actions import ConfigWizardSuggestionActions", action_bundle_text)
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
