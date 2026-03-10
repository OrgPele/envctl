# Startup, Resume, and Timing Deep Dive

This document explains the Python runtime startup system end to end.

It is intentionally code-oriented and is meant to be read alongside the implementation, not instead of it.

## Scope

This guide covers the full operational path for:

- `start`
- `plan`
- `restart`
- `resume`
- per-project requirements startup
- per-project service bootstrap and attach
- startup and restore timing/progress output
- state persistence and runtime-map generation
- hook-based startup overrides

This guide is centered on the code paths that are actually involved in startup and resume today.

It does not attempt to fully document unrelated action-command internals, dashboard rendering internals, or cleanup internals beyond the points where they intersect startup/resume.

## Top-Level Execution Model

The active control path for startup-related commands is:

1. `bin/envctl`
2. `envctl_engine.runtime.launcher_cli`
3. `envctl_engine.runtime.cli:main`
4. `envctl_engine.runtime.command_router.parse_route`
5. `envctl_engine.runtime.engine_runtime.PythonEngineRuntime`
6. `runtime_dispatch_command(...)`
7. `StartupOrchestrator.execute(...)` or `ResumeOrchestrator.execute(...)`

The runtime is intentionally split into:

- command parsing and route normalization
- runtime facade and dependency wiring
- startup orchestration
- resume orchestration
- requirement startup
- service bootstrap/attach
- state persistence and projection

That split matters because performance problems and correctness problems usually belong to different layers.

## Modes and Commands

There are two operational modes:

- `main`
- `trees`

Startup commands operate differently depending on both command and mode:

- `start`:
  Starts currently selected projects for the current mode.
- `plan`:
  Forces `trees` mode, can auto-select or create worktree targets, and defaults to parallel tree startup.
- `restart`:
  Terminates selected services first, may or may not restart requirements, then routes back through the normal startup path with restart-specific flags attached.
- `resume`:
  Loads the latest saved run state, reconciles truth, optionally restores stale projects, then saves the updated state.

There are also secondary operating variants inside those commands:

- implicit `start`:
  Entering the dashboard or default startup path without a literal `start` token
- explicit `start`
- startup disabled for a mode:
  planning/dashboard-only behavior without starting services
- auto-resume exact match
- auto-resume subset match
- auto-resume superset reuse for `plan`
- resume restore with requirement reuse
- resume restore with full requirement restart

## Route Parsing and Startup-Relevant Flags

Route parsing lives in [python/envctl_engine/runtime/command_router.py](../../python/envctl_engine/runtime/command_router.py) and command-family policy lives in [python/envctl_engine/runtime/command_policy.py](../../python/envctl_engine/runtime/command_policy.py).

Important startup-related route facts:

- `plan` forces `trees` mode.
- `start`, `plan`, and `restart` are the startup command family.
- `resume` is its own dispatch family.
- `restart`, `logs`, `health`, `errors`, action commands, and cleanup commands are marked as load-state commands through command policy.
- `--service-parallel` and `--service-sequential` bind `route.flags["service_parallel"]`.
- `--parallel-trees`, `--no-parallel-trees`, and `--parallel-trees-max` bind tree-level parallel startup behavior.
- `--main-services-local` and `--main-services-remote` rewrite effective requirement enablement in main mode.
- `--no-resume` disables auto-resume.
- `--setup-worktree`, `--setup-worktrees`, and related flags alter project selection and effective mode.
- env-style assignments such as `parallel-trees=true`, `ENVCTL_SERVICE_ATTACH_PARALLEL=false`, and `FRONTEND_TEST_RUNNER=bun` are accepted directly by the route parser.

The route object is the single contract between parsing and orchestration:

- `command`
- `mode`
- `raw_args`
- `passthrough_args`
- `projects`
- `flags`

## Runtime Composition Root

`PythonEngineRuntime` in [python/envctl_engine/runtime/engine_runtime.py](../../python/envctl_engine/runtime/engine_runtime.py) is the composition root.

It wires together:

- config
- process runner
- process probe
- port planner
- state repository
- terminal UI
- `StartupOrchestrator`
- `ResumeOrchestrator`
- `ServiceManager`
- `RequirementsOrchestrator`

It also exposes the startup-facing facade methods that the orchestrators call:

- `_discover_projects`
- `_reserve_project_ports`
- `_start_requirements_for_project`
- `_start_project_services`
- `_try_load_existing_state`
- `_write_artifacts`
- `_reconcile_state_truth`
- `_requirement_enabled`
- `_service_enabled_for_mode`
- `_project_service_env`
- `_prepare_backend_runtime`
- `_prepare_frontend_runtime`
- `_service_start_command_resolved`
- `_requirement_command_resolved`
- hook bridge methods

The runtime class is intentionally mostly glue. Most behavior lives in domain modules:

- [python/envctl_engine/runtime/engine_runtime_startup_support.py](../../python/envctl_engine/runtime/engine_runtime_startup_support.py)
- [python/envctl_engine/runtime/engine_runtime_env.py](../../python/envctl_engine/runtime/engine_runtime_env.py)
- [python/envctl_engine/runtime/engine_runtime_commands.py](../../python/envctl_engine/runtime/engine_runtime_commands.py)
- [python/envctl_engine/runtime/engine_runtime_hooks.py](../../python/envctl_engine/runtime/engine_runtime_hooks.py)

## Startup Flow

The main startup command flow lives in [python/envctl_engine/startup/startup_orchestrator.py](../../python/envctl_engine/startup/startup_orchestrator.py).

### Phase 1: Contract and mode validation

`StartupOrchestrator.execute(...)` starts by:

- checking hook contract issues
- validating mode toggles
- deciding effective startup mode
- rejecting invalid configurations early

Mode validation is implemented in [python/envctl_engine/runtime/engine_runtime_env.py](../../python/envctl_engine/runtime/engine_runtime_env.py) and enforces:

- startup disabled modes
- at least one component enabled
- mutual exclusion of postgres and supabase in the same mode
- main-mode local/remote requirement override consistency

### Phase 2: Restart pre-stop

If the command is `restart`, startup begins by loading the current state and selecting what to stop.

Restart selection policy lives in [python/envctl_engine/startup/startup_selection_support.py](../../python/envctl_engine/startup/startup_selection_support.py):

- `_restart_include_requirements(...)`
- `_restart_selected_services(...)`
- `restart_target_projects(...)`
- `restart_target_projects_for_selected_services(...)`
- `_restart_service_types_for_project(...)`

Restart then:

- terminates selected services
- optionally releases requirement ports
- preserves untouched services and requirements in memory
- rewrites the route into a synthetic `start` route with `_restart_*` flags

That means restart is not a separate implementation of startup. It is a startup prelude plus a restart-aware startup path.

### Phase 3: Project discovery and selection

Project discovery is delegated through [python/envctl_engine/runtime/engine_runtime_startup_support.py](../../python/envctl_engine/runtime/engine_runtime_startup_support.py).

Behavior:

- `main` mode discovers exactly one project: `Main`
- `trees` mode discovers worktrees via planning discovery
- duplicate project identities are rejected

Selection logic then applies:

- explicit `--project`
- plan selection
- interactive tree selector for `start` in `trees` mode
- setup-worktree selection rules

Interactive tree selection itself lives in [python/envctl_engine/startup/startup_selection_support.py](../../python/envctl_engine/startup/startup_selection_support.py) and uses:

- current discovered contexts
- resumable state to preselect worktrees
- UI bridge selection helpers via the runtime facade

### Phase 4: Auto-resume

Auto-resume only applies to `start` and `plan` and is enabled by [python/envctl_engine/runtime/engine_runtime_startup_support.py](../../python/envctl_engine/runtime/engine_runtime_startup_support.py).

The orchestrator evaluates:

- exact match:
  selected projects exactly match saved state
- subset match:
  in `trees` mode, selected projects are a subset of saved state
- superset/expand match:
  in `plan`, selected projects contain all saved-state projects and may need only incremental startup

Outcomes:

- exact/subset:
  convert to `resume`
- superset with healthy existing state:
  preserve prior services/requirements and start only new projects
- mismatch or stale state:
  continue with normal startup

### Phase 5: Tree-level parallelism

Tree-level startup parallelism is decided by [python/envctl_engine/runtime/engine_runtime_startup_support.py](../../python/envctl_engine/runtime/engine_runtime_startup_support.py).

Rules:

- only possible in `trees` mode
- requires more than one project
- defaults to enabled for `plan`
- otherwise follows `RUN_SH_OPT_PARALLEL_TREES` / config unless overridden by route flags
- `--sequential` forces sequential behavior
- worker cap comes from `--parallel-trees-max` or `RUN_SH_OPT_PARALLEL_TREES_MAX`

This is the outermost concurrency boundary: multiple projects can be started simultaneously.

### Phase 6: Docker prewarm

Before per-project startup begins, startup can issue a `docker ps` prewarm via [python/envctl_engine/startup/startup_execution_support.py](../../python/envctl_engine/startup/startup_execution_support.py).

This is guarded by:

- `ENVCTL_DOCKER_PREWARM`
- whether any requirement is enabled
- whether `docker` exists

It emits `requirements.docker_prewarm` events with duration and timeout information.

### Phase 7: Per-project startup

Per-project startup is implemented in `start_project_context(...)` in [python/envctl_engine/startup/startup_execution_support.py](../../python/envctl_engine/startup/startup_execution_support.py).

For each context it performs:

1. progress emission
2. project port reservation
3. requirements startup or restart reuse
4. requirement readiness validation
5. service startup
6. post-start service truth assertion
7. service-ready progress emission
8. return of requirements, service records, and warnings

## Port Planning and Reservation

Port plans are stored in `PortPlan` from [python/envctl_engine/state/models.py](../../python/envctl_engine/state/models.py).

Each plan tracks:

- `requested`
- `assigned`
- `final`
- `source`
- `retries`

Project-level reservation is done in [python/envctl_engine/runtime/engine_runtime_startup_support.py](../../python/envctl_engine/runtime/engine_runtime_startup_support.py):

- every service/resource plan in the context is reserved before startup
- rebinds update `final` and emit `port.rebound`
- successful reservations emit `port.reserved`

At lower layers:

- requirement startup gets a synchronized `reserve_next(...)`
- service startup gets its own `reserve_next(...)`
- resume restore has an application-only reservation path when requirements are reused

## Requirements Startup

Requirements startup is split between:

- orchestration:
  [python/envctl_engine/startup/startup_execution_support.py](../../python/envctl_engine/startup/startup_execution_support.py)
- requirement start domain:
  [python/envctl_engine/startup/requirements_startup_domain.py](../../python/envctl_engine/startup/requirements_startup_domain.py)
- retry/failure classification:
  [python/envctl_engine/requirements/orchestrator.py](../../python/envctl_engine/requirements/orchestrator.py)
- container/shared adapter logic:
  [python/envctl_engine/requirements/adapter_base.py](../../python/envctl_engine/requirements/adapter_base.py),
  [python/envctl_engine/requirements/common.py](../../python/envctl_engine/requirements/common.py)

### Requirement registry

The built-in requirements registry lives in:

- [python/envctl_engine/requirements/core/models.py](../../python/envctl_engine/requirements/core/models.py)
- [python/envctl_engine/requirements/core/registry.py](../../python/envctl_engine/requirements/core/registry.py)
- [python/envctl_engine/requirements/dependencies/postgres/__init__.py](../../python/envctl_engine/requirements/dependencies/postgres/__init__.py)
- [python/envctl_engine/requirements/dependencies/redis/__init__.py](../../python/envctl_engine/requirements/dependencies/redis/__init__.py)
- [python/envctl_engine/requirements/dependencies/supabase/__init__.py](../../python/envctl_engine/requirements/dependencies/supabase/__init__.py)
- [python/envctl_engine/requirements/dependencies/n8n/__init__.py](../../python/envctl_engine/requirements/dependencies/n8n/__init__.py)

Each `DependencyDefinition` supplies:

- canonical id
- startup order
- which `PortPlan` key it maps to
- enable keys per mode
- default enablement
- environment projection into app services
- optional native starter

Current built-ins:

- `postgres`
- `redis`
- `supabase`
- `n8n`

### Requirement enablement

Enablement is decided via [python/envctl_engine/runtime/engine_runtime_env.py](../../python/envctl_engine/runtime/engine_runtime_env.py).

Important behavior:

- if startup is disabled for a mode, all requirements are disabled
- main mode can be rewritten by `--main-services-local` and `--main-services-remote`
- trees mode follows config/profile enablement directly

### Hook override path

Before normal requirement startup begins, `start_requirements_for_project(...)` invokes `envctl_setup_infrastructure` through [python/envctl_engine/runtime/engine_runtime_hooks.py](../../python/envctl_engine/runtime/engine_runtime_hooks.py).

Possible outcomes:

- hook absent:
  use normal requirement startup
- hook present and failed:
  return degraded requirement result immediately
- hook present and returns `skip_default_requirements`:
  build a `RequirementsResult` from hook payload and skip built-ins

### Requirement execution model

`start_requirements_for_project(...)` currently does the following:

- computes the full dependency definition list
- computes a `definition_ports` lookup for O(1) plan lookup
- computes requirement enablement once into `enabled_lookup`
- pre-populates disabled definitions as skipped outcomes with zero timing
- decides requirement-level parallelism with:
  - `ENVCTL_REQUIREMENTS_PARALLEL`
  - `ENVCTL_REQUIREMENTS_PARALLEL_MAX`
- runs only enabled definitions in the executor

This means requirement parallelism is intra-project parallelism and is independent from tree-level parallelism.

### Requirement startup mechanics

Actual component startup is implemented by `_start_requirement_component(...)` in [python/envctl_engine/startup/requirements_startup_domain.py](../../python/envctl_engine/startup/requirements_startup_domain.py).

Per component it:

- emits `requirements.start`
- applies deterministic bind-conflict simulation if configured for tests
- handles supabase reliability-contract and fingerprint checks
- attempts a native adapter path first in strict mode
- otherwise resolves a real command from config
- waits for listener readiness if needed
- retries bind conflicts and transient probe failures through `RequirementsOrchestrator`

### Native adapter path

Native adapters are used only when:

- requirements strict mode is enabled
- no command override is configured for that requirement
- `docker` is available
- a native starter exists for the component

Native adapter implementations are:

- [python/envctl_engine/requirements/postgres.py](../../python/envctl_engine/requirements/postgres.py)
- [python/envctl_engine/requirements/redis.py](../../python/envctl_engine/requirements/redis.py)
- [python/envctl_engine/requirements/supabase.py](../../python/envctl_engine/requirements/supabase.py)
- [python/envctl_engine/requirements/n8n.py](../../python/envctl_engine/requirements/n8n.py)

Common lifecycle behavior is implemented by [python/envctl_engine/requirements/adapter_base.py](../../python/envctl_engine/requirements/adapter_base.py):

- container existence checks
- port mismatch handling
- listener wait
- probe retry/restart/recreate flows
- optional bind-safe cleanup of envctl-owned containers

### Command override path

If native startup is not used, requirement commands are resolved by:

- [python/envctl_engine/runtime/command_resolution.py](../../python/envctl_engine/runtime/command_resolution.py)
- [python/envctl_engine/runtime/engine_runtime_commands.py](../../python/envctl_engine/runtime/engine_runtime_commands.py)

Requirement commands are not autodetected today.

If no explicit command is configured, command resolution raises `missing_requirement_start_command` unless a native adapter handled the requirement.

### Requirement timing and diagnostics

Requirement startup emits:

- execution mode:
  `requirements.execution`
- per-component timing:
  `requirements.timing.component`
- summary timing:
  `requirements.timing.summary`
- retry events:
  `requirements.retry`
- adapter timing, stage, and probe telemetry in deep/debug modes

Timing output is enabled by:

- `ENVCTL_DEBUG_RESTORE_TIMING`
- `ENVCTL_DEBUG_UI_MODE=standard|deep`
- route flags `debug_ui` / `debug_ui_deep`

Additional requirement tracing is controlled by:

- `ENVCTL_DEBUG_REQUIREMENTS_TRACE`
- `ENVCTL_DEBUG_DOCKER_COMMAND_TIMING`

## Service Bootstrap and Attach

Service startup is divided into:

- bootstrap preparation:
  [python/envctl_engine/startup/service_bootstrap_domain.py](../../python/envctl_engine/startup/service_bootstrap_domain.py)
- attach/start logic:
  [python/envctl_engine/startup/startup_execution_support.py](../../python/envctl_engine/startup/startup_execution_support.py)
- retry and concurrency helper:
  [python/envctl_engine/runtime/service_manager.py](../../python/envctl_engine/runtime/service_manager.py)
- command resolution:
  [python/envctl_engine/runtime/command_resolution.py](../../python/envctl_engine/runtime/command_resolution.py)

### Service hook override

Before any default service behavior, startup invokes `envctl_define_services`.

Outcomes:

- hook absent:
  continue with built-ins
- hook present and failed:
  startup fails for the project
- hook returns services:
  hook-provided `ServiceRecord`s are used directly
- hook asks to skip defaults but returns no services:
  startup fails

### Service environment model

The base project environment is built by [python/envctl_engine/runtime/engine_runtime_env.py](../../python/envctl_engine/runtime/engine_runtime_env.py) using dependency environment projectors.

Then service-specific env layering happens in [python/envctl_engine/startup/service_bootstrap_domain.py](../../python/envctl_engine/startup/service_bootstrap_domain.py):

- backend env file resolution
- frontend env file resolution
- merge app env files into command env
- sync `.env.local` for frontend when backend port is known
- sync backend `.env` when envctl owns the default env file and local DB env is not skipped

### Backend bootstrap behavior

`_prepare_backend_runtime(...)` currently supports:

- poetry project detection
- pip/venv project detection
- dependency install caching
- runtime-prep caching
- optional migration execution
- non-strict migration fallback with warnings

Important backend cache files:

- `.run-sh/envctl-backend-bootstrap.json`
- `.run-sh/envctl-backend-runtime-prep.json`

The backend runtime fingerprint includes:

- dependency fingerprints
- effective env inputs
- env file identity
- local DB env policy
- migration enablement

This means backend bootstrap can be skipped when:

- dependencies are already installed
- runtime env inputs have not changed
- no migration is required

### Frontend bootstrap behavior

`_prepare_frontend_runtime(...)` currently supports:

- package manager detection
- `package.json` / `scripts.dev` validation
- env sync into `.env.local`
- dependency install only when needed
- runtime-prep caching
- fallback from `npm ci` to `npm install` when appropriate

Frontend runtime cache file:

- `.run-sh/envctl-frontend-runtime-prep.json`

Frontend runtime fingerprint includes:

- package files and lockfiles
- `.env.local`
- `VITE_BACKEND_URL`
- `VITE_API_URL`
- `APP_ENV_FILE`
- dev-script content

### Service bootstrap parallelism

Inside `start_project_services(...)` in [python/envctl_engine/startup/startup_execution_support.py](../../python/envctl_engine/startup/startup_execution_support.py):

- backend and frontend bootstrap prep now run in parallel when:
  - both services are selected
  - service prep parallel mode is enabled

Prep parallel mode is controlled by:

- route flag `service_prep_parallel`
- config/env `ENVCTL_SERVICE_PREP_PARALLEL`
- fallback to attach-parallel policy when no prep-specific override is set

If not, preparation remains sequential.

This is per-project concurrency and is separate from tree-level startup concurrency.

### Service attach mode

Service attach parallelism is controlled by:

- route flag `service_parallel`
- config/env `ENVCTL_SERVICE_ATTACH_PARALLEL`

It only applies when both backend and frontend are selected.

Attach behavior:

- if both services are selected:
  use `ServiceManager.start_project_with_attach(...)`
- otherwise:
  start services individually through `start_service_with_retry(...)`

### Command resolution for services

Service command resolution uses [python/envctl_engine/runtime/command_resolution.py](../../python/envctl_engine/runtime/command_resolution.py).

Resolution order:

1. explicit `ENVCTL_BACKEND_START_CMD` / `ENVCTL_FRONTEND_START_CMD`
2. backend autodetect:
   - Python/Uvicorn projects
   - package.json `dev` scripts
3. frontend autodetect:
   - package.json `dev` scripts

Autodetect supports package-manager-specific commands and adds Vite port flags when relevant.

### Actual port detection and listener truth

Service attach in [python/envctl_engine/startup/startup_execution_support.py](../../python/envctl_engine/startup/startup_execution_support.py) does more than launch processes.

It also:

- detects actual bound ports
- handles rebound detection
- emits requested/actual bind events
- raises hard failures in strict listener-truth mode when listeners are not found
- records log paths on returned `ServiceRecord`s

The `ServiceManager` retry loop in [python/envctl_engine/runtime/service_manager.py](../../python/envctl_engine/runtime/service_manager.py) handles:

- bind-conflict retry
- listener-not-detected retry
- deterministic rebind using `reserve_next(...)`

## Resume Flow

Resume is implemented by:

- [python/envctl_engine/startup/resume_orchestrator.py](../../python/envctl_engine/startup/resume_orchestrator.py)
- [python/envctl_engine/startup/resume_restore_support.py](../../python/envctl_engine/startup/resume_restore_support.py)
- [python/envctl_engine/startup/resume_progress.py](../../python/envctl_engine/startup/resume_progress.py)

### ResumeOrchestrator responsibilities

`ResumeOrchestrator.execute(...)` does the command-level work:

- load latest state
- enforce startup hook contract
- bind debug run id
- enforce runtime readiness gate
- validate mode toggles
- emit `state.resume`
- reconcile state truth
- optionally restore missing services/projects
- save reconciled state
- optionally enter interactive dashboard

Resume is truth-driven, not just pointer-driven.

### Restore-missing behavior

`restore_missing(...)` in [python/envctl_engine/startup/resume_restore_support.py](../../python/envctl_engine/startup/resume_restore_support.py) identifies restore targets from:

- missing services
- projects whose saved requirements are no longer considered ready

Per project, restore does:

1. resolve project context
2. inspect original services and requirements
3. decide whether requirements can be reused
4. stop stale services
5. optionally release old requirement ports
6. reserve ports
7. either reuse requirements or restart them
8. start app services
9. merge the result back into in-memory state

### Requirement reuse during resume

Resume can reuse requirements when:

- saved requirements exist
- requirements are still logically ready
- requirement truth reconciliation says the dependency endpoints did not change

If requirements are reused:

- only application service ports are re-reserved
- requirements are not restarted
- restore time is reduced

If reuse is rejected:

- requirement ports are released
- full requirement startup runs again

### Resume parallelism

Restore project parallelism is decided by `_restore_parallel_config(...)`.

Important behavior:

- restore reuses tree-level parallel startup configuration
- if the source command was `plan` and parallelism was not explicitly disabled, restore defaults to parallel

### Resume timing and output

Resume emits:

- `resume.phase`
- `resume.restore.execution`
- `resume.restore.step`
- `resume.restore.project_timing`
- `resume.restore.timing`

Timing lines are printed only when timing is enabled and spinner-driven output is not suppressing them.

## State, Persistence, and Projection

State model definitions live in [python/envctl_engine/state/models.py](../../python/envctl_engine/state/models.py).

Core objects:

- `PortPlan`
- `ServiceRecord`
- `RequirementsResult`
- `RunState`

Serialization and compatibility logic lives in [python/envctl_engine/state/__init__.py](../../python/envctl_engine/state/__init__.py).

That file handles:

- JSON state load/dump
- legacy shell-state load
- pointer-file load
- state merge
- schema validation

Repository-level persistence lives in [python/envctl_engine/state/repository.py](../../python/envctl_engine/state/repository.py).

Repository responsibilities:

- save latest scoped state
- save per-run history
- write runtime map
- write ports manifest
- write error report
- write events snapshot
- maintain scoped pointer files
- optionally mirror compat artifacts into the legacy runtime root

Runtime map generation lives in [python/envctl_engine/state/runtime_map.py](../../python/envctl_engine/state/runtime_map.py).

The runtime map provides:

- per-project backend/frontend ports
- `port_to_service`
- `service_to_actual_port`
- per-project URL projection when services are considered ready

## Progress, Spinner, and Timing Suppression

Progress UI is intentionally separate from orchestration correctness.

Files:

- [python/envctl_engine/startup/startup_progress.py](../../python/envctl_engine/startup/startup_progress.py)
- [python/envctl_engine/startup/resume_progress.py](../../python/envctl_engine/startup/resume_progress.py)
- [python/envctl_engine/startup/progress_shared.py](../../python/envctl_engine/startup/progress_shared.py)

Key behavior:

- progress messages dedupe per project
- progress can print directly, feed a single spinner, feed a multi-project spinner, or emit `ui.status`
- timing lines are suppressed whenever spinner callbacks are active

This is important when interpreting logs:

- event streams still record timing even when terminal timing lines are suppressed
- spinner mode changes presentation, not underlying execution semantics

## Hooks and Extension Points

Startup currently exposes two hook entrypoints via [python/envctl_engine/runtime/engine_runtime_hooks.py](../../python/envctl_engine/runtime/engine_runtime_hooks.py):

- `envctl_setup_infrastructure`
- `envctl_define_services`

Hook behavior is Python-mediated and safe-parsed rather than shell-sourced.

Hook outputs can:

- replace default requirement results
- replace default service records
- short-circuit built-in startup

This makes hooks the highest-priority startup override path.

## Concurrency Model

There are four distinct concurrency layers in the current implementation.

1. Tree-level parallelism:
   Multiple projects starting at once.
2. Requirement-level parallelism:
   Multiple enabled dependency components starting inside one project.
3. Service bootstrap prep parallelism:
   Backend and frontend preparation can run in parallel inside one project when service attach parallel mode is active.
4. Service attach parallelism:
   Backend and frontend process startup/attach can run in parallel inside one project.

These layers stack.

For example, in `trees` mode with two worktrees, parallel requirement startup, and parallel service attach enabled, the runtime can have:

- multiple projects active
- multiple requirements active per project
- simultaneous backend/frontend prep per project
- simultaneous backend/frontend attach per project

This is where startup wins come from, but it is also where resource contention risk comes from.

## Timing and Diagnostics Surfaces

The startup/resume path emits timing at several levels:

- startup phase timing
- requirements component timing
- requirements summary timing
- service bootstrap phase timing
- service attach phase timing
- service summary timing
- resume restore step timing
- resume restore project timing
- startup breakdown summary
- startup summary top-components view

The main switches are:

- `ENVCTL_DEBUG_UI_MODE`
- `ENVCTL_DEBUG_RESTORE_TIMING`
- `ENVCTL_DEBUG_STARTUP_BREAKDOWN`
- `ENVCTL_DEBUG_REQUIREMENTS_TRACE`
- `ENVCTL_DEBUG_DOCKER_COMMAND_TIMING`

## File-by-File Map

This appendix lists every file on the startup/resume path that matters to the current implementation.

### `startup/`

- [python/envctl_engine/startup/__init__.py](../../python/envctl_engine/startup/__init__.py)
  Package marker only.
- [python/envctl_engine/startup/protocols.py](../../python/envctl_engine/startup/protocols.py)
  Startup-facing runtime and orchestrator protocol contract.
- [python/envctl_engine/startup/startup_orchestrator.py](../../python/envctl_engine/startup/startup_orchestrator.py)
  Command-level startup flow, restart pre-stop, project selection, auto-resume, tree-level parallel startup, artifact write, summary output.
- [python/envctl_engine/startup/startup_execution_support.py](../../python/envctl_engine/startup/startup_execution_support.py)
  Per-project startup execution, requirement startup orchestration, service attach orchestration, startup summaries, docker prewarm, timing utilities.
- [python/envctl_engine/startup/startup_selection_support.py](../../python/envctl_engine/startup/startup_selection_support.py)
  Tree selector policy, restart target selection, service-type selection, state-vs-selection matching.
- [python/envctl_engine/startup/startup_progress.py](../../python/envctl_engine/startup/startup_progress.py)
  Startup progress routing and startup-specific spinner group wrapper.
- [python/envctl_engine/startup/progress_shared.py](../../python/envctl_engine/startup/progress_shared.py)
  Rich-backed per-project spinner implementation shared by startup and resume.
- [python/envctl_engine/startup/requirements_startup_domain.py](../../python/envctl_engine/startup/requirements_startup_domain.py)
  Requirement start implementation, native adapter path, listener waiting, adapter timing and retry telemetry.
- [python/envctl_engine/startup/service_bootstrap_domain.py](../../python/envctl_engine/startup/service_bootstrap_domain.py)
  Backend/frontend bootstrap preparation, cache fingerprints, env-file sync, migration handling, bootstrap command execution.
- [python/envctl_engine/startup/resume_orchestrator.py](../../python/envctl_engine/startup/resume_orchestrator.py)
  Top-level resume flow.
- [python/envctl_engine/startup/resume_restore_support.py](../../python/envctl_engine/startup/resume_restore_support.py)
  Project restore implementation for stale resumes.
- [python/envctl_engine/startup/resume_progress.py](../../python/envctl_engine/startup/resume_progress.py)
  Resume-specific spinner group wrapper.

### `runtime/`

- [python/envctl_engine/runtime/command_router.py](../../python/envctl_engine/runtime/command_router.py)
  Canonical route parser and startup-related flag binding.
- [python/envctl_engine/runtime/command_policy.py](../../python/envctl_engine/runtime/command_policy.py)
  Command-family policy, mode forcing, load-state and skip-startup defaults.
- [python/envctl_engine/runtime/engine_runtime.py](../../python/envctl_engine/runtime/engine_runtime.py)
  Composition root and facade methods used by startup/resume.
- [python/envctl_engine/runtime/engine_runtime_startup_support.py](../../python/envctl_engine/runtime/engine_runtime_startup_support.py)
  Effective startup mode, auto-resume enablement, project discovery, port reservation, tree-level parallel startup config, legacy resume sanitization.
- [python/envctl_engine/runtime/engine_runtime_env.py](../../python/envctl_engine/runtime/engine_runtime_env.py)
  Requirement/service enablement policy, startup validation, project service env building, route-to-env overrides, main-mode requirement rewrites.
- [python/envctl_engine/runtime/engine_runtime_commands.py](../../python/envctl_engine/runtime/engine_runtime_commands.py)
  Requirement/service command resolution wrappers, command env construction, default Python executable lookup.
- [python/envctl_engine/runtime/command_resolution.py](../../python/envctl_engine/runtime/command_resolution.py)
  Real requirement/service command resolution and service autodetect logic.
- [python/envctl_engine/runtime/engine_runtime_hooks.py](../../python/envctl_engine/runtime/engine_runtime_hooks.py)
  Hook bridge, hook payload conversion, supabase reinit support.
- [python/envctl_engine/runtime/runtime_context.py](../../python/envctl_engine/runtime/runtime_context.py)
  Runtime dependency lookup for state repository, port allocator, and process runtime.
- [python/envctl_engine/runtime/service_manager.py](../../python/envctl_engine/runtime/service_manager.py)
  Service retry and parallel backend/frontend attach helper.

### `requirements/`

- [python/envctl_engine/requirements/__init__.py](../../python/envctl_engine/requirements/__init__.py)
  Re-export surface for requirement starters and orchestrator types.
- [python/envctl_engine/requirements/orchestrator.py](../../python/envctl_engine/requirements/orchestrator.py)
  Requirement retry/failure classification and outcome shaping.
- [python/envctl_engine/requirements/common.py](../../python/envctl_engine/requirements/common.py)
  Shared Docker/container helpers and result types.
- [python/envctl_engine/requirements/adapter_base.py](../../python/envctl_engine/requirements/adapter_base.py)
  Shared native-adapter container lifecycle engine.
- [python/envctl_engine/requirements/core/__init__.py](../../python/envctl_engine/requirements/core/__init__.py)
  Core requirement registry exports.
- [python/envctl_engine/requirements/core/models.py](../../python/envctl_engine/requirements/core/models.py)
  Requirement definition and normalized component-result models.
- [python/envctl_engine/requirements/core/registry.py](../../python/envctl_engine/requirements/core/registry.py)
  Built-in requirement registry assembly.
- [python/envctl_engine/requirements/dependencies/postgres/__init__.py](../../python/envctl_engine/requirements/dependencies/postgres/__init__.py)
  Postgres definition and environment projection.
- [python/envctl_engine/requirements/dependencies/redis/__init__.py](../../python/envctl_engine/requirements/dependencies/redis/__init__.py)
  Redis definition and environment projection.
- [python/envctl_engine/requirements/dependencies/supabase/__init__.py](../../python/envctl_engine/requirements/dependencies/supabase/__init__.py)
  Supabase definition and environment projection.
- [python/envctl_engine/requirements/dependencies/n8n/__init__.py](../../python/envctl_engine/requirements/dependencies/n8n/__init__.py)
  n8n definition and environment projection.
- [python/envctl_engine/requirements/postgres.py](../../python/envctl_engine/requirements/postgres.py)
  Native Postgres container lifecycle.
- [python/envctl_engine/requirements/redis.py](../../python/envctl_engine/requirements/redis.py)
  Native Redis container lifecycle.
- [python/envctl_engine/requirements/supabase.py](../../python/envctl_engine/requirements/supabase.py)
  Native Supabase DB/compose lifecycle and reliability contract handling.
- [python/envctl_engine/requirements/n8n.py](../../python/envctl_engine/requirements/n8n.py)
  Native n8n container lifecycle.

### `state/`

- [python/envctl_engine/state/models.py](../../python/envctl_engine/state/models.py)
  Typed startup/resume state model.
- [python/envctl_engine/state/__init__.py](../../python/envctl_engine/state/__init__.py)
  JSON and legacy-shell state serialization/deserialization.
- [python/envctl_engine/state/repository.py](../../python/envctl_engine/state/repository.py)
  Scoped persistence, pointer maintenance, compat mirroring, runtime updates.
- [python/envctl_engine/state/runtime_map.py](../../python/envctl_engine/state/runtime_map.py)
  URL and port projection used by dashboard and summaries.

## Current Review Assessment

The current architecture is coherent.

The important structural strengths are:

- command policy is separated from startup behavior
- startup orchestration is separated from per-project work
- resume restore is a first-class path, not a hacked variant of startup
- state and runtime-map generation are typed and explicit
- requirements and service bootstrap both emit detailed telemetry
- concurrency exists at clearly defined boundaries rather than being scattered ad hoc

The current working-tree startup optimization changes in [python/envctl_engine/startup/startup_execution_support.py](../../python/envctl_engine/startup/startup_execution_support.py) fit the architecture cleanly:

- disabled requirements are skipped before executor scheduling
- requirement enablement is cached once per project startup
- backend/frontend bootstrap prep can overlap when service attach is already configured as parallel

After review, those changes look directionally correct.

The main startup-policy caveat has now been reduced:

- service bootstrap prep parallelism can be overridden independently through `ENVCTL_SERVICE_PREP_PARALLEL` or `service_prep_parallel`

The remaining tradeoff is policy simplicity versus operational control:

- leaving prep parallelism unset keeps it aligned with attach-parallel behavior
- setting a prep-specific override lets you keep sequential attach while still overlapping backend/frontend prep

## Practical Reading Order

If you need to debug or change startup now, use this order:

1. [python/envctl_engine/runtime/command_router.py](../../python/envctl_engine/runtime/command_router.py)
2. [python/envctl_engine/runtime/engine_runtime.py](../../python/envctl_engine/runtime/engine_runtime.py)
3. [python/envctl_engine/startup/startup_orchestrator.py](../../python/envctl_engine/startup/startup_orchestrator.py)
4. [python/envctl_engine/startup/startup_execution_support.py](../../python/envctl_engine/startup/startup_execution_support.py)
5. [python/envctl_engine/startup/requirements_startup_domain.py](../../python/envctl_engine/startup/requirements_startup_domain.py)
6. [python/envctl_engine/startup/service_bootstrap_domain.py](../../python/envctl_engine/startup/service_bootstrap_domain.py)
7. [python/envctl_engine/startup/resume_orchestrator.py](../../python/envctl_engine/startup/resume_orchestrator.py)
8. [python/envctl_engine/startup/resume_restore_support.py](../../python/envctl_engine/startup/resume_restore_support.py)
9. [python/envctl_engine/state/repository.py](../../python/envctl_engine/state/repository.py)
10. [python/envctl_engine/state/runtime_map.py](../../python/envctl_engine/state/runtime_map.py)
