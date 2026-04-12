# Envctl Python Engine Ledger-Driven Bash-Parity Cutover Plan
## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Reach true Python-first production parity with Bash behavior for `start`, `--plan`, `--resume`, `restart`, `stop`, `stop-all`, `blast-all`, interactive dashboard, and action commands.
  - Eliminate synthetic execution paths from default/primary runtime behavior and from parity-critical tests.
  - Reduce shell ownership debt from `320 unmigrated` ownership entries to zero, with staged budgets and enforced CI gates.
  - Make release state reproducible from tracked git content only (no reliance on local untracked files).
  - Decompose current Python runtime monolith into maintainable modules while preserving behavior.
- Non-goals:
  - Renaming `envctl` or changing high-value CLI semantics.
  - Rewriting downstream application business logic in external repos.
  - Big-bang immediate deletion of all shell code before compatibility gates are green.
- Assumptions:
  - Python 3.12 remains required for Python runtime execution (`lib/engine/main.sh`).
  - Docker remains required for requirements orchestration.
  - Existing config precedence remains stable: env -> `.envctl/.envctl.sh/.supportopia-config` -> defaults (`python/envctl_engine/config.py`).
  - Shell fallback remains available as emergency escape hatch during phased cutover.

## Goal (user experience)
Running `envctl` in normal developer workflows should be deterministic and Bash-equivalent in behavior while implemented in Python: `envctl --plan` should support interactive selection, deterministic worktree reuse/create, unique app/infra ports across parallel trees, real requirements/service startup, accurate listener-backed URLs, robust resume/restart reconciliation, and lifecycle cleanup (`stop/stop-all/blast-all`) that is idempotent and operationally complete. Diagnostics (`doctor`, `health`, `errors`, dashboard) must be truthful and gate-backed, not metadata-only.

## Business logic and data model mapping
- Launcher and engine handoff:
  - `bin/envctl` -> `lib/envctl.sh:envctl_forward_to_engine` -> `lib/engine/main.sh`.
  - Python defaulting/fallback knobs: `ENVCTL_ENGINE_PYTHON_V1`, `ENVCTL_ENGINE_SHELL_FALLBACK`.
- Python entry and routing:
  - CLI entry: `python/envctl_engine/cli.py:run`.
  - Parser: `python/envctl_engine/command_router.py:parse_route`.
  - Runtime dispatch: `python/envctl_engine/engine_runtime.py:PythonEngineRuntime.dispatch`.
- Core runtime ownership:
  - State model: `RunState`, `ServiceRecord`, `RequirementsResult`, `PortPlan` (`python/envctl_engine/models.py`).
  - State serialization/legacy compatibility: `python/envctl_engine/state.py`.
  - Runtime projection: `python/envctl_engine/runtime_map.py`.
  - Port allocation/locks: `python/envctl_engine/ports.py`.
  - Requirements orchestration/retry classes: `python/envctl_engine/requirements_orchestrator.py` + `python/envctl_engine/requirements/*`.
  - Service lifecycle/retry: `python/envctl_engine/service_manager.py`.
  - Release and shell-prune gates: `python/envctl_engine/release_gate.py`, `python/envctl_engine/shell_prune.py`.
- Shell baseline still defining historical behavior:
  - `lib/engine/lib/run_all_trees_helpers.sh`, `services_lifecycle.sh`, `requirements_core.sh`, `requirements_supabase.sh`, `state.sh`, `actions.sh`, `docker.sh`, `planning.sh`, `ports.sh`, `ui.sh`.

## Current behavior (verified in code)
- Migration debt remains structurally high:
  - Shell ownership ledger contains `320` entries, all status `unmigrated` (`docs/planning/refactoring/envctl-shell-ownership-ledger.json`).
  - Top unmigrated areas include `state.sh`, `run_all_trees_helpers.sh`, `docker.sh`, `analysis.sh`, `ports.sh`, `actions.sh`, `ui.sh`, `worktrees.sh`.
- Gate truth mismatch risk:
  - `release_gate` enforces tracked-file shipability and parity sync (`python/envctl_engine/release_gate.py`), but shell unmigrated count is only warning unless an explicit budget is configured (`python/envctl_engine/shell_prune.py`).
  - `doctor` currently reports command parity from manifest + `PARTIAL_COMMANDS` and shipability via `evaluate_shipability`, but shell migration can still show pass with non-zero unmigrated unless budget env is set (`python/envctl_engine/engine_runtime.py:_doctor_readiness_gates`, `python/envctl_engine/shell_prune.py`).
- Synthetic fallback still exists in runtime:
  - Command resolution still supports synthetic requirement/service commands when `ENVCTL_ALLOW_SYNTHETIC_DEFAULTS=true` (`python/envctl_engine/command_resolution.py`).
  - Runtime flags and summaries explicitly mark synthetic states (`python/envctl_engine/engine_runtime.py:_state_has_synthetic_defaults` and summary/dashboard warnings).
- Test suite health:
  - Python unit suite is green (`191` tests in local verification).
  - Python BATS suites are green in current harness, including parallel/plan/resume/stop/blast suites.
  - However, parity-critical BATS still frequently enable synthetic mode (multiple `python_*.bats` set `ENVCTL_ALLOW_SYNTHETIC_DEFAULTS=true`), weakening confidence for true real-runtime parity.
- Actions parity is functionally routed in Python but operationally shell-script dependent by default:
  - `test/pr/commit/analyze` default to `utils/*.sh` wrappers via Python modules (`python/envctl_engine/actions_test.py`, `actions_git.py`, `actions_analysis.py`).
- Requirements coverage:
  - Native adapters are implemented for `postgres`, `redis`, `n8n`.
  - Supabase path is currently contract/fingerprint-centric with optional command execution path and no full typed native lifecycle adapter parity with shell.
- Runtime architecture:
  - `python/envctl_engine/engine_runtime.py` remains a high-complexity monolith (~4.8k LOC), creating maintainability and regression risk.
- Shipability from clean clone currently fails:
  - `scripts/release_shipability_gate.py` fails due required paths/scopes being untracked in current workspace state.

## Root cause(s) / gaps
1. Cutover truth is split across behavior, ledger status, and git-tracking state, but not enforced as one hard pass/fail contract by default.
2. Shell ownership ledger is comprehensive but not yet actively burned down (all entries still `unmigrated`).
3. Synthetic command paths still exist and are used in many parity/E2E tests, masking real-runtime defects.
4. Action command implementations still rely on legacy shell scripts as default execution path.
5. Supabase orchestration is not yet parity-complete as a native Python adapter with full lifecycle semantics.
6. Blast/cleanup behavior is improved but still needs explicit contract-by-contract parity validation against shell outputs and side effects.
7. Large runtime monolith slows safe iteration and makes parity regressions likely.
8. Release/shipability gates fail in real workspace due tracked-file requirements not met.

## Plan
### 1) Enforce a hard, machine-checked cutover contract
- Make shell-prune unmigrated budget mandatory in doctor/release path for cutover phase:
  - Set and enforce `shell_prune_max_unmigrated=0` in cutover CI lane (`python/envctl_engine/release_gate.py`, `python/envctl_engine/engine_runtime.py:_doctor_readiness_gates`).
- Add explicit doctor fields:
  - `shell_unmigrated_budget`, `shell_unmigrated_actual`, `shell_unmigrated_status`.
- Fail command parity readiness when synthetic defaults are active in current run state.
- Deliverable:
  - A single gate output where `shipability=true` implies tracked scope complete, no parity mismatch, and no unmigrated shell budget violations.

### 2) Make repository state reproducible and tracked-first
- Resolve shipability failures in required scopes:
  - Ensure required Python engine, Python tests, BATS parity suites, parity manifest, and shell ledger are tracked.
- Add CI job that runs:
  - `./.venv/bin/python scripts/release_shipability_gate.py --repo . --check-tests`
  - plus cutover strict mode with no skip flags.
- Add pre-merge check for untracked files in required scopes.
- Deliverable:
  - Fresh clone passes shipability gate and executes same behavior.

### 3) Burn down shell ownership ledger in waves with explicit budgets
- Wave plan by module family:
  - Wave A: `actions.sh`, `analysis.sh`, `pr.sh`.
  - Wave B: `planning.sh`, `worktrees.sh`, `run_all_trees_helpers.sh` selection/setup fragments.
  - Wave C: `ports.sh`, `runtime_map.sh`, `state.sh` residuals.
  - Wave D: `docker.sh` and remaining lifecycle helpers.
- For each wave:
  - convert functions to Python equivalents or explicitly mark intentional keep (temporary only with expiry).
  - add evidence tests and update command mappings.
- Enforce staged budget targets:
  - e.g. `320 -> 220 -> 140 -> 60 -> 0`.
- Deliverable:
  - ledger statuses reflect reality with evidence, and unmigrated count trends to zero.

### 4) Remove synthetic defaults from primary runtime paths
- In `python/envctl_engine/command_resolution.py`:
  - keep synthetic paths only behind explicit test-mode guard incompatible with production runtime (e.g. require both env flag + test sentinel).
  - fail fast with actionable error when real command resolution is unavailable.
- In runtime startup (`python/envctl_engine/engine_runtime.py`):
  - treat synthetic use as hard failure in non-test contexts.
- Update tests:
  - add real-command-required coverage for production mode.
- Deliverable:
  - no synthetic execution in normal `envctl` workflows; synthetic mode only for explicit test fixtures.

### 5) Complete requirements parity with typed native adapters
- Add native Supabase adapter module under `python/envctl_engine/requirements/` with explicit lifecycle:
  - container/service bring-up sequencing, conflict recovery, readiness probes, strict/soft failure classification.
- Preserve existing contract checks/fingerprint logic, but move startup truth to observed readiness.
- Keep typed outcomes in `RequirementsResult` including retries/failure classes.
- Deliverable:
  - Postgres/Redis/Supabase/n8n all native Python-owned with consistent retry/failure semantics.

### 6) Close service lifecycle parity and listener-truth guarantees
- Keep current listener verification improvements and expand:
  - ensure process-tree listener ownership is canonical in startup, health, dashboard, and resume.
- Strengthen attach/retry/rebind logic:
  - explicit requested/assigned/final transitions persisted for every retry.
- Validate frontend env projection always uses backend actual listener.
- Deliverable:
  - no false running/URL states; projection derived from observed listener truth.

### 7) Reach operational parity for lifecycle cleanup (`stop`, `stop-all`, `blast-all`)
- Convert blast behavior to contract-driven phases with explicit expected side effects:
  - process kill patterns,
  - listener sweep,
  - docker container cleanup,
  - volume policy by flags/prompts,
  - state/pointer/lock purge.
- Add output contract snapshots to compare against shell baseline in E2E.
- Deliverable:
  - blast/stop semantics match shell intent and are idempotent under partial failures.

### 8) Remove default shell-script dependency from action commands
- Replace default wrappers in:
  - `actions_test.py`, `actions_git.py`, `actions_analysis.py`
  with Python-native orchestration logic where feasible.
- Keep optional shell adapters as explicit fallback, not primary default.
- Preserve target resolution semantics (`--all`, `--project`, service selectors).
- Deliverable:
  - action families execute in Python-native path by default, with stable exit contracts.

### 9) Finish state/resume/recovery parity and de-risk legacy paths
- Keep JSON state as authority; maintain safe legacy loader for migration window.
- Expand resume restore policy:
  - deterministic project restore ordering,
  - requirement restore + service restore reconciliation,
  - clear degraded diagnostics on partial restore.
- Remove remaining legacy `run.sh` references in Python-facing recovery outputs.
- Deliverable:
  - resume/restart are deterministic and never claim health when restore failed.

### 10) Decompose `engine_runtime.py` to reduce regression risk
- Extract cohesive modules:
  - `startup_orchestrator.py` (project startup + parallelization),
  - `lifecycle_cleanup.py` (stop/blast),
  - `dashboard.py` (interactive + rendering + truth reconcile),
  - `resume_orchestrator.py`.
- Keep public runtime behavior unchanged during extraction; gate each extract with existing tests.
- Deliverable:
  - reduced complexity and clearer ownership boundaries for future parity maintenance.

### 11) Tighten parity and docs synchronization
- Keep `docs/planning/python_engine_parity_manifest.json` synchronized with runtime truth:
  - add check that manifest `python_complete` requires non-synthetic test evidence for that command family.
- Update architecture/troubleshooting docs to explicitly state:
  - cutover phase,
  - strict gate criteria,
  - fallback policy.
- Deliverable:
  - docs do not overstate completion; parity claims are test-backed.

### 12) Execute cutover rollout with objective stop/go gates
- Gate A: shipability clean (tracked scopes + parser/doc parity + shell prune budget checkpoint).
- Gate B: synthetic-free primary E2E for `--plan`, `--resume`, `blast-all`, dashboard truth.
- Gate C: shell ledger budget reaches zero.
- Gate D: two consecutive release cycles without regression in key workflows.
- Deliverable:
  - shell fallback can be demoted to emergency-only and then retired.

## Tests (add these)
### Backend tests
- Extend:
  - `tests/python/test_engine_runtime_real_startup.py`
    - assert production mode fails when synthetic defaults are the only available resolver path.
    - assert startup uses native adapters for all enabled requirements including supabase.
  - `tests/python/test_requirements_orchestrator.py`
    - supabase failure class and retry mapping parity.
  - `tests/python/test_lifecycle_parity.py`
    - blast-all contract assertions for docker volume policies and pointer purge behavior.
  - `tests/python/test_release_shipability_gate.py`
    - enforce `max_unmigrated=0` phase behavior.
  - `tests/python/test_shell_prune_contract.py`
    - staged budgets + command mapping evidence requirements.
  - `tests/python/test_runtime_health_truth.py`
    - additional process-tree ownership and stale->restore transitions.
- Add:
  - `tests/python/test_cutover_gate_truth.py`
    - doctor/readiness gates must fail when synthetic or unmigrated budget violations exist.
  - `tests/python/test_supabase_native_adapter.py`
    - native supabase startup/retry/reconcile behavior.
  - `tests/python/test_actions_native_execution.py`
    - action commands do not require `utils/*.sh` in default path.

### Frontend tests
- Extend:
  - `tests/python/test_runtime_projection_urls.py`
    - projection remains correct through restart/resume restore.
  - `tests/python/test_frontend_env_projection_real_ports.py`
    - backend URL env injection follows rebound actual backend port.
- Add:
  - `tests/python/test_dashboard_render_truth.py`
    - dashboard rows keep URL visibility for valid process-tree listeners and degrade only on true failures.

### Integration/E2E tests
- Harden existing suites by removing synthetic-mode reliance for primary parity lanes:
  - `tests/bats/python_plan_parallel_ports_e2e.bats`
  - `tests/bats/python_plan_nested_worktree_e2e.bats`
  - `tests/bats/python_resume_projection_e2e.bats`
  - `tests/bats/python_stop_blast_all_parity_e2e.bats`
  - `tests/bats/python_listener_projection_e2e.bats`
  - `tests/bats/python_requirements_conflict_recovery.bats`
- Add:
  - `tests/bats/python_cutover_gate_strict_e2e.bats`
    - doctor/gate fails when shell unmigrated budget non-zero.
  - `tests/bats/python_no_synthetic_primary_flow_e2e.bats`
    - `--plan` and dashboard path reject synthetic defaults in production mode.
  - `tests/bats/python_actions_native_path_e2e.bats`
    - actions run without default shell script wrappers.

## Observability / logging (if relevant)
- Keep and enforce structured events for:
  - route selection, startup mode, port reservation/rebound/release, requirements lifecycle, service lifecycle, state reconcile, cleanup lifecycle, shell-prune gate status.
- Add required events:
  - `cutover.gate.evaluate`, `cutover.gate.fail_reason`, `synthetic.execution.blocked`.
- Persist per-run artifacts under scoped run dir:
  - `run_state.json`, `runtime_map.json`, `ports_manifest.json`, `error_report.json`, `events.jsonl`, `shell_prune_report.json`.

## Rollout / verification
- Baseline audit commands (must be green at each phase):
  - `./.venv/bin/python scripts/report_unmigrated_shell.py --repo .`
  - `./.venv/bin/python scripts/verify_shell_prune_contract.py --repo .`
  - `./.venv/bin/python scripts/release_shipability_gate.py --repo . --check-tests`
  - `./.venv/bin/python -m unittest discover -s tests/python -p 'test_*.py'`
  - `bats tests/bats/python_*.bats tests/bats/parallel_trees_python_e2e.bats`
- Phase gates:
  - Phase 1: tracked scope clean + gate passes except non-zero allowed shell budget.
  - Phase 2: synthetic-free primary E2E lanes green.
  - Phase 3: shell ledger budget reaches zero.
  - Phase 4: stability burn-in across two release cycles.

## Definition of done
- Shell ownership ledger has zero `unmigrated` entries for cutover scope and passes strict budget (`max_unmigrated=0`).
- Release shipability gate passes in strict mode on clean clone with tests.
- Primary workflows (`start/plan/resume/restart/stop/stop-all/blast-all/dashboard/health/errors`) are Python-owned, synthetic-free in production mode, and parity-tested.
- Action command families are Python-native by default (shell wrapper optional, explicit fallback only).
- Runtime projection and health are listener-truth based across startup/restart/resume.
- Docs/manifest/doctor outputs are synchronized and truthful.

## Risk register (trade-offs or missing tests)
- Risk: Removing synthetic fallback in primary paths may surface hidden repo misconfigurations quickly.
  - Mitigation: explicit actionable errors, controlled test-only synthetic mode, and migration docs.
- Risk: Supabase native parity can introduce platform-specific readiness flakiness.
  - Mitigation: adapter-level retries with bounded timeout and Linux/macOS CI coverage.
- Risk: Ledger burn-down may stall due broad shell surface area.
  - Mitigation: wave budgets with enforced deadlines and module-family ownership.
- Risk: Action-command de-shelling may alter side effects in existing repos.
  - Mitigation: strict parity tests and optional explicit shell fallback flags.

## Open questions (only if unavoidable)
- None currently blocking implementation; this plan assumes `.envctl.sh` hook bridge remains supported during cutover window with explicit policy review in final deprecation phase.
