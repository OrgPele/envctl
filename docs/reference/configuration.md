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

`envctl` keeps `.envctl` as a repo-local file, but envctl-owned local workflow artifacts are expected to be hidden through your Git global excludes configuration rather than by mutating the repository `.gitignore`.

That global-ignore contract covers the current envctl local artifact set:

- `.envctl*`
- `MAIN_TASK.md`
- `OLD_TASK_*.md`
- `trees/`
- `trees-*`

If `core.excludesFile` is not configured, `envctl config` still saves `.envctl` but warns that local envctl artifacts may continue to appear in `git status` until global excludes are configured.

Useful commands:

- `envctl config` opens the interactive bootstrap/editor flow
- `envctl show-config --json` prints the effective config without mutating anything
- on missing `.envctl`, inspect-only commands still run with defaults

## Service Launch Env Templates In `.envctl`

`envctl` also supports user-owned launch env sections inside `.envctl`. These are env vars injected into the backend/frontend processes that `envctl` starts.

```dotenv
# >>> envctl backend launch env >>>
DATABASE_URL=${ENVCTL_SOURCE_DATABASE_URL}  # generic DB URL; e.g. postgresql://user:pass@host:5432/dbname
APP_DATABASE_URL=${DATABASE_URL}?sslmode=disable
REDIS_URL=${ENVCTL_SOURCE_REDIS_URL}  # Redis URL; e.g. redis://host:6379/0
# <<< envctl backend launch env <<<

# >>> envctl frontend launch env >>>
VITE_SUPABASE_URL=${ENVCTL_SOURCE_SUPABASE_URL}  # frontend-only Supabase URL
# <<< envctl frontend launch env <<<
```

These sections are separate from the managed startup block:

- the backend section applies only to backend launches
- the frontend section applies only to frontend launches
- old shared sections are still understood for compatibility, but new `.envctl` files only seed backend/frontend sections
- `envctl config` seeds these sections when missing, but does not edit or normalize them afterward
- for a given service, only vars defined in its applicable sections are emitted
- you can rename, delete, add, or reorder emitted env vars manually
- later lines can reference earlier emitted values with `${VAR}`
- `ENVCTL_SOURCE_*` names are template-only inputs built from envctl's canonical dependency outputs
- if a referenced `ENVCTL_SOURCE_*` value is unavailable for the current run, that line is skipped
- custom aliases/templates are injected into launched processes only; backend `.env` writeback stays canonical
- after envctl seeds the launch env sections, `envctl config` leaves them unchanged

Supported template inputs include:

- `ENVCTL_SOURCE_DATABASE_URL`
- `ENVCTL_SOURCE_REDIS_URL`
- `ENVCTL_SOURCE_N8N_URL`
- `ENVCTL_SOURCE_SUPABASE_URL`
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

Only simple `${VAR}` placeholders are supported. Shell-style defaults, command substitution, and other expansion syntax are intentionally not supported.

## Migrate Env Resolution

Native `envctl migrate` uses the same backend env-file discovery contract as backend startup/bootstrap:

1. `BACKEND_ENV_FILE_OVERRIDE`
2. `MAIN_ENV_FILE_PATH` when the target project is `Main`
3. default `backend/.env`

When an env file is found, envctl exports `APP_ENV_FILE` into the migrate subprocess so backends that explicitly look up their env file can resolve it during Alembic imports.

Runtime dependency projection also applies to migrate:

- if the selected project already has saved requirements state, envctl reuses its canonical dependency URLs such as `DATABASE_URL` and `REDIS_URL`
- the default backend `.env` is not authoritative for those projected dependency URLs during migrate
- an explicit non-default backend env override file remains authoritative for its `DATABASE_URL` value, matching the existing `SKIP_LOCAL_DB_ENV` semantics

Relevant keys:

| Variable | Default | Purpose |
| --- | --- | --- |
| `BACKEND_ENV_FILE_OVERRIDE` | unset | Explicit backend env file path for worktree/tree targets and other non-Main projects. |
| `MAIN_ENV_FILE_PATH` | unset | Explicit backend env file path for Main mode. |
| `APP_ENV_FILE` | set by envctl when a backend env file is resolved | Exported into backend startup/migrate subprocesses for apps that discover env files from process env. |
| `SKIP_LOCAL_DB_ENV` | `false` | Compatibility toggle for preserving explicit backend env-file database URLs instead of replacing them with envctl-projected local DB URLs. |

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

The current config wizard writes the canonical managed keys. Launch env templates are edited manually in `.envctl` and are not exposed in the wizard.

## Current Wizard Coverage

The current setup/editor wizard covers:

- default mode
- services and dependencies
- optional backend-only long-running service startup
- backend/frontend directories
- canonical ports

The current flow is:

1. `Welcome / Source`
2. `Default Mode`
3. `Components`
4. optional `Long-Running Service`
5. `Directories`
6. `Ports`
7. `Review / Save`

There is no simple/advanced split in the current UI.

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
| `ENVCTL_PLAN_AGENT_TERMINALS_ENABLE` | `false` | Enable post-`--plan` cmux terminal launch for newly created worktrees. When enabled without an explicit workspace override, envctl targets a sibling workspace named `"<current workspace> implementation"`. |
| `ENVCTL_PLAN_AGENT_CLI` | `codex` | AI CLI selection for launched surfaces (`codex` or `opencode`). |
| `ENVCTL_PLAN_AGENT_PRESET` | `implement_task` | Prompt preset name typed after the AI CLI starts. Codex launches send `/prompts:<preset>`; OpenCode launches send `/<preset>`. `implement_plan` remains available as a backward-compatible preset. |
| `ENVCTL_PLAN_AGENT_CODEX_CYCLES` | `1` | Codex-only queued workflow count for the post-`--plan` launcher. The default `1` queues `implement_task` plus one finalization message. `0` keeps the existing one-shot preset launch. Values above `1` queue later `continue_task` and `implement_task` rounds in the same Codex session. OpenCode ignores this setting. Envctl only appends messages in this mode; it does not execute commit/PR shell commands itself. |
| `ENVCTL_PLAN_AGENT_SHELL` | `zsh` | Shell command used when respawning the new cmux surface. |
| `ENVCTL_PLAN_AGENT_REQUIRE_CMUX_CONTEXT` | `true` | Require caller `CMUX_WORKSPACE_ID` so envctl can derive the default `"<current workspace> implementation"` target. If false, envctl falls back to the selected cmux workspace title when available. |
| `ENVCTL_PLAN_AGENT_CLI_CMD` | unset | Optional raw AI CLI command override typed into the launched shell. |
| `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE` | unset | Explicit cmux workspace target for new surfaces. Accepts a workspace ref/UUID/index or a workspace title such as `envctl`. When set, it also enables plan-agent terminal launch even if `ENVCTL_PLAN_AGENT_TERMINALS_ENABLE` is unset. If a named workspace does not already exist, envctl creates it first and reuses that workspace's initial cmux starter surface for the first launch when the starter probe is unambiguous; otherwise it falls back to opening a new surface. |

Alias env vars:

- `CMUX=true` is a shorthand alias for enabling plan-agent launch with the default `"<current workspace> implementation"` target
- `CMUX_WORKSPACE=<value>` is a shorthand alias for `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE=<value>`
- canonical `ENVCTL_PLAN_AGENT_*` keys win when both canonical and alias forms are set

Cycle mode notes:

- the queued cycle workflow is active only for Codex and only when `ENVCTL_PLAN_AGENT_CODEX_CYCLES` is a positive integer
- invalid or negative values are ignored and the launcher stays on the one-shot workflow
- very large values are bounded internally for safety before the workflow is expanded
- if queue injection fails after the initial `implement_task` submit, envctl falls back to the initial one-shot launch and leaves the Codex surface running

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
| `MAIN_SUPABASE_ENABLE` | `false` | Canonical Supabase toggle for Main mode. Compatibility alias: `SUPABASE_MAIN_ENABLE`. |
| `TREES_SUPABASE_ENABLE` | `false` | Canonical Supabase toggle for Trees mode. |

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
| `BACKEND_ENV_FILE_OVERRIDE` | unset | Explicit backend env file path for non-Main backend startup/migrate flows. |
| `MAIN_ENV_FILE_PATH` | unset | Explicit backend env file path for Main backend startup/migrate flows. |

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
