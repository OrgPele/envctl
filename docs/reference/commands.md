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

- installs built-in prompt files into user-local AI CLI directories
- omitting `--preset` installs all built-in presets
- built-in presets:
  - `implement_plan`
  - `implement_task`
  - `review_task_imp`
  - `review_worktree_imp`
  - `continue_task`
  - `finalize_task`
  - `merge_trees_into_dev`
  - `create_plan`
- target roots:
  - Codex: `~/.codex/prompts`
  - Claude Code: `~/.claude/commands`
  - OpenCode: `~/.config/opencode/commands`
- existing files are overwritten in place after one confirmation prompt for the command
- use `--yes` or `--force` to approve overwrites without prompting
- `--json` and non-interactive TTY-less runs fail cleanly when overwrite approval is required but not pre-approved
- this command is available from the normal CLI, but not from dashboard interactive mode
- `review_worktree_imp` is intended for manual origin-side review from the local repo CLI; it defaults to the worktree created from the current plan file, and `$ARGUMENTS` can override that target with a specific worktree path or name
- interactive dashboard `review` can optionally offer one origin-side AI review tab after a successful single-worktree review; this reuses `review_worktree_imp` instead of changing review bundle generation

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
- `doctor`
- `config`
- `pr`
- `commit`
- `review`
- `migrate`
- `install-prompts`

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

Optional plan-agent launch config for `--plan`:

- `ENVCTL_PLAN_AGENT_TERMINALS_ENABLE=true` enables the feature
- `ENVCTL_PLAN_AGENT_CLI=codex|opencode` selects the AI CLI
- `ENVCTL_PLAN_AGENT_PRESET=implement_task` selects the prompt preset name by default
- `ENVCTL_PLAN_AGENT_CODEX_CYCLES=<n>` controls the Codex-only queued cycle workflow; the default is `1`
- Codex launches send `/prompts:<preset>` while OpenCode launches send `/<preset>`
- `ENVCTL_PLAN_AGENT_SHELL=zsh` selects the shell started in the new cmux surface
- `ENVCTL_PLAN_AGENT_REQUIRE_CMUX_CONTEXT=true` requires caller `CMUX_WORKSPACE_ID`
- `ENVCTL_PLAN_AGENT_CLI_CMD=/custom/cli --flag` overrides the typed AI CLI command text
- when enabled without an explicit workspace override, envctl derives the target as `"<current workspace> implementation"`
- `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE=workspace:123` targets an explicit cmux workspace and also enables the feature
- `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE=envctl` also works when you want to target a workspace by its title
- when a named target workspace does not exist yet, envctl creates it first and reuses that workspace's initial cmux starter surface for the first launch when the starter probe is unambiguous; otherwise it falls back to opening a new surface
- `CMUX=true` enables the feature and uses the default `"<current workspace> implementation"` target
- `CMUX_WORKSPACE=envctl` is a shorthand alias for targeting a named cmux workspace
- `CYCLES=<n>` is a shorthand alias for `ENVCTL_PLAN_AGENT_CODEX_CYCLES=<n>`
- `CYCLES` only changes the Codex cycle count and does not enable plan-agent launch by itself
- canonical `ENVCTL_PLAN_AGENT_*` values win when both canonical and alias forms are set
- by default (`ENVCTL_PLAN_AGENT_CODEX_CYCLES=1`), envctl submits `implement_task` and then queues `/prompts:finalize_task` in the same Codex tab
- `ENVCTL_PLAN_AGENT_CODEX_CYCLES=0` keeps the one-shot launch behavior

Optional dashboard review-tab launch:

- reuses `ENVCTL_PLAN_AGENT_CLI`, `ENVCTL_PLAN_AGENT_CLI_CMD`, `ENVCTL_PLAN_AGENT_SHELL`, `ENVCTL_PLAN_AGENT_REQUIRE_CMUX_CONTEXT`, and `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE`
- does not require `ENVCTL_PLAN_AGENT_TERMINALS_ENABLE=true`; the explicit yes/no dashboard prompt is the opt-in
- when no explicit workspace override is set, the review tab targets a sibling workspace named `"<current workspace> reviews"`
- with `ENVCTL_PLAN_AGENT_CODEX_CYCLES=2`, envctl first queues a plain commit/push/PR follow-up, then `continue_task`, `implement_task`, and `/prompts:finalize_task`
- with `ENVCTL_PLAN_AGENT_CODEX_CYCLES>=3`, envctl keeps that first commit/push/PR follow-up, uses commit/push-only follow-ups for intermediate rounds, and reserves `/prompts:finalize_task` for the last round
- OpenCode ignores `ENVCTL_PLAN_AGENT_CODEX_CYCLES` and stays on the one-shot preset workflow
- envctl only appends queued messages; it does not type `envctl test`, `git`, `gh`, `envctl commit`, or `envctl pr` commands into the shell

Debug and diagnostics:

```bash
envctl --doctor --json
envctl --debug-pack
envctl --debug-report
envctl --debug-last
```
