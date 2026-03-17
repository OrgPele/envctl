# Command Surface and Routing

This guide explains the CLI contract from token parsing through dispatch.

Use it when you are changing commands, aliases, flags, parser behavior, bootstrap-safe inspection commands, or dispatch ownership.

## Command Layers

`envctl` has two command layers:

1. launcher commands handled before the Python runtime starts
2. runtime commands handled after `envctl_engine.runtime.cli:main`

Launcher-owned examples:

- `envctl install`
- `envctl uninstall`
- `envctl doctor --repo /path`
- `envctl --version`
- repo-root resolution via `--repo`

Runtime-owned examples:

- `resume`
- `plan`
- `dashboard`
- `show-config`
- `show-state`
- `explain-startup`
- `debug-pack`

Do not document or implement these as one undifferentiated command surface. The boundary is real and affects errors, prerequisites, tests, and docs.

`--version` is the current example of a launcher-owned flag that must stay outside `SUPPORTED_COMMANDS` and `list_supported_commands()`.

## Canonical Parser Contract

The canonical parser lives in `python/envctl_engine/runtime/command_router.py`.

Its output contract is the `Route` dataclass:

- `command`
- `mode`
- `raw_args`
- `passthrough_args`
- `projects`
- `flags`

Everything after route parsing assumes those fields are already normalized enough to execute without reinterpreting the CLI.

## Parsing Pipeline

`parse_route()` is intentionally staged.

Current phases:

1. normalization
2. classification
3. command and mode resolution
4. flag binding
5. route finalization

That structure matters because changes are easier to reason about when they stay in the right phase.

Examples:

- token spelling or normalization changes belong in normalization
- alias or command detection belongs in command/mode resolution
- `--flag value` and inline assignment handling belongs in flag binding

## Default Command and Default Mode

Two defaults exist and they solve different problems.

- default command: `start`
- default mode: comes from `ENVCTL_DEFAULT_MODE`, then built-in default `main`

That means a route can be implicit in two different ways:

- user did not specify a command, so runtime treats it as `start`
- user did not specify a mode, so runtime resolves mode from config/defaults

When changing CLI behavior, be explicit about which default you are changing.

## Alias Policy

`command_router.py` owns alias compatibility.

Examples already normalized there include:

- `--resume` -> `resume`
- `--debug-ui-pack` -> `debug-pack`
- `--dashboard` -> `dashboard`
- `--stop-all` -> `stop-all`

Rules of thumb:

- add aliases in the parser, not in dispatch
- keep alias behavior testable and visible in one place
- update docs when a new alias is meant to be user-facing
- avoid silently removing aliases that may still matter for shell-era habits or scripts

## Flag Families

The parser currently separates flag tokens into distinct families:

- boolean flags
- value flags
- pair flags
- special flags
- env-style assignment keys

This is not cosmetic. It lets the parser normalize different input styles into one route contract.

Examples:

- `--debug-pack`
- `--logs-tail 200`
- `--setup-worktrees FEATURE 3`
- `parallel-trees=true`

If a new flag behaves differently from the existing families, decide whether the parser needs a new explicit category rather than hiding a one-off in dispatch code.

## Inspection Commands vs Operational Commands

The runtime treats inspection commands differently from operational commands.

Inspection commands:

- `list-commands`
- `list-targets`
- `list-trees`
- `show-config`
- `show-state`
- `explain-startup`
- `help`

Operational commands:

- `start`
- `plan`
- `resume`
- `restart`
- `stop`
- `stop-all`
- `blast-all`
- dashboard and action flows

Why this matters:

- inspection commands are bootstrap-safe in repos without `.envctl`
- operational commands participate in startup, resume, cleanup, or state mutation
- docs should tell users when a command is safe to run before configuration exists

## Dispatch Contract

`python/envctl_engine/runtime/engine_runtime_dispatch.py` is the canonical runtime dispatch matrix.

Its job is intentionally narrow:

- read normalized `route.command`
- delegate immediately to the right orchestrator or direct inspection handler

Current high-level mapping:

- direct inspection: `list-targets`, `show-config`, `show-state`, `explain-startup`
- debug helpers: `debug-pack`, `debug-last`, `debug-report`
- lifecycle cleanup: `stop`, `stop-all`, `blast-all`
- startup/resume: `start`, `plan`, `restart`, `resume`
- dashboard/config: `dashboard`, `config`
- state actions: `logs`, `clear-logs`, `health`, `errors`
- action commands: `test`, `pr`, `commit`, `review`, `migrate`

If dispatch starts accumulating policy, the architecture is drifting in the wrong direction.

## Interactive Dashboard Commands Still Use the Same Parser

The dashboard does not invent a second command language.

`ui/dashboard/orchestrator.py` reads one command line, normalizes command aliases, and then routes the tokens back through `parse_route()`.

Important consequences:

- interactive commands should follow the same parser contract as shell-entered commands
- the current state mode is inherited only when the command did not explicitly set one
- dashboard-only behavior is layered on after parsing through flags and target-selection helpers

This is a useful place to look when a command works from the shell but behaves differently inside the dashboard.

## Bootstrap-Safe Command Rules

`runtime/cli.py` uses the parsed route to decide whether missing repo-local config is acceptable.

That means command-surface changes can accidentally break bootstrap behavior.

When adding a command, decide all of the following explicitly:

- should it work before `.envctl` exists?
- is it inspection-only or operational?
- should it be available in headless mode?
- does it need prereq checks before execution?

If you do not answer those questions, the command contract will become ambiguous.

## Runtime Boundary

The Python parser and dispatch surface are the supported command path.

That affects command-surface work in two ways:

- Python-only commands must fail clearly when runtime prerequisites are missing
- docs should not pretend unsupported compatibility paths support modern Python-only features

Example:

- `debug-pack` is correctly documented and implemented as Python-runtime only

Clear capability boundaries are better than fake parity.

## Adding a New Command

Checklist:

1. Add aliases and supported-command coverage in `runtime/command_router.py`.
2. Decide whether the command is inspection-only or operational.
3. Decide whether it is bootstrap-safe without `.envctl`.
4. Dispatch it from `runtime/engine_runtime_dispatch.py`.
5. Implement it in the correct orchestrator or helper layer.
6. Add parser tests, dispatch tests, and behavior tests.
7. Update reference docs and any user/developer docs that mention the affected workflow.

## Changing an Existing Flag

Checklist:

1. Update parser token handling in the right flag family.
2. Check whether env-style assignment compatibility also needs updating.
3. Check whether `list_supported_commands()` or supported-flag reporting should change.
4. Update tests for explicit flag use, alias use, and invalid input handling.
5. Update [Commands](../reference/commands.md) or [Important Flags](../reference/important-flags.md) if the change is user-visible.

## Common Mistakes

- adding alias behavior in dispatch instead of the parser
- treating launcher and runtime commands as if they share the same prerequisites
- changing parser behavior without re-checking bootstrap-safe command rules
- burying CLI policy inside orchestrators
- documenting unsupported compatibility paths as if they were still a co-primary runtime
