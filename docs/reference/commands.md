# Commands

## Clone-Compatibility Wrapper

If you are intentionally running from a clone of the `envctl` repo and want the compatibility wrapper flow, use:

```text
./bin/envctl [--repo <path>] [engine args...]
./bin/envctl doctor [--repo <path>] [--json]
./bin/envctl install [--shell-file <path>] [--dry-run]
./bin/envctl uninstall [--shell-file <path>] [--dry-run]
./bin/envctl [--repo <path>] --version
```

Notes:

- this is compatibility-only, not the primary install story
- running `./bin/envctl`, `bin/envctl`, or an absolute wrapper path uses that exact wrapper directly
- the preferred user path is the package-installed `envctl` command on your `PATH`
- bare `envctl` keeps the installed-command preference when a repo wrapper shadows another `envctl` later on `PATH`
- `ENVCTL_USE_REPO_WRAPPER=1` remains the override when you need to force repo-wrapper behavior for an ambiguous PATH-based launch
- `--version` is launcher-owned and works without repo resolution, `.envctl`, or runtime startup
- when `envctl` is launched from a linked worktree whose owning main repo has a readable `.envctl`, envctl uses the owning repo as the control-plane root for `.envctl`, runtime state, port locks, and latest-run artifacts; this also applies to `--repo <linked-worktree>`

## Launcher Verification

Use these when you want to verify the installed command or an explicit repo wrapper before running against a repo:

```bash
envctl --version
./bin/envctl --version
envctl doctor --repo /absolute/path/to/repo --json
```

`--version` does not add a runtime command and does not appear in `list-commands`.

## Command Boundary

Use this section when you need to know which `envctl` commands are safe before repo bootstrap or full runtime startup.

| Command family | What it covers today | Boundary |
| --- | --- | --- |
| launcher-owned commands | `--help`, `--version`, launcher `doctor`, `install`, `uninstall` | handled by the launcher before the normal runtime path |
| bootstrap-safe inspection or utility commands | `list-commands`, `list-targets`, `list-trees`, `show-config`, `show-state`, `endpoints`, `explain-startup`, `install-prompts`, `codex-tmux`, `ensure-worktree`, `supabase-user`, `qa-user`, `playwright` | available without a repo-local `.envctl` and outside the full runtime dependency gate |
| operational runtime commands | `start`, `plan`, `resume`, `restart`, `dashboard`, `test`, `logs`, `health`, `errors`, `pr`, `commit`, `review`, `migrate` | enter the normal runtime path for startup, saved-state, or action workflows |

This boundary is grounded in the current launcher and Python runtime behavior, not a separate documentation-only model.

- launcher-owned commands are handled before the runtime forwards into the normal command router path
- bootstrap-safe inspection or utility commands are the right choice when you want to inspect config, state, startup decisions, or install local AI presets before changing `.envctl` or starting services
- the full envctl runtime dependency gate currently runs before `start`, `plan`, and `restart`, so not every non-launcher command is prereq-gated the same way

Examples:

```bash
envctl --help
envctl --plan --help
envctl --version
envctl doctor --repo /absolute/path/to/repo
envctl show-config --json
envctl explain-startup --json
envctl --plan backend/checkout --headless --dry-run
envctl install-prompts --cli codex
envctl install-prompts --help
envctl codex-tmux --dry-run
envctl codex-tmux --help
```

## Inspection Commands

These commands are safe to use before a repo-local `.envctl` exists:

```bash
envctl list-commands
envctl list-targets
envctl list-targets --json
envctl list-trees --json
envctl show-config --json
envctl show-state --json
envctl endpoints --project feature-a-1 --json
envctl explain-startup --json
envctl preflight --json
```

For linked worktrees of an envctl-managed project, `show-config --json` reports the owning main repo as `base_dir`, the owning repo's `.envctl` as `config_file`, and the invoked checkout as `execution_root`. Standalone repos and linked worktrees whose main repo has no readable `.envctl` keep their own repo root so bootstrap flows remain separate.

Compatibility note:

- `list-commands`, `list-targets`, and `list-trees` also accept `--list-commands`, `--list-targets`, and `--list-trees`
- `preflight` and `--preflight` expose the same startup inspection logic through the versioned `envctl.preflight.v1` JSON contract

State-backed commands that accept `--project` now fail closed when the requested project is not present in the active runtime state. For example, `envctl health --project feature-a-1 --json` returns `ok=false`, `error=requested_project_not_running`, the requested project, and the active projects instead of rendering another worktree's services. Without an explicit `--project`, JSON state/health output includes `cwd_project` and `warnings` when the invocation cwd appears to belong to a different worktree than the active runtime.

## AI CLI Presets

```bash
envctl install-prompts --cli codex
envctl install-prompts --cli claude --dry-run
envctl install-prompts --cli codex,opencode --json
envctl install-prompts --cli all
envctl install-prompts --cli all --preset all
```

Behavior:

- installs built-in workflows into user-local AI CLI directories
- omitting `--preset` installs all built-in presets
- `envctl install-prompts --help` prints command-specific usage, examples, and Codex-specific guidance
- built-in presets:
  - `implement_task`
  - `review_worktree_imp`
  - `continue_task`
  - `finalize_task`
  - `merge_implementation_branches`
  - `create_plan`
  - `create_plan_auto_codex`
  - `create_plan_auto_opencode`
  - `create_plan_auto_omx`
- target roots:
  - Codex: `~/.codex/skills/envctl-*`
  - Claude Code: `~/.claude/commands`
  - OpenCode: `~/.config/opencode/commands`
- existing files are overwritten in place after one confirmation prompt for the command
- use `--yes` or `--force` to approve overwrites without prompting
- `--json` and non-interactive TTY-less runs fail cleanly when overwrite approval is required but not pre-approved
- this command is available from the normal CLI, but not from dashboard interactive mode
- `review_worktree_imp` is intended for manual origin-side review from the local repo CLI; it defaults to the worktree created from the current plan file, and `$ARGUMENTS` can override that target with a specific worktree path or name
- interactive dashboard `review` can optionally offer one origin-side AI review tab after a successful single-worktree review; this reuses `review_worktree_imp` instead of changing review bundle generation
- Codex presets are user-editable skill markdown files owned by envctl; envctl reads the embedded direct prompt body when it needs to submit a preset itself instead of relying on a Codex slash alias
- envctl-managed `--plan` launches submit the rendered workflow automatically; manual `$envctl-*` invocation is only for direct Codex or OMX use
- Codex installs explicit-only skills under `~/.codex/skills/envctl-*` by default; `--with-codex-skills` is kept as a compatibility no-op for older scripts

Auto-launch create-plan presets:

- `create_plan` remains plan-only and approval-first; `$envctl-create-plan` writes the plan and asks before running envctl.
- `create_plan_auto_codex` writes the plan, derives `<selector>` from `todo/plans/<category>/<slug>.md`, chooses a recommended Codex cycle count from `0` through `3`, then runs `ENVCTL_PLAN_AGENT_CODEX_CYCLES=<recommended> envctl --plan <selector> --cmux --entire-system --headless --new-session`.
- `create_plan_auto_opencode` writes the plan, derives `<selector>`, then runs `envctl --plan <selector> --cmux --opencode --entire-system --headless --new-session`; OpenCode launches prepend `/ulw-loop` by default.
- `create_plan_auto_omx` writes the plan, derives `<selector>`, then runs `envctl --plan <selector> --omx --ultragoal --entire-system --headless --new-session`.
- Each auto preset creates/syncs implementation worktrees and starts a fresh implementation session; use it only when you want implementation to start immediately.
- Refresh installed prompt files with `envctl install-prompts --cli codex --yes`, `envctl install-prompts --cli opencode --yes`, or `envctl install-prompts --cli all --yes`.

## `codex-tmux`

`codex-tmux` is a supported utility command.

Use it when you want `envctl` to launch or reuse a repo-scoped tmux session for `codex` without going through the normal runtime startup path.

```bash
envctl codex-tmux
envctl codex-tmux review
envctl codex-tmux --help
envctl codex-tmux --dry-run --json
```

Behavior:

- launches a new tmux session when the repo does not already have one
- reuses the existing repo-scoped session when one already exists
- requires `tmux` and `codex`
- supports `--json` only together with `--dry-run`
- is distinct from the optional post-`--plan` cmux-based plan-agent launch flow documented in the AI playbooks

## `supabase-user`

`supabase-user` is a supported utility command for managed Supabase Auth users. It uses `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` from the shell/config when provided, or a running envctl managed Supabase state when available.

```bash
envctl supabase-user sync --headless
envctl supabase-user list --json
envctl supabase-user create e2e@example.test --password local-password --metadata-json '{"company_name":"E2E Co"}'
envctl supabase-user update e2e@example.test --password new-local-password
envctl supabase-user delete e2e@example.test --headless
```

Aliases: `supabase-users`, `auth-user`, `--supabase-user`, `--supabase-users`, and `--auth-user`.

Behavior:

- `sync` provisions the `.envctl` users for the selected `--mode main|trees`
- `list` and `show` never print passwords or service-role keys
- `create` is idempotent by email and reports an existing user without changing it
- `delete` requires `--yes`, `--headless`, or JSON automation
- JSON output includes command status, ids, emails, and errors only after secret redaction
- if no running managed Supabase state can be loaded, provide `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` or start the stack first with `envctl --entire-system --headless`

## `endpoints`

`endpoints` is the canonical machine-readable way to retrieve the active URLs and dependency ports for one running project.

```bash
envctl endpoints --project feature-a-1 --json
envctl endpoints --project feature-a-1
```

Behavior:

- requires a matching active project unless exactly one project is running
- fails closed with `requested_project_not_running` when the requested project does not match active state
- returns frontend/backend `local_url`, `public_url`, status, ports, dependency ports, `dependency_mode`, `shared_dependencies`, `run_id`, `mode`, and `project_root`
- projects public URLs through `ENVCTL_PUBLIC_HOST` when a service does not already have an explicit public URL
- emits sanitized `state.project_resolution.ok` or `state.project_resolution.failed` events with command, run id, mode, requested/selected/active projects, and inferred cwd project

## `qa-user`

`qa-user ensure` creates or reuses deterministic local QA credentials for the requested active project.

```bash
envctl qa-user ensure --project feature-a-1 --email qa@example.test --password local-password --json
envctl qa-user ensure --project feature-a-1 --email qa@example.test --password local-password --seed crm,calendar --json
```

Behavior:

- resolves the requested project before touching Supabase
- uses managed Supabase connection details from that project's active runtime state, or explicit `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`
- creates the Auth user when missing and reuses an existing user by email without mutation by default
- updates existing users only with `--update-password` and/or `--update-metadata`; update responses report `updated=true` and `updated_fields` without echoing secrets beyond the explicit local JSON credentials payload
- returns `artifact_path` and `project_resolution` in JSON output
- writes a redacted `qa-user-ensure.json` artifact under the active run directory with user id/email, created/reused/updated flags, selected seed names, seed results, timestamp, dependency mode, and redacted credentials
- emits a redacted `qa_user.ensure` event with project, run id, status, user id, email hash, created/reused/updated flags, and seed names/results
- reports seed hooks as `skipped` with `reason=no_seed_hook_configured` unless `ENVCTL_QA_USER_SEED_CMD` or `ENVCTL_QA_USER_SEED_<NAME>_CMD` is configured
- seed hook results include status, exit code, cwd, and redacted stdout/stderr snippets; service-role keys and passwords are never stored in artifacts or events

## `playwright`

`playwright` runs a passthrough command against an already running frontend without starting another dev server.

```bash
envctl playwright --project feature-a-1 -- npx playwright test
envctl playwright --project feature-a-1 --json -- python -c 'import os; print(os.environ["QA_BASE_URL"])'
```

Behavior:

- resolves exactly one active project through the same fail-closed project guard
- exports `QA_BASE_URL`, `BASE_URL`, `ENVCTL_PROJECT_NAME`, `ENVCTL_RUN_ID`, `ENVCTL_RUNTIME_MODE`, and `ENVCTL_DEPENDENCY_MODE`
- writes `playwright-endpoints.json` under the active run's `test-results` directory and exports its path as `ENVCTL_ENDPOINTS_JSON` and `ENVCTL_ENDPOINTS_JSON_PATH`
- prefers the project's public frontend URL when one is projected or explicitly configured
- writes `playwright-runtime-metadata.json` under the active run's `test-results` directory with the endpoint artifact path and without persisting the inherited subprocess environment


## Runtime Resolution Events

Project-scoped runtime commands emit sanitized observability events when they resolve state:

- `state.project_resolution.ok` for successful guarded resolution
- `state.project_resolution.failed` for fail-closed resolution errors such as `requested_project_not_running`, `multiple_projects_not_supported`, and `ambiguous_project_selector`
- `state.cwd_runtime_mismatch` whenever a command computes a cwd/runtime mismatch warning, including JSON output paths

Resolution events include command, run id, mode, requested projects, selected projects, active projects, and inferred cwd project. They do not include passwords, service-role keys, full environment maps, or command env maps.

## Main Runtime Commands

High-value command families:

- `dashboard`
- `resume`
- `plan`
- `test`
- `logs`
- `health`
- `errors`
- `restart`
- `stop` / `stop-all`
- `kill` / `kill-all` (aliases for `stop` / `stop-all`)
- `doctor`
- `config`
- `pr`
- `commit`
- `review`
- `migrate`
- `install-prompts`

Specific action commands are non-interactive by default. For example, `kill-all`, `stop`, `blast-all`,
`logs`, `health`, `errors`, `test`, `pr`, `commit`, `review`, `migrate`,
`delete-worktree`, `blast-worktree`, and `self-destruct-worktree` behave as if
`--headless` was supplied unless you explicitly pass `--interactive`.

Current supported command surface:

- `blast-all`
- `blast-worktree`
- `clear-logs`
- `commit`
- `config`
- `dashboard`
- `debug-last`
- `debug-pack`
- `debug-report`
- `delete-worktree`
- `doctor`
- `endpoints`
- `ensure-worktree`
- `errors`
- `explain-startup`
- `preflight`
- `health`
- `help`
- `install-prompts`
- `list-commands`
- `list-targets`
- `list-trees`
- `logs`
- `migrate`
- `migrate-hooks`
- `playwright`
- `plan`
- `pr`
- `qa-user`
- `restart`
- `resume`
- `review`
- `show-config`
- `supabase-user`
- `show-state`
- `start`
- `stop`
- `stop-all`
- `test`

## Common Command Patterns

Run and inspect:

```bash
envctl show-config --json
envctl explain-startup --json
envctl --resume
envctl dashboard
```

Runtime scope shortcuts:

```bash
envctl --backend --headless          # dependencies + backend service only
envctl --frontend --headless         # dependencies + frontend service only
envctl --fullstack --headless        # dependencies + backend + frontend
envctl --both --headless             # alias for --fullstack
envctl --dependencies --headless     # dependencies only; no app services
envctl --entire-system --headless    # dependencies + all configured app services
envctl --trees --only-backend         # worktree backend only; skip frontend and dependencies
envctl --trees --no-deps             # worktree app services only; skip managed dependencies/prep
envctl --trees --no-infra            # worktree state/AI only; skip backend, frontend, and dependencies
envctl --plan feature/task --opencode --no-deps  # AI session without local dependency prep

envctl stop --backend --headless
envctl stop --frontend --headless
envctl stop --fullstack --headless
envctl stop --dependencies --headless
envctl stop --entire-system --headless
envctl kill --backend --headless     # alias for stop --backend
envctl kill-all --headless           # alias for stop-all
```

`--entire-system` starts managed dependencies plus configured or autodetected local app services. In a repo/worktree with no explicit backend/frontend command, directory, enablement, launch env section, additional service, or supported autodetectable app layout, envctl keeps the AI/session flow running without app services and reports that no local app system is configured.

Review branch-relative changes:

```bash
envctl review --project feature-a-1
envctl review --project feature-a-1 --review-base dev
```

Single-mode `review` resolves its base branch in this order:

1. `--review-base <branch>`
2. persisted worktree provenance from `.envctl-state/worktree-provenance.json`
3. the target branch's upstream
4. the repo default branch

The generated markdown now reports the resolved base branch, base ref, resolution source, merge-base, and the full diff from that merge-base through the current worktree state.

Interactive dashboard follow-up:

- during dashboard `review` setup for exactly one non-`Main` worktree, envctl can use the standard selector menu to ask whether to open one origin-side AI review tab if the launch transport is ready
- if you opt in and the review succeeds, envctl opens one cmux surface, starts the configured AI CLI from the repo root, and submits `review_worktree_imp` with the selected worktree plus reviewer notes pointing at the generated review bundle, worktree directory, and the original plan file that created the worktree
- choosing `No`, cancelling the selector, reviewing `Main`, reviewing multiple targets, or a failed review keeps the current markdown bundle-only flow
- direct `envctl review ...`, `python -m envctl_engine.actions.actions_cli review`, and other non-dashboard review paths never prompt for or launch this tab in v1

Run tests:

```bash
envctl test --all
envctl test --failed
envctl test --all --skip-startup --load-state
envctl test --failed --skip-startup --load-state
```

Logs and inspection:

```bash
envctl logs --all --logs-follow
envctl health --all
envctl errors --all
```

Target one project:

```bash
envctl test --project api
envctl logs --project api --logs-follow
envctl restart --project api
```

Run backend migrations:

```bash
envctl migrate --project feature-a-1
envctl migrate --main
```

`migrate` behavior:

- runs from `<project>/backend` when that directory exists; otherwise it falls back to the project root
- default command remains `<repo-python> -m alembic upgrade head`
- still honors `ENVCTL_ACTION_MIGRATE_CMD` when you need a custom wrapper command
- loads backend env from `backend/.env` by default
- honors `BACKEND_ENV_FILE_OVERRIDE` for worktrees and `MAIN_ENV_FILE_PATH` for Main mode
- exports `APP_ENV_FILE` when an env file is resolved for the migrate process
- when a saved run state already exists for the target, reuses envctl's current dependency URLs for `DATABASE_URL` and `REDIS_URL` unless an explicit backend env override file is in control
- on failure, envctl persists the raw migrate report under the run artifacts and surfaces an actionable summary in the dashboard/action metadata

Config management:

```bash
envctl config
printf '%s\n' '{"default_mode":"trees"}' | envctl config --stdin-json
```

Planning and worktrees:

```bash
envctl list-trees --json
envctl --plan
envctl --parallel-plan
envctl --sequential-plan
envctl ensure-worktree feature-a --json
```

`ensure-worktree` is the cheap automation-oriented worktree surface:

- creates or reuses exactly one envctl-managed worktree
- does not imply runtime/service startup
- returns `envctl.ensure_worktree.v1` in `--json` mode

Envctl-managed worktree creation disables repo-local Git hooks by default for reliability. The override is command-scoped
(`git -c core.hooksPath=/dev/null ...`) and does not edit repo, global, or hook files. Set
`ENVCTL_WORKTREE_GIT_HOOKS=inherit` when you intentionally want repo-local hooks to run during envctl-managed
worktree creation. This policy applies to `--plan`, `--setup-worktree`, `--setup-worktrees`, and `ensure-worktree`.

Commit defaults:

- `envctl commit` now reads its default commit message from the repo-local `.envctl-commit-message.md` file when you do not pass `--commit-message` or `--commit-message-file`
- treat `### Envctl pointer ###` as the boundary after the last successful default commit; everything after it is the next default commit message
- write one complete next commit message in `.envctl-commit-message.md` rather than multiple fragmented summaries
- envctl-local control artifacts (`.envctl*`, `MAIN_TASK.md`, `OLD_TASK_*.md`, `trees/`) stay local; if a broad `git add .` stages them, `envctl commit` unstages those protected paths before committing normal changes

Optional plan-agent launch config for `--plan`:

- `ENVCTL_PLAN_AGENT_TERMINALS_ENABLE=true` enables the feature
- `envctl --plan <selector> --cmux` enables the default cmux plan-agent launcher for this command without setting `CMUX=true`
- `SUPERSET_PROJECT=<project-id> envctl --plan <selector>` asks Superset to create or reuse a workspace for the branch and start Codex with the rendered implementation prompt; `SUPERSET=true` is optional when a project or workspace is configured
- `SUPERSET_WORKSPACE=<workspace-id> envctl --plan <selector>` runs Codex in an existing Superset workspace
- Superset transport uses public `superset workspaces create`, `superset agents run`, and optional `superset workspaces open` commands for workspace management; it does not use cmux surface commands
- `envctl --plan <selector> --omx` launches Codex through an OMX-managed detached tmux session instead of having envctl create the tmux window itself
- `envctl --plan <selector> --omx --ultragoal` enters the default/recommended Ultragoal OMX workflow inside that OMX-managed Codex session
- `envctl --plan <selector> --omx --ralph` enters the explicit Ralph compatibility workflow inside that OMX-managed Codex session
- `envctl --plan <selector> --omx --team` enters the Team OMX workflow inside that OMX-managed Codex session
- OMX-managed plan-agent launches set a deterministic envctl-owned `OMX_ROOT` under `<worktree>/.envctl-state/omx/<worktree-name>/` so envctl can discover OMX's managed tmux session, submit optional Codex `/goal` framing, submit the rendered prompt, and queue follow-up workflow steps even when OMX isolates unsafe/YOLO runtime state
- if that handoff fails, envctl records structured diagnostics that distinguish spawn failure, missing `session.json`, wrong-worktree state, tmux candidate mismatch, prompt bootstrap failure, stale final attach targets, exited OMX sessions, and removed worktrees
- OMX-managed plan launches revalidate the final tmux attach target before headless output prints `attach:` guidance; stale or exited OMX sessions are reported as failed/degraded handoffs with diagnostic metadata instead of stale attach commands
- when an OMX handoff is stale, unavailable, exited, or tied to a removed worktree, envctl does not silently start native tmux in the same command; it prints a `recovery:` command that switches the same plan selector to envctl-owned `--tmux`, preserves relevant scope/headless flags, includes `--new-session`, and omits OMX-only workflow flags such as `--ultragoal`, `--ralph`, and `--team`
- `ENVCTL_PLAN_AGENT_CLI=codex|opencode` selects the AI CLI for envctl-owned cmux/tmux launches; OMX launches always use Codex
- `ENVCTL_PLAN_AGENT_PRESET=implement_task` selects the prompt preset name by default
- `ENVCTL_PLAN_AGENT_CODEX_GOAL_ENABLE=true` submits Codex `/goal` session framing before the initial implementation prompt; local Superset Codex launches use an envctl Superset host-agent wrapper that types `/goal`, presses Enter, waits for `Goal active`, then submits the implementation prompt; `--goal`/`--codex-goal` enable it and `--no-goal`/`--no-codex-goal` disable it for one launch
- `ENVCTL_PLAN_AGENT_CODEX_CYCLES=<n>` controls the Codex TUI queued cycle workflow for cmux, tmux, and OMX-managed Codex sessions; the default is `2`
- `$envctl-create-plan-auto-codex` computes a `0` through `3` recommendation and uses that command-scoped count for its launch command; the global default remains `2`, and values above `3` are bounded to `3`
- OpenCode cmux and tmux launches submit the rendered prompt body directly and prepend `/ulw-loop` by default, so ULW/direct-prompt flows do not depend on an installed slash command. Use `--no-ulw-loop` to submit the rendered OpenCode prompt without that prefix for one launch.
- For `--plan --tmux --opencode`, envctl considers the AI launch successful only after the tmux pane shows a usable OpenCode prompt and the implementation prompt can be submitted. If tmux starts but OpenCode exits, stays on a loading screen, reports a shell/config error, or leaves a stale non-OpenCode pane behind, envctl reports an AI launch failure instead of printing implementation-session attach guidance.
- Codex installs envctl presets as explicit-only skills under `~/.codex/skills/envctl-*`; envctl still resolves the shipped prompt body directly when it needs to submit a preset itself
- `ENVCTL_PLAN_AGENT_BROWSER_E2E_ENABLE=true` queues the Codex/OMX `$browser` E2E follow-up; set it to `false` in `.envctl` to skip that prompt
- `ENVCTL_PLAN_AGENT_PR_REVIEW_COMMENTS_ENABLE=true` queues the final Codex/OMX PR review-comments follow-up; set it to `false` in `.envctl` to skip that prompt
- `ENVCTL_PLAN_AGENT_SHELL=zsh` selects the shell started in the new cmux surface or tmux window when envctl owns the terminal bootstrap
- `ENVCTL_PLAN_AGENT_REQUIRE_CMUX_CONTEXT=true` requires caller `CMUX_WORKSPACE_ID`
- `ENVCTL_PLAN_AGENT_CODEX_YOLO=true` appends `--dangerously-bypass-approvals-and-sandbox` to the default envctl-owned Codex cmux/tmux launch command; set it to `false` in `.envctl` when your Codex wrapper or config already supplies that flag
- `ENVCTL_PLAN_AGENT_CLI_CMD=/custom/cli --flag` overrides the typed AI CLI command text for envctl-owned cmux/tmux launches; when set, this raw command wins over the default Codex YOLO command builder; OMX-managed launches still use `omx --tmux` and then envctl submits the prompt into the created Codex session after discovering it from the selected OMX state root
- plan-agent launches prepare backend and frontend dependencies inside the selected worktree before the AI prompt is submitted; this is dependency prep only, not service startup or migrations
- generic configured backend Python commands such as `ENVCTL_BACKEND_START_CMD=python -m uvicorn ...` use the prepared backend runtime when a Poetry project or backend virtualenv is available
- `--ultragoal`, `--ralph`, and `--team` are mutually exclusive OMX-only launch modifiers; using them without `--omx` fails fast
- OMX-managed Team launches force `OMX_TEAM_WORKER_LAUNCH_ARGS=--dangerously-bypass-approvals-and-sandbox` so the worker lanes stay non-sandboxed too
- when enabled without an explicit workspace override, envctl derives the target as `"<current workspace> implementation"`
- `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE=workspace:123` targets an explicit cmux workspace and also enables the feature
- `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE=envctl` also works when you want to target a workspace by its title
- when a named target workspace does not exist yet, envctl creates it first and reuses that workspace's initial cmux starter surface for the first launch when the starter probe is unambiguous; otherwise it falls back to opening a new surface
- `CMUX=true` enables the feature and uses the default `"<current workspace> implementation"` target
- `CMUX_WORKSPACE=envctl` is a shorthand alias for targeting a named cmux workspace
- `SUPERSET=true`, `SUPERSET_PROJECT=<value>`, `ENVCTL_PLAN_AGENT_SUPERSET_PROJECT=<value>`, and `SUPERSET_WORKSPACE=<value>` select the Superset public-CLI transport unless `ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT` is explicitly set; canonical `ENVCTL_PLAN_AGENT_*` keys still win
- `CYCLES=<n>` is a shorthand alias for `ENVCTL_PLAN_AGENT_CODEX_CYCLES=<n>`
- `CYCLES` only changes the Codex cycle count and does not enable plan-agent launch by itself
- canonical `ENVCTL_PLAN_AGENT_*` values win when both canonical and alias forms are set
- by default (`ENVCTL_PLAN_AGENT_CODEX_CYCLES=2`), envctl first queues an `envctl ship` handoff follow-up, then `continue_task`, `implement_task`, `finalize_task`, enabled browser-E2E and PR review-comments follow-ups
- `ENVCTL_PLAN_AGENT_CODEX_CYCLES=0` submits the single implementation prompt and queues enabled browser-E2E and PR review-comments follow-ups for Codex/OMX surfaces
- `ENVCTL_PLAN_AGENT_CODEX_CYCLES=1` queues `implement_task`, `finalize_task`, enabled browser-E2E and PR review-comments follow-ups

Degraded plan-agent handoff:

- `envctl --plan <selector> --tmux --headless` and `envctl --plan <selector> --omx --headless` can still succeed when the implementation AI session starts but local backend/frontend startup cannot resolve a service command
- if startup revalidation finds that an OMX-managed attach target is stale or exited, headless output suppresses stale `attach:` guidance and prints a native fallback such as `ENVCTL_PLAN_AGENT_CODEX_CYCLES=<n> envctl --plan <selector> --tmux --entire-system --headless --new-session`
- this path prints `Implementation session is running, but local app startup failed.`, then an `AI session:` section with copy-pastable `attach:` and `kill:` guidance when a tmux session is known
- the `Local app startup:` section names the worktree, preserves the raw startup error, and points to `ENVCTL_BACKEND_START_CMD` / `ENVCTL_FRONTEND_START_CMD` when services should run locally
- plain `start`, `restart`, `resume`, dashboard, or `--plan` runs without a running implementation session keep normal fatal `Startup failed:` semantics

Optional dashboard review-tab launch:

- reuses `ENVCTL_PLAN_AGENT_CLI`, `ENVCTL_PLAN_AGENT_CLI_CMD`, `ENVCTL_PLAN_AGENT_SHELL`, `ENVCTL_PLAN_AGENT_REQUIRE_CMUX_CONTEXT`, and `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE`
- does not require `ENVCTL_PLAN_AGENT_TERMINALS_ENABLE=true`; the explicit yes/no dashboard prompt is the opt-in
- when no explicit workspace override is set, the review tab targets a sibling workspace named `"<current workspace> reviews"`
- with `ENVCTL_PLAN_AGENT_CODEX_CYCLES=2`, envctl first queues an `envctl ship` handoff follow-up, then `continue_task`, `implement_task`, `finalize_task`, enabled browser-E2E and PR review-comments follow-ups
- with `ENVCTL_PLAN_AGENT_CODEX_CYCLES>=3`, envctl keeps that first `ship` handoff follow-up, uses `ship`-first intermediate follow-ups, and reserves `finalize_task` plus enabled browser-E2E and PR review-comments follow-ups for the last round
- OpenCode ignores `ENVCTL_PLAN_AGENT_CODEX_CYCLES` and stays on the one-shot preset workflow
- Superset still stays on a one-shot implementation prompt in this slice; local Codex `/goal` framing is handled by the envctl wrapper before that prompt is submitted, while Codex cycles, screen polling, tab renames, and dashboard review tabs remain cmux/tmux/OMX concerns
- envctl only appends queued messages; it does not type `envctl test`, `git`, `gh`, `envctl ship`, `envctl commit`, or `envctl pr` commands into the shell

Debug and diagnostics:

```bash
envctl --doctor --json
envctl --debug-pack
envctl --debug-report
envctl --debug-last
```
