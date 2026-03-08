import ast
from pathlib import Path
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]
ENGINE_ROOT = REPO_ROOT / 'python' / 'envctl_engine'

DEPRECATED_IMPORTS = {
    'envctl_engine.action_command_orchestrator',
    'envctl_engine.action_command_support',
    'envctl_engine.action_target_support',
    'envctl_engine.action_test_runner',
    'envctl_engine.action_test_support',
    'envctl_engine.action_utils',
    'envctl_engine.action_worktree_runner',
    'envctl_engine.actions_analysis',
    'envctl_engine.actions_cli',
    'envctl_engine.actions_git',
    'envctl_engine.actions_test',
    'envctl_engine.actions_worktree',
    'envctl_engine.cli',
    'envctl_engine.command_resolution',
    'envctl_engine.command_router',
    'envctl_engine.config_command_support',
    'envctl_engine.config_persistence',
    'envctl_engine.config_wizard_domain',
    'envctl_engine.dashboard_orchestrator',
    'envctl_engine.dashboard_rendering_domain',
    'envctl_engine.debug_bundle',
    'envctl_engine.debug_contract',
    'envctl_engine.debug_utils',
    'envctl_engine.dependency_compose_assets',
    'envctl_engine.doctor_orchestrator',
    'envctl_engine.engine_runtime',
    'envctl_engine.engine_runtime_artifacts',
    'envctl_engine.engine_runtime_commands',
    'envctl_engine.engine_runtime_dashboard_truth',
    'envctl_engine.engine_runtime_debug_support',
    'envctl_engine.engine_runtime_diagnostics',
    'envctl_engine.engine_runtime_dispatch',
    'envctl_engine.engine_runtime_env',
    'envctl_engine.engine_runtime_event_support',
    'envctl_engine.engine_runtime_hooks',
    'envctl_engine.engine_runtime_lifecycle_support',
    'envctl_engine.engine_runtime_misc_support',
    'envctl_engine.engine_runtime_runtime_support',
    'envctl_engine.engine_runtime_service_policy',
    'envctl_engine.engine_runtime_service_truth',
    'envctl_engine.engine_runtime_startup_support',
    'envctl_engine.engine_runtime_state_lookup',
    'envctl_engine.engine_runtime_state_support',
    'envctl_engine.engine_runtime_state_truth',
    'envctl_engine.engine_runtime_ui_bridge',
    'envctl_engine.env_access',
    'envctl_engine.hooks',
    'envctl_engine.lifecycle_cleanup_orchestrator',
    'envctl_engine.models',
    'envctl_engine.node_tooling',
    'envctl_engine.parsing',
    'envctl_engine.planning_menu',
    'envctl_engine.ports',
    'envctl_engine.process_probe',
    'envctl_engine.process_runner',
    'envctl_engine.project_action_domain',
    'envctl_engine.protocols',
    'envctl_engine.reason_codes',
    'envctl_engine.release_gate',
    'envctl_engine.requirements_orchestrator',
    'envctl_engine.requirements_startup_domain',
    'envctl_engine.resume_orchestrator',
    'envctl_engine.runtime_context',
    'envctl_engine.runtime_map',
    'envctl_engine.service_bootstrap_domain',
    'envctl_engine.service_manager',
    'envctl_engine.services',
    'envctl_engine.shell_adapter',
    'envctl_engine.shell_prune',
    'envctl_engine.startup_orchestrator',
    'envctl_engine.state_action_orchestrator',
    'envctl_engine.state_repository',
    'envctl_engine.terminal_ui',
    'envctl_engine.worktree_planning_domain',
}

PACKAGE_ROOTS = [
    ENGINE_ROOT / 'actions',
    ENGINE_ROOT / 'config',
    ENGINE_ROOT / 'debug',
    ENGINE_ROOT / 'planning',
    ENGINE_ROOT / 'runtime',
    ENGINE_ROOT / 'shared',
    ENGINE_ROOT / 'shell',
    ENGINE_ROOT / 'startup',
    ENGINE_ROOT / 'state',
    ENGINE_ROOT / 'ui' / 'dashboard',
    ENGINE_ROOT / 'ui' / 'textual' / 'screens' / 'selector',
]


class ImportAuditTests(unittest.TestCase):
    def test_domain_packages_do_not_depend_on_flat_shim_modules(self) -> None:
        violations: list[str] = []
        for package_root in PACKAGE_ROOTS:
            for path in package_root.rglob('*.py'):
                tree = ast.parse(path.read_text(), filename=str(path))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name in DEPRECATED_IMPORTS:
                                violations.append(f'{path}: import {alias.name}')
                    elif isinstance(node, ast.ImportFrom) and node.module in DEPRECATED_IMPORTS:
                        violations.append(f'{path}: from {node.module} import ...')
        self.assertEqual([], violations)


if __name__ == '__main__':
    unittest.main()
