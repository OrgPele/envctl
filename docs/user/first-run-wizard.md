# First-Run Wizard

This guide explains the run-configuration wizard that appears the first time you run `envctl` in a repository without a local `.envctl`.

For most users, this wizard is the right way to get started. It is faster and safer than hand-writing config from scratch.

## When the Wizard Opens

The wizard opens when all of the following are true:

- you run a normal operational command such as `envctl --resume`, `envctl --main`, or `envctl --plan`
- the repository does not already have a local `.envctl`
- you are in a real interactive terminal

If you only run inspection commands such as `envctl show-config --json` or `envctl explain-startup --json`, the wizard does not open.

If there is no interactive TTY, `envctl` fails with a clear message instead of guessing a config.

## What the Wizard Does

The wizard writes a managed run config to the repo-local `.envctl`.

It is designed to:

- guide you through the minimum choices needed for a good first run
- prefill from existing config when possible
- validate values before saving
- keep running services unchanged until your next start or restart

On save, `envctl` also tries to add `.envctl` and `trees/` to the repo `.gitignore` so local orchestration config and generated worktrees stay untracked.

## The Actual Steps

The wizard now has two flows:

### Simple Wizard

Used by default during first-run bootstrap.

1. `Welcome / Source`
2. `Wizard Type`
3. `Default Mode`
4. `Main Run Preset`
5. `Trees Run Preset`
6. `Review / Save`

### Advanced Wizard

Used by default when you open `envctl config` to edit an existing `.envctl`.

1. `Welcome / Source`
2. `Wizard Type`
3. `Default Mode`
4. `Run Enablement`
5. `Main Run Settings`
6. `Trees Run Settings`
7. `Directories`
8. `Ports`
9. `Review / Save`

That means the wizard is still opinionated around how `envctl` is actually used, but the first-run path is now shorter.

## Step 1: Welcome / Source

The first screen tells you:

- where `.envctl` will be written
- whether values are starting from defaults, an existing `.envctl`, or a legacy config import
- that CLI and environment overrides still apply on top
- that saving does not change already-running services immediately

If you are migrating from older repo config, this screen is where `envctl` makes that prefill behavior explicit.

## Step 2: Wizard Type

You choose between:

- `Simple`
- `Advanced`

Simple is the onboarding path.

Advanced exposes run enablement, the full per-mode run profile, directory configuration, and port configuration.

## Step 3: Default Mode

You choose the default run mode:

- `Main`
- `Trees`

Use `Main` when your normal workflow is one repo root environment.

Use `Trees` when your normal workflow is worktree-heavy and comparison-oriented.

This setting controls what happens when you run `envctl` without explicitly passing a mode flag.

## Step 4: Main Run Preset or Run Enablement

In the simple wizard, main mode is configured by preset:

- `Standard`: envctl runs enabled, backend on, frontend on, dependency defaults for main mode
- `Apps Only`: envctl runs enabled, backend on, frontend on, built-in dependencies off
- `Disabled`: envctl runs disabled for main mode

In the advanced wizard, this step is separate and only controls whether each mode is enabled for `envctl` runs:

- `Main: Enabled for envctl runs`
- `Trees: Enabled for envctl runs`

The detailed backend, frontend, and dependency toggles come later.

In the simple wizard, step 5 is `Trees Run Preset`.

In the advanced wizard, step 5 is `Main Run Settings`.

Trees mode works the same way as main mode in the simple flow, but it is configured independently.

In the advanced wizard, the next screen is `Main Run Settings`, which exposes:

- `Backend`
- `Frontend`
- built-in dependency toggles

Those toggles define what main mode should run when envctl runs are enabled.

## Step 6: Trees Run Settings

The advanced `Trees Run Settings` screen works the same way as main mode, but it is configured independently.

This matters because many teams want different defaults in tree mode than in main mode. For example:

- lighter main-mode defaults for local work
- fuller tree-mode defaults for side-by-side comparison

When envctl runs are disabled in the earlier `Run Enablement` step, these detailed toggles stay editable so you can stage future settings without enabling the mode yet.

## Step 7: Directories

This step appears only in the advanced wizard.

This screen only shows the directories that matter for components currently enabled for envctl runs:

- backend directory
- frontend directory

If you disabled frontend everywhere, you will not be prompted for a frontend directory.

## Step 8: Ports

This step appears only in the advanced wizard.

This screen only shows the port fields that matter for components currently enabled for envctl runs:

- backend base port
- frontend base port
- dependency base ports
- port spacing

The wizard validates this step before letting you continue.

In practice, this is where you fix most first-run conflicts if your repo does not use the common `backend` / `frontend` layout or standard ports.

## Step 9: Review / Save

The final screen shows the managed config block that will be written.

It also reminds you that:

- CLI and environment overrides still apply above the file
- `.envctl` and `trees/` will be added to `.gitignore` when possible

This is the last chance to confirm the exact saved values before the file is written.

## Built-In Validation Rules

The wizard and save path currently enforce a few important rules:

- default mode must be `main` or `trees`
- backend and frontend directory names must not be empty
- ports must be positive integers
- each mode enabled for envctl runs must enable at least one component
- a single mode cannot enable both PostgreSQL and Supabase at the same time

If save is blocked, the status line in the wizard tells you what to fix.

## Disabled Modes

Each mode now has a master switch for envctl runs:

- `MAIN_STARTUP_ENABLE`
- `TREES_STARTUP_ENABLE`

If a mode is disabled:

- `show-config --json` still reports its saved detailed settings
- `explain-startup --json` reports `startup_enabled: false`
- `start`, `resume`, and `restart` for that mode are blocked until you re-enable that mode for envctl runs

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
