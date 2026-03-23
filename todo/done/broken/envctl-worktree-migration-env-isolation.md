# Envctl Worktree Migration Env Isolation Plan

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Make backend startup migrations and native `envctl migrate` resolve env inputs per target/worktree deterministically instead of partially inheriting whatever shell launched `envctl`.
  - Keep each worktree on its own effective database/env contract so one tree cannot silently migrate against another tree's DB URLs or env-file pointers.
  - Align code, docs, and diagnostics for backend env-file override resolution so operators can predict which env file a migration used.
  - Remove startup/action drift by making backend env resolution and DB-key reconciliation a shared contract.
- Non-goals:
  - Changing Alembic revision files, application settings loaders, or repo-specific backend code outside envctl.
  - Adding a new secrets-management system or remote env fetch path.
  - Reworking generic frontend launch env handling beyond any shared path-resolution helper that backend startup already owns.
- Assumptions:
  - The pasted failure analysis referenced in the ticket was not available in this repo review, so this plan is grounded in verified code/tests/docs plus the user-reported symptom about worktree-specific migration env misconfiguration.
  - The product contract in [README.md](README.md) is authoritative: envctl should keep worktree environments isolated.
  - Backward compatibility for absolute override paths must be preserved.

## Goal (user experience)
When an operator starts or migrates `Main` plus multiple worktrees, each target should run Alembic with the env file and dependency URLs intended for that exact target. Relative override paths should resolve predictably, inherited shell `DATABASE_URL`-style values should not leak into unrelated worktrees, stale DB alias variables should not silently win over envctl's current local dependency projection, and failure output should say which env source was actually used.

## Business logic and data model mapping
- Target identity and root selection:
  - `python/envctl_engine/runtime/engine_runtime.py:ProjectContext`
  - `python/envctl_engine/runtime/engine_runtime.py:_discover_projects`
  - `python/envctl_engine/startup/run_reuse_support.py:build_startup_identity_metadata`
- Runtime dependency state that feeds backend env projection:
  - `python/envctl_engine/state/models.py:RequirementsResult`
  - `python/envctl_engine/state/models.py:RunState.requirements`
  - `python/envctl_engine/actions/action_command_orchestrator.py:_migrate_requirements_for_target`
- Persisted metadata used during follow-up actions and debugging:
  - `python/envctl_engine/state/models.py:RunState.metadata`
  - `RunState.metadata["project_roots"]`
  - `RunState.metadata["project_action_reports"][project]["migrate"]`
- Env projection owners:
  - `python/envctl_engine/runtime/engine_runtime_env.py:project_service_env`
  - `python/envctl_engine/runtime/engine_runtime_env.py:project_service_env_internal`
  - `python/envctl_engine/requirements/dependencies/postgres/__init__.py:project_env`
  - `python/envctl_engine/requirements/dependencies/supabase/__init__.py:project_env`
- Backend env-file resolution and migration execution owners:
  - `python/envctl_engine/startup/service_bootstrap_domain.py:_resolve_backend_env_file`
  - `python/envctl_engine/startup/service_bootstrap_domain.py:_service_env_from_file`
  - `python/envctl_engine/startup/service_bootstrap_domain.py:_prepare_backend_runtime`
  - `python/envctl_engine/startup/service_bootstrap_domain.py:_run_backend_migration_step`
  - `python/envctl_engine/actions/action_command_orchestrator.py:migrate_action_env`
  - `python/envctl_engine/actions/action_command_orchestrator.py:run_migrate_action`

## Current behavior (verified in code)
- There are two backend migration paths and they assemble env separately:
  - Native action path: `python/envctl_engine/runtime/engine_runtime.py:_run_migrate_action` delegates to `python/envctl_engine/actions/action_command_orchestrator.py:run_migrate_action`, which builds subprocess env through `migrate_action_env(...)`.
  - Startup/bootstrap path: `python/envctl_engine/startup/service_execution.py:start_project_services` calls `python/envctl_engine/startup/service_bootstrap_domain.py:_prepare_backend_runtime`, which may call `_run_backend_migration_step(...)` when `ENVCTL_BACKEND_MIGRATIONS_ON_STARTUP` is enabled.
- Both paths start from the parent process environment before target-specific cleanup:
  - `python/envctl_engine/actions/action_command_support.py:build_action_env` begins with `env = dict(process_env)` where `process_env=os.environ`, then overlays `runtime_env`.
  - `python/envctl_engine/runtime/engine_runtime_commands.py:command_env` begins with `env = dict(os.environ)`, then overlays `runtime.env`.
  - There is no targeted scrubbing step for inherited backend-sensitive keys like `DATABASE_URL`, `SQLALCHEMY_DATABASE_URL`, `ASYNC_DATABASE_URL`, `APP_ENV_FILE`, `DB_HOST`, or `DB_NAME` before target-specific merge logic runs.
- Native migrate env parity is only partial after env-file merge:
  - `python/envctl_engine/actions/action_command_orchestrator.py:migrate_action_env` merges `projected_env`, then env-file values from `_read_env_file_safe(...)`, then re-applies only `DATABASE_URL` and `REDIS_URL` when `skip_local_db_env` is false.
  - The same function does not reconcile inherited or env-file-provided `SQLALCHEMY_DATABASE_URL` / `ASYNC_DATABASE_URL`, even when the active dependency projector supplied newer canonical DB URLs before the env file overwrote them.
- Startup/backend bootstrap parity has the same partial DB-key rewrite:
  - `python/envctl_engine/startup/service_bootstrap_domain.py:_prepare_backend_runtime` merges env-file values into `env`, then overwrites `DATABASE_URL` and conditionally `REDIS_URL`, but does not rewrite or clear stale `SQLALCHEMY_DATABASE_URL` / `ASYNC_DATABASE_URL`.
  - `python/envctl_engine/startup/service_bootstrap_domain.py:_sync_backend_env_file` only writes back `DATABASE_URL` and `REDIS_URL` to the default backend `.env`.
- Relative env-file override behavior is ambiguous between docs and code:
  - `python/envctl_engine/startup/service_bootstrap_domain.py:_resolve_backend_env_file` and `_resolve_frontend_env_file` call `_override_env_path(..., base_dir=context.root)`.
  - `_override_env_path(...)` resolves relative paths against the target project's root/worktree root, not the repo root.
  - The docs currently describe `BACKEND_ENV_FILE_OVERRIDE` / `MAIN_ENV_FILE_PATH` as accepting repo-relative paths in [docs/reference/configuration.md](docs/reference/configuration.md) and [docs/operations/troubleshooting.md](docs/operations/troubleshooting.md).
- Current tests cover positive env-file and projection cases, but not the isolation gaps:
  - `tests/python/actions/test_actions_parity.py` covers default backend `.env`, absolute override files, `APP_ENV_FILE`, and projected `DATABASE_URL` / `REDIS_URL` for native `migrate`.
  - `tests/python/runtime/test_engine_runtime_real_startup.py` covers startup env-file loading, absolute overrides, default `.env` writeback, and startup Alembic retry/warning behavior.
  - No verified test covers:
    - inherited shell DB env leakage into `migrate` or startup
    - stale `SQLALCHEMY_DATABASE_URL` / `ASYNC_DATABASE_URL` surviving a projected local DB rewrite
    - relative override-path semantics in trees mode
    - one multi-worktree startup/migrate run proving each worktree gets a distinct effective backend env contract

## Root cause(s) / gaps
- Backend env composition is duplicated across startup/bootstrap and action-command code paths, so fixes land in one path without guaranteeing parity in the other.
- Both paths inherit the full launcher shell environment first and never explicitly scrub backend-sensitive keys before target-specific assembly, so missing or incomplete worktree env files can accidentally reuse unrelated shell values.
- DB URL reconciliation is incomplete:
  - envctl force-corrects `DATABASE_URL` and `REDIS_URL`
  - but it leaves `SQLALCHEMY_DATABASE_URL` and `ASYNC_DATABASE_URL` untouched after env-file merge
  - which means stale aliases can still drive Alembic/settings to the wrong database even when `DATABASE_URL` was corrected
- The override-path contract is not explicit:
  - code currently treats relative override paths as target-root-relative
  - docs promise repo-relative inputs
  - there is no diagnostic telling operators which interpretation won
- The current test suite proves positive env parity for single-target happy paths, but it does not lock down worktree isolation, relative-path behavior, or parent-shell contamination.

## Plan
### 1) Introduce one shared backend env-resolution/composition helper for startup and native `migrate`
- Add a single helper in the backend env owner layer, likely in `python/envctl_engine/startup/service_bootstrap_domain.py` or a small sibling module, that both of these call sites use:
  - `python/envctl_engine/startup/service_bootstrap_domain.py:_prepare_backend_runtime`
  - `python/envctl_engine/actions/action_command_orchestrator.py:migrate_action_env`
- The helper should own:
  - backend env-file path resolution
  - source tagging (`default`, `explicit_override`, `none`, and relative-path subtype if needed)
  - inherited-env scrubbing for backend-sensitive keys
  - authoritative merge order between runtime projection, env file, and explicit override semantics
  - a small metadata result that can be logged and surfaced in failures
- Keep command-specific concerns outside the helper:
  - startup-only writeback/fingerprint updates stay with startup code
  - action-only state-report persistence stays with `ActionCommandOrchestrator`

### 2) Define and enforce an explicit relative override-path contract
- Resolve the current docs/code mismatch for:
  - `BACKEND_ENV_FILE_OVERRIDE`
  - `MAIN_ENV_FILE_PATH`
  - `FRONTEND_ENV_FILE_OVERRIDE`
  - `MAIN_FRONTEND_ENV_FILE_PATH`
- Recommended compatibility-safe resolution:
  - absolute paths stay unchanged
  - relative paths are evaluated against both the target project root and the repo root
  - if exactly one candidate exists, use it and record the source
  - if both exist and differ, fail with an actionable ambiguity error telling the operator to use an absolute path
  - if neither exists, preserve the current fallback-to-default behavior but emit a bounded diagnostic that the override did not resolve
- Update docs so they stop implying a single interpretation that code does not actually enforce.

### 3) Scrub inherited shell env before assembling backend migration/startup env
- Define an explicit backend-sensitive inherited-env scrub list before target-specific merge, covering at minimum:
  - `APP_ENV_FILE`
  - `DATABASE_URL`
  - `REDIS_URL`
  - `SQLALCHEMY_DATABASE_URL`
  - `ASYNC_DATABASE_URL`
  - `DB_HOST`
  - `DB_PORT`
  - `DB_USER`
  - `DB_PASSWORD`
  - `DB_NAME`
- Preserve non-backend command behavior:
  - general shell vars, PATH, Git/GH prompt suppression, Python path wiring, and non-sensitive user overrides still flow through
- Apply the same scrub policy to both:
  - native `migrate`
  - startup/backend bootstrap before optional Alembic execution
- This change should make envctl fail fast or use the target env contract, rather than silently migrating against a DB value inherited from the caller's shell.

### 4) Reconcile the full DB URL family, not only `DATABASE_URL`
- Extend backend env reconciliation so envctl handles the entire DB-key family intentionally after env-file merge:
  - `DATABASE_URL`
  - `SQLALCHEMY_DATABASE_URL`
  - `ASYNC_DATABASE_URL`
  - plus `REDIS_URL` where applicable
- Required policy decision to implement explicitly:
  - if envctl has authoritative current projection values for a key family, those values win for default per-worktree env files and for no-env-file cases
  - explicit non-default env override files remain authoritative when `SKIP_LOCAL_DB_ENV` semantics say they should
  - if envctl does not have a safe canonical replacement for a scrubbed key, leave only env-file-owned values in place; never resurrect inherited shell values
- Update startup writeback in `python/envctl_engine/startup/service_bootstrap_domain.py:_sync_backend_env_file` so the default backend `.env` no longer keeps stale DB alias URLs that point at the wrong worktree DB after startup.
- Ensure async-driver retry in `_backend_migration_retry_env_for_async_driver_mismatch(...)` operates on the reconciled DB-key family rather than only best-effort patching one branch.

### 5) Add source-aware diagnostics and failure context
- Emit one bounded structured event whenever envctl resolves backend migration/startup env for a target, for example:
  - `backend.env.resolved`
- Suggested payload:
  - `project`
  - `project_root`
  - `backend_cwd`
  - `env_file_path`
  - `env_file_source`
  - `override_requested=true|false`
  - `override_resolution=target_root|repo_root|absolute|ambiguous|missing`
  - `override_authoritative=true|false`
  - `scrubbed_keys=[...]`
  - `projected_keys=[...]`
- Reuse that metadata in user-facing failure summaries where it materially helps, especially:
  - native `migrate` failure summaries persisted through `project_action_reports`
  - startup migration warning text from `_run_backend_migration_step(...)`
- Keep diagnostics bounded and avoid logging secret values; only log key names and resolved file paths.

### 6) Lock the contract with focused tests before broader refactors
- Add unit coverage around the shared helper and path-resolution rules first so startup/action implementations can move behind a stable contract.
- Then extend startup/action parity tests to prove the two code paths now behave the same for the same target/env inputs.
- Prefer small deterministic tests over broad end-to-end fixtures unless the behavior crosses multiple modules and cannot be validated otherwise.

## Tests (add these)
### Backend tests
- Extend [tests/python/startup/test_service_bootstrap_domain.py](/Users/kfiramar/projects/current/envctl/tests/python/startup/test_service_bootstrap_domain.py):
  - add focused tests for backend env-file resolution with:
    - absolute override path
    - relative path resolving only under target-root semantics
    - relative path resolving only under repo-root semantics
    - ambiguous dual-match failure
    - missing override fallback to default `backend/.env`
  - add helper-level tests proving inherited shell DB keys are scrubbed before target-specific merge
  - add helper-level tests proving explicit override authority differs from default `.env` authority
- Extend [tests/python/actions/test_actions_parity.py](/Users/kfiramar/projects/current/envctl/tests/python/actions/test_actions_parity.py):
  - native `migrate` does not inherit `DATABASE_URL` / `APP_ENV_FILE` from the parent shell when the target contract says otherwise
  - stale `SQLALCHEMY_DATABASE_URL` / `ASYNC_DATABASE_URL` in backend env files cannot override envctl's current projected DB target when default `.env` is in use
  - explicit override files remain authoritative when `SKIP_LOCAL_DB_ENV` semantics apply
  - relative override-path behavior is pinned for tree targets
  - multi-target `migrate` runs use the correct env file and DB URL family for each target independently
- Extend [tests/python/runtime/test_engine_runtime_real_startup.py](/Users/kfiramar/projects/current/envctl/tests/python/runtime/test_engine_runtime_real_startup.py):
  - startup/bootstrap path scrubs inherited shell DB vars before backend prep
  - startup migrations for two worktrees in one run produce distinct `APP_ENV_FILE` / DB env contracts per worktree
  - default backend `.env` writeback updates or removes stale DB alias keys per the chosen ownership policy
  - startup warnings include resolved env-file/source diagnostics without secret values
- Extend [tests/python/runtime/test_engine_runtime_env.py](/Users/kfiramar/projects/current/envctl/tests/python/runtime/test_engine_runtime_env.py) only if projector output changes are needed to support the final DB-key-family policy.

### Frontend tests
- No browser/frontend UI tests are required for the core migration bug.
- If frontend override-path resolution shares the same helper, add one narrow regression in [tests/python/runtime/test_engine_runtime_real_startup.py](/Users/kfiramar/projects/current/envctl/tests/python/runtime/test_engine_runtime_real_startup.py) covering relative frontend env-file resolution so the shared contract does not regress on one side.

### Integration/E2E tests
- Manual verification across at least two tree targets in one repo:
  1. create two worktrees with distinct backend env files or default `backend/.env` contents
  2. run `envctl --plan --batch` with `ENVCTL_BACKEND_MIGRATIONS_ON_STARTUP=true`
  3. confirm each backend migration log shows the correct `APP_ENV_FILE`/resolved env source and target DB URL family
  4. rerun `envctl migrate --project <tree>` for each target and confirm the same resolved env source is used
  5. repeat once with conflicting shell `DATABASE_URL` / `APP_ENV_FILE` exported in the parent shell and confirm those values are ignored for target-scoped migration env assembly

## Observability / logging (if relevant)
- Add one bounded env-resolution event as described above.
- Include the resolved backend env-file source in persisted migrate failure metadata when available so `show-state --json` and dashboard failure views can explain which file/source was used.
- Do not log secret env values. Log only:
  - file paths
  - source classifications
  - key names that were scrubbed or projected

## Rollout / verification
- Implementation order:
  1. add shared backend env-resolution helper plus unit tests
  2. switch native `migrate` to that helper
  3. switch startup/backend bootstrap to the same helper
  4. add diagnostics/failure-summary enrichment
  5. update docs for the final relative-path contract
- Verification commands:
  - `PYTHONPATH=python python3 -m unittest tests.python.startup.test_service_bootstrap_domain`
  - `PYTHONPATH=python python3 -m unittest tests.python.actions.test_actions_parity`
  - `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_real_startup`
  - `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_env`
- After automated tests, run one manual multi-worktree startup and one manual `migrate` confirmation because the bug report is about target-specific runtime behavior, not only isolated helper logic.

## Definition of done
- Native `envctl migrate` and startup-triggered backend migrations use one shared backend env-resolution contract.
- Relative override-path semantics are explicit, tested, and documented.
- Backend-sensitive shell env leakage no longer changes the effective env for a different worktree's migration.
- Default per-worktree env files cannot keep stale DB alias URLs that silently point migrations at the wrong DB.
- Failure surfaces and diagnostics identify which env-file source was actually used for the target.
- Automated tests cover startup path, action path, helper logic, and at least one multi-worktree isolation case.

## Risk register (trade-offs or missing tests)
- Risk: some repos may currently rely on inherited shell DB vars as an unofficial fallback when no backend env file exists.
  - Mitigation: treat inherited backend-sensitive vars as unsupported, document the change, and make failures point to the missing target env source explicitly.
- Risk: relative override-path behavior is already ambiguous between docs and code, so tightening it can surprise existing users.
  - Mitigation: support absolute paths unchanged, add dual-resolution plus ambiguity errors, and document the winning source.
- Risk: different backends may treat `DATABASE_URL`, `SQLALCHEMY_DATABASE_URL`, and `ASYNC_DATABASE_URL` differently.
  - Mitigation: define a single envctl ownership policy for the DB-key family, test both explicit-override and default-env cases, and avoid resurrecting inherited shell values.
- Risk: startup and action paths currently drift, so partial implementation would reintroduce inconsistency.
  - Mitigation: land the shared helper first and refuse follow-up patches that re-split the contract.

## Open questions (only if unavoidable)
- None required to execute the implementation plan. The missing pasted failure log would help prioritize which branch reproduced first, but it is not necessary to define the fix plan because the repo already shows the isolation gaps above.
