# Important Flags

These are the highest-value flags for daily use.

## Session and Mode
| Flag | Purpose |
| --- | --- |
| `--resume` | Resume previous runtime state and session mapping quickly. |
| `--repo <path>` | Resolve and operate on a repo from outside that repo tree. |
| `--version` | Print the current `envctl` package version and exit without repo/bootstrap/runtime startup. |
| `--headless` | Non-interactive startup and execution (preferred). |
| `--batch` | Legacy alias for `--headless`. |
| `--main` | Run main mode only (skip trees). |
| `--tree` / `--trees` | Explicit trees-mode switch. |
| `--doctor` | Run diagnostics and exit. |
| `--dashboard` | Show runtime dashboard and exit. |
| `show-config --json` | Print the effective managed config without starting services. |
| `show-state --json` | Print the latest saved runtime state. |
| `explain-startup --json` | Print the runtime's startup decision before executing it. |

Config note: `ENVCTL_DEFAULT_MODE` sets default startup mode when no mode flag is passed.
Allowed values are `main` and `trees` (default: `main`).
Engine note: Python runtime is the only supported runtime path.
Launcher note: `--repo` is resolved by the launcher/runtime entrypoints rather than the command router registry.
Launcher note: `--version` is launcher-owned and intentionally stays out of the runtime supported-command inventory.

## Targeting
| Flag | Purpose |
| --- | --- |
| `--project <name>` | Target one project (repeatable). |
| `--projects <a,b>` | Target multiple projects. |
| `--service <name>` | Target one service. |
| `--all` | Target all projects/services. |
| `--untested` | Target untested projects for test workflows. |
| `--failed` | Rerun only the saved failed tests/files for the selected test targets. Refuses to run if the saved git state is stale. |
| `--review-base <branch>` | Force the base branch for single-mode `review`, overriding provenance, upstream, and default-branch fallback. |

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
| `--omx` | For `--plan`, launch the Codex implementation session through OMX-managed detached tmux instead of envctl creating the tmux window directly. |

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
| `ENVCTL_UI_BACKEND=auto\|textual\|legacy\|non_interactive` | Select dashboard backend policy. `auto` currently stays on legacy by default. |
| `ENVCTL_UI_EXPERIMENTAL_DASHBOARD=1` | In `auto` mode, prefer the Textual dashboard when available. |
| `ENVCTL_UI_SELECTOR_IMPL=textual\|planning_style\|legacy` | Selector implementation for dashboard target menus. Default is the Textual plan-style selector; `planning_style` enables the prompt-toolkit rollback; `legacy` is a compatibility alias that still maps to the Textual selector. |
| `ENVCTL_UI_HYPERLINK_MODE=auto\|on\|off` | Control clickable local filesystem paths in human-facing terminal output. `off` forces plain text; `on` forces OSC-8 links when stdout is terminal-like; `auto` enables links only on supported interactive terminals. |

## Requirements and Seeding
| Flag | Purpose |
| --- | --- |
| `--seed-requirements-from-base` | Seed tree DB/Redis state from base where supported. |

## Planning Path Config
Use `ENVCTL_PLANNING_DIR` in `.envctl` to change where planning files are read from.
Default is `todo/plans`.

When a plan is scaled to zero through `envctl --plan`, envctl blasts the related worktree(s) and archives the plan into a sibling `done` root. Example:

- active: `todo/plans/backend/checkout.md`
- archived: `todo/done/backend/checkout.md`

For fuller operational guidance, see [Python Engine Guide](../user/python-engine-guide.md).
