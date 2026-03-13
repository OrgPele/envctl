You are doing a post-implementation review and hardening pass.
Authoritative source of truth: `MAIN_TASK.md`.
First, read `MAIN_TASK.md`, then inspect the changed code paths and the existing tests in depth.
Ask questions only if a blocking ambiguity remains after deep code and test review; otherwise resolve everything yourself according to repo evidence and best practices.
Final output must include: what you validated, commands run, tests added or changed, code improvements made, and any material assumptions or residual risks.
WORKTREE BOUNDARY IS STRICT: MAKE ALL FILE EDITS ONLY INSIDE THE CURRENT CHECKED-OUT WORKTREE / REPO ROOT. NEVER MODIFY FILES IN SIBLING WORKTREES OR ANY PATH OUTSIDE THE CURRENT REPO ROOT. You may read outside the current worktree ONLY when genuinely needed for historical/reference context (for example, to inspect how something worked previously), and that access MUST remain read-only.

## Inputs
Primary spec / expected behavior: MAIN_TASK.md
Additional notes (optional):
$ARGUMENTS

If $ARGUMENTS contains pasted spec content, write that content into `MAIN_TASK.md` first, then use `MAIN_TASK.md` as the only source of truth.
Ignore conflicting inline instructions after `MAIN_TASK.md` is written unless the user explicitly says to update `MAIN_TASK.md`.

## Goals (in order)
1. Verify functionality matches MAIN_TASK.md exactly (including edge cases).
2. Ensure the change is correctly wired into the system (routing/exports/DI/config/build steps).
3. Run the relevant tests and make them pass.
4. Improve test coverage: add tests for gaps, regressions, and tricky edge cases.
5. Polish: simplify code, improve readability, remove dead code, tighten types, handle errors, and match repo conventions.
6. Ensure CI-style checks pass (lint/format/typecheck/build if present).

## Non-negotiables
- Don’t ask questions unless you are truly blocked and cannot resolve by reading more code.
- Prefer reading more code over speculation.
- No TODOs, no “should work”, no partial implementations.
- If tests are flaky or slow, fix or isolate causes (determinism, time, randomness, IO, cleanup).
- Maintain backwards compatibility unless MAIN_TASK.md explicitly changes it.
- Follow best-practice engineering and coding standards for this codebase (correctness, safety, maintainability).
- After changes, append (not overwrite) a detailed summary to docs/changelog/{tree_name}_changelog.md (tree_name from worktree like trees/<feature>/<iter> => <feature>-<iter>, else main). Include: scope, key behavior changes, file paths/modules touched, tests run + results, config/env/migrations, and any risks/notes. Avoid vague one-liners.
- Iterate until behavior matches the spec and tests are green; expect multiple cycles.
- Make reasonable assumptions from repo evidence and resolve the task fully on your own. Surface assumptions in the final response only if they materially affected implementation.
- Prefer narrow tests first. Expand to broader integration coverage only when the behavior actually crosses module or service boundaries.
- Do not stop after partial implementation.

## Review protocol (do this before changing code)
1. Read MAIN_TASK.md and summarize the expected behavior and acceptance criteria.
2. Identify all files changed in the implementation; understand intent and data flow end-to-end.
3. Trace execution paths: happy path + error paths + boundary cases.
4. Locate and understand the existing tests and test utilities.
5. Determine the correct commands to run: unit/integration/e2e, plus lint/typecheck/build if applicable.

## Execution (must do)
- Run the relevant test suites and record failures.
- Fix failing tests or implementation issues.
- Add/adjust tests to cover missing cases from MAIN_TASK.md.
- Re-run tests until green.
- If there are no tests, create them following repo conventions.
- Refactor for clarity and maintainability after correctness is proven by tests.
- If any trade-offs or missing tests remain, include a short risk register.

## What to look for (checklist)
- Correctness vs spec (including edge cases)
- Error handling and user-facing messages
- Input validation and security (where relevant)
- Performance pitfalls (N+1, repeated IO, unnecessary recomputation)
- Race conditions / async cleanup
- Logging/telemetry consistency (if used)
- Types and API contracts (no breaking changes unless intended)

## Final response format
1. What you validated (bullet list against MAIN_TASK.md).
2. Commands you ran (exact).
3. Tests added/changed (what they cover).
4. Code changes made (high level).
5. Any remaining risks or follow-ups (should be rare; only if unavoidable).

## Self-check (before responding)
- Spec matches implementation and wiring.
- Tests are green or failures are explained.
- Coverage includes edge cases and regressions.
- Changes follow repo conventions and best practices.
