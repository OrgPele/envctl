# envctl 1.7.7

`envctl` 1.7.7 is a hotfix release on top of `1.7.6`. It polishes the interactive dashboard service/dependency controls and fixes the errors inspection path so warning/error log lines from otherwise-running services are surfaced headlessly and interactively.

## Fixed

- Interactive `s` / `stop` now opens a concrete services/dependencies selector instead of colliding with AI session listing behavior.
- Interactive `k` / `kill` is now the AI/tmux session action, while service/dependency stopping remains under `stop`.
- Stopping one backend/frontend service or an entire worktree keeps stopped backend/frontend rows visible in the dashboard as `not running [Stopped]` instead of disappearing from the project shape.
- `r` / `restart` can start dashboard-stopped backend/frontend rows through the same concrete resource selector without terminating an already-running sibling service.
- Normal startup (`envctl`) now treats saved dashboard-stopped services as work to restore, so rerunning envctl after a partial stop starts the stopped service types instead of silently resuming the partial state.
- `errors` now scans recent service logs for warning/error/failure keywords. Running services with log issues such as `level=WARNING ... ModuleNotFoundError ...` no longer report `No known service errors.`
- Headless `errors --json` now includes a `log_issues` array so automation can detect warning/error log lines without relying on terminal text.
- Direct Codex prompt resolution now preserves real launch arguments even when an installed envctl Codex skill already contains the generated `$ARGUMENTS` sentinel text; literal prose mentions of `$ARGUMENTS` remain untouched.

## Changed

- AI/tmux sessions are shown inline under the matching worktree/project with a ready-to-copy `tmux attach-session ...` command; the old session-listing flow is replaced with inline visibility.
- Inline AI session rows no longer use the stopped-resource `○` glyph, so attach hints do not look like stopped services.
- Dashboard footer copy now distinguishes lifecycle service/dependency controls from AI-session kill controls.
- The stop/restart selector is easier to scan:
  - single worktree selectors include an **All resources** shortcut and concise rows such as `Backend — Main (service)` and `redis (dependency)`;
  - multi-worktree selectors group resources under worktree sections;
  - `a` selects all visible resources;
  - the advanced custom selector row was removed from this dashboard flow.
- Inspect commands that can print substantial output (`logs`, `errors`, `health`, `clear-logs`) pause with an explicit manual-confirmation prompt before repainting the interactive dashboard.
- Human log/error output highlights warning/error/failure keywords while JSON output remains uncolored and machine-readable.

## Why This Release Matters

This hotfix focuses on operator trust in the dashboard. Stopping services and killing AI sessions are now separate actions with clearer labels, stopped resources remain visible, restart can recover exactly what was stopped, and `errors` surfaces the log problems operators already saw under `logs`.

For Supportopia-shaped apps, this specifically addresses the case where a backend is running but logs a warning such as missing optional content dependencies. `logs` highlighted the warning, and now `errors` reports it too in both interactive and headless modes.

## Validation

Validated in the implementation worktree with:

- `./.venv/bin/python -m pytest tests/python/ui/test_dashboard_orchestrator_restart_selector.py tests/python/ui/test_terminal_ui_dashboard_loop.py tests/python/runtime/test_engine_runtime_runtime_support.py tests/python/state/test_state_action_orchestrator_logs.py -q` → 101 passed, 8 subtests passed.
- `./.venv/bin/python -m pytest tests/python/ui/test_dashboard_orchestrator_restart_selector.py tests/python/startup/test_startup_spinner_integration.py tests/python/startup/test_startup_orchestrator_profiles.py -q` → 82 passed, 8 subtests passed.
- `./.venv/bin/python -m pytest tests/python/ui tests/python/startup/test_startup_spinner_integration.py tests/python/startup/test_startup_orchestrator_profiles.py tests/python/runtime/test_lifecycle_cleanup_spinner_integration.py tests/python/runtime/test_cli_router_parity.py -q` → 403 passed, 17 subtests passed.
- `./.venv/bin/python -m pytest tests/python/startup -q` → 83 passed.
- `./.venv/bin/python -m pytest tests/python/state/test_state_action_orchestrator_logs.py tests/python/runtime/test_command_exit_codes.py -q` → 45 passed.
- `./.venv/bin/python -m pytest tests/python/runtime/test_prompt_install_support.py::PromptInstallSupportTests::test_resolve_codex_direct_prompt_body_replaces_installed_skill_argument_sentinel tests/python/runtime/test_prompt_install_support.py::PromptInstallSupportTests::test_resolve_codex_direct_prompt_body_supports_create_plan_auto_codex tests/python/runtime/test_prompt_install_support.py::PromptInstallSupportTests::test_resolve_opencode_direct_prompt_body_supports_create_plan_auto_opencode tests/python/runtime/test_prompt_install_support.py::PromptInstallSupportTests::test_resolve_codex_direct_prompt_body_only_replaces_standalone_arguments_placeholder tests/python/runtime/test_prompt_install_support.py::PromptInstallSupportTests::test_resolve_opencode_direct_prompt_body_renders_arguments_once -q` → 5 passed.
- Headless CLI smoke against a disposable runtime/state:
  - `envctl errors --headless --main` reported `Main Backend: log issues (...)` and exited `1` without interactive prompts.
  - `envctl errors --headless --main --json` returned `ok: false` with `log_issues` and exited `1`.
  - `envctl logs --headless --main --all --logs-tail 2` printed logs without interactive prompts.
  - `envctl dashboard --headless --main` printed a snapshot without an interactive command prompt.

Release-candidate validation for this version additionally ran:

- `./.venv/bin/python -m pytest tests/python/runtime/test_prompt_install_support.py tests/python/runtime/test_launcher_version.py tests/python/runtime/test_cli_packaging.py tests/python/runtime/test_release_shipability_gate.py tests/python/runtime/test_release_shipability_gate_cli.py -q` → 89 passed, 12 skipped, 10 subtests passed.
- `./.venv/bin/python -m pytest -q` → 1853 passed, 12 skipped, 4 warnings, 138 subtests passed.
- `./.venv/bin/python scripts/release_shipability_gate.py --repo . --check-tests` → `shipability.passed: true`.
- `./.venv/bin/python -m build` → built `dist/envctl-1.7.7-py3-none-any.whl` and `dist/envctl-1.7.7.tar.gz`.

## Artifacts

This release publishes:

- wheel distribution
- source distribution
- release notes markdown asset

## Upgrade Notes

- No `.envctl` changes are required.
- Existing runtime commands keep working.
- Use `errors --headless --json` when automation needs machine-readable failed service, dependency, run-failure, and recent log-issue summaries.
