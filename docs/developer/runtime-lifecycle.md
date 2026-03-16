# Runtime Lifecycle

This guide focuses on how the Python runtime boots, parses commands, chooses behavior, and hands work off to orchestrators.

Use it when you are changing command flow, startup/resume behavior, launcher handoff, or interactive entry conditions.

## End-to-End Flow

The active execution path is:

1. `bin/envctl`
2. `envctl_engine.runtime.launcher_cli`
3. `envctl_engine.runtime.cli:main`
4. `envctl_engine.runtime.command_router.parse_route`
5. `EngineRuntime`
6. `engine_runtime_dispatch.dispatch_command`
7. orchestrator or inspection handler

Why this matters:

- launcher bugs live before Python import even starts
- wrapper-selection policy also lives before launcher handoff: explicit repo-wrapper paths stay local, while bare `envctl` can still hop to an installed command
- route-parsing bugs live before `EngineRuntime` behavior
- orchestration bugs usually live after `dispatch_command`

## Launcher Responsibilities

`envctl_engine.runtime.launcher_cli` owns:

- repository root resolution
- `--repo` handling
- launcher-only subcommands such as `install`, `uninstall`, and launcher `doctor`
- Python runtime handoff

`bin/envctl` plus `runtime/launcher_support.py` own the wrapper-selection policy that runs before `launcher_cli` starts:

- `ENVCTL_USE_REPO_WRAPPER=1` forces the repo wrapper
- explicit wrapper paths use the current wrapper directly
- bare-name invocations keep the installed-command preference when another `envctl` shadows the repo wrapper on `PATH`

Important env exports set before the engine starts include:

- `RUN_REPO_ROOT`
- `RUN_ENGINE_PATH`
- `RUN_LAUNCHER_NAME`
- `RUN_LAUNCHER_CONTEXT`

## CLI Bootstrapping

`python/envctl_engine/runtime/cli.py` is the real bootstrap layer for the Python engine.

It does all of the following before dispatch:

- initial route parse using enough local config state to honor `ENVCTL_DEFAULT_MODE`
- local config discovery
- `.envctl` bootstrap gating
- full config load into `EngineConfig`
- final route parse with the resolved config/environment
- prerequisite checks for selected command classes
- exit code normalization
- terminal restore in `finally`

That makes `runtime/cli.py` part of the runtime contract, not just a thin wrapper.

## Why Route Parsing Happens Twice

The CLI needs to know enough about the route to decide whether missing local config is allowed.

That means:

- initial parse: uses local config discovery only to infer things like default mode
- final parse: uses full loaded config and final environment view

This is why bootstrap-safe inspect commands work even before `.envctl` exists.

## Bootstrap-Safe Commands

Commands intentionally allowed without a repo-local `.envctl`:

- `help`
- `list-commands`
- `list-targets`
- `list-trees`
- `show-config`
- `show-state`
- `explain-startup`

The `config` command also has special handling because it is the bootstrap/edit path itself.

If you add a new inspect-only command, decide explicitly whether it belongs in this allowlist.

## Prerequisite Checks

`cli.py` also owns command-class-specific prereq checks.

Examples:

- `git` is required broadly
- `docker` is required for start/plan/restart when managed dependencies are enabled
- `lsof` is required when listener-query port availability mode is selected
- `rich` is required for the Python runtime surface

If you add runtime-critical dependencies, add them here instead of letting them fail later with low-quality errors.

## `EngineRuntime` as Composition Root

`EngineRuntime` wires together the runtime domains and exposes the facade the orchestrators call through.

Major collaborators include:

- config
- process runner
- process probe
- port planner
- state repository
- terminal UI
- startup/resume/dashboard/action/state orchestrators
- doctor/debug support

Guideline:

- add policy to domain modules
- add composition and cross-domain wiring to `EngineRuntime`

## Dispatch Layer

`runtime/engine_runtime_dispatch.py` maps normalized commands to handlers.

Keep it small.

A good dispatch change:

- adds a command branch
- delegates immediately to a specific handler/orchestrator

A bad dispatch change:

- starts embedding business logic
- duplicates route policy that belongs in the parser
- duplicates lifecycle logic that belongs in orchestrators

## Command Family Ownership

The runtime does not have one generic "command orchestrator".

Current dispatch families are:

- direct inspection commands
- debug bundle/report helpers
- lifecycle cleanup commands
- startup/resume commands
- dashboard and config commands
- state actions such as logs/health/errors
- project actions such as test/pr/commit/review/migrate

This matters because each family has different assumptions about:

- whether state must already exist
- whether interactive selection is allowed
- whether the command mutates runtime state
- whether headless mode should still work cleanly

If a command feels awkward in its current family, that is usually a design smell worth resolving explicitly instead of bypassing the boundary.

## Inspection vs Operational Commands

The runtime has two broad command classes:

- inspection commands that answer questions without mutating runtime state
- operational commands that create, reconcile, or destroy state

Inspection commands include:

- `list-commands`
- `list-targets`
- `list-trees`
- `show-config`
- `show-state`
- `explain-startup`

Operational commands include:

- `start`
- `plan`
- `resume`
- `restart`
- `stop`
- `stop-all`
- `blast-all`
- dashboard/state/action commands

This split matters for:

- config bootstrap rules
- headless safety
- exit code expectations
- test setup cost
- keeping `show-config` and `explain-startup` aligned with startup-blocking config such as per-mode startup disablement

Inside the operational side, there is another important split:

- startup/resume/cleanup commands operate on runtime lifecycle
- state actions operate on existing saved state
- action commands operate on selected projects or services and may reuse saved state for targeting
- dashboard commands may route back into all of the above through interactive command dispatch

## Startup Lifecycle

Startup is primarily coordinated by `startup/startup_orchestrator.py`.

High-level phases:

1. restart pre-stop if command is `restart`
2. mode validation
3. shell-budget gate enforcement
4. run id / debug session announcement
5. project discovery and selection
6. port reservation
7. requirements startup
8. service startup
9. artifact persistence
10. optional dashboard entry

The orchestrator itself should remain orchestration-heavy, not policy-heavy.

Supporting policy belongs in:

- `engine_runtime_startup_support.py`
- `startup_selection_support.py`
- `startup_execution_support.py`
- `requirements_startup_domain.py`
- `service_bootstrap_domain.py`

## Resume Lifecycle

Resume is coordinated by `startup/resume_orchestrator.py`.

High-level phases:

1. load latest state
2. bind debug run id if available
3. enforce cutover budgets for resume
4. reconcile state truth
5. optionally restore missing services
6. save reconciled state
7. optionally enter interactive dashboard

The important design choice is that resume is truth-driven, not just pointer-driven.

## Dashboard and Interactive Entry

Interactive behavior is split across:

- dashboard backend policy
- selector implementation policy

That split is important:

- dashboard backend can still be legacy by default
- selectors are already Textual-first by default

Do not collapse these into one idea when refactoring.

Key files:

- `ui/backend_resolver.py`
- `ui/backend.py`
- `ui/dashboard/orchestrator.py`
- `ui/textual/screens/selector/*`

The dashboard also has its own command path:

1. read one interactive command line
2. sanitize and normalize aliases
3. parse that command through `parse_route()`
4. inherit current state mode if the command did not set one explicitly
5. add interactive-only flags such as `interactive_command`
6. apply dashboard-owned target selection where needed
7. dispatch through the normal runtime dispatch path

That is why dashboard command bugs often cross the parser, UI, and orchestrator boundaries at once.

## Progress and Spinner Reporting

Startup and resume no longer keep all reporting logic inline.

Important files:

- `startup/startup_progress.py`
- `startup/resume_progress.py`
- `startup/progress_shared.py`

Current design:

- orchestrators emit semantic progress points
- progress helpers deduplicate messages and choose output channels
- shared spinner groups own rich progress rendering and spinner lifecycle events

That separation is important for:

- interactive UX consistency
- debug-flight-recorder evidence
- keeping orchestration code readable after feature growth

## Command Parsing Ownership

`runtime/command_router.py` is the canonical parser contract.

It owns:

- command aliases
- mode tokens
- project flag handling
- boolean/value/pair/special flags
- env-style assignment handling
- supported command inventory

If a behavior is user-visible at the CLI surface, first ask whether it belongs here.

Examples that do belong here:

- new aliases
- new command names
- new supported flags
- default mode semantics

Examples that do not belong here:

- startup sequencing
- runtime truth rules
- dependency startup retries

## Exit Code Contract

The CLI normalizes exit codes into:

- `0`: success
- `1`: actionable failure
- `2`: controlled quit / interrupt

Preserve this shape unless there is a very strong reason not to.

It is especially important for:

- automation
- CI
- agent flows
- compatibility tests

## Adding a New Command

Checklist:

1. Add aliases and supported command entry in `runtime/command_router.py`.
2. Decide whether the command is bootstrap-safe.
3. Decide whether it is inspection-only or operational.
4. Dispatch from `engine_runtime_dispatch.py`.
5. Implement behavior in the right orchestrator or support module.
6. Add parser tests, dispatch tests, and behavior tests.
7. Update reference and user docs.

## Adding a New Startup/Resume Policy

Checklist:

1. Put the policy in `startup/` or `runtime/*_support.py`, not directly into `EngineRuntime`.
2. Decide whether it affects inspection commands such as `explain-startup`.
3. Emit events if operators or diagnostics need visibility.
4. Add tests for happy path, failure path, and headless behavior if relevant.
5. Update user docs if the operational story changed.

## Common Mistakes

- putting route policy in orchestrators instead of the parser
- adding config parsing ad hoc instead of through `EngineConfig`
- changing startup behavior without updating `explain-startup`
- changing resume truth behavior without checking doctor and debug surfaces
- assuming unsupported compatibility paths are still part of the active runtime contract
