# Envctl Python Engine Full Gap-Closure and Cutover Plan

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Close every currently verified Python-engine parity gap and make Python runtime truly production-capable as the default execution path.
  - Replace shell-owned orchestration logic (planning, startup, requirements, service lifecycle, state, projection, command actions) with Python-owned logic while preserving existing `envctl` UX and command surface.
  - Eliminate current loop/failure classes seen in multi-tree `--plan` runs: duplicate/bad ports, partial requirements startup, stale/incorrect projection URLs, and non-deterministic resume/restart.
  - Reduce complexity and defect risk by moving from mutable shell globals to typed Python state models and explicit lifecycle contracts.
- Non-goals:
  - Rewriting downstream app code inside external repositories (backend/frontend business logic).
  - Introducing a new CLI name or changing user workflow semantics (`envctl`, `--plan`, `--tree`, `--resume`, interactive commands).
  - Keeping shell as permanent orchestration authority.
- Assumptions:
  - Python 3.12 is required for Python runtime path.
  - Docker remains the requirements backend for Postgres/Redis/Supabase/n8n orchestration.
  - Existing env toggles and config precedence must remain compatible (`env > .envctl/.envctl.sh > defaults`) unless explicitly deprecated.
  - Migration remains staged with an explicit fallback switch until all parity gates are green.

## Goal (user experience)
Running `envctl --plan`, `envctl --tree`, `envctl --resume`, and interactive commands should be deterministic and reliable: each project/worktree gets non-conflicting ports, displayed URLs always match real listeners, requirements are started with uniform retry behavior, and stop/restart/resume actions do exactly what users expect without partial or misleading success states.

## Business logic and data model mapping
- Launcher and runtime handoff:
  - `bin/envctl` -> `lib/envctl.sh:envctl_main` -> `lib/envctl.sh:envctl_forward_to_engine` -> `lib/engine/main.sh`.
  - Python default enablement currently happens in:
    - `lib/envctl.sh:173-179`
    - `lib/engine/main.sh:119-124`
- Current shell ownership (actual behavior authority):
  - CLI parse and command flags: `lib/engine/lib/run_all_trees_cli.sh:run_all_trees_cli_parse_args`
  - Plan/tree orchestration: `lib/engine/lib/run_all_trees_helpers.sh` (`start_tree_job_with_offset`, `run_all_trees_start_tree_projects`, parallel worker merge)
  - Service lifecycle: `lib/engine/lib/services_lifecycle.sh` (`start_service`, `start_service_with_retry`, `start_project_with_attach`)
  - Requirements lifecycle: `lib/engine/lib/requirements_core.sh` and `lib/engine/lib/requirements_supabase.sh`
  - State/resume: `lib/engine/lib/state.sh` (`save_state`, `resume_from_state`, `load_state_for_command`, `load_attach_state`)
  - Runtime projection: `lib/engine/lib/runtime_map.sh`
- Current Python modules and intended ownership:
  - Parsing/routing: `python/envctl_engine/command_router.py`
  - Runtime dispatch: `python/envctl_engine/engine_runtime.py`
  - Config model: `python/envctl_engine/config.py`
  - Port plans/reservations: `python/envctl_engine/ports.py`
  - Requirements retry classifier/orchestrator: `python/envctl_engine/requirements_orchestrator.py`
  - Service lifecycle manager: `python/envctl_engine/service_manager.py`
  - State model/serialization: `python/envctl_engine/state.py`
  - Projection map: `python/envctl_engine/runtime_map.py`
  - Shell fallback adapter: `python/envctl_engine/shell_adapter.py`
- Data model parity target:
  - Replace shell globals (`services`, `service_info`, `service_ports`, `actual_ports`, requirement maps) with canonical `RunState` + typed nested records.
  - Keep explicit and separate maps for:
    - requested/assigned/final ports
    - service -> actual port
    - port -> service
    - requirements per project with structured failure classes

## Current behavior (verified in code)
- Planning documentation baseline:
  - `docs/planning/README.md` is missing in current repo; quality baseline comes from existing plans:
    - `docs/planning/refactoring/envctl-engine-simplification-and-reliability-refactor.md`
    - `docs/planning/refactoring/envctl-python-engine-cutover-reliability-plan.md`
- Python is defaulted before true parity:
  - `lib/envctl.sh:173-179`
  - `lib/engine/main.sh:119-124`
- Python command dispatch has partial coverage and fallback-to-start behavior:
  - `python/envctl_engine/engine_runtime.py:54-79`
  - Non-migrated commands route through `_start`.
- CLI alias parity is incomplete:
  - `python/envctl_engine/command_router.py:15-45` supports `doctor`/`dashboard` (bare token), but not dashed forms parity (`--doctor`, `--dashboard`) defined in shell parser at `lib/engine/lib/run_all_trees_cli.sh:282-293`.
- Python `--plan` does not execute planning/worktree selection pipeline:
  - `python/envctl_engine/engine_runtime.py:_start` directly discovers projects and starts stack.
  - `ENVCTL_PLANNING_DIR` is loaded (`python/envctl_engine/config.py:71`) but unused by runtime.
- Tree discovery shape mismatch:
  - `python/envctl_engine/engine_runtime.py:159-163` discovers first-level `trees/*` only, not nested `trees/<feature>/<iter>`.
- Service cwd projection mismatch:
  - `python/envctl_engine/engine_runtime.py:298-299` uses `<tree_root>/backend` and `<tree_root>/frontend`; this is wrong for nested iteration layout.
- Requirements execution is simulated, not real:
  - `python/envctl_engine/engine_runtime.py:234-240` returns synthetic bind conflict/success based on env counters.
  - `python/envctl_engine/engine_runtime.py:264-281` backend/frontend starts return process IDs from current process, not spawned app services.
- Stop actions do not stop real processes/containers:
  - `python/envctl_engine/engine_runtime.py:69-72`, `386-394` only remove artifact files.
- Resume semantics are partial:
  - `python/envctl_engine/engine_runtime.py:131-147` rewrites runtime map and prints URLs; no reconciliation/restart of missing services.
- Legacy state compatibility mismatch:
  - Shell save format uses `export` plus `declare -a/-A` (`lib/engine/lib/state.sh:1999-2043`).
  - Python legacy loader expects `SERVICE_*_FIELD` flat assignments (`python/envctl_engine/state.py:67-75`), so real shell state is not decoded correctly.
- Legacy state path mismatch:
  - Python checks only `runtime_root/run_state.state` (`python/envctl_engine/engine_runtime.py:363-365`), while shell pointers/state path logic uses pointer files under runtime pointer dirs (`lib/engine/lib/state.sh:2061+`).
- `.envctl.sh` compatibility is limited to key/value parsing in Python:
  - `python/envctl_engine/config.py:115-127`
  - Shell hook behavior exists in:
    - `lib/engine/lib/config_loader.sh:90-93` (source)
    - `lib/engine/lib/run_all_trees_helpers.sh:1034-1037` (`envctl_setup_infrastructure`)
    - `lib/engine/lib/run_all_trees_helpers.sh:2027-2030` (`envctl_define_services`)
- Port reservation lifecycle gaps in Python:
  - `python/envctl_engine/ports.py` lock files do not reclaim stale locks and do not probe real host port occupancy.
  - `engine_runtime._clear_runtime_state` does not release lock files.
- Run artifact lifecycle gaps:
  - Artifacts are single-file overwritten under `${runtime}/python-engine` (`run_state.json`, `runtime_map.json`, `events.jsonl`) without run-scoped archival, unlike shell run dirs.
- Toggle parity gaps:
  - Python runtime does not use `POSTGRES_MAIN_ENABLE`, `REDIS_ENABLE`, `REDIS_MAIN_ENABLE`, `SUPABASE_MAIN_ENABLE`, `N8N_ENABLE`, `N8N_MAIN_ENABLE` in startup flow decisions.
- Supabase parity gap:
  - `RequirementsResult.supabase` is always empty from Python runtime path.
- Operational docs overstate migration completeness relative to command parity manifest:
  - `docs/planning/python_engine_parity_manifest.json` still marks many commands `python_partial`.

## Root cause(s) / gaps
1. Cutover ordering problem:
   Python runtime was default-enabled before command and orchestration parity were completed.
2. Routing completeness gap:
   Command router lacks full flag alias parity and has fallback-to-start behavior for non-migrated commands.
3. Planning pipeline gap:
   Python `--plan` does not perform planning file discovery/selection/worktree setup semantics.
4. Topology model gap:
   Project discovery and cwd derivation assume flat tree layout; real nested iteration topology is not modeled.
5. Requirements execution gap:
   Python path does not start Docker requirements; it only simulates outcomes.
6. Service execution gap:
   Python path does not spawn/manage real backend/frontend processes with real listener verification.
7. Lifecycle action gap:
   `stop`, `stop-all`, `blast-all`, `restart`, `resume` in Python path are not behaviorally equivalent to shell semantics.
8. State-format compatibility gap:
   Python legacy loader does not parse actual shell state format and ignores shell pointer model.
9. Hook compatibility gap:
   `.envctl.sh` function hooks are not executed in Python mode.
10. Config usage gap:
    Config keys are loaded but many are unused in runtime decisions.
11. Port allocation correctness gap:
    Lock-file reservation in Python is not tied to host port availability and lacks stale lock reclamation/release lifecycle.
12. Observability/actionability gap:
    Python runtime reports successful summaries without proving underlying process/container readiness.
13. Artifact durability gap:
    Single-file artifact overwrite model loses run history and complicates diagnosis.
14. Test realism gap:
    Most Python tests validate models/synthetic flows rather than real docker/process orchestration parity.
15. Documentation parity gap:
    Docs and migration messaging imply stronger parity than code currently provides.
16. Unused/dead module gap:
    `process_runner.py` and requirement wrappers are minimally integrated in runtime control flow.
17. Interactive parity gap:
    Python runtime does not implement shell interactive command loop behavior.
18. Environment constraints gap:
    `check_prereqs` is broad and unconditional for many commands that could be non-runtime operations.
19. URL projection trust gap:
    Projection correctness relies on synthetic assignments, not observed listener state for real processes.
20. Multi-repo usability gap:
    Missing full parity undermines goal of stable concurrent worktree orchestration across repositories.

## Plan
### 1) Freeze cutover risk and define strict parity gates
- Keep Python runtime available, but gate default enablement behind a temporary release flag until Gate C passes.
- Implement a machine-checked parity manifest with statuses per command+mode and enforce in CI.
- Commands blocked from Python ownership must explicitly route to shell fallback, not silent `_start`.
- Files:
  - `lib/envctl.sh`
  - `lib/engine/main.sh`
  - `python/envctl_engine/cli.py`
  - `python/envctl_engine/command_router.py`
  - `python/envctl_engine/engine_runtime.py`
  - `docs/planning/python_engine_parity_manifest.json`

### 2) Complete command router parity before runtime changes
- Add all shell-equivalent aliases and flags:
  - `--doctor`, `--dashboard`, `--logs`, `--health`, `--errors`, `--test`, `--pr`, `--commit`, `--analyze`, `--migrate`, plus existing forms.
- Remove implicit fallback-to-start for unsupported commands; emit explicit unsupported-in-python error with optional fallback hint.
- Use shell parser behavior in `run_all_trees_cli.sh` as parity baseline.
- Files:
  - `python/envctl_engine/command_router.py`
  - new tests: `tests/python/test_cli_router_parity.py`
  - extend `tests/python/test_cli_router.py`

### 3) Rebuild Python `--plan` as true planning workflow
- Implement planning file discovery from `ENVCTL_PLANNING_DIR`.
- Reproduce plan-selection/worktree-reuse/worktree-creation semantics from shell planning helpers.
- Support nested topology `trees/<feature>/<iter>` and deterministic naming.
- Wire plan-derived project list into startup orchestration.
- Files:
  - new `python/envctl_engine/planning.py`
  - `python/envctl_engine/engine_runtime.py`
  - `python/envctl_engine/config.py`
  - BATS parity tests for planning selection and existing worktree reuse.

### 4) Replace synthetic requirements with real orchestrator
- Use `ProcessRunner` as mandatory execution backend for docker operations.
- Port `requirements_core.sh` and `requirements_supabase.sh` behavior into Python modules:
  - postgres, redis, supabase db/auth/gateway, n8n
  - attach-existing-container behavior
  - bind-conflict retry with reserved-next-port policy
  - strict/soft n8n owner bootstrap policy
- Populate `RequirementsResult.supabase` and structured failure classes.
- Files:
  - `python/envctl_engine/requirements_orchestrator.py`
  - `python/envctl_engine/requirements/*.py`
  - `python/envctl_engine/process_runner.py`
  - `python/envctl_engine/engine_runtime.py`

### 5) Replace synthetic service startup with real process lifecycle manager
- Spawn backend/frontend with command resolution parity.
- Add listener detection by PID/process-tree and map requested->actual ports from real sockets.
- Persist log paths and process metadata in state.
- Implement robust retry/backoff policies and non-bind failure handling.
- Files:
  - `python/envctl_engine/service_manager.py`
  - `python/envctl_engine/process_runner.py`
  - `python/envctl_engine/engine_runtime.py`
  - `python/envctl_engine/runtime_map.py`

### 6) Implement state/pointer compatibility and safe resume/restart
- Add loader for shell pointer files and shell state declarations.
- Parse `declare -a/-A` shell state format safely (no sourcing) for migration compatibility.
- Resume behavior:
  - detect missing services
  - restart only missing targets by project/service type
  - keep existing healthy services attached
- Restart behavior:
  - preserve project selection and mode
  - reconcile state with real listeners.
- Files:
  - `python/envctl_engine/state.py`
  - new `python/envctl_engine/resume.py`
  - `python/envctl_engine/engine_runtime.py`
  - extend state-focused tests.

### 7) Implement full stop/stop-all/blast-all parity
- `stop`/`stop-all`: terminate managed app processes gracefully, preserve infra based on flags, sync state.
- `blast-all`: include process hunt, ports, containers, and optional volume removal parity with shell.
- Ensure these commands are idempotent and safe under partial state.
- Files:
  - `python/envctl_engine/engine_runtime.py`
  - new `python/envctl_engine/cleanup.py`
  - BATS e2e parity tests.

### 8) Port config and hook compatibility with explicit contract
- Support `.envctl` declarative config as primary path.
- For `.envctl.sh`:
  - either implement controlled hook execution parity (`envctl_setup_infrastructure`, `envctl_define_services`) via shell subprocess adapter
  - or formally deprecate with migration warnings and documented alternative.
- Enforce same precedence and validation behavior as shell path.
- Files:
  - `python/envctl_engine/config.py`
  - new `python/envctl_engine/hooks.py`
  - docs updates in configuration/troubleshooting.

### 9) Fix port planner correctness and lifecycle
- Reserve ports only if lock acquired and port is truly free or explicitly attached to known managed container.
- Add stale lock reclamation and per-run lock namespace/session ownership.
- Release reservations on stop, failure, and process exit.
- Persist requested/assigned/final source metadata for all services and requirements.
- Files:
  - `python/envctl_engine/ports.py`
  - `python/envctl_engine/engine_runtime.py`
  - tests for stale lock and host-occupancy behavior.

### 10) Implement interactive and command action parity
- Port interactive loop command family (`restart`, `test`, `pr`, `commit`, `analyze`, `migrate`, `logs`, `health`, `errors`) with consistent target selectors and output projection.
- Keep action execution adapters minimal and explicit, with command-level exit contracts.
- Files:
  - new `python/envctl_engine/interactive.py`
  - `python/envctl_engine/engine_runtime.py`
  - command action tests (python + bats).

### 11) Harden observability and run artifact model
- Write artifacts to run-scoped directories:
  - `${runtime}/runs/<run_id>/...`
  - `${runtime}/states/...` pointer compatibility
- Emit structured events with lifecycle correlation IDs.
- Generate deterministic error reports with failure class, command, project, service, retry count, and actionable remediation hints.
- Files:
  - `python/envctl_engine/engine_runtime.py`
  - `python/envctl_engine/state.py`
  - docs and troubleshooting updates.

### 12) Remove/retire shell orchestration in controlled phases
- Phase A: Python parity for `main` lifecycle complete.
- Phase B: Python parity for `trees` + `--plan` complete.
- Phase C: action command + interactive parity complete.
- Phase D: shell fallback opt-in only with deprecation warning window.
- Phase E: remove dead shell orchestration modules or freeze as legacy plugin.
- Exit criteria:
  - all parity tests green
  - no `python_partial` entries in parity manifest for supported command set.

## Tests (add these)
- Backend tests
  - Add `tests/python/test_engine_runtime_command_parity.py`:
    - verifies router+dispatcher mapping for all commands and dashed aliases.
  - Add `tests/python/test_engine_runtime_real_startup.py`:
    - validates requirements/service startup path uses `ProcessRunner` not synthetic lambdas.
  - Add `tests/python/test_state_shell_compatibility.py`:
    - parses shell `declare -a/-A` state fixtures and pointer files.
  - Add `tests/python/test_ports_lock_reclamation.py`:
    - stale lock reclamation, true host occupancy checks, per-session release.
  - Extend:
    - `tests/python/test_cli_router.py`
    - `tests/python/test_service_manager.py`
    - `tests/python/test_requirements_orchestrator.py`
    - `tests/python/test_state_roundtrip.py`
    - `tests/python/test_runtime_projection_urls.py`
    - `tests/python/test_command_exit_codes.py`
- Frontend tests
  - Add `tests/python/test_frontend_env_projection_real_ports.py`:
    - ensures frontend backend URL projection follows actual backend listener after retries.
  - Extend `tests/python/test_frontend_projection.py` for multi-project nested tree topology.
- Integration/E2E tests
  - Add `tests/bats/python_plan_nested_worktree_e2e.bats`:
    - validates `trees/<feature>/<iter>` discovery and unique port assignment.
  - Add `tests/bats/python_command_alias_parity_e2e.bats`:
    - validates `--doctor/--dashboard/--logs/...` do not route to startup.
  - Add `tests/bats/python_state_resume_shell_compat_e2e.bats`:
    - resume from shell-generated state pointers + state payload.
  - Add `tests/bats/python_stop_blast_all_parity_e2e.bats`:
    - verifies lifecycle cleanup semantics.
  - Extend existing:
    - `tests/bats/python_engine_parity.bats`
    - `tests/bats/python_plan_parallel_ports_e2e.bats`
    - `tests/bats/python_requirements_conflict_recovery.bats`
    - `tests/bats/python_resume_projection_e2e.bats`
    - `tests/bats/parallel_trees_python_e2e.bats`

## Observability / logging (if relevant)
- Required structured events:
  - `engine.mode.selected`
  - `command.route.selected`
  - `planning.selection.resolved`
  - `project.discovery`
  - `port.reserved`, `port.rebound`, `port.released`
  - `requirements.start`, `requirements.retry`, `requirements.failed`, `requirements.healthy`
  - `service.start`, `service.retry`, `service.bound`, `service.failed`
  - `state.save`, `state.resume`, `state.reconcile`
  - `runtime_map.write`
- Required artifacts per run:
  - `run_state.json`
  - `runtime_map.json`
  - `ports_manifest.json`
  - `error_report.json`
  - `events.jsonl`
  - optional `command_trace.json` for debugging parity failures.

## Rollout / verification
- Verification stage 1 (router/command correctness):
  - All commands map correctly in Python with no silent fallback-to-start.
  - Dashed and bare aliases parity is green.
- Verification stage 2 (planning/topology correctness):
  - `--plan` uses `ENVCTL_PLANNING_DIR` and nested worktree discovery correctly.
  - Existing worktrees reuse behavior is deterministic.
- Verification stage 3 (runtime correctness):
  - Real requirements/services start, health checks pass, URLs match listeners.
  - No partial-success summary when required infra/service is not running.
- Verification stage 4 (lifecycle correctness):
  - `resume`, `restart`, `stop`, `stop-all`, `blast-all` parity e2e passes.
- Verification stage 5 (cutover):
  - parity manifest has no `python_partial` entries for supported surface.
  - Python default enabled without regression over two consecutive release cycles.

## Definition of done
- Python runtime is behaviorally equivalent (or intentionally improved with documented changes) for all supported command flows.
- `--plan` and tree orchestration are fully Python-owned and stable for nested worktree topology.
- Requirements and service startup are real, observable, and deterministic.
- State/resume pipeline is safe, compatible with migration state formats, and pointer-aware.
- No command silently routes to startup when behavior should differ.
- Port reservation system is collision-safe, stale-safe, and release-safe.
- Docs accurately match runtime behavior and parity status.

## Risk register (trade-offs or missing tests)
- Risk: Temporary rollback to shell may mask Python defects if fallback is too easy.
  - Mitigation: CI parity gates must run Python path as required; fallback only for emergency.
- Risk: Implementing `.envctl.sh` hook parity can reintroduce shell execution risks.
  - Mitigation: controlled hook interface; deprecate unsafe patterns; prefer declarative `.envctl`.
- Risk: Docker startup timing differences across macOS/Linux can cause flaky readiness checks.
  - Mitigation: standardized probe/backoff policies and platform-specific timeout tuning.
- Risk: Port lock lifecycle bugs can cause false conflicts or silent collisions.
  - Mitigation: host-port probe + stale lock reclaim + lock release invariants tested in unit + e2e.
- Risk: Large cutover scope can delay delivery.
  - Mitigation: strict phased gates with independently shippable milestones and explicit stop criteria.

## Open questions (only if unavoidable)
- Should `.envctl.sh` hooks be fully supported long-term in Python mode, or deprecated after a defined compatibility window in favor of declarative `.envctl` + explicit plugin hooks?
