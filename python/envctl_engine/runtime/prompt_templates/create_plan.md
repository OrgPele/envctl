You are creating an implementation plan, not changing code.
Outcome: write one repo-grounded plan under `todo/plans/<category>/<slug>.md`.
Authoritative source of truth: the user-provided scope plus verified repo evidence.
First, read the relevant code, tests, docs, and existing plans deeply enough to ground the plan before writing anything. If the user explicitly asks for a light/quick/testing-oriented pass, keep research narrow and inspect only what is needed to stay repo-grounded.
Ask questions only when a blocking requirement remains missing after repo review.
Final output must include: plan path, plan intent, files researched, and material assumptions or residual risks.
WORKTREE BOUNDARY IS STRICT: MAKE ALL FILE EDITS ONLY INSIDE THE CURRENT CHECKED-OUT WORKTREE / REPO ROOT. NEVER MODIFY FILES IN SIBLING WORKTREES OR ANY PATH OUTSIDE THE CURRENT REPO ROOT. You may read outside the current worktree ONLY when genuinely needed for historical/reference context (for example, to inspect how something worked previously), and that access MUST remain read-only.
CURRENT-REPO BOUNDARY IS ALSO STRICT FOR RESEARCH: stay inside the current working repo/root unless the user explicitly asks for cross-repo comparison. Do not run parent-directory or sibling-repo searches such as `find ..`, and do not inspect embedded tooling copies just because this skill originated from envctl.

## Inputs
Primary spec / expected behavior: provided by the user or linked project docs/tickets
Additional notes (optional):
$ARGUMENTS

Do not implement code. Only research and write the plan file.

## Success contract
- Read the code, tests, docs, and plans needed to ground the plan. If the user explicitly asks for a light/quick/minimal planning pass, avoid broad recursive searches, avoid unnecessary automated tests, and inspect only the files needed.
- Stay in the current repo/root and user-mentioned paths. Do not wander into sibling repos, parent directories, or unrelated vendored/tooling trees unless the task explicitly targets them.
- Use existing `todo/plans/` files as structure and quality references.
- Ask for missing context only when requirements, constraints, environment, data scope, or external contracts are materially blocking.
- Always write plan files to the repo root todo/plans/ (never inside tree worktrees).
- Make reasonable assumptions from repo evidence and surface only assumptions that materially affected the plan.
- Do not drift into implementation work.

## Planning constraints
- Place the plan in todo/plans/<category>/<slug>.md at the repo root where <category> is one of: broken, features, refactoring, implementations.
- Keep nesting to two levels max (todo/plans/<category>/<file>.md).
- The plan must be detailed enough that another engineer can implement it with minimal back‑and‑forth.

## Required research (do before writing)
1. Review any provided requirements and extract explicit requirements and constraints.
2. Review todo/plans/README.md if it exists; otherwise use the nearest relevant plan file(s) in the current repo for depth/format reference without leaving the repo root to hunt for a README elsewhere.
3. Identify the owning modules, services, and data models.
4. Inspect the current behavior in code: key files, key functions, and call paths.
5. Locate existing tests or missing coverage for the target area.
6. Review relevant config/env keys and any related docs.
7. Capture evidence (file paths + function names) to ground the plan.

Use repo-local AGENTS.md/tooling guidance and any injected code-intelligence context while researching. Default to `rg` for exact strings such as flags, env keys, log messages, docs prose, and error text; use Serena, CGC/CodeGraphContext, CodeGraph, or another graph tool only when it is actually configured for this checkout and relevant to the question.

## Context intake (ask if missing)
Before finalizing the plan, request any missing inputs that materially affect the solution:
- User-facing goal and acceptance criteria (what must be true when done).
- Scope boundaries / non-goals.
- Environment constraints (local/dev/prod differences, feature flags, services).
- Data migrations/backfills or existing data expectations.
- External integrations or API contracts.
- Performance, security, or compliance constraints.
- Example workflows or problem reports (logs/repros) if applicable.

## Plan file structure (must follow)
Use this structure (adapt section names only if truly necessary):

- # <Title>
- ## Goals / non-goals / assumptions (if relevant)
- ## Goal (user experience)
- ## Business logic and data model mapping
- ## Current behavior (verified in code)
- ## Root cause(s) / gaps
- ## Plan
  - ### 1) ... (clear, sequenced steps)
  - ### 2) ...
  - ### 3) ...
- ## Tests (add these)
  - Backend tests
  - Frontend tests
  - Integration/E2E tests
- ## Observability / logging (if relevant)
- ## Rollout / verification
- ## Definition of done
- ## Risk register (trade‑offs or missing tests)
- ## Open questions (only if unavoidable)

## Expectations for depth
- Include specific file references and function names where the behavior lives.
- Map planned changes to code locations and data flow.
- Spell out edge cases and how you will handle them.
- Include exact test files to add (or extend), with brief intent.
- Call out any required data migrations, backfills, or cleanup tasks explicitly.
- Prefer narrow tests where possible; call for broader integration coverage only when the behavior crosses module or service boundaries.

## Deliverables (required)
- One plan file created in todo/plans/<category>/.

## Launch scope default
Before showing or running any envctl worktree-and-prompt follow-up, default implementation launches to the full stack with `--entire-system` so every feature plan starts with dependencies plus all configured backend/frontend services available for E2E validation.

- For backend-only changes, still default to `--entire-system` unless the user explicitly requests `--only-backend` or repo evidence proves full-stack startup is impossible or actively harmful.
- For frontend-only changes, still default to `--entire-system` unless the user explicitly requests `--only-frontend` or repo evidence proves full-stack startup is impossible or actively harmful.
- For changes that touch both backend and frontend, cross-stack contracts, shared runtime config, browser-visible behavior, or anything uncertain, use `--entire-system`.
- For plans that truly need no runtime infrastructure (docs-only, prompt-only, pure static analysis, non-runtime metadata, or other edits that cannot benefit from backend, frontend, managed dependencies, or dependency prep), include `--no-infra` and explain why full-stack E2E does not apply.
- For explicitly requested dependency/container/infrastructure verification, keep `--entire-system` unless a narrower dependency-only validation is part of the user's request or the repo's evidence.
- If the user explicitly requests a launch scope, honor that request unless it conflicts with verified repo requirements.

Record the inferred launch scope in the plan's Rollout / verification section and include the exact envctl flags in any follow-up command you show or run.

## Browser E2E decision
Before showing or running any envctl worktree-and-prompt follow-up, decide whether the implementation needs the browser E2E follow-up. Record both the browser E2E decision and rationale in the plan's Rollout / verification section as `browser_e2e_required: true` or `browser_e2e_required: false`.

- Use `browser_e2e_required: true` when the task is browser-visible, touches frontend behavior, changes API contracts consumed by a UI, changes auth/session/form/dashboard flows, changes browser/runtime launch behavior, or when repo evidence leaves browser observability uncertain.
- Use `browser_e2e_required: false` only for docs-only, prompt-only, CLI-only, backend-only, runtime-only, test-only, or metadata changes where reviewed code and tests show no browser-visible surface.
- When `browser_e2e_required: false`, leave `ENVCTL_PLAN_AGENT_BROWSER_E2E_ENABLE` unset or set `ENVCTL_PLAN_AGENT_BROWSER_E2E_ENABLE=false` so the plan-agent queue skips the `$browser` follow-up.
- When `browser_e2e_required: true`, include `ENVCTL_PLAN_AGENT_BROWSER_E2E_ENABLE=true` in any envctl follow-up command you show or run so the `$browser` follow-up runs after implementation/finalization.

## Codex cycle recommendation
Before writing the final response, choose exactly one integer from `0` through `3` as the recommended Codex cycle count for implementation depth. Use this rubric:

- `0`: trivial docs, prompt, static edit, or very small one-file change where one implementation prompt is enough.
- `1`: small localized code or test change with low integration risk.
- `2`: normal multi-file feature or fix, moderate verification, or a task that benefits from one continuation/finalization pass.
- `3`: genuinely complex, high-risk, cross-module, runtime-sensitive, or architecture-sensitive work.

Prefer the smallest number that can plausibly finish the task and verify it; `3` is exceptional. Include a one-sentence rationale. Require the plan file's `Rollout / verification` section to record the recommended Codex cycle count, the intended launch-scope flags, and the browser E2E decision.

## Optional envctl follow-up
- After completing the required final response items, ask exactly one final approval question asking whether you should now use `envctl` to create or sync the implementation worktree(s) for this plan and launch the implementation prompt workflow.
- Do not run `envctl` unless the user explicitly says yes.
- When you refer to that follow-up, ground it in the real supported flow:
  - use an explicit selector for the created plan with `envctl --headless --plan <selector>`
  - if the user wants envctl to launch the AI prompts too, treat that as a deterministic repo-scoped flow rather than an inherited terminal-context flow
  - explain the supported launch surfaces clearly enough that the user does not need to run `envctl --help` to understand them:
    - `--cmux`: envctl launches the default cmux plan-agent workflow for this command without requiring an environment alias; prefer this when cmux is installed
    - `--tmux`: envctl creates or reuses the tmux session/window itself, launches the selected CLI, and submits the rendered prompt/workflow there
    - `--cmux --opencode` or `--tmux --opencode`: envctl launches OpenCode and prepends `/ulw-loop` to the first submitted prompt by default; add `--no-ulw-loop` only when the user explicitly wants to omit that prefix
    - `--omx`: envctl asks OMX to create the managed detached tmux/Codex session, then envctl submits the rendered prompt/workflow into that OMX-managed session
    - `--omx --ultragoal`: same OMX-managed launch, but the first submitted prompt enters the Ultragoal workflow
    - `--omx --ralph`: same OMX-managed launch, but the first submitted prompt enters the Ralph compatibility workflow
    - `--omx --team`: same OMX-managed launch, but the first submitted prompt enters the Team workflow
    - `--headless`: envctl stays non-interactive and prints follow-up/attach guidance instead of taking over the current terminal
    - `--new-session`: create a fresh cmux surface, tmux session, or OMX-managed session instead of attaching to an existing one
  - whenever you show a follow-up command, include `--entire-system` by default; use narrower flags (`--only-frontend`, `--only-backend`, or `--no-infra`) only when the plan records why full-stack E2E does not apply
  - whenever the plan records `browser_e2e_required: true`, prefix shown/run follow-up commands with `ENVCTL_PLAN_AGENT_BROWSER_E2E_ENABLE=true`; leave it unset or false when browser E2E is not required
  - default to the cmux launcher when cmux is installed; use `--tmux` only when cmux is unavailable or the user explicitly asks for tmux
  - whenever you show a follow-up command, also explain in plain language what happens when that exact command runs: whether envctl only prints guidance or actually launches a session, whether the session is tmux-managed by envctl or OMX-managed by omx, whether the current terminal is taken over, and how the user can reconnect to the launched session later
  - keep the wording operational rather than marketing: spell out what envctl creates or syncs, what CLI or session it starts, what prompt preset it submits, and what remains for the user or AI to do after launch
  - make clear that `opencode` applies only to the cmux/tmux launcher paths today; OMX-managed launches are Codex-only
  - if you show a cmux launch command, include an explicit repo-scoped shell form such as `cd <repo> && envctl --plan <selector> --cmux --entire-system`
  - if you show an OpenCode tmux launch command, include an explicit repo-scoped shell form such as `cd <repo> && envctl --plan <selector> --tmux --opencode --entire-system`
  - if you show a Codex tmux launch command, include an explicit repo-scoped shell form such as `cd <repo> && ENVCTL_PLAN_AGENT_CODEX_CYCLES=<n> envctl --plan <selector> --tmux --entire-system`
  - if you show an OMX-managed Codex launch command, include an explicit repo-scoped shell form such as `cd <repo> && ENVCTL_PLAN_AGENT_CODEX_CYCLES=<n> envctl --plan <selector> --omx --entire-system`
  - if you show an OMX-managed Ultragoal launch command, include `cd <repo> && envctl --plan <selector> --omx --ultragoal --entire-system`
  - if you show an OMX-managed Ralph compatibility launch command, include `cd <repo> && envctl --plan <selector> --omx --ralph --entire-system`
  - if you show an OMX-managed Team launch command, include `cd <repo> && envctl --plan <selector> --omx --team --entire-system`
  - if you show a headless OpenCode tmux launch command, include `cd <repo> && envctl --plan <selector> --tmux --opencode --entire-system --headless`
  - if you show a headless Codex tmux launch command, include `cd <repo> && ENVCTL_PLAN_AGENT_CODEX_CYCLES=<n> envctl --plan <selector> --tmux --entire-system --headless`
  - when you execute envctl launch commands yourself from an AI session, always add `--new-session` so you create a fresh session instead of attaching to an existing one unless the task explicitly requires reuse
  - when you explain how to reconnect to a launched tmux or OMX-managed session later, use `tmux attach -t <session>` rather than `tmux switch-client -t <session>`
  - if an existing tmux session may already exist and the user wants another one without being prompted, include `--new-session` in the shown command
  - if the user selects `codex + opencode`, run or show both repo-scoped commands explicitly as two separate envctl invocations: one Codex tmux command with `ENVCTL_PLAN_AGENT_CODEX_CYCLES=<n>` and one OpenCode tmux command without that env var
  - if the user selects `codex + omx`, run or show both repo-scoped commands explicitly as two separate envctl invocations: one tmux Codex command with `ENVCTL_PLAN_AGENT_CODEX_CYCLES=<n>` and one OMX-managed Codex command with `ENVCTL_PLAN_AGENT_CODEX_CYCLES=<n>`
  - when the user selects multiple AI launch choices, state clearly that each command creates its own separate session; do not describe them as one shared session
  - do not claim that envctl can launch multiple CLIs or launch surfaces in one combined command; multi-launch follow-up means executing the separate repo-scoped commands one after another behind the scenes
  - leave `ENVCTL_PLAN_AGENT_CLI_CMD` unset unless the selected CLI requires a non-standard executable name
  - default the launch preset to `implement_task`
  - if you mention Codex behavior, be accurate: envctl launches the CLI and submits the rendered `implement_task` prompt body (and optional rendered follow-up prompts/messages when configured), but it does not itself run `git`, `gh`, `envctl commit`, or `envctl pr`
  - do not tell the user to manually type `/prompts:implement_task`, `$envctl-implement-task`, or any other in-session command after an envctl-managed launch unless repo evidence proves a separate manual step is required; describe envctl as submitting the rendered prompt/workflow automatically when launch is enabled
  - the final question must mention only the launch settings that should be surfaced to the user
  - do not surface the internal `--new-session` default in the user-facing approval question unless the task specifically requires explaining it
  - do not ask the user to provide or confirm cmux workspace, cmux context, shell, or custom CLI command override unless a task-specific repo constraint makes the default tmux launch example insufficient
  - keep the closing concise: do not write a long prose paragraph explaining the commands when short operational phrasing is enough
  - after the one approval question, offer the manual path as exactly three standalone command lines: one for `codex`, one for `opencode`, and one for `omx`
  - when you show those manual commands, keep them bare and copy-pastable, and always use the `cd <repo> && envctl ...` form; do not append explanatory prose to the same lines
  - include only these explicit defaults in that final question unless repo evidence for this specific task requires different values:
    - AI launch choice: `codex`, `opencode`, `omx`, `codex + opencode`, or `codex + omx` (multi-launch choices mean run the separate repo-scoped commands one after another)
  - do not mention any other launch settings, defaults, or override knobs in the user-facing question
  - if the selected launch choice includes Codex or OMX-managed Codex, include `recommended Codex cycles: <n>` using the computed recommendation and offer Codex manual commands with `ENVCTL_PLAN_AGENT_CODEX_CYCLES=<n>` explicitly instead of relying on the runtime default
  - if the selected launch choice does not involve Codex, say that the Codex cycle count setting is ignored

## Final response format
1. Path of the plan file created.
2. One-paragraph summary of the plan intent.
3. Files referenced during research (short list).
4. Risk register (only if non-empty).
5. One short approval question asking whether you should run the envctl worktree-and-prompt follow-up now or whether the user wants to run it manually.
6. If you include manual commands, print exactly three standalone command lines: `codex`, `opencode`, `omx`.

## Self-check (before responding)
- Plan matches existing todo/plans/ quality and depth.
- Every claim is grounded in code or documented evidence.
- Tests and verification steps are concrete and complete.
- Plan file written with no implementation-side ledger update required.
