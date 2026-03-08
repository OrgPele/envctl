# Envctl Python Engine Bash-Parity One-by-One Closure Plan

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Deliver a Python runtime that is behaviorally equivalent to the mature Bash runtime for normal developer workflows (`start`, `--plan`, `--resume`, `restart`, `stop`, `stop-all`, `blast-all`, interactive dashboard, action commands).
  - Remove simulation from default runtime behavior by making readiness, health, projection, and lifecycle operations depend on real process/container truth.
  - Close shell-ownership debt in a measurable, staged way, reducing `docs/planning/refactoring/envctl-shell-ownership-ledger.json` from `320 unmigrated` entries to `0`.
  - Make cutover truth machine-checkable: parity manifest, runtime gates, shell-prune contract, shipability gate, and CI outcomes must agree.
  - Ensure branch reproducibility from tracked files only.
- Non-goals:
  - Renaming `envctl`, changing core workflow semantics, or rewriting downstream product/business code.
  - Immediate deletion of all shell modules before Python parity gates are green.
  - Unbounded support for unsafe shell hook execution patterns.
- Assumptions:
  - Python 3.12 remains required for Python engine execution (`lib/engine/main.sh:python_engine_version_is_312`, `exec_python_engine_if_enabled`).
  - Docker remains required for requirements orchestration in parity workflows.
  - Config precedence remains stable (`python/envctl_engine/config.py:load_config`): process env -> `.envctl`/`.envctl.sh`/`.supportopia-config` -> defaults.
  - Existing worktree topology support (flat and nested) remains required (`python/envctl_engine/planning.py:discover_tree_projects`).

## Goal (user experience)
A user running `envctl --plan` gets the same operational confidence they had in Bash: interactive plan selection, deterministic worktree targeting, real infra/service startup, truthful URLs and health, and lifecycle commands that actually clean the environment. Interactive mode should be the default when a TTY exists, with `--batch`/`--non-interactive` explicitly disabling it. No command should claim success when services are simulated, unreachable, stale, or only partially started.

## Business logic and data model mapping
- Launcher and runtime selection:
  - `bin/envctl` -> `lib/envctl.sh:envctl_forward_to_engine` -> `lib/engine/main.sh:exec_python_engine_if_enabled`.
  - Python default path is currently enabled through launcher/main shell toggles (`ENVCTL_ENGINE_PYTHON_V1`, `ENVCTL_ENGINE_SHELL_FALLBACK`).
- Python command and lifecycle control flow:
  - Parse/route: `python/envctl_engine/command_router.py:parse_route`.
  - Entry/prereq policy: `python/envctl_engine/cli.py:run`, `check_prereqs`.
  - Runtime dispatch and orchestration: `python/envctl_engine/engine_runtime.py:PythonEngineRuntime.dispatch`.
- Canonical state/projection model:
  - Models: `python/envctl_engine/models.py` (`PortPlan`, `ServiceRecord`, `RequirementsResult`, `RunState`).
  - State IO and legacy compatibility: `python/envctl_engine/state.py` (`load_state`, `load_legacy_shell_state`, `load_state_from_pointer`, `dump_state`).
  - Runtime map and URL projection: `python/envctl_engine/runtime_map.py` (`build_runtime_map`, `build_runtime_projection`).
- Port and lock lifecycle:
  - `python/envctl_engine/ports.py:PortPlanner` (`reserve_next`, `_reserve_port`, `release_session`, `release_all`, availability strategies).
- Requirements and service startup domains:
  - Retry classification: `python/envctl_engine/requirements_orchestrator.py`.
  - Native requirement adapters: `python/envctl_engine/requirements/{postgres,redis,n8n,supabase}.py`.
  - Service retry/attach behavior: `python/envctl_engine/service_manager.py`.
  - Process and listener checks: `python/envctl_engine/process_runner.py`.
- Cutover/release truth gates:
  - Shipability gate: `python/envctl_engine/release_gate.py:evaluate_shipability`.
  - Shell-prune gate: `python/envctl_engine/shell_prune.py:evaluate_shell_prune_contract`.
  - Runtime doctor gate output: `python/envctl_engine/engine_runtime.py:_doctor_readiness_gates`.
- Shell parity baseline (behavioral source of truth for migration):
  - `lib/engine/lib/run_all_trees_cli.sh:run_all_trees_cli_parse_args`.
  - `lib/engine/lib/run_all_trees_helpers.sh:run_all_trees_start_tree_projects`, `run_all_trees_start_tree_projects_parallel`.
  - `lib/engine/lib/services_lifecycle.sh:start_service_with_retry`, `start_project_with_attach`.
  - `lib/engine/lib/requirements_core.sh:start_tree_postgres`, `start_tree_redis`, `ensure_tree_requirements`.
  - `lib/engine/lib/requirements_supabase.sh:start_tree_supabase`, `start_tree_n8n`, `restart_tree_n8n`.
  - `lib/engine/lib/state.sh:save_state`, `resume_from_state`, `load_state_for_command`, `load_attach_state`, `create_recovery_script`.

## Current behavior (verified in code)
- Command parity metadata currently indicates complete status:
  - `python/envctl_engine/engine_runtime.py:PARTIAL_COMMANDS` is empty.
  - `docs/planning/python_engine_parity_manifest.json` marks commands/modes as `python_complete`.
- Runtime doctor readiness computes shipability using release gate, but shell-prune strictness is optional:
  - `engine_runtime.py:_doctor_readiness_gates` calls `evaluate_shipability`.
  - shell-prune strict budget depends on `ENVCTL_SHELL_PRUNE_MAX_UNMIGRATED` (`engine_runtime.py:_shell_prune_max_unmigrated_budget`).
- Shell migration debt remains large by direct script evidence:
  - `./.venv/bin/python scripts/report_unmigrated_shell.py --repo .` reports:
    - `unmigrated_count: 320`
    - `intentional_keep_count: 0`
    - `partial_keep_count: 0`
    - ledger hash `e1829f58fb3762a22d5ffd49401b52c70f7a332cad984f073511f65d831f26fa`.
- Shell-prune contract currently passes while warning on unmigrated debt:
  - `./.venv/bin/python scripts/verify_shell_prune_contract.py --repo .`:
    - `shell_prune.passed: true`
    - warning `unmigrated shell entries remain: 320`.
- Shipability currently fails in this workspace:
  - `./.venv/bin/python scripts/release_shipability_gate.py --repo .` reports missing tracked scopes/files for parity-critical paths (`python/envctl_engine`, `tests/python`, key bats/parity docs), plus untracked required-scope files.
- Synthetic execution path still exists (feature-flagged):
  - `python/envctl_engine/command_resolution.py` allows synthetic command fallbacks when `ENVCTL_ALLOW_SYNTHETIC_DEFAULTS=true`.
  - `engine_runtime.py:_state_has_synthetic_defaults` marks synthetic state and dashboard warnings.
- E2E test realism gap remains in parity suites:
  - multiple BATS suites set `ENVCTL_ALLOW_SYNTHETIC_DEFAULTS=true` (for example `tests/bats/python_plan_parallel_ports_e2e.bats`, `tests/bats/python_resume_projection_e2e.bats`, `tests/bats/python_listener_projection_e2e.bats`, `tests/bats/python_stop_blast_all_parity_e2e.bats`, and others).
- Action command implementations are still shell-script-first for several command families:
  - `python/envctl_engine/actions_test.py:default_test_command` -> `utils/test-all-trees.sh`.
  - `python/envctl_engine/actions_git.py` -> `utils/create-prs.sh`, `utils/pr.sh`, `utils/commit*.sh`.
  - `python/envctl_engine/actions_analysis.py:default_analyze_command` -> `utils/analyze*.sh`.
- Runtime complexity remains high in a single module:
  - `python/envctl_engine/engine_runtime.py` is monolithic and carries startup, resume, dashboard, action commands, blast-all cleanup, and diagnostics in one file.
- Shell module ownership baseline remains broad:
  - `python/envctl_engine/shell_prune.py:list_shell_modules_from_main` discovers 17 shell modules sourced by `lib/engine/main.sh`.
  - Top ownership debt from ledger includes `state.sh`, `run_all_trees_helpers.sh`, `docker.sh`, `analysis.sh`, `pr.sh`, `ports.sh`, `ui.sh`, `actions.sh`, `worktrees.sh`.

## Root cause(s) / gaps
1. Cutover truth is fragmented: manifest says complete, but shell ownership and shipability gates still show unresolved migration debt.
2. Shell-prune strictness is not mandatory by default, allowing non-zero unmigrated debt to pass readiness in practice.
3. Synthetic command fallback remains available and is still exercised heavily in parity suites, reducing confidence in production realism.
4. Action command families are routed through Python but still default to legacy shell script wrappers in key paths.
5. Requirements parity is uneven across service types and still carries shell-equivalence risk in complex orchestration paths.
6. Blast/stop lifecycle parity is improving but needs stronger contract-level verification against shell behavior (containers, volumes, stale pointers/locks, process kill coverage).
7. Monolithic runtime structure raises regression risk and slows safe iteration across parity-critical paths.
8. Shipability/reproducibility gate failures indicate branch state is not yet ready for clean-clone parity claims.

## Plan
### 1) Establish a hard cutover contract (single source of readiness truth)
- Code targets:
  - `python/envctl_engine/engine_runtime.py` (`_doctor_readiness_gates`, doctor output schema).
  - `python/envctl_engine/release_gate.py` (strict cutover profile flags).
  - `python/envctl_engine/shell_prune.py` (budget enforcement and phase reporting).
- Implementation steps:
  - Add explicit cutover profiles (`lenient`, `staged`, `strict`) and map doctor/readiness output to profile-specific criteria.
  - In strict profile, require `shell_prune_max_unmigrated=0` and fail readiness on any unmigrated entries.
  - Add doctor output fields that expose exact gate reasons (`shipability.errors`, `shell_prune.unmigrated_count`, `synthetic_state_detected`).
- Acceptance checks:
  - Doctor fails strict cutover when unmigrated count > 0.
  - Doctor reports deterministic machine-readable gate failures.

### 2) Make repository shipability reproducible from tracked files
- Code targets:
  - `python/envctl_engine/release_gate.py`.
  - `scripts/release_shipability_gate.py`.
  - CI workflow config (repo-specific pipeline files).
- Implementation steps:
  - Keep required tracked scopes aligned with parity-critical runtime/tests/docs.
  - Add cutover CI job that runs release gate with strict profile and refuses untracked required-scope files.
  - Document local developer flow for strict gate and temporary local iteration bypasses.
- Acceptance checks:
  - Fresh clone passes release gate without manual file staging.
  - No parity-required scope remains untracked at release time.

### 3) Burn down shell ownership ledger by explicit wave budgets
- Code targets:
  - `docs/planning/refactoring/envctl-shell-ownership-ledger.json`.
  - `scripts/generate_shell_ownership_ledger.py`.
  - `python/envctl_engine/shell_prune.py`.
- Implementation steps:
  - Define wave budgets with hard numeric targets and deadlines:
    - Wave A: `320 -> <=220` (actions/analysis/pr/worktrees command ownership).
    - Wave B: `<=220 -> <=120` (planning/trees orchestration and ports).
    - Wave C: `<=120 -> <=40` (state/runtime_map/docker parity tails).
    - Wave D: `<=40 -> 0` (final shell module retirement or intentional compatibility list only).
  - Require evidence tests for every non-unmigrated ledger status transition.
  - Enforce command mapping coverage for all manifest `python_complete` commands.
- Acceptance checks:
  - Ledger status histogram progresses at each wave gate.
  - Shell-prune contract passes with progressively stricter budgets.

### 4) Eliminate synthetic defaults from production runtime paths
- Code targets:
  - `python/envctl_engine/command_resolution.py`.
  - `python/envctl_engine/engine_runtime.py`.
  - `python/envctl_engine/config.py` (explicit test-only policy semantics).
- Implementation steps:
  - Restrict synthetic fallback to test-only mode (`ENVCTL_ALLOW_SYNTHETIC_DEFAULTS` + explicit test context guard).
  - Fail startup with actionable diagnostics when real command resolution is unavailable.
  - Remove synthetic usage from primary BATS parity lanes; keep synthetic only for focused unit fixture tests.
- Acceptance checks:
  - `envctl --plan` in production profile cannot run with synthetic commands.
  - Parity E2E runs pass without synthetic flag in core suites.

### 5) Complete requirements orchestration parity per component
- Code targets:
  - `python/envctl_engine/requirements_orchestrator.py`.
  - `python/envctl_engine/requirements/{postgres,redis,supabase,n8n}.py`.
  - `python/envctl_engine/engine_runtime.py:_start_requirements_for_project`.
- Implementation steps:
  - Normalize component lifecycle contracts for all requirements: attach/reuse, conflict retry, readiness probe, failure-class mapping, structured metadata in `RequirementsResult`.
  - Align n8n bootstrap strict/soft policy with env flags and shell semantics.
  - Promote supabase adapter from reliability-contract-only checks to parity startup orchestration with validated health.
- Acceptance checks:
  - Requirement component success requires proven readiness, not only command exit code.
  - Conflict-recovery tests pass for db/redis/n8n/supabase.

### 6) Close service startup parity with listener ownership truth
- Code targets:
  - `python/envctl_engine/service_manager.py`.
  - `python/envctl_engine/process_runner.py`.
  - `python/envctl_engine/engine_runtime.py:_start_project_services`, `_wait_for_service_listener`.
- Implementation steps:
  - Keep PID + listener ownership as canonical `running` criterion.
  - Persist requested/assigned/final ports and retry metadata through every rebound.
  - Ensure frontend backend-URL injection always uses backend final listener port.
- Acceptance checks:
  - Dashboard/health never report reachable URLs for unreachable listeners.
  - Port rebound scenarios update runtime map and rendered URLs consistently.

### 7) Match interactive UX parity and command loop behavior
- Code targets:
  - `python/envctl_engine/engine_runtime.py` (plan selector UI and interactive dashboard loop).
  - `python/envctl_engine/command_router.py` (interactive flag semantics).
- Implementation steps:
  - Preserve TTY-first interactive default behavior (`_should_enter_post_start_interactive`, `_batch_mode_requested`).
  - Stabilize plan selector rendering across terminal sizes (fixed-width layout, truncation, no drift/crooked rows).
  - Keep colorized dashboard semantics equivalent to shell for running/degraded/unreachable states.
- Acceptance checks:
  - Interactive selection and dashboard commands behave consistently under repeated runs.
  - `--batch`/`--non-interactive` paths remain deterministic and non-TTY safe.

### 8) Finish blast-all/stop-all parity as contract-driven cleanup
- Code targets:
  - `python/envctl_engine/engine_runtime.py:_clear_runtime_state`, `_blast_all_ecosystem_cleanup`, `_blast_all_docker_cleanup`, `_blast_all_purge_legacy_state_artifacts`.
  - `python/envctl_engine/ports.py` (`release_session`, `release_all`).
- Implementation steps:
  - Encode explicit blast contract phases: process kill, port sweep, docker container cleanup, optional volume removal policy, state/pointer/lock purge.
  - Add deterministic output and event records for each blast phase and skipped reason (for example Docker unavailable).
  - Ensure idempotency across repeated stop/blast calls.
- Acceptance checks:
  - blast-all removes app processes, tracked infra containers, and runtime artifacts according to flags.
  - repeated blast-all exits cleanly with no false errors.

### 9) Migrate action commands from shell-wrapper defaults to Python-native defaults
- Code targets:
  - `python/envctl_engine/actions_test.py`, `actions_git.py`, `actions_analysis.py`, `actions_worktree.py`.
  - Action dispatch paths in `python/envctl_engine/engine_runtime.py`.
- Implementation steps:
  - Implement Python-native execution strategy for `test/pr/commit/analyze/migrate/delete-worktree` with explicit target resolution.
  - Keep shell wrappers only as optional fallback adapters.
  - Preserve exit contract (`0`, `1`, `2`) and target-selection semantics across `main`/`trees` modes.
- Acceptance checks:
  - action commands do not silently degrade to startup flow.
  - action commands return failure when no valid targets executed.

### 10) Complete state/resume/restart parity with safe migration compatibility
- Code targets:
  - `python/envctl_engine/state.py`.
  - `python/envctl_engine/engine_runtime.py:_resume`, `_resume_restore_missing`, `_state_action`.
  - shell baseline references in `lib/engine/lib/state.sh` for parity checks.
- Implementation steps:
  - Keep JSON state canonical while preserving safe pointer/legacy state loading during compatibility window.
  - Strengthen resume reconciliation: stale/unreachable services trigger deterministic restore policy and visible degraded status when restore fails.
  - Remove any remaining `utils/run.sh` style recovery hints from Python-facing outputs.
- Acceptance checks:
  - resume/restart never produce false healthy summaries.
  - pointer-based state restore works for both JSON and shell legacy fixture variants.

### 11) Decompose monolithic runtime into bounded modules without behavior drift
- Code targets:
  - extract from `python/envctl_engine/engine_runtime.py` into modules such as:
    - `startup_orchestrator.py`
    - `lifecycle_cleanup.py`
    - `interactive_dashboard.py`
    - `resume_orchestrator.py`
- Implementation steps:
  - Perform extraction in behavior-preserving slices gated by existing tests.
  - Keep external API stable (`dispatch_route`, command entry behavior).
- Acceptance checks:
  - full Python unit and BATS parity suites remain green after each extraction wave.
  - reduced complexity in runtime module with unchanged user-visible behavior.

### 12) Align docs and parity manifest with executable truth
- Code targets:
  - `docs/planning/python_engine_parity_manifest.json`.
  - `docs/architecture.md`, `docs/configuration.md`, `docs/troubleshooting.md`, `docs/important-flags.md`, `docs/contributing.md`.
- Implementation steps:
  - Prevent docs/manifest from overstating completion: a command may be `python_complete` only when strict gate + non-synthetic E2E evidence exists.
  - Add documented cutover phase table and exact operator commands for diagnosing failures.
- Acceptance checks:
  - docs and runtime doctor output agree on readiness.
  - manifest status changes are enforced by tests/CI checks.

### 13) Release gate choreography and final shell retirement path
- Code targets:
  - CI release workflow, `python/envctl_engine/release_gate.py`, `python/envctl_engine/shell_prune.py`, launcher flags in `lib/envctl.sh` and `lib/engine/main.sh`.
- Implementation steps:
  - Gate progression:
    - Gate A: strict shipability and zero untracked required scopes.
    - Gate B: synthetic-free core E2E parity.
    - Gate C: shell ledger unmigrated budget reaches zero.
    - Gate D: two consecutive release windows with stable parity suites.
  - After Gate D, move shell fallback to explicit emergency-only mode with deprecation window.
- Acceptance checks:
  - runtime defaults and release policy match gate outcomes.
  - no unsupported hidden fallback loops in default execution path.

## Tests (add these)
### Backend tests
- Extend `tests/python/test_engine_runtime_real_startup.py`:
  - production profile must fail when only synthetic defaults are available.
  - startup succeeds only after listener truth and requirement readiness checks.
- Extend `tests/python/test_requirements_orchestrator.py`:
  - full failure-class mapping parity for postgres/redis/supabase/n8n with retry ceilings.
- Extend `tests/python/test_lifecycle_parity.py`:
  - blast-all contracts: process kill coverage, docker cleanup policy flags, pointer/lock purge, idempotency.
- Extend `tests/python/test_release_shipability_gate.py`:
  - strict shell-prune budget (`max_unmigrated=0`) and tracked-scope invariants.
- Extend `tests/python/test_shell_prune_contract.py`:
  - wave budget checks and evidence requirements for non-unmigrated statuses.
- Extend `tests/python/test_runtime_health_truth.py`:
  - stale/unreachable transitions after resume/restart and synthetic-state failure behavior.
- Extend `tests/python/test_command_resolution.py`:
  - synthetic fallback allowed only in explicit test-only context.
- Add `tests/python/test_cutover_readiness_gates.py`:
  - doctor gate output fails when any strict gate criterion fails.
- Add `tests/python/test_actions_native_execution.py`:
  - test/pr/commit/analyze/migrate/delete-worktree default paths run Python-native logic and preserve exit codes.

### Frontend tests
- Extend `tests/python/test_runtime_projection_urls.py`:
  - projected frontend/backend URLs must match actual listener ports through retries/rebounds/resume.
- Extend `tests/python/test_frontend_env_projection_real_ports.py`:
  - backend URL injection always follows backend final listener port in multi-project trees.
- Add `tests/python/test_dashboard_render_alignment.py`:
  - fixed-width rendering, truncation behavior, and color-safe status display under long plan names.

### Integration/E2E tests
- Harden existing suites to run synthetic-free in strict lane:
  - `tests/bats/python_plan_parallel_ports_e2e.bats`
  - `tests/bats/python_plan_nested_worktree_e2e.bats`
  - `tests/bats/python_listener_projection_e2e.bats`
  - `tests/bats/python_resume_projection_e2e.bats`
  - `tests/bats/python_requirements_conflict_recovery.bats`
  - `tests/bats/python_stop_blast_all_parity_e2e.bats`
  - `tests/bats/parallel_trees_python_e2e.bats`
- Add `tests/bats/python_cutover_strict_gate_e2e.bats`:
  - strict doctor/release gate fails on unmigrated shell entries or untracked required scopes.
- Add `tests/bats/python_no_synthetic_primary_flow_e2e.bats`:
  - `--plan` and interactive dashboard reject synthetic defaults in strict runtime.
- Add `tests/bats/python_actions_native_path_e2e.bats`:
  - action command families execute successfully without requiring `utils/*.sh` defaults.
- Add `tests/bats/python_blast_all_contract_e2e.bats`:
  - verifies blast phases and side effects against expected contract output/events.

## Observability / logging (if relevant)
- Required event classes (must be emitted in strict cutover profile):
  - `engine.mode.selected`, `command.route.selected`, `planning.projects.discovered`
  - `port.lock.acquire`, `port.lock.reclaim`, `port.lock.release`, `port.reservation.failed`
  - `requirements.start`, `requirements.retry`, `requirements.failure_class`, `requirements.healthy`
  - `service.start`, `service.retry`, `service.bind.requested`, `service.bind.actual`, `service.failure`
  - `state.resume`, `state.reconcile`, `runtime_map.write`
  - `cleanup.stop`, `cleanup.stop_all`, `cleanup.blast`
  - `cutover.gate.evaluate`, `cutover.gate.fail_reason`, `shell_prune.evaluate`
- Required artifacts per run (under scoped run dir):
  - `run_state.json`, `runtime_map.json`, `ports_manifest.json`, `error_report.json`, `events.jsonl`, `shell_prune_report.json`.
- Diagnostics:
  - `--doctor` must show gate-by-gate pass/fail plus first actionable failure reasons.

## Rollout / verification
- Baseline verification commands (strict lane):
  - `./.venv/bin/python scripts/report_unmigrated_shell.py --repo . --limit 50`
  - `./.venv/bin/python scripts/verify_shell_prune_contract.py --repo .`
  - `./.venv/bin/python scripts/release_shipability_gate.py --repo . --check-tests`
  - `./.venv/bin/python -m unittest discover -s tests/python -p 'test_*.py'`
  - `bats tests/bats/python_*.bats tests/bats/parallel_trees_python_e2e.bats`
- Gate progression:
  - Gate 0 (baseline freeze): capture ledger hash, parity manifest hash, release-gate output.
  - Gate 1 (shipability): strict gate passes from clean clone.
  - Gate 2 (runtime truth): no false running/healthy statuses under kill/rebind failure drills.
  - Gate 3 (requirements/services parity): conflict and retry suites pass synthetic-free.
  - Gate 4 (lifecycle parity): stop/resume/restart/blast contracts pass and are idempotent.
  - Gate 5 (action parity): test/pr/commit/analyze/migrate/delete-worktree stable across selectors/modes.
  - Gate 6 (shell ownership zero): shell-prune budget reaches zero; fallback remains emergency-only for stabilization window.

## Definition of done
- Python runtime behavior is reproducible from tracked repository contents alone.
- Shell ownership ledger reaches zero unmigrated entries (or only explicit intentional compatibility entries with approved deprecation timeline).
- Strict doctor and release gates pass without synthetic fallbacks in primary workflows.
- Runtime map and interactive URLs always reflect actual listener truth.
- `--plan`/trees orchestration is deterministic across repeated runs with unique ports and stable recovery behavior.
- Lifecycle commands (`stop`, `stop-all`, `blast-all`, `resume`, `restart`) are parity-complete and idempotent.
- Action commands (`test`, `pr`, `commit`, `analyze`, `migrate`, `delete-worktree`) are target-correct and stable.
- Full Python unit + BATS parity/e2e matrix passes in CI and local strict verification.

## Risk register (trade-offs or missing tests)
- Risk: Strict readiness gates will initially surface more startup failures in repos with hidden misconfiguration.
  - Mitigation: keep actionable root-cause output (log snippets, failure classes, required env/command hints).
- Risk: Docker runtime differences across macOS/Linux can still cause timing variance in readiness probes.
  - Mitigation: platform-aware timeout tuning and adapter-level bounded retries.
- Risk: Migration away from shell wrappers for action commands can introduce behavior drift.
  - Mitigation: command-by-command parity fixtures and exit-code contract tests before default path switch.
- Risk: Blast-all parity changes can be destructive if policy flags are ambiguous.
  - Mitigation: explicit volume-policy prompts/flags, deterministic output, and idempotency tests.
- Risk: Large monolithic runtime refactor can introduce regressions during extraction.
  - Mitigation: slice-by-slice extraction with full suite runs at each extraction gate.

## Open questions (only if unavoidable)
- Should `.envctl.sh` remain supported in Python mode only through a constrained hook API, with all arbitrary shell execution patterns deprecated on a defined timeline?
