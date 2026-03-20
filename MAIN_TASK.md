# Envctl Migrate Direct CLI Summary And Verification Closure

## Context and objective
The previous iteration completed the dashboard-interactive migrate UX improvements: interactive migrate status lines are now bounded, failed migrate entries persist an additive `headline`, dashboard-interactive migrate prints per-target results including successes, and the action-level spinner updates from `ui.status` events. Those changes landed in commit `9f7f38e fix(migrate): improve output summaries`.

The delivery is still incomplete against the prior task goal because the direct non-interactive CLI migrate path continues to print the old raw action failure wall instead of the compact per-target result summary described in the task, and there is no repo evidence that the required real-TTY verification was performed and recorded. This iteration must close those remaining gaps fully, end to end.

## Remaining requirements (complete and exhaustive)
1. Fully implement a compact post-run migrate result summary for direct non-interactive CLI execution.
   - This remaining scope applies to action-owned migrate execution where `interactive_command=False`.
   - After `envctl migrate ...` finishes, envctl must print one concise result block covering every selected target in route order.
   - The result block must use the same practical contract already implemented for dashboard-interactive rendering:
     - `✓ migrate succeeded for <target>` for successes
     - `✗ migrate failed for <target>: <headline>` for failures
     - bounded `hint:` lines only for failed targets
     - exactly one failure-log path block per failed target when `report_path` exists
   - Do not rely on transient spinner updates alone to communicate the final result.
2. Remove raw multiline migrate failure walls from the direct non-interactive CLI path.
   - During direct CLI execution, operators should not be forced to read `migrate action failed for <target>: Traceback...` with the full raw subprocess payload inline.
   - The operator-facing terminal output must lead with the actionable failure headline, not `Traceback (most recent call last):`.
   - Preserve the full raw subprocess output only in the persisted failure report file; do not discard or truncate the artifact.
3. Keep direct CLI progress and final summary aligned with persisted action metadata.
   - The implementation may reuse `RunState.metadata["project_action_reports"]`, return structured per-target results from `execute_targeted_action(...)`, or use another repo-consistent mechanism, but the final printed summary must stay consistent with persisted `status`, `summary`, `headline`, `report_path`, and `backend_env` metadata.
   - Mixed-result and all-success runs must both be handled without duplication.
   - Missing persisted entries must not crash output rendering; fall back gracefully and print only what envctl can verify.
4. Add automated coverage for the remaining direct CLI migrate UX gap.
   - Add or extend tests proving that direct non-interactive migrate output:
     - prints concise actionable failure headlines instead of traceback-led walls
     - prints per-target success and failure summary lines in route order
     - prints one report-path block per failed target
     - preserves persisted `report_path`, `headline`, and backend env metadata
     - still updates the action spinner meaningfully while the command is running
   - Match the existing test style and keep the tests as narrow as possible.
5. Complete and record the required real-TTY verification for the shipped migrate UX.
   - Run dashboard-interactive migrate with at least one forced failure across multiple targets and confirm:
     - one spinner owner
     - bounded per-target progress during execution
     - final output includes every target, including successes
     - failures lead with the actionable exception headline
     - each failed target prints exactly one failure-log path block
   - Run direct CLI `envctl migrate --all` in a real TTY and confirm:
     - the action-level spinner updates per target while execution is in progress
     - the final direct CLI output uses the new compact per-target result summary
     - raw traceback payloads remain available only through the persisted failure report file
   - Inspect `envctl show-state --json` after a failed migrate and confirm `report_path`, `backend_env`, and additive `headline` metadata remain intact.
   - Record the exact commands executed and the observed outcomes in the implementation pass artifacts, including `.envctl-commit-message.md`.

## Gaps from prior iteration (mapped to evidence)
- Direct non-interactive migrate still prints raw action failure text instead of a curated summary.
  - Code evidence: [`python/envctl_engine/actions/action_target_support.py`](/Users/kfiramar/projects/current/envctl/trees/broken_envctl_migrate_output_1dedup_success_visibility_and_spinner_parity/1/python/envctl_engine/actions/action_target_support.py) still prints `"{command_name} action failed for {context.name}: {error}"` whenever `interactive_command` is false.
  - Code evidence: [`python/envctl_engine/actions/action_command_orchestrator.py`](/Users/kfiramar/projects/current/envctl/trees/broken_envctl_migrate_output_1dedup_success_visibility_and_spinner_parity/1/python/envctl_engine/actions/action_command_orchestrator.py) adds concise migrate failure status formatting only for interactive `ui.status` emission; it does not add a direct CLI final summary renderer.
  - Audit note evidence: [.envctl-commit-message.md](/Users/kfiramar/projects/current/envctl/trees/broken_envctl_migrate_output_1dedup_success_visibility_and_spinner_parity/1/.envctl-commit-message.md) explicitly states that direct non-interactive `migrate` still uses the existing action-level printed lines outside the new concise summary flow.
- The compact migrate result summary is implemented only for dashboard-interactive rendering.
  - Code evidence: [`python/envctl_engine/ui/dashboard/orchestrator.py`](/Users/kfiramar/projects/current/envctl/trees/broken_envctl_migrate_output_1dedup_success_visibility_and_spinner_parity/1/python/envctl_engine/ui/dashboard/orchestrator.py) contains `_print_migrate_result_details(...)`, but there is no corresponding direct CLI result-summary printer in the action path.
  - Git evidence: branch divergence from `origin/main` contains only commit `9f7f38e`, which touched action helpers, dashboard rendering, and tests, but no docs or manual verification artifact proving closure of the remaining direct CLI summary gap.
- Automated coverage added in the previous iteration does not lock the remaining direct CLI result-summary behavior.
  - Test evidence: [`tests/python/actions/test_action_target_support.py`](/Users/kfiramar/projects/current/envctl/trees/broken_envctl_migrate_output_1dedup_success_visibility_and_spinner_parity/1/tests/python/actions/test_action_target_support.py) covers interactive bounded migrate failure statuses, not direct CLI final output.
  - Test evidence: [`tests/python/actions/test_action_spinner_integration.py`](/Users/kfiramar/projects/current/envctl/trees/broken_envctl_migrate_output_1dedup_success_visibility_and_spinner_parity/1/tests/python/actions/test_action_spinner_integration.py) covers spinner updates, but not the non-interactive final result block.
  - Test evidence: [`tests/python/ui/test_dashboard_orchestrator_restart_selector.py`](/Users/kfiramar/projects/current/envctl/trees/broken_envctl_migrate_output_1dedup_success_visibility_and_spinner_parity/1/tests/python/ui/test_dashboard_orchestrator_restart_selector.py) covers dashboard-interactive mixed-result and all-success rendering, not direct CLI output.
- The required real-TTY verification from the prior task has no implementation-pass record in git.
  - Git evidence: `git log --oneline --decorate ace3821..HEAD` shows only `9f7f38e fix(migrate): improve output summaries`.
  - Git evidence: `git diff --name-status ace3821..HEAD` shows no manual-verification notes, docs updates, or additional artifacts recording the mandated TTY commands and outcomes.

## Acceptance criteria (requirement-by-requirement)
1. Direct non-interactive CLI migrate prints one compact per-target result block after execution completes.
   - Success and failure lines appear in route order.
   - Mixed-result runs show both successes and failures.
   - All-success multi-target runs still print visible success lines.
2. Direct non-interactive CLI migrate failures no longer lead with `Traceback (most recent call last):`.
   - The first visible failure line uses the actionable exception headline.
   - The raw traceback is preserved only in the persisted failure report artifact.
3. Each failed target prints exactly one failure-log path block in the direct CLI summary when `report_path` exists.
4. Persisted migrate metadata remains aligned and intact.
   - `status`, `updated_at`, `report_path`, `backend_env`, and additive `headline` remain available.
   - No data migration or backfill is required.
5. Focused automated tests prove the direct CLI summary behavior and remain green.
6. Real-TTY verification is actually run and recorded with exact commands and observed outcomes for:
   - dashboard-interactive migrate
   - direct CLI migrate
   - `show-state --json` metadata inspection

## Required implementation scope (frontend/backend/data/integration)
- Frontend / terminal UX:
  - implement the remaining direct CLI migrate result-summary rendering using the repo’s existing terminal output conventions
  - keep dashboard-interactive behavior unchanged except for any regression fixes required to share summary helpers safely
- Backend / action execution:
  - adjust the non-interactive migrate action path so raw multiline failure payloads are no longer printed inline to the terminal
  - reuse or centralize migrate headline/hint/report-path formatting so dashboard and direct CLI outputs cannot drift
- Data / state:
  - preserve current persisted migrate metadata semantics
  - do not change raw failure report contents or locations
  - keep `headline` additive and backward-compatible for older state entries without it
- Integration:
  - perform the real-TTY dashboard and direct CLI verification described above
  - verify `show-state --json` after failure to confirm metadata continuity

## Required tests and quality gates
- Add or extend focused tests in the smallest appropriate suites, likely including:
  - [`tests/python/actions/test_actions_parity.py`](/Users/kfiramar/projects/current/envctl/trees/broken_envctl_migrate_output_1dedup_success_visibility_and_spinner_parity/1/tests/python/actions/test_actions_parity.py)
    - direct non-interactive migrate failure output prefers the actionable headline over traceback chrome
    - direct non-interactive mixed-result migrate run prints both successes and failures
    - direct non-interactive all-success migrate run prints visible success lines
    - failed targets still persist `report_path`, `headline`, and backend env metadata
  - [`tests/python/actions/test_action_target_support.py`](/Users/kfiramar/projects/current/envctl/trees/broken_envctl_migrate_output_1dedup_success_visibility_and_spinner_parity/1/tests/python/actions/test_action_target_support.py)
    - if the final design changes how non-interactive migrate output is emitted, add narrow coverage there
  - [`tests/python/actions/test_action_spinner_integration.py`](/Users/kfiramar/projects/current/envctl/trees/broken_envctl_migrate_output_1dedup_success_visibility_and_spinner_parity/1/tests/python/actions/test_action_spinner_integration.py)
    - keep proving live spinner updates while the direct CLI action spinner is the visible owner
- Re-run at minimum:
  - `PYTHONPATH=python python3 -m unittest tests.python.actions.test_action_target_support`
  - `PYTHONPATH=python python3 -m unittest tests.python.actions.test_action_spinner_integration`
  - `PYTHONPATH=python python3 -m unittest tests.python.actions.test_actions_parity`
  - `PYTHONPATH=python python3 -m unittest tests.python.ui.test_dashboard_orchestrator_restart_selector`
  - `PYTHONPATH=python python3 -m unittest tests.python.ui.test_terminal_ui_dashboard_loop`
- If implementation introduces a new helper shared by dashboard and action output, add the narrowest unit-style test coverage for that helper.

## Edge cases and failure handling
- Targets missing from persisted action metadata must not crash direct CLI result rendering.
- Multiple failures must produce one report-path block per failed target, not one merged dump.
- If a migrate command fails before a report path is written, print the concise failure line and any available hints without crashing.
- Keep hints deduplicated.
- Preserve one spinner owner per visible command path.
- Do not emit raw traceback payloads into bounded status/spinner messages.
- Older persisted migrate entries without `headline` must still render correctly by reparsing `summary`.

## Definition of done
- The direct non-interactive CLI migrate path prints a compact per-target result summary instead of raw multiline failure walls.
- Direct CLI migrate failures lead with actionable exception headlines, not `Traceback (most recent call last):`.
- Dashboard-interactive migrate behavior remains correct and regression-free.
- Persisted migrate report paths, backend env metadata, and additive `headline` metadata remain intact and backward-compatible.
- Focused automated coverage locks the remaining direct CLI summary behavior and all relevant suites pass.
- Real-TTY verification is completed and recorded with exact commands and outcomes.
