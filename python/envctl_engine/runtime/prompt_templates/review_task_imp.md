You are doing a post-implementation review and hardening pass.
Authoritative source of truth: the original plan file that created this worktree.
First, resolve and read that original plan file, then inspect the changed code paths and the existing tests in depth.
Ask questions only if a blocking ambiguity remains after deep code and test review; otherwise resolve everything yourself according to repo evidence and best practices.
Final output must include: what you validated, commands run, tests added or changed, code improvements made, and any material assumptions or residual risks.
WORKTREE BOUNDARY IS STRICT: MAKE ALL FILE EDITS ONLY INSIDE THE CURRENT CHECKED-OUT WORKTREE / REPO ROOT. NEVER MODIFY FILES IN SIBLING WORKTREES OR ANY PATH OUTSIDE THE CURRENT REPO ROOT. You may read outside the current worktree ONLY when genuinely needed for historical/reference context (for example, to inspect how something worked previously), and that access MUST remain read-only.

## Inputs
Primary spec / expected behavior: the original plan file for this worktree
Additional notes (optional):
$ARGUMENTS

If $ARGUMENTS includes an explicit original plan file path, use that first.
Otherwise read `.envctl-state/worktree-provenance.json` from the current worktree and resolve the recorded `plan_file` relative to `todo/plans/` first, then `todo/done/`.
If provenance does not contain a usable `plan_file`, infer the original plan only when there is exactly one unique plan-file match for the worktree feature name under `todo/plans/` or `todo/done/`.
If no original plan file can be resolved, stop and report exactly what was missing instead of substituting `MAIN_TASK.md`.

## Goals (in order)
1. Verify functionality matches the original plan file exactly, including edge cases and acceptance criteria.
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
- Maintain backwards compatibility unless the original plan file explicitly changes it.
- Follow best-practice engineering and coding standards for this codebase (correctness, safety, maintainability).
- After changes, keep `.envctl-commit-message.md` focused on one complete next commit message. Treat `### Envctl pointer ###` as the boundary after the last successful commit; everything after it is the next default commit message, and if the marker is absent no commit pointer has been established yet. If more implementation changes happen before the next commit, return to that same next commit message and refine it so it reflects the full cumulative set of changes between commits, not separate messages for each intermediate step. Include: scope, key behavior changes, file paths/modules touched, tests run + results, config/env/migrations, and any risks/notes. Avoid vague one-liners.
- Iterate until behavior matches the spec and tests are green; expect multiple cycles.
- Make reasonable assumptions from repo evidence and resolve the task fully on your own. Surface assumptions in the final response only if they materially affected implementation.
- Prefer narrow tests first. Expand to broader integration coverage only when the behavior actually crosses module or service boundaries.
- Do not stop after partial implementation.

## Review protocol (do this before changing code)
1. Read the original plan file and summarize the expected behavior and acceptance criteria.
2. Identify all files changed in the implementation; understand intent and data flow end-to-end.
3. Trace execution paths: happy path + error paths + boundary cases.
4. Locate and understand the existing tests and test utilities.
5. Determine the correct commands to run: unit/integration/e2e, plus lint/typecheck/build if applicable.

## Execution (must do)
- Run the relevant test suites and record failures.
- Fix failing tests or implementation issues.
- Add/adjust tests to cover missing cases from the original plan file.
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
1. What you validated (bullet list against the original plan file).
2. Commands you ran (exact).
3. Tests added/changed (what they cover).
4. Code changes made (high level).
5. Any remaining risks or follow-ups (should be rare; only if unavoidable).

## Self-check (before responding)
- Spec matches implementation and wiring.
- Tests are green or failures are explained.
- Coverage includes edge cases and regressions.
- Changes follow repo conventions and best practices.
