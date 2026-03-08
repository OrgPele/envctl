# Post-Plan Dashboard Input Investigation

> Historical investigation archive.
> The `ENVCTL_DEBUG_PLAN_*` split-matrix commands documented here are no longer a supported debug surface and may no longer work.
> For current debugging, use snapshots, doctor/debug bundles, `--debug-report`, and the permanent write-up in [service-launch-io-ownership.md](/Users/kfiramar/projects/envctl/docs/troubleshooting/service-launch-io-ownership.md).

## Problem statement

In some reused Apple Terminal tabs:

- `envctl --repo /Users/kfiramar/projects/supportopia --plan`
- the planning selector works correctly
- after the planning selector exits and envctl enters the interactive dashboard, input becomes unreliable
- symptoms include:
  - some typed characters not registering
  - dashboard-opened menus like `t` feeling unresponsive
  - arrow keys / `Enter` / `Esc` partially or inconsistently registering
  - `No test target selected.` after obviously attempting to navigate

In fresh Apple Terminal tabs the same command often works correctly.

## What is already proven

### Terminal-level facts

- Raw terminal key bytes are correct in both good and bad tabs.
- `stdin` is not a TTY in the shell used for these runs.
- `stdout` and `stderr` are the real terminal TTYs.
- Good and bad tabs differ in `stdout/stderr` line flags:
  - good tab: `lflag = 1483`
  - bad tab: `lflag = 536872395`
  - this includes `PENDIN`
- Manually clearing `PENDIN` did not fix the issue.

### Selector/backend facts

- The planning selector itself works perfectly, even in bad tabs.
- The user has consistently reported that the break happens only after the plan menu exits and envctl transitions into the post-plan dashboard path.
- A standalone prompt-toolkit probe works in bad tabs.
- A standalone Textual selector works in bad tabs.
- A standalone `TerminalSession.read_command_line(...)` followed by a standalone Textual selector works in bad tabs.
- A simulated resume-progress UI followed by a standalone Textual selector works in bad tabs.

### Post-plan split facts

This command works perfectly in bad tabs:

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_SKIP_PLAN_STARTUP=1 \
ENVCTL_DEBUG_MINIMAL_DASHBOARD=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl \
  --repo /Users/kfiramar/projects/supportopia \
  --plan
```

That means:

- planning/worktree sync is not the culprit
- the minimal dashboard itself is not the culprit
- the post-plan bug is introduced somewhere after the planning selector and before or during the normal startup/dashboard handoff path
- the cleanest working mental model so far is:
  - plan selector itself is healthy
  - standalone selectors are healthy
  - something in the real `--plan` post-selection path contaminates the later dashboard/menu interaction

## Invalid test patterns

These were misleading and should not be reused as evidence:

- any `python - <<'PY' ... PY` probe that tries to exercise Textual or `TerminalSession.read_command_line(...)`
- reason:
  - here-doc makes `stdin` a pipe
  - Textual and direct line-input tests no longer represent the real terminal path

## Test matrix

### Baseline good

| Test | Result | Notes |
|---|---|---|
| `ENVCTL_DEBUG_SKIP_PLAN_STARTUP=1` + `ENVCTL_DEBUG_MINIMAL_DASHBOARD=1` | good | known-good baseline |
| `ENVCTL_DEBUG_SKIP_PLAN_STARTUP=1` without minimal dashboard | good | normal dashboard alone is fine |
| standalone Textual selector | good | even in bad tab |
| standalone prompt-toolkit probe | good | even in bad tab |
| standalone `TerminalSession` + selector | good | even in bad tab |
| simulated resume progress + selector | good | even in bad tab |

### Startup-path toggles that were still bad

| Test | Result | Session / notes |
|---|---|---|
| `ENVCTL_DEBUG_SKIP_PLAN_SERVICES=1` | bad | bug introduced |
| `ENVCTL_DEBUG_SKIP_PLAN_REQUIREMENTS=1` | bad | bug introduced |
| `ENVCTL_UI_SPINNER=0` | bad | `session-20260307181346-53013-2ecf` |
| startup parallelism disabled | bad | `session-20260307181410-54437-be7d` |
| spinner + parallelism disabled | bad | `session-20260307181256-50892-9e1c` |
| `ENVCTL_DEBUG_SKIP_PLAN_PROJECT_EXECUTION=1` | bad | `session-20260307181540-57148-7c28` |
| skip post-start reconcile | bad | `session-20260307181910-60130-8a7f` |
| skip artifacts | bad | `session-20260307181940-61528-0f19` |
| skip summary | bad | `session-20260307182017-63330-5779` |
| suppress progress output | bad | `session-20260307182249-66378-c4f3` |
| grouped stripped post-plan path (`J`) | bad | `session-20260307182510-69522-e516` |
| grouped stripped post-plan path + minimal dashboard (`K`) | bad | `session-20260307182537-71023-82e6` |

Interpretation:

- `J` and `K` are especially important because they were still bad after stripping:
  - project execution
  - post-reconcile
  - artifacts
  - summary
  - progress
  - spinner
  - startup parallelism
  - normal dashboard vs minimal dashboard
- that ruled out a large amount of obvious startup work
- but it did not rule out the full post-plan orchestration path as a whole

### Split-group reintroductions that stayed good

These all started from the known-good baseline:

```bash
ENVCTL_DEBUG_SKIP_PLAN_STARTUP=1
ENVCTL_DEBUG_MINIMAL_DASHBOARD=1
```

And re-enabled only targeted pieces. All of these were still good:

| Group | Meaning | Result |
|---|---|---|
| `state_shape` | startup-like dashboard state shape | good |
| `persist_reload` | state persistence and reload | good |
| `emit_output` | startup-style terminal output | good |
| `handoff` | startup-style handoff emits | good |
| `startup_scaffolding` | startup execution scaffolding | good |
| `startup_scaffolding + state_shape + persist_reload` | combined | good |
| `startup_scaffolding + emit_output + handoff` | combined | good |
| `startup_scaffolding + state_shape + persist_reload + emit_output + handoff` | combined | good |

Interpretation:

- the bug is not explained by any one of those buckets in isolation
- the bug appears only in the real normal `--plan` startup path, not in the synthetic skip-startup reconstruction

### Important caveat about later proposed group names

Some later shorthand group names used during the conversation were reasoning labels rather than independently wired code-path toggles. The reliable conclusions are the ones backed by:

- the known-good `ENVCTL_DEBUG_SKIP_PLAN_STARTUP=1` baseline
- the real implemented `ENVCTL_DEBUG_PLAN_SPLIT_GROUP` values listed above
- the explicitly bad startup-path toggles listed above
- the explicitly implemented split-group combinations that were actually run

Do not treat every conversational placeholder bucket as an independent proven code-path split unless it is represented in the tables in this document.

## Important child-selector findings

Child selector subprocess traces were written to:

```text
/tmp/envctl-runtime/python-engine/repo-b15e3f0c8257/debug/<session_id>/selector-subprocess-grouped.jsonl
```

Observed behavior in bad sessions:

- dashboard accepted `t`
- child selector launched
- child selector often received only `2` to `4` `Down` key events out of `10`
- then idled until `Ctrl-C`

Observed behavior in standalone deep Textual selector in the same bad tab:

- received all `10` `Down` key events
- no loss

Interpretation:

- the broken behavior is not “Textual is always broken in the bad tab”
- the broken behavior is specific to the full envctl post-plan path

## Current working hypotheses

### Hypothesis 1

There is a still-unidentified interaction in the normal `--plan` startup path that is not reproduced by the synthetic skip-startup path.

This could still be:

- one or more parent threads left alive only in the real startup path
- a terminal state mutation that only occurs in the full path
- some path-specific dashboard entry sequencing that has not yet been mirrored in the synthetic split groups

### Hypothesis 2

The culprit is an interaction, not a single feature.

The data strongly suggests:

- no single startup slice is sufficient to reproduce the bug on top of the known-good baseline
- the issue is caused by a combination that is only present in the real startup path

### Hypothesis 3

The remaining contaminant may be tied to the exact orchestrator/control-flow transition between:

- planning selector completion
- post-plan startup/orchestration entry
- final dashboard loop entry

rather than to the obvious leaf features already tested in isolation.

## What has already been tried in code

The investigation already tried and ruled out a lot of wrong directions:

- generic `stty` / termios restore fixes
- `O_NONBLOCK`
- orphan envctl process attached to terminal

## Later finding: the branch split reconverged on one shared tail

The `entry` / `loop` / `dashboard` real-noop branch split did not isolate the bug.

The corresponding bad sessions:

- `session-20260307223306-19479-92ad` (`entry`)
- `session-20260307223339-20899-1459` (`loop`)
- `session-20260307223418-22478-b9e3` (`dashboard`)

all converged on the same always-on tail after dashboard entry:

- `ui.dashboard_loop` termios normalization
- `after_first_dashboard_render`
- selector preflight
- `stdin_restore_and_drain`
- selector subprocess launch
- parent thread snapshot
- `temporary_standard_output_pendin`

## 2026-03-08 verified attach subgroup routing

Attach subgroup routing is now verified in the real current startup path.

Code path verified:

- `python/envctl_engine/startup/startup_orchestrator.py`
  - parses `ENVCTL_DEBUG_PLAN_ATTACH_GROUP`
  - injects `_debug_attach_group` into the normal `route_for_execution`
- `python/envctl_engine/startup/startup_execution_support.py`
  - reads `_debug_attach_group` inside `start_project_services(...)`
  - emits `startup.debug_attach_group`
  - executes an early-return subgroup branch for:
    - `process_start`
    - `listener_probe`
    - `attach_merge`

Important guard:

- `ENVCTL_DEBUG_PLAN_ATTACH_GROUP` only matters when both are also true:
  - `ENVCTL_DEBUG_PLAN_EXEC_GROUP=services`
  - `ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach`

Runtime/log verification:

- Existing real runtime events already show a valid `listener_probe` run in:
  - `/tmp/envctl-runtime/python-engine/repo-b15e3f0c8257/events.jsonl`
- That run contains:
  - `startup.debug_service_group` with `group=launch_attach`
  - `startup.debug_attach_group` with `group=listener_probe`
  - `service.attach.phase` with:
    - `command_resolution`
    - `process_launch`
    - `actual_port_detection`

This is trustworthy because it proves the requested attach subgroup was actually executed and observed in runtime events, not merely parsed from env.

## Next valid manual runs only

The next smallest trustworthy split is exactly:

- `process_start`
- `listener_probe`
- `attach_merge`

Trust each run only if the event log shows the requested subgroup and the expected subgroup shape:

- `process_start`
  - must show `startup.debug_attach_group` with `group=process_start`
  - should show `service.attach.phase` for launch phases
  - should not need `actual_port_detection`
- `listener_probe`
  - must show `startup.debug_attach_group` with `group=listener_probe`
  - should show `actual_port_detection`
- `attach_merge`
  - must show `startup.debug_attach_group` with `group=attach_merge`
  - should not show `service.attach.execution`
  - should not show `service.attach.phase`

## 2026-03-08 attach subgroup reruns

Validated sessions:

- `process_start`
  - session: `session-20260308162349-9670-f67a`
  - routed correctly
  - selector subprocess trace exists
  - selector trace ended with:
    - `service_count=0`
    - `project_count=0`
    - `cancelled=true`
  - user saw `No test target selected.`
  - classification: routed but non-comparable

- `listener_probe`
  - session: `session-20260308162509-11270-9951`
  - routed correctly
  - runtime events show `command_resolution`, `process_launch`, and `actual_port_detection`
  - dashboard preserved real shape:
    - `services: 8 total | 8 running`
  - user reported the real bug remained
  - classification: routed, comparable, bad

- `attach_merge`
  - session: `session-20260308162556-12820-a745`
  - routed correctly
  - runtime events show `startup.debug_attach_group=attach_merge`
  - runtime events do not show `service.attach.execution` or `service.attach.phase`
  - selector subprocess trace ended with:
    - `service_count=0`
    - `project_count=0`
    - `cancelled=true`
  - user saw `No test target selected.`
  - classification: routed but non-comparable

## Updated trustworthy narrowing

The attach split is now narrowed enough to state:

- plain process launch is not enough evidence for the bug
- attach merge is not enough evidence for the bug
- the remaining comparable bad family is the real `listener_probe` path

In code terms, that means the next split should stay within:

- `wait_for_service_listener(...)`
- `detect_service_actual_port(...)`

Relevant code:

- `python/envctl_engine/runtime/engine_runtime_service_truth.py`
  - listener groups:
    - `pid_wait`
    - `port_fallback`
    - `rebound_discovery`
- `python/envctl_engine/shared/process_runner.py`
  - pid-wait subgroups:
    - `signal_gate`
    - `pid_port_lsof`
    - `tree_port_scan`

## Next valid manual runs only

The next smallest trustworthy split is:

- keep `ENVCTL_DEBUG_PLAN_ATTACH_GROUP=listener_probe`
- vary only `ENVCTL_DEBUG_PLAN_LISTENER_GROUP`:
  - `pid_wait`
  - `port_fallback`
  - `rebound_discovery`

Trust each run only if:

- `startup.debug_attach_group=listener_probe`
- `startup.debug_listener_group=<requested subgroup>`
- dashboard still preserves `services: 8 total | 8 running`

## 2026-03-08 final real-path validation

Validation session:

- `session-20260308162858-20968-c7ee`

Code state verified in workspace:

- `python/envctl_engine/shared/process_runner.py`
  - `ProcessRunner.start(...)` now launches background service processes with:
    - `stdin=subprocess.DEVNULL`

User-reported result:

- same previously bad reused Apple Terminal tab
- dashboard interaction healthy
- post-plan behavior no longer reproduced the unreliable input bug

Interpretation:

- this is the first trusted fix validation on the real bad path
- the earlier probe-helper subprocess stdin detach was not sufficient
- detaching stdin for the long-lived launched backend/frontend service children fixed the practical bug

Important note:

- a printed `No test target selected.` line alone is not enough to reject the fix
- that line can occur in a healthy run when the selector is exited without choosing a target
- the deciding evidence here is the user's direct observation that the previously broken dashboard/menu flow now behaves normally

Final trustworthy conclusion:

- root cause, in practical terms:
  - launched service child processes were inheriting terminal stdin during the normal post-plan path
- effective fix:
  - launch those service children with `stdin=subprocess.DEVNULL`

That means the earlier branch split was too early. The useful split is the shared tail:

1. dashboard entry
2. command read
3. selector launch

## Real implemented tail split

The following tail split is now implemented:

- `ENVCTL_DEBUG_PLAN_TAIL_GROUP=dashboard_entry`
  - no command read
  - auto-injects `t`
  - forces direct Textual selector
  - no selector preflight
  - no selector subprocess

- `ENVCTL_DEBUG_PLAN_TAIL_GROUP=command_read`
  - real command read
  - forces direct Textual selector
  - no selector preflight
  - no selector subprocess

- `ENVCTL_DEBUG_PLAN_TAIL_GROUP=selector_launch`
  - real command read
  - real selector launch path

The intended next commands for the bad Apple Terminal tab are:

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_REAL_NOOP_EXECUTION=1 \
ENVCTL_DEBUG_PLAN_EXEC_GROUP=completion \
ENVCTL_DEBUG_PLAN_TAIL_GROUP=dashboard_entry \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl \
  --repo /Users/kfiramar/projects/supportopia \
  --plan
```

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_REAL_NOOP_EXECUTION=1 \
ENVCTL_DEBUG_PLAN_EXEC_GROUP=completion \
ENVCTL_DEBUG_PLAN_TAIL_GROUP=command_read \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl \
  --repo /Users/kfiramar/projects/supportopia \
  --plan
```

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_REAL_NOOP_EXECUTION=1 \
ENVCTL_DEBUG_PLAN_EXEC_GROUP=completion \
ENVCTL_DEBUG_PLAN_TAIL_GROUP=selector_launch \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl \
  --repo /Users/kfiramar/projects/supportopia \
  --plan
```

Interpretation target:

- if `dashboard_entry` is already bad, the contaminant exists before the prompt
- if `dashboard_entry` is good but `command_read` is bad, the command reader / restore path is the culprit
- if `command_read` is good but `selector_launch` is bad, the selector launch path is the culprit
- multiple selector backend swaps
- prompt-toolkit fd binding changes
- Textual selector subprocess split
- Apple Terminal mouse/focus compatibility changes
- extra selector character-mode wrappers
- preserving or clearing `PENDIN`
- planning selector shutdown cleanup

These changes did not fully solve the real post-plan dashboard bug.

## What the matrix rules out

The current matrix is strong enough to rule out these as primary root causes by themselves:

- planning selector itself
- minimal dashboard itself
- normal dashboard alone
- prompt-toolkit alone
- standalone Textual selector alone
- `TerminalSession.read_command_line(...)` alone
- startup spinner/progress alone
- startup parallelism alone
- post-start reconcile alone
- artifact writes alone
- summary printing alone
- startup-like dashboard state shape alone
- state persistence/reload alone
- startup-style output/emit boundary alone
- startup scaffolding alone

This is why the remaining investigation focus should stay on the real post-plan orchestration path and interactions between components, not on more isolated leaf-feature tweaks.

## Ground truth command set

### Known-good baseline

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_SKIP_PLAN_STARTUP=1 \
ENVCTL_DEBUG_MINIMAL_DASHBOARD=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl \
  --repo /Users/kfiramar/projects/supportopia \
  --plan
```

### Known-bad normal path

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl \
  --repo /Users/kfiramar/projects/supportopia \
  --plan
```

## Implemented diagnostic controls

These flags now exist in the codebase and are the supported way to continue the divide-and-conquer search.

### Snapshot controls

- `ENVCTL_DEBUG_PLAN_SNAPSHOT=1`
  - emits `ui.plan_handoff.snapshot` at:
    - `plan_selector_exit`
    - `startup_branch_enter`
    - `before_dashboard_entry`
    - `after_first_dashboard_render`

### Real-path noop execution gate

- `ENVCTL_DEBUG_PLAN_REAL_NOOP_EXECUTION=1`
  - keeps the real post-plan startup branch
  - bypasses real project side effects
  - still enters the dashboard through the normal path

### Execution-group split

- `ENVCTL_DEBUG_PLAN_EXEC_GROUP=requirements|services|completion`
  - `requirements`
    - runs real requirement startup
    - synthesizes backend/frontend service records
  - `services`
    - synthesizes requirements
    - runs real backend/frontend startup
  - `completion`
    - synthesizes both requirements and services
    - keeps the real post-plan branch shape

### Orchestration-group split

- `ENVCTL_DEBUG_PLAN_ORCH_GROUP=threads|tty|transition`
  - provide one or more tokens, comma- or plus-separated
  - omission of a token disables that orchestration family
  - current families:
    - `threads`
      - startup spinner/live contexts
      - startup parallelism/concurrency path
    - `tty`
      - progress/summary style output on the startup path
      - dashboard refresh status path
    - `transition`
      - startup breakdown / final transition bookkeeping

### Nested TTY-group split

- `ENVCTL_DEBUG_PLAN_TTY_GROUP=termios|output|reader`
  - only meaningful when `ENVCTL_DEBUG_PLAN_ORCH_GROUP` includes `tty`
  - provide one or more tokens, comma- or plus-separated
  - omission of a token disables that nested TTY subgroup
  - current subgroups:
    - `termios`
      - stdout/stderr line-mode normalization
      - `PENDIN` handling
      - selector subprocess `temporary_standard_output_pendin(...)`
    - `output`
      - startup summary printing
      - `ui.status` refresh message path
    - `reader`
      - selector preflight stdin restore/drain
      - selector subprocess parent-thread snapshots and launch hooks

Example:

```bash
ENVCTL_DEBUG_PLAN_REAL_NOOP_EXECUTION=1 \
ENVCTL_DEBUG_PLAN_EXEC_GROUP=completion \
ENVCTL_DEBUG_PLAN_ORCH_GROUP=threads,tty
```

### Important constraint

The supported diagnostic strategy is now:

1. start from the known-good baseline
2. add `ENVCTL_DEBUG_PLAN_REAL_NOOP_EXECUTION=1`
3. split by:
   - `ENVCTL_DEBUG_PLAN_EXEC_GROUP`
   - `ENVCTL_DEBUG_PLAN_ORCH_GROUP`
4. use `ENVCTL_DEBUG_PLAN_SNAPSHOT=1` when a run needs checkpoint comparison

This is preferred over inventing new one-off env flags for every leaf feature.

### Important caveat

Earlier manual runs using `ENVCTL_DEBUG_PLAN_TTY_GROUP=termios|output|reader` before this subgroup was implemented are not valid evidence and should be ignored.

### Real failing path

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl \
  --repo /Users/kfiramar/projects/supportopia \
  --plan
```

## Next debugging direction

Do not add more speculative terminal fixes first.

The next step should be one of:

1. mirror the real startup path more faithfully inside the skip-startup baseline until the bug appears
2. capture a complete parent-thread / fd / termios snapshot before and after the real post-plan startup path and compare it with the known-good baseline
3. temporarily bypass larger orchestrator blocks in the normal path rather than editing terminal code again

## Status

Open investigation.

Current best conclusion:

- the bug is real
- it is specific to the full post-plan startup path in some reused Apple Terminal tabs
- it is not yet pinned to one single feature
- the best debugging asset now is this matrix, because it sharply narrows what is left

## 2026-03-08: Command-Read Split

- The `dashboard_entry` tail-group run is not a reliable discriminator by itself.
  It injects `t` and can reopen/cancel the selector before a stable user-driven
  input window exists.
- The more trustworthy tail-group results remain:
  - `command_read`: bad
  - `selector_launch`: bad
- This matters because a standalone `TerminalSession.read_command_line(...)`
  followed by a standalone Textual selector is healthy in the same bad tab.
  So the remaining likely culprit is the normal dashboard loop around the
  prompt, not `TerminalSession` in isolation and not the selector in isolation.

### Added split

The command loop now supports a narrower split:

- `ENVCTL_DEBUG_PLAN_COMMAND_GROUP=reload`
  - keeps only state reload before the prompt
- `ENVCTL_DEBUG_PLAN_COMMAND_GROUP=render`
  - keeps only dashboard snapshot / command legend rendering before the prompt
- `ENVCTL_DEBUG_PLAN_COMMAND_GROUP=prelude`
  - keeps only the prompt-prelude path before `read_command_line(...)`

These are only meaningful when combined with:

- `ENVCTL_DEBUG_PLAN_REAL_NOOP_EXECUTION=1`
- `ENVCTL_DEBUG_PLAN_EXEC_GROUP=completion`
- `ENVCTL_DEBUG_PLAN_TAIL_GROUP=command_read`

This is the next honest split because the bad `command_read` result is already
inside the common post-dashboard tail, while standalone prompt and selector
probes remain healthy.

### Command-common split

The `command_read` tail is still too coarse, so it is now split further with:

- `ENVCTL_DEBUG_PLAN_COMMAND_COMMON_GROUP=session`
  - keep only dashboard command-loop session bootstrap
  - includes `TerminalSession` setup, backend-policy emit, spinner-policy emit,
    and input flush
  - then injects `t` instead of performing a real read
- `ENVCTL_DEBUG_PLAN_COMMAND_COMMON_GROUP=writes`
  - keep only pre-prompt writes
  - includes dashboard snapshot / command legend / first-render snapshot
  - skips session bootstrap and injects `t`
- `ENVCTL_DEBUG_PLAN_COMMAND_COMMON_GROUP=read`
  - keep only the actual prompt read path
  - skips prompt writes and session bootstrap side effects
  - performs a real `read_command_line(...)`

These are meaningful only when combined with:

- `ENVCTL_DEBUG_PLAN_REAL_NOOP_EXECUTION=1`
- `ENVCTL_DEBUG_PLAN_EXEC_GROUP=completion`
- `ENVCTL_DEBUG_PLAN_TAIL_GROUP=command_read`

This split is designed to answer whether the contaminant is:

1. session/bootstrap setup before the prompt
2. pre-prompt writes and first-render output
3. the actual read path inside the normal dashboard loop

## 2026-03-08: Command-Read Common Slice

Results from the `command_common_group` split in the same bad Apple Terminal tab:

- `session`: bad (`session-20260307225028-41471-7c47`)
- `writes`: bad (`session-20260307225105-42710-34a8`)
- `read`: bad (`session-20260307225145-44313-a457`)

Interpretation:

- the bug is not isolated by removing only session bootstrap
- the bug is not isolated by removing only pre-prompt writes
- the bug is not isolated by removing only the actual prompt read
- therefore the remaining culprit is in the tiny always-on slice shared by all
  three command-loop variants

That shared slice still includes:

- debug tail-group entry bookkeeping
- first dashboard loop state handoff that still occurs before the split gates
- fixed command-loop setup that is not part of `session`, `writes`, or `read`
- any always-on emits or TTY mutations still executed before those subgroup
  gates take effect

### Added split

The command loop now supports one more bisect layer:

- `ENVCTL_DEBUG_PLAN_COMMAND_ALWAYS_GROUP=banner`
  - keep only the banner / static text emission path
- `ENVCTL_DEBUG_PLAN_COMMAND_ALWAYS_GROUP=spinner`
  - keep only spinner-policy / spinner-backend emission path
- `ENVCTL_DEBUG_PLAN_COMMAND_ALWAYS_GROUP=state`
  - keep only the command-loop state-entry bookkeeping path

These are meaningful only when combined with:

- `ENVCTL_DEBUG_PLAN_REAL_NOOP_EXECUTION=1`
- `ENVCTL_DEBUG_PLAN_EXEC_GROUP=completion`
- `ENVCTL_DEBUG_PLAN_TAIL_GROUP=command_read`

If one of these is bad while the others are good, the remaining culprit family is
finally isolated to the tiny always-on pre-prompt slice of the normal dashboard
loop.

## 2026-03-08: Shell Configuration Ruled Out

A clean shell repro using:

```bash
/bin/zsh -df
```

followed by the normal bad-tab `--plan` command still reproduced the bug:

- bad clean-shell session: `session-20260307225708-51854-e49f`

This is enough to rule out the user's interactive zsh startup files as the
primary cause. In particular, it means the bug does **not** depend on:

- `~/.zshrc`
- `~/.zprofile`
- `~/.zshenv`
- `~/.clawdock/clawdock-helpers.sh`
- Kiro shell integration loaded through the normal startup files

The shell-side Kiro integration is still structurally intrusive (zle/precmd/
preexec/PTTY logic), but it is no longer a leading explanation because the bug
survives without shell rc files.

### Supporting trace detail

The clean-shell bad session still shows the same core selector failure pattern
inside the child Textual selector process:

- selector child starts normally
- input thread is alive
- terminal is in raw mode (`lflag=67`)
- only a subset of repeated Down presses reaches Textual
- latest inspected example: only `2` Down events arrived before `Ctrl-C`

So the search space remains:

- envctl post-plan orchestration
- Apple Terminal tab/session behavior after planning selector exit
- shared dashboard-loop / selector-launch interaction

and **not** the user's normal shell config.

## 2026-03-08: Broad 3-Way Split Added

To keep the divide-and-conquer honest, the investigation now has a top-level
3-way split for the remaining real post-plan tail:

- `ENVCTL_DEBUG_PLAN_BROAD_GROUP=dashboard_loop_entry`
- `ENVCTL_DEBUG_PLAN_BROAD_GROUP=prompt_cycle`
- `ENVCTL_DEBUG_PLAN_BROAD_GROUP=selector_handoff`

These map onto the already-implemented tail phases:

- `dashboard_loop_entry -> ENVCTL_DEBUG_PLAN_TAIL_GROUP=dashboard_entry`
- `prompt_cycle -> ENVCTL_DEBUG_PLAN_TAIL_GROUP=command_read`
- `selector_handoff -> ENVCTL_DEBUG_PLAN_TAIL_GROUP=selector_launch`

The purpose of the broad split is not to add new evidence by itself. It makes
the next manual runs and matrix entries match the real remaining search space
cleanly:

1. common dashboard-loop entry tail
2. normal dashboard prompt cycle
3. post-command selector handoff

This avoids depending on the older narrower subgroup flags when the goal is a
wide recursive split.

## 2026-03-08: `dashboard_loop_entry` Recursive Split Added

The latest broad split result showed:

- `dashboard_loop_entry`: bad
- `prompt_cycle`: bad
- `selector_handoff`: bad

Because the earliest broad bucket is already bad, the next useful split moves
inside `dashboard_loop_entry` itself instead of moving later.

Implemented env:

- `ENVCTL_DEBUG_PLAN_ENTRY_GROUP=bootstrap|render|dispatch`

Intent:

- `bootstrap`
  - keeps loop-bootstrap behavior
  - keeps banner / spinner-policy / state-entry setup
  - bypasses prompt rendering
  - bypasses normal dispatch
  - opens the grouped selector directly
- `render`
  - keeps the first dashboard render / command legend / first-render snapshot
  - bypasses loop bootstrap
  - bypasses normal dispatch
  - opens the grouped selector directly
- `dispatch`
  - keeps the injected `t` through the normal interactive command dispatch path
  - this is the closest `dashboard_loop_entry` subgroup to the real flow

This split is intended to answer:

1. is the contaminant already present in loop bootstrap?
2. does the first render / legend output introduce it?
3. or is it specifically the injected command -> dispatch -> selector-open path?

## 2026-03-08: `dashboard_loop_entry` Split Correction

The first round of `ENVCTL_DEBUG_PLAN_ENTRY_GROUP=bootstrap|render|dispatch`
runs should be treated as **invalid** for diagnosis.

Reason:

- the subgroup override was applied too late inside `run_dashboard_command_loop(...)`
- `TerminalSession(...)` could still be constructed before the subgroup override took
effect
- that meant `bootstrap`, `render`, and `dispatch` still shared prompt-session
side effects that the split was supposed to separate

Correction applied:

- `debug_entry_group` is now resolved before `TerminalSession(...)` creation
- `use_session_bootstrap` / `use_prompt_writes` / `use_real_read` are now adjusted
  before any prompt-session side effects occur

Therefore the earlier results for:

- `bootstrap`: bad
- `render`: bad
- `dispatch`: bad

must not be treated as trustworthy evidence.

## 2026-03-08: Broader Post-Loop Split
The `bootstrap/render/dispatch` split still converged on the same `run_dashboard_command_loop(...)` state machine. A broader split was added around the post-plan dashboard loop itself:

- `ENVCTL_DEBUG_PLAN_POSTLOOP_GROUP=direct_selector`
  - bypasses the dashboard loop and opens the grouped selector immediately after post-plan entry
- `ENVCTL_DEBUG_PLAN_POSTLOOP_GROUP=dashboard_only`
  - enters the dashboard loop and command read path but suppresses selector launch on `t`
- `ENVCTL_DEBUG_PLAN_POSTLOOP_GROUP=dashboard_selector`
  - enters the dashboard loop and uses the normal selector path on `t`

This split is intended to answer whether the remaining culprit is:
1. already present before the command loop
2. inside the command loop before selector launch
3. only present when the command loop launches the selector

## 2026-03-08: Selector-Context Broad Split Added

The last trustworthy broad result was:

- `direct_selector`: bad
- `dashboard_only`: flickering / different UX issue
- `dashboard_selector`: bad

Interpretation:

- the failure survives even when the normal dashboard command loop is bypassed and the grouped selector is opened directly from the post-plan path
- therefore the remaining seam is earlier and broader than prompt-cycle internals
- the next useful split is the selector-launch context itself

Implemented env:

- `ENVCTL_DEBUG_PLAN_SELECTOR_GROUP=context|backend|child`

Intended meaning:

- `context`
  - after the real post-plan path, open the grouped selector directly in-process via `select_grouped_targets_textual(...)`
  - bypass backend selector preflight and child selector subprocess launch
- `backend`
  - use the backend selector path, but force `ENVCTL_DEBUG_PLAN_TTY_COMMON_GROUP=preflight`
  - this keeps selector preflight / backend path but bypasses selector subprocess launch
- `child`
  - use the full real selector launch path from the post-plan flow

This is a broad divide-and-conquer seam, not a leaf split.

## 2026-03-08: Earlier Pre-Selector Split Added

The `context|backend|child` results narrowed the problem further:

- `context`: bad
- `backend`: bad
- `child`: bad

Interpretation:

- the failure already exists before backend selector preflight
- the failure already exists before selector subprocess launch
- therefore the remaining seam is earlier than selector internals

An earlier broad split was added:

- `ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=startup_direct|dashboard_direct|command_context`

Intended meaning:

- `startup_direct`
  - after the real post-plan startup/noop path builds the real `RunState`, open the grouped selector immediately
  - bypass `_run_interactive_dashboard_loop(...)` entirely
- `dashboard_direct`
  - enter `_run_interactive_dashboard_loop(...)`
  - immediately open the grouped selector from the dashboard loop
  - bypass normal prompt-cycle reads
- `command_context`
  - enter the normal dashboard loop and prompt cycle
  - use the direct in-process grouped selector context path when `t` is triggered

This split is intended to answer whether the contaminant exists:

1. before the dashboard loop
2. only after entering the dashboard loop
3. only after the normal command cycle begins

### Results

Bad-tab sessions:

- `startup_direct`: bad
  - `session-20260307233520-95476-cd8d`
- `dashboard_direct`: bad
  - `session-20260307233608-97111-aee0`
- `command_context`: bad
  - `session-20260307233638-98686-a5d4`

Interpretation:

- this is the strongest narrowing so far
- because `startup_direct` is already bad, the contaminant exists **before** `_run_interactive_dashboard_loop(...)`
- therefore:
  - the dashboard loop is not the earliest introduction point
  - the prompt cycle is not the earliest introduction point
  - selector backend/preflight/subprocess details are also not the earliest introduction point

The remaining seam is now:

- after planning selector exit
- after the real post-plan startup/noop path begins
- before the dashboard loop is entered

In practical terms, the next broad split must target the real post-plan path between:

1. `plan_selector_exit`
2. `before_dashboard_entry`

not anything inside the dashboard loop itself

## Boundary Replay Split Added (2026-03-08)

A new broad split is now implemented for the remaining interval between:

- `plan_selector_exit`
- `before_dashboard_entry`

This split is different from the earlier fake branch/loop/finalize toggles. The new version is intended to replay across real boundaries so the groups do not immediately reconverge on the same live tail.

New env:

- `ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup|project_loop|finalize`

Semantics:

- `branch_setup`
  - run real post-plan branch setup/scaffolding
  - bypass real project loop and real finalization
  - use a synthetic run state for the downstream direct-selector checkpoint
- `project_loop`
  - build a synthetic loop input route
  - run the real noop project loop/result collection
  - bypass real finalization
  - use a lightweight run state for the downstream direct-selector checkpoint
- `finalize`
  - bypass real branch setup and real project loop
  - use a startup-like synthetic loop output
  - run the real finalization-side effects used by the startup branch
  - then hit the same direct-selector checkpoint

The shared checkpoint for all three groups is:

- emit `before_dashboard_entry`
- open the grouped selector directly via `_open_debug_grouped_selector(...)`

That keeps the downstream comparison point constant while varying only the pre-dashboard phase under test.

Suggested commands for the next round:

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_REAL_NOOP_EXECUTION=1 \
ENVCTL_DEBUG_PLAN_EXEC_GROUP=completion \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia --plan
```

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_REAL_NOOP_EXECUTION=1 \
ENVCTL_DEBUG_PLAN_EXEC_GROUP=completion \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=project_loop \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia --plan
```

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_REAL_NOOP_EXECUTION=1 \
ENVCTL_DEBUG_PLAN_EXEC_GROUP=completion \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=finalize \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia --plan
```

### Boundary Replay Results (2026-03-08)

Bad-tab sessions:

- `branch_setup`: bad
  - `session-20260307234403-5049-ff39`
- `project_loop`: bad
  - `session-20260307234437-6792-f3a6`
- `finalize`: bad
  - `session-20260307234511-8287-6069`

Interpretation:

- the boundary-replay split did not isolate the culprit
- all three groups were still bad, so they are either:
  - still sharing a common earlier tail
  - or the split boundary is still too late in the real path
- by the recursion rule, the next seam must move earlier

Current highest-confidence remaining interval:

- after `plan_selector_exit`
- before the first meaningful divergence into the real startup branch

In other words, the next valid broad split should target the common prefix between:

- planning selector completion
- `startup_branch_enter`

not anything later inside branch setup / project loop / finalize.

## Preentry Split Correction (2026-03-08)

The earlier `branch_setup/project_loop/finalize` runs still shared an in-process selector tail via `_open_debug_grouped_selector(...)`.
That made the split too weak: all three groups could still fail for the same selector-context reason.

Correction:
- preentry groups now force `ENVCTL_DEBUG_PLAN_SELECTOR_GROUP=standalone_child`
- the checkpoint now terminates through the fresh child Textual selector path instead of the shared in-process helper

Intended effect:
- keep the group-specific pre-dashboard phase under test
- remove the known shared in-process selector tail
- make `branch_setup/project_loop/finalize` independent enough to be informative

## Narrowing After Independent Preentry Replay (2026-03-08)

Results:
- `branch_setup`: bad (`session-20260307234934-11769-27a4`)
- `project_loop`: bad (`session-20260307235010-13492-0397`)
- `finalize`: bad (`session-20260307235038-14834-45b3`)

These runs now terminate through a fresh standalone child selector, so the old shared in-process selector tail is no longer a valid explanation.

Updated conclusion:
- the contaminant is earlier than the full `branch_setup/project_loop/finalize` interval
- the remaining shared real-path prefix is the code after the `debug_skip_plan_startup` early-return branch and before `startup_branch_enter` hands off into the preentry group

That remaining prefix is now small enough that the next split should not pretend there are three broad mutually exclusive buckets if the code only exposes two real ones.

## Prefix Tail Split (2026-03-08)

The `gating_only/branch_enter_only/full_prefix` runs all remained bad. That means the optional prefix emits are not separating the bug; the shared tail inside `_debug_run_prefix_group(...)` is still too large.

A new broad split is now wired:

- `ENVCTL_DEBUG_PLAN_PREFIX_TAIL_GROUP=dashboard`
  - keep the prefix group, then enter the known-good minimal dashboard directly
  - no `before_dashboard_entry` emit
  - no direct selector open
- `ENVCTL_DEBUG_PLAN_PREFIX_TAIL_GROUP=snapshot_dashboard`
  - keep the prefix group
  - emit `before_dashboard_entry`
  - then enter the known-good minimal dashboard
- `ENVCTL_DEBUG_PLAN_PREFIX_TAIL_GROUP=selector_direct`
  - keep the prefix group
  - emit `before_dashboard_entry`
  - then open the standalone child selector directly

This split is designed to answer whether the remaining badness in the prefix handler is:
1. already present before dashboard entry,
2. introduced by the `before_dashboard_entry` snapshot/emit path,
3. or specific to the direct selector handoff.

## Branch Setup Subgroup Split (2026-03-08)

The latest trustworthy narrowing is:
- `full_prefix` with all three prefix tails is good
- `branch_setup` is bad

That means the earliest sufficient culprit family is now `branch_setup`.

A new broad subgroup split is now wired under:
- `ENVCTL_DEBUG_PLAN_BRANCH_GROUP=policy|route|live`

These groups partition `_debug_skip_plan_scaffolding(...)` into:
- `policy`
  - spinner policy resolution
  - startup execution policy / parallel config
  - `startup.execution` emit
- `route`
  - docker prewarm gate
  - route-for-execution construction
- `live`
  - project spinner group
  - single-spinner context
  - live/spinner lifecycle enter/exit

This is a broad split of the earliest sufficient bad family, which should have a much better chance of yielding one bad / two good than the later command-loop and selector splits.

## Branch Setup Common Slice Split (2026-03-08)

All three first-level `branch_setup` subgroup runs were bad:
- `policy`
- `route`
- `live`

That means the culprit is likely in the shared always-on slice inside `_debug_skip_plan_scaffolding(...)` that still ran before those subgroup gates.

A new broad split is now wired:
- `ENVCTL_DEBUG_PLAN_BRANCH_COMMON_GROUP=env_policy|route_scaffold|context_setup`

These groups partition the common slice into:
- `env_policy`
  - `resolve_spinner_policy(...)`
  - `use_startup_spinner` derivation
  - policy-side env interpretation
- `route_scaffold`
  - docker prewarm gate
  - `route_for_execution` construction
  - debug suppress-progress route flag wiring
- `context_setup`
  - `use_project_spinner_group` derivation
  - `_ProjectSpinnerGroup(...)` construction
  - spinner/live context setup gating

This is the next honest split of the earliest currently sufficient bad family.

## Branch Setup Root Slice Split (2026-03-08)

The `ENVCTL_DEBUG_PLAN_BRANCH_COMMON_GROUP=env_policy|route_scaffold|context_setup` runs all came back bad. That means the earlier split was still not isolating the shared always-on slice inside `_debug_skip_plan_scaffolding(...)`.

A new, earlier split is now wired:
- `ENVCTL_DEBUG_PLAN_BRANCH_ROOT_GROUP=entry|route_context|tail_live`

These groups partition the broader `branch_setup` phase into:
- `entry`
  - initial branch-setup emit
  - spinner message derivation
  - spinner policy resolution
  - startup spinner eligibility
  - startup execution / policy branch
- `route_context`
  - docker prewarm gate
  - `route_for_execution` construction
  - project spinner-group eligibility
  - spinner-group object construction
- `tail_live`
  - live/spinner context entry/exit
  - single-spinner lifecycle emits
  - final `startup.debug_split_group` completion emit

This split is earlier than the common-slice groups and is intended to isolate the shared always-on path inside `branch_setup` before the later subgroup gates.

## Branch Setup Shell Split (2026-03-08)

All three `ENVCTL_DEBUG_PLAN_BRANCH_ROOT_GROUP=entry|route_context|tail_live` runs were bad. That means even the earlier root split is still not independent enough.

A new shell-level split is now wired around `_debug_skip_plan_scaffolding(...)`:
- `ENVCTL_DEBUG_PLAN_BRANCH_SHELL_GROUP=callsite`
  - skips the scaffolding call entirely from the `branch_setup` preentry path
- `ENVCTL_DEBUG_PLAN_BRANCH_SHELL_GROUP=emit_shell`
  - enters `_debug_skip_plan_scaffolding(...)`, emits the initial `startup.debug_branch_setup_group`, then returns immediately
- `ENVCTL_DEBUG_PLAN_BRANCH_SHELL_GROUP=body`
  - runs the full scaffolding body

This split is intended to answer whether the contaminant is:
1. already present at the `branch_setup` callsite,
2. introduced by the early shell/emit of `_debug_skip_plan_scaffolding(...)`,
3. or only introduced deeper in the scaffolding body.

## Branch Setup Root Split Result (2026-03-08)

All three `ENVCTL_DEBUG_PLAN_BRANCH_ROOT_GROUP=entry|route_context|tail_live` runs were bad.

This means the root split still reconverged on a shared always-on shell inside the `branch_setup` preentry path. The results are not discriminative enough to justify another broad 3-way split at that seam.

At this point, the known-good prefix path (`full_prefix` + any prefix tail) and the bad `branch_setup` preentry path differ only by a very small shell around `_debug_run_preentry_group(..., group="branch_setup")`.

That means the next honest split is no longer a broad 3-way divide. The remaining delta is small enough that only a narrow shell-level split is defensible.

## Direct Preentry Run Validity Guard (2026-03-08)

A repeated failure mode in the later `branch_setup/project_loop/finalize` and related preentry splits was that some runs were likely **invalid** for isolation because they still appeared to fall through into the normal dashboard path.

To make those runs unambiguous, the direct preentry paths now print an explicit marker before opening the standalone selector child:

- `DEBUG DIRECT SELECTOR MODE (no dashboard). Do not press t.`

Interpretation rule:
- If a run using a direct preentry split (`ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=...`) shows the dashboard prompt, that run is invalid for isolating the preentry seam and should be ignored.
- Only runs that show the direct-mode marker and open the selector immediately should be treated as valid evidence for the preentry split.

This guard makes the direct preentry path consistent with the already-proven-good `full_prefix + selector_direct` debug path, which already printed the same marker.

## Auto-Resume Interception Of Preentry Splits (2026-03-08)

A real bug in the isolation harness was identified in the `StartupOrchestrator.execute(...)` control flow:

- `debug_prefix_group` returns **before** the auto-resume gate.
- `debug_preentry_group` executes **after** the auto-resume gate.

That meant runs like:
- `ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup`
- `ENVCTL_DEBUG_PLAN_BRANCH_SHELL_GROUP=callsite|emit_shell|body`

could be silently intercepted by auto-resume and fall through to the normal dashboard path instead of the intended direct-selector debug path.

This exactly matches the observed invalid sessions where:
- the normal dashboard appeared,
- the direct-mode marker did not appear,
- and the run reused the old run id `run-20260307185613-ccf700c2`.

Those preentry-shell sessions should therefore be treated as **invalid** for diagnosis until auto-resume is force-skipped for real-noop / preentry debug modes.

The harness was corrected so that:
- `ENVCTL_DEBUG_PLAN_REAL_NOOP_EXECUTION=1`
- `ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=...`

now force `debug_skip_plan_auto_resume = True` before the resume gate.

## Valid Branch-Setup Shell Split (2026-03-08)

After fixing the isolation harness so that real-noop / preentry debug modes force-skip auto-resume, the `branch_setup` shell split became trustworthy.

Validated runs:
- `ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup`
- `ENVCTL_DEBUG_PLAN_BRANCH_SHELL_GROUP=callsite`
  - session: `session-20260308124202-46287-1192`
  - result: **good**
- `ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup`
- `ENVCTL_DEBUG_PLAN_BRANCH_SHELL_GROUP=emit_shell`
  - session: `session-20260308124216-46576-3c1c`
  - result: **good**
- `ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup`
- `ENVCTL_DEBUG_PLAN_BRANCH_SHELL_GROUP=body`
  - session: `session-20260308124225-46846-93b0`
  - result: **good**

All three valid runs showed the direct-mode marker:
- `DEBUG DIRECT SELECTOR MODE (no dashboard). Do not press t.`

This rules out the `branch_setup` shell itself as a sufficient cause when isolated cleanly.

Updated conclusion:
- the remaining culprit is later than the isolated `branch_setup` shell,
- or is an interaction between `branch_setup` and a later pre-dashboard phase,
- but it is not caused by the `branch_setup` shell alone.

Next honest split:
- rerun the same direct-mode-valid preentry isolation for:
  - `project_loop`
  - `finalize`
- if one of those is bad, recurse only into that phase
- if both are good, the remaining explanation is interaction between phases rather than a single isolated phase

## Valid Preentry Phase Isolation: All Three Good (2026-03-08)

After fixing the auto-resume interception bug for real-noop / preentry debug modes, the broad preentry phases were re-run under the direct-selector validity guard.

Validated runs:
- `ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=project_loop`
  - session: `session-20260308124318-48022-0c15`
  - result: **good**
- `ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=finalize`
  - session: `session-20260308124325-48211-ad07`
  - result: **good**
- together with the earlier valid `branch_setup` shell split being entirely good, this means:
  - `branch_setup` is good in isolation
  - `project_loop` is good in isolation
  - `finalize` is good in isolation

Updated conclusion:
- the remaining culprit is not a single isolated preentry phase
- the remaining plausible explanation is an **interaction between phases** in the real post-plan path
- the correct next step is pairwise phase testing:
  - `branch_setup + project_loop`
  - `branch_setup + finalize`
  - `project_loop + finalize`

## Correction: Initial Pairwise Preentry Runs Were Invalid (2026-03-08)

The first pairwise preentry commands using:

- `ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop`
- `ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,finalize`
- `ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=project_loop,finalize`

were **not valid evidence**.

Reason:

- `ENVCTL_DEBUG_PLAN_PREENTRY_GROUP` only accepted a single token at that point.
- Comma-separated values were falling through to the normal path.
- Any conclusions drawn from those first pairwise runs should be ignored.

This has now been corrected in `startup_orchestrator.py`, and pairwise preentry testing must be rerun before treating those interactions as real evidence.

## Valid Pairwise Preentry Result: All Three Pairs Good (2026-03-08)

After fixing `ENVCTL_DEBUG_PLAN_PREENTRY_GROUP` to accept comma-separated combinations, the pairwise preentry runs became valid and all three were **good**:

- `branch_setup + project_loop`: good (`session-20260308124952-52661-409c`)
- `branch_setup + finalize`: good (`session-20260308125001-53016-f4b9`)
- `project_loop + finalize`: good (`session-20260308125009-53267-1697`)

All three runs showed the required direct-mode marker:

- `DEBUG DIRECT SELECTOR MODE (no dashboard). Do not press t.`

and all three kept selector input healthy.

### Meaning

This is the first strong interaction result:

- `branch_setup` is good in isolation
- `project_loop` is good in isolation
- `finalize` is good in isolation
- every **pair** of those phases is also good

So the remaining culprit is **not** inside any isolated preentry phase or any pairwise interaction among them.

The remaining plausible explanation is now:

- the **full three-phase preentry path together**,
- or the interaction between the full preentry path and the later dashboard/prompt/selector-launch path.

That means the next honest split must move back to the seam between:

- `full preentry -> direct selector` (known-good)
- `full preentry -> dashboard loop / prompt / selector launch` (still bad in the real path)

and isolate the broadest dashboard-side groups that only exist once the full preentry path has already run.

## Valid Pairwise Preentry Result With Normal Dashboard (2026-03-08)

The following runs were re-executed after fixing the preentry combo parsing bug, and they are valid.

All three combinations were **good** in the normal dashboard path:

- `branch_setup + project_loop`: good (`session-20260308124952-52661-409c`)
- `branch_setup + finalize`: good (`session-20260308125001-53016-f4b9`)
- `project_loop + finalize`: good (`session-20260308125009-53267-1697`)

These runs did **not** use the direct-selector marker path. They returned to the normal dashboard, accepted `t`, and the dashboard-opened selector behaved normally.

### Meaning

This is stronger than the earlier single-phase direct-selector result:

- each preentry phase is good in isolation when terminated through the direct-selector path
- each pairwise preentry combination is also good when allowed to return through the normal dashboard path
- therefore the remaining culprit is most likely one of:
  - a stateful interaction that appears only when **all three** preentry phases are combined
  - a shared always-on slice outside the current preentry split that still survives all earlier grouping

### Updated conclusion

The search space has narrowed to:

- the **three-way interaction** among `branch_setup`, `project_loop`, and `finalize`
- or a still-unisolated common tail that is present only in the real full preentry path

This means the next useful split should not keep testing single preentry phases or pairwise preentry combinations. Those are now ruled out as sufficient causes.

## Decisive Full-Preentry Result (2026-03-08)

The following runs were executed with:

- `ENVCTL_DEBUG_PLAN_REAL_NOOP_EXECUTION=1`
- `ENVCTL_DEBUG_PLAN_EXEC_GROUP=completion`
- `ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize`

and three different post-preentry tails.

All three were **good**:

- `all preentry + direct_selector`: good (`session-20260308125518-55448-df50`)
- `all preentry + minimal_dashboard`: good (`session-20260308125525-55818-6953`)
- `all preentry + full_dashboard`: good (`session-20260308125540-56121-5e45`)

### Meaning

This is the strongest narrowing so far.

It rules out the entire preentry interval as a sufficient cause when project execution is reduced to the noop/completion shape.

Therefore the remaining culprit requires **real project-execution side effects**, not just:

- branch setup
- project-loop shell
- finalize
- dashboard entry
- prompt cycle
- selector launch

under the noop execution model.

### Updated conclusion

The remaining search space should now move back into the real execution path and be split broadly there.

The most honest next broad split is:

1. requirements-side execution
2. services-side execution
3. real execution completion/merge path

but this time combined with the now-proven-good full preentry + full dashboard context.

## Broad Execution Split Result (2026-03-08)

Using:

- `ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize`
- `ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard`

and varying only `ENVCTL_DEBUG_PLAN_EXEC_GROUP`, the result was:

- `requirements`: good (`session-20260308125714-58669-d722`)
- `services`: bad (`session-20260308125733-59097-4b25`)
- `completion`: good (`session-20260308125801-60248-7ee3`)

### Meaning

This is the first broad execution split that isolates a single bad group.

It rules out, as sufficient causes in this full-context setup:

- requirements-side execution
- completion/merge-side execution

and strongly implicates the **services-side execution path**.

### Updated conclusion

The next recursion should split only the services-side execution path into 3 broad groups.

## 2026-03-08: Service subgroup split corrected

The earlier `bootstrap / launch_attach / record_merge` service-group runs were not valid evidence.
At that time, `_debug_service_group` was not propagated through `route_for_execution`, so those runs fell through to the generic `services` execution path.

This is now fixed in:
- `/Users/kfiramar/projects/envctl/python/envctl_engine/startup/startup_orchestrator.py`

And covered in tests in the same shape as the manual runs:
- full preentry enabled: `branch_setup,project_loop,finalize`
- full dashboard enabled: `full_dashboard`

Focused test result after the fix:
- `debug_exec_group_services`
- `debug_service_group_bootstrap`
- `debug_service_group_launch_attach`
- `debug_service_group_record_merge`
- `4 passed`

Current valid broad finding:
- `requirements` execution path: good
- `completion` execution path: good
- `services` execution path: bad

Next valid split to rerun manually:
- `bootstrap`
- `launch_attach`
- `record_merge`

All three must be run with:
- `ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize`
- `ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard`

Only these reruns should be treated as evidence.

## 2026-03-08: Services split isolated the culprit family

Valid rerun results with the service subgroup properly propagated through `route_for_execution` and exercised under:
- `ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize`
- `ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard`

Results:
- `bootstrap`: good
- `record_merge`: good
- `launch_attach`: bad

This is the first clean isolation of a single bad broad bucket.

Current strongest conclusion:
- the post-plan input bug is introduced by the **service launch / attach** phase, not by:
  - service bootstrap/runtime-prep alone
  - service record merge/state shaping alone

The next recursive split should stay entirely inside `launch_attach` and divide it into three broad subgroups:
1. process launch
2. listener/actual-port detection
3. post-attach service-state shaping

## Valid service-side isolation result

The service-side broad split is now trustworthy.

Validated results:

- `bootstrap`: good
- `launch_attach`: bad
- `record_merge`: good

Interpretation:

- the remaining culprit family is the real service launch / attach path
- it is not explained by bootstrap/runtime-prep alone
- it is not explained by post-attach service record shaping alone

Important correction:

- earlier `ENVCTL_DEBUG_PLAN_ATTACH_GROUP=process_start|listener_probe|attach_merge` manual runs should be treated as invalid historical evidence
- at that time the attach subgroup was not fully wired through the route / execution path
- attach subgroup routing and tests are now implemented and passing locally

Next valid split is inside `launch_attach` itself.

## 2026-03-08: Valid services split result under full preentry + full dashboard

Using:
- `ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize`
- `ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard`
- varying only `ENVCTL_DEBUG_PLAN_SERVICE_GROUP`

Manual result:
- `bootstrap`: good (`session-20260308131342-70292-7cfc`)
- `launch_attach`: bad (`session-20260308131355-70727-fc1e`)
- `record_merge`: good (`session-20260308131418-71814-1a52`)

Interpretation:
- the remaining culprit family is inside the real service launch / attach path
- it is not explained by bootstrap/runtime-prep alone
- it is not explained by post-attach record shaping alone

Next recursion should stay entirely inside `launch_attach`.

## 2026-03-08: Trustworthy launch-attach subgroup result under full preentry + full dashboard

Using the fully trusted enclosing context:
- `ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize`
- `ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard`
- `ENVCTL_DEBUG_PLAN_EXEC_GROUP=services`
- varying only `ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach` with `ENVCTL_DEBUG_PLAN_ATTACH_GROUP`

The latest trustworthy manual results are:

- `process_start`: good in the bug sense
  - session: `session-20260308132951-85637-deda`
  - caveat: dashboard typing was normal, but pressing `t` did not open the selector and returned `No test target selected.`
  - services displayed as `0 total`, which is materially different from the bad launch-attach path
- `listener_probe`: bad
  - session: `session-20260308133058-86355-c076`
  - dashboard entered the usual degraded state and selector behavior remained bad
- `attach_merge`: good in the bug sense
  - session: `session-20260308133142-87605-ac61`
  - caveat: dashboard typing was normal, but pressing `t` did not open the selector and returned `No test target selected.`

### Interpretation

This is the strongest current narrowing inside the trustworthy `launch_attach` family.

It suggests:
- the remaining culprit is most likely in the **listener / actual-port detection / attach probing** path
- plain process spawn alone is not sufficient to reproduce the degraded dashboard typing / selector-input bug
- post-attach record shaping alone is not sufficient either

### Important caveat

The `process_start` and `attach_merge` runs should be treated as **good in the bug sense**, not as full feature parity with the bad path. They changed the interactive outcome materially:
- the dashboard itself was not degraded
- but `t` did not open the selector and returned `No test target selected.`

So these two runs ruled out the degraded-input symptom, but they also indicate that the attach subgroup routing changes the post-start service/dashboard contract enough that follow-up recursion should stay anchored on the `listener_probe` subgroup, which preserved the bug.

### Current best conclusion

The remaining highest-confidence culprit family is now:
- `services`
- `launch_attach`
- `listener_probe`

That is the current best seam for the next recursive split.

## 2026-03-08: Attach-subgroup routing verification in code

Before asking for any additional manual runs, I re-verified that `ENVCTL_DEBUG_PLAN_ATTACH_GROUP` is genuinely wired through the current `launch_attach` path.

Verified code facts:

- parse point: [startup_orchestrator.py](/Users/kfiramar/projects/envctl/python/envctl_engine/startup/startup_orchestrator.py#L289)
- route forwarding point: [startup_orchestrator.py](/Users/kfiramar/projects/envctl/python/envctl_engine/startup/startup_orchestrator.py#L1378)
- execution re-validation and marker emission:
  - `startup.debug_service_group`
  - `startup.debug_attach_group`
  - see [startup_execution_support.py](/Users/kfiramar/projects/envctl/python/envctl_engine/startup/startup_execution_support.py#L594)
- distinct branch dispatch points inside `launch_attach`:
  - `process_start`: [startup_execution_support.py](/Users/kfiramar/projects/envctl/python/envctl_engine/startup/startup_execution_support.py#L978)
  - `listener_probe`: [startup_execution_support.py](/Users/kfiramar/projects/envctl/python/envctl_engine/startup/startup_execution_support.py#L1023)
  - `attach_merge`: [startup_execution_support.py](/Users/kfiramar/projects/envctl/python/envctl_engine/startup/startup_execution_support.py#L1070)

Updated trust rule:

- a manual attach-subgroup run is valid only if its event log shows:
  - `startup.debug_service_group` with `group=launch_attach`
  - `startup.debug_attach_group` with the requested subgroup
- otherwise the run should still be treated as invalid historical evidence

## 2026-03-08: Verified manual reruns for `process_start / listener_probe / attach_merge`

The latest three manual reruns are trustworthy. I verified their event logs directly:

- `session-20260308134343-98321-cac6`
  - `startup.debug_service_group=launch_attach`
  - `startup.debug_attach_group=process_start`
- `session-20260308134447-99265-faa6`
  - `startup.debug_service_group=launch_attach`
  - `startup.debug_attach_group=listener_probe`
- `session-20260308134528-763-6aff`
  - `startup.debug_service_group=launch_attach`
  - `startup.debug_attach_group=attach_merge`

So the user-reported outcomes for those three reruns should be treated as valid evidence.

## 2026-03-08: Added finer split inside `listener_probe`

There was no pre-existing finer listener subgroup env.

Implemented smallest next split:

- `ENVCTL_DEBUG_PLAN_LISTENER_GROUP=pid_wait`
  - isolates `wait_for_pid_port(...)`
- `ENVCTL_DEBUG_PLAN_LISTENER_GROUP=port_fallback`
  - isolates `wait_for_port(...)` fallback recovery
- `ENVCTL_DEBUG_PLAN_LISTENER_GROUP=rebound_discovery`
  - isolates `find_pid_listener_port(...)`

Routing / observability:

- parse point: [startup_orchestrator.py](/Users/kfiramar/projects/envctl/python/envctl_engine/startup/startup_orchestrator.py#L293)
- forwarded only under:
  - `services`
  - `launch_attach`
  - `listener_probe`
  - see [startup_orchestrator.py](/Users/kfiramar/projects/envctl/python/envctl_engine/startup/startup_orchestrator.py#L1388)
- runtime execution marker:
  - `startup.debug_listener_group`
  - see [startup_execution_support.py](/Users/kfiramar/projects/envctl/python/envctl_engine/startup/startup_execution_support.py#L626)

Important behavior for narrowed listener runs:

- if the selected listener subgroup alone does not detect a port, the debug path now emits `startup.debug_listener_group.synthetic_actual`
- this preserves dashboard entry so the degraded-input symptom can still be judged
- such a run is still valid, but its service state is more synthetic than the fully bad `listener_probe` path

## 2026-03-08: Trustworthy result inside `listener_probe`

Verified event-log-backed manual results:

- `session-20260308134939-2965-6005`
  - `startup.debug_listener_group=pid_wait`
  - bad
- `session-20260308135102-4588-8e0a`
  - `startup.debug_listener_group=port_fallback`
  - `startup.debug_listener_group.synthetic_actual` emitted
  - dashboard fluid, but `services: 0 total` and `t` did not open selector
- `session-20260308135158-5283-cd62`
  - `startup.debug_listener_group=rebound_discovery`
  - `startup.debug_listener_group.synthetic_actual` emitted
  - dashboard fluid, but `services: 0 total` and `t` did not open selector

Interpretation:

- only `pid_wait` is currently sufficient to preserve the fully populated running-services shape and still reproduce the buggy input
- the strongest remaining culprit family is now:
  - `services`
  - `launch_attach`
  - `listener_probe`
  - `pid_wait`

## 2026-03-08: Added finer split inside `pid_wait`

The real code inside `wait_for_pid_port(...)` is three checks in a loop:

- `signal_gate`
  - `os.kill(pid, 0)` liveness check
- `pid_port_lsof`
  - direct `lsof` query for `pid + exact requested port`
- `tree_port_scan`
  - zero-delta `find_pid_listener_port(...)` process-tree scan

Implemented routing surface:

- `ENVCTL_DEBUG_PLAN_PID_WAIT_GROUP=signal_gate|pid_port_lsof|tree_port_scan`
- parse point: [startup_orchestrator.py](/Users/kfiramar/projects/envctl/python/envctl_engine/startup/startup_orchestrator.py#L297)
- emitted execution marker:
  - `startup.debug_pid_wait_group`
  - see [startup_execution_support.py](/Users/kfiramar/projects/envctl/python/envctl_engine/startup/startup_execution_support.py#L638)
- narrowed execution point:
  - [process_runner.py](/Users/kfiramar/projects/envctl/python/envctl_engine/shared/process_runner.py#L365)

## 2026-03-08: Why the `pid_wait` subgroup reruns were non-discriminative

The three `pid_wait` subgroup reruns were valid, but they reconverged on a shared later tail and therefore did not isolate the culprit further.

Verified code reason:

- after `start_project_services(...)`, the services path still runs `_assert_project_services_post_start_truth(...)`
  - [startup_execution_support.py](/Users/kfiramar/projects/envctl/python/envctl_engine/startup/startup_execution_support.py#L123)
- that calls `service_truth_status(...)`
  - [engine_runtime_service_truth.py](/Users/kfiramar/projects/envctl/python/envctl_engine/runtime/engine_runtime_service_truth.py#L160)
- and `service_truth_status(...)` was still running the full truth sequence:
  - `wait_for_pid_port`
  - `port_fallback`
  - `truth_discovery`
  - listener-pid refresh

So the attach-side `ENVCTL_DEBUG_PLAN_PID_WAIT_GROUP` split was valid execution-wise, but not trustworthy as a final seam because all three runs still reconverged on the same unfiltered post-start truth path.

## 2026-03-08: Added post-start truth split

Implemented:

- `ENVCTL_DEBUG_PLAN_POSTSTART_TRUTH_GROUP=pid_wait|port_fallback|truth_discovery`

Routing:

- parse point: [startup_orchestrator.py](/Users/kfiramar/projects/envctl/python/envctl_engine/startup/startup_orchestrator.py#L301)
- execution marker:
  - `startup.debug_poststart_truth_group`
  - [startup_execution_support.py](/Users/kfiramar/projects/envctl/python/envctl_engine/startup/startup_execution_support.py#L128)

This is the next honest seam because it isolates the shared tail that all three `pid_wait` subgroup runs still traversed.

## 2026-03-08: Trustworthy startup post-start truth result

Verified event-log-backed result:

- `pid_wait`: fluid dashboard, but `services: 0 total` and selector did not open
  - session: `session-20260308140433-15087-8a55`
- `port_fallback`: fluid dashboard, but `services: 0 total` and selector did not open
  - session: `session-20260308140457-16100-e491`
- `truth_discovery`: bad, with full `services: 8 total` state preserved
  - session: `session-20260308140513-16937-c54f`

Interpretation:

- inside the startup post-start truth pass, `truth_discovery` is the only current bad subgroup

## 2026-03-08: Later dashboard truth refresh is a separate shared tail

The `truth_discovery` startup run still showed later `service.truth.check` events on `ThreadPoolExecutor-*` threads after dashboard entry.

That later path comes from:

- `dashboard_reconcile_for_snapshot(...)` in [engine_runtime_dashboard_truth.py](/Users/kfiramar/projects/envctl/python/envctl_engine/runtime/engine_runtime_dashboard_truth.py#L32)
- which calls `reconcile_state_truth(...)` in [engine_runtime_state_truth.py](/Users/kfiramar/projects/envctl/python/envctl_engine/runtime/engine_runtime_state_truth.py#L232)
- which again runs `runtime._service_truth_status(service)` in a thread pool

So startup `truth_discovery` is not the final seam by itself. The later dashboard truth-refresh path still reconverges on full service truth evaluation after entry.

## 2026-03-08: Added dashboard truth split

Implemented:

- `ENVCTL_DEBUG_PLAN_DASHBOARD_TRUTH_GROUP=pid_wait|port_fallback|truth_discovery`

Observability:

- emitted as `dashboard.debug_truth_group`
  - [engine_runtime_dashboard_truth.py](/Users/kfiramar/projects/envctl/python/envctl_engine/runtime/engine_runtime_dashboard_truth.py#L40)

This is the next honest seam for the remaining bad path, because it targets the post-entry threaded truth refresh rather than only the startup-time truth assertion.

## 2026-03-08: Dashboard truth split also reconverged

Verified event-log-backed reruns:

- `pid_wait`: bad
  - session: `session-20260308140915-20877-4ad2`
- `port_fallback`: bad
  - session: `session-20260308141000-22340-5bc3`
- `truth_discovery`: bad
  - session: `session-20260308141051-23583-03da`

All three runs were valid:

- each log showed `startup.debug_service_group=launch_attach`
- each log showed `dashboard.debug_truth_group` with the requested subgroup

But all three still traversed the same selector-wrapper tail:

- `ui.input.submit normalized_command=test`
- `ui.selector.preflight`
- `ui.selector.subprocess`

The grouped selector subprocess traces for those sessions still showed:

- enter on `stdout/stderr` with `lflag=536872395`, `pendin=true`
- restore to `lflag=1483`, `pendin=false` on exit
- only `3` to `4` `Down` events received before `Ctrl-C`

Interpretation:

- dashboard truth is not the next trustworthy seam
- the next real common boundary is the selector-wrapper path in [backend.py](/Users/kfiramar/projects/envctl/python/envctl_engine/ui/backend.py)

## 2026-03-08: Added explicit selector-wrapper branch marker

Implemented:

- `startup.debug_tty_common_group`

Location:

- [backend.py](/Users/kfiramar/projects/envctl/python/envctl_engine/ui/backend.py#L284)

Emitted fields:

- `selector_kind`
- `group=default|dashboard|preflight|subprocess`
- `run_preflight`
- `run_subprocess`
- `run_inprocess_direct`

This makes the next split trustworthy by event-log proof rather than by inference from UI behavior.

## 2026-03-08: Next 3-way split inside the shared selector wrapper

Use:

- `ENVCTL_DEBUG_PLAN_TTY_COMMON_GROUP=dashboard|preflight|subprocess`

Real code boundary mapping in [backend.py](/Users/kfiramar/projects/envctl/python/envctl_engine/ui/backend.py):

- `dashboard`
  - skip selector preflight
  - skip selector subprocess
  - run selector in-process directly
- `preflight`
  - run selector preflight
  - skip selector subprocess
  - run selector in-process directly
- `subprocess`
  - skip selector preflight
  - force selector subprocess wrapper

### Next 3 manual commands

#### `dashboard`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_TTY_COMMON_GROUP=dashboard \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia --plan
```

#### `preflight`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_TTY_COMMON_GROUP=preflight \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia --plan
```

#### `subprocess`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_TTY_COMMON_GROUP=subprocess \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia --plan
```

### Validation rule

Trust a run only if the event log shows:

- `startup.debug_service_group=launch_attach`
- `startup.debug_tty_common_group` with the requested `group`

And the branch booleans match:

- `dashboard`: `run_preflight=false`, `run_subprocess=false`, `run_inprocess_direct=true`
- `preflight`: `run_preflight=true`, `run_subprocess=false`, `run_inprocess_direct=true`
- `subprocess`: `run_preflight=false`, `run_subprocess=true`, `run_inprocess_direct=false`

## 2026-03-08: `TTY_COMMON_GROUP` also reconverged

Verified runs:

- `dashboard`: bad
  - `session-20260308141849-28971-34d3`
- `preflight`: bad
  - `session-20260308141914-30057-c40c`
- `subprocess`: bad
  - `session-20260308141940-31169-5c61`

These runs were trustworthy:

- `startup.debug_service_group=launch_attach` present
- `startup.debug_tty_common_group` present with the requested group
- branch booleans matched the requested branch exactly

Observed shared result:

- `dashboard` still failed with direct in-process selector
- `preflight` still failed with backend preflight plus in-process selector
- `subprocess` still failed with forced subprocess selector

Interpretation:

- the selector-wrapper split is too late
- the contaminant already exists before `dashboard|preflight|subprocess` diverge

## 2026-03-08: Preselector split corrected for a constant selector tail

The next earlier real seam is:

- `ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=startup_direct|dashboard_direct|command_context`

But the old version of that split did not hold the downstream selector tail constant.
That made it weaker than necessary under the current `services -> launch_attach` isolation.

Correction implemented in [startup_orchestrator.py](/Users/kfiramar/projects/envctl/python/envctl_engine/startup/startup_orchestrator.py#L1039):

- `startup_direct` now forces `ENVCTL_DEBUG_PLAN_SELECTOR_GROUP=standalone_child`
- `dashboard_direct` now forces `ENVCTL_DEBUG_PLAN_SELECTOR_GROUP=standalone_child`
- `command_context` now forces `ENVCTL_DEBUG_PLAN_SELECTOR_GROUP=standalone_child`

This keeps the selector checkpoint constant while varying only the earlier boundary under test.

### Real code boundary meanings

- `startup_direct`
  - after the real startup branch builds the real `RunState`
  - open the standalone child selector immediately
  - bypass `_run_interactive_dashboard_loop(...)`
- `dashboard_direct`
  - enter `_run_interactive_dashboard_loop(...)`
  - immediately open the same standalone child selector on loop entry
  - bypass the normal prompt-cycle read
- `command_context`
  - enter the normal dashboard loop
  - read the real command from the prompt
  - when `t` is triggered, open the same standalone child selector

### Next 3 manual commands

#### `startup_direct`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=startup_direct \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia --plan
```

#### `dashboard_direct`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=dashboard_direct \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia --plan
```

#### `command_context`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=command_context \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia --plan
```

### Validation rule

Trust a run only if the event log shows:

- `startup.debug_service_group=launch_attach`
- `startup.debug_preselector_group` with the requested group
- `startup.debug_selector_group=standalone_child`

Expected event shapes:

- `startup_direct`
  - `action=direct_selector_before_dashboard`
- `dashboard_direct`
  - `action=dashboard_loop_override`
  - selector opens immediately without pressing `t`
- `command_context`
  - `action=dashboard_loop_override`
  - press `t` to trigger the selector

## 2026-03-08: Preselector reruns were invalid in the current full harness

The three reruns with:

- `ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=startup_direct`
- `ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=dashboard_direct`
- `ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=command_context`

were not trustworthy under the active full context:

- `ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize`
- `ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard`

Verified log reason:

- none of the runs emitted `startup.debug_preselector_group`
- all three instead traversed the normal preentry tail:
  - `before_dashboard_entry`
  - `after_first_dashboard_render`
  - then ordinary `ui.input.submit`
  - then ordinary `ui.selector.preflight` / `ui.selector.subprocess`

So those three runs did not actually test the requested preselector branches.

## 2026-03-08: Fixed preselector handling inside the preentry tail

Root cause:

- `_debug_run_post_preentry_tail(...)` in [startup_orchestrator.py](/Users/kfiramar/projects/envctl/python/envctl_engine/startup/startup_orchestrator.py#L1497)
  ignored `ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP`

Correction implemented:

- preentry-tail execution now honors:
  - `startup_direct`
  - `dashboard_direct`
  - `command_context`
- all three force `ENVCTL_DEBUG_PLAN_SELECTOR_GROUP=standalone_child`
  so the selector checkpoint stays constant

Compile check passed after this fix.

## 2026-03-08: Rerun the same 3 preselector commands

The command texts stay the same. They are now valid under the current harness.

### `startup_direct`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=startup_direct \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia --plan
```

### `dashboard_direct`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=dashboard_direct \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia --plan
```

### `command_context`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=command_context \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia --plan
```

### Updated validation rule

Trust a run only if the event log shows:

- `startup.debug_service_group=launch_attach`
- `startup.debug_preselector_group` with the requested group
- `startup.debug_selector_group=standalone_child`

Expected runtime shape:

- `startup_direct`
  - selector opens before the dashboard loop
  - `action=direct_selector_before_dashboard`
- `dashboard_direct`
  - selector opens immediately on dashboard-loop entry
  - `action=dashboard_loop_override`
- `command_context`
  - dashboard prompt appears first
  - press `t` to trigger selector
  - `action=dashboard_loop_override`

## 2026-03-08: Corrected preselector split is valid and all three are bad

Verified valid reruns:

- `startup_direct`: bad
  - `session-20260308142719-40110-f9f2`
- `dashboard_direct`: bad
  - `session-20260308142752-41191-09f0`
- `command_context`: bad
  - `session-20260308142823-42181-1ace`

Why these are trustworthy:

- each run emitted `startup.debug_service_group=launch_attach`
- each run emitted `startup.debug_preselector_group` with the requested group
- each run emitted `startup.debug_selector_group=standalone_child`

Observed behavior:

- `startup_direct`
  - standalone child selector opened before the dashboard loop
- `dashboard_direct`
  - dashboard loop entered, then standalone child selector opened immediately
- `command_context`
  - dashboard prompt appeared, then the same selector opened after `t`

All three selector subprocess traces still showed the same core failure:

- only `2` to `4` `Down` events reached the selector
- then idle until `Ctrl-C`

Interpretation:

- every post-start interactive tail is now too late
- the contaminant already exists before the earliest standalone child selector checkpoint
- the next honest split must move back into `services -> launch_attach`

## 2026-03-08: Next attach-group rerun with the earliest constant tail

Rerun the attach-group split, but now with:

- `ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=startup_direct`

That keeps the downstream comparison point constant:

- requested `launch_attach` subgroup
- then immediate standalone child selector before the dashboard loop

### Next 3 manual commands

#### `process_start`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_ATTACH_GROUP=process_start \
ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=startup_direct \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia --plan
```

#### `listener_probe`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_ATTACH_GROUP=listener_probe \
ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=startup_direct \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia --plan
```

#### `attach_merge`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_ATTACH_GROUP=attach_merge \
ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=startup_direct \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia --plan
```

### Validation rule

Trust a rerun only if the event log shows:

- `startup.debug_service_group=launch_attach`
- `startup.debug_attach_group=<requested subgroup>`
- `startup.debug_preselector_group=startup_direct`
- `startup.debug_selector_group=standalone_child`

## 2026-03-08: Assessment after launch-attach subgroup and TTY-common runs

Latest trustworthy manual result inside the valid service-side context:
- `services -> launch_attach -> process_start`: good in the degraded-input sense, but `t` returned `No test target selected.` and the dashboard showed `services: 0 total`
  - session: `session-20260308132951-85637-deda`
- `services -> launch_attach -> listener_probe`: bad
  - session: `session-20260308133058-86355-c076`
- `services -> launch_attach -> attach_merge`: good in the degraded-input sense, but `t` returned `No test target selected.`
  - session: `session-20260308133142-87605-ac61`

Additional exploratory runs layered `ENVCTL_DEBUG_PLAN_TTY_COMMON_GROUP=dashboard|preflight|subprocess` on top of the bad `launch_attach` family. Those runs remained bad / selector-unusable, but they do **not** currently overturn the stronger `listener_probe` narrowing, because they still wrap the same already-bad attach family and have not yet been shown to be independent enough.

### Current assessment

We are mostly looking in the right area, but only one part of the current direction is strongly trustworthy:
- the bug family is in `services`
- inside that, the best trustworthy culprit seam is still `launch_attach`
- inside that, the best trustworthy narrowing is still `listener_probe`

The `TTY_COMMON_GROUP` overlays are currently weaker evidence than the `launch_attach` subgroup split. They may be useful later, but they should not displace the stronger conclusion above.

### Important caveat

There are now clearly two observable failure shapes in some debug modes:
1. degraded dashboard/menu input
2. selector not really opening and returning `No test target selected.` without degraded typing

Those should not be flattened into a single identical outcome when deciding the next split.

### Recommended next focus

Do not keep broadening back out into generic tty/common overlays.
The next trustworthy recursion should stay inside:
- `services`
- `launch_attach`
- `listener_probe`

And split that by real code boundaries, ideally:
1. listener wait / listener PID detection
2. actual-port / rebound detection
3. post-probe attach result shaping

But only after verifying that those subgroup routes are genuinely wired and leave explicit execution markers in the event log.

## 2026-03-08: Attach-group reruns under the earliest constant child-selector tail

The next attach-group reruns were executed with:

- `ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=startup_direct`
- `startup.debug_selector_group=standalone_child`

### `process_start`

Session:
- `session-20260308143123-44364-3c98`

Validation markers:
- `startup.debug_service_group=launch_attach`
- `startup.debug_attach_group=process_start`
- `startup.debug_preselector_group=startup_direct`
- `startup.debug_selector_group=standalone_child`

Observed shape:
- the grouped selector opened immediately and returned with `No test target selected.`
- `ui.plan_handoff.snapshot` at `before_dashboard_entry` showed:
  - `service_count=0`
  - `requirement_count=0`

Interpretation:
- correctly routed
- not behaviorally comparable to the real failing path because the state collapsed before the checkpoint

### `listener_probe`

Session:
- `session-20260308143157-45011-569e`

Validation markers:
- `startup.debug_service_group=launch_attach`
- `startup.debug_attach_group=listener_probe`
- `startup.debug_preselector_group=startup_direct`
- `startup.debug_selector_group=standalone_child`

Observed shape:
- bad in the same degraded-input sense as the real failing path
- `ui.plan_handoff.snapshot` at `before_dashboard_entry` showed:
  - `service_count=8`
  - `requirement_count=4`

Interpretation:
- this is the only trustworthy bad attach-group rerun in this latest batch

### `attach_merge`

Session:
- `session-20260308143230-46128-96f2`

Validation markers:
- `startup.debug_service_group=launch_attach`
- `startup.debug_attach_group=attach_merge`
- `startup.debug_preselector_group=startup_direct`
- `startup.debug_selector_group=standalone_child`

Observed shape:
- the grouped selector opened immediately and returned with `No test target selected.`
- `ui.plan_handoff.snapshot` at `before_dashboard_entry` showed:
  - `service_count=0`
  - `requirement_count=0`

Interpretation:
- correctly routed
- not behaviorally comparable to the real failing path because the state collapsed before the checkpoint

## 2026-03-08: Correct reading of those reruns

Do not summarize the latest attach-group reruns as:

- `process_start`: good
- `listener_probe`: bad
- `attach_merge`: good

That would overstate the evidence.

The stronger honest reading is:

- `listener_probe` remains the only trustworthy bad attach subgroup under the earliest constant child-selector tail
- `process_start` and `attach_merge` were routed correctly, but in these reruns they reduced the state to `service_count=0` / `requirement_count=0`, so they are not comparable behavioral controls

Practically, the next recursion should stay inside:

- `services`
- `launch_attach`
- `listener_probe`

and keep the same constant earliest tail:

- `ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=startup_direct`
- `startup.debug_selector_group=standalone_child`

## 2026-03-08: Next 3 trustworthy manual commands

### `pid_wait`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_ATTACH_GROUP=listener_probe \
ENVCTL_DEBUG_PLAN_LISTENER_GROUP=pid_wait \
ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=startup_direct \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia --plan
```

### `port_fallback`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_ATTACH_GROUP=listener_probe \
ENVCTL_DEBUG_PLAN_LISTENER_GROUP=port_fallback \
ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=startup_direct \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia --plan
```

### `rebound_discovery`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_ATTACH_GROUP=listener_probe \
ENVCTL_DEBUG_PLAN_LISTENER_GROUP=rebound_discovery \
ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=startup_direct \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia --plan
```

### Trust rule

Treat a run as trustworthy only if its event log shows:

- `startup.debug_service_group=launch_attach`
- `startup.debug_attach_group=listener_probe`
- `startup.debug_listener_group=<requested subgroup>`
- `startup.debug_preselector_group=startup_direct`
- `startup.debug_selector_group=standalone_child`

Also record the checkpoint state at `before_dashboard_entry`:

- `service_count`
- `requirement_count`

If a subgroup again collapses to `service_count=0`, do not treat that as a clean “good” result. It is routed, but not behaviorally comparable to the real failing path.

## 2026-03-08: Listener-group reruns under `listener_probe` with the earliest constant tail

The next three reruns were all correctly routed under:

- `ENVCTL_DEBUG_PLAN_EXEC_GROUP=services`
- `ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach`
- `ENVCTL_DEBUG_PLAN_ATTACH_GROUP=listener_probe`
- `ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=startup_direct`
- `startup.debug_selector_group=standalone_child`

### `pid_wait`

Session:
- `session-20260308143645-48168-242b`

Validation markers:
- `startup.debug_service_group=launch_attach`
- `startup.debug_attach_group=listener_probe`
- `startup.debug_listener_group=pid_wait`
- `startup.debug_preselector_group=startup_direct`
- `startup.debug_selector_group=standalone_child`

Checkpoint state:
- `service_count=8`
- `requirement_count=4`

Observed shape:
- still bad in the same preserved-state sense as the real failing path

Interpretation:
- this is the only trustworthy bad listener subgroup from this batch

### `port_fallback`

Session:
- `session-20260308143708-49333-1761`

Validation markers:
- `startup.debug_service_group=launch_attach`
- `startup.debug_attach_group=listener_probe`
- `startup.debug_listener_group=port_fallback`
- `startup.debug_listener_group.synthetic_actual`
- `startup.debug_preselector_group=startup_direct`
- `startup.debug_selector_group=standalone_child`

Checkpoint state:
- `service_count=0`
- `requirement_count=0`

Interpretation:
- routed correctly
- not behaviorally comparable, because the service state collapsed before the checkpoint

### `rebound_discovery`

Session:
- `session-20260308143719-49661-9d6c`

Validation markers:
- `startup.debug_service_group=launch_attach`
- `startup.debug_attach_group=listener_probe`
- `startup.debug_listener_group=rebound_discovery`
- `startup.debug_listener_group.synthetic_actual`
- `startup.debug_preselector_group=startup_direct`
- `startup.debug_selector_group=standalone_child`

Checkpoint state:
- `service_count=0`
- `requirement_count=0`

Interpretation:
- routed correctly
- not behaviorally comparable, because the service state collapsed before the checkpoint

## 2026-03-08: Strongest current trustworthy narrowing

The strongest current preserved-state chain is now:

- `services`
- `launch_attach`
- `listener_probe`
- `pid_wait`

Do not flatten this latest listener split into:

- `pid_wait`: bad
- `port_fallback`: good
- `rebound_discovery`: good

The honest reading is:

- `pid_wait` is the only trustworthy bad subgroup
- `port_fallback` and `rebound_discovery` are routed, but they collapse to synthetic zero-state and therefore are not comparable controls for the bug

## 2026-03-08: Next 3 trustworthy manual commands

### `signal_gate`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_ATTACH_GROUP=listener_probe \
ENVCTL_DEBUG_PLAN_LISTENER_GROUP=pid_wait \
ENVCTL_DEBUG_PLAN_PID_WAIT_GROUP=signal_gate \
ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=startup_direct \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia --plan
```

### `pid_port_lsof`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_ATTACH_GROUP=listener_probe \
ENVCTL_DEBUG_PLAN_LISTENER_GROUP=pid_wait \
ENVCTL_DEBUG_PLAN_PID_WAIT_GROUP=pid_port_lsof \
ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=startup_direct \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia --plan
```

### `tree_port_scan`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_ATTACH_GROUP=listener_probe \
ENVCTL_DEBUG_PLAN_LISTENER_GROUP=pid_wait \
ENVCTL_DEBUG_PLAN_PID_WAIT_GROUP=tree_port_scan \
ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=startup_direct \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia --plan
```

### Trust rule

Treat a run as trustworthy only if its event log shows:

- `startup.debug_service_group=launch_attach`
- `startup.debug_attach_group=listener_probe`
- `startup.debug_listener_group=pid_wait`
- `startup.debug_pid_wait_group=<requested subgroup>`
- `startup.debug_preselector_group=startup_direct`
- `startup.debug_selector_group=standalone_child`

Also record the checkpoint state at `before_dashboard_entry`:

- `service_count`
- `requirement_count`

If a pid-wait subgroup again collapses to `service_count=0`, do not classify it as a clean “good” branch.

## 2026-03-08: `pid_wait` leaf split reruns were all preserved-state bad

Three `pid_wait` leaf reruns were completed under the preserved-state harness:

- `signal_gate`
  - session: `session-20260308143940-52323-f1de`
- `pid_port_lsof`
  - session: `session-20260308144132-53471-533f`
- `tree_port_scan`
  - session: `session-20260308160640-87299-679b`

All three were valid:

- `startup.debug_service_group=launch_attach`
- `startup.debug_attach_group=listener_probe`
- `startup.debug_listener_group=pid_wait`
- `startup.debug_pid_wait_group=<requested subgroup>`
- `startup.debug_preselector_group=startup_direct`
- `startup.debug_selector_group=standalone_child`

All three preserved the real checkpoint state:

- `service_count=8`
- `requirement_count=4`

Observed result:

- all three remained bad / selector-unusable in the same preserved-state family

Important nuance:

- `signal_gate` and `pid_port_lsof` also emitted `startup.debug_listener_group.synthetic_actual`
- `tree_port_scan` preserved state without needing that fallback marker

## 2026-03-08: Interpretation of the all-bad `pid_wait` leaves

This is now a genuinely non-discriminative split.

Do not conclude that one of:

- `signal_gate`
- `pid_port_lsof`
- `tree_port_scan`

is the unique culprit.

The stronger conclusion is:

- the contaminating work is in the shared `pid_wait` path before those three branches diverge
- the previous leaf split was too late

That shared code lives in `wait_for_pid_port(...)` in [process_runner.py](/Users/kfiramar/projects/envctl/python/envctl_engine/shared/process_runner.py#L365):

- common validation / group normalization
- common polling loop / timeout cadence
- then the leaf checks:
  - `is_pid_running(...)`
  - `pid_owns_port(...)`
  - `find_pid_listener_port(...)`

## 2026-03-08: New earlier split inside preserved-state `pid_wait`

The next honest seam is by service boundary inside the actual detection path:

1. backend pid-wait only
2. frontend pid-wait only
3. both backend and frontend pid-wait

This is a real code-boundary split in [startup_execution_support.py](/Users/kfiramar/projects/envctl/python/envctl_engine/startup/startup_execution_support.py#L876) and [startup_execution_support.py](/Users/kfiramar/projects/envctl/python/envctl_engine/startup/startup_execution_support.py#L944), not an imaginary label.

### Wiring added

New env:

- `ENVCTL_DEBUG_PLAN_PID_WAIT_SERVICE=backend|frontend|both`

Routing / validation markers:

- parse in [startup_orchestrator.py](/Users/kfiramar/projects/envctl/python/envctl_engine/startup/startup_orchestrator.py#L301)
- propagate in [startup_orchestrator.py](/Users/kfiramar/projects/envctl/python/envctl_engine/startup/startup_orchestrator.py#L1419)
- emit in [startup_execution_support.py](/Users/kfiramar/projects/envctl/python/envctl_engine/startup/startup_execution_support.py#L662)

Non-selected service detection is synthesized with:

- `startup.debug_pid_wait_service.synthetic_actual`

Compile check passed after the wiring change.

## 2026-03-08: Next 3 manual commands

### `backend`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_ATTACH_GROUP=listener_probe \
ENVCTL_DEBUG_PLAN_LISTENER_GROUP=pid_wait \
ENVCTL_DEBUG_PLAN_PID_WAIT_SERVICE=backend \
ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=startup_direct \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia --plan
```

### `frontend`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_ATTACH_GROUP=listener_probe \
ENVCTL_DEBUG_PLAN_LISTENER_GROUP=pid_wait \
ENVCTL_DEBUG_PLAN_PID_WAIT_SERVICE=frontend \
ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=startup_direct \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia --plan
```

### `both`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_ATTACH_GROUP=listener_probe \
ENVCTL_DEBUG_PLAN_LISTENER_GROUP=pid_wait \
ENVCTL_DEBUG_PLAN_PID_WAIT_SERVICE=both \
ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=startup_direct \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia --plan
```

### Trust rule

Trust a run only if the event log shows:

- `startup.debug_service_group=launch_attach`
- `startup.debug_attach_group=listener_probe`
- `startup.debug_listener_group=pid_wait`
- `startup.debug_pid_wait_service=<requested group>`
- `startup.debug_preselector_group=startup_direct`
- `startup.debug_selector_group=standalone_child`

If `startup.debug_pid_wait_service.synthetic_actual` appears, note it, but the run is still valid. Also record:

- `service_count`
- `requirement_count`

## 2026-03-08: `pid_wait_service` reruns

Three service-boundary reruns were completed:

- `backend`
  - session: `session-20260308161043-91827-8308`
- `frontend`
  - session: `session-20260308161107-92624-2306`
- `both`
  - session: `session-20260308161139-93349-cac3`

### `backend`

Validation:

- `startup.debug_service_group=launch_attach`
- `startup.debug_attach_group=listener_probe`
- `startup.debug_listener_group=pid_wait`
- `startup.debug_pid_wait_service=backend`
- `startup.debug_preselector_group=startup_direct`
- `startup.debug_selector_group=standalone_child`

Checkpoint state:

- `service_count=8`
- `requirement_count=4`

Observed result:

- bad in the preserved-state sense
- `startup.debug_pid_wait_service.synthetic_actual` appeared for `frontend`, which is expected because this split only keeps real pid-wait on `backend`

### `frontend`

Validation:

- `startup.debug_service_group=launch_attach`
- `startup.debug_attach_group=listener_probe`
- `startup.debug_listener_group=pid_wait`
- `startup.debug_pid_wait_service=frontend`
- `startup.debug_preselector_group=startup_direct`
- `startup.debug_selector_group=standalone_child`

Checkpoint state:

- `service_count=0`
- `requirement_count=0`

Observed result:

- immediate selector exit / `No test target selected.`
- not behaviorally comparable to the real failing path

### `both`

Validation:

- `startup.debug_service_group=launch_attach`
- `startup.debug_attach_group=listener_probe`
- `startup.debug_listener_group=pid_wait`
- `startup.debug_pid_wait_service=both`
- `startup.debug_preselector_group=startup_direct`
- `startup.debug_selector_group=standalone_child`

Checkpoint state:

- `service_count=8`
- `requirement_count=4`

Observed result:

- bad in the preserved-state sense

## 2026-03-08: Strongest current trustworthy reading

Do not summarize the `pid_wait_service` split as:

- `backend`: bad
- `frontend`: good
- `both`: bad

That would overstate the evidence.

The stronger honest reading is:

- `backend` is a trustworthy preserved-state bad branch
- `both` is a trustworthy preserved-state bad branch
- `frontend` is routed, but non-comparable because it collapses to zero-state before the checkpoint

So the best current preserved-state culprit family is:

- `services`
- `launch_attach`
- `listener_probe`
- `pid_wait`
- `backend`

## 2026-03-08: Next 3 manual commands

No new wiring is needed for the next step. Reuse the existing `pid_wait_group` split, but pin it to the preserved-state bad `backend` service branch:

### `backend + signal_gate`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_ATTACH_GROUP=listener_probe \
ENVCTL_DEBUG_PLAN_LISTENER_GROUP=pid_wait \
ENVCTL_DEBUG_PLAN_PID_WAIT_SERVICE=backend \
ENVCTL_DEBUG_PLAN_PID_WAIT_GROUP=signal_gate \
ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=startup_direct \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia --plan
```

### `backend + pid_port_lsof`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_ATTACH_GROUP=listener_probe \
ENVCTL_DEBUG_PLAN_LISTENER_GROUP=pid_wait \
ENVCTL_DEBUG_PLAN_PID_WAIT_SERVICE=backend \
ENVCTL_DEBUG_PLAN_PID_WAIT_GROUP=pid_port_lsof \
ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=startup_direct \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia --plan
```

### `backend + tree_port_scan`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_ATTACH_GROUP=listener_probe \
ENVCTL_DEBUG_PLAN_LISTENER_GROUP=pid_wait \
ENVCTL_DEBUG_PLAN_PID_WAIT_SERVICE=backend \
ENVCTL_DEBUG_PLAN_PID_WAIT_GROUP=tree_port_scan \
ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=startup_direct \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia --plan
```

### Trust rule

Trust a run only if the log shows:

- `startup.debug_service_group=launch_attach`
- `startup.debug_attach_group=listener_probe`
- `startup.debug_listener_group=pid_wait`
- `startup.debug_pid_wait_service=backend`
- `startup.debug_pid_wait_group=<requested subgroup>`
- `startup.debug_preselector_group=startup_direct`
- `startup.debug_selector_group=standalone_child`

Also record:

- `service_count`
- `requirement_count`

If the run still preserves `service_count=8`, it is comparable. If it collapses, treat it as routed but non-comparable.

## Update: backend-pinned pid_wait leaves fully reconverged

The three backend-pinned reruns were all preserved-state bad:

- `signal_gate`: `session-20260308161434-96237-ab8e`
- `pid_port_lsof`: `session-20260308161538-97030-9080`
- `tree_port_scan`: `session-20260308161608-97797-54c1`

All three emitted:

- `startup.debug_service_group=launch_attach`
- `startup.debug_attach_group=listener_probe`
- `startup.debug_listener_group=pid_wait`
- `startup.debug_pid_wait_service=backend`
- `startup.debug_pid_wait_group=<requested subgroup>`
- `startup.debug_preselector_group=startup_direct`
- `startup.debug_selector_group=standalone_child`

All three also reached `before_dashboard_entry` with:

- `service_count=8`
- `requirement_count=4`

So this is a real reconvergence, not another invalid harness result. The culprit is earlier in the shared backend actual-detection path, before the `signal_gate|pid_port_lsof|tree_port_scan` leaf branches separate.

## New split: backend actual-detection wrapper

New env:

- `ENVCTL_DEBUG_PLAN_BACKEND_ACTUAL_GROUP=request_setup|detect_call|resolve_actual`

Meaning:

- `request_setup`
  - real `service.bind.requested`
  - timer/setup and backend actual-detection wrapper entry
  - synthetic actual assignment after setup
- `detect_call`
  - real call to `rt._detect_service_actual_port(...)`
  - synthetic actual only if that call returns `None`
- `resolve_actual`
  - synthetic detected value fed through the real post-call resolution tail
  - real `service.bind.actual` and `service.attach.phase`

This split is only routed when all of these are true:

- `ENVCTL_DEBUG_PLAN_EXEC_GROUP=services`
- `ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach`
- `ENVCTL_DEBUG_PLAN_ATTACH_GROUP=listener_probe`
- `ENVCTL_DEBUG_PLAN_LISTENER_GROUP=pid_wait`
- `ENVCTL_DEBUG_PLAN_PID_WAIT_SERVICE=backend`

### `request_setup`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_ATTACH_GROUP=listener_probe \
ENVCTL_DEBUG_PLAN_LISTENER_GROUP=pid_wait \
ENVCTL_DEBUG_PLAN_PID_WAIT_SERVICE=backend \
ENVCTL_DEBUG_PLAN_BACKEND_ACTUAL_GROUP=request_setup \
ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=startup_direct \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia --plan
```

### `detect_call`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_ATTACH_GROUP=listener_probe \
ENVCTL_DEBUG_PLAN_LISTENER_GROUP=pid_wait \
ENVCTL_DEBUG_PLAN_PID_WAIT_SERVICE=backend \
ENVCTL_DEBUG_PLAN_BACKEND_ACTUAL_GROUP=detect_call \
ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=startup_direct \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia --plan
```

### `resolve_actual`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_ATTACH_GROUP=listener_probe \
ENVCTL_DEBUG_PLAN_LISTENER_GROUP=pid_wait \
ENVCTL_DEBUG_PLAN_PID_WAIT_SERVICE=backend \
ENVCTL_DEBUG_PLAN_BACKEND_ACTUAL_GROUP=resolve_actual \
ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=startup_direct \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia --plan
```

### Trust rule

Trust a run only if the log shows:

- `startup.debug_service_group=launch_attach`
- `startup.debug_attach_group=listener_probe`
- `startup.debug_listener_group=pid_wait`
- `startup.debug_pid_wait_service=backend`
- `startup.debug_backend_actual_group=<requested subgroup>`
- `startup.debug_preselector_group=startup_direct`
- `startup.debug_selector_group=standalone_child`

Also record:

- `service_count`
- `requirement_count`

If `startup.debug_backend_actual_group.synthetic_actual` or `startup.debug_backend_actual_group.synthetic_detected` appears, the run is still valid; it just means the non-selected parts of the backend actual-detection wrapper were intentionally synthesized.

## Correction: backend_actual wrapper split was only partially trustworthy

The three backend-actual reruns did **not** produce a clean `1 bad / 2 good` result.

- `request_setup`: routed, but non-comparable
  - `session-20260308162200-6621-4710`
  - emitted `startup.debug_backend_actual_group=request_setup`
  - then failed in the shared post-start truth tail with:
    - `service.truth.check` `status=starting`
    - `service.failure` `failure_class=post_start_truth_check`
    - `startup.project.failed`
- `detect_call`: the only preserved-state bad branch
  - `session-20260308162225-7121-2de4`
  - emitted `startup.debug_backend_actual_group=detect_call`
  - reached full real backend detection and preserved running truth for backend/frontend services
- `resolve_actual`: routed, but non-comparable
  - `session-20260308162308-8200-3295`
  - emitted `startup.debug_backend_actual_group=resolve_actual`
  - then failed in the same shared post-start truth tail as `request_setup`

So the wrapper split only confirmed that the real bad path is still the actual backend detect call. The synthetic sibling branches collapse earlier and should not be treated as “good”.

## Current strongest technical suspect

After that correction, the strongest preserved-state culprit remains the shared backend detect path:

- `services`
- `launch_attach`
- `listener_probe`
- `pid_wait`
- `backend`
- real `detect_call`

And inside that path, the earlier `signal_gate|pid_port_lsof|tree_port_scan` leaf split was fully reconvergent and preserved-state bad. That leaves the shared probe machinery itself as the best current suspect, not one of the late pid-wait leaf branches.

## Targeted validation patch

A focused code change was applied in [process_runner.py](/Users/kfiramar/projects/envctl/python/envctl_engine/shared/process_runner.py) so the shared probe subprocesses (`ps`/`lsof`) no longer inherit terminal stdin:

- all narrowed probe-side `subprocess.run(...)` calls now pass `stdin=subprocess.DEVNULL`

This is the smallest shared change across the still-bad preserved-state path.

### Single validation command

Use the real bad path, not another synthetic branch:

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia --plan
```

Interpretation:

- if the dashboard and `t` path are now healthy in the same bad Apple Terminal tab, the shared probe subprocess stdin inheritance was the practical culprit
- if the bug remains, the next most likely shared terminal-attached path is service process stdin inheritance rather than the probe subprocesses

## Result: probe-subprocess stdin detach did not fix the real bad path

Real-path validation run:

- `session-20260308162650-14605-f956`

Outcome:

- startup completed normally
- dashboard still reproduced the same bad behavior after `t`

So the shared probe helper subprocesses were **not** the practical culprit.

## New targeted validation patch

The remaining shared terminal-attached path is the long-lived service child processes themselves.

In [process_runner.py](/Users/kfiramar/projects/envctl/python/envctl_engine/shared/process_runner.py), `ProcessRunner.start(...)` now launches background service processes with:

- `stdin=subprocess.DEVNULL`

This specifically detaches backend/frontend service children from the terminal stdin they were previously inheriting.

### Next single validation command

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
/Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia --plan
```

Interpretation:

- if the dashboard and `t` path are now healthy in the same bad reused tab, inherited stdin on launched service processes was the culprit
- if the bug remains, the surviving suspect family is no longer generic listener probes; it is another shared post-plan terminal-attached path in the real service launch/interactive handoff

## Result: service child stdin detach fixed the bug

Real-path validation run:

- `session-20260308162858-20968-c7ee`

User result:

- same previously bad reused Apple Terminal tab
- dashboard interaction reported healthy
- post-plan behavior no longer showed the unreliable input bug

Strong conclusion:

- the practical culprit was launched service child processes inheriting terminal stdin during the normal post-plan path
- setting `stdin=subprocess.DEVNULL` in `ProcessRunner.start(...)` fixed the real bug in the real bad path

Important note:

- the pasted final line `No test target selected.` does **not** by itself invalidate the fix result
- that line can still occur in a healthy run if the selector is opened and then exited without a chosen target
- the user’s direct observation that the dashboard/menu flow now works normally is the deciding evidence here

## Concrete fix

File:

- [process_runner.py](/Users/kfiramar/projects/envctl/python/envctl_engine/shared/process_runner.py)

Change:

- long-lived background service launches now use `stdin=subprocess.DEVNULL`

This matches the final narrowing:

- planning selector healthy
- standalone Textual healthy
- synthetic dashboard tails healthy
- real bug isolated to `services -> launch_attach`
- probe helper subprocess stdin detach did **not** fix it
- service child stdin detach **did** fix it

## Practical closeout

If no contradictory rerun appears, treat this as the resolved root cause and keep the `stdin=subprocess.DEVNULL` launch behavior.
