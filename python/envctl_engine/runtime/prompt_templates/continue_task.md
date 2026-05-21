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
- Audit both working-tree changes and committed divergence from the worktree's originating branch/ref.
- Read as much relevant code, tests, and docs as needed.
- Follow best-practice engineering and coding standards for this codebase (correctness, safety, maintainability).
- After changes, keep `.envctl-commit-message.md` focused on one complete next commit message. Treat `### Envctl pointer ###` as the boundary after the last successful commit; everything after it is the next default commit message, and if the marker is absent no commit pointer has been established yet. If more implementation changes happen before the next commit, return to that same next commit message and refine it so it reflects the full cumulative set of changes between commits, not separate messages for each intermediate step. Include: scope, key behavior changes, file paths/modules touched, tests run + results, config/env/migrations, and any risks/notes. Avoid vague one-liners.
- Treat `MAIN_TASK.md`, `.envctl-commit-message.md`, `.envctl-state/`, generated provenance, and related envctl control files as protected artifacts. Only stage or commit them when the active task explicitly requires it; otherwise keep them local and preserve repo/product commits for intentional implementation files.
- Use focused validation evidence selected from repo evidence. Prefer the planned structured contract `envctl test-plan --project <current-worktree-name> --json` when it exists; until then, record the exact pytest, lint, typecheck, build, smoke, or browser commands that prove implemented and remaining behavior. Escalate to broad `envctl test --project <current-worktree-name>` only when focused evidence is not strong enough.
- When a rollover cycle is also an explicit handoff boundary, prefer `envctl ship --project <current-worktree-name> --json` when available. Until `envctl ship` exists, use one compact manual fallback: inspect status, stage only intentional files, commit with the prepared message, push, update the PR, and wait for required GitHub checks.
- If this prompt is queued by a Codex plan-agent cycle, assume continuation work must remain goal-scoped when Codex goal mode is enabled. Do not downgrade the next `MAIN_TASK.md` to a plain prompt continuation.
- Do NOT ask questions unless truly blocked by ambiguity that cannot be resolved from code, tests, git history, or docs.
- Optimize for completeness over speed: assume unlimited time, and specify everything required for full implementation.
- Make reasonable assumptions from repo evidence and resolve the task fully on your own. Surface assumptions in the final response only if they materially affected the new MAIN_TASK.
- Do not leave TODOs in the new MAIN_TASK.
- Do not stop after partial analysis of the previous iteration.

## Required protocol
1. Validate preconditions:
   - Ensure `MAIN_TASK.md` exists.
   - Enumerate existing `OLD_TASK_*.md` files.
   - If present, read `.envctl-state/worktree-provenance.json` to identify the originating `source_ref` / `source_branch`.
2. Audit implementation evidence:
   - Run `git status --short`
   - Run `git diff --name-status`
   - Run `git diff --cached --name-status`
   - Run `git log --oneline --decorate -n 30`
   - If worktree provenance exists, resolve the originating base (`source_ref` first, then `source_branch`), run `git merge-base HEAD <originating-base>`, then audit both `git diff --name-status <merge-base>..HEAD` and `git log --oneline --decorate <merge-base>..HEAD`
   - If no worktree provenance exists, explicitly note that committed-divergence evidence could not be anchored to an originating branch/ref and fall back to the best available git evidence
   - Inspect relevant changed files and tests
   - Inspect focused validation evidence already run for the implementation. If coverage is missing, name the exact focused validation commands the next task must run, using `envctl test-plan --project <current-worktree-name> --json` when available.
3. Build a requirement status matrix from current MAIN_TASK.md:
   - Fully implemented
   - Partially implemented
   - Not implemented
4. Rename task file:
   - Move `MAIN_TASK.md` -> `OLD_TASK_<iteration>.md` (next available integer).
5. Create a new `MAIN_TASK.md` that includes only remaining work (partial + missing), rewritten as fully actionable requirements.
6. Ensure the new MAIN_TASK is implementation-ready with explicit acceptance criteria, focused validation commands, protected-artifact guidance, and no ambiguity.

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
- Keep the original goal active for queued Codex continuations by making the new task clear, bounded, and compatible with goal-scoped plan-agent cycles.
- No placeholders, no TODO language, no “later” buckets for core scope.
- If the previous iteration is genuinely 100% complete and nothing remains, do not invent more work; make that explicit in the new `MAIN_TASK.md` by stating clearly that there is nothing left to implement and that the prior task is fully complete.

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
- Final audit considered untracked/staged/unstaged changes plus committed divergence from the originating branch/ref when provenance was available.
