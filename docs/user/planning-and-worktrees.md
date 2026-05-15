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

## Optional Plan-Agent Launch

`--plan` can open one new AI terminal session per selected implementation worktree when the feature is enabled in config/env, or when you explicitly pass `--cmux`, `--tmux`, `--omx`, or `--new-worktree`:

```dotenv
ENVCTL_PLAN_AGENT_TERMINALS_ENABLE=true
ENVCTL_PLAN_AGENT_CLI=codex
ENVCTL_PLAN_AGENT_PRESET=implement_task
ENVCTL_PLAN_AGENT_CODEX_CYCLES=2
ENVCTL_PLAN_AGENT_BROWSER_E2E_ENABLE=true
ENVCTL_PLAN_AGENT_PR_REVIEW_COMMENTS_ENABLE=true
ENVCTL_PLAN_AGENT_SHELL=zsh
ENVCTL_PLAN_AGENT_REQUIRE_CMUX_CONTEXT=true
```

Shorthand aliases also work:

```dotenv
CMUX=true
CYCLES=3
```

Behavior:

- only runs for `--plan`
- launches for worktrees created during the current reconciliation; explicit `--cmux --new-session` can also launch a fresh surface for an already-selected implementation worktree
- when no transport is selected, Linux defaults to tmux; other hosts prefer cmux and fall back to tmux when cmux is not installed
- current planning follow-ups choose one launch surface per invocation; do not assume a later second launch can attach to the same reconciliation unless envctl explicitly says it created or recovered the target worktree(s)
- skips `--planning-prs`
- skips cleanly when the feature is disabled, no launch target was selected, or a cmux launch cannot resolve a workspace while strict caller-context mode is enabled
- for cmux launches without an explicit workspace override, envctl derives the target workspace name as `"<current workspace> implementation"`
- if `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE` is set, envctl uses that workspace directly and treats the feature as enabled even if `ENVCTL_PLAN_AGENT_TERMINALS_ENABLE` is unset
- the workspace override accepts either a cmux handle such as `workspace:1` or a workspace title such as `envctl`
- when a named target workspace does not exist yet, envctl creates it and reuses that workspace's initial cmux starter surface for the first plan-agent launch when it can identify that starter surface unambiguously; otherwise it falls back to opening a new surface
- `CMUX=true` is shorthand for enabling the feature with the default `"<current workspace> implementation"` target
- `CMUX_WORKSPACE=...` is shorthand for `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE=...`
- `CYCLES=...` is shorthand for `ENVCTL_PLAN_AGENT_CODEX_CYCLES=...`
- `ENVCTL_PLAN_AGENT_BROWSER_E2E_ENABLE=false` disables the `$browser-use` E2E follow-up when browser validation is not applicable
- `ENVCTL_PLAN_AGENT_PR_REVIEW_COMMENTS_ENABLE=false` disables the final PR review-comments follow-up when comment handling is manual
- canonical `ENVCTL_PLAN_AGENT_*` values win when both canonical and shorthand values are set

### Dependency prep before AI launch

Before envctl submits the implementation prompt, enabled plan-agent launches prepare dependency artifacts in the selected
worktree:

- Python backends with Poetry run the existing Poetry install bootstrap and launch generic configured commands through
  `poetry run python`.
- Python backends with `requirements.txt` get a worktree-local `backend/venv` and use that interpreter for generic
  commands like `python -m uvicorn ...`.
- Frontends use the same package-manager detection as service startup; for `package-lock.json`, envctl runs
  `npm ci --include=dev --prefer-offline --no-audit`.

This preparation does not start backend/frontend services and does not run migrations. It only ensures the AI session
starts in a worktree whose dependency roots are ready or were skipped for a documented reason.

Use `--no-deps` when you want to launch the AI session without dependency prep or managed dependencies. Use
`--only-backend` or `--only-frontend` when you want exactly one app side: those flags also skip managed dependencies
and dependency prep. Use `--no-infra` when the task does not need backend, frontend, managed dependencies, or
dependency prep at all.

Each launched surface stays interactive. Envctl creates the tab/window, renames it to a compact worktree-derived title when supported, starts the configured shell, types `cd <worktree>`, starts the selected AI CLI, then sends the configured preset. By default that preset is `implement_task`. OpenCode cmux/tmux launches submit the rendered prompt body directly by default. Codex resolves the preset from the envctl-managed prompt file and submits the full prompt body directly. `implement_plan` is still available when you want to override the default.

`ENVCTL_PLAN_AGENT_CODEX_CYCLES` is an additional opt-in for Codex only:

- default/unset is `2`, so Codex launches first queue a commit/push/PR/status-check follow-up, then `continue_task`, `implement_task`, `finalize_task`, enabled browser-E2E and PR review-comments follow-ups
- `CYCLES=<n>` resolves to the same effective value as `ENVCTL_PLAN_AGENT_CODEX_CYCLES=<n>`
- `0` submits the single implementation prompt and queues enabled browser-E2E and PR review-comments follow-ups for Codex/OMX surfaces
- `2` queues a plain follow-up asking Codex to commit, push, open or update the PR, and wait for GitHub status checks after the first pass, then queues `continue_task`, `implement_task`, `finalize_task`, `$browser-use` E2E, and the PR review-comments follow-up
- `3` or more keep that first commit/push/PR/status-check follow-up, then use commit/push-only follow-ups for intermediate rounds, and reserve `finalize_task` plus enabled browser-E2E and PR review-comments follow-ups for the final round
- OpenCode ignores `ENVCTL_PLAN_AGENT_CODEX_CYCLES` and stays on the existing one-shot preset flow
- `CYCLES` does not enable the plan-agent launcher on its own; you still need the existing enablement config such as `CMUX=true`, `ENVCTL_PLAN_AGENT_TERMINALS_ENABLE=true`, or `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE=...`
- envctl only appends Codex messages in this mode; it does not type `git`, `gh`, `envctl commit`, or `envctl pr` shell commands itself
- queue injection failures fall back to the initial `implement_task` launch and leave the surface open for manual continuation

## Auto-Launch Create-Plan Skills

The installed create-plan skills connect planning documents to these launch paths:

- `$envctl-create-plan` stays plan-only and approval-first.
- `$envctl-create-plan` records a recommended Codex cycle count from `0` through `8` in the plan and uses that recommendation in Codex follow-up command examples.
- `$envctl-create-plan-auto-codex` writes `todo/plans/<category>/<slug>.md`, derives `<category>/<slug>` from that path, chooses a recommended Codex cycle count from `0` through `8`, then runs `ENVCTL_PLAN_AGENT_CODEX_CYCLES=<recommended> envctl --plan <selector> --tmux --entire-system --headless --new-worktree`.
- `$envctl-create-plan-auto-opencode` writes the plan, derives the selector, then runs `envctl --plan <selector> --tmux --opencode --entire-system --headless --new-worktree`; OpenCode prepends `/ulw-loop` by default.
- `$envctl-create-plan-auto-omx` writes the plan, records the same recommendation for visibility, derives the selector, then runs `envctl --plan <selector> --omx --ultragoal --entire-system --headless --new-worktree`; optional `/goal` framing is submitted first, Ultragoal wraps the initial prompt, and envctl may queue Codex follow-up cycles using the current cycle configuration. Use `--ralph` explicitly when you need the Ralph compatibility workflow.

The auto variants are explicit opt-ins for immediate implementation. Each uses the plan file path as the selector source and asks envctl to create a fresh headless session, so invoke them only when you want implementation work to start right after planning.
Create-plan prompt recommendations use a `0` through `8` policy range even though direct `ENVCTL_PLAN_AGENT_CODEX_CYCLES` runtime parsing still follows the runtime implementation cap.

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

When you run `envctl` from a linked worktree of an envctl-managed project, envctl uses the owning main repo for control-plane metadata: `.envctl`, runtime scope, state files, port locks, and latest-run artifacts. The worktree-local provenance file remains in the worktree and is still used by planning and review flows; it is not the project-level runtime metadata store.

When the source repo already has common local dependency/runtime artifacts, envctl-created worktrees also try to link a small compatibility set into the new worktree:

- `backend/venv`
- `backend/.env`
- `frontend/node_modules`

This helps worktree-local test and runtime commands reuse the repo-local backend virtualenv, backend env file, and frontend dependency tree when those artifacts already exist in the source repo. Envctl only creates the link when the source artifact exists and the worktree path is not already occupied by a real file or directory. Plan-agent dependency prep does not rely on these links; it prepares per-worktree dependency artifacts so branch-specific dependency files remain authoritative.

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
