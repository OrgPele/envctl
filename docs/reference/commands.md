# Commands

## Clone-Compatibility Wrapper

If you are intentionally running from a clone of the `envctl` repo and want the compatibility wrapper flow, use:

```text
./bin/envctl [--repo <path>] [engine args...]
./bin/envctl doctor [--repo <path>] [--json]
./bin/envctl install [--shell-file <path>] [--dry-run]
./bin/envctl uninstall [--shell-file <path>] [--dry-run]
./bin/envctl [--repo <path>] --version
```

Notes:

- this is compatibility-only, not the primary install story
- running `./bin/envctl`, `bin/envctl`, or an absolute wrapper path uses that exact wrapper directly
- the preferred user path is the package-installed `envctl` command on your `PATH`
- bare `envctl` keeps the installed-command preference when a repo wrapper shadows another `envctl` later on `PATH`
- `ENVCTL_USE_REPO_WRAPPER=1` remains the override when you need to force repo-wrapper behavior for an ambiguous PATH-based launch
- `--version` is launcher-owned and works without repo resolution, `.envctl`, or runtime startup

## Launcher Verification

Use these when you want to verify the installed command or an explicit repo wrapper before running against a repo:

```bash
envctl --version
./bin/envctl --version
envctl doctor --repo /absolute/path/to/repo --json
```

`--version` does not add a runtime command and does not appear in `list-commands`.

## Command Boundary

Use this section when you need to know which `envctl` commands are safe before repo bootstrap or full runtime startup.

| Command family | What it covers today | Boundary |
| --- | --- | --- |
| launcher-owned commands | `--help`, `--version`, launcher `doctor`, `install`, `uninstall` | handled by the launcher before the normal runtime path |
| bootstrap-safe inspection or utility commands | `list-commands`, `list-targets`, `list-trees`, `show-config`, `show-state`, `explain-startup`, `install-prompts`, `codex-tmux` | available without a repo-local `.envctl` and outside the full runtime dependency gate |
| operational runtime commands | `start`, `plan`, `resume`, `restart`, `dashboard`, `test`, `logs`, `health`, `errors`, `pr`, `commit`, `review`, `migrate` | enter the normal runtime path for startup, saved-state, or action workflows |

This boundary is grounded in the current launcher and Python runtime behavior, not a separate documentation-only model.

- launcher-owned commands are handled before the runtime forwards into the normal command router path
- bootstrap-safe inspection or utility commands are the right choice when you want to inspect config, state, startup decisions, or install local AI presets before changing `.envctl` or starting services
- the full envctl runtime dependency gate currently runs before `start`, `plan`, and `restart`, so not every non-launcher command is prereq-gated the same way

Examples:

```bash
envctl --help
envctl --plan --help
envctl --version
envctl doctor --repo /absolute/path/to/repo
envctl show-config --json
envctl explain-startup --json
envctl --plan backend/checkout --headless --dry-run
envctl install-prompts --cli codex
envctl install-prompts --help
envctl codex-tmux --dry-run
envctl codex-tmux --help
```

## Inspection Commands

These commands are safe to use before a repo-local `.envctl` exists:

```bash
envctl list-commands
envctl list-targets
envctl list-targets --json
envctl list-trees --json
envctl show-config --json
envctl show-state --json
envctl explain-startup --json
envctl preflight --json
```

Compatibility note:

- `list-commands`, `list-targets`, and `list-trees` also accept `--list-commands`, `--list-targets`, and `--list-trees`
- `preflight` and `--preflight` expose the same startup inspection logic through the versioned `envctl.preflight.v1` JSON contract

## AI CLI Presets

```bash
envctl install-prompts --cli codex
envctl install-prompts --cli claude --dry-run
envctl install-prompts --cli codex,opencode --json
envctl install-prompts --cli all
envctl install-prompts --cli all --preset all
```

Behavior:

- installs built-in workflows into user-local AI CLI directories
- omitting `--preset` installs all built-in presets
- `envctl install-prompts --help` prints command-specific usage, examples, and Codex-specific guidance
- built-in presets:
  - `implement_plan`
  - `implement_task`
  - `review_task_imp`
  - `review_worktree_imp`
  - `continue_task`
  - `finalize_task`
  - `merge_trees_into_dev`
  - `create_plan`
  - `create_plan_auto_codex`
  - `create_plan_auto_opencode`
  - `create_plan_auto_omx`
  - `ship_release`
- target roots:
  - Codex: `~/.codex/skills/envctl-*`
  - Claude Code: `~/.claude/commands`
  - OpenCode: `~/.config/opencode/commands`
- existing files are overwritten in place after one confirmation prompt for the command
- use `--yes` or `--force` to approve overwrites without prompting
- `--json` and non-interactive TTY-less runs fail cleanly when overwrite approval is required but not pre-approved
- this command is available from the normal CLI, but not from dashboard interactive mode
- `review_worktree_imp` is intended for manual origin-side review from the local repo CLI; it defaults to the worktree created from the current plan file, and `$ARGUMENTS` can override that target with a specific worktree path or name
- interactive dashboard `review` can optionally offer one origin-side AI review tab after a successful single-worktree review; this reuses `review_worktree_imp` instead of changing review bundle generation
- Codex presets are user-editable skill markdown files owned by envctl; envctl reads the embedded direct prompt body when it needs to submit a preset itself instead of relying on a Codex slash alias
- envctl-managed `--plan` launches submit the rendered workflow automatically; manual `$envctl-*` invocation is only for direct Codex or OMX use
- Codex installs explicit-only skills under `~/.codex/skills/envctl-*` by default; `--with-codex-skills` is kept as a compatibility no-op for older scripts

Auto-launch create-plan presets:

- `create_plan` remains plan-only and approval-first; `$envctl-create-plan` writes the plan and asks before running envctl.
- `create_plan_auto_codex` writes the plan, derives `<selector>` from `todo/plans/<category>/<slug>.md`, then runs `ENVCTL_PLAN_AGENT_CODEX_CYCLES=4 envctl --plan <selector> --tmux --entire-system --headless --tmux-new-session`.
- `create_plan_auto_opencode` writes the plan, derives `<selector>`, then runs `envctl --plan <selector> --tmux --opencode --entire-system --headless --tmux-new-session`; OpenCode launches prepend `/ulw-loop` by default.
- `create_plan_auto_omx` writes the plan, derives `<selector>`, then runs `envctl --plan <selector> --omx --ralph --entire-system --headless --tmux-new-session`.
- Each auto preset creates/syncs implementation worktrees and starts a fresh implementation session; use it only when you want implementation to start immediately.
- Refresh installed prompt files with `envctl install-prompts --cli codex --yes`, `envctl install-prompts --cli opencode --yes`, or `envctl install-prompts --cli all --yes`.

## `codex-tmux`

`codex-tmux` is a supported utility command.

Use it when you want `envctl` to launch or reuse a repo-scoped tmux session for `codex` without going through the normal runtime startup path.

```bash
envctl codex-tmux
envctl codex-tmux review
envctl codex-tmux --help
envctl codex-tmux --dry-run --json
```

Behavior:

- launches a new tmux session when the repo does not already have one
- reuses the existing repo-scoped session when one already exists
- requires `tmux` and `codex`
- supports `--json` only together with `--dry-run`
- is distinct from the optional post-`--plan` cmux-based plan-agent launch flow documented in the AI playbooks

## Main Runtime Commands

High-value command families:

- `dashboard`
- `resume`
- `plan`
- `test`
- `logs`
- `health`
- `errors`
- `restart`
- `stop` / `stop-all`
- `kill` / `kill-all` (aliases for `stop` / `stop-all`)
- `doctor`
- `config`
- `pr`
- `commit`
- `review`
- `migrate`
- `install-prompts`

Specific action commands are non-interactive by default. For example, `kill-all`, `stop`, `blast-all`,
`logs`, `health`, `errors`, `test`, `pr`, `commit`, `review`, `migrate`,
`delete-worktree`, `blast-worktree`, and `self-destruct-worktree` behave as if
`--headless` was supplied unless you explicitly pass `--interactive`.

Current supported command surface:

- `blast-all`
- `blast-worktree`
- `clear-logs`
- `commit`
- `config`
- `dashboard`
- `debug-last`
- `debug-pack`
- `debug-report`
- `delete-worktree`
- `doctor`
- `ensure-worktree`
- `errors`
- `explain-startup`
- `preflight`
- `health`
- `help`
- `install-prompts`
- `list-commands`
- `list-targets`
- `list-trees`
- `logs`
- `migrate`
- `migrate-hooks`
- `plan`
- `pr`
- `restart`
- `resume`
- `review`
- `show-config`
- `show-state`
- `start`
- `stop`
- `stop-all`
- `test`

## Common Command Patterns

Run and inspect:

```bash
envctl show-config --json
envctl explain-startup --json
envctl --resume
envctl dashboard
```

Runtime scope shortcuts:

```bash
envctl --backend --headless          # dependencies + backend service only
envctl --frontend --headless         # dependencies + frontend service only
envctl --fullstack --headless        # dependencies + backend + frontend
envctl --both --headless             # alias for --fullstack
envctl --dependencies --headless     # dependencies only; no app services
envctl --entire-system --headless    # dependencies + all configured app services
envctl --trees --only-backend         # worktree backend only; skip frontend and dependencies
envctl --trees --no-deps             # worktree app services only; skip managed dependencies/prep
envctl --trees --no-infra            # worktree state/AI only; skip backend, frontend, and dependencies
envctl --plan feature/task --opencode --no-deps  # AI session without local dependency prep

envctl stop --backend --headless
envctl stop --frontend --headless
envctl stop --fullstack --headless
envctl stop --dependencies --headless
envctl stop --entire-system --headless
envctl kill --backend --headless     # alias for stop --backend
envctl kill-all --headless           # alias for stop-all
```

Review branch-relative changes:

```bash
envctl review --project feature-a-1
envctl review --project feature-a-1 --review-base dev
```

Single-mode `review` resolves its base branch in this order:

1. `--review-base <branch>`
2. persisted worktree provenance from `.envctl-state/worktree-provenance.json`
3. the target branch's upstream
4. the repo default branch

The generated markdown now reports the resolved base branch, base ref, resolution source, merge-base, and the full diff from that merge-base through the current worktree state.

Interactive dashboard follow-up:

- during dashboard `review` setup for exactly one non-`Main` worktree, envctl can use the standard selector menu to ask whether to open one origin-side AI review tab if the launch transport is ready
- if you opt in and the review succeeds, envctl opens one cmux surface, starts the configured AI CLI from the repo root, and submits `review_worktree_imp` with the selected worktree plus reviewer notes pointing at the generated review bundle, worktree directory, and the original plan file that created the worktree
- choosing `No`, cancelling the selector, reviewing `Main`, reviewing multiple targets, or a failed review keeps the current markdown bundle-only flow
- direct `envctl review ...`, `python -m envctl_engine.actions.actions_cli review`, and other non-dashboard review paths never prompt for or launch this tab in v1

Run tests:

```bash
envctl test --all
envctl test --failed
envctl test --all --skip-startup --load-state
envctl test --failed --skip-startup --load-state
```

Logs and inspection:

```bash
envctl logs --all --logs-follow
envctl health --all
envctl errors --all
```

Target one project:

```bash
envctl test --project api
envctl logs --project api --logs-follow
envctl restart --project api
```

Run backend migrations:

```bash
envctl migrate --project feature-a-1
envctl migrate --main
```

`migrate` behavior:

- runs from `<project>/backend` when that directory exists; otherwise it falls back to the project root
- default command remains `<repo-python> -m alembic upgrade head`
- still honors `ENVCTL_ACTION_MIGRATE_CMD` when you need a custom wrapper command
- loads backend env from `backend/.env` by default
- honors `BACKEND_ENV_FILE_OVERRIDE` for worktrees and `MAIN_ENV_FILE_PATH` for Main mode
- exports `APP_ENV_FILE` when an env file is resolved for the migrate process
- when a saved run state already exists for the target, reuses envctl's current dependency URLs for `DATABASE_URL` and `REDIS_URL` unless an explicit backend env override file is in control
- on failure, envctl persists the raw migrate report under the run artifacts and surfaces an actionable summary in the dashboard/action metadata

Config management:

```bash
envctl config
printf '%s\n' '{"default_mode":"trees"}' | envctl config --stdin-json
```

Planning and worktrees:

```bash
envctl list-trees --json
envctl --plan
envctl --parallel-plan
envctl --sequential-plan
envctl ensure-worktree feature-a --json
```

`ensure-worktree` is the cheap automation-oriented worktree surface:

- creates or reuses exactly one envctl-managed worktree
- does not imply runtime/service startup
- returns `envctl.ensure_worktree.v1` in `--json` mode

Commit defaults:

- `envctl commit` now reads its default commit message from the repo-local `.envctl-commit-message.md` file when you do not pass `--commit-message` or `--commit-message-file`
- treat `### Envctl pointer ###` as the boundary after the last successful default commit; everything after it is the next default commit message
- write one complete next commit message in `.envctl-commit-message.md` rather than multiple fragmented summaries
- envctl-local control artifacts (`.envctl*`, `MAIN_TASK.md`, `OLD_TASK_*.md`, `trees/`) stay local; if a broad `git add .` stages them, `envctl commit` unstages those protected paths before committing normal changes

Optional plan-agent launch config for `--plan`:

- `ENVCTL_PLAN_AGENT_TERMINALS_ENABLE=true` enables the feature
- `envctl --plan <selector> --omx` launches Codex through an OMX-managed detached tmux session instead of having envctl create the tmux window itself
- `envctl --plan <selector> --omx --ralph` enters the Ralph OMX workflow inside that OMX-managed Codex session
- `envctl --plan <selector> --omx --team` enters the Team OMX workflow inside that OMX-managed Codex session
- `ENVCTL_PLAN_AGENT_CLI=codex|opencode` selects the AI CLI for envctl-owned cmux/tmux launches; OMX launches always use Codex
- `ENVCTL_PLAN_AGENT_PRESET=implement_task` selects the prompt preset name by default
- `ENVCTL_PLAN_AGENT_CODEX_CYCLES=<n>` controls the Codex-only queued cycle workflow; the default is `2`
- `$envctl-create-plan-auto-codex` overrides that cycle count to `4` for its one launch command only; the global default remains `2`
- OpenCode cmux launches send `/<preset>`; `--tmux --opencode` submits the rendered prompt body directly so ULW/direct-prompt flows do not depend on an installed slash command
- Codex installs envctl presets as explicit-only skills under `~/.codex/skills/envctl-*`; envctl still resolves the shipped prompt body directly when it needs to submit a preset itself
- `ENVCTL_PLAN_AGENT_BROWSER_E2E_ENABLE=true` queues the Codex/OMX `$browser-use` E2E follow-up; set it to `false` in `.envctl` to skip that prompt
- `ENVCTL_PLAN_AGENT_PR_REVIEW_COMMENTS_ENABLE=true` queues the final Codex/OMX PR review-comments follow-up; set it to `false` in `.envctl` to skip that prompt
- `ENVCTL_PLAN_AGENT_SHELL=zsh` selects the shell started in the new cmux surface or tmux window when envctl owns the terminal bootstrap
- `ENVCTL_PLAN_AGENT_REQUIRE_CMUX_CONTEXT=true` requires caller `CMUX_WORKSPACE_ID`
- `ENVCTL_PLAN_AGENT_CLI_CMD=/custom/cli --flag` overrides the typed AI CLI command text for envctl-owned cmux/tmux launches; OMX-managed launches still use `omx --tmux` and then envctl submits the prompt into the created Codex session
- plan-agent launches prepare backend and frontend dependencies inside the selected worktree before the AI prompt is submitted; this is dependency prep only, not service startup or migrations
- generic configured backend Python commands such as `ENVCTL_BACKEND_START_CMD=python -m uvicorn ...` use the prepared backend runtime when a Poetry project or backend virtualenv is available
- `--ralph` and `--team` are OMX-only launch modifiers; using them without `--omx` fails fast
- OMX-managed Team launches force `OMX_TEAM_WORKER_LAUNCH_ARGS=--dangerously-bypass-approvals-and-sandbox` so the worker lanes stay non-sandboxed too
- when enabled without an explicit workspace override, envctl derives the target as `"<current workspace> implementation"`
- `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE=workspace:123` targets an explicit cmux workspace and also enables the feature
- `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE=envctl` also works when you want to target a workspace by its title
- when a named target workspace does not exist yet, envctl creates it first and reuses that workspace's initial cmux starter surface for the first launch when the starter probe is unambiguous; otherwise it falls back to opening a new surface
- `CMUX=true` enables the feature and uses the default `"<current workspace> implementation"` target
- `CMUX_WORKSPACE=envctl` is a shorthand alias for targeting a named cmux workspace
- `CYCLES=<n>` is a shorthand alias for `ENVCTL_PLAN_AGENT_CODEX_CYCLES=<n>`
- `CYCLES` only changes the Codex cycle count and does not enable plan-agent launch by itself
- canonical `ENVCTL_PLAN_AGENT_*` values win when both canonical and alias forms are set
- by default (`ENVCTL_PLAN_AGENT_CODEX_CYCLES=2`), envctl first queues a plain commit/push/PR/status-check follow-up, then `continue_task`, `implement_task`, `finalize_task`, enabled browser-E2E and PR review-comments follow-ups
- `ENVCTL_PLAN_AGENT_CODEX_CYCLES=0` submits the single implementation prompt and queues enabled browser-E2E and PR review-comments follow-ups for Codex/OMX surfaces
- `ENVCTL_PLAN_AGENT_CODEX_CYCLES=1` queues `implement_task`, `finalize_task`, enabled browser-E2E and PR review-comments follow-ups

Degraded plan-agent handoff:

- `envctl --plan <selector> --tmux --headless` and `envctl --plan <selector> --omx --headless` can still succeed when the implementation AI session starts but local backend/frontend startup cannot resolve a service command
- this path prints `Implementation session is running, but local app startup failed.`, then an `AI session:` section with copy-pastable `attach:` and `kill:` guidance when a tmux session is known
- the `Local app startup:` section names the worktree, preserves the raw startup error, and points to `ENVCTL_BACKEND_START_CMD` / `ENVCTL_FRONTEND_START_CMD` when services should run locally
- plain `start`, `restart`, `resume`, dashboard, or `--plan` runs without a running implementation session keep normal fatal `Startup failed:` semantics

Optional dashboard review-tab launch:

- reuses `ENVCTL_PLAN_AGENT_CLI`, `ENVCTL_PLAN_AGENT_CLI_CMD`, `ENVCTL_PLAN_AGENT_SHELL`, `ENVCTL_PLAN_AGENT_REQUIRE_CMUX_CONTEXT`, and `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE`
- does not require `ENVCTL_PLAN_AGENT_TERMINALS_ENABLE=true`; the explicit yes/no dashboard prompt is the opt-in
- when no explicit workspace override is set, the review tab targets a sibling workspace named `"<current workspace> reviews"`
- with `ENVCTL_PLAN_AGENT_CODEX_CYCLES=2`, envctl first queues a plain commit/push/PR/status-check follow-up, then `continue_task`, `implement_task`, `finalize_task`, enabled browser-E2E and PR review-comments follow-ups
- with `ENVCTL_PLAN_AGENT_CODEX_CYCLES>=3`, envctl keeps that first commit/push/PR/status-check follow-up, uses commit/push-only follow-ups for intermediate rounds, and reserves `finalize_task` plus enabled browser-E2E and PR review-comments follow-ups for the last round
- OpenCode ignores `ENVCTL_PLAN_AGENT_CODEX_CYCLES` and stays on the one-shot preset workflow
- envctl only appends queued messages; it does not type `envctl test`, `git`, `gh`, `envctl commit`, or `envctl pr` commands into the shell

Debug and diagnostics:

```bash
envctl --doctor --json
envctl --debug-pack
envctl --debug-report
envctl --debug-last
```
