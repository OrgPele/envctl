# Envctl Clickable Paths Across CLI Surfaces Plan

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Make user-visible local filesystem paths consistently clickable across envctl's plain terminal and Rich-backed CLI surfaces, instead of relying on ad hoc formatting or terminal auto-detection.
  - Preserve existing machine-readable behavior: JSON output, persisted state metadata, saved summary files, and report artifacts must keep storing raw path strings with no terminal escape sequences.
  - Reuse one shared path-rendering policy so dashboard, action, runtime, config, and startup flows stop reimplementing path formatting independently.
- Non-goals:
  - Changing URL rendering for HTTP/PR links. Those already use URL-specific flows such as dashboard PR lookup in `python/envctl_engine/ui/dashboard/rendering.py:_dashboard_lookup_pr`.
  - Rewriting third-party subprocess output or persisted report contents to inject hyperlinks after the fact.
  - Changing the location or schema of runtime artifacts such as `project_test_summaries`, `project_action_reports`, or `run_state.json`.
  - Reworking Textual widget rendering unless repo verification shows the same helper can be applied safely there without a separate rendering path.
- Assumptions:
  - The user-facing acceptance target is interactive terminal output, not JSON payloads or repo artifacts.
  - OSC-style hyperlink escape sequences are acceptable in this repo's terminal-output model because `python/envctl_engine/test_output/parser_base.py:strip_ansi` already strips ANSI OSC sequences as part of the existing parsing contract.
  - A conservative terminal capability policy is needed because envctl supports many terminals and already treats color/backend capability selection as policy, not as unconditional behavior.

## Goal (user experience)
When an operator runs envctl interactively, every envctl-owned file path that is meant to be acted on should be click/open friendly in a consistent way. That includes dashboard `log:` and `tests:` rows, failure summary/report locations, review bundles, debug bundles, config file paths, and similar artifact outputs. Paths should remain readable as plain text, but interactive terminals should no longer depend on fragile auto-link heuristics for some screens while other screens remain non-clickable.

## Business logic and data model mapping
- State-backed path sources:
  - `python/envctl_engine/state/models.py:ServiceRecord.log_path`
  - `python/envctl_engine/state/models.py:RunState.metadata`
  - `RunState.metadata["project_test_summaries"][project]` carries `summary_path`, `short_summary_path`, `manifest_path`, `summary_excerpt`, and `status`, written by `python/envctl_engine/actions/action_command_orchestrator.py:_persist_test_summary_artifacts`
  - `RunState.metadata["project_action_reports"][project][command]` carries `report_path`, `summary`, and `status`, written by `python/envctl_engine/actions/action_command_orchestrator.py:_write_project_action_failure_report` and related dispatch code
- Non-state path result objects:
  - `python/envctl_engine/config/persistence.py:ConfigSaveResult.path`
  - `python/envctl_engine/runtime/prompt_install_support.py:PromptInstallResult.path` and `backup_path`
  - `python/envctl_engine/shared/hooks.py:HookMigrationResult.python_hook_path`
- Current output-policy modules that are the right ownership seam for a shared rendering helper:
  - `python/envctl_engine/ui/color_policy.py`
  - `python/envctl_engine/ui/capabilities.py`
  - `python/envctl_engine/test_output/parser_base.py`
- Primary output call paths that currently surface those paths:
  - Dashboard snapshot:
    - `python/envctl_engine/ui/dashboard/rendering.py:_print_dashboard_service_row`
    - `python/envctl_engine/ui/dashboard/rendering.py:_print_dashboard_tests_row`
  - Dashboard failure/detail flows:
    - `python/envctl_engine/ui/dashboard/orchestrator.py:_print_test_failure_details`
    - `python/envctl_engine/ui/dashboard/orchestrator.py:_print_project_action_failure_details`
  - Test and action summaries:
    - `python/envctl_engine/actions/action_command_orchestrator.py:_print_test_suite_summary`
  - Review output:
    - `python/envctl_engine/actions/project_action_domain.py:_print_review_completion`
    - `python/envctl_engine/actions/project_action_domain.py:_print_review_completion_rich`
    - `python/envctl_engine/actions/project_action_domain.py:_print_review_failure`
  - Logs/inspection/debug/config/utility output:
    - `python/envctl_engine/runtime/engine_runtime_misc_support.py:print_logs`
    - `python/envctl_engine/runtime/inspection_support.py:_print_show_config`
    - `python/envctl_engine/runtime/inspection_support.py:_print_state`
    - `python/envctl_engine/runtime/engine_runtime_debug_support.py:debug_pack`
    - `python/envctl_engine/runtime/engine_runtime_debug_support.py:debug_last`
    - `python/envctl_engine/runtime/engine_runtime_debug_support.py:debug_report`
    - `python/envctl_engine/debug/doctor_orchestrator.py:DoctorOrchestrator.execute`
    - `python/envctl_engine/runtime/prompt_install_support.py:_print_install_results`
    - `python/envctl_engine/runtime/hook_migration_support.py:run_hook_migration`
    - `python/envctl_engine/config/command_support.py:run_config_command`
  - Startup warning path:
    - `python/envctl_engine/startup/service_bootstrap_domain.py:_run_backend_migration_step`

## Current behavior (verified in code)
- There is no shared hyperlink/path-output helper anywhere in the repo.
  - `rg` over `python/envctl_engine` found only one path-display helper, `python/envctl_engine/actions/project_action_domain.py:_display_path`, and it only normalizes `/private/tmp` to `/tmp`; it does not produce hyperlinks or handle other output surfaces.
- The dashboard currently prints raw path text directly:
  - `python/envctl_engine/ui/dashboard/rendering.py:_print_dashboard_service_row` prints `log:` followed by `service.log_path`.
  - `python/envctl_engine/ui/dashboard/rendering.py:_print_dashboard_tests_row` prints `tests: {summary_path} ({timestamp})`.
  - Existing coverage in `tests/python/ui/test_dashboard_rendering_parity.py` asserts the raw short-summary path string appears in output, but nothing asserts a hyperlink contract.
- The dashboard orchestrator prints failure artifact paths on their own lines, but still as raw strings:
  - `python/envctl_engine/ui/dashboard/orchestrator.py:_print_test_failure_details` prints `summary_path`.
  - `python/envctl_engine/ui/dashboard/orchestrator.py:_print_project_action_failure_details` prints `report_path`.
  - `tests/python/ui/test_dashboard_orchestrator_restart_selector.py` verifies those raw path strings today.
- The interactive test summary prints a raw failure-summary path:
  - `python/envctl_engine/actions/action_command_orchestrator.py:_print_test_suite_summary` prints `failure summary:` and then `summary_path`.
  - `tests/python/actions/test_actions_parity.py` asserts the short summary path appears in rendered output.
- Review output has two separate rendering implementations:
  - Plain terminal fallback in `python/envctl_engine/actions/project_action_domain.py:_print_review_completion` prints output, summary, and bundle paths as plain strings.
  - Rich mode in `python/envctl_engine/actions/project_action_domain.py:_print_review_completion_rich` places the same path strings into a `rich.Table`, but still as plain text, not link-styled `Text`.
  - `tests/python/actions/test_actions_cli.py` only checks path presence, not clickability.
- Several runtime/utility commands print path-bearing fields inline or on their own lines with no common formatting policy:
  - `python/envctl_engine/runtime/inspection_support.py` prints `config_file:` inline and `run_state_path:` on its own line.
  - `python/envctl_engine/runtime/engine_runtime_misc_support.py:print_logs` prints log paths on their own lines.
  - `python/envctl_engine/runtime/engine_runtime_debug_support.py` prints bundle paths on their own lines.
  - `python/envctl_engine/debug/doctor_orchestrator.py` prints `runtime_gap_report_path` as an inline field.
  - `python/envctl_engine/runtime/prompt_install_support.py:_print_install_results` embeds install and backup paths inline in one status line.
  - `python/envctl_engine/runtime/hook_migration_support.py:run_hook_migration` prints `Wrote {path}` inline.
  - `python/envctl_engine/config/command_support.py:_run_headless_config_command` already prints the config path on a separate line, but `run_config_command` prints `result.message`, whose `_save_message(...)` format is inline.
- Path-bearing startup warnings also remain inline/plain:
  - `python/envctl_engine/startup/service_bootstrap_domain.py:_run_backend_migration_step` prints `backend log:` and then the path on a following line only in the fallback branch; the structured warning path still uses an inline message string.
- The repo already tolerates OSC escape sequences in parsing layers:
  - `python/envctl_engine/test_output/parser_base.py:strip_ansi` explicitly strips ANSI OSC sequences, and `tests/python/shared/test_utility_consolidation_contract.py` covers OSC cleanup.
- Relevant config/docs evidence:
  - `docs/developer/ui-and-interaction.md` describes UI behavior as policy-driven and split across output backends.
  - `docs/reference/configuration.md` documents `ENVCTL_UI_COLOR_MODE` / `ENVCTL_UI_COLOR` and other interactive policy knobs, but there is no existing hyperlink policy key.
  - `docs/reference/commands.md` documents the command families that expose these artifact paths, but does not define any path-clickability contract.

## Root cause(s) / gaps
- Path rendering is duplicated across many modules, so clickability depends on incidental formatting instead of an explicit product contract.
- There is no terminal hyperlink capability policy analogous to `colors_enabled(...)`, so call sites cannot consistently decide when to emit richer path markup and when to fall back to plain text.
- Different output substrates are handled inconsistently:
  - plain `print(...)`
  - Rich table/panel rendering
  - returned message strings that are later printed elsewhere
- Existing tests lock in raw path presence but do not define a stronger contract for hyperlink-safe rendering, so regressions are invisible until a human notices them.
- Inline status lines such as `codex: installed <path> (backup: <path>)` and `runtime_gap_report_path: <path>` are especially dependent on terminal auto-link heuristics today and are the most likely to remain non-clickable.

## Plan
### 1) Introduce one shared path-rendering policy and helper layer
- Add a dedicated terminal path-link helper module under the shared UI/output policy area, for example `python/envctl_engine/ui/path_links.py`.
- The helper should centralize:
  - displayed path normalization, including the existing `/private/tmp` to `/tmp` cleanup now buried in `python/envctl_engine/actions/project_action_domain.py:_display_path`
  - conversion from filesystem paths to `file://` URIs for hyperlink-capable terminals
  - plain terminal rendering that can wrap the visible path text in OSC-8 sequences when enabled
  - Rich rendering for table/panel flows by returning `rich.text.Text` with a `link` style instead of a raw string
  - a no-op fallback that returns the same visible text when hyperlinks are disabled or unsupported
- Keep the helper input focused on presentation only. It must not mutate stored metadata or resolve paths back into state.

### 2) Define a conservative hyperlink capability contract
- Add a user-facing environment policy key, following the repo's existing `auto|on|off` convention from `python/envctl_engine/ui/color_policy.py`.
- Recommended shape:
  - `ENVCTL_UI_HYPERLINK_MODE=auto|on|off`
  - default `auto`
- `auto` should enable hyperlink wrapping only when stdout is an interactive TTY and the terminal is known or inferred to tolerate hyperlink output safely.
- `off` should force plain raw text for CI, logs, file redirection, or terminals that render OSC sequences poorly.
- `on` should force hyperlink output for verification and power users.
- Preserve JSON output as raw strings regardless of hyperlink mode.
- Do not tie hyperlink behavior to `NO_COLOR`; link policy is separate from color policy.

### 3) Apply the helper to the highest-value direct path surfaces first
- Update the direct print-path call sites where envctl already emits a dedicated path line or a dedicated path field:
  - `python/envctl_engine/ui/dashboard/rendering.py:_print_dashboard_service_row`
  - `python/envctl_engine/ui/dashboard/rendering.py:_print_dashboard_tests_row`
  - `python/envctl_engine/ui/dashboard/orchestrator.py:_print_test_failure_details`
  - `python/envctl_engine/ui/dashboard/orchestrator.py:_print_project_action_failure_details`
  - `python/envctl_engine/actions/action_command_orchestrator.py:_print_test_suite_summary`
  - `python/envctl_engine/runtime/engine_runtime_misc_support.py:print_logs`
  - `python/envctl_engine/runtime/inspection_support.py:_print_state`
  - `python/envctl_engine/runtime/engine_runtime_debug_support.py:debug_pack`
  - `python/envctl_engine/runtime/engine_runtime_debug_support.py:debug_last`
  - `python/envctl_engine/runtime/engine_runtime_debug_support.py:debug_report`
  - `python/envctl_engine/config/command_support.py:_run_headless_config_command`
  - `python/envctl_engine/startup/service_bootstrap_domain.py:_run_backend_migration_step`
- For these surfaces, keep the visible text unchanged after ANSI/OSC stripping so current tests and human readability stay intact.

### 4) Normalize inline path-bearing status lines instead of leaving them to autolink heuristics
- Convert inline path status lines to use the shared helper rather than raw string concatenation:
  - `python/envctl_engine/debug/doctor_orchestrator.py:DoctorOrchestrator.execute` for `runtime_gap_report_path`
  - `python/envctl_engine/runtime/inspection_support.py:_print_show_config` for `config_file`
  - `python/envctl_engine/runtime/prompt_install_support.py:_print_install_results` for install and backup paths
  - `python/envctl_engine/runtime/hook_migration_support.py:run_hook_migration` for `Wrote ...`
  - `python/envctl_engine/config/wizard_domain.py:_save_message` or the print site in `python/envctl_engine/config/command_support.py:run_config_command`
  - review output headings/body text in `python/envctl_engine/actions/project_action_domain.py:_print_review_completion`
- Where the path is currently buried inside prose, prefer one of two consistent patterns:
  - split the path onto its own line when the output already reads like a mini section
  - or wrap only the path fragment with the hyperlink helper while keeping the sentence text unchanged
- Avoid changing error semantics or introducing extra lines where tests or command consumers depend on compact output unless the command is explicitly human-facing.

### 5) Add Rich-aware path rendering for review output
- Extend `python/envctl_engine/actions/project_action_domain.py:_print_review_completion_rich` so the `Output`, `Summary`, and `Bundle` rows use Rich link-styled text rather than plain strings.
- Keep plain fallback output in `_print_review_completion(...)` aligned with the same shared helper so both branches expose the same visible path text.
- Preserve `_display_path` behavior by moving it into the shared helper or replacing it there.

### 6) Sweep remaining returned-message path surfaces and decide whether they should become structured
- Audit path-bearing strings that are returned instead of printed directly, especially:
  - `python/envctl_engine/state/action_orchestrator.py` log-clear messages
  - `python/envctl_engine/runtime/engine_runtime_service_truth.py:service_listener_failure_detail`
  - commit-ledger and commit-message path errors in `python/envctl_engine/actions/project_action_domain.py`
- For this task, only convert returned strings that are genuinely operator-facing in normal CLI output and can use the shared inline helper safely.
- Leave deep internal/state-only strings unchanged if they are primarily event payloads or intermediary data rather than direct terminal UX.

### 7) Document the new contract and override
- Update reference docs for the new policy key and operator behavior:
  - `docs/reference/configuration.md`
  - `docs/reference/important-flags.md`
- Add one short note to the user-facing runtime/UI docs that envctl now emits clickable local artifact paths in interactive output when hyperlink mode is enabled or auto-detected:
  - `docs/developer/ui-and-interaction.md`
  - if needed, `docs/user/python-engine-guide.md`
- Keep the docs explicit that JSON output remains raw.

## Tests (add these)
### Backend tests
- Add a focused helper test module, for example `tests/python/ui/test_path_links.py`:
  - `auto` vs `on` vs `off`
  - non-TTY fallback to plain text
  - `file://` URI generation from absolute and normalized paths
  - visible text remains unchanged after `strip_ansi(...)`
  - Rich link rendering returns plain visible text plus link metadata when Rich is available
- Extend `tests/python/ui/test_dashboard_rendering_parity.py`:
  - assert `tests:` and `log:` visible text is unchanged after stripping ANSI/OSC
  - add a forced-hyperlink mode case that checks raw output contains hyperlink escape/link markup while `strip_ansi(...)` still shows the same path text
- Extend `tests/python/ui/test_dashboard_orchestrator_restart_selector.py`:
  - failed test summary path output
  - failed action report path output
- Extend `tests/python/actions/test_actions_parity.py`:
  - `Test Suite Summary` failure summary line/path remains visible and hyperlink-wrapped under forced mode
- Extend `tests/python/actions/test_actions_cli.py`:
  - review plain-output branch
  - review Rich-output branch
- Extend `tests/python/runtime/test_engine_runtime_misc_support.py`:
  - `logs` command path line remains visible and link-wrapped when enabled
- Extend `tests/python/runtime/test_engine_runtime_debug_support.py`:
  - `debug-pack`, `debug-last`, and `debug-report` bundle path output
- Extend `tests/python/runtime/test_prompt_install_support.py`:
  - non-JSON install output path and backup path formatting
- Extend `tests/python/config/test_config_command_support.py`:
  - plain `config --set` output path line under hyperlink mode
- Extend `tests/python/runtime/test_engine_runtime_command_parity.py` or add a small inspection-support-specific test:
  - `show-config` / doctor field output remains visible and hyperlink-capable without affecting JSON mode

### Frontend tests
- None in the web-frontend sense.
- If Textual widget support is included in implementation after verification, add targeted Textual-screen coverage there; otherwise keep this slice on the Python CLI/dashboard rendering path only.

### Integration/E2E tests
- Manual terminal verification in at least one real interactive terminal that the team actually uses, for example Apple Terminal, iTerm2, or VS Code terminal:
  1. Run `envctl dashboard` and verify `log:` and `tests:` paths are clickable.
  2. Trigger a failing `envctl test` and verify `failure summary:` path is clickable.
  3. Run `envctl review --project <target>` and verify output directory, summary, and bundle paths are clickable in both plain and Rich-capable environments.
  4. Run `envctl debug-pack` and `envctl show-state` and verify bundle/state paths are clickable.
  5. Re-run one command with `ENVCTL_UI_HYPERLINK_MODE=off` and confirm paths degrade cleanly to plain text.

## Observability / logging (if relevant)
- No new runtime state fields are needed.
- If capability decisions are non-trivial, emit one bounded diagnostic event or debug field for hyperlink policy selection, for example:
  - `ui.path_links.selected`
  - `mode=auto|on|off`
  - `enabled=true|false`
  - `reason=non_tty|forced_on|forced_off|terminal_unsupported|terminal_supported`
- Keep this diagnostic optional and bounded; do not add hyperlink escape sequences to event payloads or persisted state.

## Rollout / verification
- Implementation order:
  1. add the shared helper and tests for policy/formatting
  2. convert direct path-line surfaces
  3. convert inline status/path surfaces
  4. convert Rich review output
  5. update docs and verification notes
- Verification commands:
  - `PYTHONPATH=python python3 -m unittest tests.python.ui.test_dashboard_rendering_parity tests.python.ui.test_dashboard_orchestrator_restart_selector`
  - `PYTHONPATH=python python3 -m unittest tests.python.actions.test_actions_parity tests.python.actions.test_actions_cli`
  - `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_engine_runtime_misc_support tests.python.runtime.test_engine_runtime_debug_support tests.python.runtime.test_prompt_install_support`
  - `PYTHONPATH=python python3 -m unittest tests.python.config.test_config_command_support tests.python.runtime.test_engine_runtime_command_parity`
- Manual verification should happen in a real terminal because hyperlink rendering is terminal-dependent even when unit tests pass.

## Definition of done
- Interactive envctl outputs that surface actionable filesystem paths now use one shared path-rendering policy instead of raw ad hoc `print(str(path))` calls.
- The visible text of those paths remains stable after stripping ANSI/OSC, so existing human readability and parser cleanup assumptions still hold.
- JSON outputs and persisted state/report artifacts remain raw and unchanged.
- Review plain output and Rich output both expose clickable artifact paths.
- Docs describe the new hyperlink policy and override.
- Automated tests cover the shared helper plus representative dashboard, action, runtime, and config call sites.

## Risk register (trade-offs or missing tests)
- OSC-8 hyperlink support varies by terminal.
  - Mitigation: conservative `auto` mode plus explicit `on`/`off` override and manual real-terminal verification.
- Rich and plain terminal outputs need different rendering mechanics.
  - Mitigation: keep one shared policy module with separate plain-string and Rich-text adapters rather than duplicating logic in call sites.
- Some current outputs are returned as free-form strings instead of structured path fields.
  - Mitigation: convert only operator-facing returned messages in this slice; do not force a large message-contract refactor unless a concrete surface requires it.
- Textual screen support is not yet verified from repo evidence.
  - Mitigation: keep the guaranteed scope on plain CLI/dashboard and Rich console flows first; treat Textual widget-specific hyperlink rendering as a follow-up if testing shows the same helper cannot be applied safely there.
- Tests that assert raw output may become brittle once escape sequences are introduced.
  - Mitigation: normalize with `strip_ansi(...)` in path-output assertions and add explicit raw-output checks only where hyperlink presence matters.

## Open questions (only if unavoidable)
- None.
