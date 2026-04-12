# FAQ

## Do I need to install `envctl` inside every repository?

No.

Install `envctl` once so the launcher is on your `PATH` in every shell, then use it against any target repo:

```bash
pipx install "git+https://github.com/kfiramar/envctl.git"
pipx ensurepath
```

Then use it against any target repo:

```bash
envctl --version
envctl --repo /absolute/path/to/project --resume
```

Each target repository keeps its own `.envctl`, runtime state, and plans.

## Do I need a `.envctl` file before I can use `envctl`?

For normal operational commands, yes.

If `.envctl` is missing:

- inspect-only commands such as `show-config`, `show-state`, and `explain-startup` still work
- normal operational commands trigger `envctl config` bootstrap when an interactive TTY is available
- headless/non-interactive operational runs fail with an actionable message instead of guessing

## What is the difference between `envctl doctor` and `envctl --doctor`?

- `envctl doctor --repo /path` is the launcher-level diagnostic and checks repo and engine resolution
- `envctl doctor --repo /path --json` gives the same launcher-level check in structured form
- `envctl --doctor` is the Python runtime diagnostic for the current repo and runtime scope

If you are troubleshooting a real run, you almost always want `envctl --doctor`.

## What is the recommended install path?

Use `pipx`:

```bash
pipx install "git+https://github.com/kfiramar/envctl.git"
pipx ensurepath
```

Use editable/source installs only when you are developing `envctl` itself.

If you intentionally run from an `envctl` source checkout, install the runtime dependencies for that interpreter with:

```bash
python -m pip install -r python/requirements.txt
```

## How do I verify which `envctl` version is installed?

Run:

```bash
envctl --version
```

This is a launcher-level check, so it works outside a repo and before `.envctl` bootstrap.

## Does `envctl` need any external system tools?

Yes, depending on the workflow.

`pipx` installs the Python package dependencies for `envctl` itself, but some workflows still rely on system tools:

- `git` for repository detection, worktrees, commits, reviews, and PR preparation
- `docker` for built-in local services such as databases, Redis, Supabase, and n8n
- `gh` for GitHub PR flows
- `poetry` for backend repos that use Poetry
- `bun`, `pnpm`, `yarn`, or `npm` for frontend repos

If one of those tools is missing, install it separately and retry the affected workflow.

`envctl` installs target project dependencies when the repo needs them, so in Python repos `pytest` is normally provided by the backend project's own dependencies rather than as a separate global prerequisite for `envctl`.

Install-path summary:

- installed command: `pipx install ...` already installs `envctl`'s runtime Python dependencies
- source checkout / `./bin/envctl`: install `python/requirements.txt`
- contributor development: use the editable workflow from `docs/developer/contributing.md`

## Why did `envctl` open a config wizard?

Because you ran a normal operational command in a repository that does not yet have a repo-local `.envctl`.

That is expected Python-runtime behavior:

- inspection commands can run without `.envctl`
- operational commands need repo-local orchestration config
- interactive runs bootstrap it with `envctl config`

If you want the exact screen flow and save behavior, use [First-Run Wizard](first-run-wizard.md).

## Is the Bash/shell engine still supported?

The supported runtime path is the Python runtime, and these docs are written for that path.

## Why does `debug-pack` fail?

Because `debug-pack`, `debug-report`, and the modern debug-bundle pipeline depend on Python runtime diagnostics and a captured debug session.

## Which commands are safest when I am not sure what will happen?

Start with:

```bash
envctl show-config --json
envctl show-state --json
envctl explain-startup --json
envctl preflight --json
envctl --list-targets --json
```

Those commands are high-signal and low-risk because they inspect rather than start.

## When should I use `show-config`, `explain-startup`, and `preflight`?

Use them before any run where predictability matters. `preflight --json` is the stable machine-facing wrapper around startup inspection:

- first use in a repo
- after editing `.envctl`
- before CI or automation
- when resume/startup behavior is surprising

They are cheap, safe inspection commands and save time.

## What does `--resume` actually do?

In Python runtime, resume:

1. loads the latest compatible saved state
2. reconciles that state against live process/listener truth
3. optionally restores missing services
4. rewrites the saved state with the reconciled result

So `--resume` is not just "reuse old pointers"; it is a truth-aware restore flow.

## What is the difference between `main` and `trees` mode?

- `main` operates on the repository root as one environment
- `trees` operates on planned or existing worktrees

`envctl --plan` always resolves into `trees` mode.

## Why do selectors feel newer than the dashboard itself?

Because they are.

Current runtime behavior intentionally splits the UI surface:

- `ENVCTL_UI_BACKEND=auto` still defaults to the legacy dashboard
- target selectors default to the Textual plan-style selector

That split is expected during the migration and is not, by itself, a bug.

## I want to compare implementations quickly. What is the shortest useful loop?

Usually this:

```bash
envctl --plan
envctl dashboard
envctl test --all
envctl errors --all
envctl logs --all --logs-tail 300
```

## Where do runtime files get written?

Under:

```text
${RUN_SH_RUNTIME_DIR:-/tmp/envctl-runtime}/python-engine/<scope-id>/
```

Common files:

- `run_state.json`
- `runtime_map.json`
- `ports_manifest.json`
- `error_report.json`
- `events.jsonl`

See [Python Engine Guide](python-engine-guide.md) for details.

## Should I edit `.envctl.sh`?

Only if you are intentionally working with advanced compatibility hooks during migration.

For normal operation:

- prefer `.envctl`
- prefer the canonical managed keys written by `envctl config`

`.envctl.sh` is still compatibility-supported, but it is not the primary configuration path.

## What should I share when reporting a bug?

For most runtime issues, send:

- `envctl show-config --json`
- `envctl explain-startup --json`
- `envctl --doctor --json`

For interactive or timing issues, also send:

- `envctl --debug-report`
- the bundle path from `envctl --debug-last`

## Where should I start when something is broken?

A good default sequence is:

```bash
envctl show-config --json
envctl show-state --json
envctl explain-startup --json
envctl --doctor --json
```

If the issue is interactive or timing-related, continue with:

```bash
ENVCTL_DEBUG_UI_MODE=deep envctl
envctl --debug-report
```

Then continue with [Troubleshooting](../operations/troubleshooting.md) if you need a more specific runbook.
