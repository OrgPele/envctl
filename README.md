# envctl

`envctl` is a global CLI for bringing up full local environments across a main repository and many worktrees in seconds.

It is optimized for high-throughput development and AI-assisted workflows: run multiple implementations in parallel, test everything, compare behavior quickly, and keep one deterministic command surface.

## Quick Start

```bash
# 1) Install envctl on your PATH
./bin/envctl install

# 2) Optional: add repo orchestration config
cp .envctl.example /path/to/your-project/.envctl

# 3) Start and operate
envctl --resume
envctl dashboard
envctl logs --all --logs-follow
envctl --debug-report
envctl test --all
envctl stop-all
```

## How to Use
Recommended flow:
1. Create plan files under `ENVCTL_PLANNING_DIR` (default: `docs/planning`).
2. Start with `envctl --plan`.
3. Use `envctl dashboard`, `envctl logs --all --logs-follow`, and `envctl test --all` to run and compare implementations.

Example:

```bash
# if ENVCTL_PLANNING_DIR is default:
mkdir -p docs/planning/backend
cat > docs/planning/backend/checkout.md <<'PLAN'
# Checkout Implementation Plan
PLAN

envctl --plan
```

## Documentation
- [Docs Index](docs/README.md)
- [Getting Started](docs/getting-started.md)
- [Important Flags](docs/important-flags.md)
- [Commands](docs/commands.md)
- [Configuration](docs/configuration.md)
- [Planning and Worktrees](docs/planning-and-worktrees.md)
- [AI Playbooks](docs/playbooks.md)
- [Architecture](docs/architecture.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Contributing](docs/contributing.md)
- [License](docs/license.md)

## Default Config
Use `.envctl.example` as a starting point:

- `ENVCTL_DEFAULT_MODE` controls startup default when no mode flag is passed (`main` or `trees`, default: `main`).
- `ENVCTL_PLANNING_DIR` controls where plan files are read from (default: `docs/planning`).
- Infra toggles support global/main/tree scopes for PostgreSQL/Supabase, Redis, and n8n.

## Debug Workflow
When interactive issues are hard to reproduce (input glitches, spinner drift, state mismatch):

```bash
# Deep capture for one session
ENVCTL_DEBUG_UI_MODE=deep envctl

# Optional: force spinner behavior while debugging TTY issues
ENVCTL_UI_SPINNER_MODE=on envctl

# Pack latest debug bundle
envctl --debug-pack

# Print triage summary from latest bundle
envctl --debug-report

# Print latest bundle path quickly
envctl --debug-last
```

By default debug capture is privacy-safe (hashed command content, no raw printable input unless explicitly enabled).

Deep-dive continuity doc for the paused Apple Terminal selector key-throughput bug:
- `docs/troubleshooting/interactive-selector-key-throughput-readme.md`

Startup-latency deep diagnostics:

```bash
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_RESTORE_TIMING=1 \
ENVCTL_DEBUG_REQUIREMENTS_TRACE=1 \
ENVCTL_DEBUG_DOCKER_COMMAND_TIMING=1 \
ENVCTL_DEBUG_STARTUP_BREAKDOWN=1 \
envctl --headless
envctl --debug-report
```

## Interactive UI Backend
Interactive backend is policy-driven:

- `ENVCTL_UI_BACKEND=auto` selects Textual interactive UI when available.
- `ENVCTL_UI_BACKEND=textual` forces Textual dashboard/selector UI.
- `ENVCTL_UI_BACKEND=legacy` is accepted for compatibility and maps to Textual with a deprecation event.
- `ENVCTL_UI_BACKEND=non_interactive` forces snapshot-only behavior.
- Target selector engine defaults to the Textual plan-style selector screen.
- `ENVCTL_UI_SELECTOR_IMPL=planning_style` enables prompt-toolkit cursor selector rollback.
- `ENVCTL_UI_SELECTOR_IMPL=legacy` remains a compatibility alias that maps to Textual selector mode.

---

`envctl` is a development control plane for running, testing, and comparing implementations at speed.
