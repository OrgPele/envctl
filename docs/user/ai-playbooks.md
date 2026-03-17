# AI Playbooks

This guide collects short workflow patterns for high-throughput development, agent-assisted work, and cross-implementation comparison.

Use it when you want a task recipe more than a conceptual explanation.

## Install AI CLI Presets

```bash
envctl install-prompts --cli codex
envctl install-prompts --cli claude --dry-run
envctl install-prompts --cli codex,opencode --json
envctl install-prompts --cli all --preset all
```

Use this when you want `envctl` to install built-in prompt presets into your user-local AI CLI directories.

Current targets:

- Codex: `~/.codex/prompts`
- Claude Code: `~/.claude/commands`
- OpenCode: `~/.config/opencode/commands`

Notes:

- existing files are backed up in-place before overwrite
- `--dry-run` shows what would be written without mutating anything
- this command is intentionally unavailable inside dashboard interactive mode

Current built-in presets:

- `implement_plan`
- `implement_task`
- `review_task_imp`
- `continue_task`
- `merge_trees_into_dev`
- `create_plan`

`implement_task` is the default preset used by the optional post-`--plan` cmux launch flow. Codex launches send it as `/prompts:implement_task`; `implement_plan` remains available as a backward-compatible preset.

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
```

Shorthand aliases:

```dotenv
CMUX=true
CMUX_WORKSPACE=envctl
```

If `CMUX_WORKSPACE` or `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE` names a workspace that does not exist yet, envctl creates that workspace before opening the new implementation surfaces.

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
