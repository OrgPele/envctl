# Envctl Python Engine Cutover and Reliability Simplification Plan

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Replace the current Bash-heavy orchestration engine with a Python-first runtime while preserving the `envctl` command surface.
  - Eliminate known failure loops in `--plan` and tree parallel startup: duplicate port claims, incorrect runtime URL projection, partial startups, and unstable resume/restart behavior.
  - Substantially reduce code complexity by moving cross-cutting orchestration concerns (ports, state, retries, runtime map, command routing) into typed Python modules with explicit contracts.
  - Reach a production-ready migration state where Python is default execution and shell is optional fallback for a limited deprecation window.
- Non-goals:
  - Renaming launcher commands (`envctl`) or changing user-facing workflow semantics (`--plan`, `--tree`, `--resume`, interactive controls).
  - Rewriting downstream app repositories (backend/frontend business code).
  - Changing docker-compose topology in target projects beyond what is needed for deterministic port/env wiring.
- Assumptions:
  - Python 3.12 remains available in development environments.
  - Docker is the required infra backend for Postgres/Redis/Supabase/n8n orchestration.
  - Existing config knobs (`ENVCTL_DEFAULT_MODE`, `SUPABASE_*`, `POSTGRES_*`, `REDIS_*`, `N8N_*`, `ENVCTL_PLANNING_DIR`) must remain compatible.
  - Existing `.envctl` declarative setup remains primary; `.envctl.sh` hooks remain temporarily supported during migration.

## Goal (user experience)
A user should be able to run `envctl --plan` repeatedly against multiple existing worktrees and always get a clean deterministic startup: each project starts with unique backend/frontend/db/redis/n8n ports, displayed URLs match actual listeners, resume/restart works without reintroducing collisions, and failures are actionable rather than cascading partial states.

## Business logic and data model mapping
- Launcher and engine boundary:
  - `bin/envctl` -> `lib/envctl.sh` (`envctl_forward_to_engine`) -> `lib/engine/main.sh`.
  - Current behavior always selects shell engine path in `lib/envctl.sh:112-123` and `lib/envctl.sh:159-178`.
- Python bridge and delegation (current):
  - `lib/engine/main.sh:91-115` gates Python execution behind `ENVCTL_ENGINE_PYTHON_V1=true`.
  - Python CLI currently delegates runtime execution to shell via `python/envctl_engine/cli.py:54-77` and `python/envctl_engine/shell_adapter.py:13-20`.
- Shell orchestration ownership today:
  - CLI argument parsing and command shape: `lib/engine/lib/run_all_trees_cli.sh` (`run_all_trees_cli_parse_args`).
  - Tree orchestration and parallel workers: `lib/engine/lib/run_all_trees_helpers.sh` (`run_all_trees_start_tree_projects`, `run_all_trees_start_tree_projects_parallel`, worker fragment merge).
  - Service startup/retry/attach: `lib/engine/lib/services_lifecycle.sh` (`start_project_with_attach`, `start_service_with_retry`).
  - Infra requirements and port derivation: `lib/engine/lib/requirements_core.sh` (`resolve_tree_requirement_ports`, `tree_requirement_ports_for_dir`, `ensure_tree_requirements`) and `lib/engine/lib/requirements_supabase.sh` (`start_tree_supabase`, `start_tree_n8n`, `restart_tree_n8n`).
  - State/load/resume: `lib/engine/lib/state.sh` (`save_state`, `resume_from_state`, `load_state_for_command`, `load_attach_state`).
  - Runtime projection consumed by commands/tests: `lib/engine/lib/runtime_map.sh` (`write_runtime_map`, `load_runtime_map`).
- Python models already available for target state:
  - `python/envctl_engine/models.py`: `PortPlan`, `ServiceRecord`, `RequirementsResult`, `RunState`.
  - `python/envctl_engine/ports.py`: deterministic plan and lock reservations.
  - `python/envctl_engine/state.py`: JSON schema validation and merge semantics.
  - `python/envctl_engine/runtime_map.py`: runtime projection with `port_to_service` and `service_to_actual_port`.

## Current behavior (verified in code)
- Migration depth is still partial:
  - Shell engine footprint is dominant (`lib/engine/**/*.sh` ~26k LOC) vs Python engine (`python/envctl_engine/**/*.py` ~506 LOC).
  - Python mode remains wrapper behavior, not orchestration ownership (`python/envctl_engine/cli.py:54`, `python/envctl_engine/shell_adapter.py:13-20`).
- Known startup instability vectors still live in shell runtime path:
  - App port allocation in parallel path is conditional and can race under concurrent workers (`lib/engine/lib/services_lifecycle.sh:1818-1835`).
  - n8n startup fails hard on compose bind conflicts with no first-class retry orchestration (`lib/engine/lib/requirements_supabase.sh:2350-2353`).
  - Redis tree startup can abort when host port is already occupied by expected container shape mismatch, causing requirements failure and skipped backend start (`lib/engine/lib/requirements_core.sh:1341-1360`, `lib/engine/lib/requirements_core.sh:1464-1506`).
- State/resume safety is inconsistent:
  - `load_state_for_command` performs path/header checks before sourcing (`lib/engine/lib/state.sh:1799-1844`).
  - `resume_from_state` and `load_attach_state` still directly `source` state files without equivalent validation (`lib/engine/lib/state.sh:1727`, `lib/engine/lib/state.sh:1928`).
- Runtime guidance and UX drift remains:
  - Resume hints still print `./utils/run.sh` commands (`lib/engine/lib/state.sh:2098-2111`).
  - Repair tips still mention legacy script paths in command actions (`lib/engine/lib/actions.sh:241`, `lib/engine/lib/actions.sh:258`).
- CLI surface area is broad and currently shell-defined:
  - `run_all_trees_cli.sh` exposes ~150+ flag forms and command permutations, increasing migration complexity and parity risk.
- Existing tests pass but do not yet prove full Python runtime parity:
  - Python tests validate scaffolding contracts (state, ports, retry helpers, projection).
  - BATS suite validates shell behavior + bridge checks, not full Python orchestration ownership.

## Root cause(s) / gaps
- Architectural gap:
  - The migration currently introduces Python contracts but leaves the core orchestration control flow in shell.
  - Result: primary defect surface (parallel startup, infra retries, resume projection) remains in the legacy engine.
- Data ownership gap:
  - Shell runtime mutates `services`, `service_info`, `service_ports`, and `actual_ports` across many modules; no single authoritative typed state pipeline.
  - Runtime URL projection can drift from actual port listeners when retries/rebinds happen across multiple code paths.
- Retry policy gap:
  - Retry behavior is implemented asymmetrically across infra components (Supabase DB vs n8n vs Redis), causing partial-start outcomes.
- Safety gap:
  - Sourced shell state remains an execution risk and can diverge from validated command load behavior.
- Operational complexity gap:
  - Command routing and lifecycle actions are spread across shell modules with dense branching and duplicated compatibility hints.

## Plan
### 1) Define migration scope contract and parity matrix before further implementation
- Create a command parity table for all high-value commands and modes:
  - Modes: `main`, `trees`, `--plan`, `--resume`, interactive loop.
  - Commands: `stop`, `stop-all`, `blast-all`, `restart`, `test`, `logs`, `health`, `errors`, `dashboard`, `doctor`, `delete-worktree`, `pr`, `commit`, `analyze`, `migrate`.
- Source of truth for parity behavior:
  - `lib/engine/main.sh`, `lib/engine/lib/run_all_trees_cli.sh`, `lib/engine/lib/actions.sh`, `lib/engine/lib/services_lifecycle.sh`, `lib/engine/lib/requirements_*.sh`, `lib/engine/lib/state.sh`.
- Deliverable:
  - Machine-readable parity manifest (`docs/planning` companion table or JSON artifact in repo) mapping each command/flag path to ownership status (`shell_only`, `python_partial`, `python_complete`).

### 2) Establish Python orchestration kernel (real runtime, no shell delegation)
- Replace `run_legacy_engine` default path in `python/envctl_engine/cli.py` with Python-native dispatcher.
- Add Python modules:
  - `python/envctl_engine/command_router.py`: parse + route command families.
  - `python/envctl_engine/process_runner.py`: subprocess start/stop/retry/health with explicit timeout semantics.
  - `python/envctl_engine/config.py`: typed config parsing from env + `.envctl` with precedence matching docs.
- Keep shell fallback behind explicit opt-in feature gate during transition (not default behavior once parity achieved).

### 3) Port deterministic port lifecycle end-to-end
- Consolidate all app + requirements port assignment into Python planner domain:
  - backend/frontend/db/redis/n8n requested, reserved, assigned, final.
  - reservation owner metadata to prevent sibling-worker collisions.
- Port source behavior from:
  - `reserve_port` / reservation locks in `lib/engine/lib/ports.sh`.
  - tree requirement derivation in `lib/engine/lib/requirements_core.sh`.
  - frontend offset adjustment flow in `lib/engine/lib/services_lifecycle.sh`.
- Explicitly model edge cases:
  - existing container owns desired host port -> attach to existing mapping (no false failure).
  - bind conflict on startup -> reserve next available and persist final.
  - frontend rebinding by Vite (`9000 -> 9001/9002`) must update runtime projection + displayed URLs.

### 4) Port requirements orchestrator with unified retry classification
- Implement Python requirements modules with common retry contract and structured outcomes:
  - Postgres, Redis, Supabase DB/auth/gateway, n8n.
- Add Supabase auth reliability contract to prevent `/auth/v1/signup` 500 regressions:
  - enforce per-implementation Docker network isolation (no static shared network name across trees),
  - enforce GoTrue auth namespace/search-path config (`GOTRUE_DB_DATABASE_URL` with `search_path=auth,public`, `GOTRUE_DB_NAMESPACE=auth`, `DB_NAMESPACE=auth`),
  - enforce auth bootstrap SQL presence/mount (`CREATE SCHEMA IF NOT EXISTS auth`, role search_path to `auth, public`),
  - enforce repo-root-safe mounts for `kong.yml` and SQL bootstrap files.
- Add Supabase config fingerprint + reinit policy:
  - when Supabase compose/auth bootstrap contract changes, require or automate:
    - `docker compose ... down -v`,
    - `docker compose ... up -d supabase-db`,
    - health wait,
    - `docker compose ... up -d supabase-auth supabase-kong`.
  - fail fast with actionable remediation if stale volumes would preserve invalid auth state.
- Define failure classes:
  - `bind_conflict_retryable`, `transient_probe_timeout_retryable`, `bootstrap_soft_failure`, `hard_start_failure`.
- Port and simplify shell logic currently distributed across:
  - `start_tree_postgres`, `start_tree_redis`, `ensure_tree_requirements` (`requirements_core.sh`).
  - `start_tree_supabase`, `start_tree_n8n`, `restart_tree_n8n` (`requirements_supabase.sh`).
- n8n-specific policy:
  - port bind/start failure blocks app startup for that project.
  - owner bootstrap endpoint mismatch (e.g., setup/login 404) is soft-fail warning unless strict mode is enabled.

### 5) Port service lifecycle and attach/resume semantics
- Implement Python service manager for backend/frontend start/restart/attach.
- Preserve attach behavior contract while eliminating map mutation ambiguity:
  - backend attach before frontend start.
  - frontend backend URL projection always uses backend final port.
- Port from:
  - `start_service_with_retry`, `attach_running_service`, `start_project_with_attach`, listener checks from `services_lifecycle.sh`.

### 6) Replace shell state sourcing with validated JSON state authority
- Make Python `RunState` JSON the canonical state format for runtime + resume.
- Add compatibility loader for legacy shell state files during transition; remove `source` execution from steady-state paths.
- Port behavior from:
  - `save_state`, `resume_from_state`, `load_state_for_command`, `load_attach_state`, project filtering in `state.sh`.
- Ensure state projections include:
  - per-service requested/final port, pid, cwd, health, logs path.
  - per-project requirements outcome and failure reasons.

### 7) Rebuild runtime map and displayed URL projection from canonical state
- Make runtime map generated exclusively from canonical `RunState` + final ports.
- Port projection responsibilities:
  - `write_runtime_map` / `load_runtime_map` in shell runtime map.
  - frontend env projection behavior currently in `python/envctl_engine/services.py` + shell startup paths.
- Ensure all displayed endpoints in interactive mode and logs commands reflect actual listener ports after retries.

### 8) Migrate command workflows incrementally with hard parity gates
- Gate A (must pass before moving on):
  - Python owns `--help`, parse/validation, mode resolution, dry command listing.
- Gate B:
  - Python owns `main` startup + stop/restart + state save/resume.
- Gate C:
  - Python owns `trees` + `--plan` startup orchestration and requirement provisioning.
- Gate D:
  - Python owns interactive loop command handling and log/health/errors projection.
- Gate E:
  - Default path is Python runtime; shell path only via explicit fallback flag for one release window.

### 9) Simplify and decompose shell code aggressively once Python ownership lands
- Remove dead and duplicate shell code paths by module family.
- Keep launcher (`lib/envctl.sh`) thin and engine-agnostic.
- Remove stale legacy command hints and script references from shell and docs.
- Reduce shell engine to compatibility adapter only (or remove entirely when deprecation window closes).

### 10) Documentation and developer ergonomics
- Update docs for Python-first internals:
  - architecture, troubleshooting, important flags, configuration, contributing.
- Add a dedicated migration operations doc with rollback steps and known failure signatures.
- Clarify `.envctl` vs `.env` roles and transition behavior for `.envctl.sh` hooks.

## Tests (add these)
### Backend tests
- Add/extend Python unit tests:
  - `/Users/kfiramar/projects/envctl/tests/python/test_cli_router.py`
    - command parsing parity for `--tree/--trees/trees=true`, mode defaults, invalid alias rejection.
  - `/Users/kfiramar/projects/envctl/tests/python/test_service_manager.py`
    - backend/frontend retry and final-port propagation.
  - `/Users/kfiramar/projects/envctl/tests/python/test_requirements_orchestrator.py`
    - uniform retry class handling across Postgres/Redis/Supabase/n8n.
  - `/Users/kfiramar/projects/envctl/tests/python/test_state_roundtrip.py`
    - save/load compatibility across multiple runs and merge behavior.
- Extend existing tests:
  - `/Users/kfiramar/projects/envctl/tests/python/test_port_plan.py`
  - `/Users/kfiramar/projects/envctl/tests/python/test_state_loader.py`
  - `/Users/kfiramar/projects/envctl/tests/python/test_requirements_retry.py`
  - `/Users/kfiramar/projects/envctl/tests/python/test_command_exit_codes.py`

### Frontend tests
- Add `/Users/kfiramar/projects/envctl/tests/python/test_runtime_projection_urls.py`
  - verify displayed frontend/backend URLs always match final listener ports after rebound/retry.
- Extend `/Users/kfiramar/projects/envctl/tests/python/test_frontend_projection.py`
  - include multi-project collisions and offset-adjusted scenarios.

### Integration/E2E tests
- Add Python-mode BATS coverage for real orchestration paths:
  - `/Users/kfiramar/projects/envctl/tests/bats/python_plan_parallel_ports_e2e.bats`
    - `envctl --plan` with 3 existing worktrees, asserts unique backend/frontend/db/redis/n8n ports.
  - `/Users/kfiramar/projects/envctl/tests/bats/python_resume_projection_e2e.bats`
    - run/resume/restart cycle asserts runtime map and printed URLs are consistent.
  - `/Users/kfiramar/projects/envctl/tests/bats/python_requirements_conflict_recovery.bats`
    - forced bind conflicts for db/redis/n8n produce retries and non-colliding final ports.
- Extend existing BATS suites:
  - `/Users/kfiramar/projects/envctl/tests/bats/services_lifecycle_ports.bats`
  - `/Users/kfiramar/projects/envctl/tests/bats/run_all_trees_helpers_ports.bats`
  - `/Users/kfiramar/projects/envctl/tests/bats/requirements_flags.bats`
  - `/Users/kfiramar/projects/envctl/tests/bats/python_engine_parity.bats`
  - `/Users/kfiramar/projects/envctl/tests/bats/parallel_trees_python_e2e.bats`

## Observability / logging (if relevant)
- Emit structured events in Python engine:
  - `engine.mode.selected`, `port.reserved`, `port.rebound`, `requirements.start`, `requirements.retry`, `service.start`, `service.attach`, `state.save`, `state.resume`, `runtime_map.write`.
- Persist run artifacts in runtime dir:
  - `run_state.json`, `runtime_map.json`, `ports_manifest.json`, `error_report.json`.
- Maintain human-readable console output with stable summaries:
  - per-project requested vs final port table.
  - explicit warning class for soft-fail steps (n8n owner bootstrap, stale attach metadata).

## Rollout / verification
- Stepwise rollout:
  - Enable Python runtime in CI smoke jobs first.
  - Enable Python runtime for local dogfooding with fallback toggle.
  - Promote Python runtime to default after parity gates pass for two consecutive release cycles.
- Verification checklist:
  - `envctl --plan` with 3+ trees produces unique app/infra ports and no partial setup loops.
  - `envctl --resume` never shows stale URLs after port rebound.
  - `stop-all`/`blast-all` cleanly handle mixed running and stale containers.
  - Runtime map accurately reflects process listeners and container host-port mappings.
  - No user-facing outputs reference `./utils/run.sh`.

## Definition of done
- Python runtime is default and executes orchestration without delegating to shell for core flows (`main`, `trees`, `--plan`, `--resume`, interactive command loop).
- Port lifecycle is deterministic and collision-safe in parallel tree startup.
- State authority is JSON + validated loaders; shell state sourcing removed from active paths.
- Existing high-value command workflows reach parity with shell behavior.
- Shell fallback (if still present) is explicitly opt-in and scheduled for deprecation/removal.
- Regression coverage exists for all previously observed loop/failure classes.

## Risk register (trade-offs or missing tests)
- Risk: Broad command surface migration introduces parity drift.
  - Mitigation: command parity matrix + staged gate enforcement before default cutover.
- Risk: Mixed shell/Python runtime period increases operational complexity.
  - Mitigation: explicit ownership boundaries and strict deprecation timeline.
- Risk: Docker/container behavior differences across host OS may alter readiness timing.
  - Mitigation: platform-aware timeout/retry policy and CI coverage on Linux/macOS.
- Risk: `.envctl.sh` hook behavior may be relied on by existing repos in undocumented ways.
  - Mitigation: compatibility adapter + explicit migration guidance + hook integration tests.
