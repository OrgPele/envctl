# Envctl Python Engine Final 100% Cutover Plan

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Complete the Python migration so `envctl` is fully reliable and parity-complete without depending on shell orchestration for normal workflows.
  - Eliminate the current mismatch between "Python default enabled" and "Python runtime fully complete."
  - Deliver deterministic behavior for `main`, `trees`, `--plan`, `--resume`, `restart`, `stop`, and interactive command actions with correct runtime projection and cleanup semantics.
  - Reduce total orchestration complexity by making Python the single source of truth for command routing, state, ports, requirements, services, and run artifacts.
- Non-goals:
  - Rewriting downstream application business logic in target repos.
  - Renaming public CLI (`envctl`) or removing existing high-value flags.
  - Keeping shell runtime as a long-term co-primary engine.
- Assumptions:
  - Python 3.12 remains a hard requirement for Python runtime execution (`lib/engine/main.sh:54-96`).
  - Docker remains the infra backend for Postgres/Redis/Supabase/n8n orchestration.
  - Configuration precedence must remain stable: `env` -> `.envctl`/`.envctl.sh` -> defaults (`python/envctl_engine/config.py:54-96`, `docs/configuration.md:5-9`).
  - Existing worktree layouts are mixed and must be supported: flat `trees/<name>` and nested `trees/<feature>/<iter>` (`python/envctl_engine/planning.py:23-45`).

## Goal (user experience)
Users can run `envctl --plan` repeatedly across multiple worktrees and always get a correct, boring outcome: unique app/infra ports per project, real running services, accurate displayed URLs, resumable state that maps to reality, and lifecycle commands (`stop`, `stop-all`, `blast-all`, `restart`, `logs`, `health`, `errors`) that behave consistently without hidden fallback loops or partial failures.

## Business logic and data model mapping
- Launcher and engine selection:
  - `bin/envctl` -> `lib/envctl.sh:envctl_main` -> `lib/envctl.sh:envctl_forward_to_engine` -> `lib/engine/main.sh`.
  - Python default is currently activated via launcher/env handoff (`lib/envctl.sh:173-179`, `lib/engine/main.sh:119-125`).
- Current Python command routing and runtime flow:
  - Route parsing: `python/envctl_engine/command_router.py:109-199` (`parse_route`).
  - Runtime dispatch: `python/envctl_engine/engine_runtime.py:71-105` (`dispatch`).
  - Current unsupported/partial command guardrail: `python/envctl_engine/engine_runtime.py:34-41`, `python/envctl_engine/engine_runtime.py:676-681`.
- Current Python runtime domain modules:
  - Config: `python/envctl_engine/config.py`.
  - Ports and reservations: `python/envctl_engine/ports.py`.
  - Requirements orchestration and classification: `python/envctl_engine/requirements_orchestrator.py`.
  - Service startup/retry/attach model: `python/envctl_engine/service_manager.py`.
  - State load/save/compatibility: `python/envctl_engine/state.py`.
  - Runtime map/projection: `python/envctl_engine/runtime_map.py`.
- Current shell authority that still defines parity baseline:
  - CLI parse and aliases: `lib/engine/lib/run_all_trees_cli.sh` (`run_all_trees_cli_parse_args` at `:174`).
  - Requirements orchestration: `lib/engine/lib/requirements_core.sh` (`resolve_tree_requirement_ports`, `start_tree_postgres`, `start_tree_redis`, `ensure_tree_requirements`).
  - Supabase/n8n orchestration: `lib/engine/lib/requirements_supabase.sh` (`start_tree_supabase`, `start_tree_n8n`, `restart_tree_n8n`).
  - Service lifecycle: `lib/engine/lib/services_lifecycle.sh` (`start_service_with_retry`, `attach_running_service`, `start_project_with_attach`).
  - State/resume/attach/recovery script: `lib/engine/lib/state.sh` (`resume_from_state`, `load_state_for_command`, `load_attach_state`, `create_recovery_script`).
- Target data model authority:
  - Canonical state: `RunState` (`python/envctl_engine/models.py`) serialized by `state_to_dict` (`python/envctl_engine/state.py:134-165`).
  - Canonical port lifecycle: `requested`, `assigned`, `final`, `source`, `retries` on `PortPlan` and `ports_manifest.json` (`python/envctl_engine/engine_runtime.py:505-529`).
  - Canonical URL projection: `runtime_map.json` built from actual service records (`python/envctl_engine/runtime_map.py:9-33`, `:39-53`).

## Current behavior (verified in code)
- Python runtime is default-enabled but not fully parity-complete:
  - `PARTIAL_COMMANDS` remain (`test`, `delete-worktree`, `pr`, `commit`, `analyze`, `migrate`) in `python/envctl_engine/engine_runtime.py:34-41`.
  - Unsupported command text is explicit at `python/envctl_engine/engine_runtime.py:676-681`.
  - Parity manifest still marks these as `python_partial` (`docs/planning/python_engine_parity_manifest.json:30-38`).
- Real startup path still relies on generic command defaults, not repo-specific engine semantics:
  - Requirement defaults use inline Python command stubs (`python/envctl_engine/engine_runtime.py:823-833`).
  - Service defaults use `python -c "time.sleep(1.0)"` (`python/envctl_engine/engine_runtime.py:834-839`).
- `--plan` and multi-project runtime stability are not yet fully green in E2E parity:
  - Full BATS run currently fails 7 tests:
    - `tests/bats/parallel_trees_python_e2e.bats`
    - `tests/bats/python_listener_projection_e2e.bats`
    - `tests/bats/python_plan_nested_worktree_e2e.bats`
    - `tests/bats/python_plan_parallel_ports_e2e.bats`
    - `tests/bats/python_requirements_conflict_recovery.bats`
    - `tests/bats/python_resume_projection_e2e.bats`
    - `tests/bats/python_stop_blast_all_parity_e2e.bats`
- `--plan` can fail at port reservation in restricted environments:
  - Failure observed: `Port reservation failed: no free port found from 8000 to 65000`.
  - Source path: `python/envctl_engine/ports.py:105-114`, socket bind check at `python/envctl_engine/ports.py:254-265`.
- Resume and cleanup are functional but not equivalent to shell lifecycle depth:
  - Resume reconciles stale PIDs and rewrites runtime map (`python/envctl_engine/engine_runtime.py:203-233`) but does not fully replicate shell interactive restart decisions from `lib/engine/lib/state.sh:1752-1785`.
  - `stop`/`blast-all` clear runtime artifacts and kill tracked PIDs (`python/envctl_engine/engine_runtime.py:683-714`) but do not fully match shell ecosystem cleanup breadth in shell action paths.
- Shell state compatibility is improved but legacy behavior still exists in shell paths:
  - Python loader parses `declare -a/-A` format safely (`python/envctl_engine/state.py:229-285`, `:350-406`).
  - Shell runtime still sources state in resume/attach (`lib/engine/lib/state.sh:1727`, `lib/engine/lib/state.sh:1928`).
  - Recovery script still references `utils/run.sh` fallback locations (`lib/engine/lib/state.sh:2208-2217`).
- Planning docs baseline:
  - `docs/planning/README.md` is currently missing; consistency baseline is existing refactoring plans under `docs/planning/refactoring/`.

## Root cause(s) / gaps
- Cutover sequencing gap: Python was made default before all command families and runtime semantics reached parity.
- Command surface gap: parser supports many aliases (`python/envctl_engine/command_router.py`) but runtime intentionally leaves high-value action commands partial.
- Runtime realism gap: default startup command resolution is generic/synthetic and not yet equivalent to shell engine orchestration contracts.
- Port reservation reliability gap: reservation strategy assumes ability to bind candidate host ports and can fail hard in restricted environments.
- Lifecycle parity gap: Python resume/restart/stop/blast behaviors are narrower than shell behavior in edge scenarios and infra cleanup breadth.
- Requirements parity gap: shell has rich Supabase/n8n policy and diagnostics paths that are only partially mirrored by current Python orchestrator behavior.
- Projection confidence gap: URL projection correctness depends on strong actual-port detection and resilient update propagation across retries/rebounds; E2E failures indicate unresolved gaps.
- State safety/compatibility gap: Python path is safer, but shell-source paths still exist and recovery scripts still refer to legacy script names.
- Test gate gap: unit tests are green, but end-to-end parity tests that represent real user workflows are not all green.
- Documentation parity gap: docs state Python-first migration, but current implementation status still includes actionable partials and failing parity gates.

## Plan
### 1) Lock cutover contract and enforce parity truth in code + docs
- Create a strict cutover policy: Python remains default only when parity gates are green; otherwise default stays Python but emits explicit readiness warning in `--doctor` and startup summary.
- Keep `docs/planning/python_engine_parity_manifest.json` as machine-readable source of truth, and add CI enforcement that manifest statuses must match runtime behavior.
- Update `python/envctl_engine/engine_runtime.py` so partial command handling is explicit, deterministic, and tied to manifest validation tests.
- Update docs (`docs/architecture.md`, `docs/troubleshooting.md`, `docs/configuration.md`) to state exact partial/complete command classes until cutover gate is closed.

### 2) Rebuild command runtime parity for all user-facing operational commands
- Implement Python-native handling for currently partial commands:
  - `test`, `delete-worktree`, `pr`, `commit`, `analyze`, `migrate`.
- Move command execution into dedicated Python modules:
  - `python/envctl_engine/actions_test.py`
  - `python/envctl_engine/actions_git.py`
  - `python/envctl_engine/actions_worktree.py`
  - `python/envctl_engine/actions_analysis.py`
- Preserve route aliases and argument patterns already parsed in `python/envctl_engine/command_router.py:15-66`.
- Exit-code contract must remain stable (`0`, `1`, `2`) and be validated in tests.

### 3) Fix port lifecycle for deterministic behavior in both unrestricted and restricted environments
- Refactor `PortPlanner` to support strategy-based availability checks:
  - `socket_bind` strategy for normal hosts.
  - `lsof/netstat` listener query strategy as fallback when bind is disallowed.
  - deterministic "reserved lock only" mode for constrained CI with explicit config flag.
- Add lock ownership metadata validation and stale reclaim safeguards:
  - verify `session`, `pid`, and `created_at` semantics.
  - preserve session isolation on release (`release_session`) and full cleanup (`release_all`).
- Add structured failure classification when reservation fails:
  - `reservation_permission_denied`
  - `reservation_exhausted`
  - `reservation_stale_lock_conflict`.
- Ensure `--plan` never hard-fails silently: emit actionable diagnostics including attempted range and current lock inventory.

### 4) Implement real requirements orchestration parity (Postgres/Redis/Supabase/n8n)
- Replace generic requirement command defaults with explicit adapters that mirror shell behavior:
  - Postgres: container create/attach/restart/wait.
  - Redis: container create/attach/restart/wait.
  - Supabase: DB + auth/gateway startup sequencing and health.
  - n8n: start/restart/bootstrap/owner-reset policy with strict vs soft handling.
- Port critical shell behaviors:
  - bind conflict retry loops and alternate port assignment (`lib/engine/lib/requirements_supabase.sh:1937-1968`).
  - n8n bootstrap endpoint fallback behavior (`lib/engine/lib/requirements_supabase.sh:1330-1344`).
  - redis attach/recreate behavior when expected container owns a different host mapping (`lib/engine/lib/requirements_core.sh:1332-1411`).
- Add real per-project requirement outcomes in `RequirementsResult` with normalized failure classes and retry counts.
- Make supabase status first-class in runtime summary and `runtime_map` metadata.

### 5) Implement real backend/frontend process lifecycle parity
- Replace synthetic service defaults with repo command resolution pipeline:
  - prefer explicit config commands.
  - fallback to deterministic auto-detect (`backend` and `frontend` directory rules).
  - validate executable existence and cwd before start.
- Port `start_service_with_retry` semantics from shell (`lib/engine/lib/services_lifecycle.sh:1211-1320`):
  - bind-error classifier.
  - exponential backoff.
  - next-port reservation and requested/final port distinction.
- Port `start_project_with_attach` behaviors (`lib/engine/lib/services_lifecycle.sh:1746-1959`):
  - attach existing services when valid.
  - maintain backend/frontend offset behavior.
  - persist changed ports back into worktree runtime config.
- Harden actual listener detection for projection:
  - detect final backend/frontend listener ports by PID + listening sockets.
  - write actual ports into service records before runtime map generation.

### 6) Complete `--plan` pipeline parity and planning-dir behavior
- Build Python planning execution equivalent to shell orchestration:
  - discover plans from `ENVCTL_PLANNING_DIR`.
  - resolve selected plans and iteration counts.
  - create/reuse worktrees deterministically.
  - assign stable project names and root paths.
- Ensure nested and flat worktree topologies are supported and deterministic:
  - `trees/<feature>/<iter>` primary.
  - `trees/<project>` compatibility.
- Ensure planning output prints requested/final ports and created/reused worktrees consistently.

### 7) Finish state, resume, restart, and recovery parity
- Keep JSON as canonical state format and continue safe parsing of legacy shell states.
- Remove remaining shell-source resume/attach usage from active migration path and replace with validated loader usage.
- Add resume reconciliation behavior to match shell expectations:
  - identify stale services.
  - prompt/auto-restart policy based on mode and interactivity.
  - do not report healthy when required services are stale or missing.
- Update recovery command generation to use `envctl`-first references (no legacy `utils/run.sh` paths).
- Add explicit compatibility window for loading legacy state pointers and format variants.

### 8) Complete lifecycle parity for `stop`, `stop-all`, and `blast-all`
- Implement cleanup levels:
  - `stop`: current run services only.
  - `stop-all`: all tracked services + optional infra preservation per config.
  - `blast-all`: aggressive process + lock + runtime artifact + optional docker/volume purge (with confirmations/flags).
- Ensure lock and state cleanup are always executed on failure paths.
- Match shell-style idempotency: repeated stop/blast calls succeed without false errors.

### 9) Resolve `.envctl` / `.envctl.sh` compatibility contract
- Preserve `.envctl` as primary declarative config path.
- For `.envctl.sh`, implement one explicit policy and enforce it:
  - Option A: support a constrained hook API in Python (`envctl_setup_infrastructure`, `envctl_define_services`) via subprocess shim.
  - Option B: deprecate `.envctl.sh` execution and provide deterministic migration path.
- Update docs and warnings so behavior is explicit and test-covered.

### 10) Strengthen observability and operator diagnostics
- Expand structured event stream with failure classes and correlation fields:
  - `command.route.selected`
  - `port.lock.acquire/reclaim/release`
  - `requirements.start/retry/failure_class/healthy`
  - `service.start/retry/bind.actual`
  - `state.resume/reconcile`
  - `cleanup.stop/stop-all/blast-all`.
- Ensure each run writes durable run-scoped artifacts under `python-engine/runs/<run_id>/`.
- Add `--doctor` diagnostics for:
  - parity status by command family.
  - latest run failures.
  - lock inventory and stale lock candidates.

### 11) Stabilize CI and release gates for 100% completion
- Gate 1: Python unit tests all green.
- Gate 2: BATS parity and E2E tests all green, including the 7 currently failing suites.
- Gate 3: manifest has no `python_partial` entries for public command set.
- Gate 4: real-world smoke tests in multi-worktree repos confirm deterministic runs, resume correctness, and cleanup correctness.
- Gate 5: shell fallback disabled by default only after two consecutive stable release cycles.

### 12) Retire shell orchestration paths in controlled phases
- Phase A: freeze new features in shell engine modules.
- Phase B: Python owns all primary flows and action commands.
- Phase C: shell fallback remains opt-in escape hatch with deprecation warning.
- Phase D: remove dead shell orchestration code and legacy run.sh guidance, keep only minimal launcher compatibility.

## Tests (add these)
### Backend tests
- Extend `tests/python/test_engine_runtime_command_parity.py`:
  - assert no public command routes to unsupported path in final state.
- Extend `tests/python/test_engine_runtime_real_startup.py`:
  - assert real command resolution and process runner integration for requirements/services.
- Extend `tests/python/test_ports_lock_reclamation.py`:
  - add permission-restricted availability strategy tests and deterministic fallback behavior.
- Add `tests/python/test_ports_availability_strategies.py`:
  - validate `socket_bind`, listener-query fallback, and constrained-ci mode.
- Add `tests/python/test_resume_reconcile_policy.py`:
  - validate stale-service detection and restart policy behavior.
- Add `tests/python/test_actions_parity.py`:
  - validate `test/pr/commit/analyze/migrate/delete-worktree` execution + exit codes.
- Extend `tests/python/test_requirements_orchestrator.py`:
  - verify full failure class mapping and retry behavior parity.

### Frontend tests
- Extend `tests/python/test_runtime_projection_urls.py`:
  - verify projected URLs always match actual listener ports after retries/rebounds/resume.
- Extend `tests/python/test_frontend_projection.py`:
  - verify backend URL injection parity for multi-project/nested-tree runs.

### Integration/E2E tests
- Fix and enforce all currently failing suites:
  - `tests/bats/parallel_trees_python_e2e.bats`
  - `tests/bats/python_listener_projection_e2e.bats`
  - `tests/bats/python_plan_nested_worktree_e2e.bats`
  - `tests/bats/python_plan_parallel_ports_e2e.bats`
  - `tests/bats/python_requirements_conflict_recovery.bats`
  - `tests/bats/python_resume_projection_e2e.bats`
  - `tests/bats/python_stop_blast_all_parity_e2e.bats`
- Add `tests/bats/python_actions_parity_e2e.bats`:
  - validate migrated command families (`test/pr/commit/analyze/migrate/delete-worktree`) in Python mode.
- Add `tests/bats/python_restricted_port_env_e2e.bats`:
  - validate behavior when direct `socket.bind` probing is disallowed.

## Observability / logging (if relevant)
- Required events:
  - `engine.mode.selected`
  - `command.route.selected`
  - `port.lock.acquire`
  - `port.lock.reclaim`
  - `port.lock.release`
  - `port.reservation.failure_class`
  - `requirements.start`
  - `requirements.retry`
  - `requirements.failure_class`
  - `requirements.healthy`
  - `service.start`
  - `service.retry`
  - `service.bind.actual`
  - `state.save`
  - `state.resume`
  - `state.reconcile`
  - `cleanup.stop`
  - `cleanup.stop_all`
  - `cleanup.blast`.
- Required artifacts:
  - `run_state.json`
  - `runtime_map.json`
  - `ports_manifest.json`
  - `error_report.json`
  - `events.jsonl`
  - run pointer files (`.last_state*`) with deterministic precedence.

## Rollout / verification
- Phase 0 (immediate):
  - Merge this plan and treat it as authoritative cutover backlog.
  - Keep shell fallback available.
- Phase 1:
  - Land port lifecycle and requirements/service realism changes.
  - Re-run full Python unit + BATS suites on each change.
- Phase 2:
  - Land action command parity and lifecycle parity (`stop/stop-all/blast-all/restart/resume`).
  - Validate no regression in existing shell-equivalent behavior.
- Phase 3:
  - Close final doc/parity manifest gaps.
  - Run multi-repo smoke validation with nested worktrees and repeated `--plan` cycles.
- Phase 4:
  - Remove `python_partial` command statuses.
  - Keep shell fallback opt-in only for one stabilization window, then retire.

## Definition of done
- Python runtime executes all public command families with no `python_partial` statuses in `docs/planning/python_engine_parity_manifest.json`.
- `envctl --plan` passes all parity/e2e tests and is deterministic for nested and flat worktree topologies.
- Runtime map URLs always match actual listeners across startup, retries, resume, and restart.
- Lifecycle commands (`stop`, `stop-all`, `blast-all`) are idempotent, complete, and parity-tested.
- Canonical state is safe, validated, and compatible during migration window without shell `source` in active Python path.
- Shell fallback is no longer required for normal operation.

## Risk register (trade-offs or missing tests)
- Risk: Port probing strategies can diverge between local hosts and constrained CI/sandbox environments.
  - Mitigation: strategy abstraction, explicit failure classes, and dedicated restricted-env tests.
- Risk: Full action-command parity (`pr`, `commit`, `migrate`) can introduce side effects if implemented without guardrails.
  - Mitigation: dry-run/confirmation options and strict exit-code contracts with e2e coverage.
- Risk: `.envctl.sh` compatibility may preserve unsafe or undocumented behavior.
  - Mitigation: choose and enforce one explicit compatibility/deprecation policy with migration docs and tests.
- Risk: Supabase/n8n orchestration parity can regress under concurrent tree startup.
  - Mitigation: conflict-recovery e2e suites and lock-aware retry policies.
- Risk: Documentation may drift from runtime readiness again.
  - Mitigation: CI check that `parity_manifest` status aligns with runtime command behavior and docs release checklist.

## Open questions (only if unavoidable)
- Should `.envctl.sh` execution remain supported in Python mode through constrained hooks, or be formally deprecated in favor of declarative `.envctl` plus explicit Python plugins?
