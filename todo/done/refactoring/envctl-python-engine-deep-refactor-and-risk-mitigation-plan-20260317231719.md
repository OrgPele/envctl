# Envctl Python Engine Deep Refactor and Risk-Mitigation Implementation Plan

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Reduce defect probability in the Python runtime by decomposing high-risk monolith paths, eliminating duplicated logic, and introducing explicit contracts between orchestration domains.
  - Preserve user-facing `envctl` behavior while making runtime truth, startup reliability, lifecycle cleanup, and state compatibility safer and easier to reason about.
  - Replace fragile custom parsing/probing where practical with well-supported libraries or constrained adapter layers.
  - Establish a phased rollout that minimizes regression blast radius and keeps strict observability for cutover/readiness decisions.
- Non-goals:
  - Rewriting downstream application code under managed project worktrees.
  - Breaking command surface/flags in one release without compatibility layer.
  - Immediate removal of all legacy runtime compatibility artifacts before migration gates prove parity.
- Assumptions:
  - Python runtime remains authoritative under `/Users/kfiramar/projects/envctl/python/envctl_engine`.
  - Existing cutover and shipability gates remain the authoritative release checks (`release_gate.py`, `shell_prune.py`).
  - Dependency additions are allowed when they materially reduce reliability risk; each optional third-party dependency must have stdlib fallback or explicit feature flag.

## Goal (user experience)
A user running `envctl --plan`, `envctl --start`, `envctl --resume`, `envctl --stop-all`, or `envctl --blast-all` should experience deterministic startup and truthful status every time: no silent worktree creation failures, no false-healthy services, no stale state surprises, no parser drift across alias forms, and no cleanup commands that leave hidden residue.

## Business logic and data model mapping
- Command intake and route mapping:
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/cli.py:run`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/command_router.py:parse_route`
  - Current command contract output from `Route(command, mode, projects, flags, passthrough_args)`.
- Core orchestration authority:
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/engine_runtime.py:PythonEngineRuntime.dispatch`
  - Startup/resume/doctor/dashboard/actions/lifecycle cleanup currently co-located.
- Data models:
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/models.py`
    - `PortPlan`
    - `ServiceRecord`
    - `RequirementsResult`
    - `RunState`
- State and compatibility IO:
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/state.py`
  - Runtime artifact write/read/cleanup paths in `engine_runtime.py` (`_write_artifacts`, `_write_legacy_runtime_compat_files`, `_try_load_existing_state`, `_clear_runtime_state`).
- Port and listener truth domain:
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/ports.py:PortPlanner`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/process_runner.py:ProcessRunner`
  - Runtime truth resolution in `/Users/kfiramar/projects/envctl/python/envctl_engine/engine_runtime.py:_service_truth_status`.
- Requirements orchestration domain:
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/requirements_orchestrator.py`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/requirements/postgres.py`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/requirements/redis.py`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/requirements/n8n.py`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/requirements/supabase.py`
- Service startup domain:
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/service_manager.py`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/command_resolution.py`
- Cutover/readiness governance:
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/release_gate.py`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/shell_prune.py`
  - Doctor gates in `/Users/kfiramar/projects/envctl/python/envctl_engine/engine_runtime.py:_doctor_readiness_gates`

## Current behavior (verified in code)
- Runtime complexity is concentrated in one file:
  - `engine_runtime.py` is ~6071 LOC; largest methods include:
    - `_start_project_services` (`~244` lines)
    - `_start` (`~223` lines)
    - `_doctor` (`~147` lines)
    - `_start_requirements_for_project` (`~121` lines)
  - Evidence: `/Users/kfiramar/projects/envctl/python/envctl_engine/engine_runtime.py`.
- Parser complexity and drift risk:
  - `parse_route` is ~356 lines in `/Users/kfiramar/projects/envctl/python/envctl_engine/command_router.py:242`.
  - Duplicate branch exists for `frontend-test-runner=` handling at lines `484-490`.
- Correctness bug with hidden failure:
  - `_create_single_worktree` in `/Users/kfiramar/projects/envctl/python/envctl_engine/engine_runtime.py:433` falls back to creating placeholder directories when `git worktree add` fails, but returns success (`None`), enabling silent partial failure.
- Runtime depends on capability probing instead of explicit contracts:
  - many `getattr(..., callable)` checks in `engine_runtime.py` for `wait_for_port`, `wait_for_pid_port`, `pid_owns_port`, `listener_pids_for_port`, `terminate`, and planner release methods.
- Listener/process truth is duplicated and shell-output driven:
  - process ownership and port parsing in `/Users/kfiramar/projects/envctl/python/envctl_engine/process_runner.py`.
  - separate blast-all parsing and `lsof` scans in `/Users/kfiramar/projects/envctl/python/envctl_engine/engine_runtime.py:4377-4484`.
- State/artifact compatibility logic is spread across write/read/cleanup paths:
  - write scoped+legacy: `engine_runtime.py:2251-2357`
  - read scoped+legacy pointers/files: `engine_runtime.py:2359-2432`
  - cleanup scoped+legacy artifacts: `engine_runtime.py:4291-4314`
- Utility duplication is widespread:
  - parsing helpers duplicated in `config.py`, `engine_runtime.py`, `state.py`, `command_resolution.py`.
  - package manager detection duplicated in `command_resolution.py` and `actions_test.py`.
  - `_str_from_env` duplicated in requirements modules.
- Requirement adapters have high duplication:
  - similar container lifecycle/restart/recreate/probe flow in `postgres.py`, `redis.py`, `n8n.py`.
- Interactive UI/TTY code is manual and high-maintenance:
  - raw mode, key decoding, ANSI rendering in `engine_runtime.py:792-1036`.
- Test architecture reflects runtime coupling breadth:
  - large fake runners and broad behavior simulation in:
    - `/Users/kfiramar/projects/envctl/tests/python/test_engine_runtime_real_startup.py`
    - `/Users/kfiramar/projects/envctl/tests/python/test_lifecycle_parity.py`
    - `/Users/kfiramar/projects/envctl/tests/python/test_runtime_health_truth.py`

## Root cause(s) / gaps
1. `PythonEngineRuntime` contains multiple bounded contexts in one class, creating intertwined side effects and making safe changes expensive.
2. Contracts between runtime and adapters are implicit, producing defensive `getattr` logic instead of enforceable interfaces.
3. Critical behaviors (parsing, state compatibility, process truth) are duplicated across modules and diverge over time.
4. Current shell/process parsing strategy (`lsof`, `ps`, regex) is brittle and platform-sensitive.
5. Legacy-compat behavior is implemented ad-hoc in multiple call paths instead of behind one migration repository boundary.
6. Parser is hand-rolled with high branch complexity, making parity drift and hidden duplicates likely.
7. Requirements adapters repeat complex flow with slight variations, making bug fixes expensive and inconsistent.
8. Test surfaces are broad because production interfaces are broad; this slows iteration and hides architectural responsibilities.

## Plan
### 1) Stabilize immediate correctness and safety defects before large refactors
- Code targets:
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/engine_runtime.py:_create_single_worktree`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/command_router.py:parse_route`
- Implementation steps:
  - Fix `_create_single_worktree` to return explicit error on `git worktree add` failure and remove placeholder-success fallback in strict mode.
  - Add an opt-in compatibility fallback flag for placeholder behavior if needed during transition (`ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK=false` by default).
  - Remove duplicate `frontend-test-runner` branch in parser and add dedupe assertions for alias/flag registries.
- Edge cases and mitigations:
  - Existing scripts relying on placeholder directories: gated by explicit fallback env flag and warning event.
  - Parser behavior drift: snapshot tests for accepted argv permutations before/after fix.
- Acceptance checks:
  - Worktree creation failure yields actionable non-zero failure.
  - Parser deterministic for duplicate alias inputs and no duplicated flag branches.

### 2) Introduce explicit architecture boundaries with typed protocols
- Code targets:
  - new modules under `/Users/kfiramar/projects/envctl/python/envctl_engine/`:
    - `protocols.py`
    - `runtime_context.py`
  - integration points in `engine_runtime.py`, `process_runner.py`, `ports.py`, `service_manager.py`, `requirements_orchestrator.py`.
- Implementation steps:
  - Define Protocols for:
    - `ProcessRuntime` (`run`, `start`, `terminate`, `is_pid_running`, `wait_for_port`, listener queries)
    - `PortAllocator` (`reserve_next`, `release`, `release_session`, `release_all`)
    - `StateRepository` (`save_run`, `load_latest`, `load_by_pointer`, `purge`)
    - `TerminalUI` (plan selection, dashboard interactive loop)
  - Replace scattered `getattr/callable` checks with protocol-compliant adapters and explicit fallback adapters.
- Edge cases and mitigations:
  - Backward compatibility for tests with partial fakes: provide lightweight adapter shims to preserve old fake methods temporarily.
- Acceptance checks:
  - `engine_runtime.py` no longer directly probes runtime capabilities through repeated `getattr` checks.

### 3) Extract artifact/state compatibility into a single repository layer
- Code targets:
  - new module: `/Users/kfiramar/projects/envctl/python/envctl_engine/state_repository.py`
  - call sites in `engine_runtime.py` and `state.py`.
- Implementation steps:
  - Centralize all scoped/legacy writes, pointer management, read-order precedence, and cleanup behavior.
  - Move logic from:
    - `_write_artifacts`
    - `_write_legacy_runtime_compat_files`
    - `_try_load_existing_state`
    - `_clear_runtime_state`
  - Add explicit migration modes:
    - `compat_read_write`
    - `compat_read_only`
    - `scoped_only`.
- Edge cases and mitigations:
  - Corrupt pointer files and mixed mode resumes: repository returns typed error classes and emits deterministic diagnostics.
- Acceptance checks:
  - No duplicate compatibility logic remains in runtime orchestration methods.

### 4) Decompose `PythonEngineRuntime` into bounded orchestrators
- Code targets:
  - new modules:
    - `/Users/kfiramar/projects/envctl/python/envctl_engine/startup_orchestrator.py`
    - `/Users/kfiramar/projects/envctl/python/envctl_engine/resume_orchestrator.py`
    - `/Users/kfiramar/projects/envctl/python/envctl_engine/doctor_orchestrator.py`
    - `/Users/kfiramar/projects/envctl/python/envctl_engine/lifecycle_cleanup_orchestrator.py`
    - `/Users/kfiramar/projects/envctl/python/envctl_engine/dashboard_orchestrator.py`
- Implementation steps:
  - Keep `PythonEngineRuntime.dispatch` as facade only.
  - Move startup, resume, doctor, cleanup, dashboard flows into modules with narrow dependencies.
  - Use `RuntimeContext` composition object to inject config, repos, planner, and adapter protocols.
- Edge cases and mitigations:
  - Behavior drift risk from large move: execute as no-logic-change extraction slices, one command family per PR.
- Acceptance checks:
  - `engine_runtime.py` reduced to orchestration shell with no high-complexity logic bodies.

### 5) Replace ad-hoc parser with declarative command grammar while preserving compatibility
- Code targets:
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/command_router.py`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/cli.py`
- Implementation steps:
  - Implement declarative spec tables for:
    - commands and aliases
    - mode toggles
    - boolean/value/pair flags
    - env-style assignments.
  - Build parser pipeline:
    - token normalize
    - token classify
    - command/mode resolve
    - flag/value bind
    - route finalize.
  - Keep unsupported token handling strict with actionable errors.
- Library strategy:
  - Default: stdlib parser engine (no dependency).
  - Optional follow-up: `argparse`/subcommands migration if alias coverage can be preserved.
- Edge cases and mitigations:
  - Existing permissive token forms (`FOO=bar`, implicit commands): encode compatibility fixtures before migration.
- Acceptance checks:
  - parser contract test matrix covers all current supported flags and alias forms.

### 6) Consolidate duplicated utility logic and configuration parsing
- Code targets:
  - new utility modules:
    - `/Users/kfiramar/projects/envctl/python/envctl_engine/parsing.py`
    - `/Users/kfiramar/projects/envctl/python/envctl_engine/node_tooling.py`
    - `/Users/kfiramar/projects/envctl/python/envctl_engine/env_access.py`
  - adopt in `config.py`, `command_resolution.py`, `actions_test.py`, requirements adapters.
- Implementation steps:
  - unify `parse_bool/int/float` with one canonical implementation.
  - unify package manager detection and package.json loading.
  - unify `str_from_env`/numeric env extraction across requirements modules.
- Library strategy:
  - Default: stdlib consolidation.
  - Optional: `pydantic-settings` for typed env parsing in `EngineConfig` after baseline consolidation.
- Edge cases and mitigations:
  - bool parsing semantics drift: lock with compatibility tests for accepted truthy/falsey strings.
- Acceptance checks:
  - duplicate helper definitions removed from runtime/config/requirements modules.

### 7) Harden process and listener truth through a dedicated probe subsystem
- Code targets:
  - new module: `/Users/kfiramar/projects/envctl/python/envctl_engine/process_probe.py`
  - wrappers around `process_runner.py` and blast-all paths in `engine_runtime.py`.
- Implementation steps:
  - centralize listener probes, process-tree queries, PID ownership checks, and liveness policies.
  - refactor blast-all to reuse shared probe service instead of custom parsing path.
- Library strategy:
  - Primary option: add `psutil` for process tree + socket/listener introspection.
  - fallback option: existing `lsof`/`ps` path via adapter when `psutil` unavailable.
- Edge cases and mitigations:
  - macOS/Linux differences: platform capability detection and telemetry for fallback mode.
- Acceptance checks:
  - truth checks and blast-all sweeps share one probe implementation and return normalized records.

### 8) Introduce reusable requirement-adapter framework
- Code targets:
  - new base module: `/Users/kfiramar/projects/envctl/python/envctl_engine/requirements/adapter_base.py`
  - refactor `postgres.py`, `redis.py`, `n8n.py`, `supabase.py`.
- Implementation steps:
  - extract shared lifecycle stages:
    - resolve existing container/compose state
    - verify mapped port contract
    - start/restart/recreate policy
    - readiness probe loop
    - structured failure classification.
  - define per-service specialization only for:
    - create/start args
    - readiness probe command
    - retryable token set
    - strict vs soft failures.
- Library strategy:
  - Optional use of `tenacity` for standardized backoff/retry envelopes.
  - Optional Docker SDK/`python-on-whales` for typed Docker interaction; retain CLI adapter fallback.
- Edge cases and mitigations:
  - supabase multi-service behavior complexity: keep dedicated adapter but inherit probe/retry utilities.
- Acceptance checks:
  - duplicate restart/recreate/probe logic minimized and behavior parity preserved by adapter contract tests.

### 9) Move terminal UI to dedicated module and reduce raw TTY risk
- Code targets:
  - new module(s):
    - `/Users/kfiramar/projects/envctl/python/envctl_engine/terminal_ui.py`
    - `/Users/kfiramar/projects/envctl/python/envctl_engine/planning_menu.py`
- Implementation steps:
  - isolate plan selection rendering and key handling from core runtime.
  - keep non-TTY-safe fallback snapshot behavior.
  - reduce manual ANSI control and escape parsing burden.
- Library strategy:
  - Optional: `prompt_toolkit` for input and key map reliability.
  - Optional: `rich` for rendering dashboard/menu while preserving NO_COLOR behavior.
- Edge cases and mitigations:
  - terminals with partial escape support: degrade gracefully to numbered prompt selection in non-raw mode.
- Acceptance checks:
  - interactive flows are testable outside full runtime startup.

### 10) Normalize observability and diagnostic reason codes
- Code targets:
  - `engine_runtime.py` event emission + new event schema docs.
  - `release_gate.py`, `shell_prune.py`, doctor outputs.
- Implementation steps:
  - define stable event names and reason enums for:
    - parser failures
    - startup requirement/service failures
    - listener-truth degradations
    - compatibility state fallback usage
    - cleanup phase outcomes.
  - ensure all strict gate failures emit machine-readable reason codes, not only free-form text.
- Edge cases and mitigations:
  - legacy event consumers: maintain backward-compatible fields and add versioned payload schema.
- Acceptance checks:
  - doctor and run artifacts present enough structured context for automated cutover triage.

### 11) Align test architecture to new boundaries and increase high-value coverage
- Code targets:
  - existing tests under `/Users/kfiramar/projects/envctl/tests/python` and `/Users/kfiramar/projects/envctl/tests/bats`.
- Implementation steps:
  - reduce giant fake surface by using protocol-targeted test doubles per orchestrator.
  - add contract tests for parser, state repository, process probe, requirement adapters, and lifecycle cleanup.
  - maintain parity BATS suites while adding new scenario-focused files.
- Edge cases and mitigations:
  - long-running integration suite costs: split CI lanes (`fast-contract`, `parity-e2e`, `strict-cutover`).
- Acceptance checks:
  - critical regressions caught by narrow tests before full runtime E2E.

### 12) Rollout sequence with explicit risk gates and fallback controls
- Phase A: Safety patches and architecture scaffolding.
- Phase B: State repository + parser refactor + utility consolidation.
- Phase C: Process probe + requirement adapter framework + runtime decomposition.
- Phase D: UI extraction + strict observability + compatibility tightening.
- Phase E: Optional dependency adoption finalization (`psutil`, `pydantic-settings`, `prompt_toolkit`, `tenacity`, Docker SDK).
- Rollback controls:
  - keep compatibility mode toggles and shell fallback until Gate D stability criteria are met.
  - each phase must support reverting to last stable tag with unchanged artifact schema.

## Tests (add these)
### Backend tests
- Extend:
  - `/Users/kfiramar/projects/envctl/tests/python/test_engine_runtime_real_startup.py`
    - assert worktree creation hard-fail semantics and event reason outputs.
    - assert no silent fallback when strict mode disables placeholder worktree behavior.
  - `/Users/kfiramar/projects/envctl/tests/python/test_lifecycle_parity.py`
    - cover unified blast-all probe behavior and idempotent cleanup via new cleanup orchestrator.
  - `/Users/kfiramar/projects/envctl/tests/python/test_runtime_health_truth.py`
    - validate shared probe subsystem behavior (`pid_owns_port`, listener fallbacks, stale transitions).
  - `/Users/kfiramar/projects/envctl/tests/python/test_requirements_orchestrator.py`
    - enforce failure-class mapping parity under new adapter framework.
  - `/Users/kfiramar/projects/envctl/tests/python/test_release_shipability_gate.py`
    - verify strict reasons remain machine-readable after event/schema changes.
- Add:
  - `/Users/kfiramar/projects/envctl/tests/python/test_command_router_contract.py`
    - full parser matrix + duplicate token invariants.
  - `/Users/kfiramar/projects/envctl/tests/python/test_state_repository_contract.py`
    - scoped/legacy read/write precedence and cleanup behavior.
  - `/Users/kfiramar/projects/envctl/tests/python/test_process_probe_contract.py`
    - normalized listener/pid behavior under psutil and fallback adapters.
  - `/Users/kfiramar/projects/envctl/tests/python/test_requirements_adapter_base.py`
    - shared restart/recreate/probe policies across services.
  - `/Users/kfiramar/projects/envctl/tests/python/test_utility_consolidation_contract.py`
    - canonical parse/env helpers and package manager detection semantics.

### Frontend tests
- This repository does not include a browser frontend for this runtime; treat terminal UX as frontend surface.
- Extend/add terminal-facing tests:
  - `/Users/kfiramar/projects/envctl/tests/python/test_interactive_input_reliability.py`
    - verify menu key handling and drain behavior with extracted UI module.
  - `/Users/kfiramar/projects/envctl/tests/python/test_dashboard_render_alignment.py` (new)
    - verify width truncation, row stability, status badge consistency, NO_COLOR behavior.
  - `/Users/kfiramar/projects/envctl/tests/python/test_planning_menu_rendering.py` (new)
    - verify deterministic cursor/selection behavior for long plan lists.

### Integration/E2E tests
- Extend:
  - `/Users/kfiramar/projects/envctl/tests/bats/python_engine_parity.bats`
    - parser + lifecycle parity checks under refactored orchestrators.
  - `/Users/kfiramar/projects/envctl/tests/bats/parallel_trees_python_e2e.bats`
    - verify no port collisions and truthful status under decomposed startup path.
  - `/Users/kfiramar/projects/envctl/tests/bats/python_stop_blast_all_parity_e2e.bats`
    - assert unified cleanup contract across repeated invocations.
- Add:
  - `/Users/kfiramar/projects/envctl/tests/bats/python_state_repository_compat_e2e.bats`
    - verify scoped/legacy compatibility modes and pointer migration behavior.
  - `/Users/kfiramar/projects/envctl/tests/bats/python_process_probe_fallback_e2e.bats`
    - verify behavior when psutil unavailable and fallback path in use.
  - `/Users/kfiramar/projects/envctl/tests/bats/python_requirements_adapter_parity_e2e.bats`
    - run conflict/restart/recreate scenarios consistently for postgres/redis/n8n/supabase.

## Observability / logging (if relevant)
- Add/standardize required event categories:
  - `route.parse.start`, `route.parse.fail`, `route.parse.resolved`
  - `startup.phase.begin`, `startup.phase.fail`, `startup.phase.success`
  - `requirements.adapter.retry`, `requirements.adapter.fail_class`
  - `service.truth.check`, `service.truth.degraded`, `service.truth.rebound`
  - `state.repo.read_path`, `state.repo.write_path`, `state.repo.compat_mode`
  - `cleanup.phase.start`, `cleanup.phase.finish`, `cleanup.phase.skip_reason`
- Ensure run artifact schema includes:
  - explicit compatibility mode
  - gate profile
  - failure reason codes
  - probe backend (`psutil` or `shell_fallback`).
- Add event schema documentation in docs and keep JSONL payload backward-compatible with additive fields.

## Rollout / verification
- Verification commands (strict lane, from repo root):
  - `./.venv/bin/python -m unittest discover -s tests/python -p 'test_*.py'`
  - `bats --print-output-on-failure tests/bats/python_*.bats tests/bats/parallel_trees_python_e2e.bats`
  - `./.venv/bin/python scripts/verify_shell_prune_contract.py --repo .`
  - `./.venv/bin/python scripts/release_shipability_gate.py --repo . --check-tests`
- Phase gates:
  - Gate 0: baseline snapshot and invariant lock (parser matrix, state compatibility behavior).
  - Gate 1: safety patches merged with no regressions.
  - Gate 2: state repository + parser + utility consolidation stable in CI.
  - Gate 3: process probe + requirement adapter framework stable on macOS/Linux CI.
  - Gate 4: runtime decomposition complete with unchanged user-visible behavior.
  - Gate 5: optional dependency lanes enabled and verified; fallback paths still green.
  - Gate 6: compatibility mode can be switched from `compat_read_write` to `compat_read_only` safely.
- Production/readiness verification:
  - run doctor in strict mode and confirm gate-by-gate reason integrity.
  - validate repeated `start -> resume -> restart -> stop-all -> blast-all` loops leave no orphaned runtime artifacts or stale locks.

## Definition of done
- Known correctness defects (worktree silent-success, parser duplicate handling) are fixed and covered.
- `PythonEngineRuntime` is decomposed into bounded orchestrators with explicit protocol-driven dependencies.
- Shared utilities replace duplicate parsing/env/node tooling implementations.
- State/artifact compatibility behavior is centralized and configurable by explicit mode.
- Process/listener truth uses one normalized probe subsystem and produces consistent status outcomes.
- Requirements adapters share lifecycle framework with per-service specialization only where required.
- Terminal UI behavior is testable in isolation and no longer deeply coupled to startup orchestration.
- Strict gate/doctor diagnostics are machine-readable and operationally actionable.
- Full unit + parity E2E suites are green in strict profile.

## Risk register (trade-offs or missing tests)
- Risk: Introducing external dependencies (`psutil`, `pydantic-settings`, `prompt_toolkit`, `tenacity`, Docker SDK) may increase packaging complexity.
  - Mitigation: stage adoption behind capability adapters and maintain stdlib/CLI fallback paths until CI matrix is stable.
- Risk: Runtime decomposition can change subtle ordering/timing behavior.
  - Mitigation: no-logic-change extraction phases with exhaustive contract tests at each boundary.
- Risk: Strict worktree failure behavior could break implicit workflows that expected placeholder dirs.
  - Mitigation: compatibility toggle for one transition window plus explicit deprecation timeline.
- Risk: Parser tightening can reject historically tolerated malformed inputs.
  - Mitigation: lock current accepted token set with parser matrix tests before any strictness increase.
- Risk: Compatibility-mode simplification may miss edge legacy pointer/state patterns.
  - Mitigation: dedicated compatibility E2E suite and telemetry for fallback path usage.
- Risk: Probe-layer unification may still exhibit OS-specific edge behavior.
  - Mitigation: dual-backend probe design (`psutil` and shell fallback), per-platform CI assertions, and probe backend tagging in artifacts.

## Open questions (only if unavoidable)
- Are new third-party dependencies acceptable for the default install profile, or should they remain optional extras with fallback adapters for the first rollout phases?
- What is the target deadline for switching default compatibility mode from `compat_read_write` to `compat_read_only`?
