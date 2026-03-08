# envctl

`envctl` is a global CLI for bringing up full local environments across a main repository and many worktrees in seconds.

It is optimized for high-throughput development and AI-assisted workflows: run multiple implementations in parallel, test everything, compare behavior quickly, and keep one deterministic command surface.

The Python engine is the primary runtime. A legacy Bash/shell engine still exists as an explicitly gated compatibility fallback during the migration/cutover window, but it is deprecated and should only be used for parity debugging or emergency rollback.

## Quick Start

```bash
# 1) Install envctl on your PATH
./bin/envctl install

# 2) Create repo orchestration config now, or let `envctl config`
#    bootstrap it on the first operational run
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
- [Documentation Hub](docs/README.md)
- [User Guides](docs/user/README.md)
- [Getting Started](docs/user/getting-started.md)
- [Common Workflows](docs/user/common-workflows.md)
- [FAQ](docs/user/faq.md)
- [Reference](docs/reference/README.md)
- [Developer Guides](docs/developer/README.md)
- [Operations](docs/operations/README.md)
- [Planning and Roadmaps](docs/planning/README.md)
- [Changelog](docs/changelog/main_changelog.md)
- [License](docs/license.md)

## Default Config
Use `.envctl.example` as a starting point:

- `ENVCTL_DEFAULT_MODE` controls startup default when no mode flag is passed (`main` or `trees`, default: `main`).
- `ENVCTL_PLANNING_DIR` controls where plan files are read from (default: `docs/planning`).
- Infra toggles support global/main/tree scopes for PostgreSQL/Supabase, Redis, and n8n.
- `ENVCTL_ENGINE_SHELL_FALLBACK=true` still forces the deprecated legacy shell engine when you need an explicit compatibility escape hatch.

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

- `ENVCTL_UI_BACKEND=auto` keeps the legacy interactive dashboard by default.
- `ENVCTL_UI_EXPERIMENTAL_DASHBOARD=1` makes `auto` prefer the Textual dashboard when Textual is available.
- `ENVCTL_UI_BACKEND=textual` requests the Textual dashboard; if Textual is unavailable the runtime falls back to the legacy dashboard instead of failing closed.
- `ENVCTL_UI_BACKEND=legacy` forces the legacy interactive dashboard.
- `ENVCTL_UI_BACKEND=non_interactive` forces snapshot-only behavior.
- Target selector menus default to the Textual plan-style selector screen even when the dashboard backend is still legacy.
- `ENVCTL_UI_SELECTOR_IMPL=planning_style` enables prompt-toolkit cursor selector rollback.
- `ENVCTL_UI_SELECTOR_IMPL=legacy` remains a compatibility alias that maps to the Textual selector mode.

---

`envctl` is a development control plane for running, testing, and comparing implementations at speed.
