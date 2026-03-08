# Commands

## Launcher Commands

```text
envctl [--repo <path>] [engine args...]
envctl doctor [--repo <path>]
envctl install [--shell-file <path>] [--dry-run]
envctl uninstall [--shell-file <path>] [--dry-run]
envctl --help
```

Launcher note:

- `envctl doctor --repo ...` is a launcher-level check. It verifies repo-root resolution and engine reachability.
- `envctl --doctor` is the Python runtime diagnostic command for the current repo.

## Runtime Inspection

```bash
envctl --list-commands
envctl --list-targets
envctl --list-targets --json
envctl --list-trees --json
envctl show-config --json
envctl show-state --json
envctl explain-startup --json
```

These commands are safe to use before a repo-local `.envctl` exists because they do not require a normal startup run.

## High-Value Runtime Command Families
- `dashboard`
- `delete-worktree`
- `stop` / `stop-all`
- `restart`
- `test`
- `logs`
- `clear-logs`
- `health`
- `errors`
- `doctor`
- `debug-pack` / `debug-report` / `debug-last`
- `pr`
- `commit`
- `config`

## Common Command Patterns

Run all:

```bash
envctl --resume
envctl test --all
envctl logs --all --logs-follow
```

Inspect before you start:

```bash
envctl show-config --json
envctl explain-startup --json
envctl --list-targets --json
```

Target one project:

```bash
envctl test --project api
envctl logs --project api --logs-follow
envctl restart --project api
```

Run a single command against saved state:

```bash
envctl test --all --skip-startup --load-state
```

Debug and diagnostics:

```bash
envctl --doctor --json
envctl --debug-pack
envctl --debug-report
envctl --debug-last
```

Config management:

```bash
envctl config
printf '%s\n' '{"default_mode":"trees"}' | envctl config --stdin-json
```
