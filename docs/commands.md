# Commands

## Launcher Commands

```text
envctl [--repo <path>] [engine args...]
envctl doctor [--repo <path>]
envctl install [--shell-file <path>] [--dry-run]
envctl uninstall [--shell-file <path>] [--dry-run]
envctl --help
```

## Runtime Discovery

```bash
envctl --list-commands
envctl --list-targets
```

## High-Value Command Families
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
- `pr`
- `commit`

## Common Command Patterns

Run all:

```bash
envctl --resume
envctl test --all
envctl logs --all --logs-follow
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
