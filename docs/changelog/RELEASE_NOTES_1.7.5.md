# envctl 1.7.5

`envctl` 1.7.5 is a hotfix release on top of `1.7.4`. It fixes a main-mode resume regression where explicitly running `envctl --main` was parsed as if the user had also requested `--no-resume`, causing repeated runs to start fresh backend/frontend app processes instead of reusing the valid main run state.

## Fixed

- `--main`, `--main=true`, `main=true`, and `MAIN=true` now select main mode without implicitly setting `no_resume`.
- `--tree=false` / `--trees=false` forced-main tokens also keep auto-resume eligible instead of forcing a fresh run.
- Explicit fresh-start flags still work: `--no-resume` and `--no-auto-resume` remain the supported opt-out for auto-resume.
- Strict mode-matched state lookup is preserved, so `envctl --main` still cannot resume a trees-mode state.

## Why This Hotfix Matters

Supportopia-shaped repos hit the regression after the 1.7.4 dependency-container hotfixes were installed: dependency containers were reused/adopted correctly, but backend/frontend application services were relaunched on new ports because run reuse was skipped with `reason=auto_resume_disabled`.

With 1.7.5, repeated `envctl --main` runs against a compatible main state resume the same run id and reuse the existing backend/frontend service URLs. Operators who truly want a fresh start should run `envctl --main --no-resume`.

## Validation

Validated in the implementation worktree with:

- `./.venv/bin/python -m pytest tests/python/runtime/test_command_policy_contract.py tests/python/runtime/test_cli_router_parity.py tests/python/runtime/test_engine_runtime_real_startup.py::EngineRuntimeRealStartupTests::test_explicit_main_start_auto_resumes_matching_main_state -q` failed before implementation for the expected `no_resume` / fresh-start reasons.
- `./.venv/bin/python -m ruff check python/envctl_engine/runtime/command_policy.py tests/python/runtime/test_command_policy_contract.py tests/python/runtime/test_cli_router_parity.py tests/python/runtime/test_engine_runtime_real_startup.py`
- `./.venv/bin/python -m pytest tests/python/runtime/test_command_policy_contract.py tests/python/runtime/test_cli_router_parity.py tests/python/runtime/test_command_router_contract.py tests/python/runtime/test_engine_runtime_startup_support.py tests/python/runtime/test_engine_runtime_env.py tests/python/runtime/test_engine_runtime_real_startup.py -q` → 204 passed, 6 subtests passed.
- `./.venv/bin/python -m pytest tests/python -q` → 1829 passed, 12 skipped, 4 warnings, 138 subtests passed.
- `ENVCTL_USE_REPO_WRAPPER=1 ./bin/envctl --repo /root/projects/supportopia explain-startup --main --json` showed `auto_resume.eligible=true` and `run_reuse.decision_kind=resume_exact`.
- Repeated `ENVCTL_USE_REPO_WRAPPER=1 ./bin/envctl --repo /root/projects/supportopia --main --batch` resumed `run-20260427161942-3f38297e` and did not increase the running app process count once services were live.

## Artifacts

This release publishes:

- wheel distribution
- source distribution
- release notes markdown asset

## Upgrade Notes

- No `.envctl` changes are required.
- Use `envctl --main` for normal main-mode resume behavior.
- Use `envctl --main --no-resume` when you intentionally want to bypass auto-resume and start fresh.
