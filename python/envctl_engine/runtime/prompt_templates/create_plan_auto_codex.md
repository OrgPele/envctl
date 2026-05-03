You are creating an implementation plan, not changing code.
Implementation note: This is the auto-launch variant of `create_plan.md`; if the base research/planning contract changes, update this file in the same commit.
Authoritative source of truth: the user-provided scope plus verified repo evidence.
First, read the relevant code, tests, docs, and existing plans deeply enough to ground the plan before writing anything. If the user explicitly asks for a light/quick/testing-oriented pass, keep research narrow and do only the minimum inspection needed to stay repo-grounded.
Ask questions only if a blocking requirement is truly missing after deep repo review; otherwise resolve the plan yourself according to repo evidence and best practices.
Final output must include: the plan path, plan intent, files researched, and any material assumptions or residual risks.
WORKTREE BOUNDARY IS STRICT: MAKE ALL FILE EDITS ONLY INSIDE THE CURRENT CHECKED-OUT WORKTREE / REPO ROOT. NEVER MODIFY FILES IN SIBLING WORKTREES OR ANY PATH OUTSIDE THE CURRENT REPO ROOT. You may read outside the current worktree ONLY when genuinely needed for historical/reference context (for example, to inspect how something worked previously), and that access MUST remain read-only.
CURRENT-REPO BOUNDARY IS ALSO STRICT FOR RESEARCH: stay inside the current working repo/root unless the user explicitly asks for cross-repo comparison. Do not run parent-directory or sibling-repo searches such as `find ..`, and do not inspect embedded tooling copies just because this skill originated from envctl.

## Inputs
Primary spec / expected behavior: provided by the user or linked project docs/tickets
Additional notes (optional):
$ARGUMENTS

Do not implement code. Only research and write the plan file.

## Non-negotiables
- Read as much relevant code, tests, and docs as needed.
- If the user explicitly asks for a light/quick/minimal planning pass, honor that: avoid broad recursive searches, avoid unnecessary automated tests, and inspect only the files needed to produce a grounded plan.
- Prefer the current working directory and user-mentioned paths; do not wander into sibling repos, parent directories, or unrelated vendored/tooling trees unless the task explicitly targets them.
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
2. Review todo/plans/README.md if it exists; otherwise use the nearest relevant plan file(s) in the current repo for depth/format reference without leaving the repo root to hunt for a README elsewhere.
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

## Launch scope default
Before showing or running any envctl worktree-and-prompt follow-up, default implementation launches to the full stack with `--entire-system` so every feature plan starts with dependencies plus all configured backend/frontend services available for E2E validation.

- For backend-only changes, still default to `--entire-system` unless the user explicitly requests `--only-backend` or repo evidence proves full-stack startup is impossible or actively harmful.
- For frontend-only changes, still default to `--entire-system` unless the user explicitly requests `--only-frontend` or repo evidence proves full-stack startup is impossible or actively harmful.
- For changes that touch both backend and frontend, cross-stack contracts, shared runtime config, browser-visible behavior, or anything uncertain, use `--entire-system`.
- For plans that truly need no runtime infrastructure (docs-only, prompt-only, pure static analysis, non-runtime metadata, or other edits that cannot benefit from backend, frontend, managed dependencies, or dependency prep), include `--no-infra` and explain why full-stack E2E does not apply.
- For explicitly requested dependency/container/infrastructure verification, keep `--entire-system` unless a narrower dependency-only validation is part of the user's request or the repo's evidence.
- If the user explicitly requests a launch scope, honor that request unless it conflicts with verified repo requirements.

Record the inferred launch scope in the plan's Rollout / verification section and include the exact envctl flags in any follow-up command you show or run.

## Automatic envctl follow-up
The explicit auto skill invocation is the approval to launch envctl after the plan is written. Do not ask an approval question before launching.

Before launching, validate the plan path and selector in this exact order:
1. Confirm the plan path starts with `todo/plans/` and has exactly `todo/plans/<category>/<slug>.md` shape.
2. Confirm `<category>` is one of `broken`, `features`, `refactoring`, or `implementations`.
3. Confirm the file exists on disk.
4. Derive `<category>/<slug>` from that path: remove the `todo/plans/` prefix and the `.md` suffix.
5. Run the launch command from the repo root, not from a generated worktree.

If selector derivation fails, stop after writing the plan and report the exact issue. Do not guess a selector.
If the envctl launch command exits non-zero, report the plan path, attempted command, exit status, relevant stderr/stdout summary, and that implementation session launch did not complete.
If launch succeeds, report the plan path, selected launch surface, exact envctl command executed, attach/reconnect guidance printed by envctl when available, and that implementation work is now delegated to the launched session.
The prompt must not begin implementing in the original planning session after launching envctl.

Run the launch command after the plan path exists and selector derivation succeeds. Use `--entire-system` immediately before `--headless` by default; only replace it with a narrower explicit scope such as `--no-infra`, `--only-backend`, or `--only-frontend` when the plan records why full-stack E2E does not apply. Run exactly this default command:

```bash
cd <repo-root> && ENVCTL_PLAN_AGENT_CODEX_CYCLES=4 envctl --plan <category>/<slug> --tmux --entire-system --headless --tmux-new-session
```

For example, a no-runtime-infrastructure plan may replace the default with `cd <repo-root> && ENVCTL_PLAN_AGENT_CODEX_CYCLES=4 envctl --plan <category>/<slug> --tmux --no-infra --headless --tmux-new-session`, but feature plans should keep `--entire-system` by default.

This command uses the `implement_task` preset through the current plan-agent default. For this auto-Codex skill, `ENVCTL_PLAN_AGENT_CODEX_CYCLES=4` is command-scoped to the launched envctl process and must not be described as changing the global runtime default. Codex `/goal` submission is enabled by default and does not need an extra flag. envctl queues the rendered follow-up prompts/messages for the Codex cycle workflow; envctl itself does not run `git`, `gh`, `envctl commit`, or `envctl pr`.

## Final response format
1. Path of the plan file created.
2. One-paragraph summary of the plan intent.
3. Files referenced during research (short list).
4. Launch surface selected and exact command executed.
5. Launch result, including attach/reconnect guidance when envctl prints it.
6. Risk register (only if non-empty).

## Self-check (before responding)
- Plan matches existing todo/plans/ quality and depth.
- Every claim is grounded in code or documented evidence.
- Tests and verification steps are concrete and complete.
- Plan file written with no implementation-side ledger update required.
- Selector was derived only after the plan file existed.
- Envctl launch command was run from the repo root with `--headless --tmux-new-session`.
- No implementation work started in the original planning session after envctl launch.
