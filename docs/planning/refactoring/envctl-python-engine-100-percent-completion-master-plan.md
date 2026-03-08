# Envctl Python Engine 100% Completion Master Plan

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Complete the `envctl` refactor and migration so Python is the true execution engine for real workflows, not only nominal routing ownership.
  - Close all verified correctness, lifecycle, parity, and usability gaps that still block "100% complete" status.
  - Preserve the public `envctl` CLI contract while improving determinism, safety, and operability across `main`, `trees`, and `--plan` modes.
  - Ensure branch/release reproducibility from committed code and tests (no local-only behavior dependencies).
- Non-goals:
  - Rewriting downstream application business logic in target repos.
  - Renaming user-facing command families (`plan`, `resume`, `restart`, `stop`, `blast-all`, etc.).
  - Long-term dual primary engines (shell + python) after migration completion.
- Assumptions:
  - Python 3.12 is required for the Python engine path (`lib/engine/main.sh`, `python_engine_select_bin`).
  - Docker remains a required dependency for infra orchestration in real repos.
  - Existing config precedence remains: process env -> repo config file (`.envctl` / `.envctl.sh` / `.supportopia-config`) -> defaults.
  - Existing planning docs under `docs/planning/refactoring/` are the format baseline; `docs/planning/README.md` does not currently exist and must be treated as a documentation gap.

## Goal (user experience)
Running `envctl`, `envctl --tree`, or `envctl --plan` should be boring and deterministic: each project gets unique app/infra ports, displayed URLs always match real listeners, requirement readiness is real (not synthetic), restart/stop/blast behavior is correct and idempotent, and users can rely on one Python engine behavior from a clean clone without shell fallback surprises.

## Business logic and data model mapping
- Launcher and engine handoff:
  - `bin/envctl` -> `lib/envctl.sh:envctl_main` -> `lib/envctl.sh:envctl_forward_to_engine` -> `lib/engine/main.sh`.
  - Python mode is default-enabled via launcher and shell engine bridge logic.
- Python routing/runtime core:
  - CLI entrypoint: `python/envctl_engine/cli.py:run`.
  - Route parsing and aliases: `python/envctl_engine/command_router.py:parse_route`.
  - Runtime dispatch/start/cleanup/doctor: `python/envctl_engine/engine_runtime.py:PythonEngineRuntime`.
- Runtime domain models:
  - `PortPlan`, `ServiceRecord`, `RequirementsResult`, `RunState` in `python/envctl_engine/models.py`.
  - Runtime projection mapping in `python/envctl_engine/runtime_map.py`.
  - Persistent state and legacy shell compatibility loaders in `python/envctl_engine/state.py`.
- Port and lock ownership:
  - Port planning/reservation/reclaim in `python/envctl_engine/ports.py`.
  - Reservation call path in `python/envctl_engine/engine_runtime.py:_reserve_project_ports`.
- Requirements and service orchestration:
  - Requirement retry/failure-class logic in `python/envctl_engine/requirements_orchestrator.py`.
  - Service start/retry/attach and listener detection path in:
    - `python/envctl_engine/service_manager.py`
    - `python/envctl_engine/engine_runtime.py:_start_project_services`.
- Shell parity baseline (behavioral reference, not target runtime):
  - Command surface and aliases: `lib/engine/lib/run_all_trees_cli.sh`.
  - Lifecycle and cleanup semantics: `lib/engine/lib/state.sh`, `lib/engine/lib/services_lifecycle.sh`, `lib/engine/lib/requirements_core.sh`, `lib/engine/lib/requirements_supabase.sh`.

## Current behavior (verified in code)
- Restart is not a real restart:
  - `python/envctl_engine/engine_runtime.py:_start` maps `restart` into a new `start` flow without explicitly stopping existing processes first.
  - Verified behavior: old processes can survive and ports rebound unexpectedly on restart.
- Stop/blast cleanup can claim success while processes remain alive:
  - `python/envctl_engine/engine_runtime.py:_clear_runtime_state` sends only `SIGTERM`, does not wait or escalate, and does not verify process termination.
  - The same cleanup path can signal stale/reused PIDs without ownership validation, risking termination of unrelated processes when persisted state is stale.
- Listener truth is port-only (not PID-scoped):
  - `python/envctl_engine/process_runner.py:wait_for_port` checks open port only.
  - `python/envctl_engine/engine_runtime.py` uses that result as service truth in startup/reconcile.
  - This allows false "healthy/running" when another process owns the requested port.
- Logging and interactive controls are parsed but operationally incomplete:
  - `--logs-tail`, `--logs-follow`, `--logs-duration`, `--logs-no-color`, `--interactive`, and `--dashboard-interactive` are parsed in `command_router.py`, but runtime `logs`/`dashboard` paths do not honor those controls.
  - `ServiceRecord.log_path` is never populated in Python startup flow, so `logs` outputs `log=n/a`.
- Process I/O handling can block long-lived services under output-heavy workloads:
  - `ProcessRunner.start` uses `stdout=PIPE` and `stderr=PIPE` with no active drain, which can backpressure and stall child processes.
- Runtime state scope is global by default:
  - Default runtime root is `/tmp/envctl-runtime` (`python/envctl_engine/config.py`).
  - `run_state.json` and pointers are not namespaced by repository identity, enabling cross-repo contamination.
- Lock stale policy can reclaim active locks after elapsed time:
  - `python/envctl_engine/ports.py:_lock_is_stale` marks stale by age even when PID is still alive.
- Cleanup lock release is overly broad:
  - `python/envctl_engine/engine_runtime.py` uses `release_all()` in failure/cleanup paths, not session/repo scoped release.
- Project name collision risk:
  - `python/envctl_engine/planning.py:discover_tree_projects` can generate duplicate logical names from mixed flat/nested layouts.
  - `services.update(...)` in runtime startup overwrites colliding keys, losing service records.
- Plan behavior is incomplete relative to user expectations:
  - `--plan` currently filters discovered tree projects and starts them; it does not own full planning-file selection/worktree creation lifecycle.
  - `ENVCTL_PLANNING_DIR` is loaded (`python/envctl_engine/config.py`) but not consumed by runtime plan flow.
- Runtime env wiring for per-project infra is incomplete:
  - Service subprocess env is built by `_command_env` with `PORT` and inherited process env, but does not inject per-project final requirement ports/URLs derived at runtime.
  - In multi-tree runs, projects can have distinct final DB/Redis ports in manifests while backend/frontend subprocesses still receive identical inherited DB/Redis env values.
- Requirements toggle model allows contradictory main-mode infra combinations:
  - `postgres` and `supabase` can be enabled simultaneously for `main`, both referencing the same DB port path, creating conflict-prone orchestration semantics.
- Repo config default mode mismatch:
  - Router default mode is derived from process env in `command_router.py`.
  - `.envctl`-loaded `ENVCTL_DEFAULT_MODE` in `config.py` does not influence route parsing for the current invocation.
- Targeted stop semantics are missing:
  - `stop` currently clears all tracked runtime state regardless of `--project/--service` selectors.
- Requirements failures do not gate app startup:
  - Runtime can continue to start backend/frontend even when requirements are degraded/failed.
- Python command surface parity is still materially narrower than shell parser surface:
  - Shell supports many options and aliases (`--docker`, `--stop-docker-on-exit`, `--parallel-trees`, short flags, blast volume flags, etc.).
  - Python router rejects many of these.
- Prerequisite checks are globally strict for startup commands and can block valid reduced-scope workflows:
  - `cli.check_prereqs` requires `docker`, `lsof`, and `npm|bun` for `start|plan|restart` regardless of actual selected mode/targets/toggles.
- Parity signal overstatement risk:
  - Manifest can report broad `python_complete` status, but some behaviors are still semantically incomplete.
  - `--doctor` currently sets lifecycle readiness as unconditional `True`, so lifecycle gate does not represent measured runtime behavior.

## Root cause(s) / gaps
- Cutover happened before behavioral parity closure.
- Route/config lifecycle split causes mode/config inconsistency.
- Runtime truth model is insufficiently strict (no PID-scoped listener ownership checks).
- Lifecycle control is incomplete (restart and stop semantics not equivalent to user expectations), and cleanup lacks safe process ownership checks.
- Port-lock model lacks robust scope isolation (repo/session) and stale reclaim correctness.
- Planning workflow ownership is incomplete (`--plan` not fully equivalent to expected planning-file driven flow).
- Failure handling is too permissive (requirements degradation does not consistently gate app startup).
- Runtime service env propagation is incomplete for per-project infra final ports/URLs.
- Command-surface parity was treated as syntactic, not operational.
- Observability/readiness checks are present but not fully behavior-gated, and log streaming contracts are not implemented.
- Process supervision model is incomplete for long-running noisy subprocesses (no output drain / no log-path contract).
- Prerequisite policy is not mode-aware and can produce unnecessary hard failures.
- Documentation baseline for planning standards is incomplete (`docs/planning/README.md` missing).

## Plan
### 1) Define hard cutover contract and parity gates
- Establish one source of truth for "100% complete":
  - command parity,
  - runtime truth,
  - lifecycle correctness,
  - release shipability.
- Make `--doctor` and release gate outcomes behavior-driven, not only manifest-driven.
- Require parity manifest status to be synchronized with runtime and test evidence.
- Add and enforce planning docs baseline doc (`docs/planning/README.md`) with required plan schema and evidence rules.

### 2) Namespace runtime state and lock scope by repository identity
- Introduce repo-scoped runtime namespaces under runtime root:
  - e.g., `python-engine/<repo_hash>/...` for state, runs, locks, pointers.
- Ensure pointers (`.last_state*`) and artifacts are resolved in repo scope only.
- Replace global `release_all()` usage in normal flows with scope-aware/session-aware release methods.
- Add migration logic for existing global state files to avoid breaking current users.

### 3) Rebuild lifecycle correctness (`restart`, `stop`, `stop-all`, `blast-all`)
- `restart`:
  - explicitly stop targeted existing processes first,
  - verify termination before re-start,
  - preserve planned ports where valid.
- `stop`:
  - honor selectors (`--project`, `--service`) and avoid full-state nuking when targeted.
- `stop-all` and `blast-all`:
  - introduce termination escalation (`SIGTERM` -> wait -> `SIGKILL` when needed),
  - verify process exit and container cleanup outcomes,
  - keep behavior idempotent across repeated invocations.
- Add safe process ownership checks before signaling:
  - validate PID ownership heuristics (cwd/command fingerprint captured at start),
  - avoid signaling stale/reused PIDs belonging to unrelated processes.
- Align blast behavior flags with intended scope semantics (worktree/main volumes, docker cleanup breadth).

### 4) Implement PID-scoped listener truth and projection correctness
- Replace port-only listener checks with PID + port ownership checks where possible.
- On startup:
  - only mark service running when target process actually owns expected listener.
  - classify and retry when listener is occupied by unrelated process.
- On health/resume/errors:
  - reconcile against live PID/listener truth.
  - never project healthy URLs for stale/unreachable services.
- Ensure runtime map projections are written from verified actual listener ports only.

### 5) Fix requirements gating and failure policy
- Make backend/frontend startup contingent on requirement readiness policy:
  - hard-block startup on required component failures by default.
  - allow explicit opt-out policy only via config.
- Normalize requirement failure classes with strict policy per service type.
- Ensure retries update final port assignments and propagate into both state and runtime map.
- Add main-mode toggle validation rules:
  - enforce mutually coherent `postgres`/`supabase` combinations,
  - fail fast with actionable diagnostics on contradictory infra policy.
- Wire per-project final requirement ports/URLs into service subprocess env:
  - include DB/Redis/n8n/supabase derived runtime values for each project instance,
  - ensure backend/frontend startup gets project-correct infra endpoints in multi-tree mode.

### 6) Complete planning/worktree ownership for `--plan`
- Integrate planning file discovery from `ENVCTL_PLANNING_DIR` into Python runtime command flow.
- Implement Python-native planning selection/worktree setup/reuse behavior parity.
- Preserve deterministic project naming and reject duplicate normalized project identifiers.
- Replace "selector miss -> run all" fallback with strict mode default for `--plan` (or explicit configurable behavior with clear warning).

### 7) Unify route parsing with loaded config defaults
- Resolve route/config split so repo config defaults affect routing in the same invocation.
- Ensure `.envctl` `ENVCTL_DEFAULT_MODE` takes effect without requiring exported process env.
- Add explicit precedence and conflict diagnostics in CLI output and docs.

### 8) Close command-surface parity gaps against shell baseline
- Expand router support for critical shell flags/aliases used in active workflows:
  - mode/interactive/parallel flags,
  - docker lifecycle flags,
  - blast volume policy flags,
  - short aliases currently expected by users.
- For unsupported flags, return actionable parity diagnostics with supported alternatives (never silent fallback).
- Keep parity scope explicit in manifest and docs until full closure.
- Add explicit behavior parity for currently parsed-but-ignored controls:
  - `--logs-tail`, `--logs-follow`, `--logs-duration`, `--logs-no-color`,
  - `--interactive`, `--dashboard-interactive`,
  - `--parallel-plan` vs `--sequential-plan` execution semantics.

### 9) Implement process logging and interactive diagnostics parity
- Replace unconsumed pipe-only process model with explicit log sinks:
  - stream service stdout/stderr to run-scoped log files,
  - persist log paths in `ServiceRecord.log_path`,
  - prevent child-process blocking due to full pipe buffers.
- Upgrade `logs` command behavior:
  - honor tail/follow/duration/color flags,
  - support per-service and all-service streaming views.
- Implement interactive dashboard mode parity:
  - honor interactive flags and provide command loop where configured.

### 10) Harden lock semantics and stale reclaim safety
- Update stale logic so active owner PID cannot be reclaimed solely by elapsed time.
- Track lock ownership with repo/session metadata and enforce ownership checks on release.
- Add deterministic lock cleanup workflow for crash recovery and blast semantics.

### 11) Add duplicate project identity guards
- Detect and fail early when discovery produces duplicate normalized project names.
- Include conflicting roots and normalization details in diagnostics.
- Prevent service/state overwrites caused by duplicate key names.

### 12) Strengthen observability and operator diagnostics
- Expand structured events for:
  - lifecycle transitions,
  - retry/failure classes,
  - requirement gating decisions,
  - scoped cleanup operations.
- Include readiness summaries with explicit failing checks in `--doctor`.
- Persist run-scoped artifacts for each failure path to aid reproducible debugging.
- Replace placeholder lifecycle readiness gate with measurable lifecycle assertions (not constant pass).
- Add mode-aware prereq diagnostics:
  - report missing tools by command/mode necessity, not global static tool list.

### 13) Enforce release shipability and cutover sequence
- Release gate must fail when:
  - required migration files are untracked/missing,
  - parity suites fail,
  - manifest/runtime readiness are inconsistent.
- Stage rollout:
  - Phase A: close correctness/lifecycle gaps under current Python-default mode.
  - Phase B: pass full Python unit + BATS parity suites in CI repeatedly.
  - Phase C: remove residual shell fallback from normal operation path.
  - Phase D: retire shell orchestration as implementation dependency.

## Tests (add these)
### Backend tests
- Extend `tests/python/test_lifecycle_parity.py`:
  - `restart` stops old PIDs before start.
  - `stop/stop-all/blast-all` enforce termination escalation and verify process exit.
  - targeted stop semantics respect `--project` and `--service`.
  - stale/reused PID protection prevents killing unrelated processes.
- Extend `tests/python/test_service_manager.py`:
  - PID-scoped listener ownership validation.
  - unrelated listener occupancy does not produce false success.
- Extend `tests/python/test_runtime_health_truth.py`:
  - stale/unreachable services are always reflected in health/errors.
- Extend `tests/python/test_ports_lock_reclamation.py`:
  - active PID lock is not reclaimed by TTL alone.
  - scoped/session release does not remove unrelated locks.
- Extend `tests/python/test_ports_availability_strategies.py`:
  - restricted environment behavior and fallback correctness.
- Add `tests/python/test_runtime_scope_isolation.py`:
  - two repos sharing runtime base do not contaminate each other's state/health.
- Add `tests/python/test_project_discovery_collisions.py`:
  - duplicate normalized project name detection and failure.
- Extend `tests/python/test_engine_runtime_real_startup.py`:
  - requirement failures correctly gate app startup by policy.
  - per-project runtime env uses project-correct infra ports in multi-tree mode.
- Extend `tests/python/test_cli_router_parity.py`:
  - additional alias/flag parity coverage against shell baseline.
- Extend `tests/python/test_config_loader.py` and route tests:
  - `.envctl` `ENVCTL_DEFAULT_MODE` affects command routing in-process.
- Add `tests/python/test_logging_and_dashboard_parity.py`:
  - log-path population and dashboard interactive behavior contract.
- Add `tests/python/test_prereq_policy.py`:
  - command/mode-aware prerequisite enforcement and diagnostics.

### Frontend tests
- Extend `tests/python/test_runtime_projection_urls.py`:
  - projection uses verified actual listener ports only.
  - rebound/retry scenarios maintain correct frontend/backend URLs.
- Extend `tests/python/test_frontend_env_projection_real_ports.py`:
  - frontend env and projection stay aligned with backend final listener under restart/rebind.
- Add projection tests for noisy service output scenarios to ensure logging does not stall listeners.

### Integration/E2E tests
- Fix and keep passing:
  - `tests/bats/python_listener_projection_e2e.bats`
  - `tests/bats/python_resume_projection_e2e.bats`
  - `tests/bats/python_plan_nested_worktree_e2e.bats`
  - `tests/bats/python_plan_parallel_ports_e2e.bats`
  - `tests/bats/python_requirements_conflict_recovery.bats`
  - `tests/bats/python_stop_blast_all_parity_e2e.bats`
  - `tests/bats/parallel_trees_python_e2e.bats`
- Add `tests/bats/python_cross_repo_state_isolation_e2e.bats`:
  - health/commands in repo A cannot see repo B state.
- Add `tests/bats/python_restart_pid_replacement_e2e.bats`:
  - restart replaces PIDs rather than creating leaked processes.
- Add `tests/bats/python_stop_signal_escalation_e2e.bats`:
  - SIGTERM-resistant process is eventually terminated in stop/blast flows.
- Add `tests/bats/python_plan_selector_strictness_e2e.bats`:
  - selector miss behavior is explicit and policy-compliant.
- Add `tests/bats/python_planning_dir_plan_mode_e2e.bats`:
  - `ENVCTL_PLANNING_DIR` is honored by Python `--plan` workflow.
- Add `tests/bats/python_logs_follow_parity_e2e.bats`:
  - `logs` tail/follow/duration/no-color flags are behaviorally honored.
- Add `tests/bats/python_dashboard_interactive_e2e.bats`:
  - interactive dashboard mode behavior is reachable and functional.
- Add `tests/bats/python_prereq_mode_aware_e2e.bats`:
  - startup prerequisite checks align with selected command/mode requirements.

## Observability / logging (if relevant)
- Emit structured events for:
  - route selection,
  - scoped state namespace selection,
  - lock acquire/release/reclaim with owner scope,
  - requirement gating decisions,
  - lifecycle stop/restart escalation paths,
  - projection source-of-truth updates.
- Persist run-level artifacts under scoped runtime directory:
  - `run_state.json`,
  - `runtime_map.json`,
  - `ports_manifest.json`,
  - `error_report.json`,
  - `events.jsonl`.
- Persist service logs as first-class artifacts:
  - backend/frontend (and requirement subprocess when applicable) log files with stable paths.
- Extend doctor diagnostics:
  - include repo scope id,
  - failing readiness classes,
  - stale lock candidates,
  - pointer validity summary.
  - lifecycle readiness evidence and prereq policy status.

## Rollout / verification
- Phase 0: Merge this plan and freeze additional shell-first feature growth.
- Phase 1: Land lifecycle correctness + runtime scope isolation + lock safety.
- Phase 2: Land PID-scoped truth + requirements gating + projection hardening.
- Phase 3: Land planning/worktree parity (`ENVCTL_PLANNING_DIR`, strict selectors, duplicate name guards).
- Phase 4: Close command-surface parity and targeted stop semantics.
- Phase 5: Run full verification matrix:
  - `.venv/bin/python -m unittest discover -s tests/python -p 'test_*.py'`
  - `bats tests/bats/python_*.bats`
  - `bats tests/bats/*.bats`
  - release gate script with tests enabled.
- Phase 6: Remove shell fallback dependency from normal workflows only after consecutive green cycles.

## Definition of done
- Python runtime behavior is correct and deterministic for `main`, `trees`, and `--plan` under repeated runs.
- Runtime state and lock scope are repository-isolated by design.
- Restart/stop/blast semantics are lifecycle-correct, termination-verified, and idempotent.
- Health/errors/projection are grounded in verified live listener truth, not stale metadata.
- Requirements readiness policy reliably gates app startup.
- Planning mode honors planning directory configuration and expected selection behavior.
- Command-surface parity for high-value flags/workflows is closed or explicitly documented with tested guardrails.
- Full Python unit and parity BATS suites pass in CI and local reproducible runs.
- Release gate confirms tracked-file completeness and parity/readiness consistency.

## Risk register (trade-offs or missing tests)
- Risk: stricter lifecycle truth checks may initially expose more startup failures.
  - Mitigation: detailed failure classes and targeted remediation guidance in doctor/errors output.
- Risk: repo-scoped runtime migration can strand old global state files.
  - Mitigation: one-time migration/compat loader and cleanup tooling.
- Risk: expanding flag parity can increase router complexity.
  - Mitigation: table-driven route parsing tests mapped directly to shell baseline expectations.
- Risk: blast behavior scope can be over-aggressive or under-aggressive for users.
  - Mitigation: explicit policy flags, non-interactive safe defaults, and dedicated E2E coverage.
- Risk: mixed topology repos (flat + nested trees) can regress discovery.
  - Mitigation: collision detection and deterministic naming constraints with failure-fast diagnostics.
- Risk: stricter PID-ownership checks can fail on restricted hosts lacking process metadata access.
  - Mitigation: tiered ownership heuristics with conservative no-kill fallback and explicit warnings.
- Risk: log streaming implementation can regress startup latency if not buffered correctly.
  - Mitigation: non-blocking drain strategy, bounded buffers, and performance-oriented e2e tests.

## Open questions (only if unavoidable)
- Should `blast-all` default to host-wide process/container cleanup parity with shell behavior, or repo-scoped cleanup by default with explicit host-wide opt-in?
- Should selector-miss behavior in `--plan` default to strict failure, or permissive fallback to all projects with explicit warning?
- What is the exact deprecation policy for `.envctl.sh` executable hooks once Python parity reaches completion?
