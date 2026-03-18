# Getting Started

This guide is the fastest path to a first successful `envctl` run in a real repository.

If you already know the basics and just want repeatable command sequences, jump to [Common Workflows](common-workflows.md).

## Supported Today

`envctl` currently documents and supports:

- the Python runtime as the primary runtime path
- repositories with Python backends and JavaScript frontends
- worktree-based development driven by `todo/plans/...`
- built-in local service wiring for databases, Redis, Supabase, and n8n

If your repo fits that shape, the rest of this guide is the supported path.

## 1. Install

If `pipx` is not installed yet, follow the official pipx installation guide first:

- [pipx installation](https://pipx.pypa.io/stable/installation/)

Recommended end-user install:

```bash
pipx install "git+https://github.com/kfiramar/envctl.git"
pipx ensurepath
```

Why this is the default:

- installs `envctl` once for your user account
- keeps it available in every shell
- avoids mixing `envctl` itself into each target repo's virtualenv
- matches the supported user-facing install path across the docs

To verify installation:

```bash
envctl --version
envctl --help
envctl doctor --repo /absolute/path/to/repo
```

`envctl --version` is launcher-level, so it works before repo detection, `.envctl` bootstrap, or runtime startup.

Important notes:

- supported Python versions are 3.12 through 3.14
- `pipx` uses its own interpreter, not your currently activated virtualenv
- if `pipx` picks an unsupported interpreter, reinstall with `--python <supported-python>`

System tools you may also need at runtime:

- `git` for repository detection, worktrees, commits, reviews, and PR preparation
- `docker` for built-in local services such as databases, Redis, Supabase, and n8n
- `gh` for GitHub PR flows
- `poetry` for backend repositories that manage Python dependencies with Poetry
- one JavaScript package manager for frontend repos:
  - `bun`, `pnpm`, `yarn`, or `npm`, depending on the project

`envctl` bootstraps target-repo dependencies when needed, so `pytest` is usually provided by the backend project itself rather than installed separately for `envctl`.

`envctl` does not require every tool for every repo. The exact requirement depends on which workflows and services you actually use.

Contributor note:

- if you are developing `envctl` itself, use the editable install documented in [Contributing](../developer/contributing.md)
- source/editable install is not the primary end-user path

## 2. Pick a Repository

`envctl` operates on a git repository root.

You can:

- run inside any subdirectory of the repo and let `envctl` auto-detect it
- run from anywhere with `--repo /absolute/path/to/repo`

Examples:

```bash
cd /path/to/your-project
envctl
```

```bash
envctl --repo /absolute/path/to/your-projecl
```

## 3. Let envctl Create `.envctl`

Best default: let `envctl` bootstrap the repo-local `.envctl` for you.

If `.envctl` is missing and you run a normal operational command in an interactive terminal, `envctl` opens the setup wizard automatically.

Useful inspection commands before that first run:

```bash
envctl show-config --json
envctl explain-startup --json
```

Those commands tell you:

- where `envctl` expects the config file
- whether it already exists
- which defaults are active
- what startup decision the runtime would make

If you prefer manual setup, use the reference example in [`.envctl.example`](../reference/.envctl.example). For most users, the wizard is the right path.

## 4. First Interactive Run

Typical first-run path:

```bash
envctl --main
```

or, if you are starting from plans/worktrees:

```bash
envctl --plan
```

If `.envctl` is missing, the wizard opens and guides you through:

1. `Welcome / Source`
2. `Default Mode`
3. `Components`
4. optional `Long-Running Service`
5. `Directories`
6. `Ports`
7. `Review / Save`

The wizard:

- writes the repo-local `.envctl`
- validates directories and ports before save
- configures services and dependencies for `main` and `trees`
- seeds user-owned backend/frontend launch env sections into `.envctl`
- checks whether Git global excludes is configured for envctl-owned local artifacts
- does not change already running services until a later start or restart

Important: `envctl` no longer auto-edits the repository `.gitignore` for local workflow artifacts. Keep `.envctl`, `MAIN_TASK.md`, archived `OLD_TASK_*.md`, and envctl worktree roots out of `git status` by configuring Git `core.excludesFile` for your user account.

See [First-Run Wizard](first-run-wizard.md) for the full step-by-step guide.

## 5. First Successful Operating Loop

After config exists, this is the safest normal loop:

```bash
envctl show-config --json
envctl explain-startup --json
envctl
envctl dashboard
envctl logs --all --logs-follow
envctl test --all
envctl stop-all
```

Why this works well:

- `show-config` confirms the active config
- `explain-startup` shows what the runtime is about to do
- `--resume` is the fastest normal start path after previous runs
- `dashboard`, `logs`, and `test` cover the common daily loop
- `stop-all` gives you a clean shutdown

If you want a fresh start instead of resume:

```bash
envctl --main --no-resume
```

## 6. Worktree / Planning Flow

If your workflow centers on multiple implementations, start from plan files:

```bash
mkdir -p todo/plans/backend
cat > todo/plans/backend/checkout.md <<'PLAN'
# Checkout Implementation Plan
PLAN

envctl --plan
envctl dashboard
envctl test --all
```

Use this flow when you want:

- many worktrees running side by side
- safe port allocation across them
- isolated supporting services such as databases, Redis, Supabase, and n8n
- one place to compare logs, tests, and health

For more on planning layout and worktree flows, see [Planning and Worktrees](planning-and-worktrees.md).

## 7. Where to Go Next

- Need the exact wizard behavior: [First-Run Wizard](first-run-wizard.md)
- Want copy-pasteable day-to-day flows: [Common Workflows](common-workflows.md)
- Want command and flag reference: [Commands](../reference/commands.md)
- Need configuration details: [Configuration](../reference/configuration.md)
- Something is broken: [Troubleshooting](../operations/troubleshooting.md)
