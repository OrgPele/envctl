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

If you only need part of the runtime while testing:

```bash
envctl --backend --headless          # backend service plus dependencies
envctl --frontend --headless         # frontend service plus dependencies
envctl --fullstack --headless        # backend + frontend plus dependencies
envctl --dependencies --headless     # DB/Redis/etc. only
envctl --entire-system --headless    # all dependencies and configured app services
envctl --trees --only-backend         # worktree backend only; skip frontend and dependencies
envctl --trees --no-deps             # worktree app services only; skip managed dependencies/prep
envctl --trees --no-infra            # worktree state/AI only; skip backend, frontend, and dependencies

envctl stop --backend --headless
envctl stop --frontend --headless
envctl stop --dependencies --headless
envctl stop --entire-system --headless
envctl kill-all --headless
```

When you invoke a specific action command directly, envctl stays non-interactive by default.
For example, `envctl kill-all`, `envctl pr`, `envctl test`, `envctl logs`, and `envctl migrate`
behave like their `--headless` forms. Add `--interactive` only when you want envctl to prompt
for targets or dashboard-style choices.

## Worktree Planning Loop

Use this when you want multiple implementations running side by side.

```bash
mkdir -p todo/plans/backend
cat > todo/plans/backend/checkout.md <<'PLAN'
# Checkout Implementation Plan
PLAN

envctl --plan
envctl dashboard
envctl logs --all --logs-follow
envctl test --all
envctl test --failed
```

Good follow-up commands:

- `envctl --list-trees --json`
- `envctl errors --all`
- `envctl restart --project <tree-name>`

## Supabase Auth E2E Users

Use this when browser/API tests need to sign in through real Supabase Auth instead of creating rows directly in Postgres.

```dotenv
MAIN_SUPABASE_ENABLE=true
ENVCTL_SUPABASE_AUTH_USERS=e2e
ENVCTL_SUPABASE_USER_E2E_EMAIL=e2e@example.test
ENVCTL_SUPABASE_USER_E2E_PASSWORD=change-me-local-only

# >>> envctl backend launch env >>>
SUPABASE_URL=${ENVCTL_SOURCE_SUPABASE_URL}
SUPABASE_JWKS_URL=${ENVCTL_SOURCE_SUPABASE_JWKS_URL}
SUPABASE_SERVICE_ROLE_KEY=${ENVCTL_SOURCE_SUPABASE_SERVICE_ROLE_KEY}
# <<< envctl backend launch env <<<

# >>> envctl frontend launch env >>>
VITE_SUPABASE_URL=${ENVCTL_SOURCE_SUPABASE_URL}
VITE_SUPABASE_ANON_KEY=${ENVCTL_SOURCE_SUPABASE_ANON_KEY}
# <<< envctl frontend launch env <<<
```

Then start and test:

```bash
envctl --entire-system --headless
envctl supabase-user list --json
```

After startup sync, launch-env templates can use `ENVCTL_SOURCE_SUPABASE_TEST_USER_EMAIL`, `ENVCTL_SOURCE_SUPABASE_TEST_USER_PASSWORD`, and `ENVCTL_SOURCE_SUPABASE_TEST_USER_ID` for E2E runner commands or backend-only test services. Do not map the service-role key into frontend launch env.

## Headless / Automation Flow

Use this in scripts, CI, or agent-driven workflows.

```bash
envctl show-config --json
envctl explain-startup --json
envctl --headless --resume
envctl test --all --skip-startup --load-state
envctl test --failed --skip-startup --load-state
```

Why this is the preferred automation shape:

- inspection commands fail earlier and more clearly than a blind startup
- `--headless` removes interactive prompts
- `--skip-startup --load-state` keeps repeated test runs fast

### Optional PR label during `envctl ship`

Repos that want shipped PRs labeled can opt in from `.envctl`:

```dotenv
ENVCTL_SHIP_PR_LABEL_ENABLE=true
ENVCTL_SHIP_PR_LABEL=deploy-app
```

When enabled, `envctl ship` ensures the label exists in GitHub and applies it
programmatically after it has a PR URL. The feature is disabled by default.

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
envctl test --failed
envctl errors --all
envctl logs --all --logs-tail 300
```

When the goal is comparison rather than deep debugging, this is usually enough:

- `test --all` for pass/fail differences
- `test --failed` for quick follow-up reruns after a full suite has already persisted failures
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

## Run the Same System in Docker

Use `--docker` to preserve envctl's main/trees, selective-service, dependency, dashboard, health,
logs, restart, and stop workflows while replacing app host processes with managed containers:

```bash
envctl start --main --entire-system --docker --headless
envctl start --trees --entire-system --isolated-deps --docker --headless
```

If a service directory contains a `Dockerfile`, envctl builds it with Docker's layer cache. Otherwise,
configure an existing image with `ENVCTL_BACKEND_DOCKER_IMAGE`, `ENVCTL_FRONTEND_DOCKER_IMAGE`, or
the corresponding prefix for an additional app service. Production-oriented images commonly need
`ENVCTL_<SERVICE>_DOCKER_COMMAND` and `ENVCTL_<SERVICE>_DOCKER_PORT` so the service listens on
`0.0.0.0` at the expected container port.

```bash
envctl endpoints --json
envctl health --json
envctl logs --project Main --service backend
envctl restart --project Main --service backend --docker --headless
envctl stop --project Main --entire-system
```

See [Configuration: Docker application runtime](../reference/configuration.md#docker-application-runtime)
for image, Dockerfile, command, port, workdir, target, and cache-policy settings.

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
