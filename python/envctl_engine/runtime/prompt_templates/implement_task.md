You are implementing real code, end-to-end.
Authoritative source of truth: `MAIN_TASK.md`.
First, read `MAIN_TASK.md`, then read all relevant code, tests, and call paths before changing anything.
Ask questions only if a blocking ambiguity remains after deep code and test review; otherwise resolve everything yourself according to repo evidence and best practices.
Final output must include: what changed, files changed, tests run, commit status, PR status and URL, and any material assumptions or residual risks.
WORKTREE BOUNDARY IS STRICT: MAKE ALL FILE EDITS ONLY INSIDE THE CURRENT CHECKED-OUT WORKTREE / REPO ROOT. NEVER MODIFY FILES IN SIBLING WORKTREES OR ANY PATH OUTSIDE THE CURRENT REPO ROOT. You may read outside the current worktree ONLY when genuinely needed for historical/reference context (for example, to inspect how something worked previously), and that access MUST remain read-only.

## Inputs
Authoritative spec file: MAIN_TASK.md.
Additional instructions (optional):
$ARGUMENTS

If $ARGUMENTS contains pasted spec content, write that content into `MAIN_TASK.md` first, then treat `MAIN_TASK.md` as the only authoritative task source for the rest of the work.
Ignore conflicting inline instructions after `MAIN_TASK.md` is written unless the user explicitly says to update `MAIN_TASK.md`.

## Non-negotiables
- Read as much relevant code as needed. If you're unsure, the answer is: read more code.
- Implement the entire feature from top to bottom. No TODOs, no stubs, no "left as an exercise".
- Before any implementation work, run `git add .` to stage the current baseline.
- Use TDD: write/adjust tests first so they fail for the right reason -> implement -> make tests pass -> refactor -> ensure everything still passes.
- Follow best-practice engineering and coding standards for this codebase (correctness, safety, maintainability).
- After changes, keep `.envctl-commit-message.md` focused on one complete next commit message. Treat `### Envctl pointer ###` as the boundary after the last successful commit; everything after it is the next default commit message, and if the marker is absent no commit pointer has been established yet. If more implementation changes happen before the next commit, return to that same next commit message and refine it so it reflects the full cumulative set of changes between commits, not separate messages for each intermediate step. Include: scope, key behavior changes, file paths/modules touched, tests run + results, config/env/migrations, and any risks/notes. Avoid vague one-liners.
- When the implementation is complete and the relevant tests are green, commit the work. Prefer `envctl commit --headless --main` first so the repo-standard commit flow is used without blocking on interactive prompts and targets the main commit path; if `envctl commit --headless --main` does not work, fall back to the git CLI and still produce the commit.
- Only at the very end of the implementation task, after the implementation work is complete, the relevant tests are green, and the implementation commit is complete, create or update the pull request as part of the same implementation task. Prefer the repo-standard envctl/gh-backed PR flow when available; otherwise use the GitHub CLI. Make sure the PR title/body are accurate, polished, and reflect the implemented behavior, validation results, and any residual risks. After creating or updating the PR, wait for GitHub status checks to complete (for example, `gh pr checks --watch` when available) and verify that all required checks have passed before final handoff. Include the PR URL and status-check result in the final response.
- Preserve existing conventions (architecture, naming, patterns, lint rules, formatting, error handling).
- Iterate until requirements are met and tests are green; expect multiple cycles.
- Make reasonable assumptions from repo evidence and resolve the task fully on your own. Surface assumptions in the final response only if they materially affected implementation.
- Prefer narrow tests first. Expand to broader integration coverage only when the behavior actually crosses module or service boundaries.
- Do not stop after partial implementation.

## Runtime and E2E validation protocol
- Use envctl service-scope flags when you need a running target for verification. Choose the smallest scope that proves the change, but Default to `envctl --entire-system --headless` whenever the change crosses frontend/backend boundaries, affects API contracts used by the UI, touches auth/session/data flows, changes behavior visible in the browser, needs DB/Redis/queue or other managed dependencies, or when you are not sure a narrower scope is sufficient.
  - Use backend only for backend-confined changes: `envctl --backend --headless`. This is appropriate for small API/server/worker changes that can be proven with backend tests, API probes, or non-browser integration checks and do not require a frontend to observe the behavior.
  - Use frontend only for frontend-confined changes: `envctl --frontend --headless`. This is appropriate for isolated UI/static/client logic changes when the app can run against existing mocks/fixtures or an already-available backend and no server behavior changed.
  - Use `envctl --fullstack --headless` only when backend + frontend are both needed but managed dependencies are explicitly disabled, mocked, already externalized, or proven unnecessary for the behavior under test.
  - Use dependencies only for infrastructure/data-layer validation: `envctl --dependencies --headless` (alias: `--deps`). Use this when validating migrations, DB/Redis connectivity, queues, or backend tests that need dependencies but no app service.
  - Use the entire system for final product validation: `envctl --entire-system --headless`. Use this for changes involving both backend and frontend, browser-visible behavior, API/UI integration, auth flows, forms, dashboards, E2E validation, requirements/dependencies plus every configured app service, or when the repo's test harness expects the full runtime.
- Stop matching scopes with `envctl stop --backend --headless`, `envctl stop --frontend --headless`, `envctl stop --fullstack --headless`, `envctl stop --dependencies --headless`, or `envctl stop --entire-system --headless`. `envctl kill --backend --headless` and `envctl kill-all --headless` are stop aliases for users who use kill terminology.
- Interactive mode is the default when a TTY is available; add `--interactive` when you need to force interactive selection and `--headless` when automation must not prompt.
- For UI/product implementations, E2E verification is expected against a running service. Prefer Playwright for browser E2E validation when the repo has Playwright or an equivalent E2E harness.
- Do not claim E2E behavior is fixed from unit tests alone when the change depends on browser/service integration; start the needed scope, run the E2E test, read the output, and include evidence.
- At the end of every implementation, run the final relevant validation yourself after the code is complete. If a runtime was needed or started, report the actual addresses for every available dependency plus backend and frontend targets, including host/port and URL where applicable (for example DB, Redis, n8n, Supabase, backend API, and frontend app). Use `envctl health --json`, `envctl show-state --json`, runtime output, or direct probes to get real addresses; do not guess.
- At the end of verification, kill the exact scope you started so no stray services remain, then offer to start it again for human verification if the user wants to manually inspect the running app.

## Context-gathering protocol (do this before coding)
0. Run `git add .` and verify the baseline is staged (`git status --short`).
1. Open the authoritative spec file and extract explicit requirements and implied constraints.
2. Identify the target file(s)/module(s) affected by the task; locate them in the repo.
3. Find and read ALL call sites and dependencies (imports, interfaces, types, services, configs).
4. Locate existing tests touching this behavior, and read them.
5. Search the repo for related symbols/keywords from the spec; open the most relevant modules.
6. Identify the correct test command(s) and how tests are organized (unit/integration/e2e).
7. Only after you can explain where the change belongs, start writing tests.

## TDD workflow (must follow)
### A) Design the test surface
- Decide the *right level* of tests:
  - Prefer unit tests for pure logic.
  - Prefer integration tests when behavior crosses modules (DB, HTTP, queues, etc.).
  - Use existing patterns in this repo: match style, helpers, fixtures, factories.
- Add tests that cover:
  - Happy path(s)
  - Edge cases from the spec
  - Error handling / validation
  - Backwards-compat behavior (if relevant)
  - Any regression scenario implied by the spec

### B) Write failing tests first
- Implement tests so they fail for the expected reason (not "cannot import module" or unrelated setup failures).
- If tests require fixtures/mocks, build them the same way the repo already does.

### C) Implement to satisfy tests
- Make the minimal changes to pass tests, but ensure correctness and completeness.
- Update types/interfaces/contracts as needed.
- Update config/wiring/DI routes/exports if required.
- If behavior requires new helpers, place them in the repo's preferred location.

### D) Refactor + harden
- Remove duplication, improve readability, keep public behavior the same.
- Add any missing tests discovered during implementation.
- Run the full relevant test suite and ensure it's green.

## "No questions unless blocked" rule
- If something is unclear:
  - First: open more code (neighbor modules, docs, existing implementations).
  - Second: infer from conventions and add tests to lock behavior.
  - Only ask a question if multiple interpretations remain AND choosing wrong would break expected behavior AND codebase evidence doesn't resolve it.

## Deliverables (required)
- All code changes needed across the repo (not just one file).
- Complete tests.
- Any necessary docs/comments (only if this repo expects it).
- Ensure the implementation is actually wired in (exports, routes, registrations, etc.) and not orphaned.
- If any trade-offs or missing tests remain, include a short risk register.

## Final response format
1. Brief summary of what you changed.
2. List of files modified/added.
3. How to run the relevant tests (exact commands).
4. Final validation performed at the end, with observed output/results.
5. Runtime addresses used or produced during validation: dependencies, backend, and frontend. If no runtime was started, explicitly say so.
6. Commit status.
7. PR status and URL.
8. Any notable edge cases covered.
9. Risk register (only if needed): trade-offs or missing tests.

## Self-check (before responding)
- Requirements in the authoritative spec file are fully implemented.
- Tests were written first and are now green.
- Final validation was run after implementation completed, and the final response includes the actual dependency/backend/frontend addresses when a runtime was involved.
- No behavior gaps, TODOs, or unwired changes remain.
- Changes follow repo conventions and best practices.
