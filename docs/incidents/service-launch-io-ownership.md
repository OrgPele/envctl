# Service Launch I/O Ownership Bug

## Summary

The post-`--plan` interactive input bug was caused by **background service processes inheriting envctl's controller stdin**.

`envctl --plan` acts as an interactive controller:
- it runs the planning selector
- it launches backend/frontend service processes
- it stays alive and enters the interactive dashboard

Before the fix, the launched backend/frontend child processes were started without an explicit `stdin=` policy, so they inherited fd `0` from the controller process. That meant:
- the dashboard and selector were trying to read terminal input
- the launched service children could also read the same terminal input
- some keypresses were consumed by the wrong process

The bug was therefore an **I/O ownership bug in child-process launch**, not a dashboard rendering bug and not a Textual bug.

## User-visible symptoms

When the bug reproduced:
- the planning selector worked correctly
- the failure started only after envctl left the planning selector and entered the post-plan dashboard
- the dashboard could feel partially unresponsive
- `t` test-target selection was especially unreliable
- arrow keys, `Enter`, `Esc`, and sometimes typed characters partially registered
- the selector could exit with `No test target selected.` even though navigation was attempted

The selector failure was a downstream symptom:
- the child selector process itself was healthy
- it was just receiving an incomplete key stream because some input bytes had already been consumed elsewhere

## When it showed up

The bug showed up in the **real post-plan fresh service-launch path**:
- after the planning selector exited
- after envctl launched real backend/frontend services
- when envctl then entered the interactive dashboard and opened menus/selectors

It was most obvious in some **reused Apple Terminal tabs**, but the terminal was not the root cause. Reused tabs only made the race/input contention easier to observe.

The bug was isolated to:
- `services`
- then `launch_attach`
- then the real listener/attach path

That isolation mattered because it proved the issue lived in real service startup side effects, not in synthetic dashboard-only paths.

## When it did not show up

The bug did **not** show up in these cases:
- the planning selector by itself
- standalone Textual selector probes
- standalone prompt-toolkit probes
- standalone `TerminalSession.read_command_line(...)` probes
- the known-good synthetic baseline with `ENVCTL_DEBUG_SKIP_PLAN_STARTUP=1`
- synthetic/minimal dashboard-only paths
- resume/restore flows that reused already-running services instead of freshly launching new ones from the same controller process

The key difference was whether the interactive controller was competing with newly launched background children for terminal input.

## Exact root cause

The concrete fault was in the background-service launch path:

- [startup_execution_support.py](../../python/envctl_engine/startup/startup_execution_support.py)
  - `start_backend(...)`
  - `start_frontend(...)`
- both launched service commands through the process runner

Before the fix, the generic subprocess launch behavior did not explicitly deny stdin inheritance for those long-lived background services.

That meant the launched backend/frontend commands inherited:
- controller stdin
- even though their stdout/stderr were already redirected to log files
- and even though they were not intended to be interactive terminal children

The dashboard and selector later read input from the same terminal, so both sides were effectively contending for the same byte stream.

## Why it was hard to find

This took so long to isolate because the symptom and the cause were in different subsystems.

What made it misleading:
- the failure looked like a UI/input bug
- the planning selector remained healthy
- standalone Textual and prompt-toolkit probes remained healthy
- many synthetic debug paths removed the real launched children and therefore hid the bug
- some intermediate investigation runs were invalid until the debug routing/harness was fixed
- reused Apple Terminal tabs made the issue look like terminal-state corruption instead of child-process stdin contention

In practice, the bug only became obvious after the investigation stopped asking "what is wrong with the selector?" and started asking "who owns terminal input in the process tree right now?"

## The fix

The fix was to turn child-process launch into an explicit **launch-intent + I/O ownership** contract.

Implemented in [process_runner.py](../../python/envctl_engine/shared/process_runner.py):
- `start_background(...)`
- `run_probe(...)`
- `start_interactive_child(...)`

Contract:
- `background_service`
  - `stdin=subprocess.DEVNULL`
  - may not own controller input
- `probe`
  - `stdin=subprocess.DEVNULL`
  - may not own controller input
- `interactive_child`
  - explicit opt-in path
  - may own controller input

The real startup call sites were migrated in [startup_execution_support.py](../../python/envctl_engine/startup/startup_execution_support.py):
- backend launch now uses `start_background(...)`
- frontend launch now uses `start_background(...)`

This is the proven behavioral fix:
- background services no longer share the controller's terminal stdin
- the dashboard/selector own the key stream again

## Permanent diagnostics added

The fix was paired with permanent observability so this class of bug is diagnosable from one run instead of a long binary-search investigation.

Every child launch now emits a `process.launch` event with:
- launch intent
- pid
- command hash
- cwd
- stdin policy
- stdout/stderr policy
- whether controller input ownership is allowed

That data is now surfaced in:
- [doctor_orchestrator.py](../../python/envctl_engine/debug/doctor_orchestrator.py)
- [debug_bundle_diagnostics.py](../../python/envctl_engine/debug/debug_bundle_diagnostics.py)
- [engine_runtime_debug_support.py](../../python/envctl_engine/runtime/engine_runtime_debug_support.py)
- [analyze_debug_bundle.py](../../scripts/analyze_debug_bundle.py)

The permanent diagnosis model is:
- background children must not own controller input
- probes must not own controller input
- only explicit interactive children may do so

## Where else this could happen

This bug class can happen anywhere a child process is launched while envctl is interactive and the child:
- is not meant to be interactive
- lives long enough to overlap with dashboard/selector input
- inherits stdin implicitly

### Fixed high-risk path

Fixed:
- real backend/frontend service launches through [process_runner.py](../../python/envctl_engine/shared/process_runner.py)

These were the actual culprit.

### Fixed probe path

Fixed:
- listener/probe helpers inside [process_runner.py](../../python/envctl_engine/shared/process_runner.py)

These were not the final root cause, but they were the same bug class and are now locked down under `run_probe(...)`.

### Intentional interactive child

Intentional and expected:
- selector subprocess launch in [backend.py](../../python/envctl_engine/ui/backend.py)

That subprocess is meant to read terminal input. It is not a background service. It is the correct class of child to own controller input while it is active.

This path should eventually be routed through the explicit `interactive_child` API for consistency, but it is not the bug that caused the post-plan dashboard failure.

### Remaining same-class hardening candidate

Still worth hardening:
- `_compose_up_handoff(...)` in [supabase.py](../../python/envctl_engine/requirements/supabase.py)

That function still uses a raw `subprocess.Popen(...)` without an explicit `stdin=` override.

Why it is lower risk than the fixed bug:
- it is a temporary handoff helper
- stdout/stderr are piped
- it is terminated after services are confirmed up
- it does not persist into the dashboard lifetime the way backend/frontend service children did

Why it is still worth fixing:
- it is the same bug class
- if its lifetime grows or overlaps future interactive flows, it could reproduce similar contention
- it should be migrated to the same launch-intent/I/O-ownership contract

### Low-risk raw subprocess sites

Audited low-risk sites include:
- short-lived `subprocess.run(..., capture_output=True)` calls in actions/shell helpers
- terminal repair helpers that intentionally run `stty sane` against a specific fd
- one-shot listener queries in [ports.py](../../python/envctl_engine/shared/ports.py)

These are not currently expected to reproduce the same persistent post-plan dashboard bug because they do not remain alive as competing background readers during the interactive dashboard phase.

## Practical rule going forward

When envctl is the interactive controller:
- only one process should own controller input at a time
- background services must never inherit stdin
- probes must never inherit stdin
- interactive children must be explicit

If a future bug looks like "the dashboard is flaky" or "the selector misses keys", the first question should be:

> which currently running child processes can still read controller input?

That question is now answerable from doctor/debug-bundle evidence without repeating the original investigation.
