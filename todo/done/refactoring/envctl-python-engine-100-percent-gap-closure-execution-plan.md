# Envctl Python Engine 100% Gap-Closure and Shell-Prune Execution Plan

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Reach actual Python runtime completion for `envctl` so default workflows (`start`, `--plan`, `--tree`, `resume`, `restart`, `stop`, `stop-all`, `blast-all`, interactive dashboard) are functionally reliable without shell fallback.
  - Remove placeholder/simulated startup paths from normal operation and guarantee runtime truth is based on live listeners/containers/process ownership.
  - Close command-surface parity gaps that currently block common documented flags.
  - Build a deletion-driven migration: remove Bash functionality only after verified Python ownership, so remaining shell code is an explicit unmigrated backlog.
  - Restore interactive and colorized operator UX parity, including logs-follow/tail/duration behavior and dashboard behavior consistency.
- Non-goals:
  - Rewriting downstream application business logic in repositories started by `envctl`.
  - Renaming public command family names or changing top-level CLI identity (`envctl`).
  - Full removal of compatibility launch wrappers (`lib/envctl.sh`, `lib/engine/main.sh`) in this wave.
- Assumptions:
  - Python 3.12 remains required for Python engine mode (`lib/engine/main.sh:98-117`).
  - Docker remains required for infra orchestration parity.
  - Existing config precedence remains env > repo config files (`.envctl`, `.envctl.sh`, `.supportopia-config`) > defaults (`python/envctl_engine/config.py:63-115`).
  - Work must run from committed code, not local-only untracked files.

## Goal (user experience)
`envctl --plan` should consistently create/reuse the intended worktrees, assign unique app+infra ports per project, start real services (not synthetic stand-ins), display URLs that match real listeners, provide actionable health/errors/logs output, and allow deterministic stop/restart/resume/blast operations. Interactive mode should feel complete again (colorful, selector-aware, followable logs, no false-green states).

## Business logic and data model mapping
- Launcher and engine routing:
  - `bin/envctl` -> `lib/envctl.sh:envctl_main` -> `lib/envctl.sh:envctl_forward_to_engine`.
  - Python defaulting logic in `lib/envctl.sh:173-179` and `lib/engine/main.sh:119-125`.
- Python runtime owners:
  - CLI parse and prereqs: `python/envctl_engine/cli.py`.
  - Route parsing: `python/envctl_engine/command_router.py:parse_route`.
  - Runtime orchestrator: `python/envctl_engine/engine_runtime.py:PythonEngineRuntime`.
  - Typed models: `python/envctl_engine/models.py` (`PortPlan`, `ServiceRecord`, `RequirementsResult`, `RunState`).
  - State persistence and shell compatibility: `python/envctl_engine/state.py`.
  - Runtime projection: `python/envctl_engine/runtime_map.py`.
  - Port lock/reservation: `python/envctl_engine/ports.py`.
  - Service lifecycle retries: `python/envctl_engine/service_manager.py`.
  - Requirements lifecycle retries: `python/envctl_engine/requirements_orchestrator.py` and `python/envctl_engine/requirements/*.py`.
- Shell parity baseline (current behavioral authority for many paths):
  - CLI flags and aliases: `lib/engine/lib/run_all_trees_cli.sh:174`.
  - Planning/worktree orchestration: `lib/engine/lib/planning.sh`, `lib/engine/lib/run_all_trees_helpers.sh:837-1031`.
  - Startup/retry/attach behavior: `lib/engine/lib/services_lifecycle.sh:1746-1959`.
  - Requirements behavior: `lib/engine/lib/requirements_core.sh:1463-1508`, `lib/engine/lib/requirements_supabase.sh:1766-2106`, `lib/engine/lib/requirements_supabase.sh:2108-2356`.
  - Resume/stop/blast behavior: `lib/engine/lib/state.sh:793-930`, `lib/engine/lib/state.sh:1707-1796`.

## Current behavior (verified in code)
- Python runtime parity is overstated in readiness/reporting:
  - `PythonEngineRuntime.PARTIAL_COMMANDS` is empty (`python/envctl_engine/engine_runtime.py:53`) and manifest marks all commands `python_complete` (`docs/planning/python_engine_parity_manifest.json:8-42`).
  - Router still rejects many documented shell flags (`python/envctl_engine/command_router.py:273-275`).
  - Verified command failure example: `PYTHONPATH=python .venv/bin/python -m envctl_engine.runtime.cli --parallel-trees --help` -> `Unknown option: --parallel-trees` (exit 1).
- Documented flag set and Python parser are materially mismatched:
  - `docs/important-flags.md:44-45` documents `--parallel-trees`, `--parallel-trees-max`.
  - Shell parser contains 105 long flags vs 64 in Python parser; 48 shell flags missing in parser (measured via `.venv/bin/python` script comparing `run_all_trees_cli.sh` and `command_router.py`).
- Requirements adapters are not actually implemented:
  - `python/envctl_engine/requirements/postgres.py`, `redis.py`, `supabase.py`, `n8n.py` are generic `run_with_retry` wrappers (`1-7`) with no Docker/container/health orchestration parity.
  - Python default now fails without explicit requirement commands or synthetic opt-in (`python/envctl_engine/command_resolution.py:26-57`), proving missing adapter ownership.
- Startup still relies heavily on synthetic test mode in core tests:
  - `tests/python/test_engine_runtime_real_startup.py:62-70` sets `ENVCTL_ALLOW_SYNTHETIC_DEFAULTS=true` in default test config.
  - Multiple startup tests explicitly run with synthetic defaults (`test_engine_runtime_real_startup.py:126`, `153`, `185`, `221`, `325`).
- Resume behavior is still partial:
  - `_resume` only reconciles and warns; it does not restart missing services/requirements (`python/envctl_engine/engine_runtime.py:676-703`).
  - Shell `resume_from_state` prompts and restarts missing services (`lib/engine/lib/state.sh:1769-1784`).
- Logs/dashboard flags are parsed but not operationally implemented:
  - Parser accepts `--logs-follow`, `--logs-duration`, `--logs-no-color`, `--dashboard-interactive` (`python/envctl_engine/command_router.py:154-204`).
  - Runtime `logs` path only tails static lines and ignores follow/duration/no-color semantics (`python/envctl_engine/engine_runtime.py:1794-1827`).
- Runtime projection can show URLs for stale/unreachable services:
  - `runtime_map` always projects URLs from stored ports, independent of status (`python/envctl_engine/runtime_map.py:39-52`).
  - `_service_truth_status` can mark service `stale`/`unreachable`, but projection still includes URL values.
- Runtime and lock scope remain global per runtime root, not repo-scoped:
  - Runtime root is `${RUN_SH_RUNTIME_DIR}/python-engine` (`python/envctl_engine/engine_runtime.py:72`), with default `/tmp/envctl-runtime` (`python/envctl_engine/config.py:12`).
  - Lock dir is `${RUN_SH_RUNTIME_DIR}/python-engine/locks` (`python/envctl_engine/engine_runtime.py:65`).
  - `release_all()` is used in cleanup/failure paths (`python/envctl_engine/engine_runtime.py:190`, `2307`; `python/envctl_engine/ports.py:167-182`).
- `blast-all` still carries host-wide kill risk:
  - Process patterns include broad tokens (`vite`, `gunicorn`, `celery`, `npm run dev`, `next dev`) in `_blast_all_process_patterns` (`python/envctl_engine/engine_runtime.py:2354-2375`).
  - This can terminate unrelated host processes outside the active repo.
- `.envctl.sh` hook parity is not implemented:
  - Python config loader parses key-value lines only (`python/envctl_engine/config.py:118-146`).
  - No Python hook execution bridge exists for `envctl_define_services` / `envctl_setup_infrastructure`, while shell calls these (`lib/engine/lib/run_all_trees_helpers.sh:1033-1037`).
- Planning/worktree parity is incomplete:
  - Python plan path filters discovered projects (`python/envctl_engine/engine_runtime.py:241-317`) but does not perform worktree create/delete orchestration performed by shell (`lib/engine/lib/run_all_trees_helpers.sh:837-1031` with `setup-worktrees.sh` integration).
  - Python planning selection memory is global under runtime root (`python/envctl_engine/engine_runtime.py:642-675`), not repo-scoped.
- Duplicate project-identity collision remains possible:
  - Discovery has no dedupe guard (`python/envctl_engine/planning.py:44-66`).
  - Startup aggregates with `services.update(project_services)` (`python/envctl_engine/engine_runtime.py:175`), allowing silent overwrite on name collision.
- Release/doctor gates are structurally weak for “100% complete” claim:
  - `_doctor_readiness_gates` marks lifecycle true when terminate callable exists (`python/envctl_engine/engine_runtime.py:1313`).
  - `_doctor` shipability check uses `check_tests=False` (`python/envctl_engine/engine_runtime.py:1316`).
  - Shell prune contract currently passes with all entries unmigrated:
    - `docs/planning/refactoring/envctl-shell-ownership-ledger.json` contains 320 `unmigrated` entries (verified via `.venv/bin/python`).
    - `scripts/report_unmigrated_shell.py --repo . --limit 5` returns `shell_migration_status: pass`, `unmigrated_count: 320`.
- Planning docs baseline is incomplete:
  - `docs/planning/README.md` does not exist (only `docs/planning/refactoring/*` plus parity manifest are present).
- Installer UX gap remains:
  - `scripts/install.sh` writes shell rc PATH block then exits silently (`scripts/install.sh:96-114`), which leads to immediate `envctl: command not found` until shell reload.

## Root cause(s) / gaps
- Cutover governance gap:
  - “Python complete” status is based on command mapping shape, not measured behavior parity across flags, interactive UX, and requirements adapters.
- Ownership gap:
  - Python owns dispatch shell but not full orchestration semantics (notably requirements adapters and planning setup lifecycle).
- Truth-model gap:
  - Health/projection/doctor do not all derive from the same strict liveness model.
- Scope-isolation gap:
  - runtime/locks/planning memory are not namespaced by repo identity; cleanup remains overly broad.
- Compatibility gap:
  - `.envctl.sh` function-based hooks have no Python equivalent bridge.
- Test-gap:
  - many tests still rely on synthetic defaults and do not prove real repo startup parity.
- Prune-gap:
  - shell ownership ledger tracks inventory but not migration closure; all entries are still unmigrated.
- UX gap:
  - Python interactive/dashboard/logs behavior is not feature-complete compared with shell expectations and docs.

## Plan
### 1) Define hard “100% complete” acceptance contract and make it executable
- Add `docs/planning/README.md` with required readiness gates and parity evidence format.
- Introduce a mandatory completion checklist in release gate:
  - real-repo startup smoke pass (no synthetic mode),
  - parity command/flag matrix pass,
  - shell-prune unmigrated budget threshold (must trend to zero by final phase),
  - full Python and BATS suites green.
- Update `python/envctl_engine/release_gate.py` and `python/envctl_engine/engine_runtime.py:_doctor_readiness_gates` to enforce behavior-based criteria rather than static manifests.

### 2) Implement repo-scoped runtime and lock namespaces
- Move from global `${RUN_SH_RUNTIME_DIR}/python-engine` to `${RUN_SH_RUNTIME_DIR}/python-engine/<repo_hash>/...`.
- Scope all pointers (`.last_state*`), run artifacts, planning memory, and lock directories by repo hash.
- Replace broad `release_all()` cleanup calls with `release_session()` / repo-scoped release in normal flows; reserve `release_all()` for explicit host-wide blast mode.
- Add migration loader to read old global artifacts once, then rewrite into repo scope.

### 3) Replace generic requirement wrappers with real requirement adapters
- Implement adapter modules with shell-equivalent behavior contracts:
  - `python/envctl_engine/requirements/postgres.py`: create/start/reuse/wait healthy, attach existing mapped port.
  - `python/envctl_engine/requirements/redis.py`: recreate on mapping drift, readiness probe parity (`redis-cli ping` contract).
  - `python/envctl_engine/requirements/supabase.py`: db/auth/gateway startup sequencing, bind-conflict reassign with env/worktree config updates.
  - `python/envctl_engine/requirements/n8n.py`: start/restart/bootstrap reset policy parity, strict/soft bootstrap semantics.
- Wire adapters into `_start_requirement_component` replacing command-exit orchestration path for default runtime.
- Keep explicit `ENVCTL_REQUIREMENT_*_CMD` as override path, but default should be adapter-based for supported topologies.

### 4) Complete planning/worktree ownership in Python
- Port shell planning workflow (`lib/engine/lib/planning.sh`, `run_all_trees_helpers.sh:837-1031`) into Python:
  - interactive selection counts with existing worktree counts,
  - create/reuse/delete worktrees via `utils/setup-worktrees.sh` bridge or native Python equivalent,
  - planning-file move-to-done behavior (`PLANNING_KEEP_PLAN` semantics),
  - `ENVCTL_PLANNING_DIR` normalization parity.
- Preserve selector strictness behavior and make fallback explicit:
  - no silent “selector miss -> run all” unless explicitly configured.

### 5) Close command parser parity against shell baseline
- Generate an automated parity artifact from `run_all_trees_cli.sh` and fail CI if high-value flags are unsupported.
- Add Python support for currently missing documented flags:
  - `--parallel-trees`, `--parallel-trees-max`, `--refresh-cache`, `--fast`, `--docker`, `--setup-worktrees`, `--include-existing-worktrees`, debug/trace flags used in production workflows.
- For unsupported-by-design flags, add explicit actionable errors with recommended alternatives, not generic unknown-option failures.

### 6) Rebuild lifecycle parity (`resume`, `restart`, `stop`, `stop-all`, `blast-all`)
- `resume`:
  - detect missing services and perform targeted restart (with optional prompt in interactive mode).
  - verify requirements runtime truth before reporting healthy projection.
- `restart`:
  - explicit stop with ownership verification -> start with prior port intentions.
- `stop`:
  - keep selector-aware stop behavior and persist remaining state safely.
- `stop-all` / `blast-all`:
  - keep termination escalation via `ProcessRunner.terminate`.
  - add deterministic verification summaries (terminated, skipped-by-ownership, still-alive).
  - make host-wide ecosystem kill optional and default to repo-scoped cleanup.

### 7) Harden blast-all safety model and policy
- Split blast policies:
  - repo-scoped default (only processes/containers linked to repo runtime metadata).
  - explicit host-wide mode requiring `--force` + confirmation (or explicit env override in batch).
- Replace broad pattern pkill for generic app names with repo-owned PID registry and command fingerprint matching.
- Preserve current Docker volume policy flags while reducing accidental unrelated host process kills.

### 8) Unify runtime truth + projection rules
- Projection should exclude or flag stale/unreachable services:
  - URLs shown as `null` or `stale:<port>` for non-running services.
- Ensure `health`, `errors`, dashboard, and runtime_map all use one truth reconciliation pass.
- Add explicit requirement truth reconciliation beyond saved success flags (container health + mapped port checks).

### 9) Restore interactive + colorful UX parity
- Expand interactive dashboard command loop to match shell operational ergonomics:
  - target selection prompts for restart/logs/test actions,
  - stable command hints and per-project grouped service details,
  - colorized statuses with parity badges.
- Implement `logs` behavior parity:
  - support `--logs-follow`, `--logs-duration`, `--logs-no-color`, and project/service filtering.
- Ensure interactive mode never reports “healthy” for simulated, stale, or unreachable services.

### 10) Implement safe `.envctl.sh` hook bridge
- Add constrained hook bridge for:
  - `envctl_define_services`,
  - `envctl_setup_infrastructure`.
- Execute hooks via isolated subprocess with structured output contract (JSON), not unrestricted sourcing in Python process.
- Add feature flag + diagnostics to allow controlled deprecation later without breaking current repos.

### 11) Enforce deletion-driven shell migration
- Use `docs/planning/refactoring/envctl-shell-ownership-ledger.json` as active migration ledger:
  - classify entries by wave, not all `unmigrated`.
- Update `python/envctl_engine/shell_prune.py` so contract fails when unmigrated count exceeds allowed threshold for current phase.
- Add per-wave pruning steps:
  - Wave A: remove duplicate status/log rendering helpers once Python dashboard/logs parity is proven.
  - Wave B: remove startup/retry/requirements shell functions once Python adapters pass parity e2e.
  - Wave C: reduce shell runtime to minimal compatibility shim.

### 12) Tighten doctor/shipability to block false-ready states
- `doctor` must report:
  - parser parity delta,
  - synthetic mode usage in latest run,
  - repo-scope runtime isolation status,
  - unmigrated shell ledger counts.
- `release_shipability_gate.py` must fail when:
  - manifest says complete but parser parity delta is non-zero for documented flags,
  - unmigrated shell count exceeds phase budget,
  - tests are skipped on release branch,
  - runtime smoke uses synthetic defaults.

### 13) Fix installer and first-run usability traps
- Update `scripts/install.sh` to print clear post-install instruction:
  - exact shell reload command (`source ~/.zshrc` etc) and immediate one-shot PATH export line.
- Add `envctl doctor` check that detects “installed but not on PATH” context and prints remediation.

### 14) Documentation alignment and drift prevention
- Update:
  - `README.md`,
  - `docs/important-flags.md`,
  - `docs/configuration.md`,
  - `docs/troubleshooting.md`,
  - `docs/architecture.md`.
- Add automated docs/parity lint:
  - documented flags must exist in parser support map,
  - manifest completeness cannot exceed measured parity coverage.

## Tests (add these)
### Backend tests
- Extend `tests/python/test_engine_runtime_real_startup.py`:
  - real adapter paths for postgres/redis/supabase/n8n (no synthetic mode).
  - resume restart of missing services/requirements.
  - projection masking for stale/unreachable services.
- Extend `tests/python/test_lifecycle_parity.py`:
  - repo-scoped blast behavior by default.
  - host-wide blast requires explicit opt-in.
  - restart replacement of PIDs and no orphaned processes.
- Extend `tests/python/test_cli_router_parity.py` and add generated parity fixture:
  - assert support for documented high-value flags from `docs/important-flags.md`.
- Add `tests/python/test_runtime_scope_isolation.py`:
  - two repos sharing runtime base cannot read/write each other’s state/locks.
- Add `tests/python/test_hooks_bridge.py`:
  - `.envctl.sh` service/infra hook bridge success, failures, and diagnostics.
- Extend `tests/python/test_release_shipability_gate.py`:
  - fail when shell ledger unmigrated count is above phase threshold.
  - fail when parser/docs parity drifts.

### Frontend tests
- Extend `tests/python/test_runtime_projection_urls.py`:
  - stale/unreachable service rows do not emit healthy URL projection.
  - rebound/retry projection remains aligned with final listeners.
- Extend `tests/python/test_frontend_env_projection_real_ports.py`:
  - frontend `PORT` and backend target env always reflect per-project final ports in multi-tree mode.
- Add `tests/python/test_dashboard_rendering_parity.py`:
  - color/no-color rendering parity and status badge correctness.

### Integration/E2E tests
- Extend existing BATS:
  - `tests/bats/python_plan_parallel_ports_e2e.bats`:
    - run without synthetic defaults and require real adapter startup behavior.
  - `tests/bats/python_resume_projection_e2e.bats`:
    - resume restarts missing services and updates runtime map.
  - `tests/bats/python_stop_blast_all_parity_e2e.bats`:
    - verify repo-scoped default blast and guarded host-wide blast.
  - `tests/bats/python_engine_parity.bats`:
    - assert documented flags accepted by Python parser.
- Add new BATS:
  - `tests/bats/python_logs_follow_parity_e2e.bats` (`--logs-follow`, `--logs-duration`, `--logs-no-color` behavior).
  - `tests/bats/python_planning_worktree_setup_e2e.bats` (create/reuse/delete semantics from planning selections).
  - `tests/bats/python_cross_repo_isolation_e2e.bats` (state and lock isolation).
  - `tests/bats/python_hook_bridge_e2e.bats` (`.envctl.sh` hook compatibility).

## Observability / logging (if relevant)
- Emit structured events for:
  - command parser parity checks,
  - adapter lifecycle transitions,
  - repo-scope lock/state selection,
  - blast policy mode and kill decisions,
  - hook bridge execution results.
- Persist run artifacts under repo-scoped runtime:
  - `run_state.json`, `runtime_map.json`, `ports_manifest.json`, `error_report.json`, `events.jsonl`.
- Add operator-readable summaries:
  - “what changed” for ports, retries, and scope decisions after each start/restart/stop/blast.

## Rollout / verification
- Phase 0: Baseline and guardrails
  - Add `docs/planning/README.md`, parity gate updates, and parser/docs drift checks.
- Phase 1: Scope and lifecycle safety
  - repo-scoped runtime/locks, safer blast policies, restart/resume parity.
- Phase 2: Requirements and planning ownership
  - real adapters + Python planning/worktree setup parity.
- Phase 3: UX completion
  - logs follow/duration/color parity, interactive dashboard parity.
- Phase 4: Shell prune waves
  - convert ledger statuses, remove verified migrated shell functions/modules.
- Verification commands (must be green per phase gate):
  - `.venv/bin/python -m unittest discover -s tests/python -p 'test_*.py'`
  - `bats tests/bats/python_*.bats`
  - `bats tests/bats/*.bats`
  - `.venv/bin/python scripts/release_shipability_gate.py --repo . --check-tests`
  - `.venv/bin/python scripts/report_unmigrated_shell.py --repo . --limit 20`

## Definition of done
- Python runtime is functionally complete for documented high-value workflows without synthetic defaults.
- Runtime state and lock handling is repo-scoped and cross-repo safe.
- `resume/restart/stop/stop-all/blast-all` behaviors are parity-tested, deterministic, and idempotent.
- Dashboard/health/errors/logs outputs are grounded in live truth and support documented controls.
- Planning mode fully owns planning-file selection and worktree lifecycle semantics.
- Shell ledger unmigrated count is reduced to the intentional-keep set (or zero for removable orchestration modules), with deletion evidence.
- Docs, parser, manifest, doctor, and release gate all agree on completion state.

## Risk register (trade-offs or missing tests)
- Risk: stricter startup truth and synthetic-default removal will expose more immediate failures in repos lacking explicit commands/adapters.
  - Mitigation: actionable error classes, migration docs, temporary explicit shell fallback path.
- Risk: repo-scoped runtime migration can strand previous global state.
  - Mitigation: one-time migration/compat loader + clear cleanup command.
- Risk: blast-all safety tightening can surprise users expecting host-wide cleanup.
  - Mitigation: explicit host-wide mode with clear flags and operator prompts.
- Risk: hook bridge introduces shell compatibility complexity.
  - Mitigation: constrained subprocess contract, strict output schema, dedicated tests.
- Risk: deleting shell too early can regress edge-case workflows.
  - Mitigation: wave-based deletion gated by parity e2e and ledger status transitions.

## Open questions (only if unavoidable)
- Should `blast-all` default to repo-scoped cleanup permanently, with host-wide cleanup always opt-in?
- What deprecation window should be enforced for `.envctl.sh` function hooks once Python hook bridge parity is complete?
