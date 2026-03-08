# Python Engine Guide

This guide is for people using `envctl` day to day after the first install.

It focuses on the Python runtime that users actually operate: guided setup, inspection commands, start/resume behavior, runtime artifacts, and diagnostics.

## What Matters to Most Users

The Python runtime is the primary runtime behind `envctl`.

In practice, that means:

- first-run setup is guided through a config wizard
- inspection commands let you see what will happen before startup
- resume is state-aware and truth-aware
- diagnostics such as `--doctor`, `--debug-pack`, and `--debug-report` are part of the normal operating surface

Temporary fallback is still available:

```bash
ENVCTL_ENGINE_SHELL_FALLBACK=true envctl --resume
```

Use shell fallback only for parity debugging or emergency rollback. The legacy Bash/shell engine is deprecated, remains opt-in behind `ENVCTL_ENGINE_SHELL_FALLBACK=true`, and parts of the modern surface such as `debug-pack` are Python-runtime only. The current docs in this repository assume Python runtime behavior unless noted otherwise.

## First Run and Local Config

The Python runtime expects a repo-local `.envctl` file for normal operation.

Behavior on first run:

- If `.envctl` exists, runtime loads it.
- If `.envctl` is missing and the command is inspect-only (`--list-commands`, `--list-targets`, `--list-trees`, `show-config`, `show-state`, `explain-startup`), runtime continues with defaults.
- If `.envctl` is missing and you run a normal operational command, runtime opens the Textual config wizard and writes `.envctl`.
- If `.envctl` is missing and there is no interactive TTY, the runtime exits with an actionable error instead of guessing.

What the wizard actually covers:

1. welcome and source
2. default mode
3. main startup profile
4. trees startup profile
5. port defaults
6. review and save

Use [First-Run Wizard](first-run-wizard.md) if you want the guided setup story in detail.

Useful commands:

```bash
# Interactive editor / bootstrap
envctl config

# Headless config save from JSON
printf '%s\n' '{"default_mode":"trees"}' | envctl config --stdin-json

# Inspect the effective managed config without creating .envctl
envctl show-config --json
```

Notes:

- `.envctl` is for orchestration settings, not app secrets.
- Legacy config files such as `.envctl.sh` can still prefill the new config flow.
- The Python config layer now has canonical managed keys like `MAIN_POSTGRES_ENABLE` and `TREES_REDIS_ENABLE`, but older compatibility aliases such as `POSTGRES_MAIN_ENABLE` and `REDIS_MAIN_ENABLE` are still accepted.

## Startup Modes

`envctl` still centers around two runtime modes:

- `main`: operate on the repository root as one environment.
- `trees`: operate on planned or existing worktrees.

Mode selection order:

1. Explicit CLI mode flags win.
2. `ENVCTL_DEFAULT_MODE` from environment or `.envctl` fills in the default.
3. Built-in default is `main`.

Examples:

```bash
envctl --main
envctl --trees
envctl --resume
envctl --plan
```

`plan` always resolves into `trees` mode.

## Startup Selection and Inspection

These are the commands to use before you start anything.

```bash
envctl --list-commands
envctl --list-targets --json
envctl --list-trees --json
envctl show-config --json
envctl show-state --json
envctl explain-startup --json
```

What each one is for:

- `--list-commands`: prints the supported Python runtime command surface.
- `--list-targets --json`: shows discovered projects and the ports they would receive.
- `--list-trees --json`: same idea, but tree-focused.
- `show-config --json`: prints the effective managed config payload, source, and file path.
- `show-state --json`: prints the latest saved state pointer and state payload.
- `explain-startup --json`: explains what the runtime would do before you actually start anything.

`explain-startup` is especially useful because it tells you:

- selected mode
- whether interactive selection is required
- whether auto-resume would happen
- which services and built-in dependencies are enabled
- whether tree startup would run in parallel

## What Gets Written During a Run

The Python runtime writes scoped artifacts under:

```text
${RUN_SH_RUNTIME_DIR:-/tmp/envctl-runtime}/python-engine/<scope-id>/
```

Typical files:

- `run_state.json`: latest canonical state for the current scope
- `runtime_map.json`: project/service/URL projection
- `ports_manifest.json`: requested vs assigned vs final ports
- `error_report.json`: structured recent failures
- `events.jsonl`: structured runtime events
- `shell_ownership_snapshot.json`: latest shell migration ledger snapshot
- `shell_prune_report.json`: latest shell prune contract result
- `runs/<run-id>/...`: immutable per-run artifact set
- `debug/session-*/...`: debug flight recorder session data

The user-facing reason these files matter:

- `run_state.json` powers resume and state-aware commands
- `runtime_map.json` is the quickest machine-readable view of projects, ports, and URLs
- `error_report.json` and `events.jsonl` are the first places to look during triage

Important detail:

- The scope root is the authoritative Python runtime location.
- The runtime also maintains a compatibility view under the broader `python-engine` root so old consumers and migration tooling can still find expected files.

## Resume Behavior

Resume in Python runtime is stricter than the old shell path.

On `envctl --resume`, the runtime:

1. Loads the latest compatible state for the requested mode.
2. Reconciles saved services against live process/listener truth.
3. Optionally restores missing services.
4. Rewrites `run_state.json` and `runtime_map.json` with the reconciled result.

Useful inspection:

```bash
envctl show-state --json
envctl explain-startup --json
```

Useful behavior to know:

- Resume is blocked when strict cutover gates are not satisfied.
- Legacy shell state can still be read, but it is marked as legacy and handled more conservatively.
- If the runtime detects synthetic placeholder state in strict mode, commands such as `dashboard` and cutover diagnostics will fail loudly instead of pretending the run is healthy.

## Doctor and Diagnostics

There are two different "doctor" surfaces:

- `envctl doctor --repo /path`: launcher-level check that confirms repo and engine resolution.
- `envctl --doctor`: Python runtime diagnostics for the current repo and scope.

The runtime doctor surfaces:

- runtime paths
- active debug mode
- latest debug bundle
- parity manifest status
- shell ownership ledger status
- pointer and lock health
- synthetic-state detection
- recent structured failures

Examples:

```bash
# Launcher-level
envctl doctor --repo /absolute/path/to/repo

# Runtime-level
envctl --doctor
envctl --doctor --json
```

The runtime doctor is also where cutover gates show up. In practice, that means it will tell you whether:

- the Python parity manifest is complete
- runtime truth reconciliation is clean
- lifecycle expectations are satisfied
- shell prune budgets are within allowed limits

If you are trying to understand why the repo is still considered migration-gated, `envctl --doctor --json` is the command to start with.

## Debug Flight Recorder Workflow

The debug workflow is now centered on the Debug Flight Recorder (DFR).

Recommended workflow for interactive or startup issues:

```bash
# 1. Capture one session
ENVCTL_DEBUG_UI_MODE=deep envctl

# 2. Reproduce once, then exit

# 3. Package the session
envctl --debug-pack

# 4. Print a summarized diagnosis
envctl --debug-report

# 5. Print the last bundle path again later
envctl --debug-last
```

What `deep` mode adds:

- more UI/input events
- selector throughput diagnostics
- startup timing decomposition
- enough evidence to build `timeline.jsonl`, `command_index.json`, and anomaly summaries

Privacy defaults:

- command content is hashed instead of stored verbatim
- text payloads are scrubbed
- printable raw input capture stays disabled unless you explicitly opt in

Key environment controls:

- `ENVCTL_DEBUG_UI_MODE=off|standard|deep`
- `ENVCTL_DEBUG_AUTO_PACK=off|crash|anomaly|always`
- `ENVCTL_DEBUG_UI_BUNDLE_STRICT=true|false`
- `ENVCTL_DEBUG_UI_CAPTURE_PRINTABLE=true|false`
- `ENVCTL_DEBUG_UI_MAX_EVENTS=<n>`
- `ENVCTL_DEBUG_UI_RING_BYTES=<n>`
- `ENVCTL_DEBUG_UI_SAMPLE_RATE=<n>`

Useful bundle selectors:

```bash
envctl --debug-pack --session-id session-...
envctl --debug-pack --run-id run-...
envctl --debug-pack --scope-id repo-...
envctl --debug-pack --output-dir /tmp/envctl-bundles
envctl --debug-pack --debug-ui-include-doctor
```

Bundle contents usually include:

- `events.debug.jsonl`
- `events.runtime.redacted.jsonl`
- `timeline.jsonl`
- `anomalies.jsonl`
- `command_index.json`
- `diagnostics.json`
- `bundle_contract.json`
- `manifest.json`
- `summary.md`

For local offline analysis:

```bash
python3 scripts/analyze_debug_bundle.py /path/to/envctl-debug-bundle-....tar.gz
```

## Reading `debug-report`

`envctl --debug-report` first packages a bundle, then summarizes it.

The highest-signal fields are:

- `probable_root_causes`
- `next_data_needed`
- `spinner_disabled_reasons`
- `missing_spinner_lifecycle_transition`
- `startup_breakdown`
- `slowest_components`
- `resume_skip_reasons`
- `requirements_stage_hotspots`
- `service_bootstrap_hotspots`
- `service_attach_hotspots`

Interpretation tips:

- If `next_data_needed` is non-empty, capture again with `ENVCTL_DEBUG_UI_MODE=deep`.
- If `startup_breakdown.unknown_ratio` is high, the runtime still needs more timing coverage for that failure.
- If `spinner_disabled_reasons` contains only policy or TTY reasons, there may not be a spinner bug at all.
- If `resume_skip_reasons` is populated, the problem may be in resume eligibility rather than startup itself.

## Interactive UI Behavior

There are now two separate interactive concerns:

- dashboard backend
- target selector implementation

Current runtime behavior:

- `ENVCTL_UI_BACKEND=auto` keeps the legacy interactive dashboard by default.
- `ENVCTL_UI_EXPERIMENTAL_DASHBOARD=1` makes `auto` prefer the Textual dashboard when Textual is available.
- `ENVCTL_UI_BACKEND=textual` explicitly requests the Textual dashboard.
- `ENVCTL_UI_BACKEND=legacy` explicitly requests the legacy dashboard.
- `ENVCTL_UI_BACKEND=non_interactive` forces snapshot-only behavior.

Selector behavior is different:

- dashboard target selectors default to the Textual plan-style selector
- `ENVCTL_UI_SELECTOR_IMPL=planning_style` enables the prompt-toolkit rollback path
- `ENVCTL_UI_SELECTOR_IMPL=legacy` is only a compatibility alias and still resolves to the Textual selector path

This split is intentional: selectors have already moved further toward Textual than the dashboard loop itself.

## Recommended User Flows

### Headless start with inspection first

```bash
envctl show-config --json
envctl explain-startup --json
envctl --headless --resume
```

### Tree planning flow

```bash
envctl --list-trees --json
envctl --plan
envctl dashboard
envctl logs --all --logs-follow
envctl test --all
```

### Runtime triage flow

```bash
envctl show-state --json
envctl --doctor --json
envctl --debug-report
```

### Startup latency triage

```bash
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_RESTORE_TIMING=1 \
ENVCTL_DEBUG_REQUIREMENTS_TRACE=1 \
ENVCTL_DEBUG_DOCKER_COMMAND_TIMING=1 \
ENVCTL_DEBUG_STARTUP_BREAKDOWN=1 \
envctl --headless

envctl --debug-report
```

## Related Guides

- [First-Run Wizard](first-run-wizard.md)
- [Getting Started](getting-started.md)
- [Common Workflows](common-workflows.md)
- [Troubleshooting](../operations/troubleshooting.md)
