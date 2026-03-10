# Post-Plan Dashboard Input Bug: Full Handoff

> Historical investigation archive.
> The `ENVCTL_DEBUG_PLAN_*` split-matrix commands documented here are no longer a supported debug surface and may no longer work.
> For current debugging, use snapshots, doctor/debug bundles, `--debug-report`, and the permanent write-up in [service-launch-io-ownership.md](service-launch-io-ownership.md).

## Problem Statement
There is a post-`--plan` interactive input bug in `envctl`.

Observed user-facing behavior:
- The planning selector itself works correctly, even in a "bad" reused Apple Terminal tab.
- After the planning selector exits and envctl enters the post-plan interactive mode, the dashboard and especially the `t` test-target menu become unreliable in some reused Apple Terminal tabs.
- Symptoms include:
  - arrow keys not registering reliably in the selector
  - `Enter` / `Esc` behaving inconsistently
  - in some bad runs, typing in the main dashboard itself also feels degraded
  - `t` sometimes leads to `No test target selected.`
- Fresh tabs often behave correctly.
- The issue reproduces in some reused Apple Terminal tabs.

The working assumption is that the bug is introduced somewhere in the **real post-plan path** after the planning selector exits.

---

## Environment
Repo:
- `<envctl checkout>`

Target repo used for reproduction:
- `/path/to/your/repo`

Terminal / shell:
- Apple Terminal on macOS
- Reproduces even in `/bin/zsh -df`

This means normal shell startup files are **not necessary** for the bug.

---

## Strongest Current Proven Conclusion
The first broad trustworthy isolation that actually narrowed the bug was:

Under:
- `ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize`
- `ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard`

and varying only:
- `ENVCTL_DEBUG_PLAN_EXEC_GROUP`

results were:
- `requirements`: good
- `services`: bad
- `completion`: good

Then inside `services`, varying only:
- `ENVCTL_DEBUG_PLAN_SERVICE_GROUP`

results were:
- `bootstrap`: good
- `launch_attach`: bad
- `record_merge`: good

So the **current best trustworthy culprit family** is:

> the real service launch / attach path

not:
- requirements-side execution
- service bootstrap/runtime-prep alone
- service record merge alone

The next trustworthy split should stay entirely inside `launch_attach`.

---

## Important Constraints / Things Already Proven

### Proven good
These are reliable and should be treated as real evidence.

#### Planning selector
- The planning selector itself is healthy.
- It works even in the bad tab.

#### Known-good baseline
This command is the main known-good control:

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_SKIP_PLAN_STARTUP=1 \
ENVCTL_DEBUG_MINIMAL_DASHBOARD=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
./bin/envctl --repo /path/to/your/repo --plan
```

This is good.

Meaning:
- planning/worktree sync is fine
- planning selector exit is fine
- synthetic post-plan minimal dashboard path is fine

#### Standalone probes
These are healthy:
- standalone Textual selector
- standalone prompt-toolkit selector/menu
- standalone `TerminalSession.read_command_line(...) -> selector` probes

#### Preentry phases in isolation
With the corrected direct-selector debug path (must show `DEBUG DIRECT SELECTOR MODE (no dashboard). Do not press t.`):
- `branch_setup`: good
- `project_loop`: good
- `finalize`: good

#### Preentry pairwise combinations
Also good (after combo parsing was fixed):
- `branch_setup,project_loop`
- `branch_setup,finalize`
- `project_loop,finalize`

#### Full preentry + postpreentry variants
Good:
- full preentry + direct selector
- full preentry + minimal dashboard
- full preentry + full dashboard

#### Broad execution split under full good context
With:
- `ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize`
- `ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard`

Good:
- `ENVCTL_DEBUG_PLAN_EXEC_GROUP=requirements`
- `ENVCTL_DEBUG_PLAN_EXEC_GROUP=completion`

Bad:
- `ENVCTL_DEBUG_PLAN_EXEC_GROUP=services`

#### Services subgroup split under full good context
Good:
- `ENVCTL_DEBUG_PLAN_SERVICE_GROUP=bootstrap`
- `ENVCTL_DEBUG_PLAN_SERVICE_GROUP=record_merge`

Bad:
- `ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach`

This is the current highest-value narrowing.

---

## Proven not-primary / ruled out
These are not the main culprit, or at least not sufficient causes on their own.

### Shell config
- Reproduces in `/bin/zsh -df`
- So `~/.zshrc`, `~/.zprofile`, `~/.zshenv`, Kiro shell integration, etc. are **not necessary**.
- They may still be incidental noise, but they are not the core cause.

### Generic terminal mode folklore
The following were investigated and are not sufficient explanations by themselves:
- generic `stty` / termios folklore
- generic `O_NONBLOCK` theory
- stray envctl process stealing input after shell prompt

### Planning selector itself
- not the culprit

### Minimal dashboard alone
- not the culprit

### Normal dashboard alone
- not sufficient by itself

### Requirements-side execution
- good in the valid broad execution split

### Completion/merge-side execution
- good in the valid broad execution split

### Service bootstrap/runtime-prep alone
- good in the valid services split

### Service record merge alone
- good in the valid services split

---

## Why Some Older Results Must Be Ignored
A large amount of time was spent on splits that were later found to be invalid because the debug routing was not actually isolating what it claimed to isolate.

These invalidity patterns happened repeatedly:
- auto-resume intercepted a debug path and dropped back into the normal dashboard path
- debug subgroup env vars were parsed, but not actually propagated into `route_for_execution`
- combo parsing for comma-separated groups was broken
- direct preentry modes still fell through to the dashboard command loop
- subgroup override points were applied too late, after common side effects had already happened

The investigation doc already contains corrections appended in-place. Any new solver should treat only the **corrected / re-run / revalidated** results as evidence.

If a run does not exhibit the intended debug-mode marker or control shape, it should be considered invalid.

---

## Key Debug Modes / Flags That Are Actually Useful Now

### Good baseline
```bash
ENVCTL_DEBUG_SKIP_PLAN_STARTUP=1 \
ENVCTL_DEBUG_MINIMAL_DASHBOARD=1
```

### Full preentry + full dashboard context
```bash
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard
```

### Broad execution split
```bash
ENVCTL_DEBUG_PLAN_EXEC_GROUP=requirements|services|completion
```

### Services split
```bash
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=bootstrap|launch_attach|record_merge
```

### Attach split (wired now and should be the next focus)
```bash
ENVCTL_DEBUG_PLAN_ATTACH_GROUP=process_start|listener_probe|attach_merge
```

Common diagnostics used in almost all runs:
```bash
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0
```

---

## 2026-03-08 Attach Routing Verification

`ENVCTL_DEBUG_PLAN_ATTACH_GROUP` is wired through the current real `launch_attach` path.

Code verification:

- `python/envctl_engine/startup/startup_orchestrator.py`
  - parses `ENVCTL_DEBUG_PLAN_ATTACH_GROUP` for `plan`
  - copies it into the real `route_for_execution.flags["_debug_attach_group"]`
  - this happens in the normal startup path, not only in the synthetic debug loop builder
- `python/envctl_engine/startup/startup_execution_support.py`
  - `start_project_services(...)` reads `route.flags["_debug_attach_group"]`
  - it emits `startup.debug_attach_group`
  - it branches early inside `run_launch_attach`:
    - `process_start`
    - `listener_probe`
    - `attach_merge`
  - those branches return before the default full attach path

Log verification:

- A real runtime event log already shows this routing working for `listener_probe`:
  - `/tmp/envctl-runtime/python-engine/repo-b15e3f0c8257/events.jsonl`
- In that file, the run contains:
  - `startup.debug_service_group` with `group=launch_attach`
  - `startup.debug_attach_group` with `group=listener_probe`
  - `service.attach.phase` with:
    - `phase=command_resolution`
    - `phase=process_launch`
    - `phase=actual_port_detection`
- This is sufficient evidence that the current live path is not silently falling back to the unsplit attach tail for that subgroup.

Acceptance rule for the next attach runs:

- Trust a run only if its event log shows:
  - `startup.debug_service_group` with `group=launch_attach`
  - `startup.debug_attach_group` with the requested subgroup
- Then validate the subgroup-specific shape:
  - `process_start`
    - should show `service.attach.phase` for `command_resolution` and `process_launch`
    - should not require `actual_port_detection`
    - should not rely on `service.attach.execution`
  - `listener_probe`
    - should show `service.attach.phase` for `command_resolution`, `process_launch`, and `actual_port_detection`
  - `attach_merge`
    - should show `startup.debug_attach_group` with `group=attach_merge`
    - should not show `service.attach.execution`
    - should not show `service.attach.phase`

Smallest trustworthy next manual split:

- rerun only:
  - `process_start`
  - `listener_probe`
  - `attach_merge`
- keep:
  - `ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize`
  - `ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard`
  - `ENVCTL_DEBUG_PLAN_EXEC_GROUP=services`
  - `ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach`

---

## 2026-03-08 Attach Split Results

Three attach subgroup reruns were performed and validated against event logs.

### `process_start`

Session:
- `session-20260308162349-9670-f67a`

Trust status:
- routed correctly
- not comparable for selector-bug isolation

Why:
- runtime events show:
  - `startup.debug_service_group=launch_attach`
  - `startup.debug_attach_group=process_start`
- selector subprocess trace exists:
  - `/tmp/envctl-runtime/python-engine/repo-b15e3f0c8257/debug/session-20260308162349-9670-f67a/selector-subprocess-grouped.jsonl`
- but the selector trace shows:
  - `service_count=0`
  - `project_count=0`
  - `cancelled=true`

Interpretation:
- this run proves `process_start` routing works
- it does **not** preserve the real post-start dashboard state
- therefore it cannot be used to judge the real `t` selector bug

### `listener_probe`

Session:
- `session-20260308162509-11270-9951`

Trust status:
- routed correctly
- comparable
- bad

Why:
- runtime events show:
  - `startup.debug_service_group=launch_attach`
  - `startup.debug_attach_group=listener_probe`
  - `service.attach.phase=command_resolution`
  - `service.attach.phase=process_launch`
  - `service.attach.phase=actual_port_detection`
- dashboard state preserved real shape:
  - `services: 8 total | 8 running`
- user-observed symptom remained bad in this run

Interpretation:
- the remaining culprit family is now inside the real `listener_probe` / actual-port-detection path
- this rules out plain process launch as the primary cause

### `attach_merge`

Session:
- `session-20260308162556-12820-a745`

Trust status:
- routed correctly
- not comparable for selector-bug isolation

Why:
- runtime events show:
  - `startup.debug_service_group=launch_attach`
  - `startup.debug_attach_group=attach_merge`
- runtime events do **not** show:
  - `service.attach.execution`
  - `service.attach.phase`
- selector subprocess trace exists:
  - `/tmp/envctl-runtime/python-engine/repo-b15e3f0c8257/debug/session-20260308162556-12820-a745/selector-subprocess-grouped.jsonl`
- but the selector trace shows:
  - `service_count=0`
  - `project_count=0`
  - `cancelled=true`

Interpretation:
- this run proves `attach_merge` routing works
- it also does not preserve the real dashboard service state
- therefore it is not a valid selector-behavior comparison run

## Updated Strongest Trustworthy Conclusion

The broad attach split now narrows to:

- `process_start`: routed, non-comparable
- `attach_merge`: routed, non-comparable
- `listener_probe`: comparable, bad

So the remaining culprit family is:

> real listener probing / actual-port detection after service launch

not:

- command resolution
- process launch alone
- attach-group routing itself

## Smallest Trustworthy Next 3 Manual Commands

Stay inside the comparable bad branch only:

- `ENVCTL_DEBUG_PLAN_ATTACH_GROUP=listener_probe`
- vary only `ENVCTL_DEBUG_PLAN_LISTENER_GROUP`

Trust a run only if the event log shows:

- `startup.debug_service_group=launch_attach`
- `startup.debug_attach_group=listener_probe`
- `startup.debug_listener_group=<requested subgroup>`
- dashboard still preserves the real shape:
  - `services: 8 total | 8 running`

Next three commands:

1. `pid_wait`
2. `port_fallback`
3. `rebound_discovery`

---

## 2026-03-08 Resolution

Real-path validation run:

- `session-20260308162858-20968-c7ee`

User result in the same previously bad reused Apple Terminal tab:

- dashboard interaction healthy
- post-plan behavior no longer reproduced the unreliable input bug

Strong conclusion:

> the practical culprit was launched service child processes inheriting terminal stdin during the normal post-plan path

Confirmed fix in code:

- [process_runner.py](../../python/envctl_engine/shared/process_runner.py#L245)
  - `ProcessRunner.start(...)`
  - background service launches now use:
    - `stdin=subprocess.DEVNULL`

Important interpretation note:

- a final printed `No test target selected.` does **not** by itself invalidate this fix result
- that line can still occur in a healthy run if the selector is opened and then exited without choosing a target
- the deciding evidence is the user's direct report that the dashboard and post-plan selector flow are now healthy in the formerly bad reused tab

Final trustworthy chain:

- planning selector itself was healthy
- standalone selector probes were healthy
- synthetic skip-startup/dashboard tails were healthy
- real bad path narrowed to `services -> launch_attach`
- probe-helper subprocess stdin detachment did **not** fix the real path
- service child stdin detachment **did** fix the real path

Practical closeout:

- treat this as the resolved root cause unless a contradictory rerun appears
- keep `stdin=subprocess.DEVNULL` for long-lived service launches

---

## Valid Commands That Established the Current Culprit Family

### Broad execution split

#### Requirements good
```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=requirements \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
./bin/envctl --repo /path/to/your/repo --plan
```
- session: `session-20260308125714-58669-d722`
- result: good

#### Services bad
```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
./bin/envctl --repo /path/to/your/repo --plan
```
- session: `session-20260308125733-59097-4b25`
- result: bad

#### Completion good
```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=completion \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
./bin/envctl --repo /path/to/your/repo --plan
```
- session: `session-20260308125801-60248-7ee3`
- result: good

### Services subgroup split

#### Bootstrap good
```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=bootstrap \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
./bin/envctl --repo /path/to/your/repo --plan
```
- session: `session-20260308131342-70292-7cfc`
- result: good in the bug sense
- caveat: the menu did not open and `t` -> `No test target selected`, but dashboard typing itself was not degraded

#### Launch-attach bad
```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
./bin/envctl --repo /path/to/your/repo --plan
```
- session: `session-20260308131355-70727-fc1e`
- result: bad

#### Record-merge good
```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=record_merge \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
./bin/envctl --repo /path/to/your/repo --plan
```
- session: `session-20260308131418-71814-1a52`
- result: good in the bug sense
- caveat: selector did not really open, but the degraded typing symptom did not occur

---

## Current Best Hypothesis
The bug is introduced by the **real service launch / attach** path.

More specifically, the remaining likely culprit area is one of:
- process spawn / process ownership side effects
- listener / actual-port detection side effects
- attach-time thread / reader / event-loop interaction during live process startup

The most likely remaining broad suspect inside `launch_attach` is currently:

> listener/actual-port detection and attach probing

But this is not yet proven by a valid split.

---

## Why We Are Not Done Yet
There was an attempt to split `launch_attach` into:
- `process_start`
- `listener_probe`
- `attach_merge`

but the first user runs were from before that subgroup routing was actually trustworthy. Those old results must be ignored.

A new solver should either:
1. verify that `ENVCTL_DEBUG_PLAN_ATTACH_GROUP` is really taking effect in the current code path, then rerun those 3 commands, or
2. instrument explicit `startup.debug_attach_group` markers and inspect the session logs before trusting the results.

---

## Exact Next Debugging Step Recommended
### Goal
Get the first trustworthy split *inside* `launch_attach`.

### Recommended next commands to rerun only after confirming subgroup routing is real

#### process_start
```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_ATTACH_GROUP=process_start \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
./bin/envctl --repo /path/to/your/repo --plan
```

#### listener_probe
```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_ATTACH_GROUP=listener_probe \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
./bin/envctl --repo /path/to/your/repo --plan
```

#### attach_merge
```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_ATTACH_GROUP=attach_merge \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
./bin/envctl --repo /path/to/your/repo --plan
```

### Validation rule for those runs
Before trusting the result, inspect event logs for explicit attach subgroup markers and make sure the subgroup actually executed.

If exactly one of those is bad, recurse into that one only.

---

## Where The Most Relevant Code Lives
- startup orchestration:
  - `python/envctl_engine/startup/startup_orchestrator.py`
- startup execution / service launch path:
  - `python/envctl_engine/startup/startup_execution_support.py`
- service attach implementation:
  - `python/envctl_engine/runtime/service_manager.py`
- dashboard loop / command loop:
  - `python/envctl_engine/ui/command_loop.py`
  - `python/envctl_engine/ui/dashboard/orchestrator.py`
  - `python/envctl_engine/ui/backend.py`
- main investigation log:
  - `docs/incidents/post-plan-dashboard-input-investigation.md`

---

## Short Summary For A New Solver
If you only read one paragraph:

The bug is a post-`--plan` interactive input corruption in reused Apple Terminal tabs. Planning selector, synthetic skip-startup baseline, standalone selector probes, and the full preentry path are all good when isolated correctly. The first trustworthy broad execution split showed `requirements` good, `completion` good, and `services` bad. The first trustworthy services split then showed `bootstrap` good, `record_merge` good, and `launch_attach` bad. So the remaining culprit is in the real service launch / attach path. The next correct step is to verify and rerun the `process_start / listener_probe / attach_merge` split inside `launch_attach`, trusting only runs whose event logs prove the subgroup actually executed.

## 2026-03-08: Latest trustworthy narrowing inside `launch_attach`

With the trustworthy enclosing context:
- `ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize`
- `ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard`
- `ENVCTL_DEBUG_PLAN_EXEC_GROUP=services`
- `ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach`

The latest manual attach-subgroup results are:

### `process_start`
- session: `session-20260308132951-85637-deda`
- result: good in the bug sense
- caveat: dashboard typing was normal, but pressing `t` returned `No test target selected.` and the selector did not really open
- additional sign: dashboard showed `services: 0 total`, so the resulting state shape differed from the bad path

### `listener_probe`
- session: `session-20260308133058-86355-c076`
- result: bad
- this is the only current trustworthy bad subgroup inside `launch_attach`

### `attach_merge`
- session: `session-20260308133142-87605-ac61`
- result: good in the bug sense
- caveat: dashboard typing was normal, but pressing `t` returned `No test target selected.` and the selector did not really open

## Practical interpretation

This is the best current narrowing:
- `process_start`: not sufficient
- `attach_merge`: not sufficient
- `listener_probe`: still sufficient

So the strongest remaining suspect is now the **listener / actual-port detection / attach probing** path.

## Important caution for the next solver

Do not treat `process_start` and `attach_merge` as perfect “good mirrors” of the bad path.
They are only good with respect to the degraded input symptom.
They also altered the interactive outcome enough that:
- selector launch no longer behaved normally on `t`
- dashboard state shape differed materially from the bad path

That means the next split should recurse into `listener_probe`, not try to infer too much from the exact behavior of the other two subgroups.

## 2026-03-08: Code verification for attach-subgroup routing

Verified directly in code before requesting any further manual runs:

- `ENVCTL_DEBUG_PLAN_ATTACH_GROUP` is parsed for `--plan` in [startup_orchestrator.py](../../python/envctl_engine/startup/startup_orchestrator.py#L289).
- It is only forwarded into `route.flags["_debug_attach_group"]` when:
  - `ENVCTL_DEBUG_PLAN_EXEC_GROUP=services`
  - `ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach`
  - see [startup_orchestrator.py](../../python/envctl_engine/startup/startup_orchestrator.py#L1378).
- The service startup path re-validates that routed flag, emits `startup.debug_attach_group`, and records which one-of-three subgroup is active in [startup_execution_support.py](../../python/envctl_engine/startup/startup_execution_support.py#L597).
- The actual `launch_attach` body then dispatches into three distinct branches:
  - `process_start` in [startup_execution_support.py](../../python/envctl_engine/startup/startup_execution_support.py#L978)
  - `listener_probe` in [startup_execution_support.py](../../python/envctl_engine/startup/startup_execution_support.py#L1023)
  - `attach_merge` in [startup_execution_support.py](../../python/envctl_engine/startup/startup_execution_support.py#L1070)

Trust rule for future manual runs:

- do not trust a run unless its event log contains both:
  - `startup.debug_service_group` with `group=launch_attach`
  - `startup.debug_attach_group` with the requested subgroup name
- if either marker is missing, treat that run as invalid routing evidence

## 2026-03-08: Manual rerun verification for attach subgroups

Verified from event logs:

- `session-20260308134343-98321-cac6`
  - `startup.debug_service_group`: `launch_attach`
  - `startup.debug_attach_group`: `process_start`
- `session-20260308134447-99265-faa6`
  - `startup.debug_service_group`: `launch_attach`
  - `startup.debug_attach_group`: `listener_probe`
- `session-20260308134528-763-6aff`
  - `startup.debug_service_group`: `launch_attach`
  - `startup.debug_attach_group`: `attach_merge`

So the user-reported behavior for those three reruns is trustworthy evidence.

## 2026-03-08: Next honest split inside `listener_probe`

There was no finer listener-probe subgroup env before this step.

The smallest honest 3-way split that now exists is:

- `ENVCTL_DEBUG_PLAN_LISTENER_GROUP=pid_wait`
  - isolates `process_runner.wait_for_pid_port(...)`
  - code boundary: [engine_runtime_service_truth.py](../../python/envctl_engine/runtime/engine_runtime_service_truth.py#L69)
- `ENVCTL_DEBUG_PLAN_LISTENER_GROUP=port_fallback`
  - isolates `wait_for_port(...)` fallback recovery when enabled
  - same helper, later branch in [engine_runtime_service_truth.py](../../python/envctl_engine/runtime/engine_runtime_service_truth.py#L84)
- `ENVCTL_DEBUG_PLAN_LISTENER_GROUP=rebound_discovery`
  - isolates `find_pid_listener_port(...)` rebound / actual-port discovery
  - code boundary: [engine_runtime_service_truth.py](../../python/envctl_engine/runtime/engine_runtime_service_truth.py#L133)

Implementation notes:

- routing is parsed in [startup_orchestrator.py](../../python/envctl_engine/startup/startup_orchestrator.py#L293)
- it is forwarded only for:
  - `ENVCTL_DEBUG_PLAN_EXEC_GROUP=services`
  - `ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach`
  - `ENVCTL_DEBUG_PLAN_ATTACH_GROUP=listener_probe`
  - see [startup_orchestrator.py](../../python/envctl_engine/startup/startup_orchestrator.py#L1388)
- execution emits `startup.debug_listener_group` in [startup_execution_support.py](../../python/envctl_engine/startup/startup_execution_support.py#L626)
- restricted listener-group runs preserve dashboard entry by emitting `startup.debug_listener_group.synthetic_actual` if the narrowed subgroup alone does not detect a port

### Next 3 manual commands

#### `pid_wait`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_ATTACH_GROUP=listener_probe \
ENVCTL_DEBUG_PLAN_LISTENER_GROUP=pid_wait \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
./bin/envctl --repo /path/to/your/repo --plan
```

#### `port_fallback`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_ATTACH_GROUP=listener_probe \
ENVCTL_DEBUG_PLAN_LISTENER_GROUP=port_fallback \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
./bin/envctl --repo /path/to/your/repo --plan
```

#### `rebound_discovery`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_ATTACH_GROUP=listener_probe \
ENVCTL_DEBUG_PLAN_LISTENER_GROUP=rebound_discovery \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
./bin/envctl --repo /path/to/your/repo --plan
```

### Validation rule for those runs

Do not trust a run unless its event log shows all of:

- `startup.debug_service_group` with `group=launch_attach`
- `startup.debug_attach_group` with `group=listener_probe`
- `startup.debug_listener_group` with the requested subgroup

If `startup.debug_listener_group.synthetic_actual` appears, treat the run as valid but note that the subgroup alone did not fully resolve the actual port and the dashboard state may be slightly more synthetic than the fully bad path.

## 2026-03-08: Trustworthy `listener_probe` subgroup result

Verified from event logs:

- `session-20260308134939-2965-6005`
  - `startup.debug_service_group=launch_attach`
  - `startup.debug_attach_group=listener_probe`
  - `startup.debug_listener_group=pid_wait`
  - user result: bad
- `session-20260308135102-4588-8e0a`
  - `startup.debug_service_group=launch_attach`
  - `startup.debug_attach_group=listener_probe`
  - `startup.debug_listener_group=port_fallback`
  - `startup.debug_listener_group.synthetic_actual` emitted for backend and frontend
  - user result: dashboard fluid, but `services: 0 total` and `t` did not open selector
- `session-20260308135158-5283-cd62`
  - `startup.debug_service_group=launch_attach`
  - `startup.debug_attach_group=listener_probe`
  - `startup.debug_listener_group=rebound_discovery`
  - `startup.debug_listener_group.synthetic_actual` emitted for backend and frontend
  - user result: dashboard fluid, but `services: 0 total` and `t` did not open selector

Current strongest narrowing:

- `services`
- `launch_attach`
- `listener_probe`
- `pid_wait`

So the bad path is now narrowed past the broader listener-probe family and into `process_runner.wait_for_pid_port(...)`.

## 2026-03-08: Next honest split inside `pid_wait`

`wait_for_pid_port(...)` in [process_runner.py](../../python/envctl_engine/shared/process_runner.py#L365) is a loop over three concrete checks:

- `signal_gate`
  - `os.kill(pid, 0)` liveness gate in [process_runner.py](../../python/envctl_engine/shared/process_runner.py#L261)
- `pid_port_lsof`
  - direct `lsof -a -p <pid> -iTCP:<port> -sTCP:LISTEN -t` in [process_runner.py](../../python/envctl_engine/shared/process_runner.py#L335)
- `tree_port_scan`
  - `find_pid_listener_port(pid, port, max_delta=0)` which walks the process tree and runs broader listener scans in [process_runner.py](../../python/envctl_engine/shared/process_runner.py#L387)

New routing surface:

- `ENVCTL_DEBUG_PLAN_PID_WAIT_GROUP=signal_gate|pid_port_lsof|tree_port_scan`
- parsed in [startup_orchestrator.py](../../python/envctl_engine/startup/startup_orchestrator.py#L297)
- forwarded only under:
  - `services`
  - `launch_attach`
  - `listener_probe`
  - `pid_wait`
- execution emits `startup.debug_pid_wait_group` in [startup_execution_support.py](../../python/envctl_engine/startup/startup_execution_support.py#L638)

### Next 3 manual commands

#### `signal_gate`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_ATTACH_GROUP=listener_probe \
ENVCTL_DEBUG_PLAN_LISTENER_GROUP=pid_wait \
ENVCTL_DEBUG_PLAN_PID_WAIT_GROUP=signal_gate \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
./bin/envctl --repo /path/to/your/repo --plan
```

#### `pid_port_lsof`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_ATTACH_GROUP=listener_probe \
ENVCTL_DEBUG_PLAN_LISTENER_GROUP=pid_wait \
ENVCTL_DEBUG_PLAN_PID_WAIT_GROUP=pid_port_lsof \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
./bin/envctl --repo /path/to/your/repo --plan
```

#### `tree_port_scan`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_ATTACH_GROUP=listener_probe \
ENVCTL_DEBUG_PLAN_LISTENER_GROUP=pid_wait \
ENVCTL_DEBUG_PLAN_PID_WAIT_GROUP=tree_port_scan \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
./bin/envctl --repo /path/to/your/repo --plan
```

### Validation rule for those runs

Do not trust a run unless its event log shows:

- `startup.debug_service_group=launch_attach`
- `startup.debug_attach_group=listener_probe`
- `startup.debug_listener_group=pid_wait`
- `startup.debug_pid_wait_group` with the requested subgroup

## 2026-03-08: Important correction on the `pid_wait` subgroup reruns

The three `pid_wait` subgroup reruns were valid executions, but they were **not trustworthy for further narrowing inside `pid_wait`**.

Reason:

- all three runs still passed through the shared post-start truth assertion in [startup_execution_support.py](../../python/envctl_engine/startup/startup_execution_support.py#L123)
- that assertion calls `service_truth_status(...)` in [engine_runtime_service_truth.py](../../python/envctl_engine/runtime/engine_runtime_service_truth.py#L160)
- `service_truth_status(...)` was still using the full, unfiltered truth path:
  - `wait_for_pid_port`
  - `port_fallback`
  - `truth_discovery`
  - `refresh_listener_pids`
- so the three attach-side `pid_wait` subgroup runs reconverged on the same later truth-check tail

Evidence that this reconvergence was real:

- `signal_gate` run: `session-20260308135503-7279-f2ab`
  - valid routing markers present
  - emitted multiple `startup.debug_listener_group.synthetic_actual`
- `pid_port_lsof` run: `session-20260308135659-8861-df58`
  - valid routing markers present
  - emitted `startup.debug_listener_group.synthetic_actual` for frontend services
- `tree_port_scan` run: `session-20260308140017-12195-2b82`
  - valid routing markers present
  - no attach-side synthetic marker, but still shared the same post-start truth path

So the right interpretation is:

- those runs were valid observations
- but they do **not** isolate the culprit further inside attach-side `pid_wait`
- the next honest seam is the shared **post-start truth** path

## 2026-03-08: New split for post-start truth

Added:

- `ENVCTL_DEBUG_PLAN_POSTSTART_TRUTH_GROUP=pid_wait|port_fallback|truth_discovery`

Routing:

- parsed in [startup_orchestrator.py](../../python/envctl_engine/startup/startup_orchestrator.py#L301)
- forwarded for `services + launch_attach` in [startup_orchestrator.py](../../python/envctl_engine/startup/startup_orchestrator.py#L1411)
- emitted as `startup.debug_poststart_truth_group` in [startup_execution_support.py](../../python/envctl_engine/startup/startup_execution_support.py#L128)

Code boundaries inside the shared post-start truth pass:

- `pid_wait`
  - `ProcessProbe.service_truth_status(...)` -> `wait_for_pid_port(...)`
  - [process_probe.py](../../python/envctl_engine/shared/process_probe.py#L171)
- `port_fallback`
  - `ProcessProbe._port_fallback_running(...)`
  - [process_probe.py](../../python/envctl_engine/shared/process_probe.py#L280)
- `truth_discovery`
  - `truth_discovery(service, port)` / discovered actual-port recovery
  - [process_probe.py](../../python/envctl_engine/shared/process_probe.py#L221)

### Next 3 manual commands

#### `pid_wait`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_POSTSTART_TRUTH_GROUP=pid_wait \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
./bin/envctl --repo /path/to/your/repo --plan
```

#### `port_fallback`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_POSTSTART_TRUTH_GROUP=port_fallback \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
./bin/envctl --repo /path/to/your/repo --plan
```

#### `truth_discovery`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_POSTSTART_TRUTH_GROUP=truth_discovery \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
./bin/envctl --repo /path/to/your/repo --plan
```

### Validation rule for those runs

Do not trust a run unless its event log shows:

- `startup.debug_service_group=launch_attach`
- `startup.debug_poststart_truth_group` with the requested subgroup

## 2026-03-08: Trustworthy result inside startup post-start truth

Verified from event logs:

- `session-20260308140433-15087-8a55`
  - `startup.debug_poststart_truth_group=pid_wait`
  - user result: fluid dashboard, `services: 0 total`, selector did not open
- `session-20260308140457-16100-e491`
  - `startup.debug_poststart_truth_group=port_fallback`
  - user result: fluid dashboard, `services: 0 total`, selector did not open
- `session-20260308140513-16937-c54f`
  - `startup.debug_poststart_truth_group=truth_discovery`
  - user result: bad, with full `services: 8 total` state preserved

So the startup post-start truth split itself did isolate one bad subgroup:

- `truth_discovery`: bad
- `pid_wait`: not sufficient
- `port_fallback`: not sufficient

## 2026-03-08: Why startup `truth_discovery` is still not the last seam

The `truth_discovery` startup run preserved the fully populated dashboard state, but the event log shows a later threaded truth-refresh pass after dashboard entry:

- later `service.truth.check` events appear on `ThreadPoolExecutor-*` threads in `session-20260308140513-16937-c54f`
- those later checks are emitted by `reconcile_state_truth(...)` in [engine_runtime_state_truth.py](../../python/envctl_engine/runtime/engine_runtime_state_truth.py#L232)
- that reconcile is triggered by dashboard snapshot rendering in [rendering.py](../../python/envctl_engine/ui/dashboard/rendering.py#L16) through [engine_runtime_dashboard_truth.py](../../python/envctl_engine/runtime/engine_runtime_dashboard_truth.py#L32)

This means the remaining bad path is no longer cleanly isolated to the startup post-start truth call alone.
There is a later dashboard truth-refresh path that still runs after entry and can reintroduce the bad behavior.

## 2026-03-08: New split for dashboard truth refresh

Added:

- `ENVCTL_DEBUG_PLAN_DASHBOARD_TRUTH_GROUP=pid_wait|port_fallback|truth_discovery`

Implementation:

- env parsed directly by [engine_runtime_dashboard_truth.py](../../python/envctl_engine/runtime/engine_runtime_dashboard_truth.py#L18)
- emitted as `dashboard.debug_truth_group` in [engine_runtime_dashboard_truth.py](../../python/envctl_engine/runtime/engine_runtime_dashboard_truth.py#L40)
- applied only around dashboard-triggered `reconcile_state_truth(...)`
- `service_truth_status(...)` now prefers this dashboard truth subgroup when set

### Next 3 manual commands

#### `pid_wait`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_DASHBOARD_TRUTH_GROUP=pid_wait \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
./bin/envctl --repo /path/to/your/repo --plan
```

#### `port_fallback`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_DASHBOARD_TRUTH_GROUP=port_fallback \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
./bin/envctl --repo /path/to/your/repo --plan
```

#### `truth_discovery`

```bash
unset ENVCTL_UI_SIMPLE_MENUS ENVCTL_UI_SELECTOR_IMPL ENVCTL_UI_SELECTOR_CHARACTER_MODE
ENVCTL_DEBUG_PLAN_EXEC_GROUP=services \
ENVCTL_DEBUG_PLAN_SERVICE_GROUP=launch_attach \
ENVCTL_DEBUG_PLAN_DASHBOARD_TRUTH_GROUP=truth_discovery \
ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize \
ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard \
ENVCTL_DEBUG_PLAN_SNAPSHOT=1 \
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_SELECTOR_KEYS=1 \
ENVCTL_DEBUG_SELECTOR_THREAD_STACK=1 \
ENVCTL_UI_BASIC_INPUT_FD=0 \
./bin/envctl --repo /path/to/your/repo --plan
```

### Validation rule for those runs

Do not trust a run unless its event log shows:

- `startup.debug_service_group=launch_attach`
- `dashboard.debug_truth_group` with the requested subgroup

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

But they still reconverged on the same later shared tail:

- `ui.input.submit normalized_command=test`
- `ui.selector.preflight`
- `ui.selector.subprocess`

And the selector subprocess traces for all three sessions still showed the same bad behavior:

- entered with `stdout/stderr lflag=536872395` and `pendin=true`
- restored to `lflag=1483` and `pendin=false` on exit
- received only `3` to `4` `Down` events, then idled until `Ctrl-C`

This means the dashboard truth split is not the next trustworthy seam.
The next honest split is the shared selector-wrapper path in [backend.py](../../python/envctl_engine/ui/backend.py).

## 2026-03-08: Added explicit selector-wrapper branch marker

Added:

- `startup.debug_tty_common_group`

Implementation:

- emitted in [backend.py](../../python/envctl_engine/ui/backend.py#L284)
- records:
  - `selector_kind`
  - `group=default|dashboard|preflight|subprocess`
  - `run_preflight`
  - `run_subprocess`
  - `run_inprocess_direct`

This makes the next manual split log-verifiable rather than inferred.

## 2026-03-08: Next trustworthy 3-way split

Use:

- `ENVCTL_DEBUG_PLAN_TTY_COMMON_GROUP=dashboard|preflight|subprocess`

Real code boundary meanings in [backend.py](../../python/envctl_engine/ui/backend.py):

- `dashboard`
  - skip selector preflight
  - skip selector subprocess
  - run selector in-process directly from the dashboard path
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
./bin/envctl --repo /path/to/your/repo --plan
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
./bin/envctl --repo /path/to/your/repo --plan
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
./bin/envctl --repo /path/to/your/repo --plan
```

### Trust rule for the next three runs

Do not trust a run unless its event log shows:

- `startup.debug_service_group=launch_attach`
- `startup.debug_tty_common_group` with the requested `group`

Then confirm the branch shape from the same event:

- `dashboard`: `run_preflight=false`, `run_subprocess=false`, `run_inprocess_direct=true`
- `preflight`: `run_preflight=true`, `run_subprocess=false`, `run_inprocess_direct=true`
- `subprocess`: `run_preflight=false`, `run_subprocess=true`, `run_inprocess_direct=false`

## 2026-03-08: `TTY_COMMON_GROUP` also reconverged

Verified event-log-backed reruns:

- `dashboard`: bad
  - session: `session-20260308141849-28971-34d3`
- `preflight`: bad
  - session: `session-20260308141914-30057-c40c`
- `subprocess`: bad
  - session: `session-20260308141940-31169-5c61`

All three runs were valid:

- each log showed `startup.debug_service_group=launch_attach`
- each log showed `startup.debug_tty_common_group` with the requested group
- the branch booleans matched the requested mode exactly

Observed code-backed behavior:

- `dashboard`
  - no `ui.selector.preflight`
  - no `ui.selector.subprocess`
  - in-process selector still cancelled after a few navigation events
- `preflight`
  - `ui.selector.preflight` ran
  - no `ui.selector.subprocess`
  - in-process selector still cancelled
- `subprocess`
  - `ui.selector.subprocess` ran
  - child selector still received only a few `Down` events before `Ctrl-C`

Interpretation:

- the selector-wrapper seam is too late
- the contaminant is already present before `dashboard|preflight|subprocess` diverge

## 2026-03-08: Preselector split corrected to use a constant child tail

The next honest seam is earlier:

- `ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=startup_direct|dashboard_direct|command_context`

But to make that split trustworthy under the current `services -> launch_attach` isolation, all three branches must terminate through the same selector checkpoint.

Implemented correction in [startup_orchestrator.py](../../python/envctl_engine/startup/startup_orchestrator.py#L1039):

- `startup_direct` now forces `ENVCTL_DEBUG_PLAN_SELECTOR_GROUP=standalone_child`
- `dashboard_direct` now forces `ENVCTL_DEBUG_PLAN_SELECTOR_GROUP=standalone_child`
- `command_context` now forces `ENVCTL_DEBUG_PLAN_SELECTOR_GROUP=standalone_child`

This keeps the downstream selector tail constant while varying only the earlier preselector boundary.

### Real boundary meanings

- `startup_direct`
  - after real startup builds the real `RunState`, open the standalone child selector immediately
  - bypass `_run_interactive_dashboard_loop(...)`
- `dashboard_direct`
  - enter `_run_interactive_dashboard_loop(...)`
  - immediately open the standalone child selector on loop entry
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
./bin/envctl --repo /path/to/your/repo --plan
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
./bin/envctl --repo /path/to/your/repo --plan
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
./bin/envctl --repo /path/to/your/repo --plan
```

### Trust rule for the next three runs

Do not trust a run unless its event log shows:

- `startup.debug_service_group=launch_attach`
- `startup.debug_preselector_group` with the requested group
- `startup.debug_selector_group=standalone_child`

Expected shapes:

- `startup_direct`
  - `startup.debug_preselector_group action=direct_selector_before_dashboard`
- `dashboard_direct`
  - `startup.debug_preselector_group action=dashboard_loop_override`
  - selector opens without needing to press `t`
- `command_context`
  - `startup.debug_preselector_group action=dashboard_loop_override`
  - press `t` to trigger the selector

## 2026-03-08: Preselector reruns were invalid under the current preentry harness

The three reruns using:

- `ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=startup_direct`
- `ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=dashboard_direct`
- `ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=command_context`

were not trustworthy in the full current harness that also uses:

- `ENVCTL_DEBUG_PLAN_PREENTRY_GROUP=branch_setup,project_loop,finalize`
- `ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP=full_dashboard`

Verified reason from the event logs:

- no run emitted `startup.debug_preselector_group`
- all three went through the normal preentry tail:
  - `before_dashboard_entry`
  - `after_first_dashboard_render`
  - then normal `ui.input.submit`
  - then normal `ui.selector.preflight` / `ui.selector.subprocess`

So those three runs did not actually exercise the requested preselector branches.

## 2026-03-08: Fixed preselector routing in the preentry tail

The bug was in [startup_orchestrator.py](../../python/envctl_engine/startup/startup_orchestrator.py#L1497):

- `_debug_run_post_preentry_tail(...)` ignored `ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP`

Correction:

- the preentry tail now honors:
  - `startup_direct`
  - `dashboard_direct`
  - `command_context`
- and forces `ENVCTL_DEBUG_PLAN_SELECTOR_GROUP=standalone_child` for all three, keeping the selector tail constant

Compile check passed after the fix.

## 2026-03-08: Rerun the same 3 preselector commands

Use the same three commands again. They are now valid with the current preentry harness.

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
./bin/envctl --repo /path/to/your/repo --plan
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
./bin/envctl --repo /path/to/your/repo --plan
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
./bin/envctl --repo /path/to/your/repo --plan
```

### Updated trust rule

Do not trust a run unless its event log shows:

- `startup.debug_service_group=launch_attach`
- `startup.debug_preselector_group` with the requested group
- `startup.debug_selector_group=standalone_child`

Expected shape:

- `startup_direct`
  - no dashboard prompt before selector
  - `startup.debug_preselector_group action=direct_selector_before_dashboard`
- `dashboard_direct`
  - selector opens immediately on dashboard-loop entry
  - `startup.debug_preselector_group action=dashboard_loop_override`
- `command_context`
  - dashboard prompt appears first
  - press `t` to trigger selector
  - `startup.debug_preselector_group action=dashboard_loop_override`

## 2026-03-08: Corrected preselector split is valid and all three are bad

Verified valid reruns:

- `startup_direct`: bad
  - session: `session-20260308142719-40110-f9f2`
- `dashboard_direct`: bad
  - session: `session-20260308142752-41191-09f0`
- `command_context`: bad
  - session: `session-20260308142823-42181-1ace`

These runs are trustworthy because the logs show:

- `startup.debug_service_group=launch_attach`
- `startup.debug_preselector_group` with the requested group
- `startup.debug_selector_group=standalone_child`

Observed shape:

- `startup_direct`
  - opened the child selector before entering the dashboard loop
- `dashboard_direct`
  - entered the dashboard loop and opened the child selector immediately
- `command_context`
  - entered the normal dashboard loop, then opened the same child selector after `t`

All three child selector traces still showed the same failure pattern:

- only `2` to `4` `Down` events received
- then idle until `Ctrl-C`

Interpretation:

- every post-start interactive tail is now ruled out as the primary seam
- the contaminant is already present before the earliest standalone child selector checkpoint
- the next honest split must move back into `services -> launch_attach`

## 2026-03-08: Next trustworthy rerun uses `launch_attach` groups with the earliest constant tail

Rerun the original attach-group split, but now with:

- `ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP=startup_direct`

This keeps the downstream checkpoint constant:

- real `launch_attach` subgroup under test
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
./bin/envctl --repo /path/to/your/repo --plan
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
./bin/envctl --repo /path/to/your/repo --plan
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
./bin/envctl --repo /path/to/your/repo --plan
```

### Trust rule for those reruns

Do not trust a run unless its event log shows:

- `startup.debug_service_group=launch_attach`
- `startup.debug_attach_group=<requested subgroup>`
- `startup.debug_preselector_group=startup_direct`
- `startup.debug_selector_group=standalone_child`

## 2026-03-08: Current direction assessment

The strongest current evidence chain remains:
- `requirements`: good
- `completion`: good
- `services`: bad
- inside `services`:
  - `bootstrap`: good
  - `record_merge`: good
  - `launch_attach`: bad
- inside `launch_attach`:
  - `process_start`: good in the degraded-input sense, though `t` may collapse to `No test target selected.`
  - `listener_probe`: bad
  - `attach_merge`: good in the degraded-input sense, though `t` may collapse to `No test target selected.`

There were later experiments layering `ENVCTL_DEBUG_PLAN_TTY_COMMON_GROUP` over the bad `launch_attach` path. Those remained bad, but they are weaker evidence than the subgroup split above because they still wrap the already-bad attach family and have not yet been proven to be independent enough.

### Practical conclusion

Yes, the investigation is broadly looking in the right direction, but the part worth trusting most is:
- `services -> launch_attach -> listener_probe`

If the next solver has to choose where to recurse, that is the best current seam. The generic tty/common overlays should be treated as secondary context, not the main line of proof.

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
./bin/envctl --repo /path/to/your/repo --plan
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
./bin/envctl --repo /path/to/your/repo --plan
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
./bin/envctl --repo /path/to/your/repo --plan
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
./bin/envctl --repo /path/to/your/repo --plan
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
./bin/envctl --repo /path/to/your/repo --plan
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
./bin/envctl --repo /path/to/your/repo --plan
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

That shared code lives in `wait_for_pid_port(...)` in [process_runner.py](../../python/envctl_engine/shared/process_runner.py#L365):

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

This is a real code-boundary split in [startup_execution_support.py](../../python/envctl_engine/startup/startup_execution_support.py#L876) and [startup_execution_support.py](../../python/envctl_engine/startup/startup_execution_support.py#L944), not an imaginary label.

### Wiring added

New env:

- `ENVCTL_DEBUG_PLAN_PID_WAIT_SERVICE=backend|frontend|both`

Routing / validation markers:

- parse in [startup_orchestrator.py](../../python/envctl_engine/startup/startup_orchestrator.py#L301)
- propagate in [startup_orchestrator.py](../../python/envctl_engine/startup/startup_orchestrator.py#L1419)
- emit in [startup_execution_support.py](../../python/envctl_engine/startup/startup_execution_support.py#L662)

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
./bin/envctl --repo /path/to/your/repo --plan
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
./bin/envctl --repo /path/to/your/repo --plan
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
./bin/envctl --repo /path/to/your/repo --plan
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
./bin/envctl --repo /path/to/your/repo --plan
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
./bin/envctl --repo /path/to/your/repo --plan
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
./bin/envctl --repo /path/to/your/repo --plan
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
./bin/envctl --repo /path/to/your/repo --plan
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
./bin/envctl --repo /path/to/your/repo --plan
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
./bin/envctl --repo /path/to/your/repo --plan
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

A focused code change was applied in [process_runner.py](../../python/envctl_engine/shared/process_runner.py) so the shared probe subprocesses (`ps`/`lsof`) no longer inherit terminal stdin:

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
./bin/envctl --repo /path/to/your/repo --plan
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

In [process_runner.py](../../python/envctl_engine/shared/process_runner.py), `ProcessRunner.start(...)` now launches background service processes with:

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
./bin/envctl --repo /path/to/your/repo --plan
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

- [process_runner.py](../../python/envctl_engine/shared/process_runner.py)

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
