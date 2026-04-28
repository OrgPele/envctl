# envctl 1.7.10

`envctl` 1.7.10 is a hotfix release on top of `1.7.9`. It ships the merged dashboard and plan-agent launch fixes that make AI session startup predictable again, especially for OpenCode and worktree-only flows.

## Fixed

- Worktree dashboard `Run AI:` guidance now uses the repo-scoped plan launch command shape instead of the stale `codex-tmux --omx` form.
- OpenCode plan launches now default to the `/ulw-loop` workflow command and use the hyphenated command spelling expected by OpenCode.
- Plan-agent tmux launch handling now attaches or reuses the intended session instead of dropping back into the dashboard when a session should be opened.
- Plan-agent startup now shows progress while tmux/OpenCode sessions are launching, reducing silent waits during cold starts.

## Added

- `--only-backend` launches just the backend app side for worktree/plan runs and skips frontend, managed dependencies, and dependency prep.
- `--only-frontend` launches just the frontend app side for worktree/plan runs and skips backend, managed dependencies, and dependency prep.
- `--no-deps` and `--no-infra` provide explicit dependency-free and infrastructure-free launch controls for AI/session workflows.
- The `create_plan` prompt family now infers the smallest safe envctl launch scope and includes the matching flags in follow-up commands.

## Changed

- Dashboard AI rows continue to show attach commands for existing AI sessions, but show a correct OpenCode plan launch command when no session exists.
- Single-side launch flags are dependency-free by design; use `--backend` or `--frontend` when you intentionally want the dependency-inclusive runtime scope.
- Plan-agent dependency bootstrap skips cleanly when dependency launch is disabled, including setup hooks and Docker prereq checks.

## Why This Release Matters

This hotfix removes the confusing path where envctl could display an obsolete Codex/OMX command, fail to attach to the expected AI session, or start unnecessary infrastructure for a narrow AI-assisted task. Operators can now start OpenCode-backed worktree sessions with the command shown by the dashboard, choose backend-only or frontend-only launches without bringing up dependencies, and see launch progress while tmux sessions are being prepared.

## Validation

Release-candidate validation for this version ran:

- `./.venv/bin/python -m pytest tests/python/runtime/test_cli_router_parity.py tests/python/runtime/test_prereq_policy.py tests/python/runtime/test_prompt_install_support.py tests/python/runtime/test_engine_runtime_command_parity.py tests/python/runtime/test_engine_runtime_real_startup.py tests/python/runtime/test_codex_tmux_support.py tests/python/startup/test_hooks_bridge.py tests/python/startup/test_startup_orchestrator_profiles.py tests/python/startup/test_startup_orchestrator_flow.py tests/python/ui/test_dashboard_rendering_parity.py tests/python/runtime/test_cli_packaging.py -q` → 396 passed, 12 skipped, 82 subtests passed
- `PYTHONPATH=python ./.venv/bin/python -m compileall -q python tests` → passed
- `git diff --check` → passed
- `./.venv/bin/python scripts/release_shipability_gate.py --repo . --skip-tests` → `shipability.passed: true`
- `./.venv/bin/python -m build` → built `dist/envctl-1.7.10-py3-none-any.whl` and `dist/envctl-1.7.10.tar.gz`

## Artifacts

This release publishes:

- wheel distribution: `envctl-1.7.10-py3-none-any.whl`
- source distribution: `envctl-1.7.10.tar.gz`
- release notes markdown asset: `RELEASE_NOTES_1.7.10.md`

## Upgrade Notes

- No `.envctl` config migration is required.
- Replace any local use of the brief-lived `--no-backend` / `--no-frontend` wording with `--only-frontend` / `--only-backend` respectively.
- Use `--backend` or `--frontend` when dependencies should still start; use `--only-backend` or `--only-frontend` when they should not.
