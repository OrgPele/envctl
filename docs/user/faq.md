# FAQ

## Do I need to install `envctl` inside every repository?

No.

Install `envctl` once from this repository so the launcher is on your `PATH`, then use it against any target repo:

```bash
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
- `envctl --doctor` is the Python runtime diagnostic for the current repo and runtime scope

If you are troubleshooting a real run, you almost always want `envctl --doctor`.

## Why did `envctl` open a config wizard?

Because you ran a normal operational command in a repository that does not yet have a repo-local `.envctl`.

That is expected Python-runtime behavior:

- inspection commands can run without `.envctl`
- operational commands need repo-local orchestration config
- interactive runs bootstrap it with `envctl config`

If you want the exact screen flow and save behavior, use [First-Run Wizard](first-run-wizard.md).

## Is the Bash/shell engine still supported?

It still exists, but only as a deprecated compatibility fallback.

Use it only when you explicitly need to compare Python vs shell behavior or temporarily fall back during cutover:

```bash
ENVCTL_ENGINE_SHELL_FALLBACK=true envctl --resume
```

The Python engine is the primary runtime and the one these docs are written for.

## Why does `debug-pack` fail when I force shell fallback?

Because `debug-pack`, `debug-report`, and the modern debug-bundle pipeline are Python-runtime features.

Switch back to Python mode before using them.

## Which commands are safest when I am not sure what will happen?

Start with:

```bash
envctl show-config --json
envctl show-state --json
envctl explain-startup --json
envctl --list-targets --json
```

Those commands are high-signal and low-risk because they inspect rather than start.

## When should I use `show-config` and `explain-startup`?

Use them before any run where predictability matters:

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
