## 2026-03-18

Scope:
- Fix interrupted `envctl test` runs so active suite subprocess groups are terminated before the interrupt escapes.
- Preserve controlled interrupt semantics for direct CLI usage and interactive dashboard-triggered test commands.

Key behavior changes:
- Added detached-session/process-group termination support to `ProcessRunner` and threaded process-start callbacks through the shared runner and `TestRunner`.
- Refactored `action_test_runner.run_test_action(...)` to track active suite PIDs, cancel queued parallel work on `KeyboardInterrupt`, emit bounded `test.interrupt.received` and `test.interrupt.cleanup` events, and skip summary persistence/overview rendering on interrupted runs.
- Updated action/dashboard interrupt handling so `action.command.finish` emits code `2` on controlled interrupts and interactive dashboard test commands return to the prompt without printing misleading failure-summary blocks.

Files/modules touched:
- `python/envctl_engine/shared/process_runner.py`
- `python/envctl_engine/shared/protocols.py`
- `python/envctl_engine/test_output/test_runner.py`
- `python/envctl_engine/actions/action_test_runner.py`
- `python/envctl_engine/actions/action_command_orchestrator.py`
- `python/envctl_engine/ui/dashboard/orchestrator.py`
- `tests/python/shared/test_process_runner_listener_detection.py`
- `tests/python/test_output/test_test_runner_streaming_fallback.py`
- `tests/python/actions/test_actions_parity.py`
- `tests/python/ui/test_dashboard_orchestrator_restart_selector.py`
- `tests/python/ui/test_terminal_ui_dashboard_loop.py`

Tests run + results:
- `PYTHONPATH=python python3 -m unittest tests.python.shared.test_process_runner_listener_detection tests.python.shared.test_process_runner_spinner_integration`
  - Passed.
- `PYTHONPATH=python python3 -m unittest tests.python.test_output.test_test_runner_streaming_fallback`
  - Passed, 1 skipped (`pytest`-dependent real-subprocess slice).
- `PYTHONPATH=python python3 -m unittest tests.python.actions.test_actions_parity`
  - Passed.
- `PYTHONPATH=python python3 -m unittest tests.python.ui.test_dashboard_orchestrator_restart_selector tests.python.ui.test_terminal_ui_dashboard_loop tests.python.runtime.test_command_exit_codes`
  - Passed.

Config/env/migrations:
- No config schema, env contract, or migration changes.

Risks/notes:
- Interrupt cleanup relies on suite processes continuing to launch in detached sessions where the process group id matches the spawned pid.
- No manual `Ctrl+C`/`pgrep` verification was run in this worktree; coverage is via deterministic unit/integration-style tests and existing CLI exit-code assertions.

## 2026-03-19

Scope:
- Close the remaining interrupt-cleanup verification gaps for `envctl test`, including failed-only state preservation and real `TestRunner` callback wiring in both sequential and parallel action paths.
- Re-verify the end-to-end interrupt contract after the production changes already staged in this worktree.

Key behavior changes:
- Added action-level regressions that prove interrupted runs preserve prior failed-only summary metadata/manifest state instead of overwriting it with partial results.
- Added integration-style action coverage that exercises the real `TestRunner` path with a stub `process_runner`, proving `process_started_callback` registration reaches the interrupt cleanup logic in both sequential and parallel execution modes.
- Re-verified that a real CLI `SIGINT` exits with code `2` and leaves no surviving envctl-started suite processes after cleanup.

Files/modules touched:
- `tests/python/actions/test_actions_parity.py`
- `docs/changelog/broken_envctl_test_interrupt_shutdown_and_child_process_cleanup-2_changelog.md`

Tests run + results:
- `PYTHONPATH=python python3 -m unittest tests.python.actions.test_actions_parity`
  - Passed (`101` tests).
- `PYTHONPATH=python python3 -m unittest tests.python.shared.test_process_runner_listener_detection tests.python.shared.test_process_runner_spinner_integration`
  - Passed (`22` tests).
- `PYTHONPATH=python python3 -m unittest tests.python.test_output.test_test_runner_streaming_fallback`
  - Passed (`14` tests, `1` skipped existing pytest-dependent slice).
- `PYTHONPATH=python python3 -m unittest tests.python.ui.test_dashboard_orchestrator_restart_selector tests.python.ui.test_terminal_ui_dashboard_loop tests.python.runtime.test_command_exit_codes`
  - Passed (`89` tests).
- Manual verification:
  - Real `envctl` CLI test run interrupted with `SIGINT` returned exit code `2`.
  - No surviving child `pytest`/`vitest` test processes remained after cleanup (`survivors: []`).

Config/env/migrations:
- No config schema, env contract, or migration changes.

Risks/notes:
- Real interrupted runs can still include already-emitted per-suite pass output for suites that completed before the operator interrupt landed; the verified guard is that interrupted runs do not print the normal final action overview or persist partial summary artifacts after `KeyboardInterrupt`.
- Cleanup still assumes the concrete process runner uses detached sessions/process groups compatible with `terminate_process_group(pid, ...)`.
