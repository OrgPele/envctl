# Envctl Python Engine MAIN_TASK Execution Plan

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Deliver Python runtime parity for core command families (`start`, `plan`, `resume`, `restart`, `stop`, `stop-all`, `blast-all`, `dashboard`, `doctor`, and action commands).
  - Make runtime truth authoritative: URLs, health, and summaries match live listeners/processes; no synthetic fallbacks in strict mode.
  - Convert shell ownership ledger from empty inventory into a wave-based migration backlog with evidence-backed coverage and enforceable budgets.
  - Keep release readiness truthful across doctor output, parity manifest, shell prune contract, and shipability gate.
- Non-goals:
  - Renaming `envctl`, changing the CLI surface, or removing shell fallback before strict gates are green.
  - Rewriting downstream application logic in target repositories.
  - Introducing new runtime dependencies beyond the current Python 3.12 and Docker baseline.
- Assumptions:
  - Python 3.12 remains required for Python mode (`lib/engine/main.sh`, `python/envctl_engine/cli.py`).
  - Docker remains the infra backend for postgres/redis/supabase/n8n (`python/envctl_engine/requirements/*.py`).
  - Planning files are rooted under `ENVCTL_PLANNING_DIR` (default `docs/planning`) as loaded in `python/envctl_engine/config.py`.

## Goal (user experience)
Running `envctl --plan` should be deterministic and low-friction: the interactive selector works on TTYs, selected plans create or reuse the correct worktrees, services start cleanly, and displayed URLs match actual listeners. `resume`, `restart`, `stop`, `stop-all`, and `blast-all` behave predictably, clean up state and locks, and do not report success when services are stale. The dashboard remains responsive with clear, accurate status and actionable failure output.

## Business logic and data model mapping
- Launcher and runtime selection:
  - `bin/envctl` -> `lib/envctl.sh:envctl_main` -> `lib/engine/main.sh` with `ENVCTL_ENGINE_SHELL_FALLBACK` gating.
- Python orchestration:
  - Routing: `python/envctl_engine/command_router.py:parse_route`.
  - Runtime dispatch: `python/envctl_engine/engine_runtime.py:PythonEngineRuntime.dispatch`.
  - Orchestrators already present: `python/envctl_engine/{startup,resume,doctor,dashboard,lifecycle_cleanup}_orchestrator.py`.
- Models and state:
  - `python/envctl_engine/models.py` (`PortPlan`, `ServiceRecord`, `RequirementsResult`, `RunState`).
  - `python/envctl_engine/state.py` (JSON + legacy shell state loading) and `python/envctl_engine/state_repository.py` (run artifacts, pointers, compat modes).
- Planning/worktrees:
  - Python: `python/envctl_engine/planning.py` (planning selection, discovery, counts).
  - Bash baseline: `lib/engine/lib/planning.sh`, `lib/engine/lib/worktrees.sh`, `lib/engine/lib/run_all_trees_helpers.sh`.
- Ports and runtime truth:
  - Python: `python/envctl_engine/ports.py:PortPlanner` and `python/envctl_engine/runtime_map.py`.
  - Bash baseline: `lib/engine/lib/ports.sh`, `lib/engine/lib/runtime_map.sh`.
- Requirements and services:
  - `python/envctl_engine/requirements_orchestrator.py`, `python/envctl_engine/requirements/*.py`.
  - `python/envctl_engine/service_manager.py` and `python/envctl_engine/process_runner.py`.
- Governance gates:
  - `python/envctl_engine/release_gate.py:evaluate_shipability`.
  - `python/envctl_engine/shell_prune.py:evaluate_shell_prune_contract`.

## Current behavior (verified in code)
- Shipability gate enforces required paths, parity sync, shell prune contract, and documented flag parity in `python/envctl_engine/release_gate.py:35` and is invoked by `scripts/release_shipability_gate.py`.
- Shell prune contract expects a non-empty ledger entries list when sourced modules exist (`python/envctl_engine/shell_prune.py:175-182`), but `docs/planning/refactoring/envctl-shell-ownership-ledger.json` currently has `"entries": []`.
- Doctor output uses `_doctor` and `_doctor_readiness_gates` in `python/envctl_engine/engine_runtime.py:2336` and emits `cutover.gate.evaluate` plus shell budget status via `_shell_prune_budget_profile` (`python/envctl_engine/engine_runtime.py:2665`).
- `PythonEngineRuntime.PARTIAL_COMMANDS` is an empty tuple (`python/envctl_engine/engine_runtime.py:78`), so runtime parity completeness depends on the parity manifest alone.
- Planning selection in Python uses `python/envctl_engine/planning.py:list_planning_files`, `resolve_planning_files`, and `planning_feature_name`, with interactive UI handled in `python/envctl_engine/planning_menu.py`.
- Bash planning orchestration uses `lib/engine/lib/planning.sh` and `lib/engine/lib/run_all_trees_helpers.sh:run_all_trees_handle_planning_envs`, which also moves plans to `Done/`.
- Worktree discovery in Bash uses `lib/engine/lib/worktrees.sh:list_tree_paths` and `worktree_identity_from_dir`, while Python uses `planning.py:discover_tree_projects` and `_discover_tree_roots`.
- Command resolution fails fast when missing configuration (`python/envctl_engine/command_resolution.py:resolve_service_start_command`, `resolve_requirement_start_command`) with tests in `tests/python/test_command_resolution.py`.
- Port reservation uses `python/envctl_engine/ports.py:PortPlanner` with socket bind or `lsof` probing and lock events (`port.lock.acquire`, `port.lock.reclaim`, `port.lock.release`).
- Runtime projection uses actual port when available, else requested port in `python/envctl_engine/runtime_map.py`.
- State compatibility is supported via JSON and legacy shell loaders in `python/envctl_engine/state.py`, with pointer management in `python/envctl_engine/state_repository.py`.

## Root cause(s) / gaps
1. **Ledger classification gap**: The shell ownership ledger entries list is empty even though `shell_prune.py` enforces populated entries when sourced modules exist. This blocks meaningful budgets and migration tracking.
2. **Governance explicitness gap**: `_shell_prune_budget_profile` defaults budgets to zero when omitted (`python/envctl_engine/engine_runtime.py:2665-2689`), which can make strict readiness appear complete without explicit budget configuration.
3. **Parity truth drift risk**: `PARTIAL_COMMANDS` is empty; parity completeness hinges on the manifest and tests rather than runtime-reported partial commands.
4. **Planning/worktree parity risk**: Python planning/worktree logic is independent from Bash orchestration; mismatches in selection normalization and tree discovery can cause divergent behavior.
5. **Runtime truth coupling**: `runtime_map` falls back to requested ports when actual ports are missing; truth is only as accurate as listener detection and service probes.
6. **Synthetic state containment**: Synthetic services are still recognized in state (`RunState.synthetic`), and strict mode blocks them; any synthetic fixtures in tests or legacy state files can mask real command resolution behavior.

## Plan
### 1) Make strict governance explicit and enforceable
- Require explicit budget profiles in strict mode, not implicit zeros:
  - Update `python/envctl_engine/engine_runtime.py:_shell_prune_budget_profile` and `_enforce_runtime_shell_budget_profile` to treat missing budgets as strict failures (aligned with `_doctor_readiness_gates`).
  - Ensure `python/envctl_engine/release_gate.py:evaluate_shipability` and `scripts/release_shipability_gate.py` require explicit budgets when strict mode is requested.
- Tests:
  - Extend `tests/python/test_release_shipability_gate.py` and `tests/python/test_engine_runtime_command_parity.py` for strict budget completeness.
  - Validate CLI behavior in `tests/bats/python_cutover_gate_strict_e2e.bats`.

### 2) Populate the shell ownership ledger with evidence-backed entries
- Regenerate and classify entries in `docs/planning/refactoring/envctl-shell-ownership-ledger.json`:
  - Add per-function entries with `python_owner_module`, `python_owner_symbol`, `status`, `delete_wave`, and `evidence_tests`.
  - Ensure `command_mappings` covers all `python_complete` commands in `docs/planning/python_engine_parity_manifest.json`.
- Verify contract:
  - Use `scripts/verify_shell_prune_contract.py` and `scripts/report_unmigrated_shell.py` for counts and budget checks.
  - Update `tests/python/test_shell_prune_contract.py` and `tests/python/test_shell_ownership_ledger.py` if new validation rules are introduced.

### 3) Align planning and worktree parity with Bash behavior
- Normalize selection and feature naming parity:
  - Ensure `python/envctl_engine/planning.py:planning_feature_name` and `_normalize_selection_token` align with `lib/engine/lib/planning.sh:planning_feature_name` and `planning_normalize_selection_token`.
- Worktree discovery parity:
  - Validate `planning.py:discover_tree_projects` against `lib/engine/lib/worktrees.sh:list_tree_paths` and `worktree_identity_from_dir` for nested and `trees-*` layouts.
- Worktree setup parity:
  - Keep `engine_runtime._sync_plan_worktrees_from_plan_counts` aligned with `run_all_trees_handle_planning_envs` semantics (Done moves, keep-plan, desired count handling).
- Tests:
  - Extend `tests/python/test_planning_selection.py`, `tests/python/test_planning_worktree_setup.py`, `tests/python/test_discovery_topology.py`.
  - Run/extend `tests/bats/python_plan_nested_worktree_e2e.bats`, `tests/bats/python_plan_parallel_ports_e2e.bats`, `tests/bats/python_planning_worktree_setup_e2e.bats`.

### 4) Enforce synthetic-free strict runtime behavior
- Keep command resolution real-only in production:
  - Ensure `python/envctl_engine/command_resolution.py` remains the single source for real commands.
  - Restrict synthetic state usage to explicit test fixtures and block in strict mode (already in `_state_has_synthetic_services`).
- Update tests to avoid synthetic placeholders in strict lanes:
  - `tests/python/test_engine_runtime_real_startup.py`, `tests/python/test_runtime_health_truth.py`.
  - `tests/bats/python_no_synthetic_primary_flow_e2e.bats`.

### 5) Complete requirements parity and retry semantics
- Align adapters with Bash requirements behavior:
  - `python/envctl_engine/requirements/{postgres,redis,supabase,n8n}.py` should mirror core flows in `lib/engine/lib/requirements_core.sh` and `requirements_supabase.sh`.
  - Use `python/envctl_engine/requirements_orchestrator.py` failure classes to standardize retry and error classification.
- Tests:
  - `tests/python/test_requirements_orchestrator.py`, `tests/python/test_requirements_adapters_real_contracts.py`, `tests/python/test_supabase_requirements_reliability.py`.
  - `tests/bats/python_requirements_conflict_recovery.bats`, `tests/bats/python_requirements_adapter_parity_e2e.bats`.

### 6) Enforce service lifecycle truth and projection accuracy
- Use listener truth for runtime map outputs:
  - Ensure `python/envctl_engine/service_manager.py` and `python/envctl_engine/process_runner.py` propagate actual ports and listener PIDs.
  - Align `python/envctl_engine/runtime_map.py` projection with actual ports only when listeners are validated.
- Tests:
  - `tests/python/test_process_runner_listener_detection.py`, `tests/python/test_service_manager.py`, `tests/python/test_runtime_projection_urls.py`, `tests/python/test_frontend_env_projection_real_ports.py`.
  - `tests/bats/python_listener_projection_e2e.bats`.

### 7) Resume/restart/state parity and reconciliation
- Keep state compatibility without stale success:
  - Confirm `python/envctl_engine/state_repository.py:load_latest` and `state.py` correctly reject out-of-scope state.
  - Implement explicit stale PID/listener reconciliation in runtime resume/restart paths.
- Tests:
  - `tests/python/test_state_shell_compatibility.py`, `tests/python/test_state_roundtrip.py`, `tests/python/test_runtime_health_truth.py`, `tests/python/test_lifecycle_parity.py`.
  - `tests/bats/python_resume_projection_e2e.bats`, `tests/bats/python_state_resume_shell_compat_e2e.bats`.

### 8) Stop/stop-all/blast-all parity and safety
- Align cleanup behavior with Bash:
  - Ensure port locks are released (`python/envctl_engine/ports.py`) and state pointers removed (`state_repository.purge`).
  - Keep Docker cleanup parity where applicable with `lib/engine/lib/docker.sh`.
- Tests:
  - `tests/python/test_lifecycle_parity.py`, `tests/python/test_ports_lock_reclamation.py`.
  - `tests/bats/python_stop_blast_all_parity_e2e.bats`, `tests/bats/python_blast_all_contract_e2e.bats`.

### 9) Action command parity and defaults
- Verify default command resolution:
  - `python/envctl_engine/actions_test.py`, `actions_git.py`, `actions_analysis.py`, `actions_worktree.py` should behave without custom overrides when possible.
  - Ensure `command_router.py` flags and selectors match Bash behavior for action commands.
- Tests:
  - `tests/python/test_actions_parity.py`, `tests/python/test_engine_runtime_command_parity.py`.
  - `tests/bats/python_actions_parity_e2e.bats`, `tests/bats/python_actions_native_path_e2e.bats`.

### 10) Interactive UX parity and stability
- Harden planning menu and dashboard key handling:
  - Keep `python/envctl_engine/planning_menu.py` escape handling reliable for CSI/SS3/control sequences.
  - Validate render alignment and truncation in `python/envctl_engine/planning_menu.py` and `terminal_ui.py`.
- Tests:
  - `tests/python/test_interactive_input_reliability.py`, `tests/python/test_planning_menu_rendering.py`, `tests/python/test_dashboard_rendering_parity.py`.
  - `tests/bats/python_interactive_input_reliability_e2e.bats`.

### 11) Continue runtime decomposition safely
- Move remaining monolithic logic from `python/envctl_engine/engine_runtime.py` into existing orchestrators:
  - `startup_orchestrator.py`, `resume_orchestrator.py`, `doctor_orchestrator.py`, `dashboard_orchestrator.py`, `lifecycle_cleanup_orchestrator.py`.
  - Keep `engine_runtime.py` as coordination and routing.
- Tests:
  - Full Python suite plus targeted parity tests must remain green after each extraction.

### 12) Keep parity manifest and docs synchronized to strict truth
- Update `docs/planning/python_engine_parity_manifest.json` only when strict parity tests pass.
- Ensure `docs/important-flags.md` matches `command_router.list_supported_flag_tokens` (checked by `release_gate._unsupported_documented_flags`).
- Tests:
  - `tests/python/test_release_shipability_gate.py` and `tests/bats/python_parser_docs_parity_e2e.bats`.

## Tests (add these)
### Backend tests
- `tests/python/test_release_shipability_gate.py`: strict budget completeness and manifest/runtime sync failure cases.
- `tests/python/test_shell_prune_contract.py`, `tests/python/test_shell_ownership_ledger.py`: ledger entry validation and command mapping coverage.
- `tests/python/test_planning_selection.py`, `tests/python/test_planning_worktree_setup.py`, `tests/python/test_discovery_topology.py`: selection and discovery parity.
- `tests/python/test_engine_runtime_real_startup.py`, `tests/python/test_runtime_health_truth.py`: synthetic-free strict runtime and listener truth.
- `tests/python/test_requirements_orchestrator.py`, `tests/python/test_requirements_adapters_real_contracts.py`: requirements parity.
- `tests/python/test_service_manager.py`, `tests/python/test_process_runner_listener_detection.py`: service truth.
- `tests/python/test_state_shell_compatibility.py`, `tests/python/test_state_roundtrip.py`, `tests/python/test_lifecycle_parity.py`: resume/restart/cleanup parity.
- `tests/python/test_actions_parity.py`, `tests/python/test_engine_runtime_command_parity.py`: action command parity.

### Frontend tests
- `tests/python/test_runtime_projection_urls.py`, `tests/python/test_frontend_env_projection_real_ports.py`: projection truth.
- `tests/python/test_dashboard_rendering_parity.py`, `tests/python/test_planning_menu_rendering.py`: UI rendering stability.

### Integration/E2E tests
- `tests/bats/python_cutover_gate_strict_e2e.bats`: strict gate behavior.
- `tests/bats/python_no_synthetic_primary_flow_e2e.bats`: synthetic-free strict lane.
- `tests/bats/python_plan_nested_worktree_e2e.bats`, `tests/bats/python_plan_parallel_ports_e2e.bats`, `tests/bats/python_planning_worktree_setup_e2e.bats`: planning/worktree parity.
- `tests/bats/python_requirements_conflict_recovery.bats`, `tests/bats/python_requirements_adapter_parity_e2e.bats`: requirements parity.
- `tests/bats/python_listener_projection_e2e.bats`, `tests/bats/python_resume_projection_e2e.bats`: runtime truth and resume parity.
- `tests/bats/python_stop_blast_all_parity_e2e.bats`, `tests/bats/python_blast_all_contract_e2e.bats`: cleanup parity.
- `tests/bats/python_actions_parity_e2e.bats`, `tests/bats/python_actions_native_path_e2e.bats`: action parity.
- `tests/bats/python_interactive_input_reliability_e2e.bats`: interactive stability.

## Observability / logging (if relevant)
- Keep emitting cutover events in `python/envctl_engine/engine_runtime.py`:
  - `cutover.gate.evaluate`, `cutover.gate.fail_reason`, `synthetic.execution.blocked`.
- Keep port lock lifecycle events in `python/envctl_engine/ports.py`:
  - `port.lock.acquire`, `port.lock.reclaim`, `port.lock.release`.
- Ensure runtime artifacts are written per run and root scope:
  - `run_state.json`, `runtime_map.json`, `ports_manifest.json`, `error_report.json`, `events.jsonl`, `shell_prune_report.json`, `shell_ownership_snapshot.json`.

## Rollout / verification
- Verify ledger and shipability gates:
  - `./.venv/bin/python scripts/report_unmigrated_shell.py --repo .`
  - `./.venv/bin/python scripts/verify_shell_prune_contract.py --repo . --max-unmigrated 0 --max-partial-keep 0 --max-intentional-keep 0 --phase cutover`
  - `./.venv/bin/python scripts/release_shipability_gate.py --repo . --shell-prune-max-unmigrated 0 --shell-prune-max-partial-keep 0 --shell-prune-max-intentional-keep 0 --shell-prune-phase cutover --require-shell-budget-complete`
- Run test suites:
  - `./.venv/bin/python -m unittest discover -s tests/python -p 'test_*.py'`
  - `bats tests/bats/python_*.bats tests/bats/parallel_trees_python_e2e.bats`
- Manual spot checks:
  - `bin/envctl --doctor`, `bin/envctl --plan`, `bin/envctl --resume`, `bin/envctl stop-all`.

## Definition of done
- Shell ownership ledger is populated with evidence-backed entries; shell prune contract passes strict cutover budgets.
- Parity manifest, doctor readiness, and release gate outputs agree under strict mode.
- Planning/worktree selection and worktree creation match Bash behavior in parity suites.
- Synthetic placeholders are absent from strict runtime flows; strict lanes pass without synthetic state.
- Requirements/service startup, runtime projection, resume/restart, and cleanup parity tests are green.
- Action commands run with native defaults and selector parity.

## Risk register (trade-offs or missing tests)
- Risk: strict budget enforcement increases visible failures for repos missing ledger coverage.
  - Mitigation: staged wave budgets and explicit evidence tests for each wave.
- Risk: planning/worktree parity drift due to duplicate implementations in Python and Bash.
  - Mitigation: parity tests for selection and worktree setup; shared normalization logic where possible.
- Risk: runtime truth relies on listener detection that can be flaky in constrained environments.
  - Mitigation: timeouts and fallback strategies in process probes, plus explicit tests for constrained environments.
- Risk: runtime decomposition can introduce subtle regressions.
  - Mitigation: extract in small slices with full test suite validation per slice.

## Open questions (only if unavoidable)
- None.
