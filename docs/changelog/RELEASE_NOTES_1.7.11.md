# envctl 1.7.11

`envctl` 1.7.11 is a hotfix release on top of `1.7.10`. It packages the shared-runtime dependency defaults and implementation-agent validation hardening from PR #159 so tree runs, dependencies, and AI implementation prompts line up with the now-default full-system workflow.

## Fixed

- Backend test and migrate actions now inherit the active project dependency environment, so configured Python tests and Alembic migrations can reach the managed database, Redis, Supabase, and n8n ports for the selected project.
- Backend Python test commands now prefer Poetry project execution when the backend declares a Poetry/PDM pyproject, avoiding missing-dependency failures from the wrong interpreter.
- Selected-service restarts preserve existing backend/frontend ports and aggressively clear stale listeners from the same service working directory before relaunching.
- n8n native startup now explicitly pulls the configured image before `docker create`, preventing cold-host image download latency from being misclassified as a create timeout.

## Added

- Mode-scoped launch-env template sections let main and tree runs project different backend/frontend dependency URLs while preserving the existing generic sections.
- `--shared-deps` / `--shared-dependencies` and `--isolated-deps` / `--isolated-dependencies` make tree dependency source selection explicit.
- Tree starts now default to the main/shared dependency stack, while `--isolated-deps` keeps per-tree dependencies available when needed.
- Start routes now default to the entire system, so a bare `envctl --main` or `envctl --trees` starts dependencies plus configured backend/frontend services.
- Direct `implement_task` prompt launches now inject current localhost addresses for known dependencies, backend, and frontend from saved envctl runtime state.

## Changed

- Supabase browser-facing URLs now use `ENVCTL_PUBLIC_HOST` when configured instead of always projecting `localhost`.
- `implement_task` guidance now requires final validation after implementation and requires reporting the actual dependency/backend/frontend addresses used during validation.
- Worktree runs that use shared dependencies annotate saved dependency records with the main container names, keeping subsequent health checks truthful.

## Why This Release Matters

This hotfix aligns envctl defaults with the way full-stack validation is actually used: the default path now brings up the complete system, tree runs share the main dependency stack unless explicitly isolated, and implementation agents receive the current runtime addresses instead of having to infer ports from stale context. It also closes several reliability gaps found while validating Supportopia-shaped projects end to end, especially around dependency-aware tests, latest n8n images, and restart port stability.

## Validation

Release-candidate validation for this version ran:

- `./.venv/bin/python -m pytest tests/python/runtime/test_prompt_install_support.py tests/python/planning/test_plan_agent_launch_support.py -q` → 150 passed, 20 subtests passed
- `./.venv/bin/python -m pytest tests/python/runtime/test_cli_router_parity.py tests/python/startup/test_startup_orchestrator_profiles.py tests/python/runtime/test_prereq_policy.py -q` → 48 passed, 37 subtests passed
- `./.venv/bin/python -m pytest tests/python/requirements/test_requirements_adapters_real_contracts.py -k "n8n_pulls_image_before_create_by_default or n8n_can_skip_image_pull or n8n_uses_configured_image_override"` → 3 passed, 65 deselected
- Manual E2E default main and tree startup checks passed with healthy dependencies, backend, and frontend services; direct `implement_task` prompt resolution injected the current Postgres, Redis, n8n, backend, and frontend localhost addresses.
- `./.venv/bin/python -m pytest tests/python/runtime/test_launcher_version.py tests/python/runtime/test_cli_packaging.py::CliPackagingTests::test_release_version_metadata_is_consistent tests/python/runtime/test_cli_packaging.py::CliPackagingTests::test_release_notes_exist_for_current_version tests/python/runtime/test_cli_packaging.py::CliPackagingTests::test_build_smoke_is_warning_free tests/python/runtime/test_release_shipability_gate.py tests/python/runtime/test_release_shipability_gate_cli.py -q` → 33 passed
- `PYTHONPATH=python ./.venv/bin/python -m compileall -q python tests` → passed
- `git diff --check` → passed
- `./.venv/bin/python scripts/release_shipability_gate.py --repo . --skip-tests` → `shipability.passed: true`
- `./.venv/bin/python -m build` → built `dist/envctl-1.7.11-py3-none-any.whl` and `dist/envctl-1.7.11.tar.gz`

## Artifacts

This release publishes:

- wheel distribution: `envctl-1.7.11-py3-none-any.whl`
- source distribution: `envctl-1.7.11.tar.gz`
- release notes markdown asset: `RELEASE_NOTES_1.7.11.md`

## Upgrade Notes

- No `.envctl` config migration is required.
- Tree runs now use shared/main dependencies by default; pass `--isolated-deps` when you intentionally need a separate per-tree dependency stack.
- Bare `envctl --main` and `envctl --trees` now default to entire-system startup. Use `--only-backend`, `--only-frontend`, `--dependencies`, `--no-deps`, or `--no-infra` to request a narrower runtime shape.
