# First-Run Wizard

This guide explains the setup wizard that appears when you run `envctl` in a repository without a local `.envctl`.

For most users, this is the right way to bootstrap the repo. It is safer and faster than writing config from scratch.

## When the Wizard Opens

The wizard opens when all of the following are true:

- you run a normal operational command such as `envctl --main`, `envctl --resume`, or `envctl --plan`
- the repository does not already have a local `.envctl`
- you are in a real interactive terminal

Inspection-only commands such as `envctl show-config --json` and `envctl explain-startup --json` do not open the wizard.

If there is no interactive TTY, `envctl` fails with a clear message instead of guessing configuration.

## What the Wizard Does

The wizard writes the managed startup configuration into the repo-local `.envctl`.

It is designed to:

- guide you through the minimum decisions needed for a good first run
- validate directories and ports before save
- configure services and dependencies for both `main` and `trees`
- seed user-owned launch env sections into `.envctl`
- leave already running services unchanged until a later start or restart

On save, `envctl` writes the repo-local `.envctl` and then checks whether your Git global excludes file is configured for envctl-managed local artifacts.

That global-ignore contract keeps files such as `.envctl`, `MAIN_TASK.md`, archived `OLD_TASK_*.md`, and envctl worktree roots like `trees/` or `trees-*` out of normal `git status` without mutating the repository's tracked `.gitignore`.

## The Actual Steps

The current wizard flow is:

1. `Welcome / Source`
2. `Default Mode`
3. `Components`
4. optional `Long-Running Service`
5. `Directories`
6. `Ports`
7. `Review / Save`

There is no simple/advanced split in the current UI.

## Step 1: Welcome / Source

This screen explains:

- where `.envctl` will be written
- which source is being used for prefill
- that existing services are not changed immediately

It is the orientation step before any config choices are made.

## Step 2: Default Mode

You choose the default run mode:

- `Main`
- `Trees`

This controls what happens when you run `envctl` without an explicit mode flag.

Use `Main` when your default workflow is one repo-local environment.

Use `Trees` when your default workflow is worktree-heavy and comparison-oriented.

## Step 3: Components

This is the main configuration screen.

It contains:

- a `Services` section
- a `Dependencies` section

Rows apply to `Main + Trees` together by default. That means one row can configure both modes at once until you decide they should differ.

Examples of rows:

- `Backend (Main + Trees)`
- `Frontend (Main + Trees)`
- `Postgres (Main + Trees)`
- `Redis (Main + Trees)`
- `Supabase (Main + Trees)`
- `n8n (Main + Trees)`

Important behavior:

- press `Space` to toggle the focused row
- press `D` to split the focused row into separate `Main` and `Trees` settings
- press `D` again on split rows to merge them back when values match

This is where you decide which services and dependencies `envctl` should manage.

## Step 4: Long-Running Service

This step appears only for backend-only projects.

It asks:

- whether `envctl` should keep that backend running automatically in `main` and `trees`
- whether `envctl` should wait for a listener/port before continuing in each mode

This exists because backend-only repos are not always long-running apps. Some are CLI or one-shot tooling repos and should not be auto-started.

For long-running scripts or workers that do not expose an API port, keep startup enabled but disable listener waiting. That lets `envctl` launch the process and continue straight to the dashboard/menu instead of waiting for port detection that will never succeed.

If your project has both backend and frontend, this screen is skipped.

## Step 5: Directories

This screen only shows the directories needed for the components currently configured in `main` or `trees`.

Possible fields:

- backend directory
- frontend directory

If a component is not configured, its directory field is not shown.

## Step 6: Ports

This screen only shows the canonical ports needed for the components currently configured in `main` or `trees`.

Ports are shown only when the selected startup configuration actually uses them. If a mode does not auto-start a service, or a backend is configured as a long-running non-listener task, that mode does not contribute port fields here.

Possible fields:

- backend base port
- frontend base port
- database base port
- Redis base port
- n8n base port
- port spacing

The wizard validates these before allowing save.

## Step 7: Review / Save

The final screen shows the managed `.envctl` block that will be written.

This is your last chance to confirm the exact saved values before the file is updated.

## Launch Env Sections

After the first save, `.envctl` also includes user-owned launch env sections like:

```dotenv
# >>> envctl backend launch env >>>
DATABASE_URL=${ENVCTL_SOURCE_DATABASE_URL}  # generic DB URL; e.g. postgresql://user:pass@host:5432/dbname
REDIS_URL=${ENVCTL_SOURCE_REDIS_URL}  # Redis URL; e.g. redis://host:6379/0
# <<< envctl backend launch env <<<

# >>> envctl frontend launch env >>>
# VITE_SUPABASE_URL=${ENVCTL_SOURCE_SUPABASE_URL}  # frontend-only Supabase URL
# <<< envctl frontend launch env <<<
```

These sections are not part of the wizard UI.

Edit them directly when you want to:

- rename emitted launch env vars
- add aliases
- remove defaults you do not want injected
- derive values from earlier lines with `${VAR}`
- scope vars to backend-only or frontend-only launches

`envctl config` seeds these sections when missing, then preserves them as-is.

## Validation Rules

The wizard/save path currently enforces these user-visible rules:

- default mode must be `main` or `trees`
- required directory fields must not be empty
- directory paths must exist and be directories
- ports must be positive integers
- a single mode cannot enable both PostgreSQL and Supabase at the same time

If save is blocked, the status line explains what to fix.

## Keyboard Behavior

Current wizard behavior:

- `Enter` moves to `Next` / `Save`
- `Space` toggles rows
- `D` splits or merges component rows
- `Left` / `Right` move between steps, except when a text input is focused
- inside text inputs, `Left` / `Right` move the cursor normally

## Related Guides

- [Getting Started](getting-started.md)
- [Configuration](../reference/configuration.md)
- [Common Workflows](common-workflows.md)
