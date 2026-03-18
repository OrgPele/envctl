You are reviewing an implementation worktree from the local/origin repo CLI.
The current local repo directory is the unedited baseline.
The edited code under review defaults to the worktree created from the current plan file unless `$ARGUMENTS` overrides that target with a specific worktree path or name.
This is a read-only review by default: do not write in the local/origin repo or the target worktree unless the user later asks for implementation changes.

## Inputs
- Baseline repo: the current working directory where this prompt was invoked
- Default target worktree: the worktree created from the current plan file
- Optional target worktree override: `$ARGUMENTS`
- Optional reviewer notes: any extra text after the target worktree override in `$ARGUMENTS`

## Required workflow
1. Resolve the target worktree.
   - If `$ARGUMENTS` specifies a worktree path or name, use that explicit override.
   - Otherwise default to the worktree created from the current plan file.
   - Accept either an absolute path, a relative path from the current repo root, or a sibling worktree name when an override is provided.
   - If a relative path override is provided, resolve it from the current repo root before reading anything.
2. Read `MAIN_TASK.md` from the target worktree first.
3. Inspect the target worktree's changed files, tests, and call paths in depth.
4. Compare the target worktree against the current local/origin repo baseline.
   - Read-only cross-worktree access is allowed for comparison.
   - Use diffs and direct file inspection to understand both behavior and intent.
5. Review findings first.
   - Use a findings-first review structure in the final response.
   - Prioritize bugs, regressions, incorrect assumptions, missing tests, and risky behavior.
   - Keep the review read-only unless the user explicitly redirects you into implementation work.

## What to validate
- The implementation matches `MAIN_TASK.md` in the target worktree.
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
2. Validation summary against `MAIN_TASK.md`.
3. Commands and comparisons run.
4. Residual risks or missing coverage, if any.
