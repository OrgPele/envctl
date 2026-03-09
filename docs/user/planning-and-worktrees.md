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
envctl --planning-prs
envctl --keep-plan
```

What these do:

- `--plan`: plan and run using the default parallel path
- `--sequential-plan`: plan and run one-by-one
- `--parallel-plan`: explicit alias for the parallel path
- `--planning-prs`: planning-oriented PR flow
- `--keep-plan`: keep planning files in place after execution

Before using any of them in automation, inspect first:

```bash
envctl --list-trees --json
envctl explain-startup --json
```

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

## Related Guides

- [Getting Started](getting-started.md)
- [First-Run Wizard](first-run-wizard.md)
- [Common Workflows](common-workflows.md)
- [Python Engine Guide](python-engine-guide.md)
