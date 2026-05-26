# No Remaining No-System Entire-System Scope

## Context and objective

The prior task, now archived in `OLD_TASK_1.md`, required envctl plan-agent launches with `--entire-system` to continue cleanly when the selected repo/worktree has no configured local app system. The implementation is already present on this branch: default backend/frontend startup is skipped only for the narrow no-system case, the AI session continues without app services, explicit local-system configuration remains actionable, and docs/tests cover the behavior.

This rollover records that there is no remaining implementation scope for the archived no-system task. Do not add unrelated product behavior under this task. If a future iteration needs to address separate validation or shipping-tool reliability, create a separate task with its own source of truth.

## Remaining requirements (complete and exhaustive)

No implementation requirements remain for the no-system `--entire-system` behavior described in `OLD_TASK_1.md`.

The completed behavior is:

- `--plan ... --entire-system` exits successfully for a repo/worktree with no `.envctl`, no explicit backend/frontend signals, no additional app services, and no autodetectable app service commands.
- The output reports that no local app system is configured, states that envctl is continuing with the implementation session only, and states that `--entire-system` was honored with nothing configured to start.
- No backend/frontend `start_background` call is made in the no-system case.
- The no-system case does not render `missing_service_start_command` or `local app startup failed`.
- Explicit backend/frontend commands, directories, enable flags, service env sections, additional services, and autodetectable layouts still keep normal service startup or failure semantics.
- Explicitly disabled services still use the existing all-services-disabled path.

## Gaps from prior iteration (mapped to evidence)

No product gaps were found in the archived task scope.

Evidence:

- `python/envctl_engine/startup/service_execution_no_system.py` defines the no-system classifier, explicit local-system signal checks, command-resolution probing, and `service.attach.skipped` event with `reason="no_system_configured"`.
- `python/envctl_engine/startup/service_execution.py` calls the no-system skip after service selection and before backend/frontend preparation or background process launch.
- `python/envctl_engine/startup/finalization_plan_output.py` renders recorded startup warnings in headless plan-agent output without using degraded local-startup failure text.
- `tests/python/runtime/test_engine_runtime_requirements_startup.py` covers no-system success, no background starts, default-scope failure preservation, and explicit backend enablement failure preservation.
- `tests/python/startup/test_startup_finalization.py` covers no-system warning rendering without `local app startup failed` or `missing_service_start_command`, while preserving real degraded-handoff failure text.
- `docs/reference/commands.md` and `docs/reference/configuration.md` document the no-system continuation and clarify that default backend/frontend enablement is not an explicit local app-system configuration.

Residual validation note: a prior environment run reported `envctl test-focused` and `envctl ship --json` being killed with exit 137 even though the underlying pytest suite and GitHub checks passed. That is outside the archived no-system product task and should be tracked as separate tooling work if it recurs.

## Acceptance criteria (requirement-by-requirement)

- No new code is required for the archived no-system task.
- `OLD_TASK_1.md` remains the preserved source task for historical review.
- `MAIN_TASK.md` remains focused on the completed state and does not carry forward unrelated requirements.
- Any future code changes for the no-system behavior must continue satisfying the completed behavior listed above.
- Any future work on `envctl test-focused`, `envctl ship --json`, or CI/shipping reliability must be specified in a separate task before implementation.

## Required implementation scope (frontend/backend/data/integration)

No frontend, backend, data, configuration, migration, or integration implementation remains for this task.

## Required tests and quality gates

No new tests are required for this rollover because it does not change executable code.

The completed implementation was validated with focused startup/finalization tests, a full Python test suite, the original no-system plan-agent smoke shape, and GitHub PR checks. If this branch changes again, rerun the relevant focused suite first:

```bash
uv run --extra dev python -m pytest tests/python/runtime/test_engine_runtime_requirements_startup.py
uv run --extra dev python -m pytest tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow_handoff.py
```

For any executable change, follow with the broader relevant suite before shipping:

```bash
uv run --extra dev pytest -q tests/python -x
```

## Edge cases and failure handling

The completed implementation already preserves the required edge cases:

- Default backend/frontend services with no explicit signal and no autodetectable command are skipped cleanly only for plan-agent `--entire-system`.
- Direct/default non-entire-system startup still reports missing service commands.
- Explicit backend/frontend enablement without a resolvable command remains an actionable startup failure.
- Real degraded handoff failures still render `Implementation session is running, but local app startup failed.` with remediation guidance.
- Autodetectable service layouts remain authoritative and should start instead of being treated as no-system.
- Additional configured services are not folded into the no-system skip.

## Definition of done

This rollover is done when:

- `MAIN_TASK.md` has been archived as `OLD_TASK_1.md`.
- This replacement `MAIN_TASK.md` states that no implementation scope remains for the archived no-system task.
- The audit evidence confirms completed requirements and records the residual exit-137 wrapper note as separate from the product task.
- The working tree contains no unintended edits outside the task archive, replacement task file, and commit-message pointer.
