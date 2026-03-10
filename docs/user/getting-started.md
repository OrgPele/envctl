# Getting Started

This guide is for a first successful run in a real repository.

If you already know the basics and just want repeatable command sequences, jump to [Common Workflows](common-workflows.md).

What this guide optimizes for:

- a safe first run with minimal guessing
- understanding which file to create and which commands are inspection-only
- reaching one known-good operating loop quickly

## 1. Install

Recommended install paths if you want `envctl` available in every shell:

```bash
# Preferred: isolated user-level CLI on your PATH
pipx install .
pipx ensurepath
```

```bash
# Current-user install
python -m pip install --user .
```

```bash
# System-managed install if that is how you manage Python CLIs
python -m pip install .
```

```bash
# VCS install from Git
pipx install "git+https://github.com/kfiramar/envctl.git"
python -m pip install --user "git+https://github.com/kfiramar/envctl.git"
```

Uninstall:

```bash
python -m pip uninstall envctl
pipx uninstall envctl
```

What this install flow does:

- installs `envctl` as a normal command-line tool
- makes `envctl` available across shells once your user PATH is set up
- leaves your target repositories separate from the `envctl` source repository
- gives you one consistent command surface across repos

Important Python note:

- `envctl` currently supports Python 3.12 through 3.14
- `pipx` uses its own default interpreter, not your currently activated virtualenv
- if `pipx` defaults to an unsupported Python, install with `--python <supported-python>`

Contributor note:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
```

Use editable install when you are developing `envctl` itself. That is not the primary end-user install story.

Repo-clone compatibility still exists if you explicitly want the old shell-wrapper flow:

```bash
./bin/envctl install
./bin/envctl uninstall
```

Treat that wrapper flow as compatibility-only. The primary story is the package-installed `envctl` command on your PATH.

## 2. Verify the Command Works

```bash
envctl --help
envctl doctor --repo /absolute/path/to/repo
```

If `envctl --help` works and `envctl doctor --repo ...` can resolve a target repo, the command is installed correctly.

## 3. Repository Detection

A valid repo root is any git repository root (`.git` directory or `.git` file).

You can run:
- Inside any subdirectory of a repo (auto-detection).
- From anywhere with `--repo <path>`.

## 4. Create or Bootstrap Project Config

Best default: let `envctl` create the repo-local `.envctl` for you.

If `.envctl` is missing and you run a normal operational command in an interactive terminal, `envctl` opens a guided setup wizard automatically.

The wizard now opens in the simple flow for first-run bootstrap:

1. where `.envctl` will be written and which source is being used for prefill
2. whether you want the simple or advanced wizard
3. your default run mode (`main` or `trees`)
4. a run preset for main mode
5. a run preset for trees mode
6. review and save

The advanced flow adds a separate run-enable step for `main` and `trees`, followed by backend/frontend toggles, dependency toggles, a directories screen, and a ports screen. The directories and ports screens only show fields for components currently enabled for envctl runs.

That flow is described in more detail in [First-Run Wizard](first-run-wizard.md).

Typical first-run path:

```bash
envctl show-config --json
envctl --resume
```

If you prefer to create the file yourself instead of using the wizard:

```bash
cp /path/to/envctl/docs/reference/.envctl.example /path/to/your-project/.envctl
```

Recommended first check before editing anything:

```bash
envctl show-config --json
```

That tells you:

- where `envctl` expects the config file
- whether it already exists
- which defaults are active
- which managed values will be used if you proceed

Important behavior from the current wizard/save path:

- legacy config can be used as prefill, but `.envctl` is the canonical saved file
- save validation blocks invalid port values or empty directories
- each mode can now be disabled entirely with `MAIN_STARTUP_ENABLE=false` or `TREES_STARTUP_ENABLE=false`
- save does not change already-running services until the next start or restart
- `envctl` tries to add `.envctl` and `trees/` to `.gitignore` on save

Default startup mode is `main`. To change default startup to tree mode manually:

```bash
# .envctl
ENVCTL_DEFAULT_MODE="trees"
```

Manual config is optional, but if you need it, here is a minimal explicit services example:

```bash
# .envctl
ENVCTL_SERVICE_1="API Server | backend  | backend  | 8000 |      | logs/api"
ENVCTL_SERVICE_2="Web App    | frontend | frontend | 3000 | 8000 | logs/web"
```

Service format:

```text
"DisplayName | DirectoryPath | ServiceType | Port | BackendPort | LogDirectory"
```

## 5. First Successful Run

For a safe first run, inspect first and then start:

```bash
envctl show-config --json
envctl explain-startup --json
envctl --resume
envctl dashboard
envctl logs --all --logs-follow
envctl test --all
envctl stop-all
```

Why this is the recommended sequence:

- `show-config` confirms the config source and effective values
- `explain-startup` shows the runtime decision before anything starts
- `--resume` is the fastest normal path after previous runs
- `dashboard`, `logs`, and `test` cover the common operating loop
- `stop-all` gives you a clean way to exit without leaving the repo in an unknown state

If you want a clean startup instead of resume:

```bash
envctl --main --no-resume
```

## 6. Worktree / Planning Flow

Start from planning files and run `--plan` first.

1. Put plan files under `ENVCTL_PLANNING_DIR` (default: `todo/plans`).
2. Run `envctl --plan` to create/start worktrees from those plans.
3. Use dashboard, logs, and tests to inspect and compare results.

Example:

```bash
mkdir -p todo/plans/backend
cat > todo/plans/backend/checkout.md <<'PLAN'
# Checkout Implementation Plan
PLAN

envctl --plan
envctl dashboard
```

When the repository already has many plan files or trees, follow up with:

```bash
envctl --list-trees --json
envctl test --all
envctl errors --all
```

## 7. If Something Feels Wrong

Start with the low-cost inspection commands:

```bash
envctl show-config --json
envctl show-state --json
envctl explain-startup --json
envctl --doctor --json
```

If the issue is interactive, timing-related, or hard to reproduce:

```bash
ENVCTL_DEBUG_UI_MODE=deep envctl
envctl --debug-report
```

For deeper help:

- [First-Run Wizard](first-run-wizard.md)
- [Common Workflows](common-workflows.md)
- [FAQ](faq.md)
- [Python Engine Guide](python-engine-guide.md)
- [Operations](../operations/README.md)

## Runtime Note

These docs assume the Python runtime.

To restore the latest runtime state directly:

```bash
envctl --resume
```
