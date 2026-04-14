You are creating an implementation plan, not changing code.
Authoritative source of truth: the user-provided scope plus verified repo evidence.
First, read the relevant code, tests, docs, and existing plans in depth before writing anything.
Ask questions only if a blocking requirement is truly missing after deep repo review; otherwise resolve the plan yourself according to repo evidence and best practices.
Final output must include: the plan path, plan intent, files researched, and any material assumptions or residual risks.
WORKTREE BOUNDARY IS STRICT: MAKE ALL FILE EDITS ONLY INSIDE THE CURRENT CHECKED-OUT WORKTREE / REPO ROOT. NEVER MODIFY FILES IN SIBLING WORKTREES OR ANY PATH OUTSIDE THE CURRENT REPO ROOT. You may read outside the current worktree ONLY when genuinely needed for historical/reference context (for example, to inspect how something worked previously), and that access MUST remain read-only.

## Inputs
Primary spec / expected behavior: provided by the user or linked project docs/tickets
Additional notes (optional):
$ARGUMENTS

Do not implement code. Only research and write the plan file.

## Non-negotiables
- Read as much relevant code, tests, and docs as needed.
- Use existing planning files in todo/plans/ as structure and quality reference.
- Follow best-practice engineering and coding standards for this codebase (correctness, safety, maintainability).
- If key context is missing (requirements, constraints, environment, data scope), ask for it before finalizing the plan.
- Always write plan files to the repo root todo/plans/ (never inside tree worktrees).
- Make reasonable assumptions from repo evidence and resolve the plan fully on your own where possible. Surface assumptions in the final response only if they materially affected the plan.
- Do not drift into implementation work.

## Planning constraints
- Place the plan in todo/plans/<category>/<slug>.md at the repo root where <category> is one of: broken, features, refactoring, implementations.
- Keep nesting to two levels max (todo/plans/<category>/<file>.md).
- The plan must be detailed enough that another engineer can implement it with minimal back‑and‑forth.

## Required research (do before writing)
1. Review any provided requirements and extract explicit requirements and constraints.
2. Review todo/plans/ README and at least one relevant plan file for depth/format.
3. Identify the owning modules, services, and data models.
4. Inspect the current behavior in code: key files, key functions, and call paths.
5. Locate existing tests or missing coverage for the target area.
6. Review relevant config/env keys and any related docs.
7. Capture evidence (file paths + function names) to ground the plan.

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

## Optional envctl follow-up
- After completing the required final response items, ask which AI CLI the user wants to use for the implementation follow-up: `codex`, `opencode`, or `both`.
- If the user selects `codex` or `both`, also offer to configure the Codex cycle count and ask what cycle count they want to use.
- Then offer exactly two next-step choices grounded in the real supported envctl flow:
  1. I can run the implementation flow for you headlessly now.
  2. If you want to run it yourself interactively, I can give you the exact command.
- Do not run `envctl` unless the user explicitly says yes.
- If the user says yes to the headless auto-run option, also tell them how they will attach afterward once envctl launches the tmux session.
- If the user chooses the interactive/manual option, give them both exact commands and do not imply that anything already ran.
- When you refer to that follow-up, ground it in the real supported flow:
  - use an explicit selector for the created plan with `envctl --headless --plan <selector>` for the automated headless option
  - for the automated headless option, tell the user that envctl will print the attach command after launch so they can attach to the tmux session
  - for the interactive/manual option, print both commands in this exact shape:
    - Codex: `envctl --plan <selector> --tmux --codex`
    - Opencode: `envctl --plan <selector> --tmux --opencode`
  - if the user selects `both`, print both commands and say they can compare the two flows themselves
  - if the user selects `codex` or `both`, include the Codex cycle count in the follow-up guidance and let the user choose that value
  - if the user wants envctl to launch the AI prompts too, treat that as a deterministic repo-scoped flow rather than an inherited terminal-context flow
  - derive the cmux workspace name dynamically from the current repo root directory name as `"<repo-name> implementation"` and use that as `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE`
  - do not rely on inherited `CMUX_WORKSPACE_ID` or any current-workspace detection for this follow-up
  - leave `ENVCTL_PLAN_AGENT_CLI_CMD` unset unless the selected CLI requires a non-standard executable name
  - do not separately surface or require `ENVCTL_PLAN_AGENT_TERMINALS_ENABLE`; setting `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE` is sufficient to enable the launcher for this flow
  - default the launch preset to `implement_task`
  - if you mention Codex behavior, be accurate: envctl launches the CLI and submits the rendered `implement_task` prompt body (and optional rendered follow-up prompts/messages when configured), but it does not itself run `git`, `gh`, `envctl commit`, or `envctl pr`
  - the final question must mention only the launch settings that should be surfaced to the user
  - do not ask the user to provide or confirm cmux workspace, cmux context, shell, custom CLI command override, or launcher-enable flags; derive or use those internally
  - do not mention any other launch settings, defaults, or override knobs in the user-facing question

## Final response format
1. Path of the plan file created.
2. One-paragraph summary of the plan intent.
3. Files referenced during research (short list).
4. Risk register (only if non-empty).
5. One final approval question that:
   - asks whether the user wants `codex`, `opencode`, or `both`
   - if `codex` or `both` is selected, asks what Codex cycle count they want to use
   - offers exactly these two choices:
     - headless auto-run by envctl now
     - interactive manual run with commands you print for them
   - if the user chooses the headless auto-run option, says that envctl will print the attach command after launch so they can attach to the tmux session
6. If you include the manual option, print both commands in these exact shapes:
   - `envctl --plan <selector> --tmux --codex`
   - `envctl --plan <selector> --tmux --opencode`

## Self-check (before responding)
- Plan matches existing todo/plans/ quality and depth.
- Every claim is grounded in code or documented evidence.
- Tests and verification steps are concrete and complete.
- Plan file written with no implementation-side ledger update required.
