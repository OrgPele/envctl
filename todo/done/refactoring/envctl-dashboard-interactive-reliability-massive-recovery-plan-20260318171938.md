# Envctl Dashboard Interactive Reliability Massive Recovery Plan

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Make dashboard interaction reliable in real TTY sessions (local terminal, tmux, SSH) with deterministic key capture, submit behavior, selector behavior, and command execution flow.
  - Restore feature parity and usability between dashboard presentation and command loop semantics so options are always visible and actions are discoverable.
  - Eliminate split-brain interactive behavior across Textual app, legacy command loop, and selector paths.
  - Add hard evidence tooling for UI bugs so failures are diagnosable from artifacts instead of repeated manual repro attempts.
- Non-goals:
  - Rewriting service/requirements business orchestration semantics not directly tied to interactive UX reliability.
  - Changing top-level CLI command names/flags.
  - Removing non-interactive output paths.
- Assumptions:
  - Textual remains required for interactive UI backend when TTY capability exists (`python/requirements.txt` includes `textual`).
  - Rich remains required spinner/status backend.
  - Supportopia-style workflow (`/Users/kfiramar/projects/supportopia`) remains the primary manual validation target.

## Goal (user experience)
Running `envctl` (or `envctl --debug-ui`) in a real repository should open a responsive dashboard where typed characters always appear, Enter is processed exactly once, target selectors are consistent and non-duplicative, command options are clearly shown in the UI, and long-running actions show clear progress with no input corruption or hidden state transitions.

## Business logic and data model mapping
- Interactive backend selection and runtime wiring:
  - `python/envctl_engine/engine_runtime.py:PythonEngineRuntime.__init__`, `_run_interactive_dashboard_loop`, `_current_ui_backend`
  - `python/envctl_engine/ui/backend_resolver.py:resolve_ui_backend_with_capabilities`
  - `python/envctl_engine/ui/backend.py:build_interactive_backend`, `TextualInteractiveBackend`, `NonInteractiveBackend`
- Dashboard loop and command intake:
  - Textual: `python/envctl_engine/ui/textual/app.py:run_textual_dashboard_loop`
  - Legacy loop: `python/envctl_engine/ui/command_loop.py:run_dashboard_command_loop`
  - Dispatch parser and route semantics: `python/envctl_engine/dashboard_orchestrator.py:_run_interactive_command`, `python/envctl_engine/command_router.py:parse_route`
- Selector flows:
  - Textual selector: `python/envctl_engine/ui/textual/screens/selector.py`
  - Selector model/dedupe: `python/envctl_engine/ui/selector_model.py`
  - Call sites: `python/envctl_engine/dashboard_orchestrator.py`, `python/envctl_engine/action_command_orchestrator.py`, `python/envctl_engine/state_action_orchestrator.py`, `python/envctl_engine/lifecycle_cleanup_orchestrator.py`
- Terminal input and TTY state handling:
  - `python/envctl_engine/ui/terminal_session.py:TerminalSession.read_command_line`, `_read_command_line_basic`, `_read_command_line_fallback`, `_ensure_tty_line_mode`, `restore_terminal_after_input`
  - `python/envctl_engine/terminal_ui.py:RuntimeTerminalUI.flush_pending_interactive_input`
- Spinner/status rendering:
  - `python/envctl_engine/ui/spinner_service.py`, `python/envctl_engine/ui/spinner.py`
  - Runtime call sites: `startup_orchestrator.py`, `resume_orchestrator.py`, `action_command_orchestrator.py`, `lifecycle_cleanup_orchestrator.py`, `ui/command_loop.py`
- Debug and diagnostics:
  - `python/envctl_engine/ui/debug_flight_recorder.py`
  - `python/envctl_engine/debug_bundle.py`
  - `scripts/analyze_debug_bundle.py`

## Current behavior (verified in code)
- Textual dashboard is currently a minimal shell and not behaviorally equivalent to legacy command loop UX:
  - `python/envctl_engine/ui/textual/app.py` renders snapshot + one input field + footer only.
  - Legacy command group hints (`Lifecycle/Actions/Inspect`) live in `python/envctl_engine/ui/command_loop.py`, not in Textual screen widgets.
- Interactive implementation is split across two stacks with divergent contracts:
  - Textual backend in `ui/textual/app.py`.
  - Legacy loop in `ui/command_loop.py` still active in code and tested.
- Selector stack is partially migrated but still functionally brittle:
  - `ui/textual/screens/selector.py` uses list/filter/toggle semantics, but caller expectations still vary across orchestrators.
- Terminal input pipeline has multiple backend paths and explicit flush operations that can race with user typing:
  - `ui/terminal_session.py` fallback path calls `termios.tcflush(..., TCIFLUSH)` before reads.
  - Interactive command paths call `RuntimeTerminalUI.flush_pending_interactive_input()` before selector prompts.
- Debug bundle diagnostics still report missing TTY transition evidence in real sessions:
  - `debug_bundle.py:_write_diagnostics` adds “TTY transition events missing” when no `ui.tty.transition` events in timeline.
  - `debug_flight_recorder.py` supports tty transition artifacts, but this signal is not consistently populated in the Textual path.
- Test coverage does not currently prove real interactive behavior:
  - `tests/bats/python_interactive_input_reliability_e2e.bats` validates non-TTY fallback only.
  - No BATS suite currently validates real Textual key submit/focus/selector behavior end-to-end.

## Root cause(s) / gaps
- Primary gap: **incomplete Textual migration**. Presentation/input moved, but UX parity and interaction contracts were not fully ported from legacy loop.
- Primary gap: **multi-path interactive control flow**. Different code paths enforce different flush/read/focus semantics, creating inconsistent behavior and hard-to-reproduce bugs.
- Primary gap: **insufficient end-to-end test surface**. Unit tests pass but do not cover real terminal semantics where failures happen.
- Secondary gap: **telemetry blind spots for Textual path**. DFR exists but cannot always explain key-loss/focus anomalies due to incomplete event coverage.
- Secondary gap: **status rendering contention** between spinner/progress output and interactive input phases.

## Plan
### 1) Freeze and simplify interactive backend contract (single authority)
- Make Textual backend the single interactive authority for supported TTY.
- Constrain legacy command loop to explicit compatibility mode only (`ENVCTL_UI_BACKEND=legacy_compat`) and stop invoking it in `auto` mode.
- In `engine_runtime.py`, enforce strict selection invariant: one backend per session (no mid-session backend switching) and emit `ui.backend.selected` once with immutable session-level reason.
- Add explicit guard event `ui.backend.invariant_violation` when runtime attempts to switch backend after loop starts.

### 2) Rebuild Textual dashboard UX parity surface
- Refactor `ui/textual/app.py` into componentized screens/widgets:
  - dashboard header, service summary panel, command groups panel, input panel, status panel.
- Port legacy command visibility contract into Textual UI:
  - lifecycle/actions/inspect group hints always visible.
  - command aliases visible and validated against router support map.
- Replace implicit stdout capture for command status with explicit status widget updates tied to command lifecycle events.

### 3) Enforce single-submit and focus ownership contract
- Add explicit state machine in Textual dashboard for command input lifecycle:
  - `idle -> submitting -> dispatching -> refreshing -> idle`.
- During `dispatching`, lock command input widget and prevent duplicate submit events.
- Explicitly restore focus to input after every dispatch (success/failure/cancel paths).
- Instrument events:
  - `ui.input.focus.changed`, `ui.input.submit.accepted`, `ui.input.submit.rejected_duplicate`, `ui.input.dispatch.completed`.

### 4) Eliminate flush-race behavior for interactive commands
- Remove unconditional `flush_pending_interactive_input()` calls from interactive selector entry paths in:
  - `dashboard_orchestrator.py`
  - `action_command_orchestrator.py`
  - `state_action_orchestrator.py`
  - `lifecycle_cleanup_orchestrator.py`
- Replace with scoped stale-input mitigation:
  - only clear buffered input when backend reports stale escape fragments and no active command token.
- Add structured flush metrics event `ui.input.flush.decision` including `reason`, `bytes_dropped`, `source`.

### 5) Unify selector behavior and dedupe policy across commands
- Keep `selector_model.py` as canonical target source and extend suppression rules for edge cases:
  - one real target => zero synthetic shortcuts.
  - duplicated scope signatures removed deterministically with emitted reason.
- Apply same selector interaction model for restart/stop/logs/errors/test/pr/commit/analyze/migrate.
- Add command-specific empty-state UX:
  - `No <command> target available.`
  - no silent returns.

### 6) Harden Textual selector interaction reliability
- Refactor `ui/textual/screens/selector.py` to avoid implicit selection side effects on list row focus changes.
- Add explicit confirm/cancel state transitions with button + keyboard parity.
- Ensure Enter behavior is consistent in both single-select and multi-select modes.
- Add deterministic keyboard map diagnostics (Arrow/Enter/Space/Esc/Ctrl+A).

### 7) Resolve spinner/input contention policy
- Keep spinner/status outside interactive input focus windows.
- In Textual sessions, use Textual-native status/progress widgets only; suppress terminal spinner writes.
- In non-interactive sessions, keep Rich spinner path.
- Add policy events:
  - `ui.spinner.policy`
  - `ui.spinner.disabled` with reason `textual_input_guard` when suppressed for focus safety.

### 8) Expand DFR for Textual causality
- Add mandatory Textual event coverage:
  - `ui.screen.enter/exit`, `ui.screen.refresh`, `ui.input.key`, `ui.input.submit`, `ui.selector.open/confirm/cancel`, `ui.focus.transition`.
- Add tty-state transition capture at session boundaries even in Textual mode.
- Upgrade `debug_bundle.py` diagnostics to rank hypotheses for:
  - duplicate submit
  - dropped key bursts
  - focus loss before submit
  - stale flush/drop anomalies.

### 9) Add interactive latency profiling and startup/restore budget reporting
- Extend startup/resume timing output with dashboard render and first-input-ready timings:
  - `interactive.bootstrap.total_ms`, `interactive.first_focus_ms`, `interactive.first_submit_latency_ms`.
- Emit per-stage restore/start metrics in a machine-readable artifact to compare “slow restore” sessions.

### 10) Build real interactive E2E coverage (TTY-backed)
- Introduce PTY-driven E2E tests for interactive dashboard (not non-TTY fallback):
  - key typing and echo reliability.
  - single Enter executes once.
  - selector confirm/cancel semantics.
  - restart/test flow invocation from dashboard.
- Add deterministic fixture harness to avoid flaky CI timing drift.

### 11) Add regression gates for UX parity
- Add shipability gate checks that fail when:
  - no interactive TTY E2E suite is executed.
  - Textual dashboard command group hints regress.
  - DFR bundle missing key causal streams (`ui.input.submit`, `ui.selector.*`, `ui.focus.transition`).
- Surface these in `doctor` output as UI-readiness gates.

### 12) Cleanup and retirement
- After parity and E2E gates pass for 2 consecutive cycles:
  - deprecate/remove legacy interactive loop path from default code path.
  - delete obsolete prompt_toolkit/basic-input selector/menu branches no longer used by runtime.
  - preserve non-interactive fallback only.

## Tests (add these)
### Backend tests
- Add `tests/python/test_textual_dashboard_input_contract.py`:
  - single-submit guard, duplicate-enter suppression, focus restoration.
- Add `tests/python/test_textual_dashboard_command_groups.py`:
  - command sections visible and aligned with supported router commands.
- Extend `tests/python/test_textual_selector_flow.py`:
  - Enter/Space behavior parity, list-focus edge cases, empty-state behavior.
- Extend `tests/python/test_selector_model.py`:
  - strict no-duplicate-scope policy including single-target suppression.
- Add `tests/python/test_interactive_flush_policy.py`:
  - no unconditional flush before selectors, decision events emitted.
- Extend `tests/python/test_terminal_session_debug.py` and `tests/python/test_debug_bundle_generation.py`:
  - Textual-specific input/focus/selector events and diagnosis coverage.
- Extend `tests/python/test_ui_backend_runtime_wiring.py`:
  - backend immutability during session and invariant event on attempted switch.

### Frontend tests
- Add Textual snapshot/render contract tests for dashboard widgets:
  - `tests/python/test_textual_dashboard_rendering_contract.py`.
- Add Textual widget interaction tests for selector filtering and click/keyboard parity:
  - `tests/python/test_textual_selector_widget_contract.py`.

### Integration/E2E tests
- Add `tests/bats/python_textual_dashboard_input_e2e.bats`:
  - typed characters registered and echoed reliably.
- Add `tests/bats/python_textual_dashboard_single_enter_e2e.bats`:
  - Enter processed once per command.
- Add `tests/bats/python_textual_selector_reliability_e2e.bats`:
  - restart/stop/test selector open-confirm-cancel behavior.
- Add `tests/bats/python_textual_dashboard_options_visibility_e2e.bats`:
  - command group/options visible in dashboard view.
- Extend `tests/bats/python_interactive_input_reliability_e2e.bats`:
  - keep fallback coverage but add true interactive coverage path.

## Observability / logging (if relevant)
- Required events to emit in all interactive sessions:
  - `ui.backend.selected`
  - `ui.screen.enter`, `ui.screen.exit`, `ui.screen.refresh`
  - `ui.input.read.begin/end`, `ui.input.submit.accepted/rejected_duplicate`, `ui.input.dispatch.begin/end`
  - `ui.focus.transition`
  - `ui.selector.open/confirm/cancel`
  - `ui.spinner.policy`, `ui.spinner.disabled`
  - `ui.input.flush.decision`
- Required debug bundle artifacts:
  - `timeline.jsonl` with command_id correlation
  - `command_index.json`
  - `diagnostics.json` with ranked hypotheses and evidence seq IDs

## Rollout / verification
- Phase A (stabilize contracts): Steps 1-4.
  - Verify with unit tests + manual supportopia repro.
- Phase B (selector + spinner harmonization): Steps 5-7.
  - Verify with interactive PTY tests + manual restart/test/logs flows.
- Phase C (DFR + latency diagnostics): Steps 8-9.
  - Verify debug-report quality and actionable root-cause output.
- Phase D (E2E gates + cleanup): Steps 10-12.
  - Verify shipability and doctor readiness gates.
- Verification commands:
  - `cd /Users/kfiramar/projects/envctl && ./.venv/bin/python -m pytest -q tests/python/test_textual_dashboard_rendering_safety.py tests/python/test_interactive_input_reliability.py tests/python/test_textual_selector_flow.py tests/python/test_selector_model.py tests/python/test_terminal_session_debug.py tests/python/test_debug_bundle_generation.py`
  - `cd /Users/kfiramar/projects/envctl && bats tests/bats/python_interactive_input_reliability_e2e.bats`
  - `cd /Users/kfiramar/projects/supportopia && ENVCTL_DEBUG_UI_MODE=deep ENVCTL_DEBUG_RESTORE_TIMING=true /Users/kfiramar/projects/envctl/bin/envctl --debug-ui`
  - `cd /Users/kfiramar/projects/supportopia && /Users/kfiramar/projects/envctl/bin/envctl --debug-pack --scope-id repo-b15e3f0c8257`
  - `cd /Users/kfiramar/projects/supportopia && /Users/kfiramar/projects/envctl/bin/envctl --debug-report --scope-id repo-b15e3f0c8257`

## Definition of done
- Dashboard input is reliable in real TTY sessions: no dropped characters, no duplicate-enter requirement, no hidden focus state.
- Dashboard always shows actionable command options and status context.
- Selector UX is consistent across all commands and free of duplicate/non-useful synthetic options.
- Spinner/status output never corrupts interactive input.
- Debug bundles provide sufficient evidence to diagnose interactive issues without rerun.
- Interactive PTY-backed tests exist and are enforced by gates.

## Risk register (trade-offs or missing tests)
- Risk: large interactive refactor may regress stable non-interactive flows.
  - Mitigation: strict backend boundary and non-interactive regression suite in every phase.
- Risk: PTY-driven tests can be flaky on CI runners.
  - Mitigation: deterministic harness, retries with bounded timing windows, CI environment capability checks.
- Risk: deeper telemetry can increase overhead in deep debug mode.
  - Mitigation: default debug off, bounded ring buffers, sample-rate controls.
- Risk: forcing Textual as sole interactive authority may expose unsupported terminal edge cases.
  - Mitigation: explicit non-interactive fallback with clear diagnostics and backend reason reporting.

## Open questions (only if unavoidable)
- Should unsupported Textual terminals fail hard in interactive mode, or auto-fallback to non-interactive snapshot + explicit warning? Current recommendation: fallback to non-interactive with clear reason to preserve safety.
