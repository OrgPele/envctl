# Python Runtime Developer Guide

This guide is for contributors working in the Python engine.

It documents the runtime entrypoints, module boundaries, artifact/state contracts, and the extension points you are expected to use when adding behavior.

For deeper topic-specific guides, use:

- [Config and Bootstrap](config-and-bootstrap.md)
- [Command Surface and Routing](command-surface.md)
- [UI and Interaction Architecture](ui-and-interaction.md)
- [Runtime Lifecycle](runtime-lifecycle.md)
- [State and Artifacts](state-and-artifacts.md)
- [Debug and Diagnostics](debug-and-diagnostics.md)
- [Testing and Validation](testing-and-validation.md)

## Top-Level Flow

Current control flow:

1. `bin/envctl`
2. `envctl_engine.runtime.launcher_cli`
3. `envctl_engine.runtime.cli:main`
4. `envctl_engine.runtime.command_router.parse_route`
5. `envctl_engine.runtime.engine_runtime.EngineRuntime`
6. `envctl_engine.runtime.engine_runtime_dispatch.dispatch_command`
7. domain orchestrator or inspection handler

Key boundary decisions:

- The launcher resolves repo root and prepares the Python runtime handoff.
- Launcher-owned flags such as `--version` must resolve before repo detection, config bootstrap, prereq checks, or runtime dispatch.
- Source checkouts should use `bin/envctl`; explicit wrapper paths stay on that exact wrapper, while bare `envctl` still prefers an installed command on `PATH`.
- Package-style test runs and raw `python3 -m unittest discover -s tests/python ...` both bootstrap the local `python/` package through the repo-owned test package initializers under `tests/`; standalone scripts use `scripts/_bootstrap.py` when launched directly.
- Contributor and release-readiness validation should run from the editable repo-local install (`.venv/bin/python -m pip install -e '.[dev]'`) so the canonical `pytest -q` lane and packaging/build smoke exercise the installed runtime.
- `runtime/cli.py` owns prereq checks, local config bootstrap policy, and exit code normalization.
- `EngineRuntime` is the runtime facade that wires the domains together.
- Orchestrators own behavior; helper modules own reusable policy and contract logic.

## Runtime Bootstrapping

`runtime/cli.py` does more than just call `dispatch`.

Before dispatching it:

- strips launcher-level repo/version arguments first
- parses the initial route with enough config context to honor `ENVCTL_DEFAULT_MODE`
- discovers repo-local config state
- bootstraps `.envctl` when required
- loads `EngineConfig`
- reparses the route with the final environment/config view
- performs command-specific prereq checks
- normalizes exit codes to:
  - `0`: success
  - `1`: actionable failure
  - `2`: controlled quit / interrupt

Commands that intentionally skip config bootstrap are limited. That is why `show-config`, `show-state`, `explain-startup`, and the `--list-*` inspection commands are safe in unconfigured repos, while startup commands are not.

The installed console-script entrypoint also shares launcher support helpers for `install`, `uninstall`, and `--version` before route parsing so those surfaces do not expand the runtime command inventory.

## Runtime Object Graph

`EngineRuntime` in `python/envctl_engine/runtime/engine_runtime.py` is the composition root.

It wires together:

- `EngineConfig`
- `ProcessRunner`
- `ProcessProbe`
- `RuntimeStateRepository`
- `RuntimeTerminalUI`
- `StartupOrchestrator`
- `ResumeOrchestrator`
- `DoctorOrchestrator`
- `LifecycleCleanupOrchestrator`
- `DashboardOrchestrator`
- `StateActionOrchestrator`
- `ActionCommandOrchestrator`
- debug recorder and event sinks

Design rule:

- add new behavior to a domain module or orchestrator first
- only add glue methods or aliases to `EngineRuntime` when the runtime facade truly needs to expose that behavior across domains

## Domain Layout

The package layout under `python/envctl_engine/` is now the main architecture boundary.

- `runtime/`: facade, dispatch, route parsing, shared runtime helpers
- `startup/`: start/restart/resume preparation, execution, progress, restore
- `actions/`: explicit action commands such as tests, PRs, commits, analysis, worktree actions
- `state/`: typed state models, load/dump compatibility, runtime map, repository
- `requirements/`: dependency registry, adapters, orchestration, compose assets
- `config/`: config load/merge/bootstrap/edit/save
- `debug/`: debug bundle packaging, sanitization, diagnostics, doctor support
- `ui/`: dashboard loop, selector flows, textual integration, spinners, input
- `shared/`: low-level helpers such as ports, process probing, parsing, environment access, hooks
- `planning/`: plan discovery, selection, worktree setup support

Use the grouped package paths. The flat compatibility shims remain only for migration tolerance.

## Route Parsing and Command Dispatch

`runtime/command_router.py` is the canonical command contract.

It owns:

- command aliases
- supported command list
- mode tokens
- boolean/value/pair/special flag binding
- env-style assignment handling
- route normalization into the `Route` dataclass

`runtime/engine_runtime_dispatch.py` is intentionally small and should stay that way. It maps commands to:

- inspection helpers
- debug helpers
- lifecycle orchestrators
- startup/resume orchestrators
- state/action orchestrators

When adding a command:

1. add aliases and support in `command_router.py`
2. make sure `list_supported_commands()` includes it
3. dispatch it from `engine_runtime_dispatch.py`
4. add tests for parsing and dispatch
5. update docs and, if relevant, parity/cutover artifacts

## Config Model

The config system has three important layers:

- environment variables
- repo-local config discovery/bootstrap
- managed persistence/editing

Core files:

- `config/__init__.py`: parsing, defaults, alias resolution, `EngineConfig`
- `config/persistence.py`: managed `.envctl` block format and save logic
- `config/wizard_domain.py`: interactive bootstrap and edit flow
- `config/command_support.py`: headless and interactive `config` command behavior

Read [Config and Bootstrap](config-and-bootstrap.md) when changing discovery, bootstrap gating, or managed save semantics.

Current semantics:

- `.envctl` is the canonical repo-local file
- legacy config files can prefill the modern config
- the config wizard writes managed canonical keys
- older aliases remain accepted for compatibility

Developer rule:

- do not scatter ad hoc env parsing across the codebase if the setting belongs in the config model
- if the setting affects startup shape, mode/profile behavior, or persisted config UX, model it in `EngineConfig` and `config/persistence.py`

## Runtime Roots and Scope Model

The Python runtime is scope-aware.

Important paths:

- `config.runtime_dir`: global envctl runtime root, usually `/tmp/envctl-runtime`
- `config.runtime_scope_dir`: active scoped runtime directory for the current repo
- `runtime.runtime_root`: same as `runtime_scope_dir`
- `runtime.runtime_legacy_root`: compatibility view at `<runtime_dir>/python-engine`

The runtime also maintains scoped locks and scoped state pointers. This is why repo isolation and cross-repo tests now matter more than they did in the shell flow.

## Command Family Split

The runtime dispatch surface is intentionally divided across command families with different responsibilities.

Main families today:

- direct inspection: `list-*`, `show-config`, `show-state`, `explain-startup`
- debug helpers: `debug-pack`, `debug-report`, `debug-last`
- lifecycle cleanup: `stop`, `stop-all`, `blast-all`
- startup/resume: `start`, `plan`, `restart`, `resume`
- dashboard/config: `dashboard`, `config`
- state actions: `logs`, `clear-logs`, `health`, `errors`
- project actions: `test`, `pr`, `commit`, `review`, `migrate`, worktree actions

Relevant orchestrators:

- `startup/StartupOrchestrator`
- `startup/ResumeOrchestrator`
- `runtime/LifecycleCleanupOrchestrator`
- `ui/dashboard/DashboardOrchestrator`
- `state/StateActionOrchestrator`
- `actions/ActionCommandOrchestrator`

Developer rule:

- put behavior in the command family that owns the user contract instead of reusing a nearby orchestrator just because it is convenient

## State Contract

Typed state lives in `state/models.py`.

Main dataclasses:

- `PortPlan`: requested, assigned, final port plus source and retry count
- `ServiceRecord`: service process/runtime truth payload
- `RequirementsResult`: normalized dependency result by component id
- `RunState`: top-level run contract

Important `RunState` fields:

- `run_id`
- `mode`
- `backend_mode`
- `services`
- `requirements`
- `pointers`
- `metadata`

Compatibility details:

- legacy shell state can still be loaded through `state/__init__.py`
- legacy payloads are normalized into modern models
- legacy state is marked in metadata and treated more strictly on resume

Developer rule:

- extend the typed models first
- keep JSON payloads backward-tolerant where practical
- preserve shell-read compatibility until the cutover explicitly removes it

## Artifact Contract

`state/repository.py` and `runtime/engine_runtime_artifacts.py` define the runtime artifact contract.

Latest pointers:

- `run_state.json`
- `runtime_map.json`
- `ports_manifest.json`
- `error_report.json`
- `events.jsonl`
- `runtime_readiness_report.json`

Per-run history:

- `runs/<run-id>/run_state.json`
- `runs/<run-id>/runtime_map.json`
- `runs/<run-id>/ports_manifest.json`
- `runs/<run-id>/error_report.json`
- `runs/<run-id>/events.jsonl`
- `runs/<run-id>/runtime_readiness_report.json`

Repository responsibilities:

- persist the latest view
- persist per-run history
- maintain scoped pointers
- optionally mirror compatibility artifacts into the legacy root

When you add an artifact:

1. decide whether it is latest-only, per-run, or both
2. write it through the repository/artifact layer, not ad hoc from orchestrators
3. update doctor/debug/reporting surfaces if operators need to inspect it

## Runtime Map Contract

`state/runtime_map.py` builds the user-facing and tooling-facing projection.

It provides:

- `projects`
- `port_to_service`
- `service_to_actual_port`
- `projection`

The `projection` block is the stable place for backend/frontend URLs and statuses.

If you change service naming or readiness semantics, update:

- `state/runtime_map.py`
- any tests consuming URL/status projection
- any docs that instruct users to read `runtime_map.json`

## Startup Architecture

Startup is coordinated by `startup/startup_orchestrator.py`, but large parts of the logic live in support modules.

Main responsibilities:

- restart pre-stop and preservation behavior
- effective mode validation
- shell-budget gate enforcement
- project discovery and selection
- port reservation
- requirements startup
- service startup
- artifact persistence
- post-start dashboard entry decision

Supporting modules to know:

- `runtime/engine_runtime_startup_support.py`: shared start-mode and project/port helpers
- `startup/startup_execution_support.py`: requirements and service execution helpers
- `startup/startup_progress.py`: progress/spinner policy
- `startup/startup_selection_support.py`: selection and restart targeting
- `startup/requirements_startup_domain.py`: dependency-start policy and timing events
- `startup/service_bootstrap_domain.py`: backend/frontend bootstrap and env projection

Developer rule:

- do not pile more branchy policy into `StartupOrchestrator.execute()`
- move new decisions into support/domain helpers and keep `execute()` mostly orchestration glue

## Progress and Reporting Split

Recent startup/resume refactors also introduced an explicit progress layer.

Important files:

- `startup/startup_progress.py`
- `startup/resume_progress.py`
- `startup/progress_shared.py`

Current design intent:

- orchestrators decide what is happening
- progress helpers decide how to report it
- shared spinner group code owns rich progress UI and lifecycle events

That separation matters for maintainability and for interactive diagnostics. Avoid re-embedding spinner or progress-print logic directly into orchestration branches.

## Resume Architecture

`startup/resume_orchestrator.py` owns the resume contract.

Resume phases:

1. load latest state
2. enforce cutover budgets for resume
3. reconcile state against runtime truth
4. optionally restore missing services
5. save the reconciled state back through the repository
6. optionally enter interactive dashboard

Important helpers live in `startup/resume_restore_support.py`.

Key difference from shell-era behavior:

- resume is truth-driven, not just pointer-driven
- missing services are surfaced explicitly
- legacy state is sanitized and treated as a stricter case

## Requirements Architecture

The dependency system is now registry-driven.

Core pieces:

- `requirements/core/models.py`: dependency metadata contracts
- `requirements/core/registry.py`: built-in dependency registry
- `requirements/dependencies/*`: dependency definitions and env projectors
- `requirements/orchestrator.py`: retry/failure classification and outcome contract
- `requirements/*.py`: native adapters for postgres, redis, supabase, n8n

Important concepts:

- `DependencyDefinition` describes ids, resources, enable keys, and native/projector hooks
- `RequirementComponentResult` is the normalized per-component payload written to state
- `RequirementsOrchestrator` classifies failures into retryable bind conflicts, transient probe failures, soft bootstrap failures, and hard failures

When adding a new built-in dependency:

1. define a `DependencyDefinition`
2. register it in `requirements/core/registry.py`
3. implement env projection if services need derived env vars
4. implement native start/cleanup behavior if managed by Python runtime
5. update config persistence and docs
6. add unit and e2e coverage

## UI Architecture

The UI surface is split on purpose.

Dashboard backend selection:

- `ui/backend_resolver.py`
- `ui/backend.py`
- `ui/dashboard/orchestrator.py`

Selector implementation:

- `ui/textual/screens/selector/*`
- `ui/prompt_toolkit_cursor_menu.py`

Current behavior matters:

- `ENVCTL_UI_BACKEND=auto` defaults to the legacy dashboard backend
- `ENVCTL_UI_EXPERIMENTAL_DASHBOARD=1` makes `auto` prefer Textual when available
- selector screens default to the Textual plan-style selector
- `ENVCTL_UI_SELECTOR_IMPL=planning_style` is the prompt-toolkit rollback path

Do not assume "dashboard backend" and "selector backend" are the same policy surface.

## Debug and Event Architecture

There are two related but separate event streams:

- runtime events written to `events.jsonl`
- debug flight recorder events written under `debug/session-*/events.debug.jsonl`

Important modules:

- `runtime/engine_runtime_event_support.py`: recorder configuration and event emission bridge
- `ui/debug_flight_recorder.py`: session recorder, anomaly files, TTY artifacts
- `debug/debug_contract.py`: event normalization schema
- `debug/debug_bundle_support.py`: bundle assembly and redaction helpers
- `debug/debug_bundle_diagnostics.py`: summarized diagnosis
- `runtime/engine_runtime_debug_support.py`: `debug-pack`, `debug-report`, `debug-last`

Privacy model:

- command strings are hashed
- string payloads are scrubbed
- printable raw input is opt-in even in deep mode

Developer rule:

- if you add user-input-adjacent telemetry, route it through the existing redaction model
- if the new signal is needed in bundles, make sure the bundle redaction and diagnostic layers know how to handle it

## Doctor and Runtime Readiness Gates

`debug/doctor_orchestrator.py` is not only a health dump. It is also a migration/cutover gate.

It combines:

- runtime path/status diagnostics
- parity manifest validation
- runtime truth reconciliation
- synthetic-state detection
- runtime readiness contract evaluation
- recent structured failure surfacing

This means doctor changes are high leverage and high risk.

If you change doctor inputs or gate semantics:

- update tests in `tests/python/runtime/` and `tests/python/debug/`
- update `contracts/python_engine_parity_manifest.json` or related ledgers if the gate contract changes
- update user-facing diagnostics docs

## Runtime Readiness Contract

The repository now uses a Python-native runtime readiness contract.

Main files:

- `runtime/release_gate.py`
- `runtime/runtime_readiness.py`
- `contracts/python_runtime_gap_report.json`
- `contracts/python_engine_parity_manifest.json`

Practical meaning:

- release/shipability checks validate Python readiness, not shell migration budgets
- doctor and release gates use the runtime gap report plus parity manifest
- compatibility surfaces are removed only when the generated readiness contract says they are no longer blockers

## Process and Truth Model

Runtime truth comes from:

- `shared/process_runner.py`
- `shared/process_probe.py`
- `runtime/engine_runtime_service_truth.py`
- `runtime/engine_runtime_state_truth.py`
- `runtime/engine_runtime_dashboard_truth.py`

Important distinctions:

- process truth: is the PID alive
- listener truth: does the expected port have a live listener
- state truth: does saved state match process/listener reality
- dashboard truth: what should be surfaced to operators without overprobing every render

If you change service readiness behavior, you usually need to update more than one of those layers.

## Extension Checklists

### Add a new command

1. Add aliases and support in `runtime/command_router.py`.
2. Dispatch in `runtime/engine_runtime_dispatch.py`.
3. Implement behavior in the appropriate orchestrator/domain.
4. Add parser, dispatch, and behavior tests.
5. Update `docs/reference/commands.md` and any user/developer guide sections affected.

### Add a new runtime artifact

1. Define its data contract.
2. Persist it through `state/repository.py` or `runtime/engine_runtime_artifacts.py`.
3. Decide whether it belongs in latest view, per-run history, or both.
4. Update doctor/debug tooling if operators need it.
5. Add tests for persistence and reload behavior.

### Add a new dependency

1. Register a `DependencyDefinition`.
2. Implement projection/start/cleanup support.
3. Wire config keys and defaults.
4. Add startup/resume/cleanup tests.
5. Document the dependency in user docs and configuration docs.

### Add a new debug signal

1. Emit through the runtime/debug recorder path.
2. Ensure payload is redactable.
3. Decide whether it belongs in bundles, diagnostics, or both.
4. Add tests for schema and redaction.
5. Update the user debugging guide if operators should act on it.

## Testing Expectations

This repository now has meaningful coverage for:

- parser and command routing
- startup/resume/runtime truth
- state repository and compatibility
- debug bundle generation and analysis
- selector/UI behavior
- runtime readiness and shipability gates

Minimum bar for non-trivial runtime changes:

- targeted Python unit tests for the affected domain
- any needed Python integration coverage when behavior crosses module or process boundaries
- docs updates when behavior or operator workflow changed

## Practical Rule of Thumb

If you are unsure where new code belongs:

- config shape or persistence: `config/`
- route/flag/command semantics: `runtime/command_router.py`
- startup or resume behavior: `startup/`
- action command logic: `actions/`
- dependency management: `requirements/`
- artifact or state model: `state/`
- runtime health/truth/diagnostics: `runtime/*truth.py`, `runtime/release_gate.py`, `debug/`
- interactive flow: `ui/`

If your change needs more than one of those, put the policy in the domain package and keep `EngineRuntime` as the composition layer.
