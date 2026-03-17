# Python Engine Guide

This guide explains the runtime users actually operate day to day: startup, resume, inspection commands, artifacts, diagnostics, and the current interactive UI surface.

## Runtime Overview

Current supported stack for this guide:

- Python runtime only
- Python backends and JavaScript frontends
- built-in local service wiring for databases, Redis, Supabase, and n8n
- worktree orchestration from `todo/plans/...`

The supported runtime path is the Python runtime.

In practice, that means:

- first-run setup happens through the config wizard
- inspection commands show what the runtime will do before startup
- resume is saved-state-aware and live-truth-aware
- diagnostics such as `--doctor`, `--debug-pack`, and `--debug-report` are part of the normal surface

## First Run and Local Config

The Python runtime expects a repo-local `.envctl` for normal operational commands.

Behavior:

- if `.envctl` exists, runtime loads it
- if `.envctl` is missing and the command is inspect-only or utility-safe, runtime continues with defaults
- if `.envctl` is missing and you run a normal operational command interactively, runtime opens the setup wizard and writes `.envctl`
- if `.envctl` is missing and there is no interactive TTY, runtime exits with a clear error instead of guessing

The `.envctl` file remains repo-local. Envctl-owned local workflow artifacts such as `.envctl`, `MAIN_TASK.md`, archived `OLD_TASK_*.md`, and envctl worktree roots are expected to be ignored through Git global excludes, not by auto-editing the repository `.gitignore`.

Useful commands:

```bash
envctl config
envctl show-config --json
printf '%s\n' '{"default_mode":"trees"}' | envctl config --stdin-json
```

The current wizard flow is:

1. `Welcome / Source`
2. `Default Mode`
3. `Components`
4. optional `Long-Running Service`
5. `Directories`
6. `Ports`
7. `Review / Save`

For the full setup story, see [First-Run Wizard](first-run-wizard.md).

## Startup Modes

`envctl` has two runtime modes:

- `main`: operate on the repository root as one environment
- `trees`: operate on planned or existing worktrees

Mode selection order:

1. explicit CLI mode flags
2. `ENVCTL_DEFAULT_MODE` from environment or `.envctl`
3. built-in default `main`

Examples:

```bash
envctl --main
envctl --trees
envctl --resume
envctl --plan
```

`plan` always resolves into `trees` mode.

## Inspection Commands

These commands are safe to run before startup:

```bash
envctl list-commands
envctl list-targets --json
envctl list-trees --json
envctl show-config --json
envctl show-state --json
envctl explain-startup --json
envctl install-prompts --cli codex --dry-run
```

What they are for:

- `list-commands`: show the supported runtime command surface
- `list-targets --json`: show discovered projects and targetable scopes
- `list-trees --json`: show discovered worktrees / planning targets
- `show-config --json`: print effective config source and values
- `show-state --json`: print the latest saved runtime state
- `explain-startup --json`: show what startup would do before anything runs
- `install-prompts --cli ...`: install built-in AI prompt presets without requiring a startup run

Compatibility note:

- `list-commands`, `list-targets`, and `list-trees` still accept the older `--list-*` flag spellings

## Runtime Artifacts

The runtime writes scoped artifacts under:

```text
${RUN_SH_RUNTIME_DIR:-/tmp/envctl-runtime}/python-engine/<scope-id>/
```

Common files:

- `run_state.json`
- `runtime_map.json`
- `ports_manifest.json`
- `error_report.json`
- `events.jsonl`
- `runs/<run-id>/...`
- `debug/session-*/...`

User-facing meaning:

- `run_state.json` powers resume and state-aware commands
- `runtime_map.json` is the quickest machine-readable map of projects, services, ports, and URLs
- `error_report.json` and `events.jsonl` are the first places to look during triage
- `runs/<run-id>/...` contains immutable per-run logs, test artifacts, summaries, and debug evidence

## Resume Behavior

On `envctl --resume`, the runtime:

1. loads the latest compatible saved state
2. reconciles saved services against live process/listener truth
3. optionally restores missing services
4. rewrites the state with the reconciled result

Useful inspection:

```bash
envctl show-state --json
envctl explain-startup --json
```

## Doctor and Diagnostics

There are two different doctor surfaces:

- `envctl doctor --repo /path`: installed-command verification for a target repo
- `envctl --doctor`: runtime diagnostics for the current repo and scope

Examples:

```bash
envctl doctor --repo /absolute/path/to/repo
envctl --doctor
envctl --doctor --json
```

The runtime doctor surfaces state, runtime health, pointers, readiness, and recent structured failures.

## User-Level Debug Workflow

Start with:

```bash
envctl show-config --json
envctl show-state --json
envctl explain-startup --json
envctl --doctor --json
```

If the issue is interactive, timing-related, or hard to reproduce:

```bash
ENVCTL_DEBUG_UI_MODE=deep envctl
envctl --debug-pack
envctl --debug-report
envctl --debug-last
```

That usually answers:

- what config is active
- what startup decision `envctl` is making
- what state was saved
- whether doctor already sees pointer or runtime-health problems
- where the latest debug bundle lives

## Interactive UI Behavior

There are two different interactive concerns:

- dashboard backend
- selector implementation

Current behavior:

- `ENVCTL_UI_BACKEND=auto` keeps the legacy interactive dashboard by default
- `ENVCTL_UI_EXPERIMENTAL_DASHBOARD=1` makes `auto` prefer the Textual dashboard when available
- `ENVCTL_UI_BACKEND=textual` explicitly requests the Textual dashboard
- `ENVCTL_UI_BACKEND=legacy` explicitly requests the legacy dashboard
- `ENVCTL_UI_BACKEND=non_interactive` forces snapshot-only behavior

Selector behavior is separate:

- dashboard target selectors default to the Textual selector
- `ENVCTL_UI_SELECTOR_IMPL=planning_style` enables the prompt-toolkit fallback path
- `ENVCTL_UI_SELECTOR_IMPL=legacy` is only a compatibility alias and still resolves to the Textual selector path

## Failed-Only Test Reruns

`envctl test --failed` reruns only the saved failed tests/files for the selected targets.

Behavior:

- backend reruns use saved exact test identifiers when the runtime could extract them
- frontend reruns use saved failed files
- reruns fail closed if the saved git state is stale
- if the prior full run failed before envctl could derive rerunnable selectors, the rerun path explains that instead of pretending no full run occurred

Useful forms:

```bash
envctl test --failed
envctl test --failed --skip-startup --load-state
```

## Recommended Flows

Headless start with inspection first:

```bash
envctl show-config --json
envctl explain-startup --json
envctl --headless --resume
```

Tree planning flow:

```bash
envctl --list-trees --json
envctl --plan
envctl dashboard
envctl logs --all --logs-follow
envctl test --all
```

Runtime triage flow:

```bash
envctl show-state --json
envctl --doctor --json
envctl --debug-report
```

## Related Guides

- [Getting Started](getting-started.md)
- [Common Workflows](common-workflows.md)
- [Planning and Worktrees](planning-and-worktrees.md)
- [Troubleshooting](../operations/troubleshooting.md)
