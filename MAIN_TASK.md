# Envctl Codex Cycle Range Completion Audit

## Context and objective

The prior task, archived as `OLD_TASK_2.md`, requested a compact Codex
plan-agent cycle scale from `0` through `3`, with runtime clamping, workflow
expansion, prompt guidance, installed skill text, docs, and tests all aligned to
that same scale.

Current repo evidence shows that the implementation is complete in commit
`95bce36` (`Limit Codex plan cycles to three`) on top of provenance base
`origin/codex/reuse-cgc-worktree-context` at merge-base
`dc131e8461c70657c63e8faaea72f12a357de62e`. There is no remaining product
implementation work for the prior task.

Objective: preserve the completed task history and keep this worktree ready for
handoff by documenting that the prior implementation is complete. Do not invent
new feature scope. Any subsequent work should be driven by a new user task,
review finding, failing check, or explicit product requirement.

## Remaining requirements (complete and exhaustive)

No remaining implementation requirements are carried forward from
`OLD_TASK_2.md`.

The prior task's requirements are complete:

1. Runtime source of truth:
   - `_PLAN_AGENT_CODEX_CYCLE_CAP` is `3` in
     `python/envctl_engine/planning/plan_agent/constants.py`.
   - `_parse_codex_cycles` still preserves invalid and negative handling as
     `invalid_codex_cycles`.
   - Values above `3` still produce `bounded_codex_cycles` and return `3`.
   - The global default remains `ENVCTL_PLAN_AGENT_CODEX_CYCLES=2`.

2. Workflow expansion:
   - `_build_plan_agent_workflow` still uses `_PLAN_AGENT_CODEX_CYCLE_CAP`.
   - Direct workflow construction with `codex_cycles=999` is bounded to
     `workflow.codex_cycles == 3`.
   - Existing queued workflow shape is preserved.

3. Prompt recommendation rubric:
   - `create_plan.md`, `create_plan_auto_codex.md`, and
     `create_plan_auto_omx.md` require exactly one integer from `0` through `3`.
   - The rubric documents `3` as genuinely complex, high-risk, cross-module,
     runtime-sensitive, or architecture-sensitive work.
   - The prompt wording preserves the "prefer the smallest number" behavior and
     makes `3` exceptional.

4. Docs and installed skill contracts:
   - User and reference docs describe the same `0` through `3` scale.
   - Docs remove the old split between create-plan recommendations and a
     separate runtime cap.
   - OpenCode notes continue to state that OpenCode ignores Codex cycle
     settings.
   - Auto-plan examples touched by the prior iteration use current `--cmux`
     wording where appropriate.

5. Tests:
   - Planning tests cover canonical `3`, canonical `4` bounded to `3`, alias
     `999` bounded to `3`, and workflow construction with `codex_cycles=999`.
   - Runtime prompt/install tests assert `0` through `3` and assert the old
     `0` through `8` phrase is absent from rendered prompt bodies and installed
     skill text.

## Gaps from prior iteration (mapped to evidence)

No product gaps remain.

Evidence reviewed:

- `git status --short` returned no unstaged or staged changes before this
  archival task.
- `git diff --name-status` returned no unstaged paths.
- `git diff --cached --name-status` returned no staged paths.
- Provenance file `.envctl-state/worktree-provenance.json` points to
  `source_ref: origin/codex/reuse-cgc-worktree-context` and
  `source_branch: codex/reuse-cgc-worktree-context`.
- `git merge-base HEAD origin/codex/reuse-cgc-worktree-context` returned
  `dc131e8461c70657c63e8faaea72f12a357de62e`.
- `git log --oneline --decorate <merge-base>..HEAD` showed exactly one
  implementation commit:
  `95bce36 Limit Codex plan cycles to three`.
- `git diff --name-status <merge-base>..HEAD` showed the runtime constant,
  prompt templates, docs, tests, worktree provenance, and previous task file as
  the only changed paths.
- Search evidence found no remaining old range descriptions in `python`,
  `tests`, or `docs` outside `docs/changelog/**`; the only `0` through `8` hits
  in active paths are negative assertions that verify the phrase is absent.
- Historical changelog text under `docs/changelog/**` remains intentionally
  unchanged, matching the archived task's risk register.

## Acceptance criteria (requirement-by-requirement)

This archival/audit task is complete when all of the following are true:

1. `OLD_TASK_2.md` exists and contains the prior `MAIN_TASK.md` content for
   "Envctl Codex Cycle Range Three-Point Scale".
2. `MAIN_TASK.md` states that no implementation work remains from the archived
   task and records the evidence supporting that conclusion.
3. `.envctl-commit-message.md` contains one focused next commit message for this
   archival/audit change after the `### Envctl pointer ###` marker.
4. No files outside the current worktree are modified.

## Required implementation scope (frontend/backend/data/integration)

- Task bookkeeping:
  - Rename the prior `MAIN_TASK.md` to `OLD_TASK_2.md`.
  - Create this new `MAIN_TASK.md`.
  - Update `.envctl-commit-message.md` for the next commit.

- Frontend:
  - None.

- Backend:
  - None.

- Data/migrations:
  - None.

- Runtime/integration:
  - None.

## Required tests and quality gates

No product test rerun is required for this task-file-only archival change. The
prior implementation was already validated with:

- `uv run --extra dev pytest -q tests/python/planning/test_plan_agent_launch_support.py -k 'codex_cycles or build_plan_agent_workflow_bounds_large_cycle_counts'`
- `uv run --extra dev pytest -q tests/python/runtime/test_prompt_install_support.py -k 'cycle or auto_codex or auto_opencode'`
- `uv run --extra dev pytest -q tests/python/runtime/test_command_exit_codes.py -k 'create_plan_auto_codex or create_plan_auto_opencode'`
- `uv run --extra dev ruff check python tests scripts`
- `uv tool run ruff check python tests scripts`

For final handoff of this archival task, run:

- `git status --short`
- `git diff --name-status`
- `git diff --cached --name-status`

## Edge cases and failure handling

- Do not create a new implementation requirement solely because the invoking
  prompt says the prior delivery was incomplete; rely on current task, code,
  tests, docs, and git evidence.
- Do not rewrite historical changelog entries that intentionally preserve past
  release notes.
- Do not modify sibling worktrees or paths outside this repo root.
- If future GitHub checks appear and fail, treat their logs as new evidence and
  create a new task only for the concrete failing requirement.

## Definition of done

- The previous task is archived as `OLD_TASK_2.md`.
- This `MAIN_TASK.md` clearly states that the prior task has no remaining
  implementation scope.
- `.envctl-commit-message.md` is updated for the archival/audit commit.
- Git evidence confirms the only uncommitted changes are the task archival,
  replacement task file, and commit-message bookkeeping.
