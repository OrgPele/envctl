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
| `--interactive` | Opt specific action commands back into prompts/interactive target selection. |
| `--main` | Run main mode only (skip trees). |
| `--tree` / `--trees` | Explicit trees-mode switch. |
| `--doctor` | Run diagnostics and exit. |
| `--dashboard` | Show runtime dashboard and exit. |
| `show-config --json` | Print the effective managed config without starting services. |
| `show-state --json` | Print the latest saved runtime state. |
| `endpoints --project <name> --json` | Print project-scoped frontend/backend/dependency endpoints from active runtime state. |
| `qa-user ensure --update-password --update-metadata` | Explicitly mutate an existing QA Auth user; omitted update flags reuse existing users unchanged. |
| `playwright --project <name> -- <command>` | Run a passthrough command with `QA_BASE_URL` plus `ENVCTL_ENDPOINTS_JSON` pointing at the selected endpoint artifact. |
| `explain-startup --json` | Print the runtime's startup decision before executing it. |

Config note: `ENVCTL_DEFAULT_MODE` sets default startup mode when no mode flag is passed.
Allowed values are `main` and `trees` (default: `main`).
Engine note: Python runtime is the only supported runtime path.
Launcher note: `--repo` is resolved by the launcher/runtime entrypoints rather than the command router registry.
Launcher note: `--version` is launcher-owned and intentionally stays out of the runtime supported-command inventory.
Action note: explicit action commands such as `kill-all`, `stop`, `blast-all`, `logs`, `health`,
`errors`, `test`, `pr`, `commit`, `review`, and `migrate` default to non-interactive execution;
pass `--interactive` only when you want prompts.

## Targeting
| Flag | Purpose |
| --- | --- |
| `--project <name>` | Target one project (repeatable). |
| `--projects <a,b>` | Target multiple projects. |
| `--service <name>` | Target one service. |
| `--backend` | Runtime scope: run or stop backend app services only. |
| `--frontend` | Runtime scope: run or stop frontend app services only. |
| `--fullstack` | Runtime scope: run or stop backend and frontend app services. |
| `--both` | Alias for `--fullstack`. |
| `--dependencies` | Runtime scope: run dependencies only, or detach their saved records/port locks on stop without removing reusable managed Docker stacks. |
| `--deps` | Alias for `--dependencies`. |
| `--entire-system` | Runtime scope: run dependencies plus app services; on stop, terminate app services and detach dependency records/locks while keeping managed Docker stacks reusable. |
| `--only-frontend` | Startup/plan modifier: launch only the frontend app service; skip backend, managed dependencies, and dependency prep. |
| `--only-backend` | Startup/plan modifier: launch only the backend app service; skip frontend, managed dependencies, and dependency prep. |
| `--no-deps` | Startup/plan modifier: skip managed dependencies and plan-agent dependency prep. |
| `--no-infra` | Startup/plan modifier: skip backend, frontend, managed dependencies, and plan-agent dependency prep. |
| `--isolated-deps` | Tree startup modifier: use isolated managed dependencies for worktrees. |
| `--separate-deps` | Alias for `--isolated-deps`. |
| `--strict` | For `health`, make optional-only degradation return non-zero while preserving non-blocking semantics in JSON. |
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
| `--cmux` | For `--plan`, enable the default cmux plan-agent workflow for this command without setting `CMUX=true`. |
| `--tmux` | For `--plan`, have envctl create or reuse an envctl-owned tmux session/window for the implementation prompt workflow. |
| `--opencode` | With `--plan --tmux`, launch OpenCode instead of Codex. |
| `--ulw` | With `--plan --opencode`, explicitly force the OpenCode `/ulw-loop` prompt prefix; this is already the default for OpenCode launches. |
| `--no-ulw-loop` | With `--plan --opencode`, disable the default OpenCode `/ulw-loop` prompt prefix for that launch. |
| `--new-session` | For AI-driven `--plan` launches, create a fresh cmux/tmux/OMX launch target instead of attaching to an existing one. |
| `--omx` | For `--plan`, launch the Codex implementation session through OMX-managed detached tmux instead of envctl creating the tmux window directly; envctl selects a deterministic OMX state root under the worktree so prompt handoff remains discoverable when OMX boxes unsafe runtime state. |
| `--ultragoal` | OMX workflow modifier for `--plan --omx`; starts the default/recommended Ultragoal workflow inside the OMX-managed Codex session after optional Codex `/goal` framing. |
| `--ralph` | OMX workflow modifier for `--plan --omx`; starts the Ralph compatibility workflow inside the OMX-managed Codex session after optional Codex `/goal` framing. |
| `--team` | OMX workflow modifier for `--plan --omx`; starts the Team workflow inside the OMX-managed Codex session after optional Codex `/goal` framing. |

Plan-agent handoff note: if `--plan --tmux/--omx --headless` starts the implementation AI session but local services cannot start, envctl reports a degraded handoff with `attach:` guidance instead of a plain fatal startup summary. For OMX-managed launches, envctl revalidates the tmux attach target before printing `attach:` guidance; stale, exited, wrong-worktree, or removed-worktree OMX sessions are reported as a failed/degraded handoff with diagnostic metadata instead of a copy-pastable stale attach command. Those OMX failures include a `recovery:` command that switches the same plan selector to native envctl-owned `--tmux`, preserves relevant scope/headless flags, includes `--new-session`, and omits OMX-only workflow flags. Non-plan commands and plan runs without a running AI session remain fatal.

## Performance and Reliability
| Flag | Purpose |
| --- | --- |
| `--fast` | Enable startup caches. |
| `--refresh-cache` | Force full scan and refresh cached metadata. |
| `--deps-parallel` / `--parallel-deps` | Force managed dependency startup to run in parallel. |
| `--deps-sequential` / `--sequential-deps` | Force managed dependency startup to run one dependency at a time. |
| `--parallel-trees` | Enable parallel tree startup workers. |
| `--parallel-trees-max <n>` | Max parallel tree startup workers. |
| `--service-parallel` / `--service-sequential` | Run backend+frontend startup attach in parallel or sequential mode (default: parallel). |
| `--docker` | Build or reuse images and run backend, frontend, and additional app services as managed Docker containers. |
| `--parallel` / `--sequential` | For `envctl test`, run backend/frontend test suites in parallel or sequential mode (default: parallel for multiple suites, with sequential fallback). Legacy aliases: `--test-parallel` / `--test-sequential`. |
| `--test-parallel-max <n>` | Cap concurrent test suites in parallel mode and pytest-xdist workers when pytest-xdist is explicitly enabled (default suite cap: CPU-aware, max `4`; default pytest workers: current free CPU cores). |
| `--clear-port-state` | Clear saved port reservations/state. |
| `--force` | Free configured ports if needed. |
| `ENVCTL_DOCKER_PREWARM=0\|1` | Enable/disable one-shot Docker daemon prewarm before requirements startup (default: `1`). |
| `ENVCTL_DOCKER_PREWARM_TIMEOUT_SECONDS=<n>` | Timeout for Docker prewarm command (default: `10`). |
| `ENVCTL_<SERVICE>_DOCKER_IMAGE=<image>` | Use an existing image for one app service. `ENVCTL_DOCKER_IMAGE` is the global fallback. |
| `ENVCTL_<SERVICE>_DOCKERFILE=<path>` | Build an app service image from a Dockerfile. `ENVCTL_DOCKERFILE` is the global fallback. |
| `ENVCTL_<SERVICE>_DOCKER_CONTEXT=<path>` | Override the Docker build context; defaults to the Dockerfile directory. |
| `ENVCTL_<SERVICE>_DOCKER_BUILD_ARGS=<names>` | Add comma-separated Docker build-arg names (or `NAME=value` entries); public frontend env keys are passed automatically. |
| `ENVCTL_<SERVICE>_DOCKER_COMMAND=<command>` | Override the image command inside the container. |
| `ENVCTL_<SERVICE>_DOCKER_COMMAND_MODE=image\|service` | Keep image CMD/ENTRYPOINT (default) or run envctl's normal service command. |
| `ENVCTL_<SERVICE>_DOCKER_PORT=<port>` | Override the container-side port while preserving envctl's allocated host port. |
| `ENVCTL_<SERVICE>_DOCKER_WORKDIR=<path>` | Override the image working directory for the service command. |
| `ENVCTL_<SERVICE>_DOCKER_BUILD_POLICY=cached\|missing\|never` | `cached` (default) reuses Docker layers; `missing` builds only when absent; `never` requires an existing image. |
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

Envctl-managed worktree creation for `--plan`, `--setup-worktree(s)`, and `ensure-worktree` disables repo-local Git
hooks by default with a command-scoped Git config override. Set `ENVCTL_WORKTREE_GIT_HOOKS=inherit` to opt into
repo-local hooks for those worktree creation commands.

For fuller operational guidance, see [Python Engine Guide](../user/python-engine-guide.md).
