## 2026-03-19 - Migrate backend env parity

Scope:
- Implement native `envctl migrate` backend env parity with startup/bootstrap so Alembic receives backend env-file context plus current dependency projection when a saved run state exists.
- Improve migrate failure summaries for env-missing import failures before Alembic reaches the revision chain.
- Document the migrate env contract and troubleshooting flow.

Key behavior changes:
- Added a migrate-specific env builder in `python/envctl_engine/actions/action_command_orchestrator.py` that starts from the generic action env, resolves the backend env file, exports `APP_ENV_FILE`, and merges run-state dependency projection for `DATABASE_URL` and `REDIS_URL`.
- Explicit backend env override files now remain authoritative for `DATABASE_URL` during migrate, matching existing `SKIP_LOCAL_DB_ENV` semantics.
- Default backend `.env` migrate runs now prefer envctl's projected `DATABASE_URL` and `REDIS_URL` from saved requirements state when available.
- Migrate failure summaries are now enriched with envctl-specific hint lines when the traceback shows an `alembic/env.py` import-time settings failure caused by missing required env vars.
- Dashboard interactive failure rendering now prints migrate hint lines once before the persisted failure-log path.

Files and modules touched:
- `python/envctl_engine/actions/action_command_orchestrator.py`
- `python/envctl_engine/ui/dashboard/orchestrator.py`
- `tests/python/actions/test_actions_parity.py`
- `tests/python/ui/test_dashboard_orchestrator_restart_selector.py`
- `docs/reference/commands.md`
- `docs/reference/configuration.md`
- `docs/operations/troubleshooting.md`

Tests run and results:
- `PYTHONPATH=python python3 -m unittest tests.python.actions.test_actions_parity`
  - Passed (`Ran 103 tests`)
- `PYTHONPATH=python python3 -m unittest tests.python.ui.test_dashboard_orchestrator_restart_selector`
  - Passed (`Ran 48 tests`)
- `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_real_startup tests.python.runtime.test_engine_runtime_env`
  - Passed (`Ran 151 tests`)

Config, env, and migrations:
- Documented and exercised `BACKEND_ENV_FILE_OVERRIDE`, `MAIN_ENV_FILE_PATH`, `APP_ENV_FILE`, and `SKIP_LOCAL_DB_ENV` behavior for native `migrate`.
- No repository schema migrations or Alembic revision files were changed.
- Raw persisted migrate failure reports remain unchanged; only the stored summary surface is enriched.

Risks and notes:
- Migrate env projection intentionally depends on saved `RunState.requirements`; if no saved state exists, envctl still falls back to backend env-file resolution plus the inherited parent environment.
- The missing-env summary enrichment is intentionally narrow to Alembic import-time validation failures so generic migrate errors continue to use the existing summary behavior.
