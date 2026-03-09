# Commands

## Installation

Primary install paths:

```bash
pipx install .
pipx ensurepath
python -m pip install --user .
python -m pip install .
python -m pip install --user "git+https://github.com/kfiramar/envctl.git"
```

Primary uninstall paths:

```bash
python -m pip uninstall envctl
pipx uninstall envctl
```

## Clone-Compatibility Wrapper

If you are running from a clone of the `envctl` repository and explicitly want the old PATH-editing wrapper flow, use:

```text
./bin/envctl [--repo <path>] [engine args...]
./bin/envctl doctor [--repo <path>]
./bin/envctl install [--shell-file <path>] [--dry-run]
./bin/envctl uninstall [--shell-file <path>] [--dry-run]
./bin/envctl --help
```

Compatibility note:

- `./bin/envctl install` and `./bin/envctl uninstall` are clone-only compatibility commands.
- The preferred package-installed `envctl` command should already be on your PATH in every shell.
- `envctl doctor --repo ...` works from the installed command and is the preferred verification path.

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
