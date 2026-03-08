# ULW Stabilization Session Log

## Scope
- Exhaustive command/option validation across Python and Bash parity surfaces.
- Deep bug fixes (no patchwork), with TDD when introducing behavior changes.
- UI/UX consistency for interactive flows, stability hardening, and snappiness improvements.

## Execution Slices
1. Baseline full-suite validation (Python unit + full BATS).
2. Build command/flag coverage matrix and gap list.
3. Reproduce and isolate failing/flaky scenarios.
4. Apply deep fixes with tests-first per issue.
5. Re-run targeted and full suites.
6. Iterate until no blocking regressions remain.

## Baseline Results (Current Session)
- Python unit baseline (`unittest discover`): completed with broad pass output; long-running but mostly green.
- BATS baseline (`tests/bats/*.bats`): two failing cases observed during timed run:
  - `python_plan_parallel_ports_e2e.bats` test 61 (`python --plan assigns unique app and infra ports across 3 trees`) failed with Python engine startup guard message.
  - `python_plan_selector_strictness_e2e.bats` test 62 terminated (`Killed: 9`) during missing-plan strictness path.

## Working Hypotheses
- Failures may be environment/version-gate related (`Python 3.12` selection path) and/or timeout/resource pressure during full BATS run.
- Need isolated reruns per failing suite to distinguish deterministic bug from run-level interference.

## In-Progress Actions
- Isolated reruns for failing BATS files.
- Command/flag coverage matrix via explore agent.
- Performance hotspot mapping (resume/interactivity) via explore agent.
- UX library/practice synthesis (prompt_toolkit + spinner/progress) via librarian.
- Oracle architecture check for stabilization ordering.

## Manual Validation Log
- Pending (to fill after isolated reproductions and tmux-driven interactive scenarios).

## Update - 2026-02-28 (Stabilization Slice)

### Background Agent Outputs Integrated
- `bg_041d5d36` (performance bottlenecks) confirmed repeated dashboard truth reconciliation as a high-impact snappiness issue.
- `bg_4a4a5bf6` (command/option surface) and `bg_e07913ae` (test strategy) were already integrated into hotspot prioritization and matrix testing order.
- `bg_679ffa21` (CLI UX stack) reinforced the current direction: prompt_toolkit for input, separate output rendering path, no mixed-render collisions.

### Fixes Applied
- Added dashboard truth-cache path in `python/envctl_engine/engine_runtime.py`:
  - `_dashboard_truth_refresh_seconds()` with `ENVCTL_DASHBOARD_TRUTH_REFRESH_SECONDS` override.
  - `_dashboard_reconcile_for_snapshot()` to reuse a short-lived reconcile result for repeated snapshots in the same run.
  - Runtime cache fields initialized in `PythonEngineRuntime.__init__`.
- Updated `python/envctl_engine/dashboard_rendering_domain.py` to call runtime snapshot reconcile helper when available.

### Tests Added
- `tests/python/test_dashboard_rendering_parity.py`
  - `test_dashboard_snapshot_reuses_recent_truth_result_for_same_run`
  - `test_dashboard_snapshot_truth_cache_can_be_disabled`

### Verification Results
- Python regressions:
  - `pytest -q tests/python/test_dashboard_rendering_parity.py tests/python/test_runtime_health_truth.py tests/python/test_terminal_ui_dashboard_loop.py`
  - Result: `26 passed`
- Expanded Python stabilization lane:
  - `pytest -q tests/python/test_ui_menu_interactive.py tests/python/test_ui_prompt_toolkit_default.py tests/python/test_terminal_ui_dashboard_loop.py tests/python/test_planning_menu_rendering.py tests/python/test_lifecycle_parity.py tests/python/test_actions_parity.py tests/python/test_dashboard_rendering_parity.py tests/python/test_runtime_health_truth.py`
  - Result: `93 passed`
- BATS regressions:
  - `bats tests/bats/python_interactive_input_reliability_e2e.bats tests/bats/python_resume_restore_missing_e2e.bats`
  - Result: `2 passed`
- Expanded BATS lane:
  - `bats tests/bats/python_plan_nested_worktree_e2e.bats tests/bats/python_plan_selector_strictness_e2e.bats tests/bats/python_interactive_input_reliability_e2e.bats tests/bats/python_resume_restore_missing_e2e.bats`
  - Result: `4 passed`
- Expanded BATS stress (3 consecutive runs):
  - `for i in 1 2 3; do bats tests/bats/python_plan_nested_worktree_e2e.bats tests/bats/python_plan_selector_strictness_e2e.bats tests/bats/python_interactive_input_reliability_e2e.bats tests/bats/python_resume_restore_missing_e2e.bats || exit 1; done`
  - Result: `3/3 runs fully green`
- Broader high-risk BATS parity lane:
  - `bats tests/bats/python_actions_parity_e2e.bats tests/bats/python_plan_nested_worktree_e2e.bats tests/bats/python_plan_selector_strictness_e2e.bats tests/bats/python_plan_parallel_ports_e2e.bats tests/bats/python_interactive_input_reliability_e2e.bats tests/bats/python_resume_restore_missing_e2e.bats tests/bats/python_logs_follow_parity_e2e.bats tests/bats/python_runtime_truth_health_e2e.bats`
  - Result: `9 passed`

### Current Status
- No regression reproduced in repeated targeted BATS runs for previously unstable planning suites.
- Dashboard interactive snapshots are now less probe-heavy while preserving strict reconciliation behavior on first refresh and configurable refresh interval behavior.
- Next stabilization slice remains: run broader BATS stress lane and continue parity matrix closure for remaining hotspot combinations.

## Update - 2026-02-28 (Interactive CPR/Input Reliability)

### Reported Symptom
- Repeated warning before command prompt: `WARNING: your terminal doesn't support cursor position requests (CPR).`
- Interactive dashboard command entry felt laggy/unreliable for typing and Enter.

### Root Cause
- Dashboard command input path uses prompt_toolkit directly in `python/envctl_engine/ui/terminal_session.py`.
- In terminals that do not respond to CPR queries, prompt_toolkit emits warning(s) and can degrade input responsiveness.

### Fix Applied
- Wrapped prompt_toolkit command prompt calls with a scoped no-CPR environment override:
  - `_prompt_toolkit_no_cpr()` context manager sets `PROMPT_TOOLKIT_NO_CPR=1` only during prompt call, then restores previous env state.
  - `_prompt_toolkit_prompt()` now executes under this context.

### Tests Added
- `tests/python/test_ui_prompt_toolkit_default.py`
  - `test_prompt_toolkit_prompt_disables_cpr_temporarily`
  - Verifies `PROMPT_TOOLKIT_NO_CPR` is forced to `1` during prompt invocation and restored afterward.

### Verification Results
- `python3 -m unittest tests.python.test_ui_prompt_toolkit_default tests.python.test_terminal_ui_dashboard_loop tests.python.test_ui_menu_interactive`
  - Result: `13 tests OK`
- `bats tests/bats/python_interactive_input_reliability_e2e.bats`
  - Result: `1 passed`

## Update - 2026-02-28 (Status-Aware Spinner UX)

### Reported Symptom
- Spinner was effectively missing during interactive command execution.
- Need richer status updates while commands run, without reintroducing input/render collisions.

### Root Cause
- `python/envctl_engine/ui/spinner.py` existed but was not wired into the interactive dashboard command loop.
- `python/envctl_engine/ui/command_loop.py` had no spinner integration and no event-to-status bridge.

### Fix Applied
- `python/envctl_engine/ui/spinner.py`
  - Added thread-safe live status updates via `Spinner.update(...)`.
  - Added polished completion states via `Spinner.succeed(...)` and `Spinner.fail(...)`.
  - Added colored, clean transient rendering and final status line output (`+` success / `!` failure), with `NO_COLOR` fallback.
  - Updated context manager to yield `Spinner` instance for in-loop status control.
- `python/envctl_engine/ui/command_loop.py`
  - Re-integrated spinner around command execution only (never during prompt input).
  - Added command normalization and command-specific initial status messages.
  - Added runtime event bridge that maps `_emit(...)` events to live spinner messages (routing, startup, requirements, bootstrap, bind, cleanup, action lifecycle).
  - Added failure detection from emitted events (`action.command.finish` non-zero, startup/planning failures) and final success/failure status line.

### Tests Added / Updated
- `tests/python/test_terminal_ui_dashboard_loop.py`
  - `test_dashboard_loop_updates_spinner_status_from_runtime_events`
  - `test_dashboard_loop_marks_spinner_failed_from_action_finish_event`

### Verification Results
- `python3 -m unittest tests.python.test_terminal_ui_dashboard_loop tests.python.test_ui_prompt_toolkit_default tests.python.test_ui_menu_interactive`
  - Result: `15 tests OK`
- `python3 -m unittest tests.python.test_engine_runtime_real_startup.EngineRuntimeRealStartupTests.test_interactive_loop_flushes_pending_input_after_noise_only_entry tests.python.test_engine_runtime_real_startup.EngineRuntimeRealStartupTests.test_interactive_loop_flushes_pending_input_after_partial_csi_fragment tests.python.test_engine_runtime_real_startup.EngineRuntimeRealStartupTests.test_interactive_loop_flushes_pending_input_after_bracketed_paste_fragment tests.python.test_engine_runtime_real_startup.EngineRuntimeRealStartupTests.test_interactive_loop_does_not_flush_before_each_prompt tests.python.test_engine_runtime_real_startup.EngineRuntimeRealStartupTests.test_interactive_loop_flushes_pending_input_after_empty_entry`
  - Result: `5 tests OK`
- `bats tests/bats/python_interactive_input_reliability_e2e.bats`
  - Result: `1 passed`

## Update - 2026-02-28 (Interactive Typing Freeze Hotfix)

### Reported Symptom
- In interactive dashboard mode, command prompt intermittently became non-typeable / input appeared frozen.

### Investigation Summary
- Internal code search showed command input path still used prompt_toolkit by default for `TerminalSession.read_command_line(...)` when interactive TTY was available.
- Parallel explore/librarian/oracle analysis aligned on a reliability-first path:
  - Use basic `/dev/tty` line input for dashboard command prompt by default.
  - Enforce canonical line mode before reads (`ICANON|ECHO|ISIG`) to recover from leaked raw mode.
  - Keep prompt_toolkit available for other UI areas but avoid it in the dashboard command-entry loop.

### Fix Applied
- `python/envctl_engine/ui/command_loop.py`
  - Dashboard loop now constructs `TerminalSession(..., prefer_basic_input=True)`.
- `python/envctl_engine/ui/terminal_session.py`
  - Added `prefer_basic_input` constructor flag and `ENVCTL_UI_BASIC_INPUT` override support.
  - Added `_restore_stdin_terminal_sane()` pre-read recovery step.
  - Added `_ensure_tty_line_mode(fd=...)` to force canonical line discipline bits before read.
  - Added `_canonical_line_state(fd=...)` and explicit `restore_terminal_after_input(..., original_state=canonical_state)` in fallback path for clean post-read flush/restore.
  - Fallback reader now avoids disabling `ISIG`/raw-mode toggles for dashboard command entry.

### Tests Added / Updated
- `tests/python/test_ui_prompt_toolkit_default.py`
  - `test_terminal_session_prefers_basic_input_when_requested`
  - `test_terminal_session_prefers_basic_input_when_env_flag_enabled`
  - `test_ensure_tty_line_mode_enables_canonical_echo_and_signal_flags`
- `tests/python/test_terminal_ui_dashboard_loop.py`
  - `test_dashboard_loop_uses_basic_input_backend_for_command_prompt`

### Verification Results
- `python3 -m unittest tests.python.test_ui_prompt_toolkit_default tests.python.test_terminal_ui_dashboard_loop tests.python.test_interactive_input_reliability tests.python.test_ui_menu_interactive`
  - Result: `34 tests OK`
- `bats tests/bats/python_interactive_input_reliability_e2e.bats`
  - Result: `1 passed`
- LSP diagnostics (error severity) clean for modified runtime/UI test files.

## Update - 2026-02-28 (Spinner Timing in Selection Menus)

### Reported Symptom
- Spinner appeared during target-selection menus (project/service selectors).
- Desired behavior: no spinner while selecting; spinner only after selection, during actual execution (restart/test/etc).

### Root Cause
- `run_dashboard_command_loop(...)` started spinner immediately before calling command handler.
- Selection prompts for commands like `restart` and `test` occur inside handler/orchestrators, so spinner rendered over selection UI.

### Fix Applied
- `python/envctl_engine/ui/spinner.py`
  - Added `start_immediately` option to spinner context manager.
  - Made `Spinner.start()` idempotent and `Spinner.stop()` no-op if never started.
- `python/envctl_engine/ui/command_loop.py`
  - Switched to deferred spinner start (`start_immediately=False`).
  - Spinner now starts only when execution-phase events occur (`action.command.start`, `startup.execution`, `requirements.start`, `service.start`, cleanup events, etc.).
  - Removed route-selection spinner message path so selection-stage routing does not render spinner.
  - Final success/fail status lines emit only when spinner actually started.
- `python/envctl_engine/action_command_orchestrator.py`
  - Moved `action.command.start` emission to after target resolution for action commands, so interactive target selection happens without spinner.

### Tests Added / Updated
- `tests/python/test_terminal_ui_dashboard_loop.py`
  - Updated spinner mocks for deferred start behavior.
  - Added `test_dashboard_loop_does_not_start_spinner_for_route_selection_only`.
  - Updated status assertions to verify no route-selection spinner update.

### Verification Results
- `python3 -m unittest tests.python.test_terminal_ui_dashboard_loop tests.python.test_ui_prompt_toolkit_default tests.python.test_ui_menu_interactive tests.python.test_interactive_input_reliability`
  - Result: `35 tests OK`
- `python3 -m unittest tests.python.test_actions_parity`
  - Result: `17 tests OK`
- `bats tests/bats/python_interactive_input_reliability_e2e.bats`
  - Result: `1 passed`

## Update - 2026-02-28 (Resume Restore Spinner)

### Reported Symptom
- During top-level `envctl` startup auto-resume, stale service restore printed plain progress lines (`Restoring stale services for project ...`) instead of using spinner-style single-line status updates.

### Fix Applied
- `python/envctl_engine/resume_orchestrator.py`
  - Integrated spinner into `restore_missing(...)` when TTY spinner is enabled.
  - Spinner now updates per project (`Restoring stale services for project <name>...`) and finishes with:
    - success: `stale services restored`
    - failure: `stale restore failed for <N> project(s)`
  - Preserved non-spinner fallback behavior for non-TTY/CI by keeping plain `print(...)` output.

### Tests Added / Updated
- `tests/python/test_lifecycle_parity.py`
  - Added `test_resume_restore_uses_spinner_when_enabled`.
  - Verifies spinner path is used and plain restore line is not emitted to stdout when spinner is active.

### Verification Results
- `python3 -m unittest tests.python.test_lifecycle_parity.LifecycleParityTests.test_resume_restarts_missing_services_when_commands_are_configured tests.python.test_lifecycle_parity.LifecycleParityTests.test_resume_interactive_restarts_missing_services_by_default tests.python.test_lifecycle_parity.LifecycleParityTests.test_resume_restore_uses_spinner_when_enabled`
  - Result: `3 tests OK`
- `python3 -m unittest tests.python.test_terminal_ui_dashboard_loop tests.python.test_ui_prompt_toolkit_default tests.python.test_interactive_input_reliability`
  - Result: `28 tests OK`
- `bats tests/bats/python_resume_restore_missing_e2e.bats tests/bats/python_interactive_input_reliability_e2e.bats`
  - Result: `2 passed`

## Update - 2026-02-28 (Permanent Interactive Typing Hardening)

### Reported Symptom
- Typing became unreliable again after adjacent spinner/UI changes.

### Root Cause
- Dashboard command loop can read input through runtime callback (`_read_interactive_command_line`) when provided.
- That runtime callback still instantiated `TerminalSession` without `prefer_basic_input=True`, silently reintroducing prompt_toolkit behavior in real runs.

### Fix Applied
- `python/envctl_engine/engine_runtime.py`
  - `_read_interactive_command_line(...)` now always uses `TerminalSession(self.env, prefer_basic_input=True)`.
- `python/envctl_engine/terminal_ui.py`
  - `RuntimeTerminalUI.read_interactive_command_line(...)` now also uses `TerminalSession(..., prefer_basic_input=True)` for consistency.

### Tests Added / Updated
- `tests/python/test_interactive_input_reliability.py`
  - Added `test_engine_runtime_read_interactive_command_line_prefers_basic_input_backend`.
- `tests/python/test_ui_prompt_toolkit_default.py`
  - Added `test_runtime_terminal_ui_interactive_read_prefers_basic_input`.

### Verification Results
- `python3 -m unittest tests.python.test_ui_prompt_toolkit_default tests.python.test_interactive_input_reliability tests.python.test_terminal_ui_dashboard_loop tests.python.test_ui_menu_interactive tests.python.test_actions_parity`
  - Result: `54 tests OK`
- `bats tests/bats/python_interactive_input_reliability_e2e.bats tests/bats/python_resume_restore_missing_e2e.bats`
  - Result: `2 passed`

## Update - 2026-02-28 (Spinner Precision Upgrade)

### Reported Symptom
- Spinner text was too generic (`Running test...`, `Restoring stale services for project Main...`) and not reflecting fine-grained progress.

### Fix Applied
- `python/envctl_engine/ui/command_loop.py`
  - Added `ui.status` event support for spinner updates.
  - Enriched startup/requirements/service status messages with project counts, ports, retry intent, and mode details.
  - Allowed spinner to start on `ui.status` events (for richer phase transitions).
- `python/envctl_engine/action_command_orchestrator.py`
  - Added precise status emissions via `ui.status` for action command lifecycle:
    - command scope (`Running test for Main...`, `Running pr for 3 targets...`)
    - per-target progress (`Running commit for feature-a-1 (1/2)...`)
    - success/failure per target.
  - Kept spinner-out-of-selection behavior by emitting `action.command.start` only after target resolution.
- `python/envctl_engine/startup_orchestrator.py`
  - When running from interactive command mode, replaced startup progress `print(...)` calls with `ui.status` emissions (so updates stay on spinner line).
  - Added final startup status (`Startup complete; refreshing dashboard...`) instead of summary block during interactive commands.
- `python/envctl_engine/resume_orchestrator.py`
  - Resume restore spinner now emits step-level statuses with project index/total:
    - context resolution
    - stale termination
    - requirement port release
    - port reservation
    - requirements start
    - app services start
    - per-project restore success/failure.

### Tests Added / Updated
- `tests/python/test_terminal_ui_dashboard_loop.py`
  - Added `test_dashboard_loop_uses_ui_status_event_for_precise_spinner_updates`.
- `tests/python/test_lifecycle_parity.py`
  - Updated spinner expectations to match indexed resume restore status flow.

### Verification Results
- `python3 -m unittest tests.python.test_terminal_ui_dashboard_loop tests.python.test_actions_parity tests.python.test_ui_prompt_toolkit_default tests.python.test_interactive_input_reliability`
  - Result: `48 tests OK`
- `python3 -m unittest tests.python.test_engine_runtime_real_startup.EngineRuntimeRealStartupTests.test_start_prints_loading_progress_per_project tests.python.test_engine_runtime_real_startup.EngineRuntimeRealStartupTests.test_interactive_command_start_suppresses_loading_progress_output tests.python.test_lifecycle_parity.LifecycleParityTests.test_resume_restarts_missing_services_when_commands_are_configured tests.python.test_lifecycle_parity.LifecycleParityTests.test_resume_interactive_restarts_missing_services_by_default tests.python.test_lifecycle_parity.LifecycleParityTests.test_resume_restore_uses_spinner_when_enabled`
  - Result: `5 tests OK`
- `bats tests/bats/python_interactive_input_reliability_e2e.bats tests/bats/python_resume_restore_missing_e2e.bats`
  - Result: `2 passed`

## Update - 2026-02-28 (Deep Test Spinner UX Overhaul)

### Reported Symptom
- Test spinner status was too generic (`Executing detected test command...`).
- Status line and action output could collide in interactive mode (`...command...Executed test action...`).

### Fix Applied
- `python/envctl_engine/action_command_orchestrator.py`
  - Added command-aware test execution status messages:
    - `pytest` path (`Running pytest suite at ...`)
    - `unittest discover` path (`Running unittest discovery (test_*.py)...`)
    - package manager path (`Running <manager> test script in <location>...`)
    - tree script path (`Running tree test matrix for <scope>...`)
    - configured command path with short command preview.
  - Suppressed interactive-mode stdout success/failure lines for test/pr/commit/analyze/migrate/delete-worktree action loops and replaced them with `ui.status` updates to keep spinner rendering clean.
  - Kept non-interactive output behavior unchanged.
- `tests/python/test_actions_parity.py`
  - Added `test_interactive_test_action_reports_status_without_stdout_summary_line`.
  - Converted imports to module-based loading to keep diagnostics clean in this workspace.

### Verification Results
- `python3 -m unittest tests.python.test_actions_parity tests.python.test_terminal_ui_dashboard_loop tests.python.test_ui_prompt_toolkit_default tests.python.test_interactive_input_reliability`
  - Result: `49 tests OK`
- `python3 -m unittest tests.python.test_lifecycle_parity.LifecycleParityTests.test_resume_restore_uses_spinner_when_enabled tests.python.test_lifecycle_parity.LifecycleParityTests.test_resume_restarts_missing_services_when_commands_are_configured tests.python.test_lifecycle_parity.LifecycleParityTests.test_resume_interactive_restarts_missing_services_by_default`
  - Result: `3 tests OK`
- `bats tests/bats/python_interactive_input_reliability_e2e.bats tests/bats/python_resume_restore_missing_e2e.bats tests/bats/python_actions_parity_e2e.bats`
  - Result: `3 passed`
