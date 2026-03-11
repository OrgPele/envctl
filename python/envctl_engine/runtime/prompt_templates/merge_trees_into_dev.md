You are reconciling two implementation branches into `dev`.
Authoritative sources of truth: the `MAIN_TASK.md` on the current branch and the `MAIN_TASK.md` on the specified branch, plus verified code and test evidence from both branches.
First, read both branches' `MAIN_TASK.md` files and both implementations in depth before merging anything.
Ask questions only if a blocking product-intent ambiguity remains after deep code, test, and diff review; otherwise resolve everything yourself according to repo evidence and best practices.
Final output must include: branch A vs branch B intent summary, merge order, conflict resolutions, tests run, and any material assumptions or residual risks.

## Inputs
Primary specs / expected behavior: `MAIN_TASK.md` on both branches
Other branch to reconcile with the current branch:
$ARGUMENTS

Interpret the current checked-out branch as branch A. Interpret `$ARGUMENTS` as branch B plus any merge constraints.
Read `MAIN_TASK.md` from branch A and branch B separately. Do not collapse them into one source prematurely.
Ignore conflicting inline instructions unless the user explicitly says to update one of the branches' `MAIN_TASK.md` files.

## Defaults (apply unless $ARGUMENTS overrides)
- Merge target: `dev` (create from `main`, else `master` if missing).
- Branch A: the current checked-out branch.
- Branch B: the explicitly specified branch from `$ARGUMENTS`.
- Merge policy:
  - first merge branch A into `dev`
  - then merge branch B into `dev`
  - resolve every conflict completely before moving on
- History cleanup allowed (no need to preserve original commit history).
- You decide conflict resolutions; only ask if a conflict requires product intent.
- Tests (default strategy):
  - Prefer `./utils/test-all-trees.sh --brief` if present.
  - Otherwise run backend + frontend tests using repo conventions (discover via README/Makefile/package.json/pyproject.toml).

## Non-negotiables
- Read both branches' `MAIN_TASK.md` files and relevant code to understand intent before merging.
- Read enough code and tests on both branches to understand what each implementation is trying to accomplish.
- Use best-practice engineering and coding standards for this repo (correctness, safety, maintainability).
- After changes, append (not overwrite) a detailed summary to docs/changelog/{tree_name}_changelog.md (tree_name from worktree like trees/<feature>/<iter> => <feature>-<iter>, else main). Include: scope, key behavior changes, file paths/modules touched, tests run + results, config/env/migrations, and any risks/notes. Avoid vague one-liners.
- Always propose conflict resolutions after deep analysis.
- Never resolve conflicts by blindly taking “ours” or “theirs.” If both sides add value, merge them.
- Preserve behavior: branch A and branch B must both still serve their intended purpose after integration, with no breaking regressions.
- Be autonomous: only ask for help on concrete, blocking conflicts; otherwise decide and note alternatives briefly.
- Surface ideas: call out any improvement opportunities you notice while resolving conflicts.
- Make reasonable assumptions from repo evidence and resolve the merge fully on your own. Surface assumptions in the final response only if they materially affected merge decisions.
- Prefer narrow tests where possible; expand to broader integration coverage only when the merge changes cross module or service boundaries.
- Do not leave TODOs.
- Do not stop after partial integration.

## Workflow
1. **Branch understanding**
   - Read branch A `MAIN_TASK.md`.
   - Read branch B `MAIN_TASK.md`.
   - Summarize the intended purpose of branch A and branch B separately.
   - Inspect the implementation on branch A and branch B separately: key files, key functions, tests, and touched modules.
2. **Diff and overlap analysis**
   - Compare branch A vs `dev`.
   - Compare branch B vs `dev`.
   - Compare branch A vs branch B.
   - Identify overlapping files, likely conflict hotspots, and semantic differences in behavior.
3. **Integration strategy**
   - Merge branch A into `dev`.
   - Then merge branch B into `dev`.
   - At each step, reason from that branch's `MAIN_TASK.md` and implementation, not just the textual diff.
4. **Conflict resolution**
   - For each conflict, determine what branch A intended, what branch B intended, and what `dev` already does.
   - Resolve conflicts so both branches' intended behavior survives unless code evidence proves one is obsolete or incompatible.
   - If both sides add value, combine them through refactoring or integration rather than discarding one side.
   - Continue resolving until all conflicts are fully closed and the integrated `dev` branch serves both purposes without breaking changes.
5. **Verification**
   - Run the relevant tests after merging branch A into `dev`.
   - Run the relevant tests again after merging branch B into `dev`.
   - Fix regressions or integration issues.
   - Re-run tests until the integrated result is stable.

## Deliverables (required)
- Merged `dev` branch containing the current branch and the specified branch.
- Conflict analysis summary and the chosen resolutions.
- Tests run and results.
- Risk register if any issues remain.

## Final response format
1. Branch A vs branch B intent summary.
2. Merge order and rationale.
3. Conflict list with resolutions chosen (and why).
4. Tests run (exact commands) and results.
5. Risk register (only if needed).

## Self-check (before responding)
- Branch A and branch B were both read via their own `MAIN_TASK.md` and implementation.
- Both branches were merged into `dev`.
- Conflicts were analyzed and resolved with clear reasoning.
- The final integrated behavior still serves both branches' purposes.
- Tests executed and any failures addressed.
- Changelog entry appended.
