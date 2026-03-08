# Configuration

## Model

Configuration precedence:
1. Existing shell environment variables.
2. `.envctl` / `.envctl.sh`.
3. Engine defaults.

Use `.envctl` for orchestration behavior.
Use `.env` for app runtime variables and secrets.

## Core
| Variable | Default | Purpose |
| --- | --- | --- |
| `ENVCTL_SKIP_DEFAULT_INFRASTRUCTURE` | `false` | Global skip for built-in PostgreSQL and Redis startup. |
| `ENVCTL_DEFAULT_MODE` | `main` | Startup default when no mode flag is passed (`main` or `trees`). |
| `ENVCTL_PLANNING_DIR` | `docs/planning` | Planning root used by `--plan`, `--sequential-plan`, and `--planning-prs`. |
| `ENVCTL_CONFIG_FILE` | unset | Explicit config file path override. |
| `ENVCTL_ENGINE_PYTHON_V1` | `true` (launcher default) | Enables Python runtime path in `lib/engine/main.sh`. |
| `ENVCTL_ENGINE_SHELL_FALLBACK` | `false` | Forces shell runtime during migration. |
| `RUN_SH_RUNTIME_DIR` | `/tmp/envctl-runtime` | Runtime artifact root (Python artifacts are under `python-engine/`). |
| `ENVCTL_STRICT_N8N_BOOTSTRAP` | `false` | Treat n8n owner/bootstrap endpoint mismatch as hard failure. |

## Execution Policy
| Variable | Default | Purpose |
| --- | --- | --- |
| `ENVCTL_SERVICE_ATTACH_PARALLEL` | `true` | Run backend+frontend service attach in parallel when both are selected. |
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
| `ENVCTL_UI_BACKEND` | `auto` | Interactive backend policy (`auto`, `textual`, `non_interactive`). `legacy` is accepted as a compatibility alias and maps to `textual`. |
| `ENVCTL_UI_TEXTUAL_HEADLESS_ALLOWED` | `false` | Test-only override to allow Textual capability checks in headless harnesses. |
| `ENVCTL_UI_TEXTUAL_FPS` | `30` | Optional Textual refresh tuning for heavy interactive sessions. |
| `ENVCTL_UI_SPINNER_MODE` | `auto` | Spinner policy mode (`auto`, `on`, `off`). |
| `ENVCTL_UI_SPINNER_MIN_MS` | `120` | Minimum operation time before spinner is rendered to reduce flicker. |
| `ENVCTL_UI_SPINNER_VERBOSE_EVENTS` | `false` | Emit extra spinner lifecycle diagnostics in debug traces. |
| `ENVCTL_UI_SPINNER` | `true` | Compatibility toggle; still honored when mode is `auto`. |
| `ENVCTL_UI_RICH` | `true` | Compatibility toggle for rich-backed UI rendering when mode is `auto`. |

## Database (PostgreSQL and Supabase)
Supabase includes PostgreSQL, so treat them as alternative stacks per scope.

| Variable | Default | Purpose |
| --- | --- | --- |
| `POSTGRES_MAIN_ENABLE` | `true` | Enable PostgreSQL for Main mode. |
| `DB_PORT` | `5432` | PostgreSQL base port. |
| `DB_USER` | `postgres` | PostgreSQL user. |
| `DB_PASSWORD` | `postgres` | PostgreSQL password. |
| `DB_NAME` | `postgres` | PostgreSQL DB name. |
| `SUPABASE_MAIN_ENABLE` | `false` | Enable Supabase stack for Main mode. |
| `SUPABASE_ALL_TREES` | `false` | Enable Supabase stack for all trees. |
| `SUPABASE_TREE_FILTER` | empty | Comma-separated features that should use Supabase. |

## Redis
| Variable | Default | Purpose |
| --- | --- | --- |
| `REDIS_ENABLE` | `true` | Global Redis switch (Main + Trees). |
| `REDIS_MAIN_ENABLE` | `true` | Redis switch for Main mode. |
| `REDIS_ALL_TREES` | `true` | Enable Redis in all tree workspaces. |
| `REDIS_TREE_FILTER` | empty | Comma-separated features that should use Redis. |
| `REDIS_PORT` | `6379` | Redis base port. |

## n8n
| Variable | Default | Purpose |
| --- | --- | --- |
| `N8N_ENABLE` | `true` | Global n8n switch (Main + Trees). |
| `N8N_MAIN_ENABLE` | `false` | Enable n8n for Main mode. |
| `N8N_ALL_TREES` | `false` | Enable n8n for all trees. |
| `N8N_TREE_FILTER` | empty | Comma-separated features that should use n8n. |
| `N8N_PORT_BASE` | `5678` | n8n base port. |

## Service Discovery
| Variable | Default | Purpose |
| --- | --- | --- |
| `RUN_BACKEND` | `true` | Enable backend auto-discovery. |
| `BACKEND_DIR_NAME` | `backend` | Preferred backend directory name. |
| `BACKEND_PORT_BASE` | `8000` | Backend base port for allocation. |
| `RUN_FRONTEND` | `true` | Enable frontend auto-discovery. |
| `FRONTEND_DIR_NAME` | `frontend` | Preferred frontend directory name. |
| `FRONTEND_PORT_BASE` | `9000` | Frontend base port for allocation. |
| `ENVCTL_SERVICE_<N>` | empty | Explicit service list; disables auto-discovery when set. |

## Optional Hooks (`.envctl.sh`)
Use hooks only for advanced custom orchestration.

Supported hooks:
- `envctl_define_services`
- `envctl_setup_infrastructure`

During Python-first migration, `.envctl.sh` remains compatibility-supported but is parsed safely by Python runtime (no shell `source` execution).
