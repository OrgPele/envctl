from pathlib import Path
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]


class PlanningWorktreeStructureLayoutTests(unittest.TestCase):
    def test_plan_agent_launch_tests_are_split_by_transport_owner(self) -> None:
        planning_tests = REPO_ROOT / "tests" / "python" / "planning"
        policy_owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "plan_agent" / "launch_policy.py"
        config_facade = REPO_ROOT / "python" / "envctl_engine" / "planning" / "plan_agent" / "config.py"
        tmux_workflow_facade = (
            REPO_ROOT / "python" / "envctl_engine" / "planning" / "plan_agent" / "tmux_workflow_submission_support.py"
        )
        tmux_submission_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "planning" / "plan_agent" / "tmux_prompt_submission_support.py"
        )
        tmux_readiness_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "planning" / "plan_agent" / "tmux_prompt_readiness_support.py"
        )
        tmux_queue_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "planning" / "plan_agent" / "tmux_workflow_queue_support.py"
        )
        queue_interaction_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "planning" / "plan_agent" / "workflow_queue_interaction.py"
        )
        bootstrap_command_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "planning" / "plan_agent" / "workflow_bootstrap_commands.py"
        )
        cmux_queue_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "planning" / "plan_agent" / "cmux_workflow_submission_support.py"
        )
        startup_spinner_owner = REPO_ROOT / "python" / "envctl_engine" / "startup" / "plan_agent_launch_spinner.py"
        dependency_bootstrap_owner = (
            REPO_ROOT / "python" / "envctl_engine" / "startup" / "plan_agent_dependency_bootstrap.py"
        )
        expected = [
            "plan_agent_launch_support_test_support.py",
            "test_plan_agent_launch_cmux_cycles.py",
            "test_plan_agent_launch_cmux_goal.py",
            "test_plan_agent_launch_cmux_review.py",
            "test_plan_agent_launch_cmux_workspace_configured.py",
            "test_plan_agent_launch_cmux_workspace_created.py",
            "test_plan_agent_launch_cmux_workspace_default.py",
            "test_plan_agent_launch_cmux_workspace_flow.py",
            "test_plan_agent_launch_omx_config.py",
            "test_plan_agent_launch_omx_spawn.py",
            "test_plan_agent_launch_omx_workflow.py",
            "test_plan_agent_launch_readiness.py",
            "test_plan_agent_launch_policy.py",
            "test_plan_agent_launch_superset.py",
            "test_plan_agent_launch_superset_desktop.py",
            "test_plan_agent_launch_tmux_existing_session.py",
            "test_plan_agent_launch_tmux_flow.py",
            "test_plan_agent_launch_tmux_identity_window.py",
            "test_plan_agent_launch_tmux_readiness.py",
            "test_plan_agent_launch_tmux_workflow_queue.py",
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
        self.assertTrue(startup_spinner_owner.is_file())
        self.assertIn("class PlanAgentLaunchSpinner", startup_spinner_owner.read_text(encoding="utf-8"))
        self.assertTrue(dependency_bootstrap_owner.is_file())
        self.assertIn("class PlanAgentDependencyBootstrapper", dependency_bootstrap_owner.read_text(encoding="utf-8"))
        for owner, symbol in (
            (tmux_submission_owner, "def submit_tmux_prompt_workflow_step"),
            (tmux_readiness_owner, "def wait_for_tmux_cli_ready"),
            (tmux_queue_owner, "def queue_tmux_codex_workflow_steps"),
            (queue_interaction_owner, "class CodexQueueMessageInteractor"),
            (bootstrap_command_owner, "class CliBootstrapCommandTyper"),
        ):
            with self.subTest(owner=owner.name):
                owner_text = owner.read_text(encoding="utf-8")
                self.assertIn(symbol, owner_text)
        tmux_workflow_text = tmux_workflow_facade.read_text(encoding="utf-8")
        self.assertIn(
            "from envctl_engine.planning.plan_agent.tmux_prompt_submission_support import", tmux_workflow_text
        )
        self.assertIn("from envctl_engine.planning.plan_agent.tmux_prompt_readiness_support import", tmux_workflow_text)
        self.assertIn("from envctl_engine.planning.plan_agent.tmux_workflow_queue_support import", tmux_workflow_text)
        self.assertLessEqual(len(tmux_workflow_text.splitlines()), 420)
        queue_owner_text = queue_interaction_owner.read_text(encoding="utf-8")
        tmux_queue_text = tmux_queue_owner.read_text(encoding="utf-8")
        cmux_queue_text = cmux_queue_owner.read_text(encoding="utf-8")
        self.assertIn("def wait_until_codex_queue_ready", queue_owner_text)
        self.assertIn("from envctl_engine.planning.plan_agent.workflow_queue_interaction import", tmux_queue_text)
        self.assertIn("from envctl_engine.planning.plan_agent.workflow_queue_interaction import", cmux_queue_text)
        self.assertIn(
            "from envctl_engine.planning.plan_agent.workflow_bootstrap_commands import",
            tmux_submission_owner.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "from envctl_engine.planning.plan_agent.workflow_bootstrap_commands import",
            cmux_queue_text,
        )
        config_text = config_facade.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.planning.plan_agent.launch_policy import", config_text)
        self.assertLessEqual(len(config_text.splitlines()), 140)

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

    def test_planning_package_exports_are_backed_by_owner_modules(self) -> None:
        package = REPO_ROOT / "python" / "envctl_engine" / "planning" / "__init__.py"
        identity_owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_identity.py"
        files_owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "planning_files.py"
        discovery_owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "planning_tree_discovery.py"
        prediction_owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "planning_project_prediction.py"

        self.assertTrue(identity_owner.is_file())
        self.assertTrue(files_owner.is_file())
        self.assertTrue(discovery_owner.is_file())
        self.assertTrue(prediction_owner.is_file())
        package_text = package.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.planning.worktree_identity import", package_text)
        self.assertIn("from envctl_engine.planning.planning_files import", package_text)
        self.assertIn("from envctl_engine.planning.planning_tree_discovery import", package_text)
        self.assertIn("from envctl_engine.planning.planning_project_prediction import", package_text)
        self.assertIn("class GeneratedWorktreeIdentity", identity_owner.read_text(encoding="utf-8"))
        self.assertIn("def generated_worktree_identity", identity_owner.read_text(encoding="utf-8"))
        self.assertIn("def list_planning_files", files_owner.read_text(encoding="utf-8"))
        self.assertIn("def resolve_planning_files", files_owner.read_text(encoding="utf-8"))
        self.assertIn("def discover_tree_projects", discovery_owner.read_text(encoding="utf-8"))
        self.assertIn("def filter_projects_for_plan", discovery_owner.read_text(encoding="utf-8"))
        self.assertIn("class PlanProjectPrediction", prediction_owner.read_text(encoding="utf-8"))
        self.assertIn("def predict_plan_projects", prediction_owner.read_text(encoding="utf-8"))
        self.assertLessEqual(len(package_text.splitlines()), 90)

    def test_worktree_path_support_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_path_support.py"
        menu_owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_menu_terminal_support.py"
        spinner_owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_spinner_support.py"
        runtime_bridge = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_runtime_bridge.py"
        selection_runtime_bridge = (
            REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_selection_runtime_bridge.py"
        )
        sync_runtime_bridge = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_sync_runtime_bridge.py"
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
        self.assertIn(
            "from envctl_engine.planning.worktree_runtime_bridge import create_planning_runtime_bridge", facade_text
        )
        top_level_imports = "\n".join(line for line in facade_text.splitlines() if line.startswith("from "))
        self.assertNotIn("from envctl_engine.actions.actions_worktree import", top_level_imports)
        self.assertNotIn("from envctl_engine.runtime.runtime_context import", top_level_imports)
        self.assertIn("def delete_worktree_path", facade_text)
        self.assertIn("def select_planning_counts_textual", facade_text)
        self.assertIn("from envctl_engine.planning.protocols import ProjectContextLike", facade_text)
        self.assertNotIn("class ProjectContextLike(Protocol)", facade_text)
        self.assertNotIn(
            "return _coerce_setup_entries_impl(flags=route.flags, flag_name=flag_name, value_name=value_name)\n    return _coerce_setup_entries_impl",
            facade_text,
        )
        self.assertLessEqual(len(facade_text.splitlines()), 720)

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
        selection_bridge = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_selection_runtime_bridge.py"

        self.assertTrue(owner.is_file())
        self.assertTrue(protocols.is_file())
        self.assertIn(
            "from envctl_engine.planning.worktree_plan_project_selection import",
            selection_bridge.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "from envctl_engine.planning.protocols import ProjectContextLike", owner.read_text(encoding="utf-8")
        )
        self.assertNotIn("class ProjectContextLike(Protocol)", owner.read_text(encoding="utf-8"))

    def test_worktree_prompt_selection_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_prompt_selection.py"
        selection_bridge = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_selection_runtime_bridge.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.planning.worktree_prompt_selection import",
            selection_bridge.read_text(encoding="utf-8"),
        )

    def test_worktree_planning_menu_has_owned_module(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_planning_menu.py"
        selection_bridge = REPO_ROOT / "python" / "envctl_engine" / "planning" / "worktree_selection_runtime_bridge.py"

        self.assertTrue(owner.is_file())
        self.assertIn(
            "from envctl_engine.planning.worktree_planning_menu import",
            selection_bridge.read_text(encoding="utf-8"),
        )

    def test_planning_menu_behavior_has_owner_modules(self) -> None:
        facade = REPO_ROOT / "python" / "envctl_engine" / "planning" / "menu.py"
        render_owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "menu_rendering.py"
        input_owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "menu_input.py"
        selection_owner = REPO_ROOT / "python" / "envctl_engine" / "planning" / "menu_selection.py"

        self.assertTrue(render_owner.is_file())
        self.assertTrue(input_owner.is_file())
        self.assertTrue(selection_owner.is_file())
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("from envctl_engine.planning.menu_rendering import", facade_text)
        self.assertIn("from envctl_engine.planning.menu_input import", facade_text)
        self.assertIn("from envctl_engine.planning.menu_selection import", facade_text)
        self.assertIn("def render_planning_selection_menu", render_owner.read_text(encoding="utf-8"))
        self.assertIn("def read_planning_menu_key", input_owner.read_text(encoding="utf-8"))
        self.assertIn("def apply_planning_menu_key", selection_owner.read_text(encoding="utf-8"))
        self.assertLessEqual(len(facade_text.splitlines()), 340)

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
        self.assertIn(
            "from envctl_engine.planning.protocols import ProjectContextLike", owner.read_text(encoding="utf-8")
        )
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
