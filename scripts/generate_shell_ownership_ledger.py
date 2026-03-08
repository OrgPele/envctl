#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path


def _ensure_python_path(repo_root: Path) -> None:
    python_root = repo_root / "python"
    if str(python_root) not in sys.path:
        sys.path.insert(0, str(python_root))


def _owner_for_command(command: str) -> tuple[str, str, list[str]]:
    runtime_module = "python/envctl_engine/engine_runtime.py"
    owner_map: dict[str, tuple[str, str, list[str]]] = {
        "start": (runtime_module, "PythonEngineRuntime._start", ["tests/python/test_engine_runtime_real_startup.py"]),
        "plan": (runtime_module, "PythonEngineRuntime._start", ["tests/python/test_engine_runtime_real_startup.py"]),
        "resume": (runtime_module, "PythonEngineRuntime._resume", ["tests/python/test_state_roundtrip.py"]),
        "restart": (runtime_module, "PythonEngineRuntime._start", ["tests/python/test_lifecycle_parity.py"]),
        "stop": (runtime_module, "PythonEngineRuntime._stop", ["tests/python/test_lifecycle_parity.py"]),
        "stop-all": (runtime_module, "PythonEngineRuntime._stop", ["tests/python/test_lifecycle_parity.py"]),
        "blast-all": (runtime_module, "PythonEngineRuntime._stop", ["tests/python/test_lifecycle_parity.py"]),
        "doctor": (runtime_module, "PythonEngineRuntime._doctor", ["tests/python/test_engine_runtime_command_parity.py"]),
        "config": ("python/envctl_engine/config_command_support.py", "run_config_command", ["tests/python/test_config_wizard_domain.py"]),
        "dashboard": (runtime_module, "PythonEngineRuntime._dashboard", ["tests/python/test_engine_runtime_command_parity.py"]),
        "logs": (runtime_module, "PythonEngineRuntime._state_action", ["tests/python/test_engine_runtime_command_parity.py"]),
        "health": (runtime_module, "PythonEngineRuntime._state_action", ["tests/python/test_runtime_health_truth.py"]),
        "errors": (runtime_module, "PythonEngineRuntime._state_action", ["tests/python/test_runtime_health_truth.py"]),
        "test": ("python/envctl_engine/actions_test.py", "default_test_command", ["tests/python/test_actions_parity.py"]),
        "delete-worktree": ("python/envctl_engine/actions_worktree.py", "delete_worktree_path", ["tests/python/test_actions_parity.py"]),
        "blast-worktree": ("python/envctl_engine/actions_worktree.py", "delete_worktree_path", ["tests/python/test_actions_parity.py"]),
        "pr": ("python/envctl_engine/actions_git.py", "default_pr_command", ["tests/python/test_actions_parity.py"]),
        "commit": ("python/envctl_engine/actions_git.py", "default_commit_command", ["tests/python/test_actions_parity.py"]),
        "analyze": ("python/envctl_engine/actions_analysis.py", "default_analyze_command", ["tests/python/test_actions_parity.py"]),
        "migrate": ("python/envctl_engine/actions_analysis.py", "default_migrate_command", ["tests/python/test_actions_parity.py"]),
        "list-commands": ("python/envctl_engine/command_router.py", "list_supported_commands", ["tests/python/test_cli_router_parity.py"]),
        "list-targets": (runtime_module, "PythonEngineRuntime._discover_projects", ["tests/python/test_discovery_topology.py"]),
        "help": (runtime_module, "PythonEngineRuntime._print_help", ["tests/python/test_cli_router.py"]),
    }
    return owner_map.get(
        command,
        (runtime_module, "PythonEngineRuntime.dispatch", ["tests/python/test_engine_runtime_command_parity.py"]),
    )


_WAVE_A_MODULES = {
    "lib/engine/lib/state.sh",
    "lib/engine/lib/services_lifecycle.sh",
    "lib/engine/lib/ports.sh",
    "lib/engine/lib/services_logs.sh",
    "lib/engine/lib/runtime_map.sh",
    "lib/engine/lib/run_cache.sh",
    "lib/engine/lib/services_registry.sh",
    "lib/engine/lib/services_worktrees.sh",
}
_WAVE_B_MODULES = {
    "lib/engine/lib/docker.sh",
    "lib/engine/lib/requirements.sh",
    "lib/engine/lib/requirements_core.sh",
    "lib/engine/lib/requirements_supabase.sh",
    "lib/engine/lib/requirements_seed.sh",
}
_WAVE_C_MODULES = {
    "lib/engine/lib/actions.sh",
    "lib/engine/lib/planning.sh",
    "lib/engine/lib/run_all_trees_helpers.sh",
    "lib/engine/lib/run_all_trees_cli.sh",
    "lib/engine/lib/setup_worktrees.sh",
    "lib/engine/lib/worktrees.sh",
    "lib/engine/lib/ui.sh",
    "lib/engine/lib/summary.sh",
}

_ENTRY_OWNER_BY_MODULE: dict[str, tuple[str, str]] = {
    "lib/engine/lib/actions.sh": (
        "python/envctl_engine/action_command_orchestrator.py",
        "ActionCommandOrchestrator.execute",
    ),
    "lib/engine/lib/analysis.sh": (
        "python/envctl_engine/actions_analysis.py",
        "default_analyze_command",
    ),
    "lib/engine/lib/cli.sh": (
        "python/envctl_engine/command_router.py",
        "parse_route",
    ),
    "lib/engine/lib/config.sh": (
        "python/envctl_engine/config.py",
        "load_config",
    ),
    "lib/engine/lib/config_loader.sh": (
        "python/envctl_engine/config.py",
        "_load_envctl_file",
    ),
    "lib/engine/lib/core.sh": (
        "python/envctl_engine/action_utils.py",
        "detect_repo_python",
    ),
    "lib/engine/lib/create_pr_helpers.sh": (
        "python/envctl_engine/actions_git.py",
        "default_pr_command",
    ),
    "lib/engine/lib/debug.sh": (
        "python/envctl_engine/doctor_orchestrator.py",
        "DoctorOrchestrator.execute",
    ),
    "lib/engine/lib/deploy_production_helpers.sh": (
        "python/envctl_engine/actions_analysis.py",
        "default_analyze_command",
    ),
    "lib/engine/lib/docker.sh": (
        "python/envctl_engine/lifecycle_cleanup_orchestrator.py",
        "LifecycleCleanupOrchestrator.blast_all_docker_cleanup",
    ),
    "lib/engine/lib/env.sh": (
        "python/envctl_engine/env_access.py",
        "str_from_env",
    ),
    "lib/engine/lib/fs.sh": (
        "python/envctl_engine/state.py",
        "load_state",
    ),
    "lib/engine/lib/git.sh": (
        "python/envctl_engine/actions_git.py",
        "default_commit_command",
    ),
    "lib/engine/lib/loader.sh": (
        "python/envctl_engine/config.py",
        "load_config",
    ),
    "lib/engine/lib/planning.sh": (
        "python/envctl_engine/planning.py",
        "resolve_planning_files",
    ),
    "lib/engine/lib/ports.sh": (
        "python/envctl_engine/ports.py",
        "PortPlanner.reserve_next",
    ),
    "lib/engine/lib/pr.sh": (
        "python/envctl_engine/actions_git.py",
        "default_pr_command",
    ),
    "lib/engine/lib/python.sh": (
        "python/envctl_engine/node_tooling.py",
        "detect_python_bin",
    ),
    "lib/engine/lib/requirements_core.sh": (
        "python/envctl_engine/requirements_orchestrator.py",
        "RequirementsOrchestrator.start_requirement",
    ),
    "lib/engine/lib/requirements_seed.sh": (
        "python/envctl_engine/requirements/supabase.py",
        "start_supabase_stack",
    ),
    "lib/engine/lib/requirements_supabase.sh": (
        "python/envctl_engine/requirements/supabase.py",
        "start_supabase_stack",
    ),
    "lib/engine/lib/run_all_trees_cli.sh": (
        "python/envctl_engine/planning.py",
        "filter_projects_for_plan",
    ),
    "lib/engine/lib/run_all_trees_helpers.sh": (
        "python/envctl_engine/planning.py",
        "discover_tree_projects",
    ),
    "lib/engine/lib/run_cache.sh": (
        "python/envctl_engine/state_repository.py",
        "RuntimeStateRepository.load_latest",
    ),
    "lib/engine/lib/runtime_map.sh": (
        "python/envctl_engine/runtime_map.py",
        "build_runtime_map",
    ),
    "lib/engine/lib/services_lifecycle.sh": (
        "python/envctl_engine/lifecycle_cleanup_orchestrator.py",
        "LifecycleCleanupOrchestrator.execute",
    ),
    "lib/engine/lib/services_logs.sh": (
        "python/envctl_engine/state_action_orchestrator.py",
        "StateActionOrchestrator.execute",
    ),
    "lib/engine/lib/services_registry.sh": (
        "python/envctl_engine/service_manager.py",
        "ServiceManager.start_project_with_attach",
    ),
    "lib/engine/lib/services_worktrees.sh": (
        "python/envctl_engine/startup_orchestrator.py",
        "StartupOrchestrator.start_project_context",
    ),
    "lib/engine/lib/setup_worktrees.sh": (
        "python/envctl_engine/startup_orchestrator.py",
        "StartupOrchestrator.start_project_context",
    ),
    "lib/engine/lib/state.sh": (
        "python/envctl_engine/state_repository.py",
        "RuntimeStateRepository.save_run",
    ),
    "lib/engine/lib/summary.sh": (
        "python/envctl_engine/dashboard_orchestrator.py",
        "DashboardOrchestrator.execute",
    ),
    "lib/engine/lib/test_runner.sh": (
        "python/envctl_engine/actions_test.py",
        "default_test_command",
    ),
    "lib/engine/lib/tests.sh": (
        "python/envctl_engine/actions_test.py",
        "build_test_args",
    ),
    "lib/engine/lib/ui.sh": (
        "python/envctl_engine/terminal_ui.py",
        "RuntimeTerminalUI.planning_selection",
    ),
    "lib/engine/lib/worktrees.sh": (
        "python/envctl_engine/actions_worktree.py",
        "delete_worktree_path",
    ),
}

_EVIDENCE_TESTS_BY_MODULE: dict[str, list[str]] = {
    "lib/engine/lib/actions.sh": ["tests/python/test_actions_parity.py"],
    "lib/engine/lib/analysis.sh": ["tests/python/test_actions_parity.py"],
    "lib/engine/lib/cli.sh": [
        "tests/python/test_cli_router.py",
        "tests/python/test_cli_router_parity.py",
        "tests/python/test_command_router_contract.py",
    ],
    "lib/engine/lib/config.sh": ["tests/python/test_config_loader.py"],
    "lib/engine/lib/config_loader.sh": ["tests/python/test_config_loader.py"],
    "lib/engine/lib/core.sh": ["tests/python/test_utility_consolidation_contract.py"],
    "lib/engine/lib/create_pr_helpers.sh": ["tests/python/test_actions_parity.py"],
    "lib/engine/lib/debug.sh": ["tests/python/test_cli_router_parity.py"],
    "lib/engine/lib/deploy_production_helpers.sh": ["tests/python/test_actions_parity.py"],
    "lib/engine/lib/docker.sh": ["tests/python/test_prereq_policy.py"],
    "lib/engine/lib/env.sh": [
        "tests/python/test_config_loader.py",
        "tests/python/test_runtime_scope_isolation.py",
    ],
    "lib/engine/lib/fs.sh": ["tests/python/test_state_loader.py"],
    "lib/engine/lib/git.sh": ["tests/python/test_actions_parity.py"],
    "lib/engine/lib/loader.sh": ["tests/python/test_config_loader.py"],
    "lib/engine/lib/planning.sh": [
        "tests/python/test_planning_selection.py",
        "tests/python/test_discovery_topology.py",
    ],
    "lib/engine/lib/ports.sh": [
        "tests/python/test_port_plan.py",
        "tests/python/test_ports_lock_reclamation.py",
        "tests/python/test_ports_availability_strategies.py",
        "tests/python/test_engine_runtime_port_reservation_failures.py",
    ],
    "lib/engine/lib/pr.sh": ["tests/python/test_actions_parity.py"],
    "lib/engine/lib/python.sh": ["tests/python/test_utility_consolidation_contract.py"],
    "lib/engine/lib/requirements_core.sh": [
        "tests/python/test_requirements_orchestrator.py",
        "tests/python/test_requirements_adapters_real_contracts.py",
        "tests/python/test_requirements_retry.py",
    ],
    "lib/engine/lib/requirements_seed.sh": ["tests/python/test_requirements_adapters_real_contracts.py"],
    "lib/engine/lib/requirements_supabase.sh": [
        "tests/python/test_requirements_adapters_real_contracts.py",
        "tests/python/test_supabase_requirements_reliability.py",
    ],
    "lib/engine/lib/run_all_trees_cli.sh": [
        "tests/python/test_planning_selection.py",
        "tests/python/test_planning_worktree_setup.py",
    ],
    "lib/engine/lib/run_all_trees_helpers.sh": [
        "tests/python/test_planning_worktree_setup.py",
        "tests/python/test_discovery_topology.py",
    ],
    "lib/engine/lib/run_cache.sh": ["tests/python/test_planning_selection.py"],
    "lib/engine/lib/runtime_map.sh": [
        "tests/python/test_runtime_projection_urls.py",
        "tests/python/test_frontend_env_projection_real_ports.py",
        "tests/python/test_frontend_projection.py",
    ],
    "lib/engine/lib/services_lifecycle.sh": [
        "tests/python/test_service_manager.py",
        "tests/python/test_lifecycle_parity.py",
    ],
    "lib/engine/lib/services_logs.sh": ["tests/python/test_logs_parity.py"],
    "lib/engine/lib/services_registry.sh": ["tests/python/test_service_manager.py"],
    "lib/engine/lib/services_worktrees.sh": [
        "tests/python/test_service_manager.py",
        "tests/python/test_planning_worktree_setup.py",
    ],
    "lib/engine/lib/setup_worktrees.sh": ["tests/python/test_planning_worktree_setup.py"],
    "lib/engine/lib/state.sh": [
        "tests/python/test_state_roundtrip.py",
        "tests/python/test_state_shell_compatibility.py",
        "tests/python/test_state_loader.py",
        "tests/python/test_state_repository_contract.py",
    ],
    "lib/engine/lib/summary.sh": [
        "tests/python/test_runtime_health_truth.py",
        "tests/python/test_dashboard_rendering_parity.py",
    ],
    "lib/engine/lib/test_runner.sh": ["tests/python/test_actions_parity.py"],
    "lib/engine/lib/tests.sh": ["tests/python/test_actions_parity.py"],
    "lib/engine/lib/ui.sh": [
        "tests/python/test_interactive_input_reliability.py",
        "tests/python/test_planning_menu_rendering.py",
        "tests/python/test_dashboard_rendering_parity.py",
    ],
    "lib/engine/lib/worktrees.sh": [
        "tests/python/test_planning_worktree_setup.py",
        "tests/python/test_discovery_topology.py",
    ],
}


def _delete_wave_for_module(module: str) -> str:
    if module in _WAVE_A_MODULES:
        return "wave-a"
    if module in _WAVE_B_MODULES or module.startswith("lib/engine/lib/requirements"):
        return "wave-b"
    if module in _WAVE_C_MODULES:
        return "wave-c"
    return "wave-d"


def _owner_for_shell_entry(module: str) -> tuple[str, str, str]:
    owner = _ENTRY_OWNER_BY_MODULE.get(module)
    if owner is not None:
        return owner[0], owner[1], "Auto-generated shell inventory entry mapped to Python owner by module domain."
    return (
        "python/envctl_engine/engine_runtime.py",
        "PythonEngineRuntime._print_help",
        "Auto-generated shell inventory entry with unresolved owner mapping. Classify with concrete owner before prune.",
    )


def _evidence_tests_for_module(module: str) -> list[str]:
    return list(_EVIDENCE_TESTS_BY_MODULE.get(module, []))


def build_ledger_payload(repo_root: Path) -> dict[str, object]:
    shell_prune = importlib.import_module("envctl_engine.shell.shell_prune")
    discover_sourced_shell_modules = shell_prune.discover_sourced_shell_modules
    iter_module_functions = shell_prune.iter_module_functions
    python_complete_commands = shell_prune.python_complete_commands

    modules = sorted(discover_sourced_shell_modules(repo_root))
    module_function_pairs = iter_module_functions(repo_root, modules)
    entries: list[dict[str, object]] = []
    for module, function_name in module_function_pairs:
        owner_module, owner_symbol, notes = _owner_for_shell_entry(module)
        entries.append(
            {
                "shell_module": module,
                "shell_function": function_name,
                "python_owner_module": owner_module,
                "python_owner_symbol": owner_symbol,
                "status": "unmigrated",
                "evidence_tests": _evidence_tests_for_module(module),
                "delete_wave": _delete_wave_for_module(module),
                "notes": notes,
                "commands": [],
            }
        )

    command_mappings: list[dict[str, object]] = []
    for command in sorted(python_complete_commands(repo_root)):
        owner_module, owner_symbol, tests = _owner_for_command(command)
        command_mappings.append(
            {
                "command": command,
                "python_owner_module": owner_module,
                "python_owner_symbol": owner_symbol,
                "evidence_tests": tests,
            }
        )

    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payload: dict[str, object] = {
        "version": 1,
        "generated_at": now,
        "source_modules": modules,
        "compat_shim_allowlist": [
            "lib/envctl.sh",
            "lib/engine/main.sh",
            "scripts/install.sh",
        ],
        "command_mappings": command_mappings,
        "entries": entries,
    }
    return payload


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    parser = argparse.ArgumentParser(description="Generate envctl shell ownership ledger from sourced shell modules.")
    parser.add_argument("--repo", default=".", help="Repository root (default: current dir).")
    parser.add_argument(
        "--output",
        default="docs/planning/refactoring/envctl-shell-ownership-ledger.json",
        help="Ledger output path relative to repo root.",
    )
    parser.add_argument("--stdout", action="store_true", help="Print generated JSON to stdout instead of writing to file.")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    _ensure_python_path(repo_root)

    payload = build_ledger_payload(repo_root)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.stdout:
        print(rendered, end="")
        return 0

    output_path = repo_root / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    print(f"Wrote shell ownership ledger: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
