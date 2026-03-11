# envctl

`envctl` is a global CLI for bringing up full local environments across a main repository and many worktrees in seconds.

# envctl

`envctl` is a global CLI for spinning up isolated local environments for a repo and many worktrees, complete with their databases and dependencies, in seconds.

Vibe coding falls apart fast once you are no longer working on just one branch at a time. As soon as multiple implementations are running in parallel, local setup becomes the bottleneck: ports collide, services point at the wrong database, logs blur together, and one worktree can interfere with another.

`envctl` fixes that by managing runtime state per worktree. It gives each environment isolated ports, correct service wiring, and a single command surface for the workflows that matter: starting and restarting services, running tests in parellel, monitoring logs and health, inspecting errors, AI reviewes, and shutting everything down cleanly.

## Quick Start

```bash
# 1) Install envctl once so it is available in every shell
pipx install "git+https://github.com/kfiramar/envctl.git"
pipx ensurepath

# Or install for the current user
python -m pip install --user "git+https://github.com/kfiramar/envctl.git"

# 2) Go to a target repo
cd /path/to/your-project

# 3a) Start the main repo environment
#     Use this when you want one repo-local environment.
#     If .envctl is missing, envctl opens the guided setup wizard.
envctl --main
# 3b) Or work from plans and let envctl manage worktrees for you
#     Use this when you want parallel implementations side by side.
mkdir -p todo/plans/backend
cat > todo/plans/backend/checkout.md <<'PLAN'
# Checkout Implementation Plan
PLAN

envctl --plan
```

That first interactive run is the normal setup path. The wizard writes the repo-local `.envctl` for you, whether you start in `main` mode or jump straight into plan-driven trees.

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
- [Changelog](docs/changelog/README.md)
- [License](docs/license.md)

## Configuration

`envctl` writes and maintains a repo-local `.envctl`.

- On first interactive use, the setup wizard creates it for you.
- Later, run `envctl config` to reopen the wizard and edit it safely.
- [`docs/reference/.envctl.example`](docs/reference/.envctl.example) is the reference file for managed keys and defaults, not the primary onboarding flow.

Common settings:

- `ENVCTL_DEFAULT_MODE` controls the default mode when no mode flag is passed (`main` or `trees`, default: `main`).
- `ENVCTL_PLANNING_DIR` controls where plan files are read from (default: `todo/plans`).
- Per-mode toggles control whether backend/frontend/dependencies are managed in `main` and `trees`.
- `envctl` now runs through the Python runtime path by default and in supported configurations.

---

`envctl` is a development control plane for running, testing, and comparing implementations at speed.
