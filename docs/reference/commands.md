# Commands

## Clone-Compatibility Wrapper

If you are intentionally running from a clone of the `envctl` repo and want the compatibility wrapper flow, use:

```text
./bin/envctl [--repo <path>] [engine args...]
./bin/envctl doctor [--repo <path>]
./bin/envctl install [--shell-file <path>] [--dry-run]
./bin/envctl uninstall [--shell-file <path>] [--dry-run]
```

Notes:

- this is compatibility-only, not the primary install story
- running `./bin/envctl`, `bin/envctl`, or an absolute wrapper path uses that exact wrapper directly
- the preferred user path is the package-installed `envctl` command on your `PATH`
- bare `envctl` keeps the installed-command preference when a repo wrapper shadows another `envctl` later on `PATH`
- `ENVCTL_USE_REPO_WRAPPER=1` remains the override when you need to force repo-wrapper behavior for an ambiguous PATH-based launch

## Inspection Commands

These commands are safe to use before a repo-local `.envctl` exists:

```bash
envctl --list-commands
envctl --list-targets
envctl --list-targets --json
envctl --list-trees --json
envctl show-config --json
envctl show-state --json
envctl explain-startup --json
```

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
envctl --list-trees --json
envctl --plan
envctl --parallel-plan
envctl --sequential-plan
```

Debug and diagnostics:

```bash
envctl --doctor --json
envctl --debug-pack
envctl --debug-report
envctl --debug-last
```
