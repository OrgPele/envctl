You are implementing real code, end-to-end.
Authoritative source of truth: `MAIN_TASK.md`.
First read `MAIN_TASK.md`, then inspect the relevant code, tests, and call paths before editing.
Ask questions only when a blocking ambiguity remains after repo evidence is exhausted.
Final output must include: what changed, files changed, tests run, commit status, PR status and URL, runtime addresses if used, and material assumptions or residual risks.
WORKTREE BOUNDARY IS STRICT: MAKE ALL FILE EDITS ONLY INSIDE THE CURRENT CHECKED-OUT WORKTREE / REPO ROOT. Read outside it only for necessary historical/reference context, and keep that access read-only.

## Inputs
Authoritative spec file: MAIN_TASK.md.
Additional instructions (optional):
$ARGUMENTS

If $ARGUMENTS contains pasted spec content, write it into `MAIN_TASK.md` first. Then treat `MAIN_TASK.md` as the only authoritative task source unless the user explicitly says to update it again.

## Success contract
- Implement the complete requested behavior across all required files; leave no TODOs, stubs, or unwired changes.
- Preserve repo conventions for architecture, naming, linting, formatting, error handling, and safety.
- Use TDD: add or adjust tests so they fail for the intended reason, implement, pass tests, then refactor and rerun relevant validation.
- Prefer narrow tests first; expand to integration, runtime, or E2E coverage when behavior crosses modules/services or user-visible flows.
- Inspect the baseline with `git status --short`; do not stage files manually during the normal path. Do not run manual staging commands such as `git add .`. `envctl ship` stages intended non-protected paths and skips envctl-local artifacts.
- Keep one complete commit/PR handoff message ready and pass it inline with `envctl ship -m "<message>"`. Do not run `envctl commit` separately unless `ship` is unavailable, blocked, or you are intentionally doing commit-only maintenance. Do not write envctl-local commit-message ledger files. If implementation continues after the message is drafted, update it to reflect the full cumulative set of changes between commits.

## Validation and ship
- During implementation, use `envctl test-focused` from inside the current generated worktree. From elsewhere, use `envctl test-focused --project <current-worktree-name>`.
- Run broader validation only when the plan, code evidence, or risk requires it.
- When relevant tests are green, run `envctl ship -m "<message>"` from inside the current worktree; add `--project <current-worktree-name>` only when operating from elsewhere, as in `envctl ship --project <current-worktree-name> -m "<message>"`.
- `ship` commits, pushes, creates a PR when none exists, reuses or updates the existing PR otherwise, predicts merge conflicts, waits for target GitHub Tests checks, and returns JSON with the PR URL, `pr_created`, `operation_statuses`, `checks_state`, `passed_checks`, `failing_checks`, `pending_checks`, `checks_error`, and merge-conflict details.
- If a real subagent or background-task tool is available, delegate `envctl ship -m "<message>"` there and keep the main implementation thread moving on non-overlapping work. The worker reports only commit/push/PR failures, `status: "merge_conflicts"`, failed checks, pending-check timeout, no-checks-reported status, or actionable review comments. A successful ship result is silent.
- Do not run raw `git`, `gh`, or separate commit/PR/status commands unless `ship` is unavailable or failed with actionable fallback instructions. Use manual commit, PR, or GitHub CLI checks only as that fallback.
- If `ship` returns `status: "merge_conflicts"`, use its `merge_conflicts.conflicting_files`, `messages`, and `resolution_steps` payload, then rerun validation and `ship`.
- Only inspect PR review comments when `ship` reports actionable review-comment status or when the dedicated PR review-comments follow-up prompt is running.

## Runtime and E2E validation
- Start runtime scopes only when they prove the change. Default to `envctl --entire-system --headless` for frontend/backend integration, browser-visible behavior, API contracts used by UI, auth/session/data flows, managed dependencies, queues, or uncertain scope.
- Use narrower scopes when evidence supports them: `envctl --backend --headless`, `envctl --frontend --headless`, `envctl --fullstack --headless`, or `envctl --dependencies --headless` / `--deps`.
- Stop exactly the scope you started: `envctl stop --backend --headless`, `envctl stop --frontend --headless`, `envctl stop --fullstack --headless`, `envctl stop --dependencies --headless`, or `envctl stop --entire-system --headless`. `envctl kill --backend --headless` and `envctl kill-all --headless` are stop aliases.
- For UI/product behavior, prove the behavior against a running service. Prefer Playwright or the repo's E2E harness when available; do not claim browser/service integration from unit tests alone.
- After runtime validation, report actual addresses for every available dependency plus backend and frontend target using `envctl health --json`, `envctl show-state --json`, runtime output, direct probes, or `envctl endpoints --project <actual-project-name> --json`; do not guess.

## Codex skills and envctl helpers
- When installed as a Codex skill or direct prompt, use available named Codex skills such as `$browser` for browser validation when present, following active skill and AGENTS.md instructions.
- Use the injected worktree code-intelligence context when envctl adds one. Otherwise follow repo-local guidance: use `rg` for exact strings, and only use Serena, CGC/CodeGraphContext, CodeGraph, or another graph tool when configured for this checkout and relevant.
- Resolve the actual envctl project target before project-scoped helpers. Prefer `envctl list-targets --json`, `envctl show-state --json`, or `envctl endpoints --project <candidate> --json`; worktree directory names are not always valid project names.
- Use `envctl qa-user ensure --project <actual-project-name> --email <email> --password <password> --json` for deterministic local QA credentials.
- Use `envctl playwright --project <actual-project-name> -- <executable> [args...]` for Playwright/browser-test commands against the active project frontend without starting a second dev server.

## Implementation loop
1. Read `MAIN_TASK.md`; extract explicit requirements, implied constraints, non-goals, and validation gates.
2. Identify affected modules, call sites, dependencies, config, docs, and tests.
3. Search related symbols or exact strings from the spec and open the most relevant files.
4. Choose the right test surface: unit for pure logic, integration for cross-module/service behavior, E2E for browser or runtime behavior.
5. Write failing tests first, using existing fixtures and style.
6. Implement the minimal complete change, wire it into exports/routes/config as needed, then refactor without changing behavior.
7. Run final relevant validation yourself after implementation is complete.

## Final response format
1. Brief summary of what changed.
2. Files modified or added.
3. Exact tests/validation run and observed results.
4. Runtime addresses used or produced; if none, say no runtime was started.
5. Commit status.
6. PR status and URL.
7. Edge cases covered.
8. Risk register only if trade-offs or missing tests remain.

## Self-check
- `MAIN_TASK.md` requirements are fully implemented.
- Tests were added or adjusted before implementation where applicable and are now green.
- Final validation ran after implementation completed.
- Runtime/browser claims are backed by runtime/browser evidence when needed.
- No TODOs, behavior gaps, unwired changes, or unrelated edits remain.
