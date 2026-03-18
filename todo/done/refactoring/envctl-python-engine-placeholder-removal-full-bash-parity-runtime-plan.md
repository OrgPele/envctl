# Envctl Python Engine Placeholder Removal and Full Bash-Parity Runtime Plan

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Remove all synthetic placeholder startup behavior from the Python runtime default path so `envctl` only reports real services/requirements as healthy/running.
  - Reach behaviorally equivalent Python orchestration for the Bash shell engine’s primary workflows (`main`, `trees`, `--plan`, `--resume`, interactive dashboard loop, lifecycle cleanup).
  - Preserve the existing `envctl` CLI contract, planning UX, and developer workflows while eliminating Python/Bash parity drift.
  - Make runtime truth (dashboard, `health`, `errors`, `runtime_map`) reflect live process/listener/container state instead of command-exit assumptions.
- Non-goals:
  - Rewriting downstream application repositories (`backend`/`frontend` business code) launched by `envctl`.
  - Renaming `envctl` or changing high-value command names/flags.
  - Keeping shell orchestration as a permanent co-primary engine once Python parity is achieved.
- Assumptions:
  - Python 3.12 remains the Python runtime requirement (launcher/engine handoff currently enforces this in `lib/engine/main.sh`).
  - Docker remains the infra backend for Postgres/Redis/Supabase/n8n orchestration.
  - Config precedence remains compatible with current docs and code (`env` -> `.envctl` / `.envctl.sh` / `.supportopia-config` -> defaults) via `python/envctl_engine/config.py`.
  - Planning-doc style baseline is existing `docs/planning/refactoring/*.md`; `docs/planning/README.md` is currently missing and should be treated as a documentation gap, not a blocker.

## Goal (user experience)
A user can run `envctl --plan` (or `envctl`, `envctl --tree`, `envctl --resume`) and get the same trust level and operational behavior they had in Bash:
- services and requirements shown in the dashboard are actually running and healthy,
- displayed URLs match real listeners and final rebound ports,
- planning mode is interactive and state-aware (selection/counts/reuse),
- lifecycle commands (`stop`, `stop-all`, `blast-all`, `restart`, `resume`) behave predictably and idempotently,
- and Python mode no longer silently substitutes fake listeners or fake infra success in normal workflows.

## Business logic and data model mapping
- Launcher and engine handoff:
  - `bin/envctl` -> `lib/envctl.sh:envctl_main` -> `lib/envctl.sh:envctl_forward_to_engine` -> `lib/engine/main.sh`.
  - Python runtime defaulting currently occurs in both launcher and engine bootstrap (`lib/envctl.sh`, `lib/engine/main.sh`).
  - Temporary shell fallback is controlled by `ENVCTL_ENGINE_SHELL_FALLBACK` (documented in `docs/configuration.md`; parsed in `python/envctl_engine/config.py`).
- Python runtime control flow (current owner for Python mode):
  - CLI parse/dispatch entry: `python/envctl_engine/cli.py:run`
  - Route parsing: `python/envctl_engine/command_router.py:parse_route`
  - Runtime dispatch and lifecycle orchestration: `python/envctl_engine/engine_runtime.py:PythonEngineRuntime.dispatch`
- Canonical Python state/models:
  - `python/envctl_engine/models.py`
    - `PortPlan`: requested/assigned/final/source/retries
    - `ServiceRecord`: service runtime record (now includes `synthetic` marker)
    - `RequirementsResult`: per-project infra result maps
    - `RunState`: canonical runtime session state
  - `python/envctl_engine/state.py`
    - JSON load/save (`load_state`, `dump_state`, `state_to_dict`)
    - legacy shell state compatibility (`load_legacy_shell_state`, `load_state_from_pointer`)
- Runtime truth and projection:
  - `python/envctl_engine/engine_runtime.py`
    - service truth reconciliation (`_reconcile_state_truth`, `_service_truth_status`)
    - dashboard rendering (`_print_dashboard_snapshot`, `_print_dashboard_service_row`, `_print_dashboard_n8n_row`)
  - `python/envctl_engine/runtime_map.py`
    - canonical URL/port projection (`build_runtime_map`, `build_runtime_projection`)
- Ports and lock lifecycle:
  - `python/envctl_engine/ports.py:PortPlanner`
    - lock files, stale reclaim, availability modes (`auto`, `socket_bind`, `listener_query`, `lock_only`)
  - runtime reservation call path in `python/envctl_engine/engine_runtime.py:_reserve_project_ports`
- Requirements/service orchestration:
  - `python/envctl_engine/requirements_orchestrator.py`
    - failure classes and retry control (`RequirementsOrchestrator`, `RequirementOutcome`)
  - `python/envctl_engine/service_manager.py`
    - service retries and attach model (`start_service_with_retry`, `start_project_with_attach`)
  - `python/envctl_engine/process_runner.py`
    - subprocess/process and port/listener probes (`run`, `start`, `wait_for_port`, `wait_for_pid_port`, `pid_owns_port`, `terminate`)
  - `python/envctl_engine/requirements/*.py`
    - lightweight retry wrappers currently present (`postgres.py`, `redis.py`, `supabase.py`, `n8n.py`) but not full Bash-parity adapters yet
- Shell parity baseline (actual mature behavior authority today):
  - CLI parsing and command flags: `lib/engine/lib/run_all_trees_cli.sh:run_all_trees_cli_parse_args`
  - Plan/tree orchestration: `lib/engine/lib/run_all_trees_helpers.sh:start_tree_job_with_offset`, `run_all_trees_start_tree_projects`
  - Service lifecycle and attach/retry: `lib/engine/lib/services_lifecycle.sh:start_service_with_retry`, `start_project_with_attach`
  - Infra orchestration: `lib/engine/lib/requirements_core.sh:start_tree_postgres`, `start_tree_redis`, `ensure_tree_requirements`
  - Supabase/n8n orchestration: `lib/engine/lib/requirements_supabase.sh:start_tree_supabase`, `start_tree_n8n`, `restart_tree_n8n`
  - State/resume/attach and blast cleanup: `lib/engine/lib/state.sh:save_state`, `resume_from_state`, `load_state_for_command`, `load_attach_state`, `cleanup_blast_all`

## Current behavior (verified in code)
- Python runtime is still default-selected by launcher/engine when fallback is not forced:
  - `lib/envctl.sh` defaults `ENVCTL_ENGINE_PYTHON_V1=true` when unset (unless `ENVCTL_ENGINE_SHELL_FALLBACK=true`)
  - `lib/engine/main.sh` also defaults Python path when not explicitly disabled
- Placeholder/synthetic defaults still exist in Python runtime:
  - requirements default command is synthetic success (`python/envctl_engine/engine_runtime.py:_default_requirement_command`)
  - backend/frontend default command is a Python socket listener + sleep placeholder (`python/envctl_engine/engine_runtime.py:_default_service_command`)
- Python now marks synthetic placeholders explicitly (recent trust fix), but still uses them in default flow when no explicit commands are configured:
  - service markers are persisted on `ServiceRecord.synthetic`
  - requirements maps now carry `simulated` markers
  - dashboard renders `Simulated` for synthetic services/requirements (`_print_dashboard_service_row`, `_print_dashboard_n8n_row`)
  - runtime truth returns `simulated` in `_service_truth_status` for live synthetic services
  - startup summary prints a warning when synthetic defaults are used (`_print_summary`)
- Requirement health is still based on command exit semantics, not proven readiness:
  - `_start_requirement_component` treats `process_runner.run(...).returncode == 0` as success
  - `_requirements_ready` checks only `enabled` + `success`, not container/port/health probe truth
- Service startup uses real listener verification, but against whichever command was launched (including synthetic placeholders):
  - `_start_project_services` validates backend/frontend listeners via `_wait_for_service_listener`
  - this means placeholder socket binders can appear truthy even though real app code is not running
- Command override resolution is partially mature:
  - runtime now resolves command overrides from `self.env` and `config.raw`
  - but default resolution still falls back to placeholders instead of repo-specific real commands or hard failure
- Planning/discovery and state infrastructure exist but do not guarantee Bash-level parity:
  - planning discovery/selection helpers exist in `python/envctl_engine/planning.py`
  - pointer/legacy state compatibility exists in `python/envctl_engine/state.py`
  - interactive dashboard loop exists in Python and is now default in TTY flows
  - however core orchestration semantics (real services/infra parity) remain incomplete
- Blast-all improved substantially (recent parity work), but broader lifecycle parity is still incomplete:
  - Python blast-all now includes process sweep, port sweep, Docker container cleanup, volume policy flags, and legacy pointer/lock purges
  - resume/restart/stop flows still do not fully mirror Bash edge-case behavior and operator ergonomics
- Real user repro confirms the remaining gap:
  - in a real repo without `.envctl`/`.envctl.sh` (for example, a supportopia-style layout with `backend/pyproject.toml` and `frontend/package.json`), Python `--plan` can still start synthetic placeholder services unless explicitly configured or shell fallback is forced
  - this produces misleading “working enough” outcomes unless the runtime truth markers are surfaced (now fixed to `Simulated`)

## Root cause(s) / gaps
- Cutover sequencing gap:
  - Python was made default before real command/infra orchestration replaced placeholder defaults.
- Placeholder fallback gap:
  - `_default_requirement_command` and `_default_service_command` remain executable placeholders in production flow instead of test-only fixtures or hard failures.
- Command resolution gap:
  - Python runtime lacks a real repo-aware command resolution pipeline equivalent to Bash startup contracts and repo hooks.
- Requirements readiness gap:
  - infra success is not tied to container existence, host-port mapping, or health probe truth.
- Service semantics gap:
  - Python validates listener existence, but not whether it started the intended app process (a placeholder listener satisfies the same checks).
- Parity ownership gap:
  - Bash still owns richer orchestration logic (requirements attach/recreate/retry, n8n bootstrap behavior, resume/recovery ergonomics, interactive UX workflows).
- Hook compatibility gap:
  - `.envctl.sh` is parsed safely in Python config load, but Bash hook execution behavior (`envctl_define_services`, `envctl_setup_infrastructure`) is not fully ported.
- Runtime truth confidence gap:
  - synthetic markers fix UI honesty but do not satisfy the user goal of “really working like Bash.”
- Documentation/troubleshooting gap:
  - docs still describe Python-first runtime while operationally significant parity gaps remain for real startup orchestration.

## Plan
### 1) Freeze placeholder behavior behind an explicit opt-in (stop using it as silent default)
- Convert synthetic default commands into an explicit, test-only compatibility mode:
  - add a single explicit runtime flag/env (for example `ENVCTL_ALLOW_SYNTHETIC_DEFAULTS=true`) for fixtures/tests only
  - default production behavior must be: resolve real command or fail with actionable error
- Change `python/envctl_engine/engine_runtime.py`:
  - `_default_requirement_command` and `_default_service_command` become test harness helpers only (or move to test-only utility module)
  - `_requirement_command_resolved` / `_service_start_command_resolved` return structured failure when no real command can be resolved
- Add error classes and operator messages:
  - `missing_service_start_command`
  - `missing_requirement_start_command`
  - `autodetect_failed_backend`
  - `autodetect_failed_frontend`
  - `autodetect_failed_requirements`
- Maintain truthful warnings for any remaining synthetic mode until fully removed.

### 2) Build Python command-resolution parity (real backend/frontend commands, no placeholders)
- Add a typed command-resolution module (new file, e.g. `python/envctl_engine/command_resolution.py`) with explicit contracts:
  - resolve backend command
  - resolve frontend command
  - validate cwd and executable presence
  - emit structured reason when unresolved
- Implement repo-aware autodetect heuristics to match common Bash-era expectations:
  - backend:
    - `backend/pyproject.toml` + FastAPI/Uvicorn patterns -> `poetry run uvicorn ...` or `.venv`/`python -m uvicorn ...` policy
    - `backend/package.json` -> `npm|pnpm|bun run dev`
  - frontend:
    - `frontend/package.json` with `scripts.dev` -> preferred package manager `dev` command
    - Vite detection (`vite` script / dependency) and port env injection parity
- Honor explicit overrides first:
  - `ENVCTL_BACKEND_START_CMD`, `ENVCTL_FRONTEND_START_CMD`
  - `.envctl`/`.envctl.sh`/`.supportopia-config` equivalents via `config.raw`
- Preserve Bash-compatible hook extension path:
  - if `.envctl.sh` defines service hooks and Python hook bridge is enabled, use hook-provided command definitions over autodetect
- Files/modules:
  - `python/envctl_engine/engine_runtime.py`
  - new `python/envctl_engine/command_resolution.py`
  - `python/envctl_engine/config.py` (if new config policy/flags are needed)

### 3) Replace synthetic requirements defaults with real infra adapters (Postgres/Redis/Supabase/n8n)
- Stop treating requirements as generic “shell command exit 0” tasks.
- Implement typed requirement adapters in `python/envctl_engine/requirements/`:
  - `postgres`: create/start/reuse/wait healthy; attach existing container on matching host-port mapping
  - `redis`: attach/recreate parity when container shape/mapping mismatches (mirror shell redis behavior)
  - `supabase`: db/auth/gateway sequencing + compose project naming parity
  - `n8n`: startup/restart/bootstrap policy parity, strict vs soft bootstrap handling (`ENVCTL_STRICT_N8N_BOOTSTRAP`)
- Integrate adapters into `engine_runtime._start_requirement_component` so `RequirementOutcome.success` means proven readiness:
  - container exists (or attached)
  - host port is mapped to expected service
  - readiness/health probe passes
- Populate richer `RequirementsResult` metadata:
  - `provider` / `container_name` / `compose_project`
  - `simulated` removed or only allowed under explicit test mode
  - `failure_class` and retry counts preserved for diagnostics
- Files/modules:
  - `python/envctl_engine/engine_runtime.py`
  - `python/envctl_engine/requirements_orchestrator.py`
  - `python/envctl_engine/requirements/postgres.py`
  - `python/envctl_engine/requirements/redis.py`
  - `python/envctl_engine/requirements/supabase.py`
  - `python/envctl_engine/requirements/n8n.py`
  - `python/envctl_engine/process_runner.py`

### 4) Make service startup prove the intended app is running (not just “some listener”)
- Extend service startup validation beyond listener existence:
  - confirm the listener belongs to the launched PID/process tree (already partially supported by `ProcessRunner.pid_owns_port` / `wait_for_pid_port`)
  - classify mismatches (listener exists but wrong process / listener absent / process exited)
- Persist execution provenance in `ServiceRecord`:
  - resolved command
  - command source (`configured`, `autodetected`, `hook`, `legacy_bridge`)
  - startup failure class / last error (if startup fails)
- Add “intended app process” validation heuristics:
  - backend: process tree includes `uvicorn`, `python`, `gunicorn`, or configured executable; port ownership must match
  - frontend: process tree includes `vite`, `node`, `bun`, `npm`, `pnpm`, `yarn`; final rebound port must be observed
- Remove any code path that silently marks service `running` without proof in normal mode.
- Files/modules:
  - `python/envctl_engine/service_manager.py`
  - `python/envctl_engine/process_runner.py`
  - `python/envctl_engine/engine_runtime.py`
  - `python/envctl_engine/models.py`
  - `python/envctl_engine/state.py`

### 5) Rework runtime truth so dashboard/health/errors are authoritative across startup, resume, and interactive loop
- Tighten `_reconcile_state_truth` and `_service_truth_status`:
  - degrade services immediately when PID is dead, listener is down, or PID no longer owns the listener
  - mark “restarting” / “starting” states explicitly when applicable (instead of only `stale`/`unreachable`)
- Extend requirement truth checks for `health`/dashboard:
  - verify container health/mapping for db/redis/n8n/supabase components, not only stored success fields
  - n8n status should be derived from actual runtime checks or adapter health probe, not stale `RequirementsResult.success`
- Ensure `runtime_map` generation uses reconciled final ports and live status state before rendering dashboards and action outputs.
- Files/modules:
  - `python/envctl_engine/engine_runtime.py`
  - `python/envctl_engine/runtime_map.py`
  - `python/envctl_engine/state.py`
  - requirement adapters / probe helpers

### 6) Port Bash planning workflow semantics (interactive selection, counts, reuse, create) to Python parity
- Preserve the new Python TUI menu work, but make plan execution semantics match Bash pipeline:
  - discovery from `ENVCTL_PLANNING_DIR`
  - remembered existing counts and tree reuse behavior
  - deterministic multi-selection / multi-count execution
  - clear reporting of reused vs newly created worktrees
- Match Bash helper behavior in `run_all_trees_helpers.sh`:
  - worktree path naming and nested `trees/<feature>/<iter>` handling
  - port offsets and environment propagation in `start_tree_job_with_offset`
- Tighten strictness policy:
  - selectors that match nothing should fail (or prompt) under a documented flag instead of silently falling back to “all”
- Files/modules:
  - `python/envctl_engine/planning.py`
  - `python/envctl_engine/engine_runtime.py`
  - `python/envctl_engine/command_router.py`
  - `python/envctl_engine/state.py` (for remembered counts/pointers if needed)

### 7) Port `.envctl.sh` hook behavior safely (or explicitly bridge to shell hooks)
- Current Python config path parses `.envctl.sh` key/value lines but does not execute hook functions.
- To reach Bash parity, implement a constrained hook bridge:
  - `envctl_define_services`
  - `envctl_setup_infrastructure`
- Use a shell subprocess adapter with explicit structured output (JSON contract) instead of sourcing into Python process:
  - avoids arbitrary shell execution in-process while preserving compatibility behavior
- Add policy controls:
  - default allow in migration mode for parity
  - explicit warning/deprecation path if long-term direction changes
- Files/modules:
  - `python/envctl_engine/config.py`
  - new `python/envctl_engine/hooks.py`
  - `python/envctl_engine/engine_runtime.py`
  - `python/envctl_engine/shell_adapter.py` (if reused for hook bridge only)

### 8) Finish lifecycle parity (`resume`, `restart`, `stop`, `stop-all`, `blast-all`) against shell contracts
- `resume`:
  - reconcile state + restart missing services/requirements by policy (non-interactive vs interactive prompt flow)
  - do not report healthy dashboard/runtime map if required components are stale/missing
- `restart`:
  - preserve selected project/service targets and mode
  - perform stop/start with port and runtime-map reconciliation parity
- `stop` / `stop-all`:
  - match shell cleanup intent for service-only vs infra-inclusive cleanup based on flags/config
- `blast-all`:
  - keep recent Python parity improvements (ecosystem sweep, volume policy, legacy purges)
  - close remaining shell gaps (volumes, optional docker ecosystem breadth, prompts/flags parity, output parity)
- Files/modules:
  - `python/envctl_engine/engine_runtime.py`
  - `python/envctl_engine/state.py`
  - `python/envctl_engine/ports.py`
  - (optional) new `python/envctl_engine/cleanup.py` if cleanup code is split out

### 9) Bring interactive dashboard and command loop UX/behavior to Bash-equivalent operation
- Preserve current colorized Python dashboard UI, but close behavioral parity gaps:
  - target selectors/prompts for restart/test/actions
  - post-command refresh behavior and failure summaries
  - command result messaging consistency (`logs`, `health`, `errors`, action commands)
  - displayed fields parity (listener PID sets, exact final URLs, requirement details, attach status)
- Ensure interactive loop never shows “healthy” summary for placeholder/synthetic or stale state.
- Files/modules:
  - `python/envctl_engine/engine_runtime.py`
  - `python/envctl_engine/runtime_map.py`
  - `python/envctl_engine/process_runner.py`
  - action modules (`actions_test.py`, `actions_git.py`, `actions_analysis.py`, `actions_worktree.py`)

### 10) Harden command routing and runtime selection parity truth
- Standardize shell-vs-Python forcing behavior and test it explicitly:
  - document and test `ENVCTL_ENGINE_SHELL_FALLBACK=true` as the supported shell-force mechanism during migration
  - test/verify `ENVCTL_ENGINE_PYTHON_V1` behavior through launcher + engine handoff paths (to avoid user confusion)
- Tie runtime readiness claims to actual implementation status:
  - manifest status cannot be `python_complete` for workflows still using placeholders or shell delegation
  - `--doctor` readiness should explicitly report placeholder/synthetic usage and hook-bridge status
- Files/modules:
  - `lib/envctl.sh`
  - `lib/engine/main.sh`
  - `python/envctl_engine/cli.py`
  - `python/envctl_engine/engine_runtime.py`
  - `docs/planning/python_engine_parity_manifest.json`

### 11) Shipability and repository hygiene gates (branch must reproduce behavior)
- Enforce committed-source completeness for Python runtime + parity tests:
  - no local/untracked-only Python engine behavior required for default runtime correctness
  - CI gate validates required `python/envctl_engine/*`, `tests/python/*`, and parity BATS files are tracked
- Add a release verification script that checks:
  - parity manifest vs runtime readiness consistency
  - unit + BATS test pass status
  - no placeholder/synthetic defaults used in smoke runs unless explicit opt-in
- Files/modules:
  - `scripts/release_shipability_gate.py` (existing gate can be extended)
  - CI config (outside scope of this repo plan if CI definitions live elsewhere; document expected checks)
  - `docs/troubleshooting.md`, `docs/configuration.md`, `docs/architecture.md`

### 12) Controlled rollout to true Python-by-default parity completion
- Phase A:
  - Placeholder removal and real command/requirements adapters land behind internal feature flag if needed
  - Python mode remains default but fails loudly (not simulated) when real startup cannot be resolved
- Phase B:
  - support representative real repos (including supportopia-like FastAPI+Vite layouts with no `.envctl`) via autodetect + hooks parity
  - all runtime truth paths and interactive dashboard reflect live state only
- Phase C:
  - parity BATS suites and multi-worktree `--plan` loops pass consistently under Python runtime
  - shell fallback remains emergency-only
- Phase D:
  - remove any placeholder/synthetic startup code from production path entirely (test fixtures may keep isolated helpers)
  - update docs/manifest to remove migration caveats

## Tests (add these)
### Backend tests
- Extend `tests/python/test_engine_runtime_real_startup.py`
  - assert Python start fails (not simulated success) when no real backend/frontend command can be resolved and synthetic mode is not explicitly enabled
  - assert startup summary includes no synthetic warning once real commands are resolved
  - assert repo autodetect resolves real commands for representative layouts (FastAPI backend + Vite frontend)
- Extend `tests/python/test_runtime_health_truth.py`
  - assert requirement truth is validated (db/redis/n8n) and `health` fails when container/port probe fails
  - assert `simulated` mode is rejected in normal runtime when placeholder opt-in is disabled
- Extend `tests/python/test_requirements_orchestrator.py`
  - classify and retry real readiness failures (`bind_conflict`, `probe_timeout`, bootstrap soft/hard failures)
  - verify success requires readiness probe pass, not command exit alone
- Extend `tests/python/test_service_manager.py`
  - verify PID-owned listener validation rejects wrong-process listener collisions
  - verify rebound/final-port propagation and retry semantics match Bash expectations
- Extend `tests/python/test_state_roundtrip.py`
  - persist/restore new runtime provenance fields (command source, synthetic markers if still present for test mode)
- Extend `tests/python/test_state_shell_compatibility.py`
  - cover additional shell pointer/state variants from `lib/engine/lib/state.sh` used in resume/attach flows
- Extend `tests/python/test_engine_runtime_command_parity.py`
  - verify commands do not report parity-complete when placeholders are active
- Extend `tests/python/test_release_shipability_gate.py`
  - assert placeholder-free smoke mode is enforced in release gate checks
- Add `tests/python/test_command_resolution.py`
  - unit tests for backend/frontend real command autodetect + validation
- Add `tests/python/test_requirements_adapters_real_contracts.py`
  - adapter-level contracts for docker create/start/attach/reuse/health behavior (mocked runner)
- Add `tests/python/test_hooks_bridge.py`
  - `.envctl.sh` hook bridge parsing/execution contract tests (structured JSON output, error handling)

### Frontend tests
- Extend `tests/python/test_frontend_env_projection_real_ports.py`
  - ensure frontend env injection points at actual backend listener after retries/rebounds with real command path
- Extend `tests/python/test_runtime_projection_urls.py`
  - runtime projection must exclude/flag non-ready services; never show healthy URLs for failed/unready services
- Extend `tests/python/test_frontend_projection.py`
  - multi-project/nested-tree actual-port projection parity under real command startup (not synthetic)

### Integration/E2E tests
- Extend `tests/bats/python_engine_parity.bats`
  - assert Python runtime does not silently use placeholder defaults in normal mode
  - assert explicit placeholder/test mode (if retained) is clearly marked and non-default
- Extend `tests/bats/python_runtime_truth_health_e2e.bats`
  - validate dashboard/health/errors degrade when listeners die or infra probes fail
- Extend `tests/bats/python_listener_projection_e2e.bats`
  - verify displayed URLs match real listeners after rebinding in actual command runs
- Extend `tests/bats/python_plan_parallel_ports_e2e.bats`
  - require real requirements/services startup success or explicit failure (no simulated success)
- Extend `tests/bats/python_resume_projection_e2e.bats`
  - verify resume reconciles stale services and does not present healthy dashboard until restarted/attached
- Extend `tests/bats/python_stop_blast_all_parity_e2e.bats`
  - verify `blast-all` clears stray plan orchestrators and exits without unexpected restart/planning UI
- Add `tests/bats/python_placeholder_free_startup_guardrails_e2e.bats`
  - `envctl --plan` on repo without resolvable real commands must fail with actionable error, not start placeholders
- Add `tests/bats/python_real_command_autodetect_supportopia_shape_e2e.bats`
  - fixture-based repo with `backend/pyproject.toml` (FastAPI/Uvicorn) + `frontend/package.json` (`vite`) starts real processes in Python mode
- Add `tests/bats/python_hooks_bridge_parity_e2e.bats`
  - `.envctl.sh` hook-defined services/infra are honored in Python mode

## Observability / logging (if relevant)
- Keep and extend structured lifecycle events in Python runtime:
  - `engine.mode.selected`, `command.route.selected`
  - `planning.projects.discovered`, `planning.selection.resolved`
  - `port.lock.acquire`, `port.lock.reclaim`, `port.lock.release`, `port.reservation.failed`
  - `requirements.start`, `requirements.retry`, `requirements.failure_class`, `requirements.healthy`
  - `service.start`, `service.bind.requested`, `service.bind.actual`, `service.failure`
  - `state.save`, `state.resume`, `state.reconcile`, `runtime_map.write`
  - `cleanup.stop`, `cleanup.stop_all`, `cleanup.blast`
- Add explicit events for placeholder prohibition and command resolution:
  - `command.resolve.backend`, `command.resolve.frontend`, `command.resolve.requirement`
  - `command.resolve.failed`
  - `runtime.placeholder_blocked` (if placeholder mode is disabled)
- Ensure run artifacts remain complete and authoritative under `${RUN_SH_RUNTIME_DIR}/python-engine/runs/<run_id>/`:
  - `run_state.json`
  - `runtime_map.json`
  - `ports_manifest.json`
  - `error_report.json`
  - `events.jsonl`
- Diagnostics (`--doctor`) should report:
  - placeholder/synthetic mode status (enabled/disabled, last run used/not used)
  - hook bridge status (`.envctl.sh` compatibility path)
  - readiness gate status tied to actual runtime truth and parity manifest

## Rollout / verification
- Verification stage 1: placeholder removal guardrails
  - Python runtime no longer silently launches placeholders in default mode
  - unresolved repos fail with actionable command-resolution errors
- Verification stage 2: real command autodetect
  - representative repos (FastAPI backend + Vite frontend; Node backend + Vite frontend) start correctly without custom `.envctl`
  - explicit overrides still take precedence and work
- Verification stage 3: requirements parity
  - Postgres/Redis/Supabase/n8n adapters pass conflict recovery and health probe scenarios
  - no “healthy” infra status on command-exit-only stubs
- Verification stage 4: runtime truth and dashboard parity
  - dashboard/health/errors always match live process/listener/container truth
  - runtime map URLs always match actual listeners after retries/rebounds/resume
- Verification stage 5: lifecycle and interactive parity
  - `resume/restart/stop/stop-all/blast-all` pass parity tests and real repo smoke runs
  - interactive dashboard loop supports Bash-equivalent operational workflows without false-green states
- Verification stage 6: cutover readiness
  - parity manifest and `--doctor` readiness are truthful
  - Python runtime can be default without caveats for standard workflows

## Definition of done
- Python runtime no longer uses placeholder/synthetic startup commands in the default execution path.
- Requirements and services are only reported healthy/running when real readiness checks pass.
- `envctl --plan` in Python mode is functionally comparable to Bash for planning selection, startup, runtime projection, and interactive dashboard flow.
- Runtime map URLs and dashboard rows always reflect actual listeners and final ports.
- Lifecycle commands (`resume`, `restart`, `stop`, `stop-all`, `blast-all`) are parity-tested and operationally reliable.
- `.envctl` / `.envctl.sh` compatibility behavior is explicit, implemented, and test-covered for Python mode.
- Full Python unit suite + Python-mode BATS parity/e2e suites pass.
- `docs/planning/python_engine_parity_manifest.json` and `--doctor` readiness state no longer overstate parity.

## Risk register (trade-offs or missing tests)
- Risk: removing placeholders by default will increase immediate startup failures in repos that currently “appear to work” under Python mode.
  - Mitigation: actionable command-resolution errors, documented shell fallback (`ENVCTL_ENGINE_SHELL_FALLBACK=true`), and fast follow-on autodetect support for common repo shapes.
- Risk: replicating Bash `.envctl.sh` hook behavior can reintroduce shell execution complexity and security concerns.
  - Mitigation: constrained subprocess hook bridge with structured output contract, explicit enablement, and strong test coverage.
- Risk: Docker and host-platform differences (macOS/Linux) may cause probe and attach behavior drift.
  - Mitigation: adapter-level retries/probes, platform-aware timeouts, CI matrix coverage, and e2e conflict-recovery tests.
- Risk: Bash parity breadth is large; partial landing of “real commands” without requirements parity may still confuse users.
  - Mitigation: staged rollout and readiness gating, plus explicit dashboard/doctor warnings until all gates pass.

## Open questions (only if unavoidable)
- None required to start implementation. Assumption for this plan is to preserve Bash-equivalent `.envctl.sh` hook behavior in Python mode via a constrained bridge until a separate deprecation decision is made.
