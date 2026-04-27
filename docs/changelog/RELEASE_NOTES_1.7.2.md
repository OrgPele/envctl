# envctl 1.7.2

`envctl` 1.7.2 is a hotfix release on top of `1.7.1`. It restores dynamic PostgreSQL and Redis wiring for projects whose `.envctl` launch env templates request `DATABASE_URL` and `REDIS_URL` but do not explicitly enable dependency toggles.

## Why This Hotfix Matters

In Supportopia-shaped repos, `.envctl` can contain active backend launch env templates such as `DATABASE_URL=${ENVCTL_SOURCE_DATABASE_URL}` and `REDIS_URL=${ENVCTL_SOURCE_REDIS_URL}` while omitting managed dependency toggle keys. After 1.7.1, that shape could leave PostgreSQL and Redis disabled, so the backend received only `PORT` and failed Pydantic settings validation for missing `DATABASE_URL` and `REDIS_URL`.

This hotfix treats active core database/cache launch env templates as requests for envctl-managed dynamic dependency URLs when the matching toggle is absent. The generated URLs still use the per-run/per-project allocated ports.

## Highlights

### Dynamic DB/Redis inference from launch env templates

- Active backend/frontend launch templates referencing core DB inputs now infer PostgreSQL when no explicit PostgreSQL toggle is present.
- Active launch templates referencing Redis inputs now infer Redis when no explicit Redis toggle is present.
- Explicit toggles still win: `MAIN_POSTGRES_ENABLE=false`, `MAIN_REDIS_ENABLE=false`, `TREES_POSTGRES_ENABLE=false`, and `TREES_REDIS_ENABLE=false` keep those dependencies disabled.
- Optional service templates such as n8n and Supabase remain opt-in and are not auto-enabled by the default template block.

### Accurate config inspection

- `envctl show-config --json` now reports the runtime-effective profile values, including dynamic dependency inferences, instead of showing only persisted managed defaults.

### Documentation

- Configuration and first-run wizard docs now explain that core DB/Redis launch env templates imply dynamic envctl-managed dependencies unless explicit toggles override them.

## Verification

Validated in the implementation worktree with:

- `./.venv/bin/python -m pytest tests/python -q` ✅
- `./.venv/bin/python -m ruff check python/envctl_engine/config/__init__.py python/envctl_engine/runtime/inspection_support.py tests/python/config/test_config_loader.py tests/python/runtime/test_engine_runtime_real_startup.py tests/python/runtime/test_engine_runtime_command_parity.py` ✅
- Supportopia smoke with local source checkout:
  - `envctl show-config --json` shows `main.dependencies.postgres=true` and `main.dependencies.redis=true` from the launch env templates ✅
  - `envctl --main --batch` with strict Docker requirements disabled reached backend import/startup with projected `DATABASE_URL`, `REDIS_URL`, `SQLALCHEMY_DATABASE_URL`, and `ASYNC_DATABASE_URL`; the previous missing-settings error was gone ✅

## Known Environmental Limitation During Smoke

A strict real-Docker Supportopia smoke could not complete in the local container host because Docker failed to program iptables DNAT rules for newly created PostgreSQL/Redis containers. That host-level Docker networking failure occurs after envctl now enables the dynamic requirements and is separate from the missing `DATABASE_URL`/`REDIS_URL` regression.

## Artifacts

This release publishes:

- wheel distribution
- source distribution
- release notes markdown asset

After build, the artifacts are available under `dist/`.

## Upgrade Notes

- No manual `.envctl` edit is required for projects with active `DATABASE_URL=${ENVCTL_SOURCE_DATABASE_URL}` or `REDIS_URL=${ENVCTL_SOURCE_REDIS_URL}` templates and no explicit dependency toggles.
- Add explicit dependency toggles set to `false` if you want to keep those launch env template lines present but prevent envctl from starting PostgreSQL or Redis.

## Summary

`envctl` 1.7.2 fixes the dynamic dependency-env regression by making active core DB/Redis launch env templates drive envctl-managed dependency startup again while preserving explicit user toggles.
