# Envctl Python Engine 100% Readiness Plan

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Close all currently verified gaps preventing a true Python-engine replacement for `envctl`.
  - Make Python runtime behaviorally complete for primary workflows (`--plan`, trees/main startup, resume/restart, stop lifecycle, runtime projection).
  - Remove ambiguity between "default enabled" and "actually production-ready."
  - Reach a measurable release state where Python can be trusted as default without shell fallback for normal developer workflows.
- Non-goals:
  - Rewriting downstream application repositories launched by envctl.
  - Changing the external CLI name (`envctl`) or breaking existing high-value flags.
  - Big-bang deletion of shell engine before parity gates pass.
- Assumptions:
  - Python 3.12 remains required for Python engine runtime path.
  - Docker remains a core prerequisite for requirements orchestration.
  - Existing config keys (`ENVCTL_DEFAULT_MODE`, `ENVCTL_PLANNING_DIR`, `POSTGRES_MAIN_ENABLE`, `REDIS_*`, `SUPABASE_MAIN_ENABLE`, `N8N_*`) must remain compatible.
  - `docs/planning/README.md` is currently missing; plan quality baseline is taken from existing refactoring plans under `docs/planning/refactoring/`.

## Goal (user experience)
`envctl` should be boring and deterministic: `envctl --plan` must work repeatedly across multiple worktrees, assign non-conflicting app/infra ports, show correct URLs, recover correctly on resume/restart, and execute lifecycle commands without hidden partial behavior or shell-only surprises.

## Business logic and data model mapping
- Launcher and runtime selection:
  - `bin/envctl` -> `lib/envctl.sh:envctl_main` -> `lib/envctl.sh:envctl_forward_to_engine` -> `lib/engine/main.sh`.
  - Python default enablement currently comes from:
    - `lib/envctl.sh:173-179`
    - `lib/engine/main.sh:119-124`
- Python runtime control flow:
  - CLI parse/run in `python/envctl_engine/cli.py` (`run`, `check_prereqs`)
  - command routing in `python/envctl_engine/command_router.py` (`parse_route`)
  - lifecycle dispatch in `python/envctl_engine/engine_runtime.py` (`dispatch`, `_start`, `_resume`, `_clear_runtime_state`)
- Core state and models:
  - `python/envctl_engine/models.py` (`PortPlan`, `ServiceRecord`, `RequirementsResult`, `RunState`)
  - `python/envctl_engine/state.py` (JSON + legacy shell format parsing + pointer loading)
  - `python/envctl_engine/runtime_map.py` (projection URLs and service-port mappings)
- Port planning/reservation:
  - `python/envctl_engine/ports.py` (`reserve_next`, `_reserve_port`, `_is_port_available`, stale lock behavior)
- Discovery/planning:
  - `python/envctl_engine/planning.py` (`discover_tree_projects`, `filter_projects_for_plan`)
- Requirements/services startup:
  - `python/envctl_engine/engine_runtime.py` (`_start_requirement_component`, `_start_project_services`)
  - `python/envctl_engine/process_runner.py` (run/start process abstraction)
  - `python/envctl_engine/service_manager.py` (retry + attach model)
- Shell parity baseline modules for behavior:
  - `lib/engine/lib/run_all_trees_cli.sh`
  - `lib/engine/lib/run_all_trees_helpers.sh`
  - `lib/engine/lib/services_lifecycle.sh`
  - `lib/engine/lib/requirements_core.sh`
  - `lib/engine/lib/requirements_supabase.sh`
  - `lib/engine/lib/state.sh`

## Current behavior (verified in code)
- Python engine is default-enabled, but command parity is intentionally partial:
  - `python/envctl_engine/engine_runtime.py:89-90` returns unsupported for `test`, `delete-worktree`, `pr`, `commit`, `analyze`, `migrate`.
  - parity manifest still marks these as `python_partial` in `docs/planning/python_engine_parity_manifest.json`.
- Major startup blocker currently exists in plan/start path:
  - `engine_runtime._reserve_project_ports` -> `ports.reserve_next` can raise `RuntimeError no free port found`.
  - Code path: `python/envctl_engine/engine_runtime.py:126`, `python/envctl_engine/engine_runtime.py:192`, `python/envctl_engine/ports.py:104`.
- Tree discovery can misidentify project roots:
  - `planning.discover_tree_projects` selects all leaf directories (`rglob`) and can produce names like `<feature>-<iter>-backend-src`.
  - Code: `python/envctl_engine/planning.py:12-18`, `python/envctl_engine/planning.py:25-27`.
- Requirements/service startup uses placeholder defaults unless env overrides are supplied:
  - requirements command default: `sh -lc true` (`python/envctl_engine/engine_runtime.py:665`)
  - service command default: `sh -lc 'sleep 0.01'` (`python/envctl_engine/engine_runtime.py:670`)
- Port projection remains mostly requested-port based:
  - backend actual detector returns requested port (`python/envctl_engine/engine_runtime.py:363-365`)
  - frontend can shift only via test env override (`python/envctl_engine/engine_runtime.py:367-370`)
- stop/blast cleanup semantics are incomplete vs shell behavior:
  - kills tracked pids and clears runtime artifacts + locks, but does not perform shell-equivalent ecosystem/docker sweep.
  - code: `python/envctl_engine/engine_runtime.py:566-596`.
- State compatibility improved but still migration-sensitive:
  - pointer loading exists (`python/envctl_engine/state.py:77-98`)
  - legacy `declare -a/-A` parsing exists (`python/envctl_engine/state.py:229+`)
  - still needs full parity against all shell pointer/state variants from `lib/engine/lib/state.sh`.
- `check_prereqs` scope is narrow to start/plan/restart in CLI (`python/envctl_engine/cli.py:49-53`) but runtime paths still assume tool presence for deeper commands.

## Root cause(s) / gaps
1. Default cutover happened before full feature parity was delivered.
2. Command surface is split between Python-complete and Python-partial paths.
3. `reserve_next` reliability is brittle in constrained environments and can fail startup globally.
4. Project discovery algorithm is based on filesystem leaves instead of logical worktree roots.
5. Startup commands are not production command-resolved by default; they rely on placeholders.
6. Actual listener detection is not implemented robustly, so URL projection can drift.
7. stop/blast lifecycle semantics are not equivalent to mature shell cleanup behavior.
8. Planning behavior is still not equivalent to full shell planning UX (selection/reuse/create nuances).
9. Port lock lifecycle and stale-lock handling need stronger invariants and observability.
10. Runtime map correctness depends on synthetic assumptions in several paths.
11. Command/action parity for interactive and operational commands is incomplete.
12. E2E parity tests are currently failing in key readiness scenarios.
13. CI/test environment sensitivity (socket bind limitations) is not abstracted cleanly in planner tests/runtime.
14. Documentation still mixes migration claims with partial command reality.
15. Shell hook parity (`.envctl.sh` function hooks) remains unresolved for Python-first final state.

## Plan
### 1) Enforce cutover gates and remove silent readiness ambiguity
- Keep Python available, but gate "default for all users" on measurable parity gates.
- Add hard startup banner in Python mode when any requested command is still partial.
- Ensure unsupported commands either:
  - perform explicit shell fallback when allowed, or
  - fail with explicit parity message and stable exit code.
- Align parity manifest with actual routing behavior and enforce in CI.

### 2) Stabilize port planner and lock lifecycle first (critical path)
- Refactor `PortPlanner.reserve_next` to support injectable availability checks (for tests) and robust host-port probing strategy.
- Add deterministic stale-lock reclaim policy with explicit session metadata and bounded lock hygiene.
- Ensure lock release is guaranteed on:
  - normal stop
  - blast-all
  - startup failures
  - interrupted runs
- Introduce structured events for lock acquisition/reclaim/release failures.

### 3) Fix project discovery to model logical worktrees, not arbitrary leaf dirs
- Replace leaf-directory discovery with logical patterns:
  - preferred: `trees/<feature>/<iter>`
  - backward-compatible: flat single-level trees where needed.
- Require project root selection logic to ignore app subdirectories (`backend`, `frontend`, `src`, `node_modules`, etc.).
- Preserve deterministic project naming (`feature-a-1`, etc.) and stable ordering.

### 4) Implement real command resolution for requirements/services (remove placeholders)
- Replace default placeholder commands with actual resolved process commands from config/repo context.
- Build explicit command-resolution module for:
  - backend start command
  - frontend start command
  - requirements stack start commands
- Validate executable presence and emit actionable failure classes when missing.
- Keep explicit env override hooks for custom repos, but never fall back to no-op commands.

### 5) Implement real listener detection and projection correctness
- Introduce PID/process-tree listener detection for backend/frontend port binding.
- Persist both requested and actual ports; projection URLs must derive from actual.
- Add rebound handling parity for frontend when requested port is unavailable.
- Reject "healthy summary" if listener validation fails.

### 6) Complete requirements orchestration parity
- Port full requirements lifecycle semantics from shell:
  - postgres/redis start/reuse/attach/retry
  - supabase db/auth/gateway sequencing and health
  - n8n start/restart/bootstrap behavior and strict/soft modes
- Ensure `RequirementsResult.supabase` is populated consistently.
- Implement deterministic recovery logic for bind conflicts across all requirements.

### 7) Complete lifecycle command parity (`stop`, `stop-all`, `blast-all`, `resume`, `restart`)
- Expand cleanup module to match shell intent:
  - process cleanup
  - runtime artifact cleanup
  - lock cleanup
  - optional docker ecosystem cleanup paths with explicit flags
- Resume/restart must reconcile state with actual running processes and missing services.
- Add per-command integration tests validating exact lifecycle outcomes.

### 8) Close command/action parity for operational workflows
- Implement Python ownership (or explicit bridged fallback) for:
  - `test`, `pr`, `commit`, `analyze`, `migrate`, `delete-worktree`
- Match shell command target-selection semantics (`--project`, `--projects`, all/interactive where applicable).
- Ensure command exit code contract stays stable (`0`, `1`, `2`).

### 9) Finalize state/pointer and hook compatibility strategy
- Validate all shell pointer/state variants used by `lib/engine/lib/state.sh`.
- Decide and implement long-term `.envctl.sh` strategy:
  - safe support path with constrained hooks, or
  - formal deprecation with migration path to declarative `.envctl`.
- Ensure `load_state_from_pointer` and legacy parser behavior are fully covered by fixtures from real shell output.

### 10) Tighten observability, docs, and release verification
- Emit run-scoped artifacts + event logs with correlation IDs.
- Add explicit "parity status" in diagnostics (`--doctor`/dashboard) so users can see command readiness.
- Update docs to reflect exact command-level readiness and fallback behavior.
- Promote Python to full default only after all parity gates and E2E suites are green.

## Tests (add these)
- Backend tests
  - Extend `tests/python/test_ports_lock_reclamation.py`:
    - add injected port-availability checker tests to avoid environment-dependent socket bind failures.
    - add lock reclaim + lock release invariants for interrupted runs.
  - Add `tests/python/test_engine_runtime_port_reservation_failures.py`:
    - assert no catastrophic `no free port found` for normal ranges in deterministic fixtures.
  - Extend `tests/python/test_engine_runtime_real_startup.py`:
    - verify command resolution uses real command providers and no placeholder defaults.
  - Add `tests/python/test_discovery_topology.py`:
    - validate `trees/<feature>/<iter>` and explicit rejection of nested app leaf dirs.
  - Add `tests/python/test_lifecycle_parity.py`:
    - `stop`, `stop-all`, `blast-all`, `resume`, `restart` behavior checks with mock runner/process graph.
- Frontend tests
  - Extend `tests/python/test_runtime_projection_urls.py`:
    - require projection from actual listener ports after retries/rebounds.
  - Extend `tests/python/test_frontend_projection.py`:
    - multi-project and rebound scenarios with deterministic actual-port inputs.
- Integration/E2E tests
  - Fix and enforce currently failing suites:
    - `tests/bats/parallel_trees_python_e2e.bats`
    - `tests/bats/python_plan_nested_worktree_e2e.bats`
    - `tests/bats/python_plan_parallel_ports_e2e.bats`
    - `tests/bats/python_requirements_conflict_recovery.bats`
    - `tests/bats/python_resume_projection_e2e.bats`
    - `tests/bats/python_stop_blast_all_parity_e2e.bats`
  - Add `tests/bats/python_command_partial_guardrails_e2e.bats`:
    - verify unsupported commands never masquerade as successful startup.
  - Add `tests/bats/python_listener_projection_e2e.bats`:
    - verify displayed URLs match actual listeners under real port contention.

## Observability / logging (if relevant)
- Required event keys:
  - `command.route.selected`
  - `planning.projects.discovered`
  - `port.lock.acquire`, `port.lock.reclaim`, `port.lock.release`
  - `requirements.start`, `requirements.retry`, `requirements.failure_class`
  - `service.start`, `service.bind.requested`, `service.bind.actual`
  - `state.resume`, `state.reconcile`
  - `cleanup.stop`, `cleanup.blast`
- Required run artifacts per run id:
  - run state, runtime map, ports manifest, error report, events stream.
- Diagnostics updates:
  - `--doctor` should include parity/readiness status and recent failing command class summaries.

## Rollout / verification
- Gate A: Router and command compatibility
  - No command routes unexpectedly to startup.
  - All dashed aliases map correctly.
- Gate B: Planning/discovery correctness
  - Nested worktree tests pass.
  - Project naming/order/port assignment deterministic.
- Gate C: Startup/runtime correctness
  - Requirements and services start with real commands.
  - Listener-validated URL projection passes.
- Gate D: Lifecycle correctness
  - stop/resume/restart/blast parity tests pass consistently.
- Gate E: Cutover readiness
  - All Python unit + BATS parity/e2e suites green.
  - No `python_partial` status for target command set in manifest.

## Definition of done
- Python runtime handles all primary commands with parity-complete behavior.
- `envctl --plan` and tree orchestration are stable for real nested worktree layouts.
- Runtime summaries and URLs reflect actual running listeners, not synthetic assumptions.
- Port reservation is robust and deterministic with tested stale-lock and cleanup behavior.
- Lifecycle commands are complete and reliable.
- Command parity manifest reflects a complete state and is enforced by tests/CI.

## Risk register (trade-offs or missing tests)
- Risk: Port availability checks can remain flaky under restricted runtime environments.
  - Mitigation: injectable availability strategy + deterministic test fakes + one real-socket integration suite.
- Risk: Docker lifecycle parity may diverge between macOS/Linux.
  - Mitigation: platform-aware retries/probes and CI matrix coverage.
- Risk: `.envctl.sh` compatibility can reintroduce unsafe shell behavior if unconstrained.
  - Mitigation: constrained hook contract and explicit deprecation path if needed.
- Risk: Partial command support can continue confusing users during transition.
  - Mitigation: explicit parity status in diagnostics + non-silent failure/fallback rules.

## Open questions (only if unavoidable)
- Do we want long-term full support for `.envctl.sh` function hooks in Python mode, or a defined deprecation window to move to declarative `.envctl` plus explicit plugin hooks?
