You are preparing the next implementation iteration after an incomplete delivery.
Authoritative source of truth: current `MAIN_TASK.md`, plus code, tests, and git evidence from this repo.
First audit what was actually implemented; then archive the old task and write the next `MAIN_TASK.md` containing only remaining work.
Ask questions only when a blocking ambiguity remains after code, test, and git review.
Final output must include: archive file name, implemented vs remaining scope, new MAIN_TASK focus, git-evidence commands used, and material assumptions or residual risks.
WORKTREE BOUNDARY IS STRICT: MAKE ALL FILE EDITS ONLY INSIDE THE CURRENT CHECKED-OUT WORKTREE / REPO ROOT. Read outside it only for necessary historical/reference context, and keep that access read-only.

## Inputs
Primary source of truth: current MAIN_TASK.md
Additional gap evidence (optional):
$ARGUMENTS

If $ARGUMENTS contains pasted spec or reviewer findings, write it into `MAIN_TASK.md` first, then continue from `MAIN_TASK.md`.

## Success contract
- Preserve history by moving `MAIN_TASK.md` to the next available `OLD_TASK_<iteration>.md`; never overwrite an existing archive.
- Audit untracked, staged, unstaged, and committed divergence from the worktree's originating branch/ref when provenance is available.
- Classify every requirement from the current `MAIN_TASK.md` as fully implemented, partially implemented, or not implemented.
- Write a new `MAIN_TASK.md` with only remaining work, fully actionable acceptance criteria, and no TODO/later placeholders.
- If nothing remains, say so explicitly in the new `MAIN_TASK.md` instead of inventing work.
- Keep one complete commit/PR handoff message ready and pass it inline with `envctl ship -m "<message>"`. Do not write envctl-local commit-message ledger files. If more changes land before handoff, update the message to cover the full cumulative set of changes between commits.

## Required audit
1. Ensure `MAIN_TASK.md` exists.
2. Enumerate existing `OLD_TASK_*.md` files.
3. If `.envctl-state/worktree-provenance.json` exists, read it for `source_ref` / `source_branch`.
4. Run:
   - `git status --short`
   - `git diff --name-status`
   - `git diff --cached --name-status`
   - `git log --oneline --decorate -n 30`
5. If provenance provides an originating base, resolve it using `source_ref` first, then `source_branch`; run `git merge-base HEAD <originating-base>`, `git diff --name-status <merge-base>..HEAD`, and `git log --oneline --decorate <merge-base>..HEAD`.
6. If no provenance exists, state that committed-divergence evidence could not be anchored and use the best available git evidence.
7. Inspect relevant changed files and tests before writing the new task.

## Rewrite protocol
1. Build a requirement status matrix from current `MAIN_TASK.md`.
2. Rename `MAIN_TASK.md` to `OLD_TASK_<iteration>.md`.
3. Create a new `MAIN_TASK.md` with this structure:
   - `# <Title focused on remaining scope>`
   - `## Context and objective`
   - `## Remaining requirements (complete and exhaustive)`
   - `## Gaps from prior iteration (mapped to evidence)`
   - `## Acceptance criteria (requirement-by-requirement)`
   - `## Required implementation scope (frontend/backend/data/integration)`
   - `## Required tests and quality gates`
   - `## Edge cases and failure handling`
   - `## Definition of done`
4. Ensure every remaining gap is specific, testable, and implementable without another planning pass.

## Handoff rule
If this task itself changes files that should be committed, use `envctl ship -m "<message>"` in the normal case. The message must include scope, key files/modules, tests run and results, config/env/migration notes, and risks. Its Verification section must state what validation proved and any remaining human checks with expected results. Do not run `envctl commit` separately unless `ship` is unavailable, blocked, or you are intentionally doing commit-only maintenance.

## Final response format
1. File rename performed (`MAIN_TASK.md` -> `OLD_TASK_<iteration>.md`).
2. Summary of implemented vs remaining scope.
3. New `MAIN_TASK.md` focus and structure confirmation.
4. Commands used for git evidence.
5. Risk register only if needed.

## Self-check
- Original `MAIN_TASK.md` was archived safely.
- New `MAIN_TASK.md` contains all remaining work and excludes completed work.
- Requirements are specific, exhaustive, and testable.
- Final audit covered current worktree state plus committed divergence when provenance was available.
