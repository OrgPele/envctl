# 2026-03-16

## Scope
- Restored release-cleanliness checks across shipability, runtime readiness, direct-inspection command routing, selector focus behavior, and repo-level static validation.
- Tightened the release-gate CLI smoke contract so success/failure semantics are asserted instead of only argument acceptance.
- Cleared the repo-wide `ruff check python tests` failures and kept the full Python test suite green.

## Key behavior changes
- `python/envctl_engine/shell/release_gate.py`
  - Manifest freshness now accepts both `...Z` and offset-aware timestamps, compares them with a timezone-aware clock, and supports deterministic test clocks.
  - Documented `--repo` is treated as launcher-owned rather than a parser-gap failure.
- `python/envctl_engine/runtime/command_router.py`
  - `list-commands` and `list-targets` now resolve in bare-token form alongside their historical `--list-*` aliases.
- `python/envctl_engine/ui/textual/screens/selector/textual_app.py`
  - The selector filter can be focused by click and by `Tab`.
  - When the filter has focus, `Tab` cycles explicitly, and navigation/toggle keys recover back into list interaction instead of getting trapped in the input.
- `python/envctl_engine/ui/textual/screens/selector/textual_app_lifecycle.py`
  - Mount no longer disables filter focusability.
- `python/envctl_engine/ui/dashboard/pr_flow.py`
  - Removed the dead duplicate `on_key(...)` handler so one keyboard contract remains authoritative.
- `python/envctl_engine/actions/action_command_orchestrator.py`
  - Imported the missing `ActionTargetContext` annotation target and removed the dead interactive test-plan helper that referenced undefined state.
- `python/envctl_engine/startup/startup_execution_support.py`
  - Re-export ownership for `start_requirements_for_project` and `start_project_services` explicitly through the support module.
- `python/envctl_engine/startup/service_execution.py`
  - Replaced the inline `_command_env` lambda fallback with a named helper.

## Files touched
- Runtime and release gate:
  - `python/envctl_engine/shell/release_gate.py`
  - `python/envctl_engine/runtime/command_router.py`
  - `scripts/release_shipability_gate.py` (behavior covered by strengthened tests; no CLI flag addition was needed)
- UI and startup hot spots:
  - `python/envctl_engine/ui/textual/screens/selector/textual_app.py`
  - `python/envctl_engine/ui/textual/screens/selector/textual_app_lifecycle.py`
  - `python/envctl_engine/ui/dashboard/pr_flow.py`
  - `python/envctl_engine/actions/action_command_orchestrator.py`
  - `python/envctl_engine/startup/startup_execution_support.py`
  - `python/envctl_engine/startup/service_execution.py`
- Tests:
  - `tests/python/runtime/test_release_shipability_gate.py`
  - `tests/python/runtime/test_release_shipability_gate_cli.py`
  - `tests/python/runtime/test_cutover_gate_truth.py`
  - `tests/python/runtime/test_cli_router_parity.py`
  - `tests/python/runtime/test_cli_packaging.py`
  - `tests/python/ui/test_textual_selector_responsiveness.py`
  - `tests/python/actions/test_actions_cli.py`
- Docs:
  - `docs/reference/commands.md`
  - `docs/reference/important-flags.md`
  - `docs/user/python-engine-guide.md`
  - `docs/developer/testing-and-validation.md`
  - `todo/plans/README.md`

## Tests run
- `./.venv/bin/pytest -q tests/python/runtime/test_release_shipability_gate.py tests/python/runtime/test_release_shipability_gate_cli.py tests/python/runtime/test_cutover_gate_truth.py tests/python/runtime/test_cli_router_parity.py tests/python/runtime/test_cli_packaging.py tests/python/ui/test_textual_selector_responsiveness.py`
  - Result: `63 passed`
- `./.venv/bin/ruff check python tests`
  - Result: `All checks passed!`
- `./.venv/bin/pytest -q`
  - Result: `1325 passed, 7 warnings, 92 subtests passed`

## Config / env / migrations
- No persisted data migrations or backfills were required.
- No contract JSON regeneration was required for this slice; the checked-in contract timestamps remain valid after the timezone-safe freshness fix.
- A local repo `.venv` was created for validation only.

## Risks / notes
- The full pytest suite still emits the pre-existing `PytestCollectionWarning` warnings for dataclass-like helper classes under `python/envctl_engine/...`; they are warnings only and do not fail validation.
- Documentation now treats bare `list-*` commands as the primary spelling while keeping `--list-*` aliases as compatibility forms.

# 2026-03-16

## Scope
- Follow-up fix for the textual selector accessibility regression after restoring filter focus.
- Restored a complete `Tab` traversal path so selector dialogs no longer trap focus between only the list and filter.

## Key behavior changes
- `python/envctl_engine/ui/textual/list_controller.py`
  - Replaced the binary list/filter toggle helper with ordered focus traversal so selector screens can define an explicit tab loop.
- `python/envctl_engine/ui/textual/screens/selector/textual_app.py`
  - `Tab` now cycles `list -> filter -> cancel -> run -> list`.
  - Disabled action buttons are skipped instead of receiving focus.
- `python/envctl_engine/ui/textual/screens/planning_selector.py`
  - Planning mode now uses the same explicit focus order as the runtime selector.
  - When `Run` is disabled, `Tab` cycles `list -> filter -> cancel -> list`.

## Files touched
- `python/envctl_engine/ui/textual/list_controller.py`
- `python/envctl_engine/ui/textual/screens/selector/textual_app.py`
- `python/envctl_engine/ui/textual/screens/planning_selector.py`
- `tests/python/ui/test_textual_selector_shared_behavior.py`
- `tests/python/ui/test_textual_selector_responsiveness.py`

## Tests run
- `./.venv/bin/pytest -q tests/python/ui/test_textual_selector_shared_behavior.py tests/python/ui/test_textual_selector_responsiveness.py`
  - Result: `27 passed`
- `./.venv/bin/pytest -q tests/python/ui/test_textual_selector_shared_behavior.py tests/python/ui/test_textual_selector_responsiveness.py tests/python/planning/test_planning_textual_selector.py`
  - Result: `31 passed`

## Config / env / migrations
- No config, environment, or migration changes were required.

## Risks / notes
- The custom `Tab` loop is intentionally explicit to preserve access to the filter from the list while still including action buttons; if additional focusable controls are added to these screens later, their ids need to be added to the local focus-order helpers.

# 2026-03-16

## Scope
- Refined the selector `Tab` order to match the visible layout more closely after restoring button participation in the focus loop.

## Key behavior changes
- `python/envctl_engine/ui/textual/screens/selector/textual_app.py`
  - The runtime selector now tabs in visual order: `search -> list -> cancel -> run -> search`.
- `python/envctl_engine/ui/textual/screens/planning_selector.py`
  - Planning mode uses the same visual wrap order.
  - When `Run` is disabled, the loop becomes `search -> list -> cancel -> search`.

## Files touched
- `python/envctl_engine/ui/textual/screens/selector/textual_app.py`
- `python/envctl_engine/ui/textual/screens/planning_selector.py`
- `tests/python/ui/test_textual_selector_shared_behavior.py`
- `tests/python/ui/test_textual_selector_responsiveness.py`

## Tests run
- `./.venv/bin/pytest -q tests/python/ui/test_textual_selector_shared_behavior.py tests/python/ui/test_textual_selector_responsiveness.py tests/python/planning/test_planning_textual_selector.py`
  - Result: `31 passed`

## Config / env / migrations
- No config, environment, or migration changes were required.

## Risks / notes
- The tab order is still maintained explicitly in code, so any future focusable controls added to these dialogs need to be inserted into the local focus-order lists to participate in traversal.
