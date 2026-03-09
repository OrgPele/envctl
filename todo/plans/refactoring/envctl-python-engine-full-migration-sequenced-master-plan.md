# Envctl Python Engine Full Migration Sequenced Master Plan

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Complete migration of orchestration authority from shell modules to Python runtime for all primary workflows (`start`, `--plan`, `--tree`, `resume`, `restart`, `stop`, `stop-all`, `blast-all`, dashboard loop, logs/health/errors/actions).
  - Remove ambiguity between "Python complete" claims and measured behavior by enforcing behavior-based readiness gates and a shell-deletion ledger policy.
  - Eliminate synthetic/placeholder reliance in normal operation and ensure runtime truth/projection is derived from verified live state.
  - Deliver safe lifecycle behavior (idempotent stop/restart/resume, ownership-safe termination, cross-repo isolation).
  - Provide deterministic planning/worktree behavior matching shell-era UX, including selection, counts, reuse/create/delete semantics, and port assignment.
- Non-goals:
  - Rewriting downstream product application business logic launched by `envctl`.
  - Removing launcher compatibility wrappers (`/Users/kfiramar/projects/envctl/lib/envctl.sh`, `/Users/kfiramar/projects/envctl/lib/engine/main.sh`) in the first cutover wave.
  - Renaming top-level command families or introducing breaking CLI naming changes.
- Assumptions:
  - Python 3.12 remains required for Python engine path (`/Users/kfiramar/projects/envctl/lib/engine/main.sh`).
  - Docker remains a mandatory dependency for infra orchestration parity.
  - Config precedence remains env -> repo config files (`.envctl`, `.envctl.sh`, `.supportopia-config`) -> defaults (`/Users/kfiramar/projects/envctl/python/envctl_engine/config.py`).
  - Migration must be validated from tracked repository state (release gate should fail if implementation-critical scopes are untracked).

## Goal (user experience)
A developer should be able to run `envctl --plan` on a clean repo and get deterministic, boring behavior every time: correct worktree selection/create/reuse, unique app+infra ports per project, truthful URLs/statuses, actionable failures, stable resume/restart, safe stop/blast semantics, and no hidden shell fallback/placeholder behavior unless explicitly opted into compatibility mode.

## Business logic and data model mapping
- Launcher and engine handoff:
  - `/Users/kfiramar/projects/envctl/bin/envctl`
  - `/Users/kfiramar/projects/envctl/lib/envctl.sh:envctl_main`
  - `/Users/kfiramar/projects/envctl/lib/envctl.sh:envctl_forward_to_engine`
  - `/Users/kfiramar/projects/envctl/lib/engine/main.sh`
- Python runtime command dispatch:
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/cli.py:run`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/command_router.py:parse_route`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/engine_runtime.py:PythonEngineRuntime.dispatch`
- Canonical runtime models/state/projection:
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/models.py`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/state.py`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/runtime_map.py`
- Port/lock lifecycle:
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/ports.py`
- Service/requirements orchestration:
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/service_manager.py`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/requirements_orchestrator.py`
  - `/Users/kfiramar/projects/envctl/python/envctl_engine/requirements/*.py`
- Shell parity baseline (behavioral reference for migration):
  - `/Users/kfiramar/projects/envctl/lib/engine/lib/run_all_trees_cli.sh`
  - `/Users/kfiramar/projects/envctl/lib/engine/lib/run_all_trees_helpers.sh`
  - `/Users/kfiramar/projects/envctl/lib/engine/lib/services_lifecycle.sh`
  - `/Users/kfiramar/projects/envctl/lib/engine/lib/requirements_core.sh`
  - `/Users/kfiramar/projects/envctl/lib/engine/lib/requirements_supabase.sh`
  - `/Users/kfiramar/projects/envctl/lib/engine/lib/state.sh`
  - `/Users/kfiramar/projects/envctl/lib/engine/lib/runtime_map.sh`

## Current behavior (verified in code)
- Shell migration ledger still contains large unmigrated surface:
  - `scripts/report_unmigrated_shell.py --repo .` shows `unmigrated_count: 320`.
  - `scripts/verify_shell_prune_contract.py --repo .` still passes because contract currently validates structure, not closure threshold.
- Shell fallback remains active and supported:
  - `ENVCTL_ENGINE_SHELL_FALLBACK` is still wired in launcher/config/CLI (`lib/envctl.sh`, `lib/engine/main.sh`, `python/envctl_engine/config.py`, `python/envctl_engine/cli.py`, `python/envctl_engine/shell_adapter.py`).
- Synthetic startup paths still exist (opt-in):
  - `python/envctl_engine/command_resolution.py` returns `synthetic_default` when `ENVCTL_ALLOW_SYNTHETIC_DEFAULTS=true`.
  - `python/envctl_engine/engine_runtime.py` still has default synthetic command helpers.
- Requirements adapters are not full parity implementations:
  - `python/envctl_engine/requirements/postgres.py`, `redis.py`, `supabase.py`, `n8n.py` are thin wrappers around generic retry helper, not Docker/container-health adapters.
- Supabase auth reliability regression class is not codified in envctl:
  - cross-implementation network collisions can occur when app compose uses static shared network names.
  - GoTrue auth schema/search_path expectations are not validated by envctl preflight checks.
  - Supabase config changes that require volume recreation (for example auth bootstrap/schema updates) are not fingerprinted or enforced by runtime policy.
- Parser parity remains incomplete relative to shell:
  - measured shell flags: 105, Python parser flags: 79, missing: 33.
  - example unsupported shell/documented option still exists (`--planning-prs` rejected).
- Parsed flags do not always imply behavioral parity:
  - multiple newly accepted flags are stored in `Route.flags` but not consumed in runtime execution paths.
- Resume/projection behavior still incomplete:
  - `_resume` reconciles and warns but does not restore missing services.
  - runtime projection currently emits URLs from stored ports without status gating.
- Runtime scope isolation incomplete:
  - runtime root, planning memory, and lock root are still global at `${RUN_SH_RUNTIME_DIR}/python-engine` (not repo-hashed namespaces).
- Hook parity missing:
  - shell hook functions (`envctl_define_services`, `envctl_setup_infrastructure`) are not executed by Python runtime; Python config loader only parses key-value lines.
- Doctor/release signaling can overstate readiness:
  - `PARTIAL_COMMANDS` is empty and manifest marks all `python_complete`, but doctor can still be gated on runtime/lifecycle/shipability failures and ledger shows 320 unmigrated entries.

## Root cause(s) / gaps
- Governance gap: parity manifest and doctor/readiness gates are not fully tied to measured behavioral parity and shell-ledger closure.
- Ownership gap: Python routing exists, but several orchestration responsibilities are still shell-owned or partially migrated.
- Truth-model gap: health/errors/dashboard/runtime_map do not all consistently derive from one strict liveness model.
- Scope gap: runtime state/locks/planning memory are not repo-isolated by construction.
- Supabase reliability gap: envctl does not currently enforce app-level Supabase invariants required to avoid `/auth/v1/signup` 500 (network isolation, auth schema namespace/search path, bootstrap SQL mount, and volume reset policy).
- Compatibility gap: `.envctl.sh` function-hook behavior has no Python bridge.
- Test coverage gap: many paths still rely on synthetic mode in fixture tests and do not enforce real startup parity by default.
- Prune gap: shell deletion process does not enforce unmigrated budget by phase.

## Plan
### 1) Migration contract and gate hardening (foundation)
- Objective:
  - Replace “status by declaration” with “status by measured evidence.”
- Implementation:
  - Add `docs/planning/README.md` with authoritative migration gate schema.
  - Update `/Users/kfiramar/projects/envctl/python/envctl_engine/release_gate.py`:
    - require parser parity threshold check.
    - require shell-ledger unmigrated threshold by phase.
    - require no synthetic mode in default smoke runs.
  - Update `/Users/kfiramar/projects/envctl/python/envctl_engine/engine_runtime.py:_doctor_readiness_gates` to use behavioral checks and `check_tests` policy for release contexts.
  - Extend `/Users/kfiramar/projects/envctl/python/envctl_engine/shell_prune.py`:
    - enforce phase budgets (`unmigrated <= target`).
- Tests:
  - extend `tests/python/test_release_shipability_gate.py` and `tests/python/test_shell_prune_contract.py`.
  - add BATS gate test for doctor parity and unmigrated budget reporting.
- Exit criteria:
  - gate fails when manifest claims complete but parser/ledger/runtime evidence disagrees.

### 2) Repo-scoped runtime state + lock namespaces (safety prerequisite)
- Objective:
  - eliminate cross-repo contamination and unsafe global cleanup behavior.
- Implementation:
  - Introduce repo hash namespace path: `${RUN_SH_RUNTIME_DIR}/python-engine/<repo_hash>/...`.
  - Scope:
    - `run_state.json`, `runtime_map.json`, `ports_manifest.json`, `error_report.json`, events, pointers, planning selection memory, lock dir.
  - Migrate existing global-state discovery to compatibility loader with one-time rewrite into scoped path.
  - Replace broad `release_all()` calls with scoped/session release in normal stop paths.
- Files:
  - `python/envctl_engine/engine_runtime.py`, `ports.py`, `state.py`, optionally `config.py` helper for scope id.
- Tests:
  - add `tests/python/test_runtime_scope_isolation.py`.
  - add BATS `python_cross_repo_isolation_e2e.bats`.
- Exit criteria:
  - running two repos under same runtime root never cross-sees state/locks.

### 3) Requirements adapter ownership (real infra orchestration)
- Objective:
  - replace generic start-command checks with component-specific orchestration and readiness.
- Implementation:
  - Implement real adapters:
    - `requirements/postgres.py`: container create/start/attach, probe and mapped-port verification.
    - `requirements/redis.py`: container mapping validation + readiness (`PING`) semantics.
    - `requirements/supabase.py`: db/auth/gateway sequencing and health checks.
    - `requirements/n8n.py`: startup/restart/bootstrap policy with strict vs soft bootstrap mode.
  - Add a Supabase reliability contract (app-side invariants + envctl enforcement):
    - verify compose network isolation: no static shared network name in tree implementations; project-scoped network names only.
    - verify GoTrue auth DB targeting:
      - `GOTRUE_DB_DATABASE_URL` includes `?search_path=auth,public`,
      - `GOTRUE_DB_NAMESPACE=auth`,
      - `DB_NAMESPACE=auth`.
    - verify bootstrap SQL presence/mount for auth schema initialization:
      - `CREATE SCHEMA IF NOT EXISTS auth`,
      - role/database search_path set to `auth, public`.
    - verify repo-root-safe mount paths for critical artifacts (`kong.yml`, `01-create-n8n-db.sql`, and auth bootstrap SQL).
  - Add Supabase config fingerprinting and reinit policy in envctl:
    - persist a hash of Supabase compose + mounted SQL contracts per project.
    - when fingerprint changes, require explicit reinit (or auto-reinit when policy allows):
      - `docker compose ... down -v`
      - `docker compose ... up -d supabase-db`
      - wait for DB healthy
      - `docker compose ... up -d supabase-auth supabase-kong`
    - fail startup with actionable diagnostics if reinit is required but not executed.
  - Add post-start auth reliability checks:
    - verify GoTrue dependency readiness and auth schema availability before reporting healthy.
    - add signup regression probe policy (expected non-500 behavior for `/auth/v1/signup` under configured local mode).
  - Wire adapters into `engine_runtime._start_requirement_component` default path.
  - Keep `ENVCTL_REQUIREMENT_*_CMD` as explicit override, not primary default.
- Tests:
  - add `tests/python/test_requirements_adapters_real_contracts.py`.
  - extend `tests/python/test_requirements_orchestrator.py`.
  - add `tests/python/test_supabase_requirements_reliability.py` for contract validation and fingerprint reset behavior.
  - extend BATS requirements conflict recovery and supabase/n8n parity tests.
  - add BATS:
    - `tests/bats/python_supabase_network_isolation_e2e.bats`
    - `tests/bats/python_supabase_config_fingerprint_reset_e2e.bats`
    - `tests/bats/python_supabase_auth_signup_500_regression_e2e.bats`
- Exit criteria:
  - default startup in representative repo works without synthetic requirement mode.
  - `/auth/v1/signup` no longer returns 500 for known regression scenarios once contract is satisfied.

### 4) Service startup provenance and listener ownership hardening
- Objective:
  - ensure service “running/healthy” means intended process owns expected listener.
- Implementation:
  - Persist command provenance in `ServiceRecord` metadata: source (`configured`/`autodetected`/`hook`), resolved command fingerprint.
  - Enforce PID+port ownership checks on startup and reconcile paths.
  - Strengthen wrong-process collision classification and retry behavior.
- Files:
  - `engine_runtime.py`, `service_manager.py`, `process_runner.py`, `models.py`, `state.py`.
- Tests:
  - extend `tests/python/test_service_manager.py`, `tests/python/test_runtime_health_truth.py`, `tests/python/test_engine_runtime_real_startup.py`.
- Exit criteria:
  - no false positive service success when unrelated process owns port.

### 5) Planning/worktree lifecycle parity ownership
- Objective:
  - Python owns planning workflow end-to-end, not only selection filtering.
- Implementation:
  - Add deterministic planning execution pipeline:
    - discover plans from `ENVCTL_PLANNING_DIR`.
    - resolve selections and counts.
    - create/reuse/delete worktrees via native logic or controlled bridge to `utils/setup-worktrees.sh`.
    - optional move-to-done behavior with `keep-plan` semantics.
  - Add duplicate normalized project identity detection with fail-fast diagnostics.
  - Replace selector miss fallback-to-all with explicit strict behavior by policy.
- Files:
  - `planning.py`, `engine_runtime.py`, optionally `actions_worktree.py`.
- Tests:
  - extend `tests/python/test_planning_selection.py`, `tests/python/test_discovery_topology.py`.
  - add BATS `python_planning_worktree_setup_e2e.bats`, `python_plan_selector_strictness_e2e.bats`.
- Exit criteria:
  - `--plan` behaves deterministically for nested/flat trees and planning counts.

### 6) Lifecycle parity completion (`resume`/`restart`/`stop`/`stop-all`/`blast-all`)
- Objective:
  - lifecycle commands are idempotent, selector-aware, and ownership-safe.
- Implementation:
  - `resume`:
    - restart missing required services by policy (batch vs interactive prompt behavior).
  - `restart`:
    - explicit stop with ownership checks, then start preserving intended ports where valid.
  - `stop`:
    - keep targeted selectors and preserve remaining state correctly.
  - `blast-all`:
    - default to repo-scoped process cleanup.
    - host-wide cleanup only under explicit opt-in/force policy.
    - avoid broad generic pkill patterns by default.
- Files:
  - `engine_runtime.py`, `process_runner.py`, `ports.py`, maybe `cleanup.py` extraction.
- Tests:
  - extend `tests/python/test_lifecycle_parity.py`.
  - extend/add BATS `python_stop_blast_all_parity_e2e.bats`, `python_stop_signal_escalation_e2e.bats`, `python_restart_pid_replacement_e2e.bats`.
- Exit criteria:
  - repeated lifecycle commands produce stable results and no orphaned runtime artifacts.

### 7) Runtime truth + projection unification
- Objective:
  - ensure dashboard/health/errors/runtime_map present one consistent truth model.
- Implementation:
  - run one canonical reconcile pass before projection generation.
  - status-gate projected URLs (no healthy URLs for stale/unreachable services).
  - include requirement liveness in health/errors summary.
- Files:
  - `engine_runtime.py`, `runtime_map.py`.
- Tests:
  - extend `tests/python/test_runtime_projection_urls.py`, `tests/python/test_frontend_env_projection_real_ports.py`, `tests/python/test_runtime_health_truth.py`.
- Exit criteria:
  - projections always match live verified listeners and status state.

### 8) Logs/dashboard interactive UX parity
- Objective:
  - restore reliable, colorful, operator-grade interaction parity.
- Implementation:
  - complete logs parity behavior (tail/follow/duration/no-color, filters by project/service).
  - interactive dashboard selection workflows for restart/logs/test/actions.
  - richer runtime row details: requested vs actual ports, listener pid ownership, requirement detail.
- Files:
  - `engine_runtime.py`, optional UI helper extraction.
- Tests:
  - `tests/python/test_logs_parity.py` (already started), add `test_dashboard_rendering_parity.py`.
  - BATS `python_logs_follow_parity_e2e.bats`, `python_dashboard_interactive_e2e.bats`.
- Exit criteria:
  - interactive operations are fully usable without shell fallback.

### 9) `.envctl.sh` function-hook compatibility bridge
- Objective:
  - preserve legacy hooks during migration while keeping Python runtime safe and deterministic.
- Implementation:
  - implement constrained shell hook bridge for `envctl_define_services` and `envctl_setup_infrastructure` with structured JSON output.
  - enforce explicit toggle and robust error diagnostics.
- Files:
  - new `python/envctl_engine/hooks.py`, `engine_runtime.py`, `shell_adapter.py`, small loader changes in `config.py`.
- Tests:
  - add `tests/python/test_hooks_bridge.py`.
  - add BATS `python_hook_bridge_e2e.bats`.
- Exit criteria:
  - hook-based repos run in Python mode without implicit shell engine routing.

### 10) Command surface closure and docs parity enforcement
- Objective:
  - close remaining high-value parser gaps and prevent future docs/parser drift.
- Implementation:
  - finish missing supported flags and map semantics or explicit unsupported diagnostics.
  - add automated parser-vs-shell-vs-docs parity check script and CI gate.
- Files:
  - `command_router.py`, `scripts/release_shipability_gate.py`, docs in `docs/important-flags.md`.
- Tests:
  - extend `tests/python/test_cli_router_parity.py`.
  - add BATS parser parity coverage for documented flags.
- Exit criteria:
  - documented flag surface is either implemented or explicitly marked deprecated with actionable guidance.

### 11) Shell prune execution waves (deletion-driven migration)
- Objective:
  - remove migrated shell code in controlled waves tied to parity tests.
- Wave A:
  - delete shell status/log rendering duplicates after Python dashboard/logs parity proven.
- Wave B:
  - delete shell startup/retry/requirements implementations after adapter parity passes.
- Wave C:
  - reduce shell runtime to minimal launcher compatibility shim.
- Wave D:
  - retire shell fallback routing (`ENVCTL_ENGINE_SHELL_FALLBACK`) after stability window and policy signoff.
- Enforcement:
  - update `docs/planning/refactoring/envctl-shell-ownership-ledger.json` statuses per wave.
  - tighten shell prune contract to fail when wave targets not met.
- Exit criteria:
  - ledger reaches intended terminal state (`python_verified_delete_now` + explicit intentional keep set only).

### 12) Release readiness and cutover completion
- Objective:
  - make Python default truly production-safe and auditable.
- Implementation:
  - require consecutive green cycles for full Python and BATS matrices.
  - enforce tracked-file completeness for implementation-critical scopes.
  - include migration smoke in release gate (no synthetic mode, no fallback mode).
- Tools:
  - `scripts/release_shipability_gate.py`, `python/envctl_engine/release_gate.py`, `python/envctl_engine/engine_runtime.py --doctor`.
- Exit criteria:
  - release gate passes without overrides; doctor reports parity complete with measured evidence.

## Tests (add these)
### Backend tests
- Extend:
  - `/Users/kfiramar/projects/envctl/tests/python/test_engine_runtime_real_startup.py`
  - `/Users/kfiramar/projects/envctl/tests/python/test_service_manager.py`
  - `/Users/kfiramar/projects/envctl/tests/python/test_requirements_orchestrator.py`
  - `/Users/kfiramar/projects/envctl/tests/python/test_runtime_health_truth.py`
  - `/Users/kfiramar/projects/envctl/tests/python/test_lifecycle_parity.py`
  - `/Users/kfiramar/projects/envctl/tests/python/test_release_shipability_gate.py`
  - `/Users/kfiramar/projects/envctl/tests/python/test_shell_prune_contract.py`
- Add:
  - `/Users/kfiramar/projects/envctl/tests/python/test_runtime_scope_isolation.py`
  - `/Users/kfiramar/projects/envctl/tests/python/test_requirements_adapters_real_contracts.py`
  - `/Users/kfiramar/projects/envctl/tests/python/test_hooks_bridge.py`
  - `/Users/kfiramar/projects/envctl/tests/python/test_dashboard_rendering_parity.py`
  - `/Users/kfiramar/projects/envctl/tests/python/test_supabase_requirements_reliability.py`

### Frontend tests
- Extend:
  - `/Users/kfiramar/projects/envctl/tests/python/test_runtime_projection_urls.py`
  - `/Users/kfiramar/projects/envctl/tests/python/test_frontend_env_projection_real_ports.py`
  - `/Users/kfiramar/projects/envctl/tests/python/test_frontend_projection.py`

### Integration/E2E tests
- Extend existing:
  - `/Users/kfiramar/projects/envctl/tests/bats/python_plan_parallel_ports_e2e.bats`
  - `/Users/kfiramar/projects/envctl/tests/bats/python_resume_projection_e2e.bats`
  - `/Users/kfiramar/projects/envctl/tests/bats/python_requirements_conflict_recovery.bats`
  - `/Users/kfiramar/projects/envctl/tests/bats/python_stop_blast_all_parity_e2e.bats`
  - `/Users/kfiramar/projects/envctl/tests/bats/python_engine_parity.bats`
- Add:
  - `/Users/kfiramar/projects/envctl/tests/bats/python_cross_repo_isolation_e2e.bats`
  - `/Users/kfiramar/projects/envctl/tests/bats/python_planning_worktree_setup_e2e.bats`
  - `/Users/kfiramar/projects/envctl/tests/bats/python_logs_follow_parity_e2e.bats`
  - `/Users/kfiramar/projects/envctl/tests/bats/python_dashboard_interactive_e2e.bats`
  - `/Users/kfiramar/projects/envctl/tests/bats/python_hook_bridge_e2e.bats`
  - `/Users/kfiramar/projects/envctl/tests/bats/python_parser_docs_parity_e2e.bats`
  - `/Users/kfiramar/projects/envctl/tests/bats/python_supabase_network_isolation_e2e.bats`
  - `/Users/kfiramar/projects/envctl/tests/bats/python_supabase_config_fingerprint_reset_e2e.bats`
  - `/Users/kfiramar/projects/envctl/tests/bats/python_supabase_auth_signup_500_regression_e2e.bats`

## Observability / logging (if relevant)
- Standardize structured events for:
  - route selection, scope selection, lock lifecycle, requirements lifecycle, service startup/bind actual, lifecycle cleanup, projection write.
  - Supabase reliability: `supabase.network.contract`, `supabase.auth_namespace.contract`, `supabase.fingerprint.changed`, `supabase.reinit.required`, `supabase.reinit.executed`, `supabase.signup.probe`.
- Persist run artifacts under scoped runtime dir:
  - `run_state.json`, `runtime_map.json`, `ports_manifest.json`, `error_report.json`, `events.jsonl`, shell ownership snapshot.
- Upgrade doctor output:
  - parser parity delta, synthetic usage, scope isolation health, shell-ledger budget status, shipability test status.

## Rollout / verification
- Phase 0: Gate and scope foundation (Steps 1-2).
- Phase 1: Real infra/service ownership (Steps 3-4).
- Phase 2: Planning/worktree and lifecycle parity (Steps 5-7).
- Phase 3: Interactive/logs/hook compatibility parity (Steps 8-9).
- Phase 4: Parser/docs parity closure and shell prune waves (Steps 10-11).
- Phase 5: Release hardening and fallback retirement readiness (Step 12).
- Verification commands per phase:
  - `.venv/bin/python -m unittest discover -s tests/python -p 'test_*.py'`
  - `bats tests/bats/python_*.bats`
  - `bats tests/bats/*.bats`
  - `.venv/bin/python scripts/release_shipability_gate.py --repo . --check-tests`
  - `.venv/bin/python scripts/report_unmigrated_shell.py --repo . --limit 50`
- Supabase auth regression verification checklist:
  - For changed Supabase auth/network/bootstrap config, run explicit reinit workflow (or envctl equivalent):
    - `docker compose ... down -v`
    - `docker compose ... up -d supabase-db`
    - wait healthy
    - `docker compose ... up -d supabase-auth supabase-kong`
  - confirm `/auth/v1/signup` returns non-500 behavior under local test inputs.

## Definition of done
- Python engine owns all primary runtime workflows without requiring shell delegation.
- Default startup path does not rely on synthetic mode.
- Runtime and locks are repo-scoped and safe across concurrent repos.
- Projection/health/errors/dashboard are liveness-grounded and consistent.
- Planning/worktree behavior is deterministic and parity-tested.
- Lifecycle commands are idempotent and ownership-safe.
- Shell ledger reaches planned terminal state and shell prune contract enforces it.
- Release gate and doctor report parity completion from measured evidence.

## Risk register (trade-offs or missing tests)
- Risk: stricter truth checks increase visible failures short-term.
  - Mitigation: richer diagnostics and explicit remediation hints.
- Risk: hook bridge reintroduces shell complexity.
  - Mitigation: constrained subprocess contract with structured output and explicit toggle.
- Risk: repo-scope migration may strand old global state paths.
  - Mitigation: compatibility loader + migration rewrite + cleanup command.
- Risk: aggressive shell deletion can regress edge-case workflows.
  - Mitigation: wave-gated deletion only after passing phase-specific parity tests.
- Risk: Supabase reinit policy requires volume deletion, which can surprise users and remove local auth state.
  - Mitigation: explicit preflight warning, dry-run diagnostics, and policy flags controlling auto-reinit vs manual confirmation.

## Open questions (only if unavoidable)
- Should host-wide `blast-all` remain available long-term or become an internal-only escape hatch?
- What explicit deprecation window should apply to `.envctl.sh` function hooks once Python hook parity is stable?
