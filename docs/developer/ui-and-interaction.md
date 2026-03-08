# UI and Interaction Architecture

This guide explains how the Python runtime chooses interactive behavior across dashboard rendering, selectors, command input, and non-interactive fallback.

Use it when you are changing dashboard backend policy, selector behavior, input handling, terminal capability checks, or interactive debug instrumentation.

## The UI Surface Is Intentionally Split

`envctl` does not have one single "UI mode".

There are four related but distinct concerns:

1. dashboard backend
2. selector implementation
3. command-line input handling inside interactive loops
4. debug and diagnostic capture for interactive sessions

Those layers interact, but they are not interchangeable. Most confusion in this area comes from collapsing them into one concept.

## Dashboard Backend Policy

Dashboard backend selection is resolved by `python/envctl_engine/ui/backend_resolver.py`.

Current user-facing policy:

- `ENVCTL_UI_BACKEND=auto` keeps the legacy dashboard by default
- `ENVCTL_UI_EXPERIMENTAL_DASHBOARD=1` makes `auto` prefer Textual when Textual is available
- `ENVCTL_UI_BACKEND=textual` explicitly requests Textual
- `ENVCTL_UI_BACKEND=legacy` explicitly requests the legacy dashboard
- `ENVCTL_UI_BACKEND=non_interactive` disables interactive dashboard behavior

Important behavior detail:

- if `textual` is requested but Textual is unavailable, runtime falls back to `legacy`
- if no interactive TTY is available, runtime resolves to `non_interactive`

That fallback behavior is deliberate. The runtime currently prefers degraded functionality over abrupt failure for dashboard rendering.

## Selector Policy Is Separate

Selector behavior lives primarily under `python/envctl_engine/ui/textual/screens/selector/`.

Current policy is intentionally different from dashboard policy:

- selectors default to the Textual plan-style selector
- `ENVCTL_UI_SELECTOR_IMPL=planning_style` enables the prompt-toolkit rollback path
- `ENVCTL_UI_SELECTOR_IMPL=legacy` is a compatibility alias that still resolves to the Textual selector path

This is why the dashboard can still be legacy by default while selectors are already more Textual-first.

Do not refactor this area under the assumption that one backend switch controls both.

## Dashboard-Orchestrator Responsibilities

`python/envctl_engine/ui/dashboard/orchestrator.py` owns more than rendering.

It is responsible for:

- loading the latest state snapshot for the requested mode
- blocking interactive dashboard use when strict synthetic-state gates fail
- deciding snapshot-only versus interactive entry
- parsing dashboard-entered commands
- applying dashboard-owned target selection for certain command families
- refreshing state after interactive commands mutate the runtime

That means dashboard work is partly UI and partly command-routing policy.

## Selector Backend Internals

There is a second selector-level backend decision inside `selector/implementation.py`.

Relevant internal controls include:

- `ENVCTL_UI_SELECTOR_BACKEND`
- `ENVCTL_UI_PROMPT_TOOLKIT`

These are lower-level routing and compatibility controls, not the main user-facing dashboard policy knobs.

Practical guidance:

- prefer documenting `ENVCTL_UI_SELECTOR_IMPL` for normal user/operator guidance
- treat `ENVCTL_UI_SELECTOR_BACKEND` and `ENVCTL_UI_PROMPT_TOOLKIT` as internal, test, or emergency-override surfaces unless the product story explicitly expands them

## Interactive Command Input

Interactive command entry inside the dashboard loop is a separate concern again.

`python/envctl_engine/runtime/engine_runtime_ui_bridge.py` currently reads command lines through `TerminalSession`, with:

- `ENVCTL_UI_BASIC_INPUT` defaulting to `true`
- prompt-toolkit still available as an explicit path when allowed

That means these statements can all be true at once:

- dashboard is legacy
- selector is Textual-first
- command entry is using basic input
- deep debug capture is enabled

This is expected and should be documented that way.

## Target Selection Ownership

Target selection is also split across layers.

Important pieces:

- `ui/selection_support.py`: shared rules for whether interactive selection is allowed and how selections map back to routes or services
- dashboard orchestrator: decides which commands should get dashboard-owned selection prompts
- selector implementation modules: render the actual selection UI

The split matters because "who chooses a target" and "how the selector is rendered" are different concerns.

## Non-Interactive Fallback

The runtime has explicit non-interactive fallback semantics.

Backend resolution moves to `non_interactive` when:

- `ENVCTL_UI_BACKEND=non_interactive`
- there is no usable interactive TTY
- capability checks require a safe downgrade

Selector flows also emit fallback events such as `ui.fallback.non_interactive` when the requested path cannot safely run.

That behavior is part of the runtime contract, not an implementation accident.

Selection helpers also produce headless-friendly error guidance when a command needs a target but interactive selection is unavailable. Preserve that behavior when changing routing or selector flows.

## Capability Checks

Capability detection spans several modules:

- `ui/backend_resolver.py`
- `ui/capabilities.py`
- `ui/terminal_session.py`

Relevant concepts include:

- interactive TTY availability
- Textual importability
- prompt-toolkit availability
- terminal-specific guardrails

One important example already encoded in selector behavior:

- Apple Terminal may require the prompt-toolkit rollback path for reliable selector input

When you change capability logic, verify the fallback reasons emitted to diagnostics still make sense.

## UI Bridge Responsibilities

`python/envctl_engine/runtime/engine_runtime_ui_bridge.py` is the shared bridge between runtime/orchestrator code and concrete UI implementations.

It centralizes helpers for:

- running the interactive dashboard loop
- selecting projects or grouped targets
- reading interactive command lines
- sanitizing interactive input
- resolving the current backend when environment or capability state changes

Keep high-level runtime code talking to the bridge or orchestrators. Avoid sprinkling direct UI implementation imports through unrelated runtime modules.

## Events and Diagnostics

Interactive behavior is observable through both runtime events and debug-flight-recorder capture.

Examples of useful evidence:

- `ui.backend.selected`
- `ui.fallback.non_interactive`
- selector engine decision events
- spinner lifecycle events
- command-input and throughput diagnostics in deep mode

When you add or change UI behavior, make sure operators can still answer:

- which backend was chosen
- why that backend was chosen
- whether a fallback happened
- whether the issue is policy, capability, or input throughput

## User-Facing vs Internal Knobs

Keep this distinction sharp in docs and code reviews.

Reasonable user-facing knobs:

- `ENVCTL_UI_BACKEND`
- `ENVCTL_UI_EXPERIMENTAL_DASHBOARD`
- `ENVCTL_UI_SELECTOR_IMPL`
- `ENVCTL_UI_SPINNER_MODE`
- `ENVCTL_DEBUG_UI_MODE`

Internal or specialist knobs that should usually stay out of the main user story:

- `ENVCTL_UI_SELECTOR_BACKEND`
- `ENVCTL_UI_PROMPT_TOOLKIT`
- `ENVCTL_UI_TEXTUAL_HEADLESS_ALLOWED`
- file-descriptor specific input overrides used in investigations

If an internal knob becomes necessary in normal user docs, that usually signals unfinished product policy.

## Shell Fallback Boundary

The deprecated shell fallback still exists, but the modern UI and debug story is Python-first.

Implications:

- dashboard and selector evolution should be described primarily in Python-runtime docs
- Python-only diagnostic features such as debug bundles should fail clearly under shell fallback
- user docs should mention shell only as an explicit compatibility fallback, not as a normal UI option

## Changing Dashboard Policy

Checklist:

1. Update `ui/backend_resolver.py`.
2. Update any backend-building logic in `ui/backend.py`.
3. Verify fallback reasons and emitted events still match behavior.
4. Update user docs if `auto`, `textual`, `legacy`, or `non_interactive` behavior changed.
5. Update tests for TTY and non-TTY cases.

## Changing Selector Behavior

Checklist:

1. Update selector support and implementation modules under `ui/textual/screens/selector/`.
2. Confirm whether the change affects `ENVCTL_UI_SELECTOR_IMPL` semantics or only internal backend choice.
3. Verify deep debug selector evidence is still emitted.
4. Check Apple Terminal and prompt-toolkit rollback behavior if relevant.
5. Update operations docs when troubleshooting guidance changes.

## Changing Input Handling

Checklist:

1. Update `TerminalSession` or `engine_runtime_ui_bridge.py`.
2. Verify `ENVCTL_UI_BASIC_INPUT` and prompt-toolkit override behavior.
3. Re-check deep debug capture and redaction.
4. Re-test interactive command submission, cancellation, and fallback behavior.
5. Update any troubleshooting docs that mention command-entry workarounds.

## Common Mistakes

- treating dashboard and selector selection as the same policy surface
- documenting internal test knobs as normal user configuration
- changing fallback behavior without updating emitted reasons or diagnostics
- bypassing the UI bridge from unrelated runtime modules
- forgetting that shell fallback is deprecated but still part of the compatibility story
