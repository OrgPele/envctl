# Envctl Prompt Workflow Modernization

## Goal

Modernize the envctl prompt templates and plan-agent cycle workflow so generated
plans, Codex cycles, OpenCode launches, docs, and tests all describe and execute
the current operating model:

- prefer cmux when available, with `--new-session` as the session-forcing flag;
- keep `--tmux-new-session` out of all user-facing guidance and tests;
- keep branch name, worktree project name, and generated worktree identity aligned;
- read runtime configuration from the parent repo `.envctl` when envctl is invoked
  inside a generated tree;
- use focused, relevant validation by default through a test-plan style workflow;
- use a single handoff command for add/commit/push/PR/check monitoring once that
  command exists, with a clear temporary fallback while it is being built;
- require Codex plan-agent cycles and iterations to run under explicit `/goal`
  framing instead of allowing later queued cycles to proceed as plain prompts.

This is a prompt/workflow refactor, not a feature UI change.

## Background / evidence

- `python/envctl_engine/runtime/prompt_templates/implement_task.md` still starts by
  asking the agent to run `git add .` before implementation, then later asks it to
  try `envctl commit --headless --main`, fall back to raw git, create or update a
  PR, and wait for GitHub checks. That is the old high-friction loop the new
  workflow is trying to compress.
- `python/envctl_engine/runtime/prompt_templates/finalize_task.md` similarly asks
  for a broad `envctl test --project <current-worktree-name>` and then repeats the
  commit/push/PR/check sequence.
- `_plan_agent_first_cycle_completion.md`,
  `_plan_agent_intermediate_cycle_completion.md`,
  `_plan_agent_browser_e2e_followup.md`, and
  `_plan_agent_pr_review_comments_followup.md` still encode the old manual
  commit/push/PR/check sequencing between cycles.
- `python/envctl_engine/runtime/prompt_templates/create_plan.md` still contains
  mixed tmux/cmux/OMX examples and user-facing wording that predates the current
  cmux-default and `--new-session` model.
- `docs/user/planning-and-worktrees.md` still documents auto-Codex as running a
  tmux-based command in at least one section, even though current implementation
  and tests now expect cmux-capable launch guidance.
- `python/envctl_engine/planning/plan_agent/workflow.py` builds the multi-cycle
  Codex workflow as:
  `implement_task`, completion message, `continue_task`, `implement_task`, ...
  and final `finalize_task`. The queued follow-up steps have no explicit
  goal-framing metadata.
- `python/envctl_engine/planning/plan_agent/cmux_transport.py` and
  `python/envctl_engine/planning/plan_agent/tmux_transport.py` submit `/goal`
  before the initial Codex prompt when goal mode is enabled, then queue later
  prompts directly through the Codex queue helpers. That means every subsequent
  iteration depends on the original goal remaining active, rather than the
  workflow making goal usage explicit per cycle.
- `tests/python/runtime/test_prompt_install_support.py` is the main snapshot-style
  contract for prompt wording. It should become the guardrail that prevents stale
  `--tmux-new-session`, old handoff instructions, and broad-test defaults from
  coming back.

## Proposed contract

Prompt templates should describe one coherent workflow:

- During implementation, run the smallest relevant tests or checks that prove the
  changed behavior. Use the planned `envctl test-plan --project <project> --json`
  contract when available; until then, name the exact focused commands selected
  from repo evidence.
- For handoff, use the planned `envctl ship --project <project> --json` contract:
  stage intended files, read `.envctl-commit-message.md`, commit, push, create or
  update the PR only when needed, monitor GitHub status, and return structured
  status. While `envctl ship` is not yet implemented, prompts may describe the
  manual fallback in one compact fallback block instead of repeating raw git and
  gh commands across every template.
- `MAIN_TASK.md`, `.envctl-commit-message.md`, `.envctl-state/`, generated
  provenance, and related control files must be covered by artifact-protection
  guidance, preferably through per-worktree `.git/info/exclude` plus a deliberate
  global-ignore policy for machine-local artifacts only.
- User-facing launch examples should prefer:
  `ENVCTL_PLAN_AGENT_CODEX_CYCLES=<n> envctl --plan <selector> --cmux --headless --new-session`
  with `--no-infra` for prompt/static-only plans and `--entire-system` only when
  runtime services are actually needed.
- OpenCode guidance should say `/ulw-loop` is the default first-prompt wrapper and
  `--no-ulw-loop` removes it for a one-off plain prompt.
- Codex launches should say goal mode is on by default for Codex plan-agent
  workflows, and each queued cycle should be goal-scoped or re-goal-framed before
  the cycle prompt is submitted.

## Implementation plan

1. Inventory and classify every prompt template.
   - Classify templates into planning, implementation, continuation,
     finalization, review, release, and plan-agent follow-up groups.
   - Record which templates mention `git add .`, `envctl commit`, raw git/gh PR
     commands, `--tmux-new-session`, `--tmux`, `--cmux`, `--omx`, `--ulw-loop`,
     `$browser`, `$browser-use`, `envctl test`, `envctl playwright`, and
     project/worktree naming assumptions.
   - Use this inventory as the migration checklist so no prompt is silently left
     on the old flow.

2. Define a shared prompt workflow vocabulary.
   - Add a small shared wording block or helper constants in
     `python/envctl_engine/runtime/prompt_install_support.py` only if that fits
     the existing renderer design; otherwise keep template edits explicit but
     synchronized by tests.
   - Define canonical phrases for focused validation, handoff, artifact
     protection, cmux launch defaults, OpenCode `/ulw-loop`, and Codex `/goal`
     usage.
   - Avoid introducing an abstraction that makes the markdown harder to review.

3. Rewrite implementation and finalization prompts.
   - Update `implement_task.md` to remove the unconditional `git add .`
     baseline and replace broad default validation with focused validation chosen
     from repo evidence.
   - Update `implement_task.md` to prefer the future single handoff command:
     `envctl ship --project <current-project-name> --json`.
   - Keep a compact fallback manual handoff block for the period before
     `envctl ship` lands, but do not duplicate the long manual loop in multiple
     sections.
   - Update `finalize_task.md` so it finalizes via focused/affected validation
     first and only escalates to full envctl validation for broad or risky work.
   - Update `continue_task.md` so rollover still preserves task history, but the
     cycle prompt aligns with focused tests, goal-scoped Codex work, and the
     single handoff contract.
   - Decide whether `implement_plan.md` remains a supported compatibility prompt
     or becomes a thin compatibility alias; remove stale wording either way.

4. Rewrite plan-agent follow-up prompts.
   - Replace `_plan_agent_first_cycle_completion.md` and
     `_plan_agent_intermediate_cycle_completion.md` with concise state/handoff
     expectations that do not force repeated commit/push/PR work unless the cycle
     is explicitly at a handoff boundary.
   - Update `_plan_agent_browser_e2e_followup.md` to run only when browser-visible
     validation is relevant, use injected endpoints when available, and avoid
     defaulting to a full stack if the plan scope is prompt/static-only.
   - Update `_plan_agent_pr_review_comments_followup.md` to keep the
     thread-aware GitHub review inspection behavior, but route any follow-up
     handoff through the same single handoff contract.

5. Make Codex goal framing explicit for every cycle.
   - Extend `_PlanAgentWorkflowStep` or the workflow builder so Codex queued
     steps can carry a `goal_text` or `requires_goal` flag.
   - Ensure the initial implementation prompt and every queued
     `continue_task`, `implement_task`, and `finalize_task` cycle is submitted
     with active goal framing when `codex_goal_enable` is true.
   - For cmux and tmux transports, add focused tests around queueing so a queued
     cycle cannot be sent without the expected goal behavior.
   - For OMX-managed Codex, document and test the supported behavior clearly:
     if OMX cannot re-submit `/goal` between queued prompts, the workflow should
     either keep a verified active goal across the queue or refuse to advertise
     per-cycle goal guarantees on that surface.
   - Keep `--no-goal` / `--no-codex-goal` as explicit opt-outs, and make the
     prompt/documentation wording say those opt-outs are unusual.

6. Update planning prompts and auto-plan skills.
   - Update `create_plan.md`, `create_plan_auto_codex.md`,
     `create_plan_auto_opencode.md`, and `create_plan_auto_omx.md` so launch
     guidance uses the current flag names and launch defaults.
   - Prefer cmux for Codex when present, `--new-session` for new sessions, and
     `--no-infra` for prompt-only/static plans.
   - Remove old instructions that say envctl only appends messages while the
     agent manually performs every handoff step; instead, describe what exists
     today and what the new single handoff command is expected to do once built.
   - Make generated plan files record the recommended cycle count and launch
     scope, but avoid pushing agents toward maximum cycles for narrow work.

7. Update docs and install contracts.
   - Update `docs/user/planning-and-worktrees.md` and any adjacent user docs that
     still show `--tmux-new-session`, stale tmux defaults, old manual prompt
     invocation, or broad validation defaults.
   - Update `AGENTS.md` only if prompt usage guidance there needs to reflect the
     same Serena/CGC/current workflow rules.
   - Update prompt-install tests so installed Codex, Claude, and OpenCode prompts
     retain their surface-specific differences while sharing the same modern
     workflow contract.

8. Add regression coverage.
   - Add snapshot assertions that no installed prompt contains
     `--tmux-new-session`.
   - Add assertions that planning prompts mention `--new-session`, cmux default
     behavior, OpenCode `/ulw-loop` default behavior, `--no-ulw-loop`, focused
     validation, and the single handoff contract.
   - Add assertions that implementation/finalization prompts no longer contain
     the unconditional `git add .` baseline or repeated long manual PR/check
     loops.
   - Add plan-agent workflow tests proving Codex cycle steps are goal-scoped when
     goal mode is enabled and not goal-scoped when explicitly disabled.
   - Add cmux/tmux transport tests for queued goal submission or the chosen
     equivalent guarantee.

## Rollout / verification

Recommended Codex cycles: 7.

Rationale: this touches prompt contracts, docs, tests, and the plan-agent queued
workflow, but it should stay below the maximum because it is mostly localized to
runtime prompts and launch orchestration.

Intended launch scope: `--cmux --no-infra --headless --new-session`.

Focused validation commands for the implementation work:

- `uv run pytest -q tests/python/runtime/test_prompt_install_support.py`
- `uv run pytest -q tests/python/planning/test_plan_agent_launch_support.py`
- `uv run pytest -q tests/python/runtime/test_runtime_feature_inventory.py`
- `uv tool run ruff check python tests scripts`

Escalate to broader tests only if changes leave the prompt/runtime boundary or
touch shared config parsing.

## Risks / open questions

- `envctl ship` and `envctl test-plan` may be separate planned features rather
  than already implemented commands. Prompt wording should distinguish current
  fallback behavior from the intended product workflow until those commands land.
- Codex `/goal` behavior across queued prompts may be constrained by the current
  Codex UI and by OMX. The implementation should verify what can be guaranteed
  per surface and document any surface-specific limitation instead of promising
  behavior the launcher cannot enforce.
- Some broad validation wording exists to protect end-to-end user-facing work.
  The cleanup should remove wasteful defaults without making agents skip required
  validation for high-risk or browser-visible changes.
