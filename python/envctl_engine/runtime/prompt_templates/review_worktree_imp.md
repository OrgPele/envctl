You are reviewing an implementation worktree from the local/origin repo CLI.
The current local repo directory is the unedited baseline.
The edited code under review defaults to the worktree created from the current plan file.
This is a read-only review by default: do not write in the local/origin repo or the target worktree unless the user later asks for implementation changes.

## Inputs
- Baseline repo: the current working directory where this prompt was invoked
- Default target worktree: the worktree created from the current plan file
- Launch arguments: `$ARGUMENTS`
- Explicit worktree override: the first path-like token in the launch arguments, if any
- Reviewer notes: the remaining launch-argument text after removing that explicit worktree override, if one was provided
- Reviewer notes may include a generated review bundle path and an explicit worktree directory path when envctl launches this prompt from the dashboard review flow
- Reviewer notes may also include the original plan file path that was used to create the worktree

## Required workflow
1. Resolve the target worktree.
   - Treat only the first path-like token as the explicit worktree override.
   - If that explicit override specifies a worktree path or name, use it.
   - Otherwise default to the worktree created from the current plan file.
   - Accept either an absolute path, a relative path from the current repo root, or a sibling worktree name when an override is provided.
   - If a relative path override is provided, resolve it from the current repo root before reading anything.
2. Resolve the original plan file.
   - If reviewer notes include an original plan file path, use that first.
   - Otherwise read `.envctl-state/worktree-provenance.json` from the target worktree and resolve the recorded `plan_file` relative to the baseline repo's `todo/plans/` first, then `todo/done/`.
   - If provenance does not contain a usable `plan_file`, infer the original plan only when there is exactly one unique plan-file match for the worktree feature name under `todo/plans/` or `todo/done/`.
   - If no original plan file can be resolved, report that explicitly in the review rather than substituting any task-file surrogate.
3. Read that resolved original plan file first when it is available.
4. Do not start with broad repo exploration before reading the original plan file.
5. If reviewer notes include a generated review bundle path, read that bundle immediately after the original plan file and use that bundle as the primary review guide before doing any wider inspection. Cross-check the bundle against the current repo state instead of rediscovering everything from scratch.
6. Only after reading the original plan file and any provided review bundle, inspect the target worktree's changed files, tests, and call paths in depth.
7. Compare the target worktree against the current local/origin repo baseline.
   - Read-only cross-worktree access is allowed for comparison.
   - Use diffs and direct file inspection to understand both behavior and intent.
8. Review findings first.
   - Use a findings-first review structure in the final response.
   - Prioritize bugs, regressions, incorrect assumptions, missing tests, and risky behavior.
   - Keep the review read-only unless the user explicitly redirects you into implementation work.

## What to validate
- The implementation matches the original plan file that created the worktree.
- The changed code is correctly wired through its runtime/module call paths.
- Tests cover the main behavior, edge cases, and likely regressions.
- The target worktree’s behavior is evaluated relative to the unedited current repo baseline, not in isolation.

## Guardrails
- Do not modify files in either repo during this review pass.
- Do not treat the current baseline repo as the implementation target.
- Do not assume `$ARGUMENTS` is already normalized; resolve it explicitly.
- If the target worktree cannot be resolved, stop and report exactly what was missing.

## Final response format
1. Findings first, ordered by severity, with file references from the target worktree.
2. Validation summary against the original plan file.
3. Commands and comparisons run.
4. Residual risks or missing coverage, if any.
