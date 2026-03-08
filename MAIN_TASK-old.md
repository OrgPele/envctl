## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Ship a Python runtime that is behaviorally equivalent to the mature Bash runtime for all high-value command families: `start`, `--plan`, `--tree/--trees`, `--resume`, `restart`, `stop`, `stop-all`, `blast-all`, dashboard/interactive loop, and action commands.
  - Remove all production reliance on placeholder/synthetic execution paths and ensure runtime truth (health, URLs, summaries) is backed by observed process/container/listener state.
  - Drive shell ownership migration from inventory-only status to evidence-backed ownership/deletion, reducing ledger `unmigrated` entries from `320` to `0` for cutover scope.
  - Make cutover readiness machine-checked and truthful across `doctor`, parity manifest, release gate, and shell-prune contract.
  - Preserve existing CLI contract and user semantics while improving maintainability via runtime decomposition.
- Non-goals:
  - Renaming `envctl`, changing core command semantics, or rewriting downstream application business logic.
  - Deleting launcher compatibility layers (`bin/envctl`, `lib/envctl.sh`, `lib/engine/main.sh`) before parity gates are green.
  - Permanently supporting unsafe/unbounded shell hook execution.
- Assumptions:
  - Python 3.12 remains required for Python mode (`lib/engine/main.sh:python_engine_version_is_312`, `exec_python_engine_if_enabled`).
  - Docker remains the infra backend for Postgres/Redis/Supabase/N8N orchestration.
  - Config precedence remains stable: env -> `.envctl` / `.envctl.sh` / `.supportopia-config` -> defaults (`python/envctl_engine/config.py:load_config`).
  - Cutover remains staged with shell fallback retained only as emergency escape hatch until strict parity gates pass.

## Goal (user experience)
Running `envctl --plan` in a real repository should be boring and deterministic: user gets an interactive plan picker by default on TTY, selects multiple plans and iteration counts, services actually start, displayed URLs always match live listeners, `resume` and `restart` reconcile missing services correctly, and `stop` / `stop-all` / `blast-all` perform complete cleanup with predictable scope and no false success. The dashboard/interactive loop should feel at least as usable as Bash: responsive key handling, clear colorful statuses, accurate logs/health/errors, and explicit failure diagnostics.

## Business logic and data model mapping
- Launcher and runtime handoff:
  - `bin/envctl` -> `lib/envctl.sh:envctl_main` -> `lib/envctl.sh:envctl_forward_to_engine` -> `lib/engine/main.sh`.
  - Runtime selection knobs: `ENVCTL_ENGINE_PYTHON_V1`, `ENVCTL_ENGINE_SHELL_FALLBACK`.
- Python command lifecycle:
  - CLI/prereq entry: `python/envctl_engine/cli.py:run`, `check_prereqs`.
  - Routing/alias parsing: `python/envctl_engine/command_router.py:parse_route`, `list_supported_flag_tokens`.
  - Runtime dispatch and orchestration: `python/envctl_engine/engine_runtime.py:PythonEngineRuntime.dispatch`.
- Canonical model/state/projection:
  - Models: `python/envctl_engine/models.py` (`PortPlan`, `ServiceRecord`, `RequirementsResult`, `RunState`).
  - State IO + legacy compatibility: `python/envctl_engine/state.py`.
  - Runtime map/projection: `python/envctl_engine/runtime_map.py`.
- Runtime execution domains:
  - Port lifecycle/locking: `python/envctl_engine/ports.py:PortPlanner`.
  - Requirements retry/failure classification: `python/envctl_engine/requirements_orchestrator.py`.
  - Requirements adapters: `python/envctl_engine/requirements/{postgres,redis,supabase,n8n}.py`.
  - Service process lifecycle: `python/envctl_engine/service_manager.py`, `python/envctl_engine/process_runner.py`.
  - Actions: `python/envctl_engine/actions_{test,git,analysis,worktree}.py`.
- Shipability/cutover truth:
  - Release gate: `python/envctl_engine/release_gate.py:evaluate_shipability`.
  - Shell ownership contract: `python/envctl_engine/shell_prune.py:evaluate_shell_prune_contract`.
  - Doctor readiness output: `python/envctl_engine/engine_runtime.py:_doctor_readiness_gates`.
- Bash parity baseline (behavioral source of truth to migrate):
  - CLI flags/flow: `lib/engine/lib/run_all_trees_cli.sh`.
  - Planning/start orchestration: `lib/engine/lib/run_all_trees_helpers.sh`, `lib/engine/lib/planning.sh`.
  - Service lifecycle: `lib/engine/lib/services_lifecycle.sh`.
  - Requirements lifecycle: `lib/engine/lib/requirements_core.sh`, `lib/engine/lib/requirements_supabase.sh`.
  - State/resume/cleanup/recovery: `lib/engine/lib/state.sh`.
  - Actions/UI/ports/docker/worktrees internals: `lib/engine/lib/{actions,ui,ports,docker,worktrees,analysis,pr,env,git,runtime_map,config,loader}.sh`.

## Current behavior (verified in code)
- Strict cutover gate currently fails on ledger budget:
  - Command: `./.venv/bin/python scripts/release_shipability_gate.py --repo . --shell-prune-max-unmigrated 0 --shell-prune-phase cutover`
  - Result: `shipability.passed: false` due to `unmigrated entries exceed budget ... 320 > 0`.
- Non-strict gate passes with warning:
  - Command: `./.venv/bin/python scripts/release_shipability_gate.py --repo .`
  - Result: `shipability.passed: true` + warning `unmigrated shell entries remain: 320`.
- Doctor can display parity complete while shell budget is unchecked:
  - Command: `RUN_REPO_ROOT=/Users/kfiramar/projects/envctl PYTHONPATH=python ./.venv/bin/python -m envctl_engine.runtime.cli --doctor`
  - Current output includes `parity_status: complete`, `shell_unmigrated_actual: 320`, `shell_unmigrated_budget: none`, `shell_unmigrated_status: unchecked`.
- Shell ledger inventory and status:
  - `docs/planning/refactoring/envctl-shell-ownership-ledger.json` contains `320` entries; all status `unmigrated`.
  - This count equals current parsed shell function inventory from sourced shell modules (`modules_sourced=17`, `function_inventory_count=320`).
  - Important nuance: this is currently inventory/unclassified debt, not necessarily 320 broken user-visible features.
- Synthetic path remains in runtime code:
  - `python/envctl_engine/command_resolution.py` still contains `source="synthetic_default"` branches.
  - `python/envctl_engine/engine_runtime.py` still models synthetic states and warnings.
- Synthetic mode still used in multiple parity-related tests:
  - `tests/bats/python_requirements_conflict_recovery.bats`
  - `tests/bats/python_cross_repo_isolation_e2e.bats`
  - `tests/bats/python_listener_projection_e2e.bats`
  - `tests/bats/python_main_requirements_mode_flags_e2e.bats`
  - `tests/bats/parallel_trees_python_e2e.bats`
  - `tests/bats/python_plan_selector_strictness_e2e.bats`
  - `tests/bats/python_parallel_trees_execution_mode_e2e.bats`
  - `tests/bats/python_planning_worktree_setup_e2e.bats`
  - `tests/bats/python_setup_worktree_selection_e2e.bats`
  - plus selected Python tests.
- Action-command default coverage is incomplete:
  - `python/envctl_engine/actions_git.py` default PR/commit commands return `None`.
  - `python/envctl_engine/actions_analysis.py` default analyze command returns `None`.
  - Runtime requires explicit command env overrides for those families.
- Runtime implementation concentration remains high risk:
  - `python/envctl_engine/engine_runtime.py` currently ~5.8k LOC and mixes dispatch, planning, startup, interactive UI, health, cleanup, doctor, and gate reporting.
- Baseline tests currently green (important for refactor safety):
  - `./.venv/bin/python -m unittest discover -s tests/python -p 'test_*.py'` -> `281` tests pass.
  - `bats tests/bats/python_*.bats tests/bats/parallel_trees_python_e2e.bats` -> `37` tests pass.

## Root cause(s) / gaps
1. Migration governance gap: strict cutover criteria are not the default runtime truth path; non-strict mode can look green while ownership debt remains high.
2. Ownership classification gap: ledger entries are auto-generated as `unmigrated` and not yet systematically reclassified with evidence tests.
3. Runtime realism gap: synthetic fallback paths still exist and are still exercised in parity tests.
4. Command-surface completion gap: action defaults for PR/commit/analyze are not Python-native by default.
5. Lifecycle-depth gap: cleanup/resume contracts need explicit parity verification against Bash behavior under failure/partial-state conditions.
6. Maintainability gap: monolithic runtime implementation increases regression risk and slows safe migration.
7. Truth synchronization gap: manifest, doctor, and release gate can drift without strict policy enforcement.

## Plan
### 1) Establish strict cutover governance as default release truth
- Change policy so cutover lanes always evaluate with explicit shell budget.
- Make `doctor` reflect strict profile status clearly and fail readiness when budget is undefined in strict lane.
- Enforce that release readiness is computed from strict gate outputs, not metadata-only parity signals.
- Files:
  - `python/envctl_engine/release_gate.py`
  - `python/envctl_engine/engine_runtime.py`
  - `scripts/release_shipability_gate.py`
- Exit criteria:
  - Strict gate is authoritative; no release readiness pass when unmigrated budget violated.

### 2) Convert shell ledger from static inventory into execution backlog
- Reclassify entries by wave with ownership + evidence tests + migration notes.
- Use phase budgets and make each wave gateable by `shell_prune_max_unmigrated`.
- Proposed wave budgets:
  - Wave 0 (classification only): `320 -> 320` with complete metadata.
  - Wave 1 (actions/ui/analysis/pr): `320 -> 220`.
  - Wave 2 (planning/worktrees/helpers): `220 -> 130`.
  - Wave 3 (state/ports/runtime_map/env/config/git/loader): `130 -> 40`.
  - Wave 4 (docker + final stragglers): `40 -> 0`.
- Files:
  - `docs/planning/refactoring/envctl-shell-ownership-ledger.json`
  - `python/envctl_engine/shell_prune.py`
- Exit criteria:
  - Each wave has evidence tests for every migrated function family and passes budget gate.

### 3) Detailed wave implementation map (function-family ownership)
- Wave 1 modules:
  - `lib/engine/lib/actions.sh` (dashboard/doctor/action targeting)
  - `lib/engine/lib/ui.sh` (interactive read loop/menu rendering)
  - `lib/engine/lib/analysis.sh` (analysis selection/scoping)
  - `lib/engine/lib/pr.sh` (PR payload/branch/status helpers)
- Python ownership targets:
  - `python/envctl_engine/engine_runtime.py` (dashboard/doctor interactive integration)
  - `python/envctl_engine/actions_{git,analysis,test,worktree}.py`
  - new optional split modules: `python/envctl_engine/dashboard.py`, `python/envctl_engine/interactive_input.py`
- Wave 2 modules:
  - `lib/engine/lib/planning.sh`
  - `lib/engine/lib/worktrees.sh`
  - `lib/engine/lib/run_all_trees_helpers.sh`
- Python ownership targets:
  - `python/envctl_engine/planning.py`
  - `python/envctl_engine/engine_runtime.py` planning/start orchestration paths
  - new optional `python/envctl_engine/worktree_orchestrator.py`
- Wave 3 modules:
  - `lib/engine/lib/state.sh`
  - `lib/engine/lib/ports.sh`
  - `lib/engine/lib/runtime_map.sh`
  - `lib/engine/lib/env.sh`
  - `lib/engine/lib/config.sh`
  - `lib/engine/lib/git.sh`
  - `lib/engine/lib/loader.sh`
- Python ownership targets:
  - `python/envctl_engine/state.py`
  - `python/envctl_engine/ports.py`
  - `python/envctl_engine/runtime_map.py`
  - `python/envctl_engine/config.py`
  - `python/envctl_engine/release_gate.py`/`shell_prune.py` helpers
- Wave 4 modules:
  - `lib/engine/lib/docker.sh`
- Python ownership targets:
  - `python/envctl_engine/requirements/*.py`
  - lifecycle cleanup orchestration in runtime/split modules.
- Exit criteria:
  - For each module family: parity tests green + ledger status updates + no regression in full suite.

### 4) Remove synthetic defaults from primary runtime and strict tests
- Keep synthetic mode only under explicit test-only guard.
- Make strict profile reject synthetic usage at runtime and in gate checks.
- Replace synthetic usage in parity-critical BATS with real commands/adapters.
- Files:
  - `python/envctl_engine/command_resolution.py`
  - `python/envctl_engine/engine_runtime.py`
  - affected tests under `tests/bats` and `tests/python`
- Exit criteria:
  - No strict lane test uses synthetic defaults.
  - Production profile cannot complete startup with synthetic sources.

### 5) Complete requirements parity by adapter contract
- Postgres adapter parity:
  - create/attach/restart/recreate semantics, port-mapping validation, readiness probes, retry class mapping.
- Redis adapter parity:
  - same lifecycle guarantees and transient failure handling.
- Supabase adapter parity:
  - DB + dependent services sequencing, health checks, and retry semantics equivalent to shell baseline.
- N8N parity:
  - bootstrap/restart/recreate policies with strict/soft handling.
- Files:
  - `python/envctl_engine/requirements/{postgres,redis,supabase,n8n}.py`
  - `python/envctl_engine/requirements_orchestrator.py`
- Exit criteria:
  - Requirements status is based on proven readiness, not command return code alone.

### 6) Complete service lifecycle parity and listener-truth projection
- Only mark services running when listener ownership is validated.
- Persist requested/assigned/final ports and rebound metadata per service.
- Ensure projected runtime URLs are always derived from actual final listeners.
- Files:
  - `python/envctl_engine/service_manager.py`
  - `python/envctl_engine/process_runner.py`
  - `python/envctl_engine/engine_runtime.py`
  - `python/envctl_engine/runtime_map.py`
- Exit criteria:
  - No stale/unreachable service shown as healthy in dashboard/health/errors/runtime map.

### 7) Finish resume/restart/state parity
- Reconcile stale state on resume:
  - detect dead PIDs/listeners,
  - restart missing targets by policy,
  - keep healthy services attached.
- Maintain compatibility for legacy state pointers during migration window.
- Remove any legacy command hints that contradict Python-first runtime.
- Files:
  - `python/envctl_engine/state.py`
  - `python/envctl_engine/engine_runtime.py`
- Exit criteria:
  - `resume` and `restart` are deterministic and idempotent under mixed healthy/stale states.

### 8) Complete stop/stop-all/blast-all parity and safety
- Define explicit cleanup contracts and output contract:
  - tracked process shutdown,
  - port/listener cleanup,
  - docker cleanup,
  - volume policies,
  - pointer/lock/state cleanup.
- Add explicit scope controls to avoid accidental host-wide collateral kills by default.
- Files:
  - `python/envctl_engine/engine_runtime.py`
  - optional split `python/envctl_engine/lifecycle_cleanup.py`
- Exit criteria:
  - repeated operations are idempotent and parity-tested; aggressive cleanup requires explicit opt-in.

### 9) Complete interactive UX parity and key-input reliability
- Ensure interactive mode defaults on TTY unless `--batch`/`--non-interactive`.
- Harden key parsing against CSI/SS3/control-sequence contamination.
- Stabilize fixed-width rendering for long plan names; keep line-by-line readability.
- Preserve colorful status and operator-friendly summaries.
- Files:
  - `python/envctl_engine/engine_runtime.py` (interactive + planning UI paths)
  - optional split modules for dashboard/menu input rendering
- Exit criteria:
  - no intermittent “keypress ignored until enter” behavior.
  - no crooked multi-line rendering in plan selection.

### 10) Complete planning/worktree orchestration parity
- Keep interactive plan selection with counts and reuse awareness.
- Ensure deterministic worktree create/reuse/delete behavior and post-plan startup flow.
- Keep nested `trees/<feature>/<iter>` and flat compatibility behavior deterministic.
- Files:
  - `python/envctl_engine/planning.py`
  - `python/envctl_engine/engine_runtime.py`
- Exit criteria:
  - `--plan` behaves end-to-end like mature Bash UX flow, including interactive continuation into runtime dashboard.

### 11) Complete action-command parity with Python-native defaults
- Implement default PR/commit/analyze paths (or robust auto-detect strategy) without mandatory shell wrapper scripts.
- Preserve target selectors and exit-code contract for `test/pr/commit/analyze/migrate/delete-worktree`.
- Files:
  - `python/envctl_engine/actions_git.py`
  - `python/envctl_engine/actions_analysis.py`
  - `python/envctl_engine/actions_test.py`
  - `python/envctl_engine/actions_worktree.py`
  - `python/envctl_engine/engine_runtime.py`
- Exit criteria:
  - action families execute natively by default; shell wrappers are optional explicit fallback only.

### 12) Decompose runtime monolith with behavior-safe extraction
- Extract bounded modules while preserving public runtime behavior:
  - startup orchestration,
  - resume/reconcile,
  - lifecycle cleanup,
  - dashboard/interactive rendering,
  - doctor/readiness reporting.
- Keep extraction slices test-first and small.
- Files:
  - `python/envctl_engine/engine_runtime.py` + new modules
- Exit criteria:
  - full suite green after each extraction wave; runtime codebase easier to maintain.

### 13) Keep manifest, doctor, and docs synchronized to strict truth
- Make parity manifest updates contingent on strict evidence.
- Ensure docs do not overstate readiness relative to strict gate outcomes.
- Add drift checks where feasible.
- Files:
  - `docs/planning/python_engine_parity_manifest.json`
  - `docs/{architecture,configuration,troubleshooting,important-flags}.md`
  - `python/envctl_engine/release_gate.py`
- Exit criteria:
  - no parity truth drift across manifest/doctor/gate/docs.

### 14) Controlled rollout and retirement
- Gate A: strict shipability is green with budgeted ledger thresholds per phase.
- Gate B: synthetic-free strict parity suites are green.
- Gate C: ledger reaches zero unmigrated for cutover scope.
- Gate D: two consecutive release cycles without parity regressions.
- Post-Gate D: shell fallback demoted to emergency-only for one window, then orchestrator retirement.

## Tests (add these)
### Backend tests
- Extend `tests/python/test_release_shipability_gate.py`:
  - strict budget enforcement and fail-fast behavior.
  - parity manifest/doctor strict consistency checks.
- Extend `tests/python/test_shell_prune_contract.py`:
  - wave budget tests and evidence-test completeness checks.
- Extend `tests/python/test_engine_runtime_real_startup.py`:
  - strict profile rejects synthetic command sources.
  - listener-truth checks for startup success.
- Extend `tests/python/test_requirements_orchestrator.py`:
  - full failure-class mapping and retry ceilings for all requirement types.
- Extend `tests/python/test_lifecycle_parity.py`:
  - contract tests for stop/stop-all/blast-all phases and idempotency.
- Extend `tests/python/test_runtime_health_truth.py`:
  - stale/unreachable downgrade across resume/restart.
- Extend `tests/python/test_actions_parity.py`:
  - native default behavior for PR/commit/analyze (without env overrides).
- Add `tests/python/test_cutover_gate_truth.py`:
  - strict readiness fails when synthetic state or budget violation exists.
- Add `tests/python/test_interactive_input_reliability.py`:
  - command key responsiveness under CSI/SS3/control-sequence edge cases.

### Frontend tests
- Extend `tests/python/test_runtime_projection_urls.py`:
  - projection always tracks actual listener ports after retry/rebound/resume.
- Extend `tests/python/test_frontend_env_projection_real_ports.py`:
  - backend target env injection uses backend final actual listener.
- Add `tests/python/test_dashboard_rendering_parity.py`:
  - line stability and readability for long item names; color/no-color rendering checks.

### Integration/E2E tests
- Harden existing suites to strict synthetic-free lanes:
  - `tests/bats/python_plan_parallel_ports_e2e.bats`
  - `tests/bats/python_plan_nested_worktree_e2e.bats`
  - `tests/bats/python_listener_projection_e2e.bats`
  - `tests/bats/python_resume_projection_e2e.bats`
  - `tests/bats/python_requirements_conflict_recovery.bats`
  - `tests/bats/python_stop_blast_all_parity_e2e.bats`
  - `tests/bats/parallel_trees_python_e2e.bats`
- Add `tests/bats/python_cutover_gate_strict_e2e.bats`:
  - strict gate failure semantics for budget/synthetic violations.
- Add `tests/bats/python_no_synthetic_primary_flow_e2e.bats`:
  - strict profile blocks synthetic runtime flows.
- Add `tests/bats/python_actions_native_path_e2e.bats`:
  - action families run natively by default.
- Add `tests/bats/python_interactive_input_reliability_e2e.bats`:
  - keypress responsiveness and interactive loop reliability.
- Add `tests/bats/python_blast_all_contract_e2e.bats`:
  - full blast contract behavior and safety guard checks.

## Observability / logging (if relevant)
- Required event taxonomy:
  - `engine.mode.selected`, `command.route.selected`, `planning.projects.discovered`
  - `port.lock.acquire`, `port.lock.reclaim`, `port.lock.release`, `port.reservation.failed`
  - `requirements.start`, `requirements.retry`, `requirements.failure_class`, `requirements.healthy`
  - `service.start`, `service.retry`, `service.bind.requested`, `service.bind.actual`, `service.failure`
  - `state.save`, `state.resume`, `state.reconcile`, `runtime_map.write`
  - `cleanup.stop`, `cleanup.stop_all`, `cleanup.blast`
  - `cutover.gate.evaluate`, `cutover.gate.fail_reason`, `synthetic.execution.blocked`
- Required run artifacts per run scope:
  - `run_state.json`, `runtime_map.json`, `ports_manifest.json`, `error_report.json`, `events.jsonl`, `shell_prune_report.json`.
- Doctor diagnostics minimum fields:
  - strict budget status, unmigrated count, synthetic-state detection, parity source hash/timestamp, lock inventory health.

## Rollout / verification
- Core verification commands:
  - `./.venv/bin/python scripts/report_unmigrated_shell.py --repo .`
  - `./.venv/bin/python scripts/verify_shell_prune_contract.py --repo .`
  - `./.venv/bin/python scripts/release_shipability_gate.py --repo . --shell-prune-max-unmigrated 0 --shell-prune-phase cutover`
  - `./.venv/bin/python -m unittest discover -s tests/python -p 'test_*.py'`
  - `bats tests/bats/python_*.bats tests/bats/parallel_trees_python_e2e.bats`
- Milestone gates:
  - M1: Governance + classification complete; strict gate failure reason narrowed and intentional.
  - M2: Waves 1-2 done; interactive/action/planning parity stable.
  - M3: Waves 3-4 done; lifecycle/state/requirements/docker parity stable.
  - M4: Synthetic-free strict lanes green; ledger budget reaches zero.
  - M5: Two stable release cycles; fallback retirement decision.
- Regression policy:
  - Any failure in strict parity lanes blocks advancing the current wave.

## Definition of done
- Strict cutover gate passes with `shell_prune_max_unmigrated=0` for cutover phase.
- Shell ownership ledger has no `unmigrated` entries for cutover scope, and each migrated function family has evidence tests.
- Primary runtime workflows are Python-owned and synthetic-free in strict profile.
- Interactive planning/dashboard behavior matches Bash-level usability and reliability.
- Lifecycle commands (`stop`, `stop-all`, `blast-all`, `resume`, `restart`) are parity-tested, deterministic, and idempotent.
- Action commands are Python-native by default with correct target selection and exit contracts.
- Runtime map/health/errors outputs are grounded in live process/listener truth.
- `doctor`, parity manifest, release gate, and docs are synchronized and truthful.

## Risk register (trade-offs or missing tests)
- Risk: stricter truth gates increase visible failures in misconfigured repos.
  - Mitigation: actionable failure classes and migration guidance.
- Risk: broad ledger burn-down can stall delivery.
  - Mitigation: strict wave budgets, module ownership, and evidence-driven gating.
- Risk: blast-all parity/safety trade-offs can conflict with historical expectations.
  - Mitigation: explicit cleanup scope modes with guarded aggressive opt-in.
- Risk: runtime decomposition can introduce subtle behavioral regressions.
  - Mitigation: test-first extraction and full-suite validation per slice.

## Open questions (only if unavoidable)
- No blocking open questions for execution. The `.envctl.sh` long-term policy can remain “supported during cutover window” and be decided in the final deprecation phase once strict parity gates are green.

## Appendix A: Remaining shell migration inventory (machine-generated baseline)
This appendix is generated from `docs/planning/refactoring/envctl-shell-ownership-ledger.json` and represents current unclassified migration backlog.


Current unmigrated entry count: **320**

Module breakdown (with exact function names):

### lib/engine/lib/actions.sh (21)
- `actions_is_truthy`
- `actions_trim`
- `dashboard_connection_targets`
- `dashboard_extract_host_ports`
- `dashboard_http_endpoint_candidates`
- `dashboard_http_probe_status`
- `dashboard_is_data_container`
- `dashboard_show_docker_containers`
- `doctor_check_port`
- `doctor_check_state_orphans`
- `doctor_collect_state_pointers`
- `list_command_targets`
- `list_commands`
- `list_worktree_paths_for_delete`
- `parse_command_targets`
- `run_command`
- `run_dashboard`
- `run_doctor`
- `run_worktree_delete_command`
- `validate_command_targets`
- `worktree_delete_label_for_path`

### lib/engine/lib/analysis.sh (34)
- `analysis_collect_tree_paths`
- `analysis_ensure_base_dir`
- `analysis_extract_non_md_files`
- `analysis_extract_paths_from_status_list`
- `analysis_filter_files`
- `analysis_init_config`
- `analysis_parse_args`
- `analysis_prepare_output_dir`
- `analysis_print_completion`
- `analysis_print_next_steps`
- `analysis_print_output_dir`
- `analysis_print_tree_selection`
- `analysis_print_verbose_details`
- `analysis_resolve_scope_filter`
- `analysis_resolve_trees_to_analyze`
- `analysis_run_trees`
- `analysis_selection_has_multiple_iterations`
- `analysis_set_base_dir`
- `analysis_should_include_file`
- `analysis_show_help`
- `analysis_write_name_status_list`
- `analysis_write_state_file`
- `analysis_write_summary_short`
- `analyze_tree_changes`
- `copy_root_docs_markdown`
- `create_evaluation_request`
- `create_scoring_template`
- `estimate_tokens`
- `generate_enhanced_summary`
- `generate_llm_prompt`
- `get_grep_exclusions`
- `list_project_iterations`
- `resolve_analysis_selection`
- `run_tree_change_analysis`

### lib/engine/lib/config.sh (3)
- `init_run_all_trees_config`
- `parse_run_all_trees_args`
- `print_run_all_trees_usage`

### lib/engine/lib/docker.sh (43)
- `check_docker`
- `cleanup_docker_log_followers`
- `collect_tree_entries`
- `compose_has_service`
- `docker_check_health`
- `docker_cmd`
- `docker_compose`
- `docker_compose_up`
- `docker_container_exists`
- `docker_container_running`
- `docker_containers_on_port`
- `docker_containers_on_port_details`
- `docker_effective_services`
- `docker_init_known_services`
- `docker_list_services`
- `docker_print_timeout_hint_once`
- `docker_probe`
- `docker_ps_all_names_cached`
- `docker_ps_all_names_contains`
- `docker_ps_cache_ready`
- `docker_ps_cache_refresh`
- `docker_ps_ids_cached`
- `docker_ps_names_cached`
- `docker_ps_names_contains`
- `docker_published_port`
- `docker_rebuild_services`
- `docker_restart_service`
- `docker_run_with_timeout`
- `docker_show_errors`
- `docker_show_status`
- `docker_socket_path`
- `docker_socket_state`
- `docker_stop_all`
- `docker_stop_services`
- `docker_tail_logs`
- `docker_timeout_bin`
- `ensure_docker_credential_helper`
- `generate_docker_compose_trees`
- `local_port_listeners`
- `maybe_stop_docker`
- `resolve_docker_ports`
- `resolve_docker_trees`
- `scan_tree_root`

### lib/engine/lib/env.sh (10)
- `_read_env_value_raw`
- `env_cache_build`
- `env_cache_dir`
- `env_cache_enabled`
- `env_cache_file_for`
- `env_cache_key`
- `load_env_file_safe`
- `read_env_value`
- `read_env_value_cached`
- `upsert_env_value`

### lib/engine/lib/git.sh (4)
- `extract_repo_slug`
- `git_state_cache_ttl`
- `git_state_for_dir`
- `hash_stdin`

### lib/engine/lib/loader.sh (1)
- `safe_source`

### lib/engine/lib/planning.sh (13)
- `list_done_planning_files`
- `list_planning_files`
- `planning_dir_display`
- `planning_dir_path`
- `planning_dir_raw`
- `planning_existing_count`
- `planning_feature_name`
- `planning_file_path`
- `planning_move_to_done`
- `planning_normalize_selection_token`
- `resolve_planning_files`
- `select_planning_files`
- `select_planning_files_interactive`

### lib/engine/lib/ports.sh (22)
- `find_free_port`
- `is_port_free`
- `port_is_open_fast`
- `port_is_reserved`
- `port_release`
- `port_release_all`
- `port_reservation_dir`
- `port_reservation_lock_dir`
- `port_reservation_reclaim_stale`
- `port_reservation_write_owner`
- `port_reserve`
- `port_snapshot_collect`
- `port_snapshot_enabled`
- `port_snapshot_refresh`
- `port_state_clear`
- `port_state_clear_saved`
- `port_state_file_path`
- `port_state_load_once`
- `port_state_record`
- `port_state_write`
- `reserve_port`
- `wait_for_port`

### lib/engine/lib/pr.sh (23)
- `apply_main_task_to_body`
- `build_commit_list`
- `build_pr_body_file`
- `commit_paths`
- `commit_unstaged_changes`
- `create_prs_for_paths`
- `create_prs_for_planning_paths`
- `default_pr_base_branch`
- `find_template_file`
- `pr_branch_exists`
- `pr_info_for_project`
- `pr_label_for_project`
- `pr_status_for_branch`
- `pr_url_for_branch`
- `pr_url_for_branch_if_exists`
- `pr_url_for_project`
- `prompt_commit_message`
- `prompt_pr_base_branch`
- `read_main_task_content`
- `read_main_task_message`
- `read_main_task_title`
- `read_tree_changelog_message`
- `replace_placeholder`

### lib/engine/lib/run_all_trees_helpers.sh (44)
- `check_required_tools`
- `cleanup_empty_feature_root`
- `dedupe_array_in_place`
- `envctl_define_flat_services`
- `resolve_main_backend_env_file`
- `resolve_main_frontend_env_file`
- `run_all_trees_apply_cli_project_filters`
- `run_all_trees_collect_finished_parallel_worker`
- `run_all_trees_dashboard_path`
- `run_all_trees_ensure_command_context`
- `run_all_trees_export_setup_envs`
- `run_all_trees_handle_docker_mode`
- `run_all_trees_handle_planning_envs`
- `run_all_trees_handle_resume`
- `run_all_trees_handle_setup_worktrees`
- `run_all_trees_init_tty`
- `run_all_trees_init_tty_debug_log`
- `run_all_trees_is_main_project_name`
- `run_all_trees_merge_worker_fragment`
- `run_all_trees_parallel_worker`
- `run_all_trees_parallel_worker_write_fragment`
- `run_all_trees_prepare_requirements`
- `run_all_trees_prepare_tree_paths`
- `run_all_trees_print_failed_services`
- `run_all_trees_print_logs_path_once`
- `run_all_trees_print_logs_summary`
- `run_all_trees_print_noninteractive_summary`
- `run_all_trees_print_running_services`
- `run_all_trees_resolve_main_environment`
- `run_all_trees_root_dashboard_path`
- `run_all_trees_run_command`
- `run_all_trees_run_docker_interactive`
- `run_all_trees_run_interactive`
- `run_all_trees_start_main_project`
- `run_all_trees_start_projects`
- `run_all_trees_start_requirements`
- `run_all_trees_start_tree_projects`
- `run_all_trees_start_tree_projects_parallel`
- `run_all_trees_write_dashboard`
- `slugify`
- `slugify_underscore`
- `start_tree_dir`
- `start_tree_job_with_offset`
- `tree_target_matches`

### lib/engine/lib/runtime_map.sh (3)
- `load_runtime_map`
- `runtime_map_path`
- `write_runtime_map`

### lib/engine/lib/state.sh (56)
- `_kill_pid_tree`
- `analysis_info_for_project`
- `backend_port_for_project`
- `cleanup`
- `cleanup_add_port`
- `cleanup_add_spaced_ports`
- `cleanup_blast_all`
- `cleanup_collect_port_candidates`
- `cleanup_kill_port_ranges`
- `cleanup_port_slot_count`
- `collect_all_state_pointers`
- `collect_dashboard_state_files`
- `create_recovery_script`
- `file_mtime_epoch`
- `find_last_state_file`
- `find_service_by_name`
- `format_epoch_short`
- `format_last_test_line`
- `format_summary_timestamp`
- `generate_error_report`
- `get_pids_for_port`
- `has_passing_tests`
- `kill_job_pids`
- `last_state_is_main`
- `last_state_is_trees`
- `latest_test_summary_file`
- `list_untested_projects`
- `load_attach_state`
- `load_state_for_command`
- `load_state_for_dashboard`
- `project_tests_status`
- `restart_service`
- `resume_apply_project_filter`
- `resume_apply_status_defaults`
- `resume_from_state`
- `resume_hint_command`
- `resume_project_name_is_main`
- `resume_selected_projects_from_targets`
- `resume_selected_targets_include_main`
- `save_state`
- `service_health_suffix`
- `state_absolute_dir`
- `state_absolute_path`
- `state_file_from_pointer`
- `state_file_matches`
- `state_file_matches_requested_mode`
- `state_guess_project_root_from_name`
- `state_guess_service_dir_from_name`
- `state_load_dashboard_selection`
- `state_pointer_dir`
- `state_projects_from_services`
- `state_recover_service_info_if_missing`
- `status_cache_ttl`
- `test_info_for_project`
- `tests_status_for_summary_file`
- `write_last_state_pointers`

### lib/engine/lib/ui.sh (22)
- `append_menu_option`
- `append_project_options`
- `append_service_options`
- `drain_pending_input`
- `interactive_mode`
- `interactive_mode_docker`
- `menu_cleanup`
- `menu_setup`
- `migration_db_hint`
- `prompt_yes_no`
- `read_char`
- `read_command`
- `read_key`
- `request_sigint_quit`
- `tty_flush_input`
- `tty_prepare_prompt`
- `tty_raw_off`
- `tty_raw_on`
- `tty_restore_base`
- `ui_can_interactive`
- `ui_docker_handle_command`
- `ui_interactive_handle_command`

### lib/engine/lib/worktrees.sh (21)
- `_ports_file_lock_reclaim_stale`
- `count_numeric_dir_names`
- `discover_tree_roots`
- `list_numeric_dir_names`
- `list_numeric_dirs`
- `list_tree_paths`
- `ports_file_lock_acquire`
- `ports_file_lock_release`
- `preferred_tree_root_for_feature`
- `read_ports_from_worktree_config`
- `remove_worktree_port_config`
- `resolve_tree_root_for_feature`
- `tree_config_signature`
- `update_worktree_port_config`
- `worktree_cache_enabled`
- `worktree_cache_record_ports`
- `worktree_cache_record_tree_paths`
- `worktree_identity_from_dir`
- `worktree_path_mtime`
- `worktree_port_cache_enabled`
- `worktree_roots_signature`

## Appendix B: Command-family parity closure checklist

- `start`
  - Remaining: Python runtime startup path; strict no-synthetic; listener-truth required
  - Ownership target: engine_runtime.py::_start + service/requirements adapters
- `plan`
  - Remaining: Interactive selector + worktree orchestration + startup continuation parity
  - Ownership target: planning.py + engine_runtime.py
- `resume`
  - Remaining: State pointer load + stale detection + targeted restore
  - Ownership target: state.py + engine_runtime.py::_resume
- `restart`
  - Remaining: Stop+reconcile+restart semantics parity with idempotency
  - Ownership target: engine_runtime.py + lifecycle modules
- `stop`
  - Remaining: Current run services cleanup + lock release
  - Ownership target: engine_runtime.py::_stop
- `stop-all`
  - Remaining: All tracked run cleanup + state/pointer consistency
  - Ownership target: engine_runtime.py::_stop
- `blast-all`
  - Remaining: Contracted aggressive cleanup with scope guards
  - Ownership target: engine_runtime.py::_stop / cleanup extractor
- `dashboard`
  - Remaining: Interactive colorful truth-based status and commands
  - Ownership target: engine_runtime.py::_dashboard / dashboard module
- `doctor`
  - Remaining: Strict gate-backed readiness output
  - Ownership target: engine_runtime.py::_doctor + release_gate.py
- `logs`
  - Remaining: follow/tail/duration/no-color behavior parity
  - Ownership target: engine_runtime.py::_state_action
- `health`
  - Remaining: Live listener/process truth, no stale false-green
  - Ownership target: engine_runtime.py::_state_action
- `errors`
  - Remaining: Actionable degraded state and failure-class summaries
  - Ownership target: engine_runtime.py::_state_action
- `test`
  - Remaining: Native default command resolution + selectors
  - Ownership target: actions_test.py + engine_runtime.py
- `pr`
  - Remaining: Native default path and selector parity
  - Ownership target: actions_git.py + engine_runtime.py
- `commit`
  - Remaining: Native default path and selector parity
  - Ownership target: actions_git.py + engine_runtime.py
- `analyze`
  - Remaining: Native default path and selector parity
  - Ownership target: actions_analysis.py + engine_runtime.py
- `migrate`
  - Remaining: Stable alembic/target execution contract
  - Ownership target: actions_analysis.py + engine_runtime.py
- `delete-worktree`
  - Remaining: Target-safe deletion with all/yes semantics
  - Ownership target: actions_worktree.py + engine_runtime.py

## Appendix C: Synthetic-mode removal matrix
- `tests/bats/python_requirements_conflict_recovery.bats` -> replace synthetic defaults with strict real-runtime fixture path.
- `tests/bats/python_cross_repo_isolation_e2e.bats` -> replace synthetic defaults with strict real-runtime fixture path.
- `tests/bats/python_listener_projection_e2e.bats` -> replace synthetic defaults with strict real-runtime fixture path.
- `tests/bats/python_main_requirements_mode_flags_e2e.bats` -> replace synthetic defaults with strict real-runtime fixture path.
- `tests/bats/parallel_trees_python_e2e.bats` -> replace synthetic defaults with strict real-runtime fixture path.
- `tests/bats/python_plan_selector_strictness_e2e.bats` -> replace synthetic defaults with strict real-runtime fixture path.
- `tests/bats/python_parallel_trees_execution_mode_e2e.bats` -> replace synthetic defaults with strict real-runtime fixture path.
- `tests/bats/python_planning_worktree_setup_e2e.bats` -> replace synthetic defaults with strict real-runtime fixture path.
- `tests/bats/python_setup_worktree_selection_e2e.bats` -> replace synthetic defaults with strict real-runtime fixture path.

## Appendix D: Strict cutover command checklist
- `./.venv/bin/python scripts/release_shipability_gate.py --repo . --shell-prune-max-unmigrated 0 --shell-prune-phase cutover`
- `./.venv/bin/python scripts/report_unmigrated_shell.py --repo .`
- `./.venv/bin/python scripts/verify_shell_prune_contract.py --repo .`
- `./.venv/bin/python -m unittest discover -s tests/python -p 'test_*.py'`
- `bats tests/bats/python_*.bats tests/bats/parallel_trees_python_e2e.bats`

## Appendix E: Milestone-by-Milestone Execution Program (Everything Planned)

### Milestone 0: Governance and truth hardening (no behavior regressions)
- Objective:
  - Make strict cutover truth (`max_unmigrated=0` for cutover lane) the default release signal.
- Work packages:
  - WP-0001: Enforce strict budget in release lane wrappers and CI invocation.
  - WP-0002: Add doctor strict-mode indicators and fail reason surfacing.
  - WP-0003: Add manifest/doctor/release-gate consistency assertions.
- Entry criteria:
  - Baseline full test suite green.
- Exit criteria:
  - Strict gate failure reason is singular and explicit when non-zero backlog exists.

### Milestone 1: Shell ledger classification pass (inventory -> execution backlog)
- Objective:
  - Transform 320 inventory rows into classified migration tasks with evidence and ownership.
- Work packages:
  - WP-0101: Add wave ownership metadata for all 320 entries.
  - WP-0102: Add module-level owner mappings and target python symbols.
  - WP-0103: Add required evidence test references for every entry.
  - WP-0104: Add per-wave budget constraints and CI gate checks.
- Entry criteria:
  - M0 complete.
- Exit criteria:
  - 100% ledger rows classified with wave/owner/evidence; no unplanned rows.

### Milestone 2: Interactive and action parity completion
- Objective:
  - Achieve Bash-equivalent interactive UX and action command native defaults.
- Work packages:
  - WP-0201: Harden TTY input parser (CSI/SS3/control-seq contamination).
  - WP-0202: Stabilize planning selector rendering layout/truncation.
  - WP-0203: Make `pr`/`commit` native defaults in `actions_git.py`.
  - WP-0204: Make `analyze` native default in `actions_analysis.py`.
  - WP-0205: Validate command selector semantics (`--project`, `--projects`, `--all`).
- Entry criteria:
  - M1 complete.
- Exit criteria:
  - Interactive key behavior reliable and action families execute without mandatory shell wrappers.

### Milestone 3: Planning/worktree orchestration parity
- Objective:
  - Make plan mode fully Python-owned, deterministic, and Bash-parity compatible.
- Work packages:
  - WP-0301: Planning selection + count adjust + existing-worktree awareness.
  - WP-0302: Deterministic create/reuse/delete orchestration for worktrees.
  - WP-0303: Nested + flat topology consistency and naming invariants.
  - WP-0304: Plan-mode continuation into startup + dashboard flow.
- Entry criteria:
  - M2 complete.
- Exit criteria:
  - `--plan` behavior is end-to-end parity and deterministic.

### Milestone 4: Requirements + service startup realism
- Objective:
  - Remove synthetic dependence and ensure readiness is proven by real checks.
- Work packages:
  - WP-0401: Strict runtime blocks synthetic execution in production profile.
  - WP-0402: Postgres adapter parity completion.
  - WP-0403: Redis adapter parity completion.
  - WP-0404: Supabase adapter parity completion (sequence/probes/recovery).
  - WP-0405: N8N parity completion (bootstrap/restart/recreate policy).
  - WP-0406: Listener-truth backend/frontend startup and rebound propagation.
- Entry criteria:
  - M3 complete.
- Exit criteria:
  - Service/requirements success only on proven readiness.

### Milestone 5: Resume/restart/cleanup parity
- Objective:
  - Ensure deterministic recoverability and complete lifecycle cleanup behavior.
- Work packages:
  - WP-0501: Resume stale detection + targeted restore policy.
  - WP-0502: Restart idempotency with replacement semantics.
  - WP-0503: Stop/stop-all deterministic lock/state cleanup.
  - WP-0504: Blast-all contract parity and safety controls.
  - WP-0505: Recovery output and pointer compatibility cleanup.
- Entry criteria:
  - M4 complete.
- Exit criteria:
  - Lifecycle commands parity-tested and idempotent under partial state.

### Milestone 6: Runtime decomposition and maintainability
- Objective:
  - Reduce regression risk by extracting bounded modules from runtime monolith.
- Work packages:
  - WP-0601: Extract startup orchestrator.
  - WP-0602: Extract lifecycle cleanup controller.
  - WP-0603: Extract dashboard/interactive rendering controller.
  - WP-0604: Extract resume/reconcile controller.
  - WP-0605: Extract doctor/readiness gate reporter.
- Entry criteria:
  - M5 complete.
- Exit criteria:
  - No behavior drift; full suite green across extraction slices.

### Milestone 7: Final strict cutover and shell retirement readiness
- Objective:
  - Reach strict green gates and prepare shell runtime demotion.
- Work packages:
  - WP-0701: Eliminate synthetic use in strict parity suites.
  - WP-0702: Reduce ledger unmigrated count to zero for cutover scope.
  - WP-0703: Validate two stable release cycles.
  - WP-0704: Formalize fallback deprecation/removal window.
- Entry criteria:
  - M6 complete.
- Exit criteria:
  - All strict criteria met; fallback is emergency-only.

## Appendix F: Crosswalk Matrix (Bash domain -> Python ownership -> tests)

### A) CLI and routing crosswalk
- Bash source:
  - `lib/engine/lib/run_all_trees_cli.sh:run_all_trees_cli_parse_args`
- Python owner:
  - `python/envctl_engine/command_router.py:parse_route`
  - `python/envctl_engine/cli.py:run`
- Required tests:
  - `tests/python/test_cli_router.py`
  - `tests/python/test_cli_router_parity.py`
  - `tests/python/test_prereq_policy.py`
  - `tests/bats/python_command_alias_parity_e2e.bats`
  - `tests/bats/python_parser_docs_parity_e2e.bats`

### B) Planning/worktree orchestration crosswalk
- Bash source:
  - `lib/engine/lib/planning.sh`
  - `lib/engine/lib/run_all_trees_helpers.sh` (planning/setup paths)
  - `lib/engine/lib/worktrees.sh`
- Python owner:
  - `python/envctl_engine/planning.py`
  - `python/envctl_engine/engine_runtime.py:_select_plan_projects`, `_apply_setup_worktree_selection`
- Required tests:
  - `tests/python/test_planning_selection.py`
  - `tests/python/test_planning_worktree_setup.py`
  - `tests/python/test_discovery_topology.py`
  - `tests/bats/python_plan_nested_worktree_e2e.bats`
  - `tests/bats/python_plan_parallel_ports_e2e.bats`
  - `tests/bats/python_planning_worktree_setup_e2e.bats`

### C) Requirements parity crosswalk
- Bash source:
  - `lib/engine/lib/requirements_core.sh`
  - `lib/engine/lib/requirements_supabase.sh`
- Python owner:
  - `python/envctl_engine/requirements/{postgres,redis,supabase,n8n}.py`
  - `python/envctl_engine/requirements_orchestrator.py`
- Required tests:
  - `tests/python/test_requirements_orchestrator.py`
  - `tests/python/test_requirements_adapters_real_contracts.py`
  - `tests/python/test_supabase_requirements_reliability.py`
  - `tests/bats/python_requirements_conflict_recovery.bats`

### D) Service lifecycle parity crosswalk
- Bash source:
  - `lib/engine/lib/services_lifecycle.sh`
- Python owner:
  - `python/envctl_engine/service_manager.py`
  - `python/envctl_engine/process_runner.py`
  - `python/envctl_engine/engine_runtime.py:_start_project_services`
- Required tests:
  - `tests/python/test_service_manager.py`
  - `tests/python/test_process_runner_listener_detection.py`
  - `tests/python/test_engine_runtime_real_startup.py`

### E) State/resume/restart parity crosswalk
- Bash source:
  - `lib/engine/lib/state.sh`
- Python owner:
  - `python/envctl_engine/state.py`
  - `python/envctl_engine/engine_runtime.py:_resume`
- Required tests:
  - `tests/python/test_state_loader.py`
  - `tests/python/test_state_shell_compatibility.py`
  - `tests/python/test_state_roundtrip.py`
  - `tests/python/test_runtime_health_truth.py`
  - `tests/bats/python_state_resume_shell_compat_e2e.bats`
  - `tests/bats/python_resume_restore_missing_e2e.bats`

### F) Runtime map / truth projection crosswalk
- Bash source:
  - `lib/engine/lib/runtime_map.sh`
- Python owner:
  - `python/envctl_engine/runtime_map.py`
  - `python/envctl_engine/engine_runtime.py` state-action and dashboard projection logic
- Required tests:
  - `tests/python/test_runtime_projection_urls.py`
  - `tests/python/test_frontend_env_projection_real_ports.py`
  - `tests/python/test_frontend_projection.py`
  - `tests/bats/python_listener_projection_e2e.bats`

### G) Cleanup parity crosswalk (`stop`, `stop-all`, `blast-all`)
- Bash source:
  - `lib/engine/lib/state.sh:cleanup`, `cleanup_blast_all`
  - `lib/engine/lib/docker.sh` cleanup helpers
- Python owner:
  - `python/envctl_engine/engine_runtime.py:_stop`
  - `python/envctl_engine/ports.py` release functions
- Required tests:
  - `tests/python/test_lifecycle_parity.py`
  - `tests/python/test_ports_lock_reclamation.py`
  - `tests/bats/python_stop_blast_all_parity_e2e.bats`

### H) Interactive/dashboard parity crosswalk
- Bash source:
  - `lib/engine/lib/ui.sh`
  - `lib/engine/lib/actions.sh:run_dashboard`, `run_doctor`
- Python owner:
  - `python/envctl_engine/engine_runtime.py:_interactive_loop`, `_dashboard`, `_doctor`, `_state_action`
- Required tests:
  - `tests/python/test_logs_parity.py`
  - `tests/python/test_runtime_health_truth.py`
  - `tests/bats/python_logs_follow_parity_e2e.bats`
  - `tests/bats/python_runtime_truth_health_e2e.bats`


## Appendix G: Function-Level Migration Matrix (320 items)

This matrix assigns every currently unmigrated shell function to a concrete Python ownership target and required evidence tests.

### lib/engine/lib/actions.sh (21)
- Planned Python owner: `python/envctl_engine/engine_runtime.py (+ actions_worktree.py)`
- Required evidence tests: `tests/python/test_engine_runtime_command_parity.py; tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats`

| Shell function | Source line | Planned target owner | Evidence tests |
| --- | ---: | --- | --- |
| `actions_is_truthy` | `16` | `python/envctl_engine/engine_runtime.py (+ actions_worktree.py)` | `tests/python/test_engine_runtime_command_parity.py; tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `actions_trim` | `5` | `python/envctl_engine/engine_runtime.py (+ actions_worktree.py)` | `tests/python/test_engine_runtime_command_parity.py; tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `dashboard_connection_targets` | `310` | `python/envctl_engine/engine_runtime.py (+ actions_worktree.py)` | `tests/python/test_engine_runtime_command_parity.py; tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `dashboard_extract_host_ports` | `271` | `python/envctl_engine/engine_runtime.py (+ actions_worktree.py)` | `tests/python/test_engine_runtime_command_parity.py; tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `dashboard_http_endpoint_candidates` | `358` | `python/envctl_engine/engine_runtime.py (+ actions_worktree.py)` | `tests/python/test_engine_runtime_command_parity.py; tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `dashboard_http_probe_status` | `383` | `python/envctl_engine/engine_runtime.py (+ actions_worktree.py)` | `tests/python/test_engine_runtime_command_parity.py; tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `dashboard_is_data_container` | `294` | `python/envctl_engine/engine_runtime.py (+ actions_worktree.py)` | `tests/python/test_engine_runtime_command_parity.py; tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `dashboard_show_docker_containers` | `421` | `python/envctl_engine/engine_runtime.py (+ actions_worktree.py)` | `tests/python/test_engine_runtime_command_parity.py; tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `doctor_check_port` | `145` | `python/envctl_engine/engine_runtime.py (+ actions_worktree.py)` | `tests/python/test_engine_runtime_command_parity.py; tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `doctor_check_state_orphans` | `163` | `python/envctl_engine/engine_runtime.py (+ actions_worktree.py)` | `tests/python/test_engine_runtime_command_parity.py; tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `doctor_collect_state_pointers` | `159` | `python/envctl_engine/engine_runtime.py (+ actions_worktree.py)` | `tests/python/test_engine_runtime_command_parity.py; tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `list_command_targets` | `47` | `python/envctl_engine/engine_runtime.py (+ actions_worktree.py)` | `tests/python/test_engine_runtime_command_parity.py; tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `list_commands` | `27` | `python/envctl_engine/engine_runtime.py (+ actions_worktree.py)` | `tests/python/test_engine_runtime_command_parity.py; tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `list_worktree_paths_for_delete` | `599` | `python/envctl_engine/engine_runtime.py (+ actions_worktree.py)` | `tests/python/test_engine_runtime_command_parity.py; tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `parse_command_targets` | `58` | `python/envctl_engine/engine_runtime.py (+ actions_worktree.py)` | `tests/python/test_engine_runtime_command_parity.py; tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `run_command` | `762` | `python/envctl_engine/engine_runtime.py (+ actions_worktree.py)` | `tests/python/test_engine_runtime_command_parity.py; tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `run_dashboard` | `563` | `python/envctl_engine/engine_runtime.py (+ actions_worktree.py)` | `tests/python/test_engine_runtime_command_parity.py; tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `run_doctor` | `177` | `python/envctl_engine/engine_runtime.py (+ actions_worktree.py)` | `tests/python/test_engine_runtime_command_parity.py; tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `run_worktree_delete_command` | `656` | `python/envctl_engine/engine_runtime.py (+ actions_worktree.py)` | `tests/python/test_engine_runtime_command_parity.py; tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `validate_command_targets` | `91` | `python/envctl_engine/engine_runtime.py (+ actions_worktree.py)` | `tests/python/test_engine_runtime_command_parity.py; tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `worktree_delete_label_for_path` | `634` | `python/envctl_engine/engine_runtime.py (+ actions_worktree.py)` | `tests/python/test_engine_runtime_command_parity.py; tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |

### lib/engine/lib/analysis.sh (34)
- Planned Python owner: `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)`
- Required evidence tests: `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats`

| Shell function | Source line | Planned target owner | Evidence tests |
| --- | ---: | --- | --- |
| `analysis_collect_tree_paths` | `1817` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `analysis_ensure_base_dir` | `390` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `analysis_extract_non_md_files` | `473` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `analysis_extract_paths_from_status_list` | `461` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `analysis_filter_files` | `423` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `analysis_init_config` | `175` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `analysis_parse_args` | `278` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `analysis_prepare_output_dir` | `374` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `analysis_print_completion` | `1982` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `analysis_print_next_steps` | `2029` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `analysis_print_output_dir` | `2002` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `analysis_print_tree_selection` | `2006` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `analysis_print_verbose_details` | `2012` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `analysis_resolve_scope_filter` | `351` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `analysis_resolve_trees_to_analyze` | `1833` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `analysis_run_trees` | `1910` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `analysis_selection_has_multiple_iterations` | `53` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `analysis_set_base_dir` | `346` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `analysis_should_include_file` | `410` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `analysis_show_help` | `202` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `analysis_write_name_status_list` | `437` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `analysis_write_state_file` | `1936` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `analysis_write_summary_short` | `1950` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `analyze_tree_changes` | `490` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `copy_root_docs_markdown` | `738` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `create_evaluation_request` | `759` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `create_scoring_template` | `1721` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `estimate_tokens` | `732` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `generate_enhanced_summary` | `1750` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `generate_llm_prompt` | `1496` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `get_grep_exclusions` | `404` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `list_project_iterations` | `38` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `resolve_analysis_selection` | `5` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |
| `run_tree_change_analysis` | `83` | `python/envctl_engine/actions_analysis.py (+ runtime action dispatch)` | `tests/python/test_actions_parity.py; tests/python/test_actions_native_execution.py; tests/bats/python_actions_parity_e2e.bats` |

### lib/engine/lib/config.sh (3)
- Planned Python owner: `python/envctl_engine/config.py`
- Required evidence tests: `tests/python/test_config_loader.py`

| Shell function | Source line | Planned target owner | Evidence tests |
| --- | ---: | --- | --- |
| `init_run_all_trees_config` | `14` | `python/envctl_engine/config.py` | `tests/python/test_config_loader.py` |
| `parse_run_all_trees_args` | `18` | `python/envctl_engine/config.py` | `tests/python/test_config_loader.py` |
| `print_run_all_trees_usage` | `10` | `python/envctl_engine/config.py` | `tests/python/test_config_loader.py` |

### lib/engine/lib/docker.sh (43)
- Planned Python owner: `python/envctl_engine/requirements/*.py + runtime cleanup`
- Required evidence tests: `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats`

| Shell function | Source line | Planned target owner | Evidence tests |
| --- | ---: | --- | --- |
| `check_docker` | `238` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `cleanup_docker_log_followers` | `657` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `collect_tree_entries` | `706` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `compose_has_service` | `393` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `docker_check_health` | `1376` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `docker_cmd` | `117` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `docker_compose` | `377` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `docker_compose_up` | `407` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `docker_container_exists` | `191` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `docker_container_running` | `197` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `docker_containers_on_port` | `1481` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `docker_containers_on_port_details` | `1487` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `docker_effective_services` | `636` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `docker_init_known_services` | `645` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `docker_list_services` | `1071` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `docker_print_timeout_hint_once` | `79` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `docker_probe` | `122` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `docker_ps_all_names_cached` | `151` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `docker_ps_all_names_contains` | `178` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `docker_ps_cache_ready` | `127` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `docker_ps_cache_refresh` | `134` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `docker_ps_ids_cached` | `158` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `docker_ps_names_cached` | `144` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `docker_ps_names_contains` | `165` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `docker_published_port` | `1054` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `docker_rebuild_services` | `1267` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `docker_restart_service` | `1246` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `docker_run_with_timeout` | `87` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `docker_show_errors` | `1347` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `docker_show_status` | `1081` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `docker_socket_path` | `30` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `docker_socket_state` | `46` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `docker_stop_all` | `1471` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `docker_stop_services` | `1450` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `docker_tail_logs` | `1310` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `docker_timeout_bin` | `14` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `ensure_docker_credential_helper` | `205` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `generate_docker_compose_trees` | `874` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `local_port_listeners` | `1493` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `maybe_stop_docker` | `425` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `resolve_docker_ports` | `448` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `resolve_docker_trees` | `1002` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |
| `scan_tree_root` | `711` | `python/envctl_engine/requirements/*.py + runtime cleanup` | `tests/python/test_requirements_adapters_real_contracts.py; tests/python/test_lifecycle_parity.py; tests/bats/python_stop_blast_all_parity_e2e.bats` |

### lib/engine/lib/env.sh (10)
- Planned Python owner: `python/envctl_engine/config.py (+ env helpers if extracted)`
- Required evidence tests: `tests/python/test_config_loader.py`

| Shell function | Source line | Planned target owner | Evidence tests |
| --- | ---: | --- | --- |
| `_read_env_value_raw` | `93` | `python/envctl_engine/config.py (+ env helpers if extracted)` | `tests/python/test_config_loader.py` |
| `env_cache_build` | `64` | `python/envctl_engine/config.py (+ env helpers if extracted)` | `tests/python/test_config_loader.py` |
| `env_cache_dir` | `20` | `python/envctl_engine/config.py (+ env helpers if extracted)` | `tests/python/test_config_loader.py` |
| `env_cache_enabled` | `10` | `python/envctl_engine/config.py (+ env helpers if extracted)` | `tests/python/test_config_loader.py` |
| `env_cache_file_for` | `56` | `python/envctl_engine/config.py (+ env helpers if extracted)` | `tests/python/test_config_loader.py` |
| `env_cache_key` | `39` | `python/envctl_engine/config.py (+ env helpers if extracted)` | `tests/python/test_config_loader.py` |
| `load_env_file_safe` | `210` | `python/envctl_engine/config.py (+ env helpers if extracted)` | `tests/python/test_config_loader.py` |
| `read_env_value` | `118` | `python/envctl_engine/config.py (+ env helpers if extracted)` | `tests/python/test_config_loader.py` |
| `read_env_value_cached` | `126` | `python/envctl_engine/config.py (+ env helpers if extracted)` | `tests/python/test_config_loader.py` |
| `upsert_env_value` | `189` | `python/envctl_engine/config.py (+ env helpers if extracted)` | `tests/python/test_config_loader.py` |

### lib/engine/lib/git.sh (4)
- Planned Python owner: `python/envctl_engine/actions_git.py (+ shared git util if extracted)`
- Required evidence tests: `tests/python/test_actions_parity.py`

| Shell function | Source line | Planned target owner | Evidence tests |
| --- | ---: | --- | --- |
| `extract_repo_slug` | `73` | `python/envctl_engine/actions_git.py (+ shared git util if extracted)` | `tests/python/test_actions_parity.py` |
| `git_state_cache_ttl` | `26` | `python/envctl_engine/actions_git.py (+ shared git util if extracted)` | `tests/python/test_actions_parity.py` |
| `git_state_for_dir` | `35` | `python/envctl_engine/actions_git.py (+ shared git util if extracted)` | `tests/python/test_actions_parity.py` |
| `hash_stdin` | `3` | `python/envctl_engine/actions_git.py (+ shared git util if extracted)` | `tests/python/test_actions_parity.py` |

### lib/engine/lib/loader.sh (1)
- Planned Python owner: `python/envctl_engine/state.py / hooks bridge (safe parsing)`
- Required evidence tests: `tests/python/test_state_loader.py; tests/python/test_hooks_bridge.py`

| Shell function | Source line | Planned target owner | Evidence tests |
| --- | ---: | --- | --- |
| `safe_source` | `34` | `python/envctl_engine/state.py / hooks bridge (safe parsing)` | `tests/python/test_state_loader.py; tests/python/test_hooks_bridge.py` |

### lib/engine/lib/planning.sh (13)
- Planned Python owner: `python/envctl_engine/planning.py`
- Required evidence tests: `tests/python/test_planning_selection.py; tests/bats/python_plan_nested_worktree_e2e.bats`

| Shell function | Source line | Planned target owner | Evidence tests |
| --- | ---: | --- | --- |
| `list_done_planning_files` | `69` | `python/envctl_engine/planning.py` | `tests/python/test_planning_selection.py; tests/bats/python_plan_nested_worktree_e2e.bats` |
| `list_planning_files` | `57` | `python/envctl_engine/planning.py` | `tests/python/test_planning_selection.py; tests/bats/python_plan_nested_worktree_e2e.bats` |
| `planning_dir_display` | `24` | `python/envctl_engine/planning.py` | `tests/python/test_planning_selection.py; tests/bats/python_plan_nested_worktree_e2e.bats` |
| `planning_dir_path` | `14` | `python/envctl_engine/planning.py` | `tests/python/test_planning_selection.py; tests/bats/python_plan_nested_worktree_e2e.bats` |
| `planning_dir_raw` | `5` | `python/envctl_engine/planning.py` | `tests/python/test_planning_selection.py; tests/bats/python_plan_nested_worktree_e2e.bats` |
| `planning_existing_count` | `378` | `python/envctl_engine/planning.py` | `tests/python/test_planning_selection.py; tests/bats/python_plan_nested_worktree_e2e.bats` |
| `planning_feature_name` | `368` | `python/envctl_engine/planning.py` | `tests/python/test_planning_selection.py; tests/bats/python_plan_nested_worktree_e2e.bats` |
| `planning_file_path` | `34` | `python/envctl_engine/planning.py` | `tests/python/test_planning_selection.py; tests/bats/python_plan_nested_worktree_e2e.bats` |
| `planning_move_to_done` | `387` | `python/envctl_engine/planning.py` | `tests/python/test_planning_selection.py; tests/bats/python_plan_nested_worktree_e2e.bats` |
| `planning_normalize_selection_token` | `41` | `python/envctl_engine/planning.py` | `tests/python/test_planning_selection.py; tests/bats/python_plan_nested_worktree_e2e.bats` |
| `resolve_planning_files` | `279` | `python/envctl_engine/planning.py` | `tests/python/test_planning_selection.py; tests/bats/python_plan_nested_worktree_e2e.bats` |
| `select_planning_files` | `251` | `python/envctl_engine/planning.py` | `tests/python/test_planning_selection.py; tests/bats/python_plan_nested_worktree_e2e.bats` |
| `select_planning_files_interactive` | `82` | `python/envctl_engine/planning.py` | `tests/python/test_planning_selection.py; tests/bats/python_plan_nested_worktree_e2e.bats` |

### lib/engine/lib/ports.sh (22)
- Planned Python owner: `python/envctl_engine/ports.py`
- Required evidence tests: `tests/python/test_ports_lock_reclamation.py; tests/python/test_ports_availability_strategies.py`

| Shell function | Source line | Planned target owner | Evidence tests |
| --- | ---: | --- | --- |
| `find_free_port` | `431` | `python/envctl_engine/ports.py` | `tests/python/test_ports_lock_reclamation.py; tests/python/test_ports_availability_strategies.py` |
| `is_port_free` | `376` | `python/envctl_engine/ports.py` | `tests/python/test_ports_lock_reclamation.py; tests/python/test_ports_availability_strategies.py` |
| `port_is_open_fast` | `461` | `python/envctl_engine/ports.py` | `tests/python/test_ports_lock_reclamation.py; tests/python/test_ports_availability_strategies.py` |
| `port_is_reserved` | `255` | `python/envctl_engine/ports.py` | `tests/python/test_ports_lock_reclamation.py; tests/python/test_ports_availability_strategies.py` |
| `port_release` | `313` | `python/envctl_engine/ports.py` | `tests/python/test_ports_lock_reclamation.py; tests/python/test_ports_availability_strategies.py` |
| `port_release_all` | `321` | `python/envctl_engine/ports.py` | `tests/python/test_ports_lock_reclamation.py; tests/python/test_ports_availability_strategies.py` |
| `port_reservation_dir` | `162` | `python/envctl_engine/ports.py` | `tests/python/test_ports_lock_reclamation.py; tests/python/test_ports_availability_strategies.py` |
| `port_reservation_lock_dir` | `181` | `python/envctl_engine/ports.py` | `tests/python/test_ports_lock_reclamation.py; tests/python/test_ports_availability_strategies.py` |
| `port_reservation_reclaim_stale` | `198` | `python/envctl_engine/ports.py` | `tests/python/test_ports_lock_reclamation.py; tests/python/test_ports_availability_strategies.py` |
| `port_reservation_write_owner` | `188` | `python/envctl_engine/ports.py` | `tests/python/test_ports_lock_reclamation.py; tests/python/test_ports_availability_strategies.py` |
| `port_reserve` | `293` | `python/envctl_engine/ports.py` | `tests/python/test_ports_lock_reclamation.py; tests/python/test_ports_availability_strategies.py` |
| `port_snapshot_collect` | `348` | `python/envctl_engine/ports.py` | `tests/python/test_ports_lock_reclamation.py; tests/python/test_ports_availability_strategies.py` |
| `port_snapshot_enabled` | `155` | `python/envctl_engine/ports.py` | `tests/python/test_ports_lock_reclamation.py; tests/python/test_ports_availability_strategies.py` |
| `port_snapshot_refresh` | `367` | `python/envctl_engine/ports.py` | `tests/python/test_ports_lock_reclamation.py; tests/python/test_ports_availability_strategies.py` |
| `port_state_clear` | `103` | `python/envctl_engine/ports.py` | `tests/python/test_ports_lock_reclamation.py; tests/python/test_ports_availability_strategies.py` |
| `port_state_clear_saved` | `117` | `python/envctl_engine/ports.py` | `tests/python/test_ports_lock_reclamation.py; tests/python/test_ports_availability_strategies.py` |
| `port_state_file_path` | `20` | `python/envctl_engine/ports.py` | `tests/python/test_ports_lock_reclamation.py; tests/python/test_ports_availability_strategies.py` |
| `port_state_load_once` | `62` | `python/envctl_engine/ports.py` | `tests/python/test_ports_lock_reclamation.py; tests/python/test_ports_availability_strategies.py` |
| `port_state_record` | `49` | `python/envctl_engine/ports.py` | `tests/python/test_ports_lock_reclamation.py; tests/python/test_ports_availability_strategies.py` |
| `port_state_write` | `32` | `python/envctl_engine/ports.py` | `tests/python/test_ports_lock_reclamation.py; tests/python/test_ports_availability_strategies.py` |
| `reserve_port` | `406` | `python/envctl_engine/ports.py` | `tests/python/test_ports_lock_reclamation.py; tests/python/test_ports_availability_strategies.py` |
| `wait_for_port` | `436` | `python/envctl_engine/ports.py` | `tests/python/test_ports_lock_reclamation.py; tests/python/test_ports_availability_strategies.py` |

### lib/engine/lib/pr.sh (23)
- Planned Python owner: `python/envctl_engine/actions_git.py`
- Required evidence tests: `tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats`

| Shell function | Source line | Planned target owner | Evidence tests |
| --- | ---: | --- | --- |
| `apply_main_task_to_body` | `136` | `python/envctl_engine/actions_git.py` | `tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `build_commit_list` | `69` | `python/envctl_engine/actions_git.py` | `tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `build_pr_body_file` | `158` | `python/envctl_engine/actions_git.py` | `tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `commit_paths` | `434` | `python/envctl_engine/actions_git.py` | `tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `commit_unstaged_changes` | `224` | `python/envctl_engine/actions_git.py` | `tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `create_prs_for_paths` | `550` | `python/envctl_engine/actions_git.py` | `tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `create_prs_for_planning_paths` | `647` | `python/envctl_engine/actions_git.py` | `tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `default_pr_base_branch` | `33` | `python/envctl_engine/actions_git.py` | `tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `find_template_file` | `85` | `python/envctl_engine/actions_git.py` | `tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `pr_branch_exists` | `60` | `python/envctl_engine/actions_git.py` | `tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `pr_info_for_project` | `354` | `python/envctl_engine/actions_git.py` | `tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `pr_label_for_project` | `331` | `python/envctl_engine/actions_git.py` | `tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `pr_status_for_branch` | `255` | `python/envctl_engine/actions_git.py` | `tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `pr_url_for_branch` | `290` | `python/envctl_engine/actions_git.py` | `tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `pr_url_for_branch_if_exists` | `320` | `python/envctl_engine/actions_git.py` | `tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `pr_url_for_project` | `375` | `python/envctl_engine/actions_git.py` | `tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `prompt_commit_message` | `210` | `python/envctl_engine/actions_git.py` | `tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `prompt_pr_base_branch` | `655` | `python/envctl_engine/actions_git.py` | `tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `read_main_task_content` | `110` | `python/envctl_engine/actions_git.py` | `tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `read_main_task_message` | `403` | `python/envctl_engine/actions_git.py` | `tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `read_main_task_title` | `119` | `python/envctl_engine/actions_git.py` | `tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `read_tree_changelog_message` | `413` | `python/envctl_engine/actions_git.py` | `tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |
| `replace_placeholder` | `5` | `python/envctl_engine/actions_git.py` | `tests/python/test_actions_parity.py; tests/bats/python_actions_parity_e2e.bats` |

### lib/engine/lib/run_all_trees_helpers.sh (44)
- Planned Python owner: `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)`
- Required evidence tests: `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats`

| Shell function | Source line | Planned target owner | Evidence tests |
| --- | ---: | --- | --- |
| `check_required_tools` | `21` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `cleanup_empty_feature_root` | `71` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `dedupe_array_in_place` | `1637` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `envctl_define_flat_services` | `1968` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `resolve_main_backend_env_file` | `95` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `resolve_main_frontend_env_file` | `135` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_apply_cli_project_filters` | `466` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_collect_finished_parallel_worker` | `1706` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_dashboard_path` | `1223` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_ensure_command_context` | `228` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_export_setup_envs` | `657` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_handle_docker_mode` | `598` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_handle_planning_envs` | `837` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_handle_resume` | `413` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_handle_setup_worktrees` | `720` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_init_tty` | `157` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_init_tty_debug_log` | `170` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_is_main_project_name` | `458` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_merge_worker_fragment` | `1653` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_parallel_worker` | `1606` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_parallel_worker_write_fragment` | `1564` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_prepare_requirements` | `647` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_prepare_tree_paths` | `1429` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_print_failed_services` | `1153` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_print_logs_path_once` | `1168` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_print_logs_summary` | `1180` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_print_noninteractive_summary` | `1412` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_print_running_services` | `1136` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_resolve_main_environment` | `663` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_root_dashboard_path` | `1234` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_run_command` | `307` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_run_docker_interactive` | `181` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_run_interactive` | `201` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_start_main_project` | `2011` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_start_projects` | `2059` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_start_requirements` | `1033` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_start_tree_projects` | `1859` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_start_tree_projects_parallel` | `1800` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `run_all_trees_write_dashboard` | `1249` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `slugify` | `63` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `slugify_underscore` | `67` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `start_tree_dir` | `2067` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `start_tree_job_with_offset` | `1507` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |
| `tree_target_matches` | `1476` | `python/envctl_engine/engine_runtime.py (+ startup orchestrator extraction)` | `tests/python/test_engine_runtime_real_startup.py; tests/python/test_planning_worktree_setup.py; tests/bats/parallel_trees_python_e2e.bats` |

### lib/engine/lib/runtime_map.sh (3)
- Planned Python owner: `python/envctl_engine/runtime_map.py`
- Required evidence tests: `tests/python/test_runtime_projection_urls.py; tests/bats/python_listener_projection_e2e.bats`

| Shell function | Source line | Planned target owner | Evidence tests |
| --- | ---: | --- | --- |
| `load_runtime_map` | `105` | `python/envctl_engine/runtime_map.py` | `tests/python/test_runtime_projection_urls.py; tests/bats/python_listener_projection_e2e.bats` |
| `runtime_map_path` | `3` | `python/envctl_engine/runtime_map.py` | `tests/python/test_runtime_projection_urls.py; tests/bats/python_listener_projection_e2e.bats` |
| `write_runtime_map` | `15` | `python/envctl_engine/runtime_map.py` | `tests/python/test_runtime_projection_urls.py; tests/bats/python_listener_projection_e2e.bats` |

### lib/engine/lib/state.sh (56)
- Planned Python owner: `python/envctl_engine/state.py + engine_runtime resume/cleanup`
- Required evidence tests: `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats`

| Shell function | Source line | Planned target owner | Evidence tests |
| --- | ---: | --- | --- |
| `_kill_pid_tree` | `423` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `analysis_info_for_project` | `52` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `backend_port_for_project` | `364` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `cleanup` | `607` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `cleanup_add_port` | `451` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `cleanup_add_spaced_ports` | `462` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `cleanup_blast_all` | `793` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `cleanup_collect_port_candidates` | `512` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `cleanup_kill_port_ranges` | `576` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `cleanup_port_slot_count` | `480` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `collect_all_state_pointers` | `1066` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `collect_dashboard_state_files` | `1078` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `create_recovery_script` | `2164` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `file_mtime_epoch` | `175` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `find_last_state_file` | `1106` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `find_service_by_name` | `370` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `format_epoch_short` | `191` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `format_last_test_line` | `303` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `format_summary_timestamp` | `168` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `generate_error_report` | `2116` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `get_pids_for_port` | `568` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `has_passing_tests` | `278` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `kill_job_pids` | `416` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `last_state_is_main` | `1321` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `last_state_is_trees` | `1312` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `latest_test_summary_file` | `237` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `list_untested_projects` | `290` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `load_attach_state` | `1919` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `load_state_for_command` | `1799` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `load_state_for_dashboard` | `1200` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `project_tests_status` | `260` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `restart_service` | `2222` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `resume_apply_project_filter` | `1421` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `resume_apply_status_defaults` | `1528` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `resume_from_state` | `1707` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `resume_hint_command` | `2089` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `resume_project_name_is_main` | `1329` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `resume_selected_projects_from_targets` | `1338` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `resume_selected_targets_include_main` | `1384` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `save_state` | `1975` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `service_health_suffix` | `339` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `state_absolute_dir` | `1962` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `state_absolute_path` | `1944` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `state_file_from_pointer` | `1043` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `state_file_matches` | `27` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `state_file_matches_requested_mode` | `1112` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `state_guess_project_root_from_name` | `1564` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `state_guess_service_dir_from_name` | `1608` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `state_load_dashboard_selection` | `1395` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `state_pointer_dir` | `1055` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `state_projects_from_services` | `2047` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `state_recover_service_info_if_missing` | `1636` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `status_cache_ttl` | `18` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `test_info_for_project` | `110` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `tests_status_for_summary_file` | `247` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |
| `write_last_state_pointers` | `2061` | `python/envctl_engine/state.py + engine_runtime resume/cleanup` | `tests/python/test_state_shell_compatibility.py; tests/python/test_runtime_health_truth.py; tests/bats/python_state_resume_shell_compat_e2e.bats` |

### lib/engine/lib/ui.sh (22)
- Planned Python owner: `python/envctl_engine/engine_runtime.py (interactive/dashboard) (+ extracted module)`
- Required evidence tests: `tests/python/test_logs_parity.py; tests/python/test_interactive_input_reliability.py; tests/bats/python_logs_follow_parity_e2e.bats`

| Shell function | Source line | Planned target owner | Evidence tests |
| --- | ---: | --- | --- |
| `append_menu_option` | `455` | `python/envctl_engine/engine_runtime.py (interactive/dashboard) (+ extracted module)` | `tests/python/test_logs_parity.py; tests/python/test_interactive_input_reliability.py; tests/bats/python_logs_follow_parity_e2e.bats` |
| `append_project_options` | `480` | `python/envctl_engine/engine_runtime.py (interactive/dashboard) (+ extracted module)` | `tests/python/test_logs_parity.py; tests/python/test_interactive_input_reliability.py; tests/bats/python_logs_follow_parity_e2e.bats` |
| `append_service_options` | `468` | `python/envctl_engine/engine_runtime.py (interactive/dashboard) (+ extracted module)` | `tests/python/test_logs_parity.py; tests/python/test_interactive_input_reliability.py; tests/bats/python_logs_follow_parity_e2e.bats` |
| `drain_pending_input` | `90` | `python/envctl_engine/engine_runtime.py (interactive/dashboard) (+ extracted module)` | `tests/python/test_logs_parity.py; tests/python/test_interactive_input_reliability.py; tests/bats/python_logs_follow_parity_e2e.bats` |
| `interactive_mode` | `883` | `python/envctl_engine/engine_runtime.py (interactive/dashboard) (+ extracted module)` | `tests/python/test_logs_parity.py; tests/python/test_interactive_input_reliability.py; tests/bats/python_logs_follow_parity_e2e.bats` |
| `interactive_mode_docker` | `824` | `python/envctl_engine/engine_runtime.py (interactive/dashboard) (+ extracted module)` | `tests/python/test_logs_parity.py; tests/python/test_interactive_input_reliability.py; tests/bats/python_logs_follow_parity_e2e.bats` |
| `menu_cleanup` | `329` | `python/envctl_engine/engine_runtime.py (interactive/dashboard) (+ extracted module)` | `tests/python/test_logs_parity.py; tests/python/test_interactive_input_reliability.py; tests/bats/python_logs_follow_parity_e2e.bats` |
| `menu_setup` | `338` | `python/envctl_engine/engine_runtime.py (interactive/dashboard) (+ extracted module)` | `tests/python/test_logs_parity.py; tests/python/test_interactive_input_reliability.py; tests/bats/python_logs_follow_parity_e2e.bats` |
| `migration_db_hint` | `630` | `python/envctl_engine/engine_runtime.py (interactive/dashboard) (+ extracted module)` | `tests/python/test_logs_parity.py; tests/python/test_interactive_input_reliability.py; tests/bats/python_logs_follow_parity_e2e.bats` |
| `prompt_yes_no` | `13` | `python/envctl_engine/engine_runtime.py (interactive/dashboard) (+ extracted module)` | `tests/python/test_logs_parity.py; tests/python/test_interactive_input_reliability.py; tests/bats/python_logs_follow_parity_e2e.bats` |
| `read_char` | `40` | `python/envctl_engine/engine_runtime.py (interactive/dashboard) (+ extracted module)` | `tests/python/test_logs_parity.py; tests/python/test_interactive_input_reliability.py; tests/bats/python_logs_follow_parity_e2e.bats` |
| `read_command` | `226` | `python/envctl_engine/engine_runtime.py (interactive/dashboard) (+ extracted module)` | `tests/python/test_logs_parity.py; tests/python/test_interactive_input_reliability.py; tests/bats/python_logs_follow_parity_e2e.bats` |
| `read_key` | `103` | `python/envctl_engine/engine_runtime.py (interactive/dashboard) (+ extracted module)` | `tests/python/test_logs_parity.py; tests/python/test_interactive_input_reliability.py; tests/bats/python_logs_follow_parity_e2e.bats` |
| `request_sigint_quit` | `343` | `python/envctl_engine/engine_runtime.py (interactive/dashboard) (+ extracted module)` | `tests/python/test_logs_parity.py; tests/python/test_interactive_input_reliability.py; tests/bats/python_logs_follow_parity_e2e.bats` |
| `tty_flush_input` | `313` | `python/envctl_engine/engine_runtime.py (interactive/dashboard) (+ extracted module)` | `tests/python/test_logs_parity.py; tests/python/test_interactive_input_reliability.py; tests/bats/python_logs_follow_parity_e2e.bats` |
| `tty_prepare_prompt` | `349` | `python/envctl_engine/engine_runtime.py (interactive/dashboard) (+ extracted module)` | `tests/python/test_logs_parity.py; tests/python/test_interactive_input_reliability.py; tests/bats/python_logs_follow_parity_e2e.bats` |
| `tty_raw_off` | `294` | `python/envctl_engine/engine_runtime.py (interactive/dashboard) (+ extracted module)` | `tests/python/test_logs_parity.py; tests/python/test_interactive_input_reliability.py; tests/bats/python_logs_follow_parity_e2e.bats` |
| `tty_raw_on` | `274` | `python/envctl_engine/engine_runtime.py (interactive/dashboard) (+ extracted module)` | `tests/python/test_logs_parity.py; tests/python/test_interactive_input_reliability.py; tests/bats/python_logs_follow_parity_e2e.bats` |
| `tty_restore_base` | `306` | `python/envctl_engine/engine_runtime.py (interactive/dashboard) (+ extracted module)` | `tests/python/test_logs_parity.py; tests/python/test_interactive_input_reliability.py; tests/bats/python_logs_follow_parity_e2e.bats` |
| `ui_can_interactive` | `26` | `python/envctl_engine/engine_runtime.py (interactive/dashboard) (+ extracted module)` | `tests/python/test_logs_parity.py; tests/python/test_interactive_input_reliability.py; tests/bats/python_logs_follow_parity_e2e.bats` |
| `ui_docker_handle_command` | `670` | `python/envctl_engine/engine_runtime.py (interactive/dashboard) (+ extracted module)` | `tests/python/test_logs_parity.py; tests/python/test_interactive_input_reliability.py; tests/bats/python_logs_follow_parity_e2e.bats` |
| `ui_interactive_handle_command` | `734` | `python/envctl_engine/engine_runtime.py (interactive/dashboard) (+ extracted module)` | `tests/python/test_logs_parity.py; tests/python/test_interactive_input_reliability.py; tests/bats/python_logs_follow_parity_e2e.bats` |

### lib/engine/lib/worktrees.sh (21)
- Planned Python owner: `python/envctl_engine/planning.py (+ worktree helper module)`
- Required evidence tests: `tests/python/test_planning_worktree_setup.py; tests/bats/python_planning_worktree_setup_e2e.bats`

| Shell function | Source line | Planned target owner | Evidence tests |
| --- | ---: | --- | --- |
| `_ports_file_lock_reclaim_stale` | `33` | `python/envctl_engine/planning.py (+ worktree helper module)` | `tests/python/test_planning_worktree_setup.py; tests/bats/python_planning_worktree_setup_e2e.bats` |
| `count_numeric_dir_names` | `183` | `python/envctl_engine/planning.py (+ worktree helper module)` | `tests/python/test_planning_worktree_setup.py; tests/bats/python_planning_worktree_setup_e2e.bats` |
| `discover_tree_roots` | `190` | `python/envctl_engine/planning.py (+ worktree helper module)` | `tests/python/test_planning_worktree_setup.py; tests/bats/python_planning_worktree_setup_e2e.bats` |
| `list_numeric_dir_names` | `171` | `python/envctl_engine/planning.py (+ worktree helper module)` | `tests/python/test_planning_worktree_setup.py; tests/bats/python_planning_worktree_setup_e2e.bats` |
| `list_numeric_dirs` | `177` | `python/envctl_engine/planning.py (+ worktree helper module)` | `tests/python/test_planning_worktree_setup.py; tests/bats/python_planning_worktree_setup_e2e.bats` |
| `list_tree_paths` | `212` | `python/envctl_engine/planning.py (+ worktree helper module)` | `tests/python/test_planning_worktree_setup.py; tests/bats/python_planning_worktree_setup_e2e.bats` |
| `ports_file_lock_acquire` | `66` | `python/envctl_engine/planning.py (+ worktree helper module)` | `tests/python/test_planning_worktree_setup.py; tests/bats/python_planning_worktree_setup_e2e.bats` |
| `ports_file_lock_release` | `94` | `python/envctl_engine/planning.py (+ worktree helper module)` | `tests/python/test_planning_worktree_setup.py; tests/bats/python_planning_worktree_setup_e2e.bats` |
| `preferred_tree_root_for_feature` | `467` | `python/envctl_engine/planning.py (+ worktree helper module)` | `tests/python/test_planning_worktree_setup.py; tests/bats/python_planning_worktree_setup_e2e.bats` |
| `read_ports_from_worktree_config` | `333` | `python/envctl_engine/planning.py (+ worktree helper module)` | `tests/python/test_planning_worktree_setup.py; tests/bats/python_planning_worktree_setup_e2e.bats` |
| `remove_worktree_port_config` | `447` | `python/envctl_engine/planning.py (+ worktree helper module)` | `tests/python/test_planning_worktree_setup.py; tests/bats/python_planning_worktree_setup_e2e.bats` |
| `resolve_tree_root_for_feature` | `483` | `python/envctl_engine/planning.py (+ worktree helper module)` | `tests/python/test_planning_worktree_setup.py; tests/bats/python_planning_worktree_setup_e2e.bats` |
| `tree_config_signature` | `128` | `python/envctl_engine/planning.py (+ worktree helper module)` | `tests/python/test_planning_worktree_setup.py; tests/bats/python_planning_worktree_setup_e2e.bats` |
| `update_worktree_port_config` | `409` | `python/envctl_engine/planning.py (+ worktree helper module)` | `tests/python/test_planning_worktree_setup.py; tests/bats/python_planning_worktree_setup_e2e.bats` |
| `worktree_cache_enabled` | `16` | `python/envctl_engine/planning.py (+ worktree helper module)` | `tests/python/test_planning_worktree_setup.py; tests/bats/python_planning_worktree_setup_e2e.bats` |
| `worktree_cache_record_ports` | `158` | `python/envctl_engine/planning.py (+ worktree helper module)` | `tests/python/test_planning_worktree_setup.py; tests/bats/python_planning_worktree_setup_e2e.bats` |
| `worktree_cache_record_tree_paths` | `147` | `python/envctl_engine/planning.py (+ worktree helper module)` | `tests/python/test_planning_worktree_setup.py; tests/bats/python_planning_worktree_setup_e2e.bats` |
| `worktree_identity_from_dir` | `301` | `python/envctl_engine/planning.py (+ worktree helper module)` | `tests/python/test_planning_worktree_setup.py; tests/bats/python_planning_worktree_setup_e2e.bats` |
| `worktree_path_mtime` | `100` | `python/envctl_engine/planning.py (+ worktree helper module)` | `tests/python/test_planning_worktree_setup.py; tests/bats/python_planning_worktree_setup_e2e.bats` |
| `worktree_port_cache_enabled` | `23` | `python/envctl_engine/planning.py (+ worktree helper module)` | `tests/python/test_planning_worktree_setup.py; tests/bats/python_planning_worktree_setup_e2e.bats` |
| `worktree_roots_signature` | `117` | `python/envctl_engine/planning.py (+ worktree helper module)` | `tests/python/test_planning_worktree_setup.py; tests/bats/python_planning_worktree_setup_e2e.bats` |

## Appendix H: Detailed Wave Exit Criteria by Module

### Wave 1
- `lib/engine/lib/actions.sh` (21 functions)
  - Exit checks:
    - All module functions moved out of `unmigrated` status in ledger.
    - Module-level parity tests green (unit + relevant BATS).
    - No regression in full Python unit suite and full Python BATS suite.
    - Release gate strict budget passes for wave target threshold.
- `lib/engine/lib/ui.sh` (22 functions)
  - Exit checks:
    - All module functions moved out of `unmigrated` status in ledger.
    - Module-level parity tests green (unit + relevant BATS).
    - No regression in full Python unit suite and full Python BATS suite.
    - Release gate strict budget passes for wave target threshold.
- `lib/engine/lib/analysis.sh` (34 functions)
  - Exit checks:
    - All module functions moved out of `unmigrated` status in ledger.
    - Module-level parity tests green (unit + relevant BATS).
    - No regression in full Python unit suite and full Python BATS suite.
    - Release gate strict budget passes for wave target threshold.
- `lib/engine/lib/pr.sh` (23 functions)
  - Exit checks:
    - All module functions moved out of `unmigrated` status in ledger.
    - Module-level parity tests green (unit + relevant BATS).
    - No regression in full Python unit suite and full Python BATS suite.
    - Release gate strict budget passes for wave target threshold.

### Wave 2
- `lib/engine/lib/planning.sh` (13 functions)
  - Exit checks:
    - All module functions moved out of `unmigrated` status in ledger.
    - Module-level parity tests green (unit + relevant BATS).
    - No regression in full Python unit suite and full Python BATS suite.
    - Release gate strict budget passes for wave target threshold.
- `lib/engine/lib/worktrees.sh` (21 functions)
  - Exit checks:
    - All module functions moved out of `unmigrated` status in ledger.
    - Module-level parity tests green (unit + relevant BATS).
    - No regression in full Python unit suite and full Python BATS suite.
    - Release gate strict budget passes for wave target threshold.
- `lib/engine/lib/run_all_trees_helpers.sh` (44 functions)
  - Exit checks:
    - All module functions moved out of `unmigrated` status in ledger.
    - Module-level parity tests green (unit + relevant BATS).
    - No regression in full Python unit suite and full Python BATS suite.
    - Release gate strict budget passes for wave target threshold.

### Wave 3
- `lib/engine/lib/state.sh` (56 functions)
  - Exit checks:
    - All module functions moved out of `unmigrated` status in ledger.
    - Module-level parity tests green (unit + relevant BATS).
    - No regression in full Python unit suite and full Python BATS suite.
    - Release gate strict budget passes for wave target threshold.
- `lib/engine/lib/ports.sh` (22 functions)
  - Exit checks:
    - All module functions moved out of `unmigrated` status in ledger.
    - Module-level parity tests green (unit + relevant BATS).
    - No regression in full Python unit suite and full Python BATS suite.
    - Release gate strict budget passes for wave target threshold.
- `lib/engine/lib/runtime_map.sh` (3 functions)
  - Exit checks:
    - All module functions moved out of `unmigrated` status in ledger.
    - Module-level parity tests green (unit + relevant BATS).
    - No regression in full Python unit suite and full Python BATS suite.
    - Release gate strict budget passes for wave target threshold.
- `lib/engine/lib/env.sh` (10 functions)
  - Exit checks:
    - All module functions moved out of `unmigrated` status in ledger.
    - Module-level parity tests green (unit + relevant BATS).
    - No regression in full Python unit suite and full Python BATS suite.
    - Release gate strict budget passes for wave target threshold.
- `lib/engine/lib/config.sh` (3 functions)
  - Exit checks:
    - All module functions moved out of `unmigrated` status in ledger.
    - Module-level parity tests green (unit + relevant BATS).
    - No regression in full Python unit suite and full Python BATS suite.
    - Release gate strict budget passes for wave target threshold.
- `lib/engine/lib/git.sh` (4 functions)
  - Exit checks:
    - All module functions moved out of `unmigrated` status in ledger.
    - Module-level parity tests green (unit + relevant BATS).
    - No regression in full Python unit suite and full Python BATS suite.
    - Release gate strict budget passes for wave target threshold.
- `lib/engine/lib/loader.sh` (1 functions)
  - Exit checks:
    - All module functions moved out of `unmigrated` status in ledger.
    - Module-level parity tests green (unit + relevant BATS).
    - No regression in full Python unit suite and full Python BATS suite.
    - Release gate strict budget passes for wave target threshold.

### Wave 4
- `lib/engine/lib/docker.sh` (43 functions)
  - Exit checks:
    - All module functions moved out of `unmigrated` status in ledger.
    - Module-level parity tests green (unit + relevant BATS).
    - No regression in full Python unit suite and full Python BATS suite.
    - Release gate strict budget passes for wave target threshold.

## Non-negotiables
- Read as much relevant code as needed. If you’re unsure, the answer is: read more code.
- Do NOT ask questions unless you are truly blocked by ambiguity that cannot be resolved by reading more code (tests, adjacent modules, docs, config, types).
- Implement the entire feature from top to bottom. No TODOs, no stubs, no “left as an exercise”.
- Use TDD: write/adjust tests first so they fail for the right reason → implement → make tests pass → refactor → ensure everything still passes.
- Run any Python commands via the project venv (no global python).
- Follow best-practice engineering and coding standards for this codebase (correctness, safety, maintainability).
- After changes, append (not overwrite) a detailed summary to docs/changelog/{tree_name}_changelog.md (tree_name from worktree like trees/<feature>/<iter> => <feature>-<iter>, else main). Include: scope, key behavior changes, file paths/modules touched, tests run + results, config/env/migrations, and any risks/notes. Avoid vague one-liners.
- Preserve existing conventions (architecture, naming, patterns, lint rules, formatting, error handling).
- Iterate until requirements are met and tests are green; expect multiple cycles.

## Context-gathering protocol (do this before coding)
1. Open the authoritative spec file and extract explicit requirements and implied constraints.
2. Identify the target file(s)/module(s) affected by the task; locate them in the repo.
3. Find and read ALL call sites and dependencies (imports, interfaces, types, services, configs).
4. Locate existing tests touching this behavior, and read them.
5. Search the repo for related symbols/keywords from the spec; open the most relevant modules.
6. Identify the correct test command(s) and how tests are organized (unit/integration/e2e).
7. Only after you can explain where the change belongs, start writing tests.

## TDD workflow (must follow)
### A) Design the test surface
- Decide the *right level* of tests:
  - Prefer unit tests for pure logic.
  - Prefer integration tests when behavior crosses modules (DB, HTTP, queues, etc.).
  - Use existing patterns in this repo: match style, helpers, fixtures, factories.
- Add tests that cover:
  - Happy path(s)
  - Edge cases from the spec
  - Error handling / validation
  - Backwards-compat behavior (if relevant)
  - Any regression scenario implied by the spec

### B) Write failing tests first
- Implement tests so they fail for the expected reason (not “cannot import module” or unrelated setup failures).
- If tests require fixtures/mocks, build them the same way the repo already does.

### C) Implement to satisfy tests
- Make the minimal changes to pass tests, but ensure correctness and completeness.
- Update types/interfaces/contracts as needed.
- Update config/wiring/DI routes/exports if required.
- If behavior requires new helpers, place them in the repo’s preferred location.

### D) Refactor + harden
- Remove duplication, improve readability, keep public behavior the same.
- Add any missing tests discovered during implementation.
- Run the full relevant test suite and ensure it’s green.

## “No questions unless blocked” rule
- If something is unclear:
  - First: open more code (neighbor modules, docs, existing implementations).
  - Second: infer from conventions and add tests to lock behavior.
  - Only ask a question if multiple interpretations remain AND choosing wrong would break expected behavior AND codebase evidence doesn’t resolve it.

## Deliverables (required)
- All code changes needed across the repo (not just one file).
- Complete tests.
- Any necessary docs/comments (only if this repo expects it).
- Ensure the implementation is actually wired in (exports, routes, registrations, etc.) and not orphaned.
- If any trade-offs or missing tests remain, include a short risk register.

## Final response format
1. Brief summary of what you changed.
2. List of files modified/added.
3. How to run the relevant tests (exact commands).
4. Any notable edge cases covered.
5. Risk register (only if needed): trade-offs or missing tests.

## Self-check (before responding)
- Requirements in the authoritative spec file are fully implemented.
- Tests were written first and are now green.
- No behavior gaps, TODOs, or unwired changes remain.
- Changes follow repo conventions and best practices.
