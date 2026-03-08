# Envctl Python Engine Ideal-State Finalization Plan (100% Cutover)

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Complete the refactor and Python migration so `envctl` is operationally correct, deterministic, and fully shippable without hidden shell-engine dependency for standard workflows.
  - Close every currently verified gap blocking a true 100% cutover: synthetic startup defaults, false health/projection, lifecycle edge-cases, and release/shipability gaps.
  - Preserve the existing CLI contract (`envctl`, key flags, main/trees/plan workflows) while removing failure loops and complexity that caused repeated regressions.
  - Make behavior match user expectations from real usage: parallel trees by default, correct ports/URLs, stable resume/restart, and reliable cleanup.
- Non-goals:
  - Renaming the CLI or changing existing high-value command names.
  - Rewriting downstream repo application code (backend/frontend business logic).
  - Breaking backward compatibility for existing env keys unless explicitly versioned and migrated.
- Assumptions:
  - Python 3.12 is required for Python mode (`lib/engine/main.sh:94`, `lib/engine/main.sh:98`).
  - Docker-backed requirements (postgres/redis/supabase/n8n) remain part of runtime expectations.
  - Configuration precedence remains: process env -> `.envctl` / `.envctl.sh` / `.supportopia-config` -> defaults (`python/envctl_engine/config.py:60`, `python/envctl_engine/config.py:105`).
  - Planning-doc style baseline is existing `docs/planning/refactoring/*.md`; `docs/planning/README.md` is currently missing.

## Goal (user experience)
A user can run `envctl`, `envctl --tree`, and `envctl --plan` repeatedly across multiple worktrees and always get a stable outcome:
- every project receives unique, conflict-free app + infra ports,
- displayed URLs always match actual listeners,
- requirements + services are genuinely running (not synthetic success),
- `resume`, `restart`, `stop`, `stop-all`, and `blast-all` behave predictably,
- action commands (`test`, `pr`, `commit`, `analyze`, `migrate`, `delete-worktree`) are parity-complete and target-correct,
- and the shipped branch itself is sufficient to reproduce this behavior on a fresh clone.

## Business logic and data model mapping
- Launcher and engine handoff:
  - `bin/envctl` -> `lib/envctl.sh:envctl_main` -> `lib/envctl.sh:envctl_forward_to_engine` (`lib/envctl.sh:159`) -> `lib/engine/main.sh`.
  - Python mode is default-enabled when shell fallback is not forced (`lib/envctl.sh:173`, `lib/engine/main.sh:119`).
  - Python engine exec path is in `lib/engine/main.sh:98` (`exec_python_engine_if_enabled`).
- Python command lifecycle:
  - Parse: `python/envctl_engine/command_router.py:109` (`parse_route`).
  - Entry: `python/envctl_engine/cli.py:25` (`run`).
  - Runtime dispatch: `python/envctl_engine/engine_runtime.py:69` (`dispatch`).
- Core runtime models:
  - Port model: `PortPlan` (`python/envctl_engine/models.py`).
  - Service model: `ServiceRecord` (`python/envctl_engine/models.py`).
  - Requirements model: `RequirementsResult` (`python/envctl_engine/models.py`).
  - Session model: `RunState` (`python/envctl_engine/models.py`).
- State and projection:
  - State load/save + legacy shell compatibility: `python/envctl_engine/state.py`.
  - Runtime map + projected URLs: `python/envctl_engine/runtime_map.py`.
  - Artifact write path: `python/envctl_engine/engine_runtime.py:488`.
- Port reservation/locking:
  - Planner + locks + availability strategy: `python/envctl_engine/ports.py:17`.
  - Reservation call path from runtime: `python/envctl_engine/engine_runtime.py:255`.
- Requirements + service orchestration:
  - Requirements retry/failure class: `python/envctl_engine/requirements_orchestrator.py:43`.
  - Service retry + attach: `python/envctl_engine/service_manager.py:16`.
  - Runtime start of requirements/services: `python/envctl_engine/engine_runtime.py:267`, `python/envctl_engine/engine_runtime.py:396`.
- Shell parity baseline modules (source of mature behavior to mirror):
  - CLI and command flow: `lib/engine/lib/run_all_trees_cli.sh:174`, `lib/engine/lib/run_all_trees_helpers.sh:307`.
  - Requirements: `lib/engine/lib/requirements_core.sh:697`, `lib/engine/lib/requirements_core.sh:1463`.
  - Supabase/n8n: `lib/engine/lib/requirements_supabase.sh:1766`, `lib/engine/lib/requirements_supabase.sh:2108`.
  - Service lifecycle: `lib/engine/lib/services_lifecycle.sh:1211`, `lib/engine/lib/services_lifecycle.sh:1746`.
  - Resume/state/recovery: `lib/engine/lib/state.sh:1707`, `lib/engine/lib/state.sh:1799`, `lib/engine/lib/state.sh:2164`.

## Current behavior (verified in code)
- Python engine is selected by default from launcher/engine:
  - `lib/envctl.sh:173-179`, `lib/engine/main.sh:119-125`.
- Runtime claims parity completeness in doctor and manifest:
  - `PARTIAL_COMMANDS` is empty (`python/envctl_engine/engine_runtime.py:38`).
  - `--doctor` prints `parity_status` from `PARTIAL_COMMANDS` only (`python/envctl_engine/engine_runtime.py:612`).
  - `docs/planning/python_engine_parity_manifest.json:27` marks all commands as `python_complete`.
- Requirements can report success without running real infra by default:
  - Default requirement command is inline Python stub returning success (`python/envctl_engine/engine_runtime.py:1168`).
  - Requirement component success depends on command return code (`python/envctl_engine/engine_runtime.py:366`), not validated container/service state.
- Service startup can report running without real listener validation:
  - Default service command is `time.sleep(1.0)` (`python/envctl_engine/engine_runtime.py:1179`).
  - Actual-port detection falls back to requested port when listener check fails (`python/envctl_engine/engine_runtime.py:445`, `python/envctl_engine/engine_runtime.py:447`, `python/envctl_engine/engine_runtime.py:460`, `python/envctl_engine/engine_runtime.py:463`).
- `health`/`errors` operate from persisted state, not live process/listener truth:
  - `health` uses stored `status` + stored port (`python/envctl_engine/engine_runtime.py:658`).
  - `errors` checks status labels only (`python/envctl_engine/engine_runtime.py:664`).
- Resume detects stale PIDs but does not automatically reconcile services to healthy running state:
  - stale detection only sets `service.status = "stale"` (`python/envctl_engine/engine_runtime.py:213-216`).
  - runtime map is rewritten and printed (`python/envctl_engine/engine_runtime.py:222-231`).
- Planning discovery supports nested + flat, but plan filtering falls back to all projects when selectors miss:
  - discovery: `python/envctl_engine/planning.py:23`.
  - selector fallback behavior: `python/envctl_engine/planning.py:63`.
- Prerequisite gate is only enforced for `start|plan|restart`:
  - `python/envctl_engine/cli.py:49`.
- Shell parity baseline remains richer in lifecycle/infra behaviors:
  - advanced requirements/retry/attach logic in `lib/engine/lib/requirements_core.sh` and `lib/engine/lib/requirements_supabase.sh`.
  - mature service attach/retry + real bind behavior in `lib/engine/lib/services_lifecycle.sh`.
  - full resume/recovery ergonomics in `lib/engine/lib/state.sh`.
- Release/shipability gap exists in current workspace:
  - implementation and tests are present locally but large parts are still untracked in git (`python/envctl_engine/*`, `tests/python/*`, and multiple `tests/bats/python_*` files), so branch reproducibility is not yet guaranteed from committed history.

## Root cause(s) / gaps
- Cutover gate mismatch:
  - Python mode is default-on, but runtime truth gates rely on self-reported parity metadata rather than hard end-to-end proof.
- Synthetic default execution:
  - requirements and services can "succeed" without real infra/service contracts.
- Health/projection reliability gap:
  - state can say `running` while processes are gone or never bound requested ports.
- Runtime map trust gap:
  - projected URLs can be derived from requested/fallback values instead of observed listeners.
- Requirements parity gap:
  - Python requirements orchestration is generic compared to shell's detailed container and recovery semantics.
- Lifecycle parity gap:
  - Python `stop/stop-all/blast-all/resume` logic is narrower than shell behavioral surface and operational cleanup patterns.
- Command parity truth gap:
  - manifest says `python_complete` while some behaviors are functionally incomplete for real-world workflows.
- Shipability gap:
  - branch completeness depends on local untracked files, not committed source of truth.
- Documentation contract gap:
  - planning baseline doc (`docs/planning/README.md`) missing; migration readiness communication remains fragmented across multiple plan docs.

## Plan
### 1) Establish hard cutover contract and release gate policy
- Introduce explicit readiness gate constants in Python runtime:
  - block "parity complete" status unless command families, runtime truth checks, and E2E gates pass.
  - make `--doctor` report machine-validated readiness classes (for example: `command_parity`, `runtime_truth`, `lifecycle`, `shipability`).
- Replace parity-manifest-only confidence with code + test-backed validation:
  - add CI assertion that manifest statuses match runtime behavior and test outcomes.
- Add a release checklist script at repo root that verifies:
  - no required implementation files are untracked,
  - Python/BATS suites pass,
  - parity manifest + doctor status are synchronized.

### 2) Make committed source authoritative (shipability first)
- Commit the full Python engine package and all parity tests required for default behavior:
  - `python/envctl_engine/*`
  - `tests/python/*`
  - `tests/bats/python_*` and `tests/bats/parallel_trees_python_e2e.bats`.
- Add CI lint gate for repository completeness:
  - fail when parity-required paths are missing from tracked files.
- Ensure install path user experience is explicit:
  - docs and `envctl install` output should clearly state shell reload/new shell requirement.

### 3) Replace synthetic default commands with real command resolution
- Replace `_default_requirement_command` and `_default_service_command` in `python/envctl_engine/engine_runtime.py` with real adapters:
  - requirements adapter: docker orchestration commands (postgres/redis/supabase/n8n) equivalent to shell baseline.
  - service adapter: backend/frontend startup command resolution from repo context and explicit env overrides.
- Introduce a command-resolution module that:
  - validates executable, cwd, and required files before start,
  - classifies failure reason (`missing_executable`, `invalid_cwd`, `bootstrap_failure`, `bind_conflict`).
- Keep explicit override env hooks but remove no-op success defaults.

### 4) Implement requirements parity by service type
- Break requirements into typed adapters under `python/envctl_engine/requirements/`:
  - postgres adapter with create/start/reuse/wait semantics.
  - redis adapter with container ownership + port mapping validation.
  - supabase adapter with db + auth/gateway sequencing and health probe.
  - n8n adapter with bootstrap/reset policy and strict/soft mode controlled by `ENVCTL_STRICT_N8N_BOOTSTRAP`.
- Mirror shell conflict/retry semantics:
  - reserve next ports under bind collisions,
  - keep retry bounds explicit and logged,
  - propagate final assigned ports to manifests and runtime map.
- Treat requirement success as proven readiness, not command exit alone.

### 5) Enforce live process/listener truth for service state and projection
- Refactor backend/frontend startup path:
  - start process -> detect live listener by pid + listener ownership -> only then mark `running`.
  - if listener is absent, classify as failed and retry/port-rebound based on policy.
- Replace fallback-to-requested-port projection with observed listener ports.
- On resume/health/errors:
  - revalidate PID existence and listener availability for each service,
  - downgrade stale/unreachable services immediately,
  - never print healthy URLs for unreachable listeners.

### 6) Harden port planner behavior across environments
- Keep availability strategies in `PortPlanner` but make selection explicit and test-verified:
  - `socket_bind`, `listener_query`, `lock_only`.
- Add deterministic fallback policy for restricted environments:
  - avoid full-range scan loops with no diagnostics,
  - emit structured reservation failure report with attempted range, mode, lock inventory.
- Strengthen stale lock reclaim:
  - strict owner/session semantics,
  - bounded stale threshold and reasoned reclaim events.

### 7) Close planning/worktree behavior parity
- Keep nested + flat discovery support from `python/envctl_engine/planning.py`, but tighten selector contract:
  - configurable option to fail when plan selectors match nothing (instead of implicit fallback to all).
  - preserve deterministic ordering and naming.
- Match shell plan behavior for reuse/new creation semantics and ports across multiple selected plans.
- Ensure plan-mode output reports:
  - requested + final ports,
  - reused vs newly created worktrees,
  - clear reason when a target is skipped.

### 8) Complete lifecycle parity (`stop`, `stop-all`, `blast-all`, `resume`, `restart`)
- Expand cleanup command semantics:
  - `stop`: stop current run services and preserve requested infra per policy.
  - `stop-all`: stop all tracked runs + release locks across runtime scope.
  - `blast-all`: aggressive cleanup including stale runtime artifacts, lock/state pointers, and optional docker ecosystem cleanup.
- Resume/restart:
  - add policy-driven auto-restart of missing services (or explicit prompt in interactive modes),
  - prevent stale state from being projected as active run.
- Ensure cleanup is idempotent and safe under partial failure.

### 9) Align action-command parity with shell expectations
- Keep existing Python action modules (`actions_test`, `actions_git`, `actions_analysis`, `actions_worktree`) and harden them for operational parity:
  - target resolution in both main/trees contexts,
  - predictable behavior for `--all`, `--project`, and service selectors,
  - consistent exit-code policy and messages.
- Add strict guardrails:
  - no command should silently degrade into startup flow,
  - no "success" return when no valid targets were run.

### 10) Finalize state compatibility and recovery contracts
- Continue JSON as canonical state format and legacy pointer compatibility (`python/envctl_engine/state.py`), but:
  - exhaustively test shell pointer variants from `lib/engine/lib/state.sh`,
  - keep backward compatibility window explicit and versioned.
- Remove legacy `utils/run.sh` references from any recovery outputs in active engine path and use `envctl`-first commands.

### 11) Observability, diagnostics, and operator UX hardening
- Standardize event taxonomy and include correlation IDs:
  - route selection, reservation acquire/reclaim/release, requirement retries, service start/bind, state reconcile, cleanup.
- Ensure every run writes complete artifact bundle under `python-engine/runs/<run_id>/`:
  - run state, runtime map, ports manifest, error report, events stream.
- Improve `--doctor`:
  - show readiness gates, parity manifest hash/date, recent failure classes, lock health summary, and runtime pointer status.

### 12) Controlled rollout to 100% completion
- Phase A: functional parity closure behind default Python mode with shell fallback retained.
- Phase B: enable strict runtime truth checks and make failing truth gates block "complete" status.
- Phase C: run full matrix in CI and in real local workflows (`--plan`, multi-tree parallel, resume/restart, stop/blast).
- Phase D: declare 100% cutover only after all done criteria pass for consecutive release windows.

## Tests (add these)
### Backend tests
- Extend `tests/python/test_engine_runtime_real_startup.py`:
  - assert requirements/services are not marked successful without live readiness.
  - assert startup fails when default commands cannot produce real listeners.
- Extend `tests/python/test_service_manager.py`:
  - validate retry/rebound behavior with listener validation and final-port propagation.
- Extend `tests/python/test_requirements_orchestrator.py`:
  - verify typed failure classes and retry ceilings across postgres/redis/supabase/n8n scenarios.
- Extend `tests/python/test_ports_lock_reclamation.py`:
  - validate stale-lock reclaim and session-scoped release invariants.
- Extend `tests/python/test_ports_availability_strategies.py`:
  - lock-only, listener-query, and socket-bind modes under deterministic fixtures.
- Add `tests/python/test_runtime_health_truth.py`:
  - `health/errors` must reflect live process/listener state, not stale metadata only.
- Add `tests/python/test_release_shipability_gate.py`:
  - parity-required file set must be tracked and present.

### Frontend tests
- Extend `tests/python/test_runtime_projection_urls.py`:
  - runtime projection must match actual bound frontend/backend listeners after retry/rebound.
- Extend `tests/python/test_frontend_env_projection_real_ports.py`:
  - ensure projected frontend URLs and env-injected backend URLs align with final ports.

### Integration/E2E tests
- Keep and harden all current Python parity suites:
  - `tests/bats/python_engine_parity.bats`
  - `tests/bats/parallel_trees_python_e2e.bats`
  - `tests/bats/python_plan_parallel_ports_e2e.bats`
  - `tests/bats/python_plan_nested_worktree_e2e.bats`
  - `tests/bats/python_requirements_conflict_recovery.bats`
  - `tests/bats/python_listener_projection_e2e.bats`
  - `tests/bats/python_resume_projection_e2e.bats`
  - `tests/bats/python_state_resume_shell_compat_e2e.bats`
  - `tests/bats/python_stop_blast_all_parity_e2e.bats`
  - `tests/bats/python_actions_parity_e2e.bats`
  - `tests/bats/python_command_alias_parity_e2e.bats`
  - `tests/bats/python_command_partial_guardrails_e2e.bats`
- Add `tests/bats/python_runtime_truth_health_e2e.bats`:
  - prove `--health` fails/degrades correctly when processes die or listeners are absent.
- Add `tests/bats/python_shipability_commit_guard_e2e.bats`:
  - ensure release gate fails when required implementation files are untracked.

## Observability / logging (if relevant)
- Required event classes:
  - `engine.mode.selected`, `command.route.selected`
  - `planning.projects.discovered`
  - `port.lock.acquire`, `port.lock.reclaim`, `port.lock.release`, `port.reservation.failed`
  - `requirements.start`, `requirements.retry`, `requirements.failure_class`, `requirements.healthy`
  - `service.start`, `service.bind.requested`, `service.bind.actual`, `service.failure`
  - `state.resume`, `state.reconcile`, `runtime_map.write`
  - `cleanup.stop`, `cleanup.stop_all`, `cleanup.blast`
- Each run must persist:
  - `run_state.json`
  - `runtime_map.json`
  - `ports_manifest.json`
  - `error_report.json`
  - `events.jsonl`
- Operator-facing diagnostics:
  - `doctor` outputs gate readiness, parity status source, stale pointer summary, and last failure classes.

## Rollout / verification
- Gate 1: Shipability
  - full Python engine + parity tests tracked in git,
  - clean branch reproduces runtime behavior on fresh clone.
- Gate 2: Runtime truth
  - no false `running`/healthy projection when listeners are absent.
- Gate 3: Requirements/services parity
  - deterministic startup/retry across multi-tree and conflict cases.
- Gate 4: Lifecycle parity
  - `resume/restart/stop/stop-all/blast-all` pass all contract tests and are idempotent.
- Gate 5: Command parity
  - action commands stable across modes/selectors with correct target resolution.
- Gate 6: Operational burn-in
  - repeated local and CI runs across representative repos without regression loops.

## Definition of done
- Python engine behavior is reproducible from committed branch contents alone.
- Requirements and services are only marked healthy when real readiness checks pass.
- Runtime map/projection URLs always match actual listeners.
- `--plan` and trees parallel startup produce unique ports and deterministic outcomes without collision loops.
- Lifecycle commands (`resume/restart/stop/stop-all/blast-all`) are parity-complete and idempotent.
- Action commands (`test/pr/commit/analyze/migrate/delete-worktree`) are parity-complete and target-correct.
- Full Python unit + BATS parity/E2E suite passes in CI and local validation.
- Parity manifest and `doctor` readiness are truthful and test-enforced.

## Risk register (trade-offs or missing tests)
- Risk: stricter readiness checks may initially increase startup failures in misconfigured repos.
  - Mitigation: provide explicit diagnostics with required fixes and fallback instructions.
- Risk: Docker/network behavior differences across macOS/Linux can skew infra readiness.
  - Mitigation: cross-platform CI matrix and adapter-level retries with bounded backoff.
- Risk: release gate for tracked files may block fast local experimentation.
  - Mitigation: keep gate in release/CI path, not in normal local `envctl` runtime.
- Risk: legacy `.envctl.sh` behavior can reintroduce unsafe shell execution complexity.
  - Mitigation: define constrained support contract or explicit deprecation/migration path.

## Open questions (only if unavoidable)
- Should `.envctl.sh` remain executable hook surface in Python mode, or should the project formally standardize on declarative `.envctl` plus explicit Python plugin hooks?
