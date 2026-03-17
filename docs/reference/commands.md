# Commands

## Clone-Compatibility Wrapper

If you are intentionally running from a clone of the `envctl` repo and want the compatibility wrapper flow, use:

```text
./bin/envctl [--repo <path>] [engine args...]
./bin/envctl doctor [--repo <path>]
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
```

Compatibility note:

- `list-commands`, `list-targets`, and `list-trees` also accept `--list-commands`, `--list-targets`, and `--list-trees`

## AI CLI Presets

```bash
envctl install-prompts --cli codex
envctl install-prompts --cli claude --dry-run
envctl install-prompts --cli codex,opencode --json
envctl install-prompts --cli all --preset all
```

Behavior:

- installs built-in prompt files into user-local AI CLI directories
- built-in presets:
  - `implement_plan`
  - `implement_task`
  - `review_task_imp`
  - `continue_task`
  - `merge_trees_into_dev`
  - `create_plan`
- target roots:
  - Codex: `~/.codex/prompts`
  - Claude Code: `~/.claude/commands`
  - OpenCode: `~/.config/opencode/commands`
- existing files are backed up in-place before overwrite
- this command is available from the normal CLI, but not from dashboard interactive mode

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
- `errors`
- `explain-startup`
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
envctl explain-startup --json
envctl --resume
envctl dashboard
```

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
```

Optional plan-agent launch config for `--plan`:

- `ENVCTL_PLAN_AGENT_TERMINALS_ENABLE=true` enables the feature
- `ENVCTL_PLAN_AGENT_CLI=codex|opencode` selects the AI CLI
- `ENVCTL_PLAN_AGENT_PRESET=implement_plan` selects the slash command preset
- `ENVCTL_PLAN_AGENT_SHELL=zsh` selects the shell started in the new cmux surface
- `ENVCTL_PLAN_AGENT_REQUIRE_CMUX_CONTEXT=true` requires caller `CMUX_WORKSPACE_ID`
- `ENVCTL_PLAN_AGENT_CLI_CMD=/custom/cli --flag` overrides the typed AI CLI command text

Debug and diagnostics:

```bash
envctl --doctor --json
envctl --debug-pack
envctl --debug-report
envctl --debug-last
```
