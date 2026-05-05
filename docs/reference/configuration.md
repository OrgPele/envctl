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
- active backend/frontend launch templates for core database/cache inputs (`ENVCTL_SOURCE_DATABASE_URL`,
  `ENVCTL_SOURCE_SQLALCHEMY_DATABASE_URL`, `ENVCTL_SOURCE_ASYNC_DATABASE_URL`, and `ENVCTL_SOURCE_REDIS_URL`) also
  request envctl-managed PostgreSQL/Redis dynamically when the matching dependency toggle is absent
- when Main-mode dependency port bases are left at the built-in defaults, envctl applies a per-session offset to managed
  dependency ports so generated DB/Redis URLs do not bind the same well-known host ports on every run
- explicit dependency toggles still win; for example `MAIN_POSTGRES_ENABLE=false` keeps PostgreSQL disabled even when a
  template references `ENVCTL_SOURCE_DATABASE_URL`
- if any other referenced `ENVCTL_SOURCE_*` value is unavailable for the current run, that line is skipped
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

The current config wizard writes the canonical managed keys. Launch env templates are edited manually in `.envctl` and are not exposed in the wizard.

## Current Wizard Coverage

The current setup/editor wizard covers:

- default mode
- services and dependencies
- optional backend-only long-running service startup
- backend/frontend directories
- entrypoints and backend/frontend test command suggestions
- optional frontend test directory suggestions
- canonical ports

The current flow is:

1. `Welcome / Source`
2. `Default Mode`
3. `Components`
4. optional `Long-Running Service`
5. `Directories`
6. `Entrypoints / Commands`
7. `Ports`
8. `Review / Save`

There is no simple/advanced split in the current UI.

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
| `ENVCTL_PLAN_AGENT_TERMINALS_ENABLE` | `false` | Enable post-`--plan` cmux terminal launch for newly created worktrees. When enabled without an explicit workspace override, envctl targets a sibling workspace named `"<current workspace> implementation"`. |
| `ENVCTL_PLAN_AGENT_CLI` | `codex` | AI CLI selection for launched surfaces (`codex` or `opencode`). |
| `ENVCTL_PLAN_AGENT_PRESET` | `implement_task` | Prompt preset name submitted after the AI CLI starts. OpenCode cmux launches send `/<preset>`; `--tmux --opencode` submits the rendered prompt body directly. Codex resolves the preset from the envctl-managed Codex prompt file and submits that prompt body directly. `implement_plan` remains available as a backward-compatible preset. |
| `ENVCTL_PLAN_AGENT_CODEX_CYCLES` | `2` | Codex-only queued workflow count for the post-`--plan` launcher. The default `2` queues a first follow-up telling Codex to commit, push, open or update the PR, and wait for GitHub status checks before the final `continue_task` -> `implement_task` -> `finalize_task` round, then queues the enabled browser-E2E and PR-review-comment follow-ups after finalization. `0` submits the single implementation prompt and queues enabled follow-ups for Codex/OMX surfaces. `1` queues `implement_task`, `finalize_task`, and enabled follow-ups. Higher values keep that first follow-up, use commit/push-only follow-ups for intermediate rounds, and reserve `finalize_task` plus enabled follow-ups for the final round. OpenCode ignores this setting. Envctl only appends prompt commands/messages in this mode; it does not execute those shell commands itself. |
| `ENVCTL_PLAN_AGENT_BROWSER_E2E_ENABLE` | `true` | Toggle the Codex/OMX `$browser-use` E2E follow-up. When true, envctl queues a browser validation prompt after implementation/finalization to re-read `MAIN_TASK.md`, validate the feature end-to-end against the full `envctl --entire-system --headless` stack, capture browser evidence where possible, and fix implementation-introduced issues. Set this to `false` in `.envctl` or the environment to skip that follow-up. |
| `ENVCTL_PLAN_AGENT_PR_REVIEW_COMMENTS_ENABLE` | `true` | Toggle the final Codex/OMX PR review-comments follow-up. When true, envctl queues a `$gh-address-comments` prompt after the current implementation/E2E prompts to inspect unresolved PR comments, address all actionable feedback, commit/push fixes, and wait for final PR confirmation. Set this to `false` in `.envctl` or the environment to skip that follow-up. |
| `ENVCTL_PLAN_AGENT_SHELL` | `zsh` | Shell command used when respawning the new cmux surface. |
| `ENVCTL_PLAN_AGENT_REQUIRE_CMUX_CONTEXT` | `true` | Require caller `CMUX_WORKSPACE_ID` so envctl can derive the default `"<current workspace> implementation"` target. If false, envctl falls back to the selected cmux workspace title when available. |
| `ENVCTL_PLAN_AGENT_CLI_CMD` | unset | Optional raw AI CLI command override typed into the launched shell. |
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

- the queued cycle workflow is active only for Codex and only when `ENVCTL_PLAN_AGENT_CODEX_CYCLES` is a positive integer; enabled browser-E2E and PR-review-comment follow-ups are queued for Codex/OMX surfaces even when the cycle count is `0`
- invalid or negative values are ignored and the launcher stays on the single implementation prompt plus enabled follow-ups
- very large values are bounded internally for safety before the workflow is expanded
- if queue injection fails after the initial `implement_task` submit, envctl falls back to the initial one-shot launch and leaves the Codex surface running
- the global default remains `ENVCTL_PLAN_AGENT_CODEX_CYCLES=2`; `$envctl-create-plan-auto-codex` uses the same `ENVCTL_PLAN_AGENT_CODEX_CYCLES=2` value for the envctl command it launches
- `$envctl-create-plan-auto-opencode` ignores Codex cycles and uses `--tmux --opencode` with the default `/ulw-loop` prefix
- `$envctl-create-plan-auto-omx` ignores Codex cycles and uses `--omx --ralph`, because the OMX/Ralph workflow owns its own loop

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
