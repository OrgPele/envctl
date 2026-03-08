# First-Run Wizard

This guide explains the startup wizard that appears the first time you run `envctl` in a repository without a local `.envctl`.

For most users, this wizard is the right way to get started. It is faster and safer than hand-writing config from scratch.

## When the Wizard Opens

The wizard opens when all of the following are true:

- you run a normal operational command such as `envctl --resume`, `envctl --main`, or `envctl --plan`
- the repository does not already have a local `.envctl`
- you are in a real interactive terminal

If you only run inspection commands such as `envctl show-config --json` or `envctl explain-startup --json`, the wizard does not open.

If there is no interactive TTY, `envctl` fails with a clear message instead of guessing a config.

## What the Wizard Does

The wizard writes a managed startup config to the repo-local `.envctl`.

It is designed to:

- guide you through the minimum choices needed for a good first run
- prefill from existing config when possible
- validate values before saving
- keep running services unchanged until your next start or restart

On save, `envctl` also tries to add `.envctl` to `.git/info/exclude` so your local orchestration config stays untracked.

## The Actual Steps

The current wizard flow in code is:

1. `Welcome / Source`
2. `Default Mode`
3. `Main Startup Profile`
4. `Trees Startup Profile`
5. `Port Defaults`
6. `Review / Save`

That means the wizard is not a generic form. It is opinionated around how `envctl` is actually used.

## Step 1: Welcome / Source

The first screen tells you:

- where `.envctl` will be written
- whether values are starting from defaults, an existing `.envctl`, or a legacy config import
- that CLI and environment overrides still apply on top
- that saving does not change already-running services immediately

If you are migrating from older repo config, this screen is where `envctl` makes that prefill behavior explicit.

## Step 2: Default Mode

You choose the default startup mode:

- `Main`
- `Trees`

Use `Main` when your normal workflow is one repo root environment.

Use `Trees` when your normal workflow is worktree-heavy and comparison-oriented.

This setting controls what happens when you run `envctl` without explicitly passing a mode flag.

## Step 3: Main Startup Profile

This screen toggles what `envctl` should start in main mode.

Current toggle categories come directly from the runtime:

- backend
- frontend
- PostgreSQL
- Redis
- Supabase
- n8n

Use this screen to decide what a normal repo-root run should bring up by default.

## Step 4: Trees Startup Profile

This is the same idea as the main profile, but for worktree runs.

This matters because many teams want different defaults in tree mode than in main mode. For example:

- lighter main-mode defaults for local work
- fuller tree-mode defaults for side-by-side comparison

## Step 5: Port Defaults

This screen lets you set:

- backend directory
- frontend directory
- backend base port
- frontend base port
- dependency base ports
- port spacing

The wizard validates this step before letting you continue.

In practice, this is where you fix most first-run conflicts if your repo does not use the common `backend` / `frontend` layout or standard ports.

## Step 6: Review / Save

The final screen shows the managed config block that will be written.

It also reminds you that:

- CLI and environment overrides still apply above the file
- `.envctl` will be ignored through `.git/info/exclude` when possible

This is the last chance to confirm the exact saved values before the file is written.

## Built-In Validation Rules

The wizard and save path currently enforce a few important rules:

- default mode must be `main` or `trees`
- backend and frontend directory names must not be empty
- ports must be positive integers
- each mode must enable at least one component
- a single mode cannot enable both PostgreSQL and Supabase at the same time

If save is blocked, the status line in the wizard tells you what to fix.

## Best Practice

For a clean first run:

```bash
envctl show-config --json
envctl --resume
```

If `.envctl` does not exist yet, the second command opens the wizard and guides you through setup.

After saving, continue with:

```bash
envctl explain-startup --json
envctl dashboard
```

## When to Skip the Wizard

You may want to skip the interactive wizard when:

- you are automating setup in scripts
- you already know the exact config shape you want
- you are editing config over SSH or in a non-interactive environment

In those cases, use:

- `.envctl.example` as a starting point
- `envctl config --stdin-json`
- `envctl config --set KEY=VALUE`

## Related Guides

- [Getting Started](getting-started.md)
- [Common Workflows](common-workflows.md)
- [Python Engine Guide](python-engine-guide.md)
- [Configuration Reference](../reference/configuration.md)
