# Common Workflows

This guide is the fastest way to get real work done with `envctl`.

Use it when you already understand the basics and want copy-pasteable, task-oriented flows.

## Before You Start

These examples assume:

- `envctl` is on your `PATH`
- you are inside the target repository, or you are passing `--repo /path/to/repo`
- the repository has a repo-local `.envctl`, or you are willing to let `envctl config` create one
- if `.envctl` is missing and you run an operational command interactively, the first-run wizard will guide setup

If you are starting from zero, read [Getting Started](getting-started.md) first.

## Quickest Daily Start

Use this when you want the fastest normal development loop.

```bash
envctl show-config --json
envctl explain-startup --json
envctl --resume
envctl dashboard
```

Why this works well:

- `show-config` confirms you are operating on the config you expect
- `explain-startup` shows what the runtime is about to do
- `--resume` reuses the latest good state when possible
- `dashboard` gives you one place to inspect the result

## Start Fresh Instead of Resuming

Use this when the previous run is stale, surprising, or irrelevant.

```bash
envctl --main --no-resume
envctl dashboard
```

If you want a full clean stop first:

```bash
envctl stop-all
envctl --main --no-resume
```

## Worktree Planning Loop

Use this when you want multiple implementations running side by side.

```bash
mkdir -p docs/planning/backend
cat > docs/planning/backend/checkout.md <<'PLAN'
# Checkout Implementation Plan
PLAN

envctl --plan
envctl dashboard
envctl logs --all --logs-follow
envctl test --all
```

Good follow-up commands:

- `envctl --list-trees --json`
- `envctl errors --all`
- `envctl restart --project <tree-name>`

## Headless / Automation Flow

Use this in scripts, CI, or agent-driven workflows.

```bash
envctl show-config --json
envctl explain-startup --json
envctl --headless --resume
envctl test --all --skip-startup --load-state
```

Why this is the preferred automation shape:

- inspection commands fail earlier and more clearly than a blind startup
- `--headless` removes interactive prompts
- `--skip-startup --load-state` keeps repeated test runs fast

## One Project Tight Loop

Use this when you only care about one service or one project.

```bash
envctl test --project api
envctl logs --project api --logs-follow
envctl restart --project api
```

Good variants:

```bash
envctl health --project api
envctl errors --project api
envctl logs --project api --logs-tail 200
```

## Compare Multiple Implementations

Use this after a `--plan` run or any trees-mode session.

```bash
envctl test --all
envctl errors --all
envctl logs --all --logs-tail 300
```

When the goal is comparison rather than deep debugging, this is usually enough:

- `test --all` for pass/fail differences
- `errors --all` for quick failure triage
- `logs --all --logs-tail 300` for a compact comparison sample

## Inspect Before You Change Anything

Use this when you are not sure what `envctl` will do.

```bash
envctl --list-commands
envctl --list-targets --json
envctl show-config --json
envctl show-state --json
envctl explain-startup --json
```

This is especially useful:

- before first use in an unfamiliar repo
- after config changes
- before CI or agent automation
- when debugging resume surprises

## Debug a Bad Interactive Session

Use this when the issue is in the dashboard, selector, spinner, or input flow.

```bash
ENVCTL_DEBUG_UI_MODE=deep envctl

# reproduce once, then exit

envctl --debug-pack
envctl --debug-report
envctl --debug-last
```

If you are sharing findings with someone else, send:

- the `--debug-report` output
- the bundle path from `--debug-last`

## Debug Slow Startup

Use this when startup feels unusually slow and you need timing evidence.

```bash
ENVCTL_DEBUG_UI_MODE=deep \
ENVCTL_DEBUG_RESTORE_TIMING=1 \
ENVCTL_DEBUG_REQUIREMENTS_TRACE=1 \
ENVCTL_DEBUG_DOCKER_COMMAND_TIMING=1 \
ENVCTL_DEBUG_STARTUP_BREAKDOWN=1 \
envctl --headless

envctl --debug-report
```

Look for:

- `slowest_components`
- `startup_breakdown`
- `requirements_stage_hotspots`

## Force the Deprecated Shell Fallback

Use this only when you are isolating a parity issue or need an emergency rollback during cutover.

```bash
ENVCTL_ENGINE_SHELL_FALLBACK=true envctl --resume
```

Important:

- this is a deprecated compatibility path
- modern diagnostics such as `debug-pack` are Python-runtime features
- switch back to Python mode before filing or analyzing new runtime bugs

## Multi-Repo Control

Use this when you are operating several repositories from one shell session.

```bash
envctl --repo ~/projects/service-a --resume
envctl --repo ~/projects/service-b --resume
envctl --repo ~/projects/service-c --resume
```

Inspection variants:

```bash
envctl --repo ~/projects/service-a show-config --json
envctl --repo ~/projects/service-b explain-startup --json
```

## Which Guide Next?

- Use [First-Run Wizard](first-run-wizard.md) if guided setup is the part you still need.
- Use [Planning and Worktrees](planning-and-worktrees.md) when worktree selection or plan-file layout is the hard part.
- Use [Python Engine Guide](python-engine-guide.md) when you need a deeper explanation of runtime behavior, artifacts, and diagnostics.
- Use [Operations](../operations/README.md) when you are already in troubleshooting mode.
