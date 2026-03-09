# Envctl Interactive Debug Flight Recorder Plan

## Why this plan exists
Users are reporting interactive bugs that are real in their TTY/tmux sessions but hard to reproduce in automated environments. The most painful symptom is typed characters not appearing or command input behaving inconsistently. We need a deep, shareable, privacy-safe debug mode that captures enough truth from the user's real terminal session to diagnose root causes quickly.

This plan defines a "Debug Flight Recorder" (DFR) for interactive input, menu handling, terminal state transitions, and rendering paths.

## Goals / non-goals / assumptions

### Goals
- Capture high-fidelity interactive diagnostics from real user sessions (tmux/SSH/local terminal) with minimal repro friction.
- Produce a deterministic bug bundle users can send without manual copy/paste of random logs.
- Correlate input pipeline stages end-to-end: raw bytes -> key decoding -> sanitization -> dispatch -> UI/render side effects.
- Preserve current behavior when debug mode is off.
- Reuse existing artifacts and debug conventions (`events.jsonl`, `RUN_SH_DEBUG`, runtime scope directories).

### Non-goals
- Replacing all observability systems project-wide.
- Streaming diagnostics to remote services.
- Logging secrets or full unrestricted command payloads by default.

### Assumptions
- Python runtime remains default interactive runtime.
- Existing shell debug flags must continue to work.
- Users can run one extra command to generate a bug bundle.

## Business logic and data model mapping
- Routing/parsing surfaces:
  - `python/envctl_engine/command_router.py:parse_route` (unknown options currently fail fast; default command behavior is `start`).
  - `python/envctl_engine/engine_runtime.py:dispatch` (explicit command-to-orchestrator routing; no current debug-pack route).
- Interactive input lifecycle:
  - `python/envctl_engine/ui/command_loop.py:run_dashboard_command_loop`.
  - `python/envctl_engine/ui/terminal_session.py:TerminalSession.read_command_line` and fallback helpers.
  - `python/envctl_engine/dashboard_orchestrator.py:_sanitize_interactive_input`.
  - `python/envctl_engine/planning_menu.py` legacy raw key path.
- Event persistence model:
  - in-memory append via `python/envctl_engine/engine_runtime.py:_emit`.
  - snapshot persistence into `events.jsonl` via `python/envctl_engine/state_repository.py:save_run` and runtime snapshot helpers.
- Existing raw command emission risk:
  - `python/envctl_engine/ui/command_loop.py` emits `ui.input.submit` with a raw command slice today.
- Parallel emission risk:
  - startup uses thread pool in `python/envctl_engine/startup_orchestrator.py`, so sequence assignment/writes must be synchronized.

## Goal (user experience)
When a user experiences interactive input bugs, they can run envctl in debug-flight-recorder mode, reproduce once, run one "pack" command, and share a single bundle containing structured event timeline, terminal context, focused input traces, and diagnostics metadata.

## Current behavior (verified in code)
- Interactive command input currently flows through `python/envctl_engine/ui/command_loop.py:run_dashboard_command_loop`, `python/envctl_engine/ui/terminal_session.py:TerminalSession.read_command_line`, and `python/envctl_engine/dashboard_orchestrator.py:_sanitize_interactive_input`.
- Runtime events are accumulated in memory and persisted as snapshots via `python/envctl_engine/engine_runtime.py:_emit` and `python/envctl_engine/state_repository.py:save_run` / `python/envctl_engine/engine_runtime.py:_persist_events_snapshot`.
- Planning interactive flow still has a legacy raw-key path in `python/envctl_engine/planning_menu.py` (`_run_legacy`, `read_key`, `flush_pending_input`) where decode/flush races are most likely.
- Existing debug knobs (`--debug-trace`, `--key-debug`, `RUN_SH_DEBUG*`) are shell-first and do not provide a unified Python interactive stage timeline.

## Current telemetry baseline (already present)

### Existing useful pieces
- Structured event collection via `PythonEngineRuntime._emit` and persisted `events.jsonl`.
- Runtime artifact structure under `${RUN_SH_RUNTIME_DIR}/python-engine/<scope-id>/`.
- Shell-side debug facilities:
  - `--debug-trace`, `--debug-trace-log`, `--debug-trace-no-xtrace`, `--debug-trace-no-stdio`, `--debug-trace-no-interactive`
  - `--key-debug`
  - `RUN_SH_DEBUG*`, `KEY_DEBUG*`
- Existing high-level backend events (`ui.input.backend`, `ui.menu.backend`, `ui.spinner.backend`, `probe.backend`).

### Key gaps
- No single correlated input timeline across read/sanitize/dispatch.
- No byte/escape-sequence-level trace for Python input paths.
- No unified tmux/TTY environment snapshot attached to the same session timeline.
- No one-command "bundle" UX for sharing diagnostics.
- No anomaly tagging (e.g., dropped input, escape-timeout, repeated-char burst, flush race).

## Root cause(s) / gaps
### Confirmed gaps
1. No correlated stage timeline across Python read/sanitize/dispatch/render stages.
2. No low-level deep capture for Python key/escape/flush behavior in real tmux/TTY sessions.
3. No one-command, privacy-safe debug bundle flow for user handoff.
4. Existing event persistence is snapshot-oriented; debug evidence can be weaker than incremental append-style traces.

### Root-cause hypotheses to explicitly test
1. Input bytes consumed/cleared by flush logic before command read.
2. Escape-sequence timing races (tmux latency + short timeouts).
3. Terminal mode transitions (raw/canonical/echo) not restored consistently.
4. Prompt-toolkit and fallback paths diverge in normalization/sanitization behavior.
5. Spinner/status writes interleave with prompt redraw and hide visible input.
6. CPR/bracketed-paste/terminal-capability mismatch causes key handling anomalies.

## Architecture: Debug Flight Recorder (DFR)

### Modes
- `off` (default): no extra overhead beyond current events.
- `standard`: stage-level structured events with redacted payloads.
- `deep`: includes low-level key/byte and tty-state transitions with rate limits.

### Recommended defaults
- `ENVCTL_DEBUG_UI_MODE=standard` when explicitly enabled via `--debug-ui` or `--debug-trace`.
- `ENVCTL_DEBUG_UI_MODE=deep` only for focused reproduction sessions.
- `ENVCTL_DEBUG_UI_CAPTURE_PRINTABLE=false` by default in all modes.
- `ENVCTL_DEBUG_UI_MAX_EVENTS=20000`, `ENVCTL_DEBUG_UI_RING_BYTES=32768`.

### Activation surfaces
- New CLI surfaces (proposed):
  - `--debug-ui` -> DFR standard mode (flag on normal commands)
  - `--debug-ui-deep` -> DFR deep mode (flag on normal commands)
  - `debug-pack` -> dedicated command alias for packing (recommended)
  - optional legacy compatibility: `--debug-ui-pack` maps internally to `debug-pack`
- New env vars (proposed):
  - `ENVCTL_DEBUG_UI_MODE=off|standard|deep`
  - `ENVCTL_DEBUG_UI_PATH=<dir>` (optional custom output root)
  - `ENVCTL_DEBUG_UI_CAPTURE_PRINTABLE=false|true` (default false)
  - `ENVCTL_DEBUG_UI_RING_BYTES=32768`
  - `ENVCTL_DEBUG_UI_MAX_EVENTS=20000`
  - `ENVCTL_DEBUG_UI_SAMPLE_RATE=1` (every event by default)
- Compatibility mapping:
  - `--debug-trace` implicitly enables `ENVCTL_DEBUG_UI_MODE=standard` when Python runtime is active.
  - `--key-debug` maps to `ENVCTL_DEBUG_UI_MODE=deep` plus key-level category enabled.

### Command-surface contract (must implement)
- `debug-pack` is a first-class routed command (same level as `doctor`, `logs`, etc.), not startup flow.
- `debug-pack` must never trigger startup orchestration.
- Parser behavior:
  - unknown debug-ui options remain hard failures (consistent with current router strictness),
  - `--debug-ui-pack` is normalized to `debug-pack` before dispatch,
  - positional fallback to `start` is bypassed for `debug-pack`.
- Dispatcher behavior:
  - add explicit `route.command == "debug-pack"` branch in runtime dispatch,
  - command returns deterministic exit codes for selection/pack errors without side effects on services.

### Output location
- Default DFR root: `${RUN_SH_RUNTIME_DIR}/python-engine/<scope-id>/debug/`
- Session directory: `debug/session-<utc>-<pid>-<shortid>/`
- Symlink or pointer to latest: `debug/latest`

### Session artifacts
- `events.debug.jsonl` (DFR-specific high/detail events)
- `events.runtime.redacted.jsonl` (sanitized copy of runtime events used for sharing)
- `tty_context.json` (terminal/tmux/ssh/process metadata)
- `tty_state_transitions.jsonl` (raw/canonical changes and diffs)
- `input_ring.hex` (deep-mode bounded ring buffer of recent raw bytes)
- `anomalies.jsonl` (heuristic-detected suspicious patterns)
- `summary.md` (human-readable timeline + top anomalies)
- `doctor.txt` (optional captured `envctl --doctor` output)
- `manifest.json` (file list, hashes, redaction mode, version)

### Persistence strategy (critical)
- Recorder writes debug events incrementally (append mode) during session, not only at run-end snapshots.
- Flush policy: periodic buffered flush plus forced flush on interactive loop exit and exception path.
- Preserve current runtime snapshot events, but treat append-only DFR stream as primary evidence for input races.

### Thread safety and ordering contract
- Sequence ids must be generated from a per-session atomic counter guarded by a lock.
- Event append and file writes must be synchronized (single writer lock) to prevent interleaving under parallel startup workers.
- `seq` ordering is the source of truth; wall-clock timestamps are informational only.
- Recorder must remain correct when events originate from thread pool work in startup paths.

## Event model (required schema)

### Common fields (every DFR event)
- `event` string
- `ts_wall` ISO-8601 UTC
- `ts_mono_ns` monotonic nanoseconds
- `seq` incrementing per-session integer
- `session_id` string
- `run_id` string or null
- `pid` int
- `thread` string
- `scope_id` string
- `mode` (`standard` or `deep`)
- `component` module/function identifier

### Must-have diagnostic fields by stage
- Correlation: `read_id`, `dispatch_id`, `confidence` (for anomaly events), `evidence_seq` list.
- Input read: `backend`, `source_fd`, `tty_path`, `bytes_read`, `decode_status`.
- Flush: `bytes_flushed`, `flush_reason`, `flush_duration_ms`.
- Sanitize/normalize: `len_before`, `len_after`, `removed_control_count`, `normalize_changed`, `recovered_single_letter`.
- Dispatch: `command_hash`, `normalized_verb`, `token_count`, `dispatch_result`, `latency_ms`.
- TTY state: `isatty_stdin`, `isatty_stdout`, `isatty_stderr`, `term`, `tmux`, `tmux_pane`, `ssh_tty`, `stty_hash_before`, `stty_hash_after`, `restore_ok`.

### Input-stage event taxonomy
- `ui.input.read.begin`
- `ui.input.read.byte` (deep, rate-limited)
- `ui.input.read.end`
- `ui.input.escape.decode`
- `ui.input.flush.begin`
- `ui.input.flush.drain`
- `ui.input.flush.end`
- `ui.input.sanitize.before`
- `ui.input.sanitize.after`
- `ui.input.normalize.after`
- `ui.input.dispatch.begin`
- `ui.input.dispatch.end`

### TTY/terminal events
- `ui.tty.detect`
- `ui.tty.state.snapshot`
- `ui.tty.state.change`
- `ui.tty.state.restore`
- `ui.tty.capabilities`
- `ui.tmux.context`

### Rendering events
- `ui.spinner.render.begin`
- `ui.spinner.render.end`
- `ui.menu.render.begin`
- `ui.menu.render.end`
- `ui.prompt.render.begin`
- `ui.prompt.render.end`

### Anomaly events
- `ui.anomaly.input_drop`
- `ui.anomaly.escape_timeout`
- `ui.anomaly.repeat_burst`
- `ui.anomaly.flush_race`
- `ui.anomaly.restore_failure`
- `ui.anomaly.debug_limit_reached`

### Detection heuristics (v1)
- `input_drop`: read stage reports N decoded keys but sanitize/normalize yields empty command unexpectedly.
- `escape_timeout`: escape prefix observed and decode times out or resolves to unknown token.
- `repeat_burst`: same printable class appears >= 3 times within a short monotonic window without matching user intent pattern.
- `flush_race`: flush drains bytes immediately before command read and the next command is unexpectedly empty.
- `restore_failure`: tty state after restore differs from pre-read canonical snapshot.

## Redaction and privacy policy

### Default policy
- Do not log printable typed characters in plain text.
- Store control/meta keys symbolically (`ENTER`, `ESC`, `CTRL_C`, arrows).
- For printable keys: store class metadata only (`printable=true`, `length`, `ascii_range`) unless opt-in enabled.

### Optional explicit opt-in
- `ENVCTL_DEBUG_UI_CAPTURE_PRINTABLE=true` allows printable capture for hard cases.
- Even with opt-in, pass through a sensitive-token scrubber before writing events.

### Strict sharing mode
- Add `ENVCTL_DEBUG_UI_BUNDLE_STRICT=true` (default true for pack command).
- In strict mode:
  - include only redacted runtime events (`events.runtime.redacted.jsonl`),
  - exclude unsanitized runtime events from bundle,
  - disable raw-byte artifacts unless explicitly allowed.

### Command payload handling rule
- Do not persist raw command text in DFR events by default.
- Replace raw command payloads with `command_hash` + non-sensitive metadata (`normalized_verb`, `token_count`).
- If temporary raw capture is ever needed, gate behind explicit opt-in and apply scrubber before persistence.

### Secret scrubber rules
- Redact values matching `(TOKEN|SECRET|PASSWORD|KEY|AUTH|COOKIE|SESSION|PRIVATE)`.
- Scrub URLs with embedded credentials.
- Scrub command fragments after `--commit-message` and similar value flags unless explicitly whitelisted.

## Instrumentation map (implementation targets)

### 1) Session + sink plumbing
- `python/envctl_engine/engine_runtime.py`
  - Add `DebugFlightRecorder` initialization from route/env.
  - Keep `_emit` as authoritative event entrypoint and mirror to DFR sink internally.
  - Append DFR events incrementally during execution; force flush on run end and exception path.

### 1b) Emitter/stability contract
- `python/envctl_engine/ui/command_loop.py` currently monkeypatches `runtime._emit` for spinner bridging.
- Refactor bridge to a listener/fan-out mechanism that does not replace `_emit` dynamically.
- Enforce no-recursion/no-duplication rule for DFR sink under spinner updates.

### 2) Command loop integration
- `python/envctl_engine/ui/command_loop.py`
  - Emit read-start/read-end markers around command reads.
  - Emit dispatch begin/end and command normalization metadata.
  - Emit spinner render boundaries for interleaving analysis.
  - Replace/debug-augment current raw `ui.input.submit` payload usage with hashed command identity for privacy.

### 3) Terminal session (primary hot path)
- `python/envctl_engine/ui/terminal_session.py`
  - Instrument backend choice, prompt_toolkit enter/exit, fallback enter/exit.
  - In deep mode, log bounded raw byte traces and normalization deltas.
  - Capture tty state before/after `_ensure_tty_line_mode` and restore paths.

### 4) Planning menu legacy path diagnostics
- `python/envctl_engine/planning_menu.py`
  - Instrument `flush_pending_input`, `read_key`, escape sequence decode, apply_key.
  - Emit timeout and decode-failure anomalies.
  - Capture state transitions around `tty.setraw` and restore.

### 5) Sanitization correlation
- `python/envctl_engine/dashboard_orchestrator.py`
  - Emit sanitize-before/after metadata (`len_before`, `len_after`, removed_seq_count).
  - Tag recovered single-letter command heuristics.

### 6) Menu and selector
- `python/envctl_engine/ui/menu.py`
  - Emit prompt_toolkit/fallback selection lifecycle and selected index cardinality.
- `python/envctl_engine/ui/target_selector.py`
  - Emit grouped-selection map sizes and cancel/confirm outcomes.

### 7) Rich spinner and render behavior
- `python/envctl_engine/ui/spinner.py`
  - Emit rich-status lifecycle boundaries.
  - Capture update frequency and last message metadata for race analysis.

### Exact hook points (current code paths)
- `python/envctl_engine/ui/command_loop.py`
  - `run_dashboard_command_loop`: before read, after read, before sanitize, after sanitize, pre-dispatch, post-dispatch, exit reason.
- `python/envctl_engine/ui/terminal_session.py`
  - `TerminalSession.read_command_line`: backend branch selection and fallback transitions.
  - `_read_command_line_fallback`: flush/read/restore boundaries.
  - `_read_line_from_fd`: byte-read loop (deep-mode sampled).
  - `_ensure_tty_line_mode` and `restore_terminal_after_input`: mode diffs.
- `python/envctl_engine/planning_menu.py`
  - `_run_legacy`: `tty.setraw` enter/exit and loop boundaries.
  - `read_key` + `read_escape_sequence`: decode timing and unknown sequences.
  - `flush_pending_input` + `_flush_input_buffer`: drain counts and timing.
- `python/envctl_engine/dashboard_orchestrator.py`
  - `_sanitize_interactive_input`: before/after transformation metadata.
  - `_recover_single_letter_command_from_escape_fragment`: heuristic recovery events.
- `python/envctl_engine/ui/menu.py`
  - `build_menu_presenter`: chosen backend context.
  - `PromptToolkitMenuPresenter` / `FallbackMenuPresenter`: selection lifecycle.
- `python/envctl_engine/engine_runtime.py`
  - `_emit`: attach monotonic sequence/session context and optional mirror to DFR sink.
  - run teardown/failure paths: force flush DFR buffer and write `summary.md`.

## prompt_toolkit-specific diagnostics to add
- Capture implementation-grounded fields first (v1):
  - backend chosen (`prompt_toolkit` vs fallback),
  - `prompt_toolkit_available()` result,
  - stdin/stdout/stderr TTY booleans,
  - effective `PROMPT_TOOLKIT_NO_CPR` value,
  - prompt invocation exceptions/timeouts.
- Advanced parser-level metrics (e.g., key parser internals) are phase-gated and only added when envctl adopts APIs exposing them directly.

## tmux/SSH/environment context capture
- `TERM`, `COLORTERM`, `TMUX`, `TMUX_PANE`, `SSH_TTY`, `LC_ALL`, `LANG`.
- `stty -a` snapshot (best effort).
- stdin/stdout/stderr `isatty()` and tty device resolution.
- Process context: parent process name, shell, platform version.

## Performance and safety guardrails
- Deep mode must be bounded by ring buffers and event caps.
- Hard limits:
  - max events per session (default 20k)
  - max raw-byte file size (default 256 KB)
  - max bundle size (default 10 MB)
- On limit exceed, emit `ui.anomaly.debug_limit_reached` and continue with sampling.

### Raw-byte artifact privacy rule
- `input_ring.hex` is disabled in strict sharing mode by default.
- When enabled, store tokenized classes by default (control/meta/printable-length) rather than raw printable bytes.
- Full raw-byte capture requires explicit deep opt-in plus explicit non-strict bundle mode.

## Decision log (intentional trade-offs)
- Prefer evented JSONL over plain text logs to support deterministic analysis tooling.
- Keep deep byte capture opt-in and bounded to prevent accidental sensitive leakage and large artifacts.
- Keep shell debug paths intact; DFR augments Python runtime rather than replacing shell diagnostics.
- Reuse runtime scope directories for debug data to preserve current mental model and cleanup behavior.
- Add explicit anomaly heuristics now, then iterate based on real bundles instead of overfitting up front.

## Risk register
- Risk: Debug overhead perturbs timing-sensitive bugs.
  - Mitigation: lightweight standard mode by default; deep mode is opt-in with bounded logging.
- Risk: False-positive anomaly detection causes noisy summaries.
  - Mitigation: include confidence score and raw evidence pointers in anomaly records.
- Risk: Bundle contains sensitive data.
  - Mitigation: strict default redaction + explicit printable opt-in + manifest redaction metadata.
- Risk: Prompt-toolkit and fallback traces become incomparable.
  - Mitigation: shared stage taxonomy (`read`, `sanitize`, `dispatch`, `render`) across both backends.
- Risk: Users forget to attach critical files.
  - Mitigation: `debug-pack` outputs one tarball and warns if required artifacts are missing.

## Bug bundle UX

### Proposed command flow
1. User runs with debug mode:
   - `envctl --resume --debug-ui-deep`
2. User reproduces issue and exits.
3. User packs bundle:
   - `envctl debug-pack`
4. CLI prints one path:
   - `/tmp/envctl-runtime/python-engine/<scope>/debug/session-.../envctl-debug-bundle.tar.gz`

### Deterministic pack target selection
Selection precedence is mandatory and deterministic:
1. `--session-id <id>` (exact match required)
2. `--run-id <id>` (must resolve to exactly one debug session)
3. `debug/latest` pointer in the active scope

Failure behavior:
- If explicit `--session-id` does not exist -> exit non-zero with actionable message.
- If `--run-id` resolves to 0 sessions -> non-zero with candidate hint.
- If `--run-id` resolves to >1 sessions -> non-zero with disambiguation list.
- If no selectors and no `debug/latest` -> non-zero with guidance to run debug mode first.

### Scope resolution for pack
- Default scope is current runtime scope id.
- Optional `--scope-id <id>` allows explicit scope targeting.
- Cross-scope ambiguity is never auto-resolved; caller must pass `--scope-id`.

### Bundle atomicity contract
- Pack must operate on a quiesced snapshot, not live-writing files.
- Required protocol:
  1. acquire recorder snapshot lock,
  2. flush/rotate current append streams,
  3. copy snapshot files to a staging dir,
  4. release lock,
  5. build tarball from staging dir.
- If lock cannot be acquired within timeout, fail with actionable retry message.

### Runtime event sanitization rule (mandatory)
- Before packaging runtime events, run a sanitizer pass that:
  - replaces `ui.input.submit.command` with hashed/tokenized metadata,
  - redacts known sensitive patterns in string payloads,
  - strips fields explicitly marked unsafe by schema policy.
- Output goes to `events.runtime.redacted.jsonl`.
- Unsanitized runtime `events.jsonl` is never included when strict mode is enabled.

### Shell fallback behavior policy
- If `ENVCTL_ENGINE_SHELL_FALLBACK=true` and `debug-pack` is requested:
  - fail fast with clear message that pack is Python-runtime DFR only, or
  - explicitly bridge to shell pack path if implemented.
- v1 requirement: deterministic fail-fast with actionable remediation is acceptable.

### Bundle contents
- `manifest.json` (version, redaction policy, hashes)
- `summary.md` (top anomalies and timeline)
- `events.debug.jsonl`
- `events.runtime.redacted.jsonl`
- `tty_context.json`
- `tty_state_transitions.jsonl`
- `anomalies.jsonl`
- optional `doctor.txt`

`events.runtime.jsonl` (unsanitized) is excluded from strict sharing bundles.

## Sequenced implementation plan (TDD)

### Phase 0 - Contract and schema tests
Add tests first:
- `tests/python/test_debug_flight_recorder_schema.py`
- `tests/python/test_debug_flight_recorder_redaction.py`
- `tests/python/test_debug_flight_recorder_limits.py`

Expected failures: no recorder implementation yet.

### Phase 1 - Recorder core and sink wiring
Implement:
- `python/envctl_engine/ui/debug_flight_recorder.py`
- runtime wiring in `engine_runtime.py`
- incremental append-mode sink with bounded buffering and forced flush hooks.

Tests:
- recorder initialization, session id generation, event sequence monotonicity, file persistence.

### Phase 2 - Input-path instrumentation
Implement instrumentation in:
- `ui/terminal_session.py`
- `ui/command_loop.py`
- `dashboard_orchestrator.py`
- `planning_menu.py`

Tests:
- `tests/python/test_interactive_input_reliability.py` extensions for event assertions.
- new focused tests for flush/decode/sanitize correlation.

### Phase 3 - Bundle generation
Implement packer:
- `python/envctl_engine/debug_bundle.py`
- CLI route/flag plumbing in command router/runtime.
- Add lightweight analyzer:
  - `scripts/analyze_debug_bundle.py` to print stage timings, anomaly counts, and likely fault zone.

Command-surface fallout to handle explicitly:
- update router/dispatch tests for new `debug-pack` command and optional `--debug-ui-pack` normalization.
- update strict command-count tests if `debug-pack` is added to supported command list.
- review command-surface parity artifacts (`docs/planning/python_engine_parity_manifest.json`) and update if command inventory assumptions change.

Tests:
- `tests/python/test_debug_bundle_generation.py`
- `tests/python/test_doctor_debug_bundle_integration.py`
- `tests/python/test_debug_bundle_analyzer.py`

### Phase 4 - tmux-oriented integration tests
Add BATS:
- `tests/bats/python_interactive_debug_packet_e2e.bats`
- `tests/bats/python_interactive_escape_timeout_e2e.bats`
- `tests/bats/python_interactive_flush_race_e2e.bats`

Each test validates bundle creation + expected anomaly/event markers.

## Tests to add or extend
- `tests/python/test_debug_flight_recorder_schema.py`
- `tests/python/test_debug_flight_recorder_redaction.py`
- `tests/python/test_debug_flight_recorder_limits.py`
- `tests/python/test_debug_bundle_generation.py`
- `tests/python/test_doctor_debug_bundle_integration.py`
- `tests/python/test_debug_bundle_analyzer.py`
- Extend `tests/python/test_interactive_input_reliability.py` with event-sequence assertions.
- Extend `tests/python/test_command_dispatch_matrix.py` for new routed command behavior.
- Extend `tests/python/test_command_router_contract.py` for `--debug-ui-pack` normalization and strict unknown-option behavior.
- Add `tests/bats/python_interactive_debug_packet_e2e.bats`.
- Add `tests/bats/python_interactive_escape_timeout_e2e.bats`.
- Add `tests/bats/python_interactive_flush_race_e2e.bats`.

## Rollout / verification

### Verification matrix

### Unit
- Schema validity for all event types.
- Redaction behavior across representative secret-like inputs.
- Ring buffer and cap behavior.

### Integration
- Prompt-toolkit path with TTY and non-TTY fallback.
- Planning menu path in legacy and prompt-toolkit modes.
- Spinner-enabled and spinner-disabled paths.
- Command routing verifies `debug-pack` never touches startup orchestrator paths.

### E2E
- tmux reproduction scripts with controlled key timings.
- SSH session smoke tests.
- Non-interactive CI run confirms zero behavior drift when debug mode off.

## Rollout strategy
1. Ship behind env/flags, default `off`.
2. Dogfood with known problematic terminals.
3. Promote to documented troubleshooting workflow.
4. Keep deep mode opt-in; keep standard mode cheap and safe.
5. Align command-surface parity artifacts/tests (including command matrix expectations) before enabling broadly.

## Definition of done
- User can reliably generate a single debug bundle from a failing interactive session.
- Bundle includes enough correlated evidence to identify where input was altered/dropped.
- Redaction defaults are safe; opt-in printable capture is explicit.
- All new tests and existing interactive reliability suites pass.
- Troubleshooting docs include exact commands for capture and share.
- Command routing tests prove `debug-pack` bypasses startup and unknown debug flags still fail fast.

## Implementation checklist (execution-order)
1. Add recorder schema + limits tests (fail first).
2. Add recorder core + persistence.
3. Wire runtime session creation and event bridge.
4. Instrument terminal session + command loop.
5. Instrument planning menu + sanitize pipeline.
6. Add anomaly detector heuristics.
7. Add bundle pack command and manifest hashes.
8. Add docs and e2e flows.

## Suggested first reproduction workflow (once implemented)
```bash
envctl --resume --debug-ui-deep
# reproduce input issue, then quit interactive mode
envctl debug-pack
```

Share the emitted tarball path.
