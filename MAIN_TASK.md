# Env Override Documentation And Verification Closure

## Context and objective
The prior iteration landed the backend env-isolation fix in code and tests: startup/bootstrap and native `envctl migrate` now share backend env resolution, scrub inherited backend-sensitive shell keys, reconcile the DB URL family, and emit env-source diagnostics. The remaining work is to close the documented contract and verification gap so operator-facing guidance matches the shipped behavior and the original manual multi-worktree verification requirement is completed explicitly.

This iteration must fully implement the remaining scope end-to-end. Do not reopen already-complete backend logic unless a fresh audit proves the docs still disagree with the runtime.

## Remaining requirements (complete and exhaustive)
1. Document the shared relative override-path contract for all env-file override variables in the authoritative docs:
   - `BACKEND_ENV_FILE_OVERRIDE`
   - `MAIN_ENV_FILE_PATH`
   - `FRONTEND_ENV_FILE_OVERRIDE`
   - `MAIN_FRONTEND_ENV_FILE_PATH`
2. Update operator guidance so it is explicit which fallback applies when an override path does not resolve:
   - backend falls back to `backend/.env` when present
   - frontend falls back to `frontend/.env` when present
   - absolute paths remain authoritative when they exist
   - ambiguous relative paths that exist under both the target root and repo root must fail and require an absolute path
3. Document that frontend service start env uses the same dual-resolution contract as backend env-file overrides, while backend-only migrate diagnostics remain backend-scoped.
4. Perform the previously required manual multi-worktree verification and capture concrete evidence in the implementation pass:
   - startup verification with `ENVCTL_BACKEND_MIGRATIONS_ON_STARTUP=true`
   - native `envctl migrate --project <target>` verification for each target
   - verification that conflicting parent-shell `DATABASE_URL` / `APP_ENV_FILE` do not leak into target-scoped backend migration env
   - verification that a relative frontend override path resolves correctly under the documented contract
5. If the manual verification exposes a real runtime mismatch with the documented contract, fix the code and tests in the same iteration instead of narrowing the docs around a broken behavior.

## Gaps from prior iteration (mapped to evidence)
- Frontend override behavior is implemented and tested, but not covered in the authoritative docs:
  - code evidence: `python/envctl_engine/startup/service_bootstrap_domain.py:_resolve_frontend_env_file_resolution`
  - test evidence: `tests/python/startup/test_service_bootstrap_domain.py::test_resolve_frontend_env_file_uses_shared_repo_relative_contract`
  - test evidence: `tests/python/runtime/test_engine_runtime_real_startup.py::test_frontend_env_override_file_is_loaded_for_service_start`
  - test evidence: `tests/python/runtime/test_engine_runtime_real_startup.py::test_main_frontend_env_file_path_is_loaded_in_main_mode`
  - missing-doc evidence: `docs/reference/configuration.md` and `docs/operations/troubleshooting.md` currently describe backend override variables and backend diagnostics but do not mention `FRONTEND_ENV_FILE_OVERRIDE` or `MAIN_FRONTEND_ENV_FILE_PATH`
- The previous task explicitly required manual multi-worktree verification after automated tests, but the anchored git history contains only the implementation commit `1ecc478 fix(backend-env): isolate target env resolution`; there is no follow-up repo evidence that the manual verification step was completed or recorded.

## Acceptance criteria (requirement-by-requirement)
1. `docs/reference/configuration.md` explicitly documents all four override variables and states the exact shared resolution contract:
   - absolute path
   - target-root relative path
   - repo-root relative path
   - ambiguity failure
   - fallback to service-local default `.env`
2. `docs/operations/troubleshooting.md` tells operators how to diagnose both backend and frontend env-file selection without implying incorrect repo-only relative-path semantics.
3. Manual verification is actually run against at least two worktrees with distinct backend env files, and the implementation pass records:
   - the exact commands used
   - which env file/source each target resolved
   - the observed proof that parent-shell backend env leakage was ignored
   - the observed proof that frontend override resolution matched the documented contract
4. If manual verification uncovers a defect, the same iteration lands the required code and test updates before completion.
5. No completed backend-isolation requirements from `OLD_TASK_2.md` are duplicated here unless they must change to satisfy verified runtime evidence.

## Required implementation scope (frontend/backend/data/integration)
- Frontend:
  - update docs for `FRONTEND_ENV_FILE_OVERRIDE` and `MAIN_FRONTEND_ENV_FILE_PATH`
  - document fallback to `frontend/.env` and the shared dual-resolution behavior
- Backend:
  - update backend docs only where needed to keep the shared contract accurate
  - make code/test changes only if manual verification reveals a real mismatch
- Data/state:
  - no schema or migration-file changes are expected
  - if verification depends on persisted migrate failure metadata or startup events, confirm the existing metadata matches the documented contract
- Integration:
  - run multi-worktree startup and native migrate verification against real repo targets or faithful local fixtures
  - verify both backend env isolation and frontend override resolution in the same iteration

## Required tests and quality gates
- Re-run the focused automated suites that already lock the current contract before or alongside manual verification:
  - `PYTHONPATH=python python3 -m unittest tests.python.startup.test_service_bootstrap_domain`
  - `PYTHONPATH=python python3 -m unittest tests.python.actions.test_actions_parity`
  - `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_real_startup`
- Manual verification is required and is not optional:
  - run startup verification across at least two worktrees with distinct backend `.env` contents
  - run `envctl migrate --project <target>` for each verified worktree
  - repeat with conflicting parent-shell backend env vars exported
  - run at least one frontend override-path verification using a relative path that resolves through the documented contract
- If code changes are needed after manual verification, add or extend the narrowest tests that prove the newly discovered behavior.

## Edge cases and failure handling
- Relative override paths that exist under both the target root and repo root must be documented and observed as hard failures requiring an absolute path.
- Missing override files must be documented and observed as falling back to the service-local default `.env` only when that default file exists.
- Documentation and verification output must not expose secret env values; record file paths, source classifications, and key names only.
- Main-mode frontend override behavior and tree/worktree frontend override behavior must both remain explicit in the docs.

## Definition of done
- The authoritative docs describe the same override-path contract that the runtime currently implements for both backend and frontend env-file overrides.
- The manual multi-worktree verification required by the previous task has been completed and recorded with concrete commands and outcomes.
- Any defect discovered during that verification has been fixed with matching tests in the same iteration.
- No remaining undocumented or unverified scope from `OLD_TASK_2.md` is left open at the end of the pass.
