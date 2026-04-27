# envctl 1.7.6

`envctl` 1.7.6 is a patch release on top of `1.7.5`. It adds the scoped runtime controls needed for fast local and AI-driven validation, and updates the implementation-task guidance so agents default to dependency-inclusive E2E validation when behavior may involve app services plus managed requirements.

## Added

- New start-time runtime-scope flags:
  - `--backend` starts backend services only.
  - `--frontend` starts frontend services only.
  - `--fullstack` / `--both` starts backend and frontend services without managed dependency-only scope selection.
  - `--dependencies` / `--deps` starts managed dependencies only.
  - `--entire-system` starts managed dependencies plus all configured app services.
- Matching cleanup ergonomics:
  - `envctl stop --backend --headless`
  - `envctl stop --frontend --headless`
  - `envctl stop --fullstack --headless`
  - `envctl stop --dependencies --headless`
  - `envctl stop --entire-system --headless`
  - `envctl kill --<scope> --headless` and `envctl kill-all --headless` aliases for users who use kill terminology.
- Documentation for the new scope flags in the command reference, important flags reference, common workflows, and runtime feature inventory contracts.

## Changed

- Startup selection now respects the requested runtime scope while preserving dependency startup for scopes that need managed requirements.
- Dependency-only stop now releases requirement ports without terminating app services.
- The `implement_task` prompt now explains when to use backend-only, frontend-only, fullstack, dependencies-only, and entire-system validation.
- The generated `$envctl-implement-task` Codex skill metadata and OpenAI skill default prompt now advertise the same scoped-runtime decision criteria.
- Implementation-task guidance now defaults uncertain, cross-boundary, browser-visible, or dependency-backed validation to `envctl --entire-system --headless`. `envctl --fullstack --headless` is reserved for cases where managed dependencies are mocked, disabled, externalized, or proven unnecessary.
- UI/product implementation guidance now explicitly expects Playwright E2E validation against a running service, cleanup of the exact scope started, and an offer to restart for human verification.

## Why This Release Matters

This release gives humans and implementation agents direct, memorable commands for the common validation shapes: backend-only, frontend-only, fullstack, dependencies-only, and the complete system. It reduces both over-starting and under-testing: small backend or frontend changes can use narrow scopes, while product/browser/API/data-path changes are steered toward dependency-inclusive validation by default.

The dependency-inclusive default is especially important for repos whose behavior depends on PostgreSQL, Redis, queues, Supabase, n8n, or other managed services. Agents should not claim final E2E confidence from backend/frontend processes alone when the real workflow needs dependencies.

## Validation

Validated in the implementation and release worktrees with:

- `./.venv/bin/python -m pytest tests/python/runtime/test_cli_router_parity.py::CliRouterParityTests::test_runtime_scope_flags_are_parsed_for_start_and_kill_commands tests/python/startup/test_startup_orchestrator_profiles.py tests/python/runtime/test_lifecycle_cleanup_spinner_integration.py::LifecycleCleanupSpinnerIntegrationTests::test_stop_runtime_scope_backend_selects_backend_services_without_prompt tests/python/runtime/test_lifecycle_cleanup_spinner_integration.py::LifecycleCleanupSpinnerIntegrationTests::test_stop_dependencies_scope_releases_requirements_without_terminating_services tests/python/runtime/test_prompt_install_support.py::PromptInstallSupportTests::test_renderers_produce_expected_target_shapes -q` → 8 passed.
- `./.venv/bin/python -m pytest tests/python/runtime/test_cli_router_parity.py tests/python/startup/test_startup_orchestrator_profiles.py tests/python/runtime/test_lifecycle_cleanup_spinner_integration.py tests/python/runtime/test_prompt_install_support.py -q` → 62 passed, 10 subtests passed.
- `./.venv/bin/python -m pytest tests/python/runtime tests/python/startup -q` → 749 passed, 12 skipped, 100 subtests passed.
- `./.venv/bin/python -m pytest tests/python -q` → 1834 passed, 12 skipped, 4 warnings, 138 subtests passed.
- `./.venv/bin/python -m pytest tests/python/runtime/test_prompt_install_support.py::PromptInstallSupportTests::test_renderers_produce_expected_target_shapes tests/python/runtime/test_prompt_install_support.py::PromptInstallSupportTests::test_install_prompts_installs_codex_skills_with_legacy_feature_flag -q` → 2 passed.
- `./.venv/bin/python -m ruff check python/envctl_engine/runtime/prompt_templates/implement_task.md python/envctl_engine/runtime/prompt_install_support.py tests/python/runtime/test_prompt_install_support.py` → passed.
- `./.venv/bin/python -m pytest tests/python/runtime/test_prompt_install_support.py -q` → 35 passed, 10 subtests passed.
- Manual E2E smoke against a disposable local app and wheel built from the feature branch underlying this release:
  - Backend-only start and kill.
  - Frontend-only start and stop.
  - Fullstack start and Playwright browser navigation to a frontend that displayed data fetched from the backend.
  - Dependencies-only start/stop with no app services in the disposable app.
  - Backend start followed by `kill-all` cleanup.

Release-candidate validation for this version additionally ran:

- `./.venv/bin/python -m pytest tests/python/runtime/test_launcher_version.py tests/python/runtime/test_cli_packaging.py tests/python/runtime/test_release_shipability_gate.py tests/python/runtime/test_release_shipability_gate_cli.py -q` → 53 passed, 12 skipped.
- `./.venv/bin/python scripts/release_shipability_gate.py --repo . --check-tests` → `shipability.passed: true`.
- `./.venv/bin/python -m build` → built `dist/envctl-1.7.6-py3-none-any.whl` and `dist/envctl-1.7.6.tar.gz`.

## Artifacts

This release publishes:

- wheel distribution
- source distribution
- release notes markdown asset

## Upgrade Notes

- No `.envctl` changes are required.
- Existing commands keep working.
- Use `envctl --entire-system --headless` for final browser/product/API/data validation when dependencies may matter.
- Use `envctl --fullstack --headless` only when managed dependencies are intentionally not part of the behavior under test.
