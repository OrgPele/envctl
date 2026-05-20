# Python Engine Architecture

This inventory records the current ownership boundaries for the Python engine refactor. It is a maintained reference for contributors moving code out of broad orchestration modules while preserving public envctl behavior.

## Ownership Map

| Workflow area | Public entry point | Current owner modules | Contract tests and artifacts |
| --- | --- | --- | --- |
| CLI dispatch and runtime facade | `python/envctl_engine/runtime/engine_runtime.py` | `python/envctl_engine/runtime/command_router.py`, `python/envctl_engine/runtime/engine_runtime_dispatch.py`, `python/envctl_engine/runtime/engine_runtime_commands.py`, `python/envctl_engine/runtime/engine_runtime_lifecycle_support.py` | `tests/python/runtime/test_command_router_contract.py`, `tests/python/runtime/test_command_dispatch_matrix.py`, `contracts/runtime_feature_matrix.json` |
| Startup and resume orchestration | `python/envctl_engine/startup/startup_orchestrator.py` | `python/envctl_engine/startup/startup_execution_support.py`, `python/envctl_engine/startup/startup_selection_support.py`, `python/envctl_engine/startup/service_bootstrap_domain.py`, `python/envctl_engine/startup/finalization.py`, `python/envctl_engine/startup/resume_orchestrator.py` | `tests/python/startup`, `tests/python/runtime/test_engine_runtime_real_startup.py` |
| Action commands | `python/envctl_engine/actions/action_command_orchestrator.py` | `python/envctl_engine/actions/action_target_support.py`, `python/envctl_engine/actions/action_summary_support.py`, `python/envctl_engine/actions/action_project_result_support.py`, `python/envctl_engine/actions/action_command_support.py`, `python/envctl_engine/actions/action_test_support.py`, `python/envctl_engine/actions/action_test_runner.py`, `python/envctl_engine/actions/action_worktree_runner.py`, `python/envctl_engine/actions/project_action_domain.py` | `tests/python/actions`, `tests/python/actions/test_action_target_support.py`, `tests/python/actions/test_action_summary_support.py`, `tests/python/actions/test_action_project_result_support.py` |
| Planning and worktrees | `python/envctl_engine/planning/worktree_domain.py` | `python/envctl_engine/planning/menu.py`, `python/envctl_engine/planning/worktree_orchestrator.py`, `python/envctl_engine/planning/plan_agent_launch_support.py` | `tests/python/planning/test_planning_worktree_setup.py`, `tests/python/planning/test_discovery_topology.py` |
| Plan-agent transports | `python/envctl_engine/planning/plan_agent/launch.py` | `python/envctl_engine/planning/plan_agent/models.py`, `python/envctl_engine/planning/plan_agent/workflow.py`, `python/envctl_engine/planning/plan_agent/tmux_transport.py`, `python/envctl_engine/planning/plan_agent/cmux_transport.py`, `python/envctl_engine/planning/plan_agent/omx_transport.py`, `python/envctl_engine/planning/plan_agent/superset_transport.py`, `python/envctl_engine/planning/plan_agent/recovery.py` | `tests/python/planning/test_plan_agent_launch_support.py`, `tests/python/planning/test_plan_agent_module_layout.py` |
| Requirements and dependencies | `python/envctl_engine/requirements/orchestrator.py` | `python/envctl_engine/requirements/adapter_base.py`, `python/envctl_engine/requirements/postgres.py`, `python/envctl_engine/requirements/redis.py`, `python/envctl_engine/requirements/n8n.py`, `python/envctl_engine/requirements/supabase.py`, `python/envctl_engine/requirements/supabase_auth_users.py` | `tests/python/requirements`, `tests/python/requirements/test_requirements_adapters_real_contracts.py` |
| Dashboard and terminal UI | `python/envctl_engine/ui/dashboard/orchestrator.py` | `python/envctl_engine/ui/dashboard/rendering.py`, `python/envctl_engine/ui/dashboard/pr_flow.py`, `python/envctl_engine/ui/dashboard/terminal_ui.py`, `python/envctl_engine/ui/command_loop.py`, `python/envctl_engine/ui/selection_support.py` | `tests/python/ui`, `tests/python/ui/test_dashboard_orchestrator_restart_selector.py` |
| Runtime state and debug artifacts | `python/envctl_engine/state/models.py` | `python/envctl_engine/state/repository.py`, `python/envctl_engine/state/runtime_map.py`, `python/envctl_engine/debug/debug_bundle.py`, `python/envctl_engine/debug/debug_contract.py` | `tests/python/state`, `tests/python/debug`, `contracts/python_runtime_gap_report.json`, `contracts/python_engine_parity_manifest.json` |

## Compatibility Invariants

- Supported CLI flags, aliases, exit-status categories, and route selection must remain compatible with `command_router.py` and generated runtime inventory output.
- `PythonEngineRuntime` remains the public runtime facade. Refactors should move implementation behind it, not remove the facade until all callers and tests have migrated.
- `.envctl-state` artifacts, runtime state JSON, debug bundles, startup logs, and generated contract formats must remain backward compatible unless a task explicitly requires a compatible schema update.
- Prompt install behavior and plan-agent launch semantics must not drift across Codex, OpenCode, tmux, cmux, omx, ULW, new-session, headless, and direct-prompt paths.
- Worktree operations may create or edit the target generated worktree, but implementation tasks in a checked-out worktree must not mutate sibling worktrees or paths outside the current repo root.
- Requirement adapters must keep their public adapter API stable for startup and runtime callers while lifecycle, health, user, and database details move into smaller helpers.
- Dashboard and terminal UI changes must preserve status text that tests or users rely on for startup, restart, action, PR, and failure summaries.

## Generated Contracts

The following checked-in artifacts are compatibility contracts, not incidental outputs:

- `contracts/runtime_feature_matrix.json`
- `contracts/python_runtime_gap_report.json`
- `contracts/python_engine_parity_manifest.json`

Regenerate them only when the declared behavior changes intentionally. Pair any artifact update with the generator command, an explanation of the behavior change, and the relevant runtime or dispatch tests.

## Change Guide

- For runtime dispatch changes, start with `python/envctl_engine/runtime/command_router.py` and the focused runtime command tests before editing `python/envctl_engine/runtime/engine_runtime.py`.
- For startup changes, keep `python/envctl_engine/startup/startup_orchestrator.py` as the sequence owner and move low-level policy, bootstrap, rendering, or finalization behavior into the startup support modules.
- For action command changes, put target resolution in `python/envctl_engine/actions/action_target_support.py`, failure-summary formatting in `python/envctl_engine/actions/action_summary_support.py`, project action result persistence in `python/envctl_engine/actions/action_project_result_support.py`, environment and replacements in `python/envctl_engine/actions/action_command_support.py`, test execution in `python/envctl_engine/actions/action_test_support.py` or `action_test_runner.py`, and worktree deletion behavior in `python/envctl_engine/actions/action_worktree_runner.py`.
- For planning worktree changes, keep public call signatures stable in `python/envctl_engine/planning/worktree_domain.py` while moving selection, provenance, code-intelligence, and worktree lifecycle internals behind smaller helpers.
- For plan-agent transport changes, update the shared launch models and workflow helpers first, then adjust transport-specific code in `python/envctl_engine/planning/plan_agent/`.
- For Supabase changes, preserve the adapter contract in `python/envctl_engine/requirements/supabase.py` while extracting configuration, Docker lifecycle, health/readiness, database setup, QA user setup, and repair/reinit behavior behind focused components.
- For dashboard changes, keep rendering in `python/envctl_engine/ui/dashboard/rendering.py`, PR flow behavior in `python/envctl_engine/ui/dashboard/pr_flow.py`, and terminal-specific behavior in `python/envctl_engine/ui/dashboard/terminal_ui.py`.
