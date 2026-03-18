# Planning and Worktrees

This guide explains the worktree-oriented side of `envctl`: plan files, tree selection, and the compare-many-implementations loop.

If you want quick copy-paste flows, pair this with [Common Workflows](common-workflows.md).

## Planning Root Path
Planning commands read files from `ENVCTL_PLANNING_DIR`.

Default:

```bash
ENVCTL_PLANNING_DIR="todo/plans"
```

You can set:
- A repo-relative path (recommended), for example `work/plans`.
- An absolute path.

Recommended practice:

- keep plan files inside the repo
- use a stable folder structure
- treat the planning directory as part of your implementation workflow, not a temporary scratch area

## Planning Commands

```bash
envctl --plan
envctl --sequential-plan
envctl --parallel-plan
envctl --keep-plan
```

What these do:

- `--plan`: plan and run using the default parallel path
- `--sequential-plan`: plan and run one-by-one
- `--parallel-plan`: explicit alias for the parallel path
- `--keep-plan`: keep planning files in place after execution

Before using any of them in automation, inspect first:

```bash
envctl --list-trees --json
envctl explain-startup --json
```

## Optional Cmux Agent Launch

`--plan` can now open one new `cmux` terminal surface per newly created worktree when the feature is enabled in config or env:

```dotenv
ENVCTL_PLAN_AGENT_TERMINALS_ENABLE=true
ENVCTL_PLAN_AGENT_CLI=codex
ENVCTL_PLAN_AGENT_PRESET=implement_task
ENVCTL_PLAN_AGENT_CODEX_CYCLES=1
ENVCTL_PLAN_AGENT_SHELL=zsh
ENVCTL_PLAN_AGENT_REQUIRE_CMUX_CONTEXT=true
```

Shorthand aliases also work:

```dotenv
CMUX=true
```

Behavior:

- only runs for `--plan`
- only launches for worktrees created during the current reconciliation
- skips `--planning-prs`
- skips cleanly when the feature is disabled, no new worktrees were created, or the caller is not inside `cmux` while strict caller-context mode is enabled
- when enabled without an explicit workspace override, envctl derives the target workspace name as `"<current workspace> implementation"`
- if `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE` is set, envctl uses that workspace directly and treats the feature as enabled even if `ENVCTL_PLAN_AGENT_TERMINALS_ENABLE` is unset
- the workspace override accepts either a cmux handle such as `workspace:1` or a workspace title such as `envctl`
- when a named target workspace does not exist yet, envctl creates it and reuses that workspace's initial cmux starter surface for the first plan-agent launch when it can identify that starter surface unambiguously; otherwise it falls back to opening a new surface
- `CMUX=true` is shorthand for enabling the feature with the default `"<current workspace> implementation"` target
- `CMUX_WORKSPACE=...` is shorthand for `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE=...`

Each launched surface stays interactive. Envctl creates the tab, renames it to a compact worktree-derived title, starts the configured shell, types `cd <worktree>`, starts the selected AI CLI, then sends the configured preset command. By default that preset is `implement_task`. For Codex the launch command is `/prompts:<preset>`; for OpenCode it remains `/<preset>`. `implement_plan` is still available when you want to override the default.

`ENVCTL_PLAN_AGENT_CODEX_CYCLES` is an additional opt-in for Codex only:

- default/unset is `1`, so Codex launches queue `/prompts:implement_task` plus one plain follow-up message telling Codex to commit, push, and open or update the PR when that pass finishes
- `0` keeps the current one-shot launch behavior
- values greater than `1` queue repeated rounds of `continue_task`, `implement_task`, and the same finalization message in that same Codex session
- OpenCode ignores `ENVCTL_PLAN_AGENT_CODEX_CYCLES` and stays on the existing one-shot preset flow
- envctl only appends Codex messages in this mode; it does not type `git`, `gh`, `envctl commit`, or `envctl pr` shell commands itself
- queue injection failures fall back to the initial `implement_task` launch and leave the surface open for manual continuation

## Selection Input
When passing plan selections, you can use any of these forms:
- `folder/task`
- `<planning-root>/folder/task`
- absolute path to a plan file

The `.md` suffix is optional.

Examples:

```bash
envctl --plan backend/checkout
envctl --plan todo/plans/backend/checkout.md
envctl --plan /absolute/path/to/todo/plans/backend/checkout.md
```

This is useful when you want to run a narrow slice of a larger planning tree.

## Recommended Planning Layout

One practical pattern is:

```text
todo/plans/
  backend/
    checkout.md
    pricing.md
  frontend/
    checkout.md
  integrations/
    stripe-sync.md
```

When a plan’s selected count reaches `0`, envctl blasts the related worktree(s) and archives the plan into the sibling done root:

```text
todo/done/
  backend/
    checkout.md
```

You do not need this exact structure, but a stable folder hierarchy makes selection and comparison much easier.

## Direct Worktree Setup

```bash
envctl --setup-worktrees feature-x 3
envctl --setup-worktree feature-x 2
envctl --include-existing-worktrees 1,3
```

Use direct setup when:

- you already know the feature name
- you want numbered worktrees directly
- you do not need the plan-file discovery step

Use `--plan` when:

- plan files are already your source of truth
- you want repo-native selection by plan/task
- multiple people or agents need to run the same implementation matrix

New worktrees created by `envctl` now persist their origin branch in:

```text
<worktree>/.envctl-state/worktree-provenance.json
```

Single-mode `envctl review` uses that provenance automatically when it needs a base branch. For older or manually created worktrees, review falls back to the attached branch's upstream and then the repo default branch. Use `--review-base <branch>` when you need to override that resolution explicitly.

## Typical Loop

```bash
envctl --plan
envctl dashboard
envctl test --all
envctl logs --all --logs-follow
```

Useful follow-up commands:

```bash
envctl errors --all
envctl restart --project <tree-name>
envctl logs --project <tree-name> --logs-follow
```

Recommended inspection before enabling auto-launch:

```bash
envctl show-config --json
envctl explain-startup --json
```

## Headless Planning

For scripts and agents, use explicit selection instead of relying on interactive choice:

```bash
envctl --list-trees --json
envctl --headless --plan backend/checkout
```

This avoids interactive plan selection and makes the run reproducible.

## Common Mistakes

- assuming `--plan` should guess a selection in headless mode
- mixing ad hoc tree naming with plan-file naming
- skipping `--list-trees --json` when automation needs stable target discovery
- forgetting that `--plan` always resolves into `trees` mode
- forgetting that `envctl test --all` and `envctl test --failed` can run across all selected trees after startup

## Related Guides

- [Getting Started](getting-started.md)
- [First-Run Wizard](first-run-wizard.md)
- [Common Workflows](common-workflows.md)
- [Python Engine Guide](python-engine-guide.md)
