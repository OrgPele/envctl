# Envctl Migrate Output Deduplication, Success Visibility, and Spinner Parity

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Make `migrate` failures concise and high-signal instead of leading with low-value traceback chrome or repeating raw details across multiple surfaces.
  - Surface successful targets when one or more targets fail in a multi-target migration run, especially in dashboard-interactive mode where transient `ui.status` lines are not preserved after the command completes.
  - Give migrate the same practical spinner/progress quality bar as the better action paths in this repo by making one spinner owner show meaningful per-target progress instead of a static start/end wrapper.
  - Preserve raw failure artifacts and existing env-resolution metadata so operators can still inspect the full migrate log when needed.
- Non-goals:
  - Changing backend env resolution, Alembic command selection, or report file locations in [`python/envctl_engine/actions/action_command_orchestrator.py`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/action_command_orchestrator.py).
  - Reworking the Textual dashboard widget structure in [`python/envctl_engine/ui/textual/app.py`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/ui/textual/app.py); this issue is in action execution, state metadata, and legacy dashboard rendering.
  - Changing raw persisted migrate report contents written by [`ActionCommandOrchestrator._write_project_action_failure_report(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/action_command_orchestrator.py).
  - Introducing a second competing spinner for the same migrate command path.
- Assumptions:
  - The pasted user example came from dashboard-interactive usage, because the output shape matches the interactive command flow in [`python/envctl_engine/ui/command_loop.py`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/ui/command_loop.py) plus post-dispatch failure rendering in [`python/envctl_engine/ui/dashboard/orchestrator.py`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/ui/dashboard/orchestrator.py).
  - The desired acceptance target is human-facing terminal UX, not JSON output or `show-state --json` schema changes beyond additive metadata if implementation needs it.

## Goal (user experience)
When an operator runs `migrate`, envctl should show one concise progress surface while the command is running, then print a compact result summary that covers every selected target. On failure, the summary should lead with the actionable exception headline, not `Traceback (most recent call last):`, and it should include the failure-log path once. On mixed-result runs, successful targets should still be visible. Operators should never lose the full raw report, but they should not need to read or copy a traceback wall just to understand what failed.

## Business logic and data model mapping
- Command routing and migrate ownership:
  - [`python/envctl_engine/runtime/engine_runtime.py:_run_migrate_action`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/runtime/engine_runtime.py#L1064)
  - [`python/envctl_engine/actions/action_command_orchestrator.py:ActionCommandOrchestrator.run_migrate_action`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/action_command_orchestrator.py#L471)
  - [`python/envctl_engine/actions/action_target_support.py:execute_targeted_action`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/action_target_support.py#L49)
- Persisted action metadata:
  - [`python/envctl_engine/state/models.py:RunState`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/state/models.py#L104)
  - `RunState.metadata["project_action_reports"][project]["migrate"]`
  - [`python/envctl_engine/actions/action_command_orchestrator.py:_persist_project_action_result`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/action_command_orchestrator.py#L970)
- Failure-summary generation and rendering:
  - [`python/envctl_engine/actions/action_command_orchestrator.py:_project_action_failure_summary_lines`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/action_command_orchestrator.py#L1601)
  - [`python/envctl_engine/actions/action_command_orchestrator.py:_format_summary_error_lines`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/action_command_orchestrator.py#L1742)
  - [`python/envctl_engine/actions/action_command_orchestrator.py:_structured_summary_lines`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/action_command_orchestrator.py#L1812)
  - [`python/envctl_engine/ui/dashboard/orchestrator.py:_print_project_action_failure_details`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/ui/dashboard/orchestrator.py#L307)
- Spinner/progress ownership:
  - [`python/envctl_engine/actions/action_command_orchestrator.py:ActionCommandOrchestrator.execute`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/action_command_orchestrator.py#L188)
  - [`python/envctl_engine/actions/action_command_orchestrator.py:_emit_status`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/action_command_orchestrator.py#L927)
  - [`python/envctl_engine/ui/command_loop.py:_install_spinner_event_bridge`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/ui/command_loop.py#L433)
  - [`python/envctl_engine/shared/process_runner.py:ProcessRunner.run`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/shared/process_runner.py#L66)
  - [`python/envctl_engine/shared/process_runner.py:ProcessRunner.run_streaming`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/shared/process_runner.py#L136)
- Existing user-facing test references:
  - [`tests/python/actions/test_action_target_support.py`](/Users/kfiramar/projects/current/envctl/tests/python/actions/test_action_target_support.py)
  - [`tests/python/actions/test_actions_parity.py`](/Users/kfiramar/projects/current/envctl/tests/python/actions/test_actions_parity.py)
  - [`tests/python/actions/test_action_spinner_integration.py`](/Users/kfiramar/projects/current/envctl/tests/python/actions/test_action_spinner_integration.py)
  - [`tests/python/ui/test_dashboard_orchestrator_restart_selector.py`](/Users/kfiramar/projects/current/envctl/tests/python/ui/test_dashboard_orchestrator_restart_selector.py)
  - [`tests/python/ui/test_terminal_ui_dashboard_loop.py`](/Users/kfiramar/projects/current/envctl/tests/python/ui/test_terminal_ui_dashboard_loop.py)
  - [`tests/python/shared/test_process_runner_spinner_integration.py`](/Users/kfiramar/projects/current/envctl/tests/python/shared/test_process_runner_spinner_integration.py)
- Relevant config/env and docs:
  - [`docs/reference/configuration.md`](/Users/kfiramar/projects/current/envctl/docs/reference/configuration.md) for `ENVCTL_UI_SPINNER_MODE`, `ENVCTL_UI_SPINNER`, `ENVCTL_UI_SPINNER_MIN_MS`, `ENVCTL_UI_RICH`, and `ENVCTL_UI_HYPERLINK_MODE`
  - [`docs/reference/commands.md`](/Users/kfiramar/projects/current/envctl/docs/reference/commands.md) for the current `migrate` contract
  - [`docs/operations/troubleshooting.md`](/Users/kfiramar/projects/current/envctl/docs/operations/troubleshooting.md) for current migrate-failure troubleshooting guidance

## Current behavior (verified in code)
- Migrate target execution is currently linearly executed through [`execute_targeted_action(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/action_target_support.py#L49).
  - The helper returns only a command-level exit code.
  - It does not return a structured per-target result list to the caller.
  - Success and failure are emitted as transient status strings, but only failures are later re-rendered after dashboard dispatch.
- Interactive migrate failure status uses the full raw subprocess error, not a concise headline.
  - In [`execute_targeted_action(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/action_target_support.py#L49), interactive failures call `emit_status(f"{command_name} failed for {context.name}: {error}")`.
  - For migrate, `interactive_print_failures=False`, so the raw error is suppressed from direct `print(...)` but still sent into the status/event path.
  - That means the spinner-driven surface can receive the entire traceback even though envctl later prints a second, more curated failure block.
- Dashboard post-dispatch rendering only prints failures.
  - [`DashboardOrchestrator._print_interactive_failure_details(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/ui/dashboard/orchestrator.py#L191) calls [`_print_project_action_failure_details(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/ui/dashboard/orchestrator.py#L307).
  - [`_print_project_action_failure_details(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/ui/dashboard/orchestrator.py#L307) iterates failed `project_action_reports` entries only and never prints successful target results.
  - Successful migrate targets are therefore visible only as transient `ui.status` updates during execution.
- Persisted migrate success entries are minimal.
  - [`_persist_project_action_result(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/action_command_orchestrator.py#L970) stores `status="success"` and `updated_at`, and stores failure-only `summary`/`report_path`.
  - This is enough to know that a target succeeded, but no interactive summary currently consumes those entries.
- The current failure headline selection is low-signal for dashboard output.
  - [`_structured_summary_lines(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/action_command_orchestrator.py#L1812) intentionally places `Traceback (most recent call last):` first when a traceback exists.
  - [`_print_project_action_failure_details(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/ui/dashboard/orchestrator.py#L307) prints the first summary line as the headline and then only the `hint:` lines plus the report path.
  - Result: the operator often sees `migrate failed for <target>: Traceback (most recent call last):` instead of the actual exception body.
- Action-command spinner coverage is static, not progress-aware.
  - [`ActionCommandOrchestrator.execute(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/action_command_orchestrator.py#L188) starts an action-level spinner and emits lifecycle events, but it does not bridge later [`_emit_status(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/action_command_orchestrator.py#L927) messages back into `active_spinner.update(...)`.
  - By contrast, the dashboard command loop explicitly installs a status-to-spinner bridge in [`_install_spinner_event_bridge(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/ui/command_loop.py#L433), and the tests in [`tests/python/ui/test_terminal_ui_dashboard_loop.py`](/Users/kfiramar/projects/current/envctl/tests/python/ui/test_terminal_ui_dashboard_loop.py) lock that behavior down.
  - Result: direct CLI action spinners stay on their initial message until success/fail.
- Migrate uses the non-streaming subprocess path.
  - [`run_migrate_action(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/action_command_orchestrator.py#L471) passes `rt.process_runner.run(...)` into [`execute_targeted_action(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/action_target_support.py#L49).
  - Unlike the review streaming branch in [`run_project_action(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/action_command_orchestrator.py#L723), migrate does not use [`ProcessRunner.run_streaming(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/shared/process_runner.py#L136) and therefore has no subprocess-owned spinner/progress surface.
- Existing tests prove some pieces, but not the user-reported gaps.
  - [`tests/python/actions/test_action_target_support.py`](/Users/kfiramar/projects/current/envctl/tests/python/actions/test_action_target_support.py) proves that interactive migrate suppresses direct failure printing but still emits `migrate failed for Main: ...` into status.
  - [`tests/python/actions/test_actions_parity.py`](/Users/kfiramar/projects/current/envctl/tests/python/actions/test_actions_parity.py) covers migrate env contracts and failure summary persistence, but not mixed-result interactive summaries or failure-headline ranking.
  - [`tests/python/actions/test_action_spinner_integration.py`](/Users/kfiramar/projects/current/envctl/tests/python/actions/test_action_spinner_integration.py) covers only start/success/fail lifecycle for action spinners, not progress updates.
  - [`tests/python/ui/test_dashboard_orchestrator_restart_selector.py`](/Users/kfiramar/projects/current/envctl/tests/python/ui/test_dashboard_orchestrator_restart_selector.py) covers one failed migrate target, not multi-target success visibility.

## Root cause(s) / gaps
- The project-action execution helper mixes two different concerns into one failure string:
  - raw error payload for persistence/debugging
  - user-facing status text for the spinner and dashboard flow
- The persisted migrate summary is optimized for retention, but the dashboard printer is optimized for the first line only.
  - That combination makes `Traceback...` the visible headline.
- Dashboard post-dispatch reporting is failure-only.
  - Mixed success/failure migrate runs lose successful targets once transient spinner/status updates disappear.
- Action-level spinner infrastructure exists, but there is no bridge from `ui.status` to `active_spinner.update(...)`.
  - Tests use richer spinner patterns because test execution has dedicated progress plumbing; migrate does not.
- Migrate has no structured per-target outcome object.
  - Without an ordered result list, later rendering relies on persisted state snapshots rather than a single explicit command result contract.

## Plan
### 1) Separate raw failure capture from operator-facing migrate status text
- Extend [`python/envctl_engine/actions/action_target_support.py:execute_targeted_action`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/action_target_support.py#L49) so callers can provide a concise status formatter for failures without losing the raw `error` string passed to `on_failure(...)`.
- Keep raw error assembly unchanged for persistence/report writing.
- For `migrate`, the operator-facing failure status should prefer a concise headline derived from the persisted-summary helper rather than the full multiline traceback.
- Preserve current behavior for `pr`, `commit`, and `review` unless repo evidence during implementation shows they benefit from the same split with no UX regression.

### 2) Introduce a migrate failure-headline helper that prefers the exception body over traceback chrome
- Add a dedicated helper in [`python/envctl_engine/actions/action_command_orchestrator.py`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/action_command_orchestrator.py) that turns stored summary lines into:
  - one concise headline
  - zero or more bounded hint lines
- The helper should explicitly skip low-value lead lines such as:
  - `Traceback (most recent call last):`
  - stack-frame lines beginning with `File "..."` when a later exception line exists
  - captured-output headers that are not the actionable error
- Prefer the terminal exception body when present, for example `alembic.util.exc.CommandError: ...` or `ValidationError: ...`.
- Reuse this helper in both:
  - persisted failure metadata if implementation stores an additive `headline` field
  - dashboard-interactive rendering in [`python/envctl_engine/ui/dashboard/orchestrator.py`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/ui/dashboard/orchestrator.py)
- Keep the raw failure report file unchanged and keep the existing hint-generation paths (`_migrate_failure_hint_lines`, `_migrate_env_source_hint_lines`) additive and deduplicated.

### 3) Add a post-run migrate result summary that includes successes as well as failures
- Replace the failure-only rendering path in [`DashboardOrchestrator._print_project_action_failure_details(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/ui/dashboard/orchestrator.py#L307) with a migrate-aware result-summary helper that iterates the selected targets in route order and prints:
  - `✓ migrate succeeded for <target>` for successes
  - `✗ migrate failed for <target>: <headline>` for failures
  - bounded `hint:` lines only for failed targets
  - one clickable report path block per failed target when `report_path` exists
- Keep non-migrate project actions on their current behavior unless implementation can generalize the helper without widening scope.
- Use existing `RunState.metadata["project_action_reports"]` success entries first; do not require a breaking schema change.
- Edge cases to handle explicitly:
  - all-success multi-target runs should still print one concise result block so the operator sees every completed target
  - targets missing from persisted action metadata should not crash rendering; print only what envctl can verify and keep the existing generic fallback if nothing is available
  - multiple failures should produce one report path block per failed target, not one merged path dump

### 4) Add one shared action-spinner status bridge instead of introducing nested spinners
- Extract the status-to-spinner update pattern already proven in [`python/envctl_engine/ui/command_loop.py:_install_spinner_event_bridge`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/ui/command_loop.py#L433) into an action-usable helper or add an action-local equivalent in [`python/envctl_engine/actions/action_command_orchestrator.py`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/action_command_orchestrator.py).
- Use that bridge inside [`ActionCommandOrchestrator.execute(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/action_command_orchestrator.py#L188) so action-level spinners can update from later [`_emit_status(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/action_command_orchestrator.py#L927) messages.
- Preserve the current rule that dashboard-interactive commands suppress the nested action spinner and let the command-loop spinner remain the single owner in that mode.
- Do not add a second generic subprocess spinner for migrate unless implementation proves the action-level bridge cannot satisfy direct CLI progress needs; the default should remain one spinner owner per visible command path.

### 5) Make migrate emit bounded progress messages that are useful for both the dashboard spinner and direct CLI action spinner
- Adjust migrate status emissions in [`execute_targeted_action(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/action_target_support.py#L49) and/or [`run_migrate_action(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/action_command_orchestrator.py#L471) so the spinner can show meaningful target-level progress, for example:
  - `Running migrate for feature-a-1 (1/4)...`
  - `migrate succeeded for feature-a-1`
  - `migrate failed for feature-b-1: <headline>`
- Keep these messages single-line and bounded.
- Avoid emitting the full raw traceback into `ui.status`.
- Preserve per-target ordering and counts so direct CLI spinners and dashboard-command spinners both reflect the same progress contract.

### 6) Keep stored action metadata and dashboard rendering aligned
- If implementation adds an additive failure `headline` field to [`project_action_reports`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/state/models.py#L104), make the dashboard renderer prefer it over reparsing `summary`.
- If implementation chooses not to store `headline`, centralize summary parsing in one shared helper so state persistence and rendering cannot drift.
- Continue storing:
  - `status`
  - `updated_at`
  - `report_path` for failures
  - `backend_env` migrate metadata when available
- No data migration or backfill is needed; old entries can fall back to reparsing `summary`.

### 7) Extend tests around the exact UX gaps instead of broad rewrites
- Start with narrow unit-style tests for failure-headline extraction and spinner status bridging.
- Then add dashboard-interactive mixed-result coverage for `migrate`.
- Only touch shared process-runner spinner tests if implementation genuinely moves migrate onto [`run_streaming(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/shared/process_runner.py#L136); do not expand that suite unnecessarily if the final design keeps action-level spinner ownership.

## Tests (add these)
### Backend tests
- Extend [`tests/python/actions/test_action_target_support.py`](/Users/kfiramar/projects/current/envctl/tests/python/actions/test_action_target_support.py):
  - interactive migrate failure status uses a concise headline formatter instead of the full raw multiline error
  - raw combined stdout/stderr payload still reaches `on_failure(...)`
  - multi-target execution preserves ordered result collection if implementation introduces a returned result object
- Extend [`tests/python/actions/test_actions_parity.py`](/Users/kfiramar/projects/current/envctl/tests/python/actions/test_actions_parity.py):
  - dashboard-style migrate summary prefers the actionable exception line over `Traceback (most recent call last):`
  - interactive mixed-result migrate run across multiple targets reports both successes and failures
  - failed targets still persist `report_path` and env metadata
  - all-success multi-target migrate run produces visible success lines instead of silent completion
- Extend [`tests/python/actions/test_action_spinner_integration.py`](/Users/kfiramar/projects/current/envctl/tests/python/actions/test_action_spinner_integration.py):
  - action spinner updates from later status events, not only start/success/fail
  - migrate/action spinner still stays disabled for `interactive_command=True`
- Extend [`tests/python/ui/test_dashboard_orchestrator_restart_selector.py`](/Users/kfiramar/projects/current/envctl/tests/python/ui/test_dashboard_orchestrator_restart_selector.py):
  - multi-target interactive migrate with mixed success/failure prints one concise result block in route order
  - failure headline does not start with `Traceback (most recent call last):`
  - failure log path prints once per failed target
  - duplicate hint lines are not repeated
- Extend [`tests/python/ui/test_terminal_ui_dashboard_loop.py`](/Users/kfiramar/projects/current/envctl/tests/python/ui/test_terminal_ui_dashboard_loop.py) if needed:
  - migrate command-loop spinner reflects concise status updates from action execution without showing full traceback text
- Extend [`tests/python/shared/test_process_runner_spinner_integration.py`](/Users/kfiramar/projects/current/envctl/tests/python/shared/test_process_runner_spinner_integration.py) only if implementation changes migrate to [`run_streaming(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/shared/process_runner.py#L136).

### Frontend tests
- No browser/frontend tests are required.
- The only UI coverage needed is Python terminal/dashboard rendering in:
  - [`tests/python/ui/test_dashboard_orchestrator_restart_selector.py`](/Users/kfiramar/projects/current/envctl/tests/python/ui/test_dashboard_orchestrator_restart_selector.py)
  - [`tests/python/ui/test_terminal_ui_dashboard_loop.py`](/Users/kfiramar/projects/current/envctl/tests/python/ui/test_terminal_ui_dashboard_loop.py)

### Integration/E2E tests
- Manual verification in a real TTY:
  1. Start envctl in dashboard-interactive mode with at least four migrate targets and force one failure.
  2. Run `migrate` from the dashboard and confirm the spinner shows bounded per-target progress, not a static message.
  3. Confirm the final output prints every target result, including the successful ones.
  4. Confirm failed targets lead with the actual exception headline and include exactly one failure-log path block each.
  5. Run direct CLI `envctl migrate --all` in a TTY and confirm the action-level spinner updates as targets advance.
  6. Inspect `envctl show-state --json` and confirm raw failure report paths and backend env metadata remain intact.

## Observability / logging (if relevant)
- Reuse existing `ui.status`, `ui.spinner.lifecycle`, and `action.command.finish` events as the primary transport.
- If implementation needs more structure, add one bounded per-target event such as `action.command.target.result` with:
  - `command`
  - `project`
  - `status`
  - `index`
  - `total`
  - `report_path_present`
- Do not emit raw traceback payloads into new bounded events.
- Continue writing the full raw migrate subprocess output only to the persisted failure report file.

## Rollout / verification
- Implementation order:
  1. add failure-headline/status-format helpers and unit tests
  2. wire migrate execution to use concise status text while preserving raw failure persistence
  3. add dashboard migrate result-summary rendering for mixed success/failure runs
  4. add action-level spinner status bridging for non-interactive CLI action execution
  5. run focused tests, then real-TTY verification
- Verification commands:
  - `PYTHONPATH=python python3 -m unittest tests.python.actions.test_action_target_support`
  - `PYTHONPATH=python python3 -m unittest tests.python.actions.test_action_spinner_integration`
  - `PYTHONPATH=python python3 -m unittest tests.python.actions.test_actions_parity`
  - `PYTHONPATH=python python3 -m unittest tests.python.ui.test_dashboard_orchestrator_restart_selector`
  - `PYTHONPATH=python python3 -m unittest tests.python.ui.test_terminal_ui_dashboard_loop`
- No data migration, cleanup job, or backfill is required.

## Definition of done
- Interactive migrate failures no longer lead with `Traceback (most recent call last):` when a better exception headline is available.
- Mixed-result multi-target migrate runs show successful targets as well as failed ones.
- Direct CLI action spinners for migrate update meaningfully during execution instead of staying static until completion.
- Dashboard-interactive migrate still uses one spinner owner and does not render duplicate spinner/output surfaces.
- Raw persisted failure reports and existing backend env metadata remain available and unchanged in purpose.
- Automated coverage locks the new headline-selection, mixed-result rendering, and spinner-update behavior.

## Risk register (trade-offs or missing tests)
- Risk: changing failure-headline ranking in shared summary code could unintentionally alter non-migrate action output.
  - Mitigation: scope the new headline logic to migrate or to dashboard/action rendering helpers unless broader reuse is explicitly verified.
- Risk: adding spinner status bridging at the action layer could create duplicate updates in dashboard-interactive mode.
  - Mitigation: preserve the current `interactive_command` spinner suppression and reuse the command-loop spinner as the single owner there.
- Risk: relying on persisted `project_action_reports` for mixed-result summaries can miss targets if persistence fails mid-run.
  - Mitigation: keep a generic fallback when no action metadata is available and prefer ordered route-target iteration in the renderer.
- Risk: storing additive metadata such as `headline` could create old/new entry drift.
  - Mitigation: make the renderer backward-compatible by reparsing `summary` when additive fields are absent.

## Open questions (only if unavoidable)
- None. Repo evidence is sufficient to define the implementation plan without further requirements input.
