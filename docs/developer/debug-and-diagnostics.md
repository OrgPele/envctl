# Debug and Diagnostics

This guide explains the Python runtime's diagnostics model: events, debug flight recorder sessions, bundle packing, doctor output, and cutover gates.

Use it when you are changing telemetry, doctor behavior, bundle contents, anomaly rules, or operator-facing diagnosis flows.

## Two Diagnostic Layers

There are two different diagnostic layers in the runtime:

1. always-on runtime artifacts and event logs
2. opt-in debug flight recorder capture

Examples of always-on diagnostics:

- `run_state.json`
- `runtime_map.json`
- `error_report.json`
- `events.jsonl`
- `envctl --doctor`

Examples of opt-in capture:

- `ENVCTL_DEBUG_UI_MODE=deep`
- `events.debug.jsonl`
- `anomalies.jsonl`
- `envctl --debug-pack`
- `envctl --debug-report`

Keep the distinction clear when making changes.

## Runtime Events

Runtime events are written to `events.jsonl`.

They are used for:

- operational traceability
- artifact persistence
- some doctor/debug analysis
- bundle redaction into `events.runtime.redacted.jsonl`

If an event is needed for ordinary runtime inspection, it belongs here first.

## Debug Flight Recorder

The debug flight recorder lives in `ui/debug_flight_recorder.py`.

It owns:

- session ids
- bounded event capture
- anomaly files
- TTY context capture
- input ring persistence when allowed
- retention cleanup

Key point:

- the debug recorder is privacy-aware and not just a raw log sink

## Capture Modes

Important runtime knobs:

- `ENVCTL_DEBUG_UI_MODE=off|standard|deep`
- `ENVCTL_DEBUG_AUTO_PACK=off|crash|anomaly|always`
- `ENVCTL_DEBUG_UI_BUNDLE_STRICT=true|false`
- `ENVCTL_DEBUG_UI_CAPTURE_PRINTABLE=true|false`
- `ENVCTL_DEBUG_UI_MAX_EVENTS`
- `ENVCTL_DEBUG_UI_RING_BYTES`
- `ENVCTL_DEBUG_UI_SAMPLE_RATE`

`deep` is the mode most likely to matter when debugging selector, dashboard, spinner, or startup timing issues.

## Privacy and Redaction

Privacy behavior is not optional afterthought logic. It is part of the design contract.

Examples:

- command strings are hashed
- string payloads are scrubbed
- printable raw input is not captured unless explicitly allowed
- runtime events are sanitized again when moved into bundles

Relevant modules:

- `debug/debug_utils.py`
- `debug/debug_contract.py`
- `debug/debug_bundle_support.py`
- `ui/debug_flight_recorder.py`

When you add telemetry touching user input or command text, update the redaction path at the same time.

## Bundle Packaging

Bundle packaging is implemented through:

- `debug/debug_bundle.py`
- `debug/debug_bundle_support.py`
- `runtime/engine_runtime_debug_support.py`

Typical bundle contents:

- `events.debug.jsonl`
- `events.runtime.redacted.jsonl`
- `timeline.jsonl`
- `anomalies.jsonl`
- `command_index.json`
- `diagnostics.json`
- `bundle_contract.json`
- `manifest.json`
- `summary.md`

The bundle is meant to be portable and safe enough to share within the expected debugging workflow.

## `debug-pack`, `debug-last`, and `debug-report`

These commands are wired through `runtime/engine_runtime_debug_support.py`.

Important current behavior:

- they are Python-runtime only
- missing debug data or prerequisites should produce a clear error instead of pretending support exists
- `debug-report` packages first, then summarizes

If you change bundle behavior, check all three commands.

## Doctor

`debug/doctor_orchestrator.py` is not just a health command. It is also a runtime readiness and governance surface.

Doctor currently reports on:

- runtime paths
- debug mode and latest bundle
- parity manifest state
- pointer and lock health
- synthetic state detection
- runtime readiness status
- runtime gap counts
- recent failures

That means doctor changes can affect:

- troubleshooting workflows
- release/shipability gates
- migration status interpretation

## Cutover Gates

Doctor and related diagnostics rely on:

- parity manifest completeness
- runtime truth reconciliation
- lifecycle expectations
- runtime readiness contract

Relevant modules:

- `runtime/engine_runtime_diagnostics.py`
- `shell/release_gate.py`
- `debug/doctor_orchestrator.py`

If you change cutover semantics, you are changing both engineering governance and user/operator output.

## Anomaly and Summary Logic

Bundle analysis and summary behavior live in:

- `debug/debug_bundle_diagnostics.py`
- `scripts/analyze_debug_bundle.py`

These modules convert raw evidence into:

- probable root causes
- next data needed
- spinner policy explanations
- timing hotspots
- selector activity diagnoses

If you add a new class of bug signal, you may need changes in:

1. event emission
2. bundle inclusion
3. diagnostic summarization
4. user docs

## Selector and Input Debugging

The selector path has extra importance because interactive issues are one of the main reasons the debug flight recorder exists.

Key files:

- `ui/textual/screens/selector/*`
- `ui/prompt_toolkit_cursor_menu.py`
- `ui/debug_anomaly_rules.py`
- `debug/debug_bundle_diagnostics.py`

When working here, make sure the evidence chain is complete:

- raw runtime/debug event exists
- bundle includes it
- diagnostics can explain it

## Startup Timing Diagnostics

Startup timing diagnostics are built from:

- startup event emission
- requirement-stage timing
- service bootstrap timing
- bundle timeline synthesis
- diagnostic aggregation

This is why partial event coverage can make `startup_breakdown.unknown_ratio` large even when the runtime is working correctly.

If you add timing events, think in terms of end-to-end attribution, not isolated event counts.

## Adding a New Diagnostic Signal

Checklist:

1. Decide whether it belongs in runtime events, debug events, or both.
2. Ensure payloads are redactable.
3. Decide whether it belongs in packed bundles.
4. Decide whether it should affect doctor or only debug bundles.
5. Add tests for schema, redaction, and summary behavior.
6. Update operations docs if users should act on it.

## Changing Doctor Output

Checklist:

1. Confirm whether the change is just formatting or a semantic gate change.
2. Update tests under `tests/python/debug/` and `tests/python/runtime/`.
3. Update user troubleshooting docs if operators will see different guidance.
4. Update migration/cutover docs if the meaning of a gate changed.

## Common Mistakes

- adding telemetry without redaction updates
- assuming runtime events and debug events are interchangeable
- changing doctor output without realizing release gates depend on it
- adding bundle files without updating manifest/contract logic
- emitting diagnostics that users cannot interpret because no docs explain them
