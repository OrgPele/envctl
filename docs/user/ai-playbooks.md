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

- Codex: `~/.codex/skills/envctl-*`
- Claude Code: `~/.claude/commands`
- OpenCode: `~/.config/opencode/commands`

Notes:

- omitting `--preset` installs all built-in presets for the selected CLI targets
- existing files are overwritten in place after one confirmation prompt for the whole command
- use `--yes` or `--force` to approve overwrites non-interactively
- `--dry-run` shows what would be written without mutating anything
- `envctl install-prompts --help` prints command-specific usage, examples, and Codex guidance
- this command is intentionally unavailable inside dashboard interactive mode
- the installed implementation-oriented presets tell agents to prefer inline `envctl ship -m "<message>"` / `envctl commit -m "<message>"` messages and use `.envctl-commit-message.md` only as the fallback default-message ledger with a single `### Envctl pointer ###` marker
- broad staging during implementation is tolerated by `envctl commit`; envctl-local task/control artifacts stay local and are unstaged before the normal commit is created
- Codex installs explicit-only skills under `~/.codex/skills/envctl-*` by default; `--with-codex-skills` remains accepted as a compatibility no-op for older scripts
- envctl-managed `--plan` launches submit the rendered workflow automatically; the `$envctl-*` skill names are for direct manual Codex/OMX use

Current built-in presets:

- `implement_task`
- `review_worktree_imp`
- `continue_task`
- `finalize_task`
- `merge_implementation_branches`
- `create_plan`
- `create_plan_auto_codex`
- `create_plan_auto_opencode`
- `create_plan_auto_omx`

`implement_task` is the default preset used by the optional post-`--plan` launch flow. For Codex, envctl resolves the shipped preset body and submits it directly; the installed `SKILL.md` files are for direct manual Codex use.

All Codex presets now install as explicit-only skills. Run `envctl install-prompts --cli codex`, then edit the generated `SKILL.md` files under `~/.codex/skills/envctl-*` if you want to customize them for manual Codex use. The installed skills are explicit-only and use names such as:

- `$envctl-implement-task`
- `$envctl-continue-task`
- `$envctl-finalize-task`
- `$envctl-review-worktree`
- `$envctl-create-plan`
- `$envctl-create-plan-auto-codex`
- `$envctl-create-plan-auto-opencode`
- `$envctl-create-plan-auto-omx`

Create-plan skill behavior:

- `$envctl-create-plan` is plan-only and approval-first. It writes `todo/plans/<category>/<slug>.md` and asks before running envctl.
- `$envctl-create-plan` records a recommended Codex cycle count from `0` through `3` in the plan and uses that recommendation in Codex follow-up command examples.
- `$envctl-create-plan-auto-codex` writes the same kind of plan, derives `<category>/<slug>` from the plan file path, chooses a recommended Codex cycle count from `0` through `3`, then runs `ENVCTL_PLAN_AGENT_CODEX_CYCLES=<recommended> envctl --plan <selector> --cmux --preset implement_task --entire-system --headless --new-session`.
- `$envctl-create-plan-auto-opencode` writes the plan, derives `<selector>`, then runs `envctl --plan <selector> --cmux --opencode --entire-system --headless --new-session`. OpenCode ignores Codex cycle settings and prepends `/ulw-loop` by default.
- `$envctl-create-plan-auto-omx` writes the plan, records the same `0` through `3` recommendation for visibility, derives `<selector>`, then runs `envctl --plan <selector> --omx --ultragoal --preset implement_task --entire-system --headless --new-session`. OMX-managed launches are Codex-only: optional `/goal` framing is submitted first, Ultragoal wraps the initial prompt, and envctl may queue Codex follow-up cycles using the current cycle configuration. Use `--ralph` explicitly when you need the Ralph compatibility workflow.
- Keep the auto variants explicit-only; do not configure them for implicit invocation from generic planning language.
- Rerun `envctl install-prompts --cli codex --yes`, `envctl install-prompts --cli opencode --yes`, or `envctl install-prompts --cli all --yes` to refresh installed prompt files.

`continue_task` is used automatically only by the optional Codex cycle workflow. When `ENVCTL_PLAN_AGENT_CODEX_CYCLES` is greater than `1`, envctl queues `continue_task`, then `implement_task`, in the same Codex session for each later round.

Use `review_worktree_imp` from the local/origin repo CLI when you want a read-only review of a generated implementation worktree. By default it reviews the worktree created from the current plan file; pass `$ARGUMENTS` only when you want to override that target with a specific worktree path or name. The prompt treats the current repo as the unedited baseline and the target worktree as the edited implementation under review.

Dashboard review follow-up:

- during interactive `envctl dashboard` -> `review` setup for exactly one non-`Main` worktree, envctl can offer one origin-side AI review tab through the same selector UI used for dashboard target selection
- the opened tab starts in the current repo root, not the target worktree
- the submitted prompt includes reviewer notes pointing at the generated full review bundle, the target worktree directory, and the original plan file that created the worktree when provenance can resolve it
- Codex receives the rendered `review_worktree_imp` prompt body with the reviewer notes injected. OpenCode cmux and tmux launches submit the rendered prompt body directly and prepend `/ulw-loop` by default; use `--no-ulw-loop` when that prefix should be omitted for one launch.
- choosing `No`, cancelling the selector, reviewing `Main`, reviewing multiple targets, or a failed review keeps the existing markdown bundle-only behavior
- this optional review-tab launch reuses the same `ENVCTL_PLAN_AGENT_CLI`, `ENVCTL_PLAN_AGENT_CLI_CMD`, `ENVCTL_PLAN_AGENT_SHELL`, `ENVCTL_PLAN_AGENT_REQUIRE_CMUX_CONTEXT`, and `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE` transport settings as the post-`--plan` launcher, but it does not require `ENVCTL_PLAN_AGENT_TERMINALS_ENABLE=true`

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
ENVCTL_PLAN_AGENT_CODEX_CYCLES=2
ENVCTL_PLAN_AGENT_BROWSER_E2E_ENABLE=false
ENVCTL_PLAN_AGENT_PR_REVIEW_COMMENTS_ENABLE=false
```

Shorthand aliases:

```dotenv
CMUX=true
CYCLES=3
```

For a command-scoped cmux launch, pass `--cmux`:

```bash
envctl --plan backend/checkout --cmux --headless
```

By default, enabling the feature targets a sibling workspace named `"<current workspace> implementation"`. Set `CMUX_WORKSPACE` or `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE` when you want a different workspace title or handle.

The optional dashboard review-tab flow reuses the same AI CLI and cmux transport settings, but when no explicit workspace override is set it targets a sibling workspace named `"<current workspace> reviews"`.

If `CMUX_WORKSPACE` or `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE` names a workspace that does not exist yet, envctl creates that workspace before opening the new implementation surfaces.

To launch through Superset instead of cmux surfaces:

```sh
SUPERSET_PROJECT=<project-id> envctl --plan <selector>
SUPERSET_WORKSPACE=<workspace-id> envctl --plan <selector>
```

Superset project or workspace config selects the Superset transport unless `ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT` is explicitly set. Superset launches use Superset's public high-level CLI. Envctl sends the rendered Codex `implement_task` prompt to `superset workspaces create` or `superset agents run`, then optionally opens the workspace. Superset does not support envctl's cmux screen polling, tab renames, key sending, review tabs, or Codex cycle queue injection in this slice.

Codex TUI cycle mode:

- default/unset behavior is `ENVCTL_PLAN_AGENT_CODEX_CYCLES=2`, which queues an `envctl ship` handoff follow-up after the first pass, then `continue_task`, `implement_task`, `finalize_task`, enabled browser-E2E, and any explicitly enabled PR review-comments follow-up
- `CYCLES=<n>` is shorthand for `ENVCTL_PLAN_AGENT_CODEX_CYCLES=<n>`
- `ENVCTL_PLAN_AGENT_CODEX_CYCLES=0` submits the single implementation prompt and queues enabled browser-E2E plus any explicitly enabled PR review-comments follow-up for Codex/OMX surfaces
- `ENVCTL_PLAN_AGENT_CODEX_CYCLES=1` queues `implement_task`, `finalize_task`, enabled browser-E2E, and any explicitly enabled PR review-comments follow-up
- `ENVCTL_PLAN_AGENT_CODEX_CYCLES=2` queues an `envctl ship` handoff after the first pass, then `continue_task`, `implement_task`, `finalize_task`, enabled browser-E2E, and any explicitly enabled PR review-comments follow-up
- `ENVCTL_PLAN_AGENT_CODEX_CYCLES=3` is the maximum: it keeps that first `ship` handoff, uses `ship`-first follow-ups in the middle, and reserves `finalize_task` plus enabled browser-E2E and any explicitly enabled PR review-comments follow-up for the last round
- OpenCode keeps the existing one-shot flow even when the cycle count is set
- Superset keeps a one-shot Codex prompt even when the cycle count is set
- create-plan prompts and lower-level runtime parsing use the same `0` through `3` scale; values above `3` are bounded to `3`, and `3` is reserved for genuinely complex work
- `ENVCTL_PLAN_AGENT_BROWSER_E2E_ENABLE=true` opts in to the `$browser` E2E follow-up when browser validation is applicable
- `ENVCTL_PLAN_AGENT_PR_REVIEW_COMMENTS_ENABLE=true` opts in to the final PR review-comments follow-up when comment handling should run as a dedicated pass
- canonical `ENVCTL_PLAN_AGENT_*` values win if both canonical and shorthand env vars are set
- `CYCLES` does not enable plan-agent launch by itself; use `--cmux`, `CMUX=true`, `ENVCTL_PLAN_AGENT_TERMINALS_ENABLE=true`, or a cmux workspace override to enable launch
- envctl only appends messages in this mode; Codex still runs `envctl ship` or the fallback commit, push, and PR flow itself
- when `ship` is delegated to a real background/subagent lane, successful completion is silent; the worker reports back only for commit/push/PR failures, merge conflicts, failed checks, pending timeouts, no-checks-reported status, or actionable review comments

Then run:

```bash
envctl --plan --help
envctl --plan backend/checkout --headless --dry-run
envctl --plan backend/checkout
# or, for an OMX-managed Codex session that creates its own tmux session/HUD:
envctl --plan backend/checkout --omx
# OMX-only workflow variants:
envctl --plan backend/checkout --omx --ultragoal
envctl --plan backend/checkout --omx --ralph
envctl --plan backend/checkout --omx --team
# utility command-specific help:
envctl codex-tmux --help
```

If a headless plan-agent launch prints `Implementation session is running, but local app startup failed.`, the implementation session is still alive. Copy the `attach:` command from the `AI session:` section to continue watching or driving the agent. Configure `ENVCTL_BACKEND_START_CMD` / `ENVCTL_FRONTEND_START_CMD` only when that worktree also needs local services for verification; otherwise you can leave services disabled and let the AI implementation session continue.

If `envctl --plan ... --tmux --opencode` reports `OpenCode AI session failed to start`, inspect the shown screen excerpt first. Common causes are a missing `opencode` executable in the shell used by tmux, an OpenCode startup/config error, or a stale tmux session. Re-run with `--new-session` after fixing the shell/config issue.

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
