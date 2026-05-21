# Prompt Workflow Residual Contract Cleanup

## Context and objective

The prior iteration archived as `OLD_TASK_2.md` implemented most of the envctl
prompt workflow modernization in commit `644cc2c`:

- implementation/finalization prompts now prefer focused validation,
  `envctl test-plan --project <project> --json` when available, planned
  `envctl ship --project <project> --json`, compact manual fallback handoff, and
  artifact-protection wording;
- plan-agent first/intermediate/browser/review follow-up prompts no longer force
  repeated handoff work between cycles;
- cmux and tmux Codex cycle queueing now carries `requires_goal` metadata and
  queues `/goal ...` before goal-required queued direct prompts;
- OMX wording now states that OMX uses the initial goal frame and does not
  re-submit `/goal` before every queued cycle prompt;
- docs and prompt-install tests cover many stale contract terms, including
  `--tmux-new-session`, blanket `git add .`, old `envctl commit --headless`
  guidance, cmux launch examples, OpenCode `/ulw-loop`, and queued Codex goal
  behavior.

The current task is a focused residual cleanup. Fully implement the remaining
prompt contract gaps end-to-end, without broadening into unrelated launcher
features.

## Remaining requirements (complete and exhaustive)

1. Modernize `continue_task.md`.
   - Preserve its existing purpose: archive the previous `MAIN_TASK.md` to the
     next `OLD_TASK_<n>.md`, audit implementation evidence, and create a new
     implementation-ready `MAIN_TASK.md` for the next cycle.
   - Align its workflow language with the modern implementation/finalization
     contract:
     - use focused validation evidence selected from repo evidence;
     - reference the planned `envctl test-plan --project <current-worktree-name> --json`
       contract when available;
     - reference the planned `envctl ship --project <current-worktree-name> --json`
       handoff and compact manual fallback when handoff is actually needed;
     - keep `.envctl-commit-message.md` focused on one cumulative next commit;
     - treat `MAIN_TASK.md`, `.envctl-commit-message.md`, `.envctl-state/`,
       generated provenance, and related envctl control files as protected
       artifacts;
     - mention that queued Codex continuation cycles are expected to remain
       goal-scoped when Codex goal mode is enabled.
   - Do not reintroduce blanket `git add .`, old `envctl commit --headless`
     preference, broad default `envctl test --project ...`, or repeated
     commit/push/PR loops.

2. Finish automatic create-plan launch-scope wording.
   - Update `create_plan_auto_codex.md` and `create_plan_auto_opencode.md` so
     auto-launch command guidance is not hard-coded to `--entire-system` as the
     default for all plans.
   - The templates must require the generated plan's `Rollout / verification`
     section to record explicit launch-scope flags.
   - The launch command must use the selected launch-scope flags:
     - `--no-infra` for prompt-only, docs-only, static, or otherwise no-runtime
       plans;
     - `--entire-system` only when runtime services, full-stack behavior, browser
       validation, or integration risk actually require it;
     - narrower flags only when the plan records why they are sufficient.
   - Remove stale wording such as "feature plans should keep `--entire-system`
     by default" and "backend-only plan still keeps `--entire-system` by
     default".
   - Keep cmux, `--headless`, `--new-session`, OpenCode `/ulw-loop`, and Codex
     goal/default-cycle guidance intact.

3. Update user docs for the residual launch-scope contract.
   - Update `docs/user/planning-and-worktrees.md` and `docs/user/ai-playbooks.md`
     so auto-Codex and auto-OpenCode descriptions say launch scope comes from
     the plan, rather than implying unconditional `--entire-system`.
   - Include explicit examples or wording for `--no-infra` on prompt/static-only
     plans and `--entire-system` only when runtime services are required.
   - Do not reintroduce stale tmux-default wording or old manual handoff claims.

4. Strengthen regression coverage.
   - Extend `tests/python/runtime/test_prompt_install_support.py` so
     `continue_task` is checked for the same modern contract terms as
     implementation/finalization where relevant.
   - Add assertions that auto-Codex and auto-OpenCode templates no longer
     hard-code broad `--entire-system` as the default for all plans and no longer
     contain the stale "feature plans" / "backend-only plan" broad-scope wording.
   - Keep existing assertions for cmux, `--new-session`, OpenCode `/ulw-loop`,
     `--no-ulw-loop`, Codex goal behavior, and OMX initial-goal limitations.

## Gaps from prior iteration (mapped to evidence)

Fully implemented in commit `644cc2c`:

- `python/envctl_engine/planning/plan_agent/models.py` adds
  `_PlanAgentWorkflowStep.requires_goal`.
- `python/envctl_engine/planning/plan_agent/workflow.py` marks Codex direct
  implementation, continuation, and finalization prompts as goal-required.
- `python/envctl_engine/planning/plan_agent/cmux_transport.py` and
  `tmux_transport.py` queue `/goal ...` before goal-required queued direct
  prompts when `codex_goal_enable` is true.
- `python/envctl_engine/runtime/prompt_templates/implement_task.md`,
  `finalize_task.md`, `implement_plan.md`, and private plan-agent follow-up
  templates use the modern focused-validation and single-handoff vocabulary.
- `create_plan.md`, `create_plan_auto_codex.md`, `create_plan_auto_opencode.md`,
  `create_plan_auto_omx.md`, `docs/user/planning-and-worktrees.md`, and
  `docs/user/ai-playbooks.md` largely prefer cmux and `--new-session`.
- `tests/python/runtime/test_prompt_install_support.py` and
  `tests/python/planning/test_plan_agent_launch_support.py` cover stale prompt
  terms and queued goal-frame behavior.
- Validation passed after the prior implementation:
  - `uv run --extra dev pytest -q tests/python/runtime/test_prompt_install_support.py tests/python/planning/test_plan_agent_launch_support.py tests/python/runtime/test_runtime_feature_inventory.py`
    -> `251 passed, 45 subtests passed`
  - `uv tool run ruff check python tests scripts` -> passed.

Partially implemented:

- `continue_task.md` still carries the older rollover prompt. It preserves
  history and audits git evidence, but it does not include the modern focused
  validation, `envctl test-plan`, `envctl ship`, protected-artifact, or
  goal-scoped continuation vocabulary required by the previous task.
- Auto-create prompt launch scope is still too broad:
  - `create_plan_auto_codex.md` says to use `--entire-system` by default and
    says feature plans should keep `--entire-system` by default.
  - `create_plan_auto_opencode.md` says to use `--entire-system` by default and
    says backend-only plans still keep `--entire-system` by default.
  - docs mirror the auto-Codex/OpenCode command examples as unconditional
    `--entire-system` defaults.
- Existing tests still lock the auto-Codex and auto-OpenCode default commands
  with `--entire-system`, so they would not catch this residual contract drift.

Not carried forward:

- Do not implement real `envctl ship` or `envctl test-plan` commands in this
  task. The prompt contract may reference them as planned commands with compact
  fallback behavior.
- Do not change the existing cmux/tmux queued-goal implementation unless a test
  failure caused by the residual prompt updates proves it is necessary.
- Do not change branch/worktree identity or parent `.envctl` runtime-root logic;
  existing code and docs already cover those behaviors outside this residual
  prompt cleanup.

## Acceptance criteria (requirement-by-requirement)

- `continue_task.md` retains the rollover/history-preservation protocol and now
  includes modern focused-validation, planned test-plan, planned ship handoff,
  protected-artifact, and goal-scoped continuation wording.
- No installed prompt template contains `--tmux-new-session`, blanket
  `git add .`, `Prefer envctl commit --headless --main`, or stale repeated
  manual handoff-loop wording.
- `create_plan_auto_codex.md` and `create_plan_auto_opencode.md` require
  launch-scope flags to come from the generated plan and no longer present
  `--entire-system` as the default for all plans.
- `docs/user/planning-and-worktrees.md` and `docs/user/ai-playbooks.md` describe
  auto launch scope as plan-selected and include `--no-infra` for prompt/static
  work plus `--entire-system` only when runtime services are required.
- Prompt-install tests fail before the residual fixes and pass after them.
- Focused runtime inventory coverage remains green.

## Required implementation scope (frontend/backend/data/integration)

- Runtime prompt templates:
  - `python/envctl_engine/runtime/prompt_templates/continue_task.md`
  - `python/envctl_engine/runtime/prompt_templates/create_plan_auto_codex.md`
  - `python/envctl_engine/runtime/prompt_templates/create_plan_auto_opencode.md`
- Docs:
  - `docs/user/planning-and-worktrees.md`
  - `docs/user/ai-playbooks.md`
- Tests:
  - `tests/python/runtime/test_prompt_install_support.py`
- Frontend: none.
- Backend/runtime services: none.
- Data/migrations/config: none.

## Required tests and quality gates

Run all of the following after implementation:

- `uv run --extra dev pytest -q tests/python/runtime/test_prompt_install_support.py`
- `uv run --extra dev pytest -q tests/python/runtime/test_runtime_feature_inventory.py`
- `uv tool run ruff check python tests scripts`

Escalate to `tests/python/planning/test_plan_agent_launch_support.py` only if
the implementation touches plan-agent runtime code or launch orchestration.

## Edge cases and failure handling

- Keep auto launch guidance deterministic enough for installed prompt snapshot
  tests while allowing the selected launch-scope flag to differ by plan evidence.
- Keep `--no-infra` examples explicitly tied to prompt/static/no-runtime plans.
- Keep `--entire-system` available for runtime-service and browser-visible work;
  the cleanup must not make agents skip required validation for high-risk
  product changes.
- Preserve all existing surface-specific differences between Codex, OpenCode,
  and OMX prompts.

## Definition of done

- `OLD_TASK_2.md` archives the previous full prompt workflow modernization task.
- This `MAIN_TASK.md` contains only the residual prompt-contract cleanup work.
- Prompt templates, docs, and tests fully satisfy the acceptance criteria above.
- Required focused tests and Ruff pass locally.
- The implementation is committed, pushed to the active PR branch, and the PR is
  updated with validation evidence.
