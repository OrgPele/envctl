# Configuration

## Model

Configuration precedence:

1. existing shell environment variables
2. `.envctl` / `.envctl.sh`
3. engine defaults

Use:

- `.envctl` for orchestration behavior
- `.env` for app runtime variables and secrets

The Python runtime expects a repo-local `.envctl` for normal operational commands.

`envctl` keeps `.envctl` as a repo-local file, but envctl-owned local workflow artifacts are hidden through your Git global excludes configuration rather than by mutating the repository `.gitignore`.

That global-ignore contract covers the current envctl local artifact set:

- `.envctl*`
- `MAIN_TASK.md`
- `OLD_TASK_*.md`
- `trees/`
- `trees-*`

On config save, `envctl` updates the envctl-managed block in your configured Git global excludes file. If `core.excludesFile` is not configured, `envctl config` configures it to `~/.gitignore_global` and writes the envctl-managed artifact patterns there.

Useful commands:

- `envctl config` opens the interactive bootstrap/editor flow
- `envctl show-config --json` prints the effective config without mutating anything
- on missing `.envctl`, inspect-only commands still run with defaults

## Service Launch Env Templates In `.envctl`

`envctl` also supports user-owned launch env sections inside `.envctl`. These are env vars injected into the backend/frontend processes and configured additional app services that `envctl` starts.

```dotenv
# >>> envctl backend launch env >>>
DATABASE_URL=${ENVCTL_SOURCE_DATABASE_URL}  # generic DB URL; e.g. postgresql://user:pass@host:5432/dbname
APP_DATABASE_URL=${DATABASE_URL}?sslmode=disable
REDIS_URL=${ENVCTL_SOURCE_REDIS_URL}  # Redis URL; e.g. redis://host:6379/0
SUPABASE_URL=${ENVCTL_SOURCE_SUPABASE_URL}
SUPABASE_JWKS_URL=${ENVCTL_SOURCE_SUPABASE_JWKS_URL}
SUPABASE_SERVICE_ROLE_KEY=${ENVCTL_SOURCE_SUPABASE_SERVICE_ROLE_KEY}
# <<< envctl backend launch env <<<

# >>> envctl frontend launch env >>>
VITE_SUPABASE_URL=${ENVCTL_SOURCE_SUPABASE_URL}  # frontend-only Supabase URL
VITE_SUPABASE_ANON_KEY=${ENVCTL_SOURCE_SUPABASE_ANON_KEY}  # frontend-safe Supabase anon key
# <<< envctl frontend launch env <<<

# >>> envctl service voice-runtime launch env >>>
VOICE_RUNTIME_PUBLIC_URL=${ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_PUBLIC_URL}
# <<< envctl service voice-runtime launch env <<<

# >>> envctl main service voice-runtime launch env >>>
PELE_API_BASE_URL=${ENVCTL_SOURCE_BACKEND_URL}
# <<< envctl main service voice-runtime launch env <<<
```

These sections are separate from the managed startup block:

- the backend section applies only to backend launches
- the frontend section applies only to frontend launches
- `service <slug>` sections apply only to the matching additional app service
- `main service <slug>` and `trees service <slug>` sections apply only for that startup mode
- old shared sections are still understood for compatibility, but new `.envctl` files only seed backend/frontend sections
- `envctl config` seeds these sections when missing, but does not edit or normalize them afterward
- for a given service, only vars defined in its applicable sections are emitted
- you can rename, delete, add, or reorder emitted env vars manually
- later lines can reference earlier emitted values with `${VAR}`
- `ENVCTL_SOURCE_*` names are template-only inputs built from envctl's canonical dependency outputs
- active backend/frontend launch templates for core database/cache inputs (`ENVCTL_SOURCE_DATABASE_URL`,
  `ENVCTL_SOURCE_SQLALCHEMY_DATABASE_URL`, `ENVCTL_SOURCE_ASYNC_DATABASE_URL`, and `ENVCTL_SOURCE_REDIS_URL`) also
  request envctl-managed PostgreSQL/Redis dynamically when the matching dependency toggle is absent
- when Main-mode dependency port bases are left at the built-in defaults, envctl applies a per-session offset to managed
  dependency ports so generated DB/Redis URLs do not bind the same well-known host ports on every run
- explicit dependency toggles still win; for example `MAIN_POSTGRES_ENABLE=false` keeps PostgreSQL disabled even when a
  template references `ENVCTL_SOURCE_DATABASE_URL`
- a dependency already configured as managed/enabled stays managed even if the default app `.env` contains an old
  dependency URL from a previous run
- if any other referenced `ENVCTL_SOURCE_*` value is unavailable for the current run, that line is skipped
- custom aliases/templates are injected into launched processes only; the default backend `.env` is not rewritten with
  per-run managed PostgreSQL or Redis URLs
- after envctl seeds the launch env sections, `envctl config` leaves them unchanged

Supported template inputs include:

- `ENVCTL_SOURCE_DATABASE_URL`
- `ENVCTL_SOURCE_REDIS_URL`
- `ENVCTL_SOURCE_N8N_URL`
- `ENVCTL_SOURCE_SUPABASE_URL`
- `ENVCTL_SOURCE_SUPABASE_PUBLIC_URL`
- `ENVCTL_SOURCE_SUPABASE_PUBLIC_PORT`
- `ENVCTL_SOURCE_SUPABASE_API_PORT`
- `ENVCTL_SOURCE_SUPABASE_ANON_KEY`
- `ENVCTL_SOURCE_SUPABASE_SERVICE_ROLE_KEY`
- `ENVCTL_SOURCE_SUPABASE_JWT_SECRET`
- `ENVCTL_SOURCE_SUPABASE_JWKS_URL`
- `ENVCTL_SOURCE_SQLALCHEMY_DATABASE_URL`
- `ENVCTL_SOURCE_ASYNC_DATABASE_URL`
- `ENVCTL_SOURCE_DB_HOST`
- `ENVCTL_SOURCE_DB_PORT`
- `ENVCTL_SOURCE_DB_USER`
- `ENVCTL_SOURCE_DB_PASSWORD`
- `ENVCTL_SOURCE_DB_NAME`
- `ENVCTL_SOURCE_REDIS_PORT`
- `ENVCTL_SOURCE_N8N_PORT`
- `ENVCTL_SOURCE_SUPABASE_DB_PASSWORD`
- `ENVCTL_SOURCE_SUPABASE_DB_PORT`
- `ENVCTL_SOURCE_BACKEND_HOST`
- `ENVCTL_SOURCE_BACKEND_PORT`
- `ENVCTL_SOURCE_BACKEND_URL`
- `ENVCTL_SOURCE_FRONTEND_HOST`
- `ENVCTL_SOURCE_FRONTEND_PORT`
- `ENVCTL_SOURCE_FRONTEND_URL`
- `ENVCTL_SOURCE_SERVICE_<SUFFIX>_HOST`
- `ENVCTL_SOURCE_SERVICE_<SUFFIX>_PORT`
- `ENVCTL_SOURCE_SERVICE_<SUFFIX>_URL`
- `ENVCTL_SOURCE_SERVICE_<SUFFIX>_PUBLIC_URL`
- `ENVCTL_SOURCE_SERVICE_<SUFFIX>_HEALTH_URL`
- `ENVCTL_SOURCE_SUPABASE_USER_<SUFFIX>_ID`
- `ENVCTL_SOURCE_SUPABASE_USER_<SUFFIX>_EMAIL`
- `ENVCTL_SOURCE_SUPABASE_USER_<SUFFIX>_PASSWORD`
- `ENVCTL_SOURCE_SUPABASE_TEST_USER_ID`
- `ENVCTL_SOURCE_SUPABASE_TEST_USER_EMAIL`
- `ENVCTL_SOURCE_SUPABASE_TEST_USER_PASSWORD`

Only simple `${VAR}` placeholders are supported. Shell-style defaults, command substitution, and other expansion syntax are intentionally not supported.

Frontend launch-env sections may use `ENVCTL_SOURCE_SUPABASE_URL` and `ENVCTL_SOURCE_SUPABASE_ANON_KEY`. They cannot reference `ENVCTL_SOURCE_SUPABASE_SERVICE_ROLE_KEY`; envctl rejects that mapping before launching the frontend process.

## Managed Supabase Ports

Managed Supabase exposes two distinct local resources:

- `DB_PORT` / `ENVCTL_SOURCE_SUPABASE_DB_PORT` is the PostgreSQL host port used for database URLs such as `DATABASE_URL` and `SQLALCHEMY_DATABASE_URL`.
- `SUPABASE_PUBLIC_PORT` / `ENVCTL_SOURCE_SUPABASE_PUBLIC_PORT` is the public Supabase API gateway port. `ENVCTL_SOURCE_SUPABASE_URL` and `ENVCTL_SOURCE_SUPABASE_PUBLIC_URL` point here, not at Postgres. Browser auth clients should use this URL for `/auth/v1/*` calls.

The managed Supabase compose stack publishes Kong on `SUPABASE_PUBLIC_PORT` and readiness checks `/auth/v1/health`. If Postgres is healthy but Kong/Auth is unreachable, startup reports that split explicitly instead of marking Supabase healthy from the database listener alone. The readiness probe uses the local loopback URL for the published port, even when the projected `SUPABASE_PUBLIC_URL` points at a LAN or public host for browser access.

## Managed Supabase Auth Users

Declare local/E2E Auth users in `.envctl` when managed Supabase is enabled:

```dotenv
MAIN_SUPABASE_ENABLE=true
ENVCTL_SUPABASE_AUTH_USERS=e2e
ENVCTL_SUPABASE_USER_E2E_EMAIL=e2e@example.test
ENVCTL_SUPABASE_USER_E2E_PASSWORD=change-me-local-only
ENVCTL_SUPABASE_USER_E2E_USER_METADATA_JSON={"company_name":"E2E Co"}
ENVCTL_SUPABASE_USER_E2E_APP_METADATA_JSON={"role":"tester"}
ENVCTL_SUPABASE_AUTH_USERS_STRICT=true
```

User slugs must use lowercase letters, numbers, and hyphens. Env suffixes use uppercase with hyphens changed to underscores, so `admin-user` maps to `ENVCTL_SUPABASE_USER_ADMIN_USER_*` and `ENVCTL_SOURCE_SUPABASE_USER_ADMIN_USER_*`. Startup provisions enabled users through the Supabase Auth Admin API after managed Supabase is healthy and before app services launch.

`ENVCTL_SUPABASE_AUTH_USERS_STRICT=false` allows startup to continue after provisioning failures, but malformed user config still fails early. Passwords are never included in JSON command output or the runtime artifact.

## QA User Seed Hooks

`envctl qa-user ensure --seed <name>` can call project-provided deterministic seed hooks after the Auth user is created or reused. Configure either one generic command or per-seed commands:

```dotenv
ENVCTL_QA_USER_SEED_CMD=scripts/envctl/seed-qa-user.sh
ENVCTL_QA_USER_SEED_CRM_CMD=scripts/envctl/seed-crm-qa-user.sh
```

Seed commands run from the selected project root when envctl can infer it from active runtime state. They receive `ENVCTL_QA_USER_ID`, `ENVCTL_QA_USER_EMAIL`, `ENVCTL_QA_USER_LOCALE`, `ENVCTL_QA_USER_SEEDS`, `ENVCTL_PROJECT_NAME`, and available managed dependency connection env such as local Supabase URLs/keys for backend-only seeding. When no hook is configured, envctl reports the requested seed as skipped with `reason=no_seed_hook_configured` instead of assuming an app schema.

`qa-user ensure` writes a redacted `qa-user-ensure.json` artifact under the active run directory. The artifact includes user id/email, created/reused/updated flags, selected seeds, seed results, timestamp, dependency mode, and redacted credentials. Use `--update-password` and `--update-metadata` to mutate an existing user; without those flags an existing user is reused unchanged.

## Additional App Services

Additional app services are long-running application processes owned by the repo, not managed infrastructure dependencies. They are enabled through `.envctl` and participate in normal startup, state, runtime-map, logs, health, dashboard, and `envctl test --service <slug>` flows.

Example HTTP sidecar plus non-listener worker:

```dotenv
ENVCTL_ADDITIONAL_SERVICES=voice-runtime,worker

ENVCTL_SERVICE_VOICE_RUNTIME_ENABLE=true
ENVCTL_SERVICE_VOICE_RUNTIME_DIR=voice-runtime
ENVCTL_SERVICE_VOICE_RUNTIME_PORT_BASE=8010
ENVCTL_SERVICE_VOICE_RUNTIME_START_CMD=scripts/envctl/start-voice-runtime.sh {port}
ENVCTL_SERVICE_VOICE_RUNTIME_EXPECT_LISTENER=true
ENVCTL_SERVICE_VOICE_RUNTIME_HEALTH_URL=http://${ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_HOST}:${ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_PORT}/readyz
ENVCTL_SERVICE_VOICE_RUNTIME_PUBLIC_URL=http://${ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_HOST}:${ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_PORT}
ENVCTL_SERVICE_VOICE_RUNTIME_TEST_CMD=scripts/envctl/test-voice-runtime.sh

ENVCTL_SERVICE_WORKER_ENABLE=true
ENVCTL_SERVICE_WORKER_DIR=backend
ENVCTL_SERVICE_WORKER_START_CMD=python -m app.worker
ENVCTL_SERVICE_WORKER_EXPECT_LISTENER=false
ENVCTL_SERVICE_WORKER_TEST_CMD=python -m pytest tests/test_worker.py
```

Supported keys use `ENVCTL_SERVICE_<SUFFIX>_...`, where `<SUFFIX>` is the uppercase slug with hyphens changed to underscores. For `voice-runtime`, the suffix is `VOICE_RUNTIME`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `ENVCTL_ADDITIONAL_SERVICES` | unset | Comma-separated ordered service slugs, such as `voice-runtime,worker`. |
| `ENVCTL_SERVICE_<SUFFIX>_ENABLE` | `true` | Both-mode enable default for a declared service. |
| `ENVCTL_SERVICE_<SUFFIX>_MAIN_ENABLE` | `ENABLE` | Main-mode override. |
| `ENVCTL_SERVICE_<SUFFIX>_TREES_ENABLE` | `ENABLE` | Trees-mode override. |
| `ENVCTL_SERVICE_<SUFFIX>_DIR` | `.` | Repo-relative service working directory. Startup fails if a configured non-root directory is missing or escapes the project root. |
| `ENVCTL_SERVICE_<SUFFIX>_START_CMD` | unset | Required for enabled services. Supports `{port}`, `{project_root}`, `{service_dir}`, and `{service_name}` placeholders. |
| `ENVCTL_SERVICE_<SUFFIX>_TEST_CMD` | unset | Command used by `envctl test --service <slug>`. Runs from the configured service directory. If this is unset, `envctl test --service <slug>` fails clearly instead of falling back to generic backend/frontend tests. |
| `ENVCTL_SERVICE_<SUFFIX>_PORT_BASE` | unset | Required when `EXPECT_LISTENER=true`; gets normal per-project port spacing. |
| `ENVCTL_SERVICE_<SUFFIX>_EXPECT_LISTENER` | `true` | Set `false` for workers and schedulers that do not bind a port. |
| `ENVCTL_SERVICE_<SUFFIX>_HEALTH_URL` | unset | Template stored/projected for tooling and launch env aliases. |
| `ENVCTL_SERVICE_<SUFFIX>_PUBLIC_URL` | derived from host/port | Template for the service public URL source variable. |
| `ENVCTL_SERVICE_<SUFFIX>_START_ORDER` | `100` | Coarse ordering for additional services after built-in service descriptors. |
| `ENVCTL_SERVICE_<SUFFIX>_DEPENDS_ON` | unset | Comma-separated references to `backend`, `frontend`, configured additional services, or configured dependency ids. Unknown references and service cycles fail validation/startup with actionable diagnostics. Dependency ids such as `redis`, `postgres`, `supabase`, or `n8n` validate the relationship and influence service ordering/metadata, but they do not by themselves enable disabled infrastructure; keep the matching `MAIN_*_ENABLE` / `TREES_*_ENABLE` dependency setting enabled when the service requires that infrastructure at runtime. |
| `ENVCTL_SERVICE_<SUFFIX>_CRITICAL` | `true` | `true` keeps fail-fast startup. `false` records a degraded failed service with cwd/log/port/failure metadata and allows healthy independent services to continue. |

Reserved additional-service slugs include `backend`, `frontend`, managed dependency ids, `all`, `services`, and `dependencies`.

Startup plans application services in dependency layers. Built-in backend/frontend behavior is unchanged when no additional service dependencies are configured. Inside a layer, `START_ORDER` and slug order are deterministic tie-breakers; a service that depends on another app service starts only after that dependency's layer completes. Listener services use strict listener truth, while `EXPECT_LISTENER=false` workers persist `port: null`, `url: null`, and `listener_expected: false` but still keep static health/public URLs if configured.

Runtime state, `show-state --json`, runtime maps, dashboard rows, and `health --json` expose canonical `project`, `service_slug`, `public_url`, `health_url`, `critical`, `degraded`, and `failure_detail` fields so external tooling does not need to parse display names. Dashboard rows render additional listener services with final rebound URLs, public/health URLs, log paths, and port rebind notes; non-listener workers render as non-listener rows instead of unreachable URLs. Service targeting accepts `<slug>`, `service:<slug>`, exact display names, and full service names for logs, errors, tests, stop, restart, and other actions where service filters are supported.

## Migrate Env Resolution

Native `envctl migrate` uses the same backend env-file discovery contract as backend startup/bootstrap:

1. `BACKEND_ENV_FILE_OVERRIDE`
2. `MAIN_ENV_FILE_PATH` when the target project is `Main`
3. default `backend/.env`

Override path resolution is explicit:

- absolute paths are used as-is
- relative paths are checked against both the target project root and the repo root
- if exactly one relative candidate exists, envctl uses it
- if both candidates exist and differ, envctl fails and requires an absolute path
- if neither candidate exists, envctl falls back to the default `backend/.env` contract when present

When an env file is found, envctl exports `APP_ENV_FILE` into the migrate subprocess so backends that explicitly look up their env file can resolve it during Alembic imports.

Runtime dependency projection also applies to migrate:

- inherited shell backend keys such as `DATABASE_URL`, `APP_ENV_FILE`, `SQLALCHEMY_DATABASE_URL`, `ASYNC_DATABASE_URL`, and `DB_*` are scrubbed before target-specific merge
- if the selected project already has saved requirements state, envctl reuses its canonical dependency URLs such as `DATABASE_URL`, `SQLALCHEMY_DATABASE_URL`, `ASYNC_DATABASE_URL`, and `REDIS_URL`
- the default backend `.env` is not authoritative for those projected dependency URLs during migrate or startup bootstrap
- default backend `.env` writeback is limited to cleanup of stale DB alias keys and does not persist current run
  `DATABASE_URL`, `SQLALCHEMY_DATABASE_URL`, `ASYNC_DATABASE_URL`, or `REDIS_URL` values
- an explicit non-default backend env override file remains authoritative for DB-family keys, matching the existing `SKIP_LOCAL_DB_ENV` semantics

Relevant keys:

| Variable | Default | Purpose |
| --- | --- | --- |
| `BACKEND_ENV_FILE_OVERRIDE` | unset | Explicit backend env file path for worktree/tree targets and other non-Main projects. Relative paths can resolve from the target root or repo root. |
| `MAIN_ENV_FILE_PATH` | unset | Explicit backend env file path for Main mode. Relative paths can resolve from the target root or repo root. |
| `APP_ENV_FILE` | set by envctl when a backend env file is resolved | Exported into backend startup/migrate subprocesses for apps that discover env files from process env. |
| `SKIP_LOCAL_DB_ENV` | `false` | Compatibility toggle for preserving explicit backend env-file database URLs instead of replacing them with envctl-projected local DB URLs. |

## Frontend Service Env Resolution

Frontend service startup uses the same env-file override contract as backend startup/bootstrap, but it only affects frontend service launch env and does not participate in backend-only `migrate` diagnostics.

Frontend env resolution order is:

1. `FRONTEND_ENV_FILE_OVERRIDE`
2. `MAIN_FRONTEND_ENV_FILE_PATH` when the target project is `Main`
3. default `frontend/.env`

Override path resolution is shared with backend env-file discovery:

- absolute paths are used as-is
- relative paths are checked against both the target project root and the repo root
- if exactly one relative candidate exists, envctl uses it
- if both candidates exist and differ, envctl fails and requires an absolute path
- if neither candidate exists, envctl falls back to the default `frontend/.env` contract when present

Relevant keys:

| Variable | Default | Purpose |
| --- | --- | --- |
| `FRONTEND_ENV_FILE_OVERRIDE` | unset | Explicit frontend env file path for worktree/tree targets and other non-Main projects. Relative paths can resolve from the target root or repo root. |
| `MAIN_FRONTEND_ENV_FILE_PATH` | unset | Explicit frontend env file path for Main mode. Relative paths can resolve from the target root or repo root. |

## Managed vs Compatibility Keys

The Python config layer now has canonical managed keys such as:

- `MAIN_STARTUP_ENABLE`
- `MAIN_BACKEND_ENABLE`
- `MAIN_POSTGRES_ENABLE`
- `TREES_STARTUP_ENABLE`
- `TREES_REDIS_ENABLE`
- `TREES_N8N_ENABLE`

Compatibility aliases from the shell era are still accepted where relevant, for example:

- `POSTGRES_MAIN_ENABLE`
- `REDIS_MAIN_ENABLE`
- `SUPABASE_MAIN_ENABLE`
- `N8N_MAIN_ENABLE`

The current config wizard writes, edits, and preserves the canonical managed keys, including declared additional app services. Launch env template sections remain user-owned and are preserved as-is.

## Current Wizard Coverage

The current setup/editor wizard covers:

- default mode
- services and dependencies
- optional backend-only long-running service startup
- backend/frontend directories
- entrypoints and backend/frontend test command suggestions
- optional frontend test directory suggestions
- canonical ports
- advanced additional app service definitions: slug, directory, start command, port base, listener expectation, main/trees enablement, optional test command, public URL, health URL, dependencies, start order, and critical/non-critical behavior

The current flow is:

1. `Welcome / Source`
2. `Default Mode`
3. `Components`
4. optional `Long-Running Service`
5. advanced `Additional App Services` fields when services are configured or the advanced wizard is requested
6. `Directories`
7. `Entrypoints / Commands`
8. `Ports`
9. `Review / Save`

There is no separate visible simple/advanced chooser in the current UI; callers can request the advanced wizard path to show additional-service fields even before a service exists.

The `Entrypoints / Commands` step shows only the command fields needed for the enabled backend/frontend components. For test commands, the wizard displays detected suggestions with source labels (for example backend pytest from `backend/tests` or a frontend package test script from `frontend/package.json`). Test command fields are optional: leaving one blank means `envctl test` may still try runtime defaults later. The wizard does not execute test commands during setup.

The wizard saves accepted backend/frontend test suggestions to `ENVCTL_BACKEND_TEST_CMD`, `ENVCTL_FRONTEND_TEST_CMD`, and `ENVCTL_FRONTEND_TEST_PATH` when applicable. Shared `ENVCTL_ACTION_TEST_CMD` remains a lower-level override for config/API payload compatibility and is not a first-run wizard field.

## Core
| Variable | Default | Purpose |
| --- | --- | --- |
| `ENVCTL_SKIP_DEFAULT_INFRASTRUCTURE` | `false` | Global skip for built-in PostgreSQL and Redis startup. |
| `ENVCTL_DEFAULT_MODE` | `main` | Startup default when no mode flag is passed (`main` or `trees`). |
| `ENVCTL_PLANNING_DIR` | `todo/plans` | Planning root used by `--plan`, `--sequential-plan`, and `--planning-prs`. Plans scaled to zero are archived into sibling `done/` under the same parent (for example `todo/done`). |
| `ENVCTL_CONFIG_FILE` | unset | Explicit config file path override. |
| `RUN_SH_RUNTIME_DIR` | `/tmp/envctl-runtime` | Runtime artifact root (Python artifacts are under `python-engine/`). |
| `ENVCTL_STRICT_N8N_BOOTSTRAP` | `false` | Treat n8n owner/bootstrap endpoint mismatch as hard failure. |
| `ENVCTL_STATE_COMPAT_MODE` | `compat_read_write` | State repository compatibility mode (`compat_read_write`, `compat_read_only`, `scoped_only`). |
| `ENVCTL_RUNTIME_TRUTH_MODE` | `auto` | Runtime truth enforcement policy. |

## Execution Policy
| Variable | Default | Purpose |
| --- | --- | --- |
| `ENVCTL_SERVICE_ATTACH_PARALLEL` | `true` | Run backend+frontend service attach in parallel when both are selected. |
| `ENVCTL_SERVICE_PREP_PARALLEL` | follows `ENVCTL_SERVICE_ATTACH_PARALLEL` | Override backend+frontend bootstrap prep parallelism independently from attach mode. |
| `ENVCTL_ACTION_TEST_PARALLEL` | `true` | Run backend/frontend test suites in parallel when both suites are detected. |
| `ENVCTL_ACTION_TEST_PARALLEL_MAX` | `4` | Max concurrently running test suites when parallel test mode is enabled. |

## Plan Agent Launch
| Variable | Default | Purpose |
| --- | --- | --- |
| `ENVCTL_PLAN_AGENT_TERMINALS_ENABLE` | `false` | Enable post-`--plan` terminal launch for selected implementation worktrees. When no transport is selected, Linux defaults to tmux; other hosts prefer cmux and fall back to tmux when cmux is not installed. Explicit `--cmux` or cmux workspace config keeps the launch on cmux. |
| `ENVCTL_PLAN_AGENT_CLI` | `codex` | AI CLI selection for launched surfaces (`codex` or `opencode`). |
| `ENVCTL_PLAN_AGENT_PRESET` | `implement_task` | Prompt preset name submitted after the AI CLI starts. OpenCode cmux/tmux launches submit the rendered prompt body directly by default. Codex resolves the preset from the envctl-managed Codex prompt file and submits that prompt body directly. `implement_plan` remains available as a backward-compatible preset. |
| `ENVCTL_PLAN_AGENT_DIRECT_PROMPT` | transport/CLI dependent | Use direct prompt-body submission instead of slash-command submission when supported. Defaults to true for cmux/tmux OpenCode. |
| `ENVCTL_PLAN_AGENT_ULW_LOOP_PREFIX` | transport/CLI dependent | Prefix OpenCode direct prompts with `/ulw-loop` when supported. Defaults to true for cmux/tmux OpenCode direct prompts. |
| `ENVCTL_PLAN_AGENT_APPEND_ULW` | `false` | Append ULW guidance for slash-command mode. |
| `ENVCTL_PLAN_AGENT_CODEX_CYCLES` | `2` | Codex TUI queued workflow count for the post-`--plan` launcher, including envctl-owned cmux/tmux Codex and OMX-managed Codex sessions. The default `2` queues a first follow-up telling Codex to commit, push, open or update the PR, and wait for GitHub status checks before the final `continue_task` -> `implement_task` -> `finalize_task` round, then queues the enabled browser-E2E and PR-review-comment follow-ups after finalization. `0` submits the single implementation prompt and queues enabled follow-ups for Codex/OMX surfaces. `1` queues `implement_task`, `finalize_task`, and enabled follow-ups. Higher values keep that first follow-up, use commit/push-only follow-ups for intermediate rounds, and reserve `finalize_task` plus enabled follow-ups for the final round. OpenCode ignores this setting. Envctl only appends prompt commands/messages in this mode; it does not execute those shell commands itself. |
| `ENVCTL_PLAN_AGENT_CODEX_GOAL_ENABLE` | `true` | Toggle Codex `/goal` session framing before the initial implementation prompt. Applies to Codex cmux, tmux, and OMX-managed tmux launches, including `--omx --ultragoal`, `--omx --ralph`, and `--omx --team`; OpenCode ignores it. Route flags `--goal`/`--codex-goal` enable it and `--no-goal`/`--no-codex-goal` disable it for one launch. |
| `ENVCTL_PLAN_AGENT_BROWSER_E2E_ENABLE` | `true` | Toggle the Codex/OMX `$browser-use` E2E follow-up. When true, envctl queues a browser validation prompt after implementation/finalization to re-read `MAIN_TASK.md`, validate the feature end-to-end against the full `envctl --entire-system --headless` stack, capture browser evidence where possible, and fix implementation-introduced issues. Set this to `false` in `.envctl` or the environment to skip that follow-up. |
| `ENVCTL_PLAN_AGENT_PR_REVIEW_COMMENTS_ENABLE` | `true` | Toggle the final Codex/OMX PR review-comments follow-up. When true, envctl queues a `$gh-address-comments` prompt after the current implementation/E2E prompts to inspect unresolved PR comments, address all actionable feedback, commit/push fixes, and wait for final PR confirmation. Set this to `false` in `.envctl` or the environment to skip that follow-up. |
| `ENVCTL_PLAN_AGENT_SHELL` | `zsh` | Shell command used when respawning the new cmux surface. |
| `ENVCTL_PLAN_AGENT_REQUIRE_CMUX_CONTEXT` | `true` | Require caller `CMUX_WORKSPACE_ID` so envctl can derive the default `"<current workspace> implementation"` target. If false, envctl falls back to the selected cmux workspace title when available. |
| `ENVCTL_PLAN_AGENT_CODEX_YOLO` | `true` | When envctl owns a Codex cmux/tmux launch and `ENVCTL_PLAN_AGENT_CLI_CMD` is unset, append `--dangerously-bypass-approvals-and-sandbox`. Set to `false` in `.envctl` when your Codex wrapper or config already supplies that flag. |
| `ENVCTL_PLAN_AGENT_CLI_CMD` | unset | Optional raw AI CLI command override typed into the launched shell. When set, this raw command wins over the default Codex YOLO command builder. |
| `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE` | unset | Explicit cmux workspace target for new surfaces. Accepts a workspace ref/UUID/index or a workspace title such as `envctl`. When set, it also enables plan-agent terminal launch even if `ENVCTL_PLAN_AGENT_TERMINALS_ENABLE` is unset. If a named workspace does not already exist, envctl creates it first and reuses that workspace's initial cmux starter surface for the first launch when the starter probe is unambiguous; otherwise it falls back to opening a new surface. |

Enabled plan-agent launches prepare backend/frontend dependencies in the selected worktree before prompt submission.
This reuses the normal backend/frontend bootstrap logic, skips migrations, and does not start services. Configured backend
commands that begin with generic Python (`python`, `python3`, or `python3.12`) are resolved through the prepared Poetry
runner or backend virtualenv when available.

Dashboard review-tab note:

- the optional post-review origin tab in `envctl dashboard` reuses `ENVCTL_PLAN_AGENT_CLI`, `ENVCTL_PLAN_AGENT_CLI_CMD`, `ENVCTL_PLAN_AGENT_SHELL`, `ENVCTL_PLAN_AGENT_REQUIRE_CMUX_CONTEXT`, and `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE`
- it does not read `ENVCTL_PLAN_AGENT_TERMINALS_ENABLE`; the dashboard selector menu is the opt-in
- when no explicit cmux workspace override is set, the review-tab flow targets a sibling workspace named `"<current workspace> reviews"`
- the launched review prompt includes reviewer notes pointing at the generated review bundle, target worktree directory, and the original plan file that created the worktree when provenance can resolve it

Alias env vars:

- `CMUX=true` is a shorthand alias for enabling plan-agent launch with the default `"<current workspace> implementation"` target
- `CMUX_WORKSPACE=<value>` is a shorthand alias for `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE=<value>`
- `CYCLES=<n>` is a shorthand alias for `ENVCTL_PLAN_AGENT_CODEX_CYCLES=<n>`
- canonical `ENVCTL_PLAN_AGENT_*` keys win when both canonical and alias forms are set
- `CYCLES` only changes the effective Codex cycle count; it does not enable plan-agent launch by itself

Cycle mode notes:

- the queued cycle workflow is active for Codex TUI surfaces (cmux, tmux, and OMX-managed tmux) when `ENVCTL_PLAN_AGENT_CODEX_CYCLES` is a positive integer; enabled browser-E2E and PR-review-comment follow-ups are queued for Codex/OMX surfaces even when the cycle count is `0`
- invalid or negative values are ignored and the launcher stays on the single implementation prompt plus enabled follow-ups
- very large values are bounded internally for safety before the workflow is expanded
- if queue injection fails after the initial `implement_task` submit, envctl falls back to the initial one-shot launch and leaves the Codex surface running
- the global default remains `ENVCTL_PLAN_AGENT_CODEX_CYCLES=2`; `$envctl-create-plan-auto-codex` computes a `0` through `8` recommendation and uses that command-scoped value for the envctl command it launches
- `$envctl-create-plan-auto-opencode` ignores Codex cycles and uses `--tmux --opencode` with the default `/ulw-loop` prefix
- `$envctl-create-plan-auto-omx` uses `--omx --ultragoal`; Codex `/goal` framing is submitted first when enabled, Ultragoal wraps the initial prompt, and envctl can queue the same Codex follow-up cycle workflow used by plain Codex TUI launches. Use `--omx --ralph` explicitly when you need the Ralph compatibility workflow.

## Debug and Diagnostics
| Variable | Default | Purpose |
| --- | --- | --- |
| `ENVCTL_DEBUG_UI_MODE` | `off` | Debug capture mode (`off`, `standard`, `deep`). |
| `ENVCTL_DEBUG_AUTO_PACK` | `off` | Auto-pack policy (`off`, `crash`, `anomaly`, `always`). |
| `ENVCTL_DEBUG_RETENTION_DAYS` | `7` | Retention window for debug sessions under runtime debug root. |
| `ENVCTL_DEBUG_TRACE_ID_MODE` | `per-command` | Trace identifier strategy (`per-command`, `per-session`). |
| `ENVCTL_DEBUG_UI_BUNDLE_STRICT` | `true` | Enforce strict redaction when packaging debug bundles. |
| `ENVCTL_DEBUG_UI_CAPTURE_PRINTABLE` | `false` | Permit printable byte ring capture in deep mode (not recommended). |
| `ENVCTL_DEBUG_UI_MAX_EVENTS` | `20000` | Max debug events captured per session. |
| `ENVCTL_DEBUG_UI_RING_BYTES` | `32768` | Input ring size bound for deep capture. |
| `ENVCTL_DEBUG_UI_SAMPLE_RATE` | `1` | Event sampling interval for recorder (`1` means every event). |

## Interactive UI Policy
| Variable | Default | Purpose |
| --- | --- | --- |
| `ENVCTL_UI_BACKEND` | `auto` | Interactive dashboard policy (`auto`, `textual`, `legacy`, `non_interactive`). `auto` currently stays on the legacy dashboard unless `ENVCTL_UI_EXPERIMENTAL_DASHBOARD=1` is also set. |
| `ENVCTL_UI_EXPERIMENTAL_DASHBOARD` | `false` | When combined with `ENVCTL_UI_BACKEND=auto`, prefer the Textual dashboard if Textual is available. |
| `ENVCTL_UI_TEXTUAL_HEADLESS_ALLOWED` | `false` | Test-only override to allow Textual capability checks in headless harnesses. |
| `ENVCTL_UI_TEXTUAL_FPS` | `30` | Optional Textual refresh tuning for heavy interactive sessions. |
| `ENVCTL_UI_SPINNER_MODE` | `auto` | Spinner policy mode (`auto`, `on`, `off`). |
| `ENVCTL_UI_SPINNER_MIN_MS` | `120` | Minimum operation time before spinner is rendered to reduce flicker. |
| `ENVCTL_UI_SPINNER_VERBOSE_EVENTS` | `false` | Emit extra spinner lifecycle diagnostics in debug traces. |
| `ENVCTL_UI_SPINNER` | `true` | Compatibility toggle; still honored when mode is `auto`. |
| `ENVCTL_UI_RICH` | `true` | Compatibility toggle for rich-backed UI rendering when mode is `auto`. |
| `ENVCTL_UI_HYPERLINK_MODE` | `auto` | Local-path hyperlink policy for human-facing CLI output (`auto`, `on`, `off`). `auto` only emits OSC-8 links on supported interactive terminals; JSON output stays raw. |
| `ENVCTL_PUBLIC_HOST` | `localhost` | Host/IP injected into browser-facing frontend environment URLs such as `VITE_BACKEND_URL` and `VITE_API_URL`. Dashboard visual URLs use this host by default. Ports remain dynamically allocated per project/worktree; service binding, probes, and persisted runtime maps are unchanged. |
| `ENVCTL_UI_VISUAL_HOST` | `ENVCTL_PUBLIC_HOST` | Optional dashboard-only override for visual service URLs. Leave unset/blank to reuse `ENVCTL_PUBLIC_HOST`. This does not change service binding, probes, persisted runtime maps, or frontend/backend environment URLs. |

Spinner configuration affects whether animated progress is shown, but not final status semantics: envctl-owned final/status lines use `✓` for success, `✗` for failure/error, and neutral glyphs such as `•`, `~`, or `○` for non-terminal or non-error states. Headless/non-TTY output remains deterministic and does not emit animated spinner frames.

## Experimental
| Variable | Default | Purpose |
| --- | --- | --- |
| `ENVCTL_EXPERIMENTAL_CODEX_SKILLS` | `false` | Legacy compatibility toggle; Codex install-prompts now installs explicit-only skills under `~/.codex/skills/envctl-*` by default. |

Selector implementation is controlled separately from dashboard backend policy:

- default selector implementation is the Textual plan-style selector
- `ENVCTL_UI_SELECTOR_IMPL=planning_style` enables the prompt-toolkit rollback path
- `ENVCTL_UI_SELECTOR_IMPL=legacy` remains a compatibility alias that still resolves to the Textual selector implementation

## Database (PostgreSQL and Supabase)
Supabase includes PostgreSQL, so treat them as alternative stacks per scope.

| Variable | Default | Purpose |
| --- | --- | --- |
| `MAIN_POSTGRES_ENABLE` | `false` | Canonical PostgreSQL toggle for Main mode. Compatibility alias: `POSTGRES_MAIN_ENABLE`. |
| `TREES_POSTGRES_ENABLE` | `false` | Canonical PostgreSQL toggle for Trees mode. |
| `DB_PORT` | `5432` | PostgreSQL base port. |
| `DB_USER` | `postgres` | PostgreSQL user. |
| `DB_PASSWORD` | `postgres` | PostgreSQL password. |
| `DB_NAME` | `postgres` | PostgreSQL DB name. |
| `ENVCTL_DYNAMIC_MAIN_DEPENDENCY_PORTS` | `true` when DB/Redis ports use built-in defaults | Apply a per-session offset to Main-mode managed dependency ports while keeping app ports stable. Set to `false` to bind exactly to `DB_PORT`, `REDIS_PORT`, and `N8N_PORT_BASE`. |
| `MAIN_SUPABASE_ENABLE` | `false` | Canonical Supabase toggle for Main mode. Compatibility alias: `SUPABASE_MAIN_ENABLE`. |
| `TREES_SUPABASE_ENABLE` | `false` | Canonical Supabase toggle for Trees mode. |
| `SUPABASE_PUBLIC_PORT` | `54321` | Public Supabase API/Kong port used for `ENVCTL_SOURCE_SUPABASE_URL`. |
| `ENVCTL_SUPABASE_COMPOSE_UP_TIMEOUT_SECONDS` | `120.0` | Timeout for managed Supabase `docker compose up -d` handoff before timeout recovery checks service/container state. |
| `ENVCTL_SUPABASE_DB_PROBE_ATTEMPTS` | `2` | Initial managed Supabase DB listener probe attempts after DB compose startup. |
| `ENVCTL_SUPABASE_DB_PROBE_TIMEOUT_SECONDS` | `10.0` | Per-attempt managed Supabase DB listener probe timeout; non-positive values fall back to 30 seconds. |
| `ENVCTL_SUPABASE_DB_RESTART_ON_PROBE_FAILURE` | `true` | Restart only the Supabase DB service when the initial DB listener probe exhausts. |
| `ENVCTL_SUPABASE_DB_RESTART_PROBE_ATTEMPTS` | same as `ENVCTL_SUPABASE_DB_PROBE_ATTEMPTS` | DB listener probe attempts after scoped DB restart. |
| `ENVCTL_SUPABASE_DB_RECREATE_ON_PROBE_FAILURE` | `true` | Stop/remove/recreate only the Supabase DB service when restart recovery exhausts. |
| `ENVCTL_SUPABASE_DB_RECREATE_PROBE_ATTEMPTS` | same as restart probe attempts | DB listener probe attempts after scoped DB recreate. |
| `ENVCTL_SUPABASE_AUTH_PROBE_TIMEOUT_SECONDS` | `5.0` | Per-phase timeout for managed Supabase Auth/Kong `/auth/v1/health` readiness probes. |
| `ENVCTL_SUPABASE_AUTH_RESTART_ON_PROBE_FAILURE` | `true` | Restart only Auth/Kong after DB is healthy but the public API health probe fails. |
| `ENVCTL_SUPABASE_AUTH_RESTART_PROBE_ATTEMPTS` | `2` | Number of Auth/Kong health probe windows after scoped restart; clamped to at least 1. |
| `ENVCTL_SUPABASE_AUTH_RECREATE_ON_PROBE_FAILURE` | `true` | Stop/remove/recreate only Auth/Kong after restart recovery is exhausted. Does not remove the Supabase DB service or volumes. |
| `ENVCTL_SUPABASE_AUTH_RECREATE_PROBE_ATTEMPTS` | `3` | Number of Auth/Kong health probe windows after scoped recreate; clamped to at least 1. |
| `ENVCTL_SUPABASE_NETWORK_RECOVERY_ALLOW_GLOBAL_EMPTY_CLEANUP` | `false` | Allow stale missing-network recovery to fall back from current-project cleanup to broader empty `envctl-supabase-*` network cleanup. Address-pool exhaustion recovery still uses the existing empty envctl Supabase network cleanup path. |
| `ENVCTL_SUPABASE_AUTH_USERS` | unset | Comma-separated managed Supabase Auth user slugs for local/E2E provisioning. |
| `ENVCTL_SUPABASE_USER_<SUFFIX>_EMAIL` | unset | Required email for an enabled managed Auth user. |
| `ENVCTL_SUPABASE_USER_<SUFFIX>_PASSWORD` | unset | Required local/E2E password for an enabled managed Auth user. |
| `ENVCTL_SUPABASE_USER_<SUFFIX>_USER_METADATA_JSON` | unset | Optional JSON object passed as Supabase user metadata. |
| `ENVCTL_SUPABASE_USER_<SUFFIX>_APP_METADATA_JSON` | unset | Optional JSON object passed as Supabase app metadata. |
| `ENVCTL_SUPABASE_AUTH_USERS_STRICT` | `true` | Fail startup when enabled Auth users cannot be provisioned. |

## Redis
| Variable | Default | Purpose |
| --- | --- | --- |
| `REDIS_ENABLE` | `false` | Global compatibility toggle honored by both Main and Trees profiles. |
| `MAIN_REDIS_ENABLE` | `false` | Canonical Redis toggle for Main mode. Compatibility alias: `REDIS_MAIN_ENABLE`. |
| `TREES_REDIS_ENABLE` | `false` | Canonical Redis toggle for Trees mode. Compatibility alias path still honors `REDIS_ENABLE`. |
| `REDIS_PORT` | `6379` | Redis base port. |

## n8n
| Variable | Default | Purpose |
| --- | --- | --- |
| `N8N_ENABLE` | `false` | Global compatibility toggle honored by both Main and Trees profiles. |
| `MAIN_N8N_ENABLE` | `false` | Canonical n8n toggle for Main mode. Compatibility alias: `N8N_MAIN_ENABLE`. |
| `TREES_N8N_ENABLE` | `false` | Canonical n8n toggle for Trees mode. Compatibility alias path still honors `N8N_ENABLE`. |
| `N8N_PORT_BASE` | `5678` | n8n base port. |

## Service Discovery
| Variable | Default | Purpose |
| --- | --- | --- |
| `MAIN_STARTUP_ENABLE` | `true` | Master switch for whether Main mode auto-starts anything at all. |
| `TREES_STARTUP_ENABLE` | `true` | Master switch for whether Trees mode auto-starts anything at all. |
| `MAIN_BACKEND_ENABLE` | `true` | Enable backend startup in Main mode when startup is enabled. |
| `MAIN_BACKEND_EXPECT_LISTENER` | `true` | Expect the Main backend to open a listener/port. Set `false` for long-running scripts or workers that should start without blocking on port detection. |
| `TREES_BACKEND_ENABLE` | `true` | Enable backend startup in Trees mode when startup is enabled. |
| `TREES_BACKEND_EXPECT_LISTENER` | `true` | Expect the Trees backend to open a listener/port. Set `false` for long-running scripts or workers that should start without blocking on port detection. |
| `MAIN_FRONTEND_ENABLE` | `true` | Enable frontend startup in Main mode when startup is enabled. |
| `TREES_FRONTEND_ENABLE` | `true` | Enable frontend startup in Trees mode when startup is enabled. |
| `BACKEND_DIR` | `backend` | Preferred backend directory name. |
| `BACKEND_PORT_BASE` | `8000` | Backend base port for allocation. |
| `FRONTEND_DIR` | `frontend` | Preferred frontend directory name. |
| `FRONTEND_PORT_BASE` | `9000` | Frontend base port for allocation. |
| `BACKEND_ENV_FILE_OVERRIDE` | unset | Explicit backend env file path for non-Main backend startup/migrate flows. Relative paths can resolve from the target root or repo root; ambiguous dual matches are rejected. |
| `MAIN_ENV_FILE_PATH` | unset | Explicit backend env file path for Main backend startup/migrate flows. Relative paths can resolve from the target root or repo root; ambiguous dual matches are rejected. |

## Optional Hooks (`.envctl.sh`)

Use hooks only for advanced custom orchestration.

Supported hooks:
- `envctl_define_services`
- `envctl_setup_infrastructure`

During Python-first migration, `.envctl.sh` remains compatibility-supported but is parsed safely by Python runtime (no shell `source` execution).

## Related Docs

- [Python Engine Guide](../user/python-engine-guide.md)
- [Commands](commands.md)
- [Architecture Overview](../developer/architecture-overview.md)
- [Python Runtime Guide](../developer/python-runtime-guide.md)
