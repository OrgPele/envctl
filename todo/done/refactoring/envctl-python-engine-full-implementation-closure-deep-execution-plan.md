# Envctl Python Engine Final 42 Percent Closure Execution Plan

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Close the remaining implementation gap (about 42 percent) to reach true full implementation, not just broad parity signaling.
  - Make strict release criteria green in clean-clone conditions with no waivers:
    - Python unit lane,
    - Python BATS parity lane,
    - shell prune contract,
    - release shipability gate.
  - Convert partial refactor scaffolding into real architecture boundaries with measurable reduction in coupling, duplication, and hidden fallback behavior.
  - Ensure operational reliability for real workloads, including Docker bind conflicts, stale state recovery, and repeated lifecycle command loops.
- Non-goals:
  - Rewriting downstream application code in managed repositories/worktrees.
  - Breaking existing command names/flag semantics without compatibility handling and migration documentation.
  - Enforcing optional third-party dependencies in baseline installs for first closure wave.
- Assumptions:
  - Python runtime remains authoritative under `/Users/kfiramar/projects/envctl/python/envctl_engine`.
  - Strict gates in `/Users/kfiramar/projects/envctl/python/envctl_engine/release_gate.py` and `/Users/kfiramar/projects/envctl/python/envctl_engine/shell_prune.py` are the source of truth for release readiness.
  - Runtime compatibility mode remains default `compat_read_write` from `/Users/kfiramar/projects/envctl/python/envctl_engine/config.py` until migration gates prove safe tightening.
  - Existing planning standards from `/Users/kfiramar/projects/envctl/docs/planning/README.md` remain mandatory.

## Goal (user experience)
Users running `envctl` (default), `envctl --plan`, `envctl --restart`, `envctl --resume`, `envctl --stop-all`, and `envctl --blast-all` should experience one coherent runtime: explicit mode overrides are honored, startup/health reflect real process ownership, requirement failures are actionable, cleanup is complete and idempotent, and state artifacts remain consistent across resumes/restarts without shell fallback surprises.

## Business logic and data model mapping
- Launcher and mode handoff:
  - `/Users/kfiramar/projects/envctl/lib/envctl.sh:envctl_main`
  - `/Users/kfiramar/projects/envctl/lib/engine/main.sh:exec_python_engine_if_enabled`
- CLI route parse and dispatch entry:
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/cli.py:run`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/command_router.py:parse_route`
  - route model: `Route(command, mode, raw_args, passthrough_args, projects, flags)`.
- Runtime command facade and orchestrator boundaries:
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/engine_runtime.py:PythonEngineRuntime.dispatch`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/startup_orchestrator.py:StartupOrchestrator.execute`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/resume_orchestrator.py:ResumeOrchestrator.execute`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/lifecycle_cleanup_orchestrator.py:LifecycleCleanupOrchestrator.execute`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/doctor_orchestrator.py:DoctorOrchestrator.execute`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/state_action_orchestrator.py:StateActionOrchestrator.execute`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/action_command_orchestrator.py:ActionCommandOrchestrator.execute`
- Process, listener truth, and port ownership:
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/process_runner.py:ProcessRunner`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/process_probe.py:ProcessProbe`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/ports.py:PortPlanner`
- Requirements lifecycle and retry/failure classes:
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/requirements_orchestrator.py:RequirementsOrchestrator.start_requirement`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/requirements/common.py:run_with_retry`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/requirements/postgres.py:start_postgres_container`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/requirements/redis.py:start_redis_container`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/requirements/n8n.py:start_n8n_container`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/requirements/supabase.py:start_supabase_container`
- State/artifact persistence and compatibility:
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/models.py` (`RunState`, `ServiceRecord`, `RequirementsResult`, `PortPlan`)
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/state_repository.py:RuntimeStateRepository`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/state.py`
- Release/migration governance:
  - `/Users/kfiramar/projects/envctl/docs/planning/python_engine_parity_manifest.json`
  - `/Users/kfiramar/projects/envctl/docs/planning/refactoring/envctl-shell-ownership-ledger.json`
  - `/Users/kfiramar/projects/envctl/scripts/verify_shell_prune_contract.py`
  - `/Users/kfiramar/projects/envctl/scripts/release_shipability_gate.py`

## Current behavior (verified in code)
- Verified hard blockers:
  - Launcher override bug:
    - `/Users/kfiramar/projects/envctl/lib/engine/main.sh:73` force-sets `ENVCTL_ENGINE_PYTHON_V1=true`.
    - BATS failure confirms behavior mismatch in `/Users/kfiramar/projects/envctl/tests/bats/python_engine_parity.bats` (case 2).
  - Strict shell-prune failure:
    - `unmigrated_count=619`, `max_unmigrated=0`, `phase=cutover` via `scripts/verify_shell_prune_contract.py`.
- Runtime decomposition remains incomplete:
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/engine_runtime.py` still 4049 LOC.
  - `PythonEngineRuntime` contains 251 methods.
  - Residual high-complexity methods in runtime:
    - `_start_requirement_component` (147 LOC)
    - `_apply_setup_worktree_selection` (117 LOC)
    - `_prepare_backend_runtime` (97 LOC)
    - `_run_interactive_command` (68 LOC)
- Orchestrators are still large and runtime-coupled:
  - `startup_orchestrator.py` top methods:
    - `start_project_services` (262 LOC)
    - `execute` (242 LOC)
    - `start_requirements_for_project` (121 LOC)
  - `doctor_orchestrator.py` top methods:
    - `readiness_gates` (143 LOC)
    - `execute` (133 LOC)
- Parser remains hand-rolled:
  - `parse_route` spans 350 LOC (lines 270-619 in `command_router.py`).
- Protocol boundary is not yet enforced:
  - `protocols.py` and `runtime_context.py` exist.
  - `RuntimeContext` is instantiated, but runtime still performs dynamic capability probing (`getattr` 49, `callable` 13 in runtime).
- State repository centralization is partial:
  - `RuntimeStateRepository` writes scoped/legacy artifacts.
  - Duplicate manual writes still exist in:
    - `/Users/kfiramar/projects/envctl/python/envctl_engine/resume_orchestrator.py` (legacy `run_state.json`/`runtime_map.json` writes)
    - `/Users/kfiramar/projects/envctl/python/envctl_engine/lifecycle_cleanup_orchestrator.py` (selected-stop writes)
  - Dead duplicate helper remains in runtime: `_write_legacy_runtime_compat_files` (defined, no callsites).
- Process-probe architecture is single-backend:
  - `process_probe.py` centralizes some logic, but no optional probe backend (e.g. psutil) is implemented.
- Requirements adapter consolidation is incomplete:
  - Shared helpers exist, but service modules remain large and duplicative:
    - postgres 331 LOC, redis 294 LOC, n8n 219 LOC, supabase 438 LOC.
- Terminal UI extraction is incomplete:
  - `terminal_ui.py` and `planning_menu.py` cover planning selection only.
  - Dashboard interactive loop still in runtime (`_run_interactive_dashboard_loop`, raw termios handlers).
- Metadata/governance mismatch:
  - Parity manifest reports all commands as `python_complete` (`14/14`).
  - `PythonEngineRuntime.PARTIAL_COMMANDS` is empty.
  - Despite this, strict release gates remain red due unresolved cutover blockers.
- Shell-ledger migration quality gap:
  - All `619` unmigrated entries currently map to one coarse owner pair:
    - `python/envctl_engine/engine_runtime.py#PythonEngineRuntime.dispatch`.
  - This owner granularity is too coarse for meaningful burn-down tracking.
- Shell-ledger wave distribution (current):
  - `wave-1: 100`, `wave-2: 88`, `wave-3: 285`, `wave-4: 146` unmigrated entries.
- Command coverage gap indicators (from test corpus scan):
  - `list-targets`: no explicit Python/BATS references.
  - `list-commands`: appears only in BATS parity file, no explicit Python unit tests.
- Field reliability incident: interactive restart in trees mode can replace a healthy multi-project run with partial stale state after one project fails startup.
  - Observed behavior:
    - interactive dashboard `r` (restart) stopped current healthy projects and restarted a different discovered trees set.
    - startup then failed on one project with `missing_service_start_command` (`autodetect_failed_backend`).
    - dashboard resumed on failed run state showing stale backend/frontend records and healthy n8n only.
  - Verified code path:
    - dashboard command dispatch: `/Users/kfiramar/projects/envctl/python/envctl_engine/dashboard_orchestrator.py:_run_interactive_command`.
    - restart flow: `/Users/kfiramar/projects/envctl/python/envctl_engine/startup_orchestrator.py:execute`.
    - restart re-discovers projects from filesystem instead of reusing previous run set:
      - `/Users/kfiramar/projects/envctl/python/envctl_engine/startup_orchestrator.py:79`.
      - project discovery source: `/Users/kfiramar/projects/envctl/python/envctl_engine/planning.py:discover_tree_projects`.
    - on partial startup failure, cleanup terminates started services but does not rollback to previous healthy run nor guarantee requirement teardown:
      - `/Users/kfiramar/projects/envctl/python/envctl_engine/startup_orchestrator.py:169-203`.
      - requirement containers can remain healthy while services become stale in persisted failed run state.

## Root cause(s) / gaps
1. Refactor wave 1 extracted entrypoints without fully moving domain ownership and dependency boundaries.
2. Runtime contract boundaries are typed but not enforced in implementation; dynamic probing still drives behavior.
3. State compatibility responsibilities are split between repository and orchestrators.
4. Parser complexity remains high and branch-driven, slowing safe evolution.
5. Cutover ledger tracking is not granular enough to represent real ownership migration progress.
6. Readiness metadata (`python_complete`, empty `PARTIAL_COMMANDS`) is not coupled strongly enough to strict gate success.
7. Requirements conflict handling is functional but not fully standardized for operator mitigation in real environments.
8. Terminal UX remains partially monolithic and harder to harden/test.
9. Command coverage for low-frequency routes (`list-targets`, `list-commands`) is shallow.
10. Restart semantics are non-deterministic in trees mode because restart target selection depends on current tree discovery, not prior run membership.
11. Restart is not transactional: a single project startup failure can permanently replace a previously healthy run with failed/stale state visibility.
12. Preflight validation of service start command resolvability is missing before tearing down currently healthy services during restart.
13. Interactive loop currently accepts failed restart state as current state source without rollback preference to last healthy run snapshot.

## Plan
### 1) Establish a measurable 42 percent closure scorecard
- Create an explicit closure scoreboard with weighted criteria:
  - Launcher contract and BATS parity closure: 10 points.
  - Shell-ledger strict cutover closure (619 -> 0): 20 points.
  - State repository full ownership and dedupe removal: 15 points.
  - Protocol/runtime-context enforcement and dynamic probe elimination: 15 points.
  - Runtime decomposition phase-2 completion: 10 points.
  - Declarative parser migration: 10 points.
  - Process probe backend abstraction and unification: 5 points.
  - Requirements adapter and bind-conflict mitigation completion: 10 points.
  - Terminal UI extraction completion: 5 points.
- Add score updates to changelog entries for each implementation PR.
- Acceptance checks:
  - Score only reaches 100 when strict shipability command passes with tests in clean clone.

### 2) Fix the immediate launcher parity blocker
- Code targets:
  - `/Users/kfiramar/projects/envctl/lib/engine/main.sh`
  - `/Users/kfiramar/projects/envctl/lib/envctl.sh`
  - `/Users/kfiramar/projects/envctl/tests/bats/python_engine_parity.bats`
- Implementation steps:
  - Remove unconditional assignment at `main.sh:73`.
  - Keep defaulting policy only in `envctl.sh`.
  - Add explicit tests for direct `main.sh` invocation with env override false.
- Edge cases and mitigations:
  - Direct shell script invocations expecting forced Python: provide migration note in changelog and docs.
- Acceptance checks:
  - All tests in `python_engine_parity.bats` pass.

### 3) Re-baseline shell ownership ledger for actionable migration tracking
- Code targets:
  - `/Users/kfiramar/projects/envctl/docs/planning/refactoring/envctl-shell-ownership-ledger.json`
  - `/Users/kfiramar/projects/envctl/scripts/generate_shell_ownership_ledger.py`
- Implementation steps:
  - Replace coarse owner mapping (`PythonEngineRuntime.dispatch`) with granular owner module/symbol mapping.
  - Ensure each entry references concrete Python owner symbol and evidence tests.
  - Re-group entries by implementation wave based on real code domain boundaries.
- Edge cases and mitigations:
  - Legacy generated entries with missing context: mark with explicit unresolved-owner notes and prioritize early.
- Acceptance checks:
  - No unmigrated entry remains mapped to coarse dispatch-level owner.

### 4) Execute shell-ledger burn-down waves to strict zero budget
- Wave A (state/lifecycle):
  - Targets: `state.sh`, `services_lifecycle.sh`, `ports.sh`, `services_logs.sh`.
  - Deliverables: Python ownership complete, shell function deletions, ledger status updates, tests.
- Wave B (requirements/docker):
  - Targets: `requirements_core.sh`, `requirements_supabase.sh`, `docker.sh`.
  - Deliverables: requirements and cleanup parity with robust diagnostics.
- Wave C (planning/actions/worktrees/ui):
  - Targets: `run_all_trees_helpers.sh`, `actions.sh`, `worktrees.sh`, `ui.sh`, `planning.sh`.
  - Deliverables: remove remaining behavior fallback points and UI shell coupling.
- Wave D (analysis/pr/testing infra libs):
  - Targets: `analysis.sh`, `pr.sh`, `test_runner.sh`, `tests.sh`, `core.sh`, `env.sh`, `debug.sh`.
- Acceptance checks per wave:
  - `verify_shell_prune_contract.py` with strict budgets remains green for completed wave scope.
  - no module marked `python_verified_delete_now` is still sourced.

### 5) Complete state repository ownership and remove duplicate write paths
- Code targets:
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/state_repository.py`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/resume_orchestrator.py`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/lifecycle_cleanup_orchestrator.py`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/engine_runtime.py`
- Implementation steps:
  - Add repository APIs for resume and selected-stop updates.
  - Replace direct file write operations in resume/cleanup orchestrators.
  - Remove `_write_legacy_runtime_compat_files` dead helper.
  - Centralize pointer normalization + precedence resolution in repository only.
- Edge cases and mitigations:
  - Corrupt pointers, missing run artifacts, mode mismatch during resume.
- Acceptance checks:
  - no direct writes to `run_state.json` or `runtime_map.json` from runtime/orchestrators outside repository.

### 6) Enforce protocols and runtime context in production code paths
- Code targets:
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/protocols.py`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/runtime_context.py`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/engine_runtime.py`
  - new adapters under `python/envctl_engine/`.
- Implementation steps:
  - Introduce explicit adapters that satisfy protocol contracts.
  - Route orchestrator dependencies through `RuntimeContext`.
  - Remove runtime-level `getattr/callable` probes except isolated compatibility shim locations.
- Edge cases and mitigations:
  - Existing tests monkeypatching partial objects: migrate to protocol-compatible fakes.
- Acceptance checks:
  - runtime dynamic-probe count near zero and isolated.

### 7) Runtime decomposition phase-2 (large residual method extraction)
- Code targets:
  - runtime and orchestrator/domain modules.
- Implementation steps:
  - Extract setup-worktree selection and planning sync domain from runtime.
  - Extract requirement component startup internals from runtime into dedicated domain service.
  - Extract backend/frontend preparation and command bootstrap logic.
  - Extract dashboard snapshot and status rendering helpers.
- Edge cases and mitigations:
  - avoid logic drift by no-behavior-change extraction PRs followed by targeted hardening PRs.
- Acceptance checks:
  - runtime method count and complexity materially reduced; high-risk methods moved.

### 8) Replace route parser with staged declarative pipeline
- Code targets:
  - `command_router.py`, `cli.py`.
- Implementation steps:
  - Implement phases: normalization, classification, command/mode resolution, flag binding, route finalization.
  - Preserve compatibility forms and strict unknown-token errors.
  - Add deterministic precedence rules for repeated/overlapping tokens.
- Edge cases and mitigations:
  - multi-token value flags, pair flags, env-style assignments, duplicate aliases.
- Acceptance checks:
  - parser contract matrix remains green with reduced branch complexity.

### 9) Complete utility consolidation and remove runtime-local parse helpers
- Code targets:
  - `parsing.py`, `env_access.py`, `node_tooling.py`, runtime and requirements modules.
- Implementation steps:
  - Remove runtime-private parse methods in favor of shared parsing utilities.
  - Ensure env access in requirements/runtime goes through `env_access`.
  - Keep package manager detection single-sourced.
- Acceptance checks:
  - no duplicated bool/int/float/env helper implementations remain.

### 10) Process probe hardening and backend abstraction
- Code targets:
  - `process_probe.py`, `process_runner.py`, lifecycle cleanup orchestrator.
- Implementation steps:
  - Add `ProbeBackend` abstraction with shell backend and optional psutil backend.
  - Normalize probe records with `backend`, `pid`, `listener_ports`, `ownership` fields.
  - Reuse identical probe service for truth reconciliation and blast-all sweeps.
- Edge cases and mitigations:
  - missing tools, permissions, platform differences.
- Acceptance checks:
  - no duplicated blast/truth listener parsing outside process_probe.

### 11) Requirements adapter framework completion and conflict mitigation
- Code targets:
  - requirements adapter modules and startup orchestrator integration.
- Implementation steps:
  - Extract reusable lifecycle template (discover state, start/restart/recreate, probe, classify failures).
  - Standardize event/reason emission for retry/failure classes.
  - Harden bind-conflict mitigation for user-reported postgres/redis collision scenarios:
    - deterministic rebind attempts,
    - optional safe cleanup for envctl-owned stale resources,
    - explicit error guidance when unresolved.
- Acceptance checks:
  - adapter duplication reduced and conflict behavior deterministic.

### 12) Finish terminal UI extraction
- Code targets:
  - `terminal_ui.py`, `dashboard_orchestrator.py`, runtime interactive methods.
- Implementation steps:
  - Move dashboard interactive command loop and raw tty handling out of runtime.
  - Keep robust non-tty fallback behavior.
  - retain no-color and width-safe rendering parity.
- Acceptance checks:
  - runtime no longer manages raw termios dashboard loop internals.

### 13) Strengthen observability schema and gate diagnostics
- Code targets:
  - runtime/orchestrator event emitters, docs.
- Implementation steps:
  - Normalize event families and reason-code enums.
  - Add schema version and backend mode fields in artifacts.
  - Ensure strict gate failures always emit machine-readable reason codes.
- Acceptance checks:
  - doctor/readiness output and artifacts are machine-triage complete.

### 14) Close low-frequency command coverage gaps
- Code targets:
  - tests under `tests/python` and `tests/bats`.
- Implementation steps:
  - Add explicit coverage for `list-targets` and `list-commands` command behavior.
  - Add command dispatch contract tests for all 21 supported commands and their owners.
- Acceptance checks:
  - every command in `list_supported_commands()` has at least one direct Python test and one BATS or integration assertion (where applicable).

### 15) Release-gate alignment and anti-overstatement policy
- Code targets:
  - parity manifest, shell ownership ledger, release gate logic.
- Implementation steps:
  - Block declaring `python_complete` for commands/modes until corresponding wave acceptance checks are green.
  - Keep strict defaults for shell budgets in CI.
  - Add manifest freshness checks (generated_at recency and proof references).
- Acceptance checks:
  - shipability passes with strict defaults and parity metadata truthfully reflects runtime behavior.

### 16) PR slicing and execution order
- PR-1: launcher contract fix + BATS parity closure.
- PR-2: ledger owner granularity rebaseline.
- PR-3: state repository full ownership + dead helper removal.
- PR-4: protocol adapters + runtime context enforcement.
- PR-5: runtime decomposition slice A (setup/planning).
- PR-6: runtime decomposition slice B (requirements startup internals).
- PR-7: parser staged migration.
- PR-8: utility dedupe completion.
- PR-9: process probe backend abstraction.
- PR-10: requirements adapter framework completion.
- PR-11: terminal UI extraction completion.
- PR-12+: shell-ledger migration waves A-D until zero unmigrated.
- PR-final: observability normalization + strict gate final verification.

### 17) Interactive restart determinism and rollback safety (new incident closure)
- Goal:
  - Ensure interactive/dashboard restart cannot degrade a previously healthy run into stale/partial state due to mixed project discovery or single-project command-resolution failures.
- Code targets:
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/startup_orchestrator.py`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/dashboard_orchestrator.py`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/engine_runtime.py`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/planning.py`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/state_repository.py`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/requirements_startup_domain.py`
- Implementation steps:
  - Add restart target contract:
    - default restart target set = projects from loaded prior run state (`project_roots` metadata and service names), not broad `discover_tree_projects()` output.
    - allow explicit opt-in for full rediscovery with a dedicated flag if needed (`--restart-rediscover`).
  - Add restart preflight phase before termination:
    - resolve backend/frontend start commands for every target project up-front.
    - validate requirement strategy availability per project (strict adapters or explicit command overrides).
    - fail restart fast before stopping current services if any target is non-startable.
  - Add transactional restart behavior:
    - stage restart in phases with checkpoint events:
      1) preflight,
      2) termination,
      3) startup,
      4) commit new run state.
    - if startup fails after termination:
      - attempt bounded rollback restore from prior state when commands remain resolvable,
      - otherwise preserve prior healthy state pointer as active and persist failed attempt under run history only.
  - Normalize failure-state persistence:
    - failed restart artifacts should not become default dashboard state when a healthy prior state exists and rollback succeeded.
    - include explicit `restart_failed` and `rollback_status` metadata fields.
  - Harden requirement cleanup on failed startup:
    - when a project started in the attempt is torn down due downstream failure, cleanup requirement resources for that project according to strict ownership rules.
  - Interactive dashboard safety:
    - after failed `restart`, keep current dashboard view bound to last healthy state unless user explicitly switches to failed run details.
- Edge cases and mitigations:
  - Mixed tree directories with unrelated experiments:
    - restart state membership lock prevents accidental inclusion.
  - Partial migration repos missing backend/frontend commands:
    - preflight fail with actionable per-project report before teardown.
  - Rollback failure after teardown:
    - persist machine-readable rollback failure reason and advise explicit `start --project ...` recovery sequence.
  - Concurrent interactive commands:
    - gate restart execution with runtime lock to prevent overlapping lifecycle mutations.
- Acceptance checks:
  - interactive `r` from healthy multi-project run never leaves dashboard on stale partial state due to unrelated project discovery.
  - restart failure in one project does not lose previous healthy run visibility.
  - restart emits deterministic phase events and rollback outcome reason codes.

## Tests (add these)
### Backend tests
- Extend `/Users/kfiramar/projects/envctl/tests/python/test_engine_runtime_command_parity.py`
  - assert command dispatch ownership for all 21 commands.
  - add direct `list-commands` and `list-targets` behavior assertions.
- Add `/Users/kfiramar/projects/envctl/tests/python/test_command_dispatch_matrix.py`
  - table-driven command -> orchestrator/handler mapping assertions.
- Extend `/Users/kfiramar/projects/envctl/tests/python/test_state_repository_contract.py`
  - resume and selected-stop write paths go through repository APIs only.
- Add `/Users/kfiramar/projects/envctl/tests/python/test_state_repository_update_paths.py`
  - repository path updates for resume/cleanup and compatibility pointers.
- Extend `/Users/kfiramar/projects/envctl/tests/python/test_runtime_context_protocols.py`
  - orchestrators consume dependencies via runtime context.
- Extend `/Users/kfiramar/projects/envctl/tests/python/test_command_router_contract.py`
  - parser precedence and compatibility forms across phased parser rewrite.
- Add `/Users/kfiramar/projects/envctl/tests/python/test_command_router_pipeline.py`
  - token normalization/classification unit contracts.
- Extend `/Users/kfiramar/projects/envctl/tests/python/test_process_probe_contract.py`
  - backend abstraction result normalization and fallback tags.
- Add `/Users/kfiramar/projects/envctl/tests/python/test_process_probe_backend_selection.py`
  - shell/optional backend selection behavior.
- Extend `/Users/kfiramar/projects/envctl/tests/python/test_requirements_adapter_base.py`
  - shared lifecycle contract across all requirement adapters.
- Add `/Users/kfiramar/projects/envctl/tests/python/test_requirements_conflict_mitigation.py`
  - postgres/redis conflict scenarios and safe remediation policy.
- Extend `/Users/kfiramar/projects/envctl/tests/python/test_utility_consolidation_contract.py`
  - ensure runtime parse/env helper duplicates are removed.
- Add `/Users/kfiramar/projects/envctl/tests/python/test_restart_transactional_safety.py`
  - restart preflight rejects unresolved backend/frontend commands before terminating healthy state.
  - restart targets derived from prior run state, not broad tree discovery by default.
  - failed restart keeps prior healthy state as active snapshot when rollback succeeds.
- Add `/Users/kfiramar/projects/envctl/tests/python/test_restart_project_membership_contract.py`
  - verifies `project_roots`/service-derived restart membership handling and explicit `--restart-rediscover` override behavior.
- Extend `/Users/kfiramar/projects/envctl/tests/python/test_engine_runtime_real_startup.py`
  - regression case for interactive restart reproducing stale-state incident and asserting fixed behavior.

### Frontend tests
- Extend `/Users/kfiramar/projects/envctl/tests/python/test_interactive_input_reliability.py`
  - extracted dashboard loop behavior under tty/non-tty.
- Extend `/Users/kfiramar/projects/envctl/tests/python/test_dashboard_render_alignment.py`
  - rendering invariants after UI extraction.
- Extend `/Users/kfiramar/projects/envctl/tests/python/test_planning_menu_rendering.py`
  - deterministic selection and cursor movement.
- Add `/Users/kfiramar/projects/envctl/tests/python/test_terminal_ui_dashboard_loop.py`
  - command loop handling and fallback behavior.
- Extend `/Users/kfiramar/projects/envctl/tests/python/test_interactive_input_reliability.py`
  - restart failure in interactive loop preserves healthy state context and prints deterministic remediation output.

### Integration/E2E tests
- Extend `/Users/kfiramar/projects/envctl/tests/bats/python_engine_parity.bats`
  - direct launcher override matrix and fallback behavior.
- Extend `/Users/kfiramar/projects/envctl/tests/bats/python_state_repository_compat_e2e.bats`
  - repository-owned writes in resume/stop paths.
- Extend `/Users/kfiramar/projects/envctl/tests/bats/python_process_probe_fallback_e2e.bats`
  - backend selection and fallback telemetry.
- Extend `/Users/kfiramar/projects/envctl/tests/bats/python_requirements_conflict_recovery.bats`
  - user-facing bind conflict mitigation behavior.
- Extend `/Users/kfiramar/projects/envctl/tests/bats/python_stop_blast_all_parity_e2e.bats`
  - unified cleanup via probe + repository paths.
- Extend `/Users/kfiramar/projects/envctl/tests/bats/python_shell_prune_e2e.bats`
  - wave-by-wave zero-budget enforcement.
- Add `/Users/kfiramar/projects/envctl/tests/bats/python_list_commands_targets_parity_e2e.bats`
  - explicit low-frequency command behavior coverage.
- Add `/Users/kfiramar/projects/envctl/tests/bats/python_release_gate_strict_closure_e2e.bats`
  - strict shipability passes only when all closure criteria are met.
- Add `/Users/kfiramar/projects/envctl/tests/bats/python_restart_transactional_safety_e2e.bats`
  - create healthy multi-project trees run, inject one project with unresolved backend command, assert:
    - restart preflight fails before teardown, or rollback restores healthy state,
    - no stale-only dashboard replacement occurs,
    - requirements/service cleanup ownership contract holds.

## Observability / logging (if relevant)
- Required normalized event families:
  - `route.parse.start`, `route.parse.fail`, `route.parse.resolved`
  - `startup.phase.begin`, `startup.phase.fail`, `startup.phase.success`
  - `requirements.adapter.retry`, `requirements.adapter.fail_class`
  - `service.truth.check`, `service.truth.degraded`, `service.truth.rebound`
  - `state.repo.read_path`, `state.repo.write_path`, `state.repo.compat_mode`
  - `cleanup.phase.start`, `cleanup.phase.finish`, `cleanup.phase.skip_reason`
  - `gate.shipability.fail_reason`, `gate.shell_prune.fail_reason`
  - `restart.phase.begin`, `restart.phase.preflight_fail`, `restart.phase.terminate`, `restart.phase.startup_fail`, `restart.phase.rollback`, `restart.phase.commit`
- Artifact schema additions:
  - `schema_version`, `probe_backend`, `state_compat_mode`, `runtime_truth_mode`, `reason_code`.
  - restart attempt metadata: `restart_source_run_id`, `restart_target_projects`, `rollback_attempted`, `rollback_status`.
- Diagnostic requirements:
  - strict failures must include machine-parsable reason payload and first actionable remediation hint.

## Rollout / verification
- Required verification commands (repo root):
  - `./.venv/bin/python -m unittest discover -s tests/python -p 'test_*.py'`
  - `bats --print-output-on-failure tests/bats/python_*.bats tests/bats/parallel_trees_python_e2e.bats`
  - `./.venv/bin/python scripts/verify_shell_prune_contract.py --repo .`
  - `./.venv/bin/python scripts/release_shipability_gate.py --repo . --check-tests`
- Phase gates:
  - Gate 0: baseline metrics captured and committed (current blockers and counts).
  - Gate 1: launcher parity fixed, BATS parity lane all green.
  - Gate 2: ledger owner granularity corrected and Wave A closure complete.
  - Gate 3: state repository ownership complete and duplicate write paths removed.
  - Gate 4: protocol enforcement + runtime decomposition slices complete.
  - Gate 5: parser and utility dedupe migration complete.
  - Gate 6: process probe + requirements framework hardening complete.
  - Gate 7: terminal UI extraction and low-frequency command coverage complete.
  - Gate 8: shell-ledger zero-budget strict pass and shipability strict pass.
- Operational confidence checks:
  - repeated lifecycle loop tests under both modes.
  - port conflict tests (postgres/redis and service listeners).
  - cross-repo runtime scope isolation checks.
  - interactive dashboard restart loop under mixed tree inventories and partial command resolvability.

## Definition of done
- Launcher override behavior is correct and parity-tested.
- Shell prune strict cutover contract passes with zero unmigrated entries.
- State repository solely owns compatibility/state artifact writes.
- Runtime boundaries are protocol-driven with minimal dynamic probing.
- Runtime monolith high-complexity domains are extracted.
- Parser migration complete and compatibility matrix green.
- Process truth/cleanup share one probe subsystem with backend tagging.
- Requirements adapters follow shared lifecycle framework with deterministic conflict mitigation.
- Terminal dashboard loop is externalized and test-covered.
- Every supported command has direct behavior coverage, including `list-targets` and `list-commands`.
- Strict release shipability gate passes with tests in clean clone.
- Restart is deterministic and transactional: healthy run state is not replaced by stale partial artifacts on restart failure.

## Risk register (trade-offs or missing tests)
- Risk: 619-entry shell-ledger debt is large and can hide stale ownership assumptions.
  - Mitigation: owner-granularity rebaseline before wave execution; strict per-wave gates.
- Risk: boundary enforcement breaks tests using partial fakes.
  - Mitigation: protocol-aligned adapters and staged fixture migration.
- Risk: parser migration may break tolerated legacy forms.
  - Mitigation: compatibility fixtures and targeted error messaging for rejected forms.
- Risk: optional backend probes create environment variance.
  - Mitigation: explicit fallback lanes and backend tagging.
- Risk: conflict cleanup could remove non-envctl resources.
  - Mitigation: strict envctl ownership checks and opt-in cleanup policy.
- Risk: restart rollback logic can introduce state-pointer complexity and split-brain artifacts.
  - Mitigation: explicit restart phase state machine, single commit point, and dedicated rollback metadata plus contract tests.

## Open questions (only if unavoidable)
- Do we want temporary non-zero shell budgets during waves or maintain strict-zero throughout and accept potentially larger PR batches?
- Should optional probe/TTY dependencies be validated in default CI lanes during closure, or remain in dedicated optional-capability lanes until post-cutover stabilization?
