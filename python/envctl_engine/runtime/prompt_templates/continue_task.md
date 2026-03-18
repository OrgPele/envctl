You are preparing the next implementation iteration after an incomplete delivery.
Authoritative source of truth: the current `MAIN_TASK.md`, plus code and test evidence from the repo.
First, audit what was actually implemented by reading the task, the code, the tests, and recent git history in depth.
Ask questions only if a blocking ambiguity remains after deep code, test, and git review; otherwise resolve everything yourself according to repo evidence and best practices.
Final output must include: archive file name, implemented vs remaining scope, new MAIN_TASK focus, git-evidence commands used, and any material assumptions or residual risks.
WORKTREE BOUNDARY IS STRICT: MAKE ALL FILE EDITS ONLY INSIDE THE CURRENT CHECKED-OUT WORKTREE / REPO ROOT. NEVER MODIFY FILES IN SIBLING WORKTREES OR ANY PATH OUTSIDE THE CURRENT REPO ROOT. You may read outside the current worktree ONLY when genuinely needed for historical/reference context (for example, to inspect how something worked previously), and that access MUST remain read-only.

## Inputs
Primary source of truth: current MAIN_TASK.md
Additional gap evidence (optional):
$ARGUMENTS

If $ARGUMENTS contains pasted spec or reviewer findings, write that content into `MAIN_TASK.md` first, then continue from `MAIN_TASK.md`.
Ignore conflicting inline instructions after `MAIN_TASK.md` is written unless the user explicitly says to update `MAIN_TASK.md`.

## Non-negotiables
- Preserve history first: rename current MAIN_TASK.md to `OLD_TASK_<iteration>.md` before creating a new MAIN_TASK.md.
- Determine `<iteration>` as the next available integer in repo root (do not overwrite any existing `OLD_TASK_*.md`).
- Use git CLI and code evidence to identify what was implemented vs what remains.
- Read as much relevant code, tests, and docs as needed.
- Follow best-practice engineering and coding standards for this codebase (correctness, safety, maintainability).
- After changes, keep `.envctl-commit-message.md` focused on one complete next commit message. Treat `### Envctl pointer ###` as the boundary after the last successful commit; everything after it is the next default commit message, and if the marker is absent no commit pointer has been established yet. If more implementation changes happen before the next commit, return to that same next commit message and refine it so it reflects the full cumulative set of changes between commits, not separate messages for each intermediate step. Include: scope, key behavior changes, file paths/modules touched, tests run + results, config/env/migrations, and any risks/notes. Avoid vague one-liners.
- Do NOT ask questions unless truly blocked by ambiguity that cannot be resolved from code, tests, git history, or docs.
- Optimize for completeness over speed: assume unlimited time, and specify everything required for full implementation.
- Make reasonable assumptions from repo evidence and resolve the task fully on your own. Surface assumptions in the final response only if they materially affected the new MAIN_TASK.
- Do not leave TODOs in the new MAIN_TASK.
- Do not stop after partial analysis of the previous iteration.

## Required protocol
1. Validate preconditions:
   - Ensure `MAIN_TASK.md` exists.
   - Enumerate existing `OLD_TASK_*.md` files.
2. Audit implementation evidence:
   - Run `git status --short`
   - Run `git diff --name-status`
   - Run `git diff --cached --name-status`
   - Run `git log --oneline --decorate -n 30`
   - Inspect relevant changed files and tests
3. Build a requirement status matrix from current MAIN_TASK.md:
   - Fully implemented
   - Partially implemented
   - Not implemented
4. Rename task file:
   - Move `MAIN_TASK.md` -> `OLD_TASK_<iteration>.md` (next available integer).
5. Create a new `MAIN_TASK.md` that includes only remaining work (partial + missing), rewritten as fully actionable requirements.
6. Ensure the new MAIN_TASK is implementation-ready with explicit acceptance criteria and no ambiguity.

## New MAIN_TASK.md structure (must follow)
- # <Title focused on remaining scope>
- ## Context and objective
- ## Remaining requirements (complete and exhaustive)
- ## Gaps from prior iteration (mapped to evidence)
- ## Acceptance criteria (requirement-by-requirement)
- ## Required implementation scope (frontend/backend/data/integration)
- ## Required tests and quality gates
- ## Edge cases and failure handling
- ## Definition of done

## Completeness standard for the new MAIN_TASK
- Every remaining gap from the previous task is included.
- Requirements are specific enough to implement confidently from the spec.
- Explicitly state to fully implement all items end-to-end.
- No placeholders, no TODO language, no “later” buckets for core scope.

## Deliverables (required)
- `OLD_TASK_<iteration>.md` created from the previous MAIN_TASK.md.
- New `MAIN_TASK.md` containing all remaining work, fully specified.
- Short summary of what was complete vs what was carried forward.
- Risk register only if unresolved ambiguity remains.

## Final response format
1. File rename performed (`MAIN_TASK.md` -> `OLD_TASK_<iteration>.md`).
2. Summary of implemented vs remaining scope.
3. New MAIN_TASK.md focus and structure confirmation.
4. Commands used for git evidence.
5. Risk register (only if needed).

## Self-check (before responding)
- Original MAIN_TASK.md was archived safely with the correct next iteration number.
- New MAIN_TASK.md contains all remaining work and excludes completed work.
- New MAIN_TASK.md emphasizes full implementation to completion.
- Requirements are specific, exhaustive, and testable.
