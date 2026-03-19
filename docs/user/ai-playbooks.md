# AI Playbooks

This guide collects short workflow patterns for high-throughput development, agent-assisted work, and cross-implementation comparison.

Use it when you want a task recipe more than a conceptual explanation.

## Install AI CLI Presets

```bash
envctl install-prompts --cli codex
envctl install-prompts --cli claude --dry-run
envctl install-prompts --cli codex,opencode --json
envctl install-prompts --cli all
envctl install-prompts --cli all --preset all
```

Use this when you want `envctl` to install built-in prompt presets into your user-local AI CLI directories.

Current targets:

- Codex: `~/.codex/prompts`
- Claude Code: `~/.claude/commands`
- OpenCode: `~/.config/opencode/commands`

Notes:

- omitting `--preset` installs all built-in presets for the selected CLI targets
- existing files are overwritten in place after one confirmation prompt for the whole command
- use `--yes` or `--force` to approve overwrites non-interactively
- `--dry-run` shows what would be written without mutating anything
- this command is intentionally unavailable inside dashboard interactive mode
- the installed implementation-oriented presets tell agents to append structured work summaries to `.envctl-commit-message.md` and preserve a single `### Envctl pointer ###` marker for default `envctl commit` messages

Current built-in presets:

- `implement_plan`
- `implement_task`
- `review_task_imp`
- `review_worktree_imp`
- `continue_task`
- `finalize_task`
- `merge_trees_into_dev`
- `create_plan`

`implement_task` is the default preset used by the optional post-`--plan` cmux launch flow. Codex launches send it as `/prompts:implement_task`; `implement_plan` remains available as a backward-compatible preset.

`continue_task` is used automatically only by the optional Codex cycle workflow. When `ENVCTL_PLAN_AGENT_CODEX_CYCLES` is greater than `1`, envctl queues `continue_task`, then `implement_task`, in the same Codex session for each later round.

Use `review_worktree_imp` from the local/origin repo CLI when you want a read-only review of a generated implementation worktree. By default it reviews the worktree created from the current plan file; pass `$ARGUMENTS` only when you want to override that target with a specific worktree path or name. The prompt treats the current repo as the unedited baseline and the target worktree as the edited implementation under review.

## Parallel Implementation Loop

```bash
envctl --plan
envctl dashboard
envctl logs --all --logs-follow
envctl test --all
```

Use this to run many implementations at the same time and inspect behavior in one place.

To auto-open one AI terminal per newly created planning worktree in your current `cmux` workspace:

```dotenv
ENVCTL_PLAN_AGENT_TERMINALS_ENABLE=true
ENVCTL_PLAN_AGENT_CLI=codex
ENVCTL_PLAN_AGENT_PRESET=implement_task
ENVCTL_PLAN_AGENT_CODEX_CYCLES=1
```

Shorthand aliases:

```dotenv
CMUX=true
CYCLES=3
```

By default, enabling the feature targets a sibling workspace named `"<current workspace> implementation"`. Set `CMUX_WORKSPACE` or `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE` when you want a different workspace title or handle.

If `CMUX_WORKSPACE` or `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE` names a workspace that does not exist yet, envctl creates that workspace before opening the new implementation surfaces.

Codex-only cycle mode:

- default/unset behavior is `ENVCTL_PLAN_AGENT_CODEX_CYCLES=1`, which queues `implement_task` plus `/prompts:finalize_task`
- `CYCLES=<n>` is shorthand for `ENVCTL_PLAN_AGENT_CODEX_CYCLES=<n>`
- `ENVCTL_PLAN_AGENT_CODEX_CYCLES=0` keeps the one-shot preset launch
- `ENVCTL_PLAN_AGENT_CODEX_CYCLES=1` queues `implement_task` plus `/prompts:finalize_task`
- `ENVCTL_PLAN_AGENT_CODEX_CYCLES=2` queues a commit/push/PR follow-up after the first pass, then `continue_task`, `implement_task`, and `/prompts:finalize_task`
- `ENVCTL_PLAN_AGENT_CODEX_CYCLES=3` or more keep that first commit/push/PR follow-up, use commit/push-only follow-ups in the middle, and reserve `/prompts:finalize_task` for the last round
- OpenCode keeps the existing one-shot flow even when the cycle count is set
- canonical `ENVCTL_PLAN_AGENT_*` values win if both canonical and shorthand env vars are set
- `CYCLES` does not enable plan-agent launch by itself
- envctl only appends messages in this mode; Codex still performs the actual commit, push, and PR work itself

Then run:

```bash
envctl --plan backend/checkout
```

## Compare Implementations

```bash
envctl test --all
envctl test --failed
envctl errors --all
envctl logs --all --logs-tail 300
```

Run one test command across all targets and compare outcomes quickly.

Good follow-up:

```bash
envctl health --all
envctl errors --all
```

## Tight Loop for One Project

```bash
envctl test --project api
envctl logs --project api --logs-follow
envctl restart --project api
```

## Multi-Repo Control

```bash
envctl --repo ~/projects/service-a --resume
envctl --repo ~/projects/service-b --resume
envctl --repo ~/projects/service-c --resume
```

## Automation-Friendly Mode
Use non-interactive mode for scripts/agents:

```bash
envctl --headless --resume
envctl test --all --skip-startup --load-state
envctl test --failed --skip-startup --load-state
```

Recommended pattern for safer automation:

```bash
envctl show-config --json
envctl explain-startup --json
envctl --headless --resume
```

## Debugging Workflow for Agents

When an agent or automated run hits an interactive/runtime issue:

```bash
ENVCTL_DEBUG_UI_MODE=deep envctl
envctl --debug-report
```

This gives you something shareable and reproducible instead of a vague "interactive mode was weird" report.

## Related Guides

- [Common Workflows](common-workflows.md)
- [Planning and Worktrees](planning-and-worktrees.md)
- [Python Engine Guide](python-engine-guide.md)
