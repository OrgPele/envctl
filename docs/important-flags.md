# Important Flags

These are the highest-value flags for daily use.

## Session and Mode
| Flag | Purpose |
| --- | --- |
| `--resume` | Resume previous runtime state and session mapping quickly. |
| `--headless` | Non-interactive startup and execution (preferred). |
| `--batch` | Legacy alias for `--headless`. |
| `--main` | Run main mode only (skip trees). |
| `--tree` / `--trees` / `trees=true` / `trees=false` | Explicit tree mode switch. |
| `--doctor` | Run diagnostics and exit. |
| `--dashboard` | Show runtime dashboard and exit. |

Config note: `ENVCTL_DEFAULT_MODE` sets default startup mode when no mode flag is passed.
Allowed values are `main` and `trees` (default: `main`).
Engine note: Python runtime is default; set `ENVCTL_ENGINE_SHELL_FALLBACK=true` to use shell fallback.

## Targeting
| Flag | Purpose |
| --- | --- |
| `--project <name>` | Target one project (repeatable). |
| `--projects <a,b>` | Target multiple projects. |
| `--service <name>` | Target one service. |
| `--all` | Target all projects/services. |
| `--untested` | Target untested projects for test workflows. |

## Worktree Orchestration
| Flag | Purpose |
| --- | --- |
| `--plan [SELECTION]` | Create worktrees from planning selection and run (parallel). |
| `--sequential-plan [SELECTION]` | Plan and run one-by-one. |
| `--parallel-plan [SELECTION]` | Alias for `--plan`. |
| `--setup-worktrees <FEATURE> <COUNT>` | Create multiple worktrees directly. |
| `--setup-worktree <FEATURE> <ITER>` | Create one worktree iteration directly. |
| `--include-existing-worktrees <a,b>` | Include specific existing iterations. |
| `--keep-plan` | Keep planning files in place after execution. |

## Performance and Reliability
| Flag | Purpose |
| --- | --- |
| `--fast` | Enable startup caches. |
| `--refresh-cache` | Force full scan and refresh cached metadata. |
| `--parallel-trees` | Enable parallel tree startup workers. |
| `--parallel-trees-max <n>` | Max parallel tree startup workers. |
| `--service-parallel` / `--service-sequential` | Run backend+frontend startup attach in parallel or sequential mode (default: parallel). |
| `--test-parallel` / `--test-sequential` | Run backend/frontend test suites in parallel or sequential mode (default: parallel when both suites exist). |
| `--test-parallel-max <n>` | Cap concurrent test suites in parallel mode (default: `4` shared across backend/frontend suites). |
| `--clear-port-state` | Clear saved port reservations/state. |
| `--force` | Free configured ports if needed. |
| `ENVCTL_DOCKER_PREWARM=0\|1` | Enable/disable one-shot Docker daemon prewarm before requirements startup (default: `1`). |
| `ENVCTL_DOCKER_PREWARM_TIMEOUT_SECONDS=<n>` | Timeout for Docker prewarm command (default: `10`). |
| `ENVCTL_REQUIREMENTS_PORT_MISMATCH_POLICY=adopt_existing\|recreate` | On existing container port mismatch, adopt existing mapping (default) or force recreate. |

## Logs and Debugging
| Flag | Purpose |
| --- | --- |
| `--logs-tail <n>` | Tail last N lines for logs command. |
| `--logs-follow` | Follow logs continuously. |
| `--logs-duration <sec>` | Follow logs for a fixed duration. |
| `--debug-pack` | Package latest debug session into a portable bundle. |
| `--debug-report` | Build+analyze latest debug bundle and print probable root causes. |
| `--debug-last` | Print latest debug bundle path. |
| `--debug-capture <off\|standard\|deep>` | Override capture level for current command. |
| `--debug-auto-pack <off\|crash\|anomaly\|always>` | Auto-pack policy when anomalies/exceptions occur. |
| `ENVCTL_DEBUG_REQUIREMENTS_TRACE=1` | Emit requirement adapter lifecycle stage events. |
| `ENVCTL_DEBUG_DOCKER_COMMAND_TIMING=1` | Emit per-command Docker timing events for requirements adapters. |
| `ENVCTL_DEBUG_STARTUP_BREAKDOWN=1` | Emit startup breakdown event and include timing decomposition in debug diagnostics. |
| `--debug-trace` | Enable trace logging. |
| `--debug-trace-log <path>` | Write trace output to a specific path. |

## Interactive Backend Policy
| Flag | Purpose |
| --- | --- |
| `ENVCTL_UI_BACKEND=auto\|textual\|legacy` | Select interactive backend policy. |
| `ENVCTL_UI_TEXTUAL_FORCE=1` | In `auto` mode, force Textual backend when supported. |
| `ENVCTL_UI_SELECTOR_IMPL=textual\|planning_style\|legacy` | Selector implementation for dashboard target menus (default: Textual plan-style screen; use `planning_style` for prompt-toolkit rollback; `legacy` is an alias for Textual). |

## Cutover Gates
| Flag | Purpose |
| --- | --- |
| `ENVCTL_SHELL_PRUNE_MAX_UNMIGRATED` | Maximum unmigrated shell ledger entries allowed for shipability/doctor (default: `0`). |
| `ENVCTL_SHELL_PRUNE_PHASE` | Phase label shown in shell prune reports (default: `cutover`). |

## Main Infra Source
| Flag | Purpose |
| --- | --- |
| `--main-services-local` | Force local main infra mode. |
| `--main-services-remote` | Force remote main service mode via main env files. |
| `--seed-requirements-from-base` | Seed tree DB/Redis state from base where supported. |

## Planning Path Config
Use `ENVCTL_PLANNING_DIR` in `.envctl` to change where planning files are read from.
Default is `docs/planning`.
