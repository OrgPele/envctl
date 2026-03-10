# Configuration

## Model

Configuration precedence:
1. Existing shell environment variables.
2. `.envctl` / `.envctl.sh`.
3. Engine defaults.

Use `.envctl` for orchestration behavior.
Use `.env` for app runtime variables and secrets.

The Python runtime expects a repo-local `.envctl` for normal operational commands.
That is true regardless of whether `envctl` was installed with `pip`, `pipx`, or the clone-compatibility wrapper.

- `envctl config` opens the interactive config editor/bootstrap flow.
- `envctl show-config --json` prints the effective managed config without mutating anything.
- On missing `.envctl`, inspect-only commands can still run with defaults.

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

The Textual config wizard writes the canonical managed keys.

## Core
| Variable | Default | Purpose |
| --- | --- | --- |
| `ENVCTL_SKIP_DEFAULT_INFRASTRUCTURE` | `false` | Global skip for built-in PostgreSQL and Redis startup. |
| `ENVCTL_DEFAULT_MODE` | `main` | Startup default when no mode flag is passed (`main` or `trees`). |
| `ENVCTL_PLANNING_DIR` | `todo/plans` | Planning root used by `--plan`, `--sequential-plan`, and `--planning-prs`. Plans scaled to zero are archived into sibling `done/` under the same parent (for example `todo/done`). |
| `ENVCTL_CONFIG_FILE` | unset | Explicit config file path override. |
| `ENVCTL_ENGINE_PYTHON_V1` | `true` (launcher default) | Enables the Python runtime path used by the launcher bridge. |
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

## Spinner UX Policy
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
| `MAIN_POSTGRES_ENABLE` | `true` | Canonical PostgreSQL toggle for Main mode. Compatibility alias: `POSTGRES_MAIN_ENABLE`. |
| `TREES_POSTGRES_ENABLE` | `true` | Canonical PostgreSQL toggle for Trees mode. |
| `DB_PORT` | `5432` | PostgreSQL base port. |
| `DB_USER` | `postgres` | PostgreSQL user. |
| `DB_PASSWORD` | `postgres` | PostgreSQL password. |
| `DB_NAME` | `postgres` | PostgreSQL DB name. |
| `MAIN_SUPABASE_ENABLE` | `false` | Canonical Supabase toggle for Main mode. Compatibility alias: `SUPABASE_MAIN_ENABLE`. |
| `TREES_SUPABASE_ENABLE` | `false` | Canonical Supabase toggle for Trees mode. |

## Redis
| Variable | Default | Purpose |
| --- | --- | --- |
| `REDIS_ENABLE` | `true` | Global compatibility toggle honored by both Main and Trees profiles. |
| `MAIN_REDIS_ENABLE` | `true` | Canonical Redis toggle for Main mode. Compatibility alias: `REDIS_MAIN_ENABLE`. |
| `TREES_REDIS_ENABLE` | `true` | Canonical Redis toggle for Trees mode. Compatibility alias path still honors `REDIS_ENABLE`. |
| `REDIS_PORT` | `6379` | Redis base port. |

## n8n
| Variable | Default | Purpose |
| --- | --- | --- |
| `N8N_ENABLE` | `true` | Global compatibility toggle honored by both Main and Trees profiles. |
| `MAIN_N8N_ENABLE` | `false` | Canonical n8n toggle for Main mode. Compatibility alias: `N8N_MAIN_ENABLE`. |
| `TREES_N8N_ENABLE` | `true` | Canonical n8n toggle for Trees mode. Compatibility alias path still honors `N8N_ENABLE`. |
| `N8N_PORT_BASE` | `5678` | n8n base port. |

## Service Discovery
| Variable | Default | Purpose |
| --- | --- | --- |
| `MAIN_STARTUP_ENABLE` | `true` | Master switch for whether Main mode auto-starts anything at all. |
| `TREES_STARTUP_ENABLE` | `true` | Master switch for whether Trees mode auto-starts anything at all. |
| `MAIN_BACKEND_ENABLE` | `true` | Enable backend startup in Main mode when startup is enabled. |
| `TREES_BACKEND_ENABLE` | `true` | Enable backend startup in Trees mode when startup is enabled. |
| `MAIN_FRONTEND_ENABLE` | `true` | Enable frontend startup in Main mode when startup is enabled. |
| `TREES_FRONTEND_ENABLE` | `true` | Enable frontend startup in Trees mode when startup is enabled. |
| `BACKEND_DIR` | `backend` | Preferred backend directory name. |
| `BACKEND_PORT_BASE` | `8000` | Backend base port for allocation. |
| `FRONTEND_DIR` | `frontend` | Preferred frontend directory name. |
| `FRONTEND_PORT_BASE` | `9000` | Frontend base port for allocation. |

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
