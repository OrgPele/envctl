# Envctl Codex Cycle Range Three-Point Scale

## Goals / non-goals / assumptions

Goals:

- Change the Codex plan-agent cycle range from the current broad recommendation
  scale to a compact `0` through `3` scale.
- Make `3` mean a genuinely complex task, not a normal multi-file task.
- Keep the global default at `2` unless implementation evidence shows a better
  default is required.
- Align runtime clamping, generated prompt guidance, installed skill text, docs,
  and tests so the behavior is not split between "prompt recommendation" and
  "runtime implementation cap".

Non-goals:

- Do not redesign the queued Codex workflow shape in this change.
- Do not change OpenCode behavior; OpenCode still ignores Codex cycle counts.
- Do not change launch surface defaults such as cmux, tmux, OMX, or
  `--new-session` beyond updating stale examples encountered in the touched
  docs/tests.

Assumption:

- The user wants product behavior to use the smaller range, not only the wording
  in `$envctl-create-plan-auto-codex`. Therefore direct env/config values above
  `3` should be bounded to `3`, and prompt recommendations should never select
  `4` or higher.

## Goal (user experience)

When a user creates or launches a Codex plan-agent workflow, every visible
recommendation and every accepted cycle count follows the same compact scale:

- `0`: one initial implementation prompt only, plus whatever non-cycle follow-up
  prompts remain enabled.
- `1`: small localized change.
- `2`: normal implementation that benefits from one continuation/finalization
  round.
- `3`: genuinely complex, risky, cross-module, or architecture-sensitive work
  that needs the maximum available continuation depth.

If a user or config provides `ENVCTL_PLAN_AGENT_CODEX_CYCLES=999` or
`CYCLES=999`, envctl should report the bounded-cycle warning and use `3`.

## Business logic and data model mapping

- Runtime parsing lives in
  `python/envctl_engine/planning/plan_agent/config.py::_parse_codex_cycles`.
  It reads `ENVCTL_PLAN_AGENT_CODEX_CYCLES`, the `CYCLES` alias, and config raw
  values, then bounds them using `_PLAN_AGENT_CODEX_CYCLE_CAP`.
- The hard cap constant lives in
  `python/envctl_engine/planning/plan_agent/constants.py` as
  `_PLAN_AGENT_CODEX_CYCLE_CAP = 10`.
- Workflow expansion lives in
  `python/envctl_engine/planning/plan_agent/workflow.py::_build_plan_agent_workflow`.
  It independently bounds the requested cycles with the same cap before
  expanding queued `continue_task`, `implement_task`, and `finalize_task` steps.
- Prompt recommendation wording lives in:
  - `python/envctl_engine/runtime/prompt_templates/create_plan.md`
  - `python/envctl_engine/runtime/prompt_templates/create_plan_auto_codex.md`
  - `python/envctl_engine/runtime/prompt_templates/create_plan_auto_omx.md`
- Installed prompt rendering and prompt contract tests live in
  `python/envctl_engine/runtime/prompt_install_support.py` and
  `tests/python/runtime/test_prompt_install_support.py`.
- Runtime and command docs currently mention the old range in:
  - `docs/user/planning-and-worktrees.md`
  - `docs/user/ai-playbooks.md`
  - `docs/reference/configuration.md`
  - `docs/reference/commands.md`

## Current behavior (verified in code)

- `constants.py` sets `_PLAN_AGENT_CODEX_CYCLE_CAP = 10`.
- `_parse_codex_cycles` returns `_PLAN_AGENT_CODEX_CYCLE_CAP` plus
  `bounded_codex_cycles` when an env/config value is above the cap.
- `_build_plan_agent_workflow` also clamps to `_PLAN_AGENT_CODEX_CYCLE_CAP`, so a
  direct call with `codex_cycles=999` expands a workflow with `10` cycles.
- `tests/python/planning/test_plan_agent_launch_support.py` currently asserts
  this old cap in:
  - `test_resolve_plan_agent_launch_config_bounds_large_cycles_alias`
  - `test_build_plan_agent_workflow_bounds_large_cycle_counts`
- `tests/python/runtime/test_prompt_install_support.py` asserts that create-plan
  prompts contain `exactly one integer from \`0\` through \`8\``.
- `tests/python/runtime/test_command_exit_codes.py` checks the installed
  auto-Codex skill text for the same `0` through `8` phrase.
- Docs under `docs/user` and `docs/reference` describe create-plan skills as
  computing `0` through `8` recommendations, while also saying lower-level
  runtime parsing uses a separate implementation cap.

## Root cause(s) / gaps

- The recommendation scale and runtime cap drifted apart: prompts talk about
  `0` through `8`, while runtime still accepts and expands up to `10`.
- The broad `0` through `8` rubric encourages over-launching continuation cycles
  for ordinary work.
- Tests lock the old values in several layers, so changing only prompt markdown
  would leave direct env/config behavior and workflow expansion inconsistent.
- Docs explicitly preserve the old split between create-plan recommendation
  policy and runtime implementation cap; that split should go away for this
  simpler behavior.

## Plan

### 1) Introduce the new cap as the runtime source of truth

- Change `_PLAN_AGENT_CODEX_CYCLE_CAP` in
  `python/envctl_engine/planning/plan_agent/constants.py` from `10` to `3`.
- Keep `_parse_codex_cycles` warning semantics unchanged:
  values above `3` should still produce `bounded_codex_cycles`.
- Keep invalid and negative handling unchanged:
  invalid or negative values should resolve to `0` with
  `invalid_codex_cycles`.
- Confirm `ENVCTL_PLAN_AGENT_CODEX_CYCLES=2` remains the global default and does
  not need migration.

### 2) Update workflow expansion expectations

- Keep `_build_plan_agent_workflow` using `_PLAN_AGENT_CODEX_CYCLE_CAP`.
- Update tests so `codex_cycles=999` expands to exactly `3` cycles.
- Verify the number of queued workflow steps still follows the existing formula
  for the reduced cap.
- Add or update a focused test that direct canonical values `0`, `1`, `2`, and
  `3` are accepted without warnings.

### 3) Rewrite the create-plan recommendation rubric

- Update `create_plan.md`, `create_plan_auto_codex.md`, and
  `create_plan_auto_omx.md` to say the allowed recommendation is exactly one
  integer from `0` through `3`.
- Replace the old five-band rubric with:
  - `0`: trivial docs, prompt, static edit, or very small one-file change.
  - `1`: small localized code/test change with low integration risk.
  - `2`: normal multi-file feature/fix, moderate verification, or a task that
    benefits from one continuation/finalization pass.
  - `3`: genuinely complex, high-risk, cross-module, runtime-sensitive, or
    architecture-sensitive work.
- Keep "prefer the smallest number" wording so `3` is exceptional.
- Update auto-Codex and auto-OMX wording so `recommended_codex_cycles=<n>` is
  constrained to the new scale.

### 4) Update docs and installed skill contracts

- Update `docs/user/planning-and-worktrees.md`,
  `docs/user/ai-playbooks.md`, `docs/reference/configuration.md`, and
  `docs/reference/commands.md` to describe the `0` through `3` scale.
- Remove wording that says create-plan uses `0` through `8` while runtime uses a
  separate cap.
- Keep OpenCode notes explicit that OpenCode ignores Codex cycle settings.
- If touched docs still show old launch examples such as `--tmux` where current
  repo behavior prefers cmux, update those examples only when they are in the
  same edited paragraph and are part of the auto-plan contract.

### 5) Update tests that lock the old range

- In `tests/python/runtime/test_prompt_install_support.py`, replace assertions
  for `0` through `8` with `0` through `3`.
- In `tests/python/runtime/test_command_exit_codes.py`, update installed skill
  assertions to expect `0` through `3`.
- In `tests/python/planning/test_plan_agent_launch_support.py`, update:
  - bounded alias parsing from `10` to `3`;
  - large workflow expansion from `10` to `3`;
  - any canonical-value tests that currently treat `4` as valid. Values above
    `3` should now assert `bounded_codex_cycles`.
- Search for remaining literal `0 through 8`, `through \`8\``, and
  `_PLAN_AGENT_CODEX_CYCLE_CAP = 10` references and remove or intentionally
  update them.

## Tests (add these)

### Backend tests

- Extend `tests/python/planning/test_plan_agent_launch_support.py`:
  - `ENVCTL_PLAN_AGENT_CODEX_CYCLES=3` resolves to `3` with no warning.
  - `ENVCTL_PLAN_AGENT_CODEX_CYCLES=4` resolves to `3` with
    `bounded_codex_cycles`.
  - `CYCLES=999` resolves to `3` with `bounded_codex_cycles`.
  - `_build_plan_agent_workflow(..., codex_cycles=999)` has
    `workflow.codex_cycles == 3`.

### Frontend tests

- None. This is CLI/runtime prompt behavior with no frontend surface.

### Integration/E2E tests

- Extend prompt-install coverage in
  `tests/python/runtime/test_prompt_install_support.py` and
  `tests/python/runtime/test_command_exit_codes.py` so installed skills and
  rendered direct prompt bodies contain `0` through `3` and not `0` through `8`.
- Run focused docs/prompt tests rather than full-stack E2E.

## Observability / logging

- Keep existing `codex_cycles_warning="bounded_codex_cycles"` behavior. No new
  telemetry event is required.
- If command output or JSON payloads already expose `codex_cycles`, the bounded
  value should now be `3`.

## Rollout / verification

Recommended Codex cycles: 2.

Rationale: this is a localized behavior change across runtime config, prompts,
docs, and tests; it does not need the future maximum of `3`.

Launch scope flags: `--cmux --no-infra --headless --new-session`.

Focused verification commands:

- `uv run pytest -q tests/python/planning/test_plan_agent_launch_support.py -k 'codex_cycles or build_plan_agent_workflow_bounds_large_cycle_counts'`
- `uv run pytest -q tests/python/runtime/test_prompt_install_support.py -k 'cycle or auto_codex'`
- `uv run pytest -q tests/python/runtime/test_command_exit_codes.py -k create_plan_auto_codex`
- `uv tool run ruff check python tests scripts`

Escalate to broader runtime tests only if changing the cap exposes unrelated
launch parsing failures.

## Definition of done

- No prompt, installed skill, or user/reference doc describes the Codex
  recommendation range as `0` through `8`.
- Runtime parsing and workflow expansion bound any value above `3` down to `3`.
- `3` is documented as the maximum for genuinely complex work.
- Focused tests pass and lock both the prompt text and runtime behavior.

## Risk register

- Lowering the runtime cap from `10` to `3` is behaviorally visible for users who
  intentionally set larger values. That is aligned with the requested simpler
  scale, but release notes or docs should call it out.
- Some historical changelog files mention the old range. Treat release notes and
  archived changelogs as historical unless tests require otherwise; do not rewrite
  old release history just to remove the phrase.

## Open questions

- None.
