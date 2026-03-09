# envctl

`envctl` is a global CLI for bringing up full local environments across a main repository and many worktrees in seconds.

It is optimized for high-throughput development and AI-assisted workflows: run multiple implementations in parallel, test everything, compare behavior quickly, and keep one deterministic command surface.

The Python engine is the primary runtime. A legacy Bash/shell engine still exists as an explicitly gated compatibility fallback during the migration/cutover window, but it is deprecated and should only be used for parity debugging or emergency rollback.

## Quick Start

```bash
# 1) Install envctl once so it is available in every shell
pipx install .
pipx ensurepath

# Or install for the current user
python -m pip install --user .

# 2) Go to a target repo
cd /path/to/your-project

# 3a) Start the main repo environment
#     If .envctl is missing, envctl opens the guided setup wizard
envctl --main

# 3b) Or create a plan and start a worktree-driven run
mkdir -p todo/plans/backend
cat > todo/plans/backend/checkout.md <<'PLAN'
# Checkout Implementation Plan
PLAN

envctl --plan
```

Repo-clone compatibility still exists:

```bash
./bin/envctl install
./bin/envctl uninstall
```

That wrapper path is now compatibility-only. The primary install story is a user- or system-level package install so `envctl` is on your `PATH` in every shell.

## What envctl Is For

`envctl` is built to:

- bring up a repo-local environment quickly
- run and compare multiple implementations or worktrees
- keep startup, logs, tests, and inspection behind one CLI
- support high-throughput human and AI-assisted development workflows

## Docs

Start here:

- [Documentation Hub](docs/README.md)
- [Getting Started](docs/user/getting-started.md)
- [First-Run Wizard](docs/user/first-run-wizard.md)
- [Common Workflows](docs/user/common-workflows.md)

User docs:

- [User Guides](docs/user/README.md)
- [Planning and Worktrees](docs/user/planning-and-worktrees.md)
- [Python Engine Guide](docs/user/python-engine-guide.md)
- [FAQ](docs/user/faq.md)

Reference:

- [Commands](docs/reference/commands.md)
- [Configuration](docs/reference/configuration.md)
- [Important Flags](docs/reference/important-flags.md)

Operations and troubleshooting:

- [Troubleshooting](docs/operations/troubleshooting.md)
- [Operations Index](docs/operations/README.md)

Developer docs:

- [Developer Guides](docs/developer/README.md)
- [Debug and Diagnostics](docs/developer/debug-and-diagnostics.md)
- [UI and Interaction Architecture](docs/developer/ui-and-interaction.md)
- [Python Runtime Guide](docs/developer/python-runtime-guide.md)

Project docs:

- [Planning and Roadmaps](todo/plans/README.md)
- [Changelog](docs/changelog/main_changelog.md)
- [License](docs/license.md)

## How to Use

Recommended flow:

1. Run `envctl --main` in your target repository for the normal repo-root environment.
2. If `.envctl` does not exist, complete the guided setup wizard.
3. Use `envctl --plan` when you want multiple implementations or worktrees side by side.
4. Follow the user guides for the normal operating loop after startup.

Example:

```bash
# if ENVCTL_PLANNING_DIR is default:
mkdir -p todo/plans/backend
cat > todo/plans/backend/checkout.md <<'PLAN'
# Checkout Implementation Plan
PLAN

envctl --plan
```

## Default Config
Use `.envctl.example` as a starting point:

- `ENVCTL_DEFAULT_MODE` controls startup default when no mode flag is passed (`main` or `trees`, default: `main`).
- `ENVCTL_PLANNING_DIR` controls where plan files are read from (default: `todo/plans`).
- Infra toggles support global/main/tree scopes for PostgreSQL/Supabase, Redis, and n8n.
- `ENVCTL_ENGINE_SHELL_FALLBACK=true` still forces the deprecated legacy shell engine when you need an explicit compatibility escape hatch.

---

`envctl` is a development control plane for running, testing, and comparing implementations at speed.
