# envctl 1.7.8

`envctl` 1.7.8 is a hotfix release on top of `1.7.7`. It focuses on operator trust in plan/startup status output, test-run result tracking, and dashboard URLs used for visual inspection from another machine.

## Fixed

- Startup failures now render the final envctl-owned fatal line with the canonical failure glyph: `✗ Startup failed: ...`.
- The final startup failure glyph is red whenever terminal color is enabled, making hard failures stand out consistently in plan/startup output.
- Multi-worktree startup failures now append explicit source context, such as `(worktree: refactoring_repository_layout_cleanliness_consolidation-1)`, so the failing worktree is easier to identify from long service-manager messages.
- Envctl-owned terminal and dashboard status rows now share one status glyph contract instead of mixing legacy `+` / `!` prefixes with spinner final symbols.
- Mocked or wrapper test commands that print pytest/unittest failures but exit `0` are no longer reported as passing. Envctl reconciles parsed failure evidence with the raw process status before rendering `✓ PASSED` or returning success.

## Added

- `ENVCTL_UI_VISUAL_HOST` lets visual dashboard output display an IP address or hostname instead of `localhost`.
- The new setting defaults to `localhost` and is managed through `.envctl` / `envctl config --set ENVCTL_UI_VISUAL_HOST=<host>`.
- Dashboard-rendered service and dependency URLs use the visual host override for display only. Service binds, listener probes, app environment variables, persisted runtime maps, and non-visual runtime behavior remain unchanged.

## Changed

- Dashboard service/dependency badges, health output, action spinner events, lifecycle cleanup warnings, startup progress, and spinner fallbacks now route through shared success/failure/warning/neutral status semantics.
- Stopped/neutral states remain non-errors while failure states keep the canonical failure glyph and color policy.
- Configuration reference docs and `.envctl.example` document the dashboard-only visual host option.

## Why This Release Matters

This hotfix makes envctl's visible status output match the state operators need to act on. A failed plan-agent backend now shows a red `✗`, names the failing worktree, and keeps raw subprocess log content intact. Test automation also no longer trusts a false-success subprocess exit when parsed output proves failures occurred.

For remote or multi-device visual review, dashboards can now show reachable URLs such as `http://192.0.2.42:<port>` without changing where services bind or how envctl probes them.

## Validation

Validated in the implementation worktree before release prep with:

- `PYTHONPATH=python python3 -m unittest tests.python.ui.test_spinner_service tests.python.ui.test_status_symbols tests.python.ui.test_status_glyph_contract tests.python.ui.test_dashboard_rendering_parity tests.python.ui.test_dashboard_render_alignment tests.python.ui.test_textual_dashboard_rendering_safety tests.python.state.test_state_action_orchestrator_logs tests.python.ui.test_terminal_ui_dashboard_loop tests.python.startup.test_startup_spinner_integration tests.python.startup.test_startup_progress tests.python.startup.test_resume_progress tests.python.runtime.test_lifecycle_cleanup_spinner_integration tests.python.actions.test_action_spinner_integration tests.python.config.test_config_command_support` → 126 passed.
- `PYTHONPATH=python python3 -m unittest discover tests/python` → 1888 passed, 12 skipped.
- `PYTHONPATH=python python3 -m compileall -q python tests` → passed.
- `git diff --check` → passed.
- `.venv/bin/python -m ruff check` on changed Python files → passed; full-repo Ruff remains red from pre-existing unrelated E501 violations.
- Manual CLI E2E with a live local HTTP server and `.envctl` `ENVCTL_UI_VISUAL_HOST=192.0.2.42` rendered `Backend: http://192.0.2.42:<port>` and no `Backend: http://localhost:<port>`.

Release-candidate validation for this version additionally ran:

- `./.venv/bin/python -m pytest tests/python/runtime/test_launcher_version.py tests/python/runtime/test_cli_packaging.py tests/python/runtime/test_release_shipability_gate.py tests/python/runtime/test_release_shipability_gate_cli.py -q` → 53 passed, 12 skipped.
- `PYTHONPATH=python python3 -m compileall -q python tests` → passed.
- `git diff --check` → passed.
- `./.venv/bin/python scripts/release_shipability_gate.py --repo . --check-tests` → `shipability.passed: true`.
- `./.venv/bin/python -m pytest -q` → 1876 passed, 12 skipped, 4 warnings, 156 subtests passed.
- `./.venv/bin/python -m build` → built `dist/envctl-1.7.8-py3-none-any.whl` and `dist/envctl-1.7.8.tar.gz`.

## Artifacts

This release publishes:

- wheel distribution
- source distribution
- release notes markdown asset

## Upgrade Notes

- No `.envctl` changes are required.
- Existing dashboards continue to display `localhost` by default.
- To show an IP address or hostname in dashboard-visible URLs, set `ENVCTL_UI_VISUAL_HOST`, for example: `envctl config --set ENVCTL_UI_VISUAL_HOST=192.0.2.42`.
- The visual host setting is display-only; it does not expose services on a different network interface.
