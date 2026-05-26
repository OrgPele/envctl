# Verify No-System Entire-System Plan-Agent Launch

## Context and objective

The previous implementation added no-local-app-system handling for `envctl --plan ... --entire-system` launches. Code, tests, docs, commits, and PR checks show the implementation is in place and green. The remaining gap is the original task's real launch verification step: prove the actual plan-agent launch shape behaves correctly in a repo/worktree with no configured local app system, and fix any discrepancy found by that verification.

Complete this task end-to-end. If verification exposes a behavior gap, implement the narrowest correct fix, add or update tests, run focused and relevant broader validation, commit, push, and ship the PR.

## Remaining requirements (complete and exhaustive)

1. Re-run the original launch shape against the current worktree/repo context:

   ```bash
   envctl --plan broken/envctl-entire-system-no-system-noop --cmux --preset implement_task --entire-system --headless --new-session
   ```

2. Confirm the launched plan-agent path reports a no-system continuation:
   - Output says no local app system is configured for the selected repo/worktree.
   - Output says envctl is continuing with the implementation session only.
   - Output says `--entire-system` was honored but nothing was configured to start.

3. Confirm the no-system case is not rendered as local startup failure:
   - Output does not include `missing_service_start_command`.
   - Output does not include `Implementation session is running, but local app startup failed.`
   - Runtime metadata does not mark `local_startup_failed` for the no-system case.

4. Confirm no default backend/frontend process is started for the no-system case:
   - No backend process is launched solely because default trees startup selects backend.
   - No frontend process is launched solely because default trees startup selects frontend.
   - Structured startup events include `service.attach.skipped` with `reason="no_system_configured"`, `requested_scope="entire-system"`, and selected default services `backend` and `frontend`.

5. If the real launch violates any requirement above, fix the implementation without weakening already-covered behavior:
   - Keep direct command resolution strict for missing configured commands.
   - Keep explicit backend/frontend enablement, explicit start commands, explicit service directories, additional services, and service env/dependency sections actionable as real local-system intent.
   - Keep autodetectable backend/frontend layouts startable under `--entire-system`.
   - Keep `--no-infra` semantics unchanged.

## Gaps from prior iteration (mapped to evidence)

- Implemented: `python/envctl_engine/startup/no_system_config.py` classifies no-local-app-system plan launches only for `plan` + `--entire-system`, default backend/frontend selections, no additional services, no explicit local-system signals, and no autodetectable app layout.
- Implemented: `python/envctl_engine/startup/service_execution.py` calls the classifier after service selection and before service preparation/command resolution, emits `service.attach.skipped`, and returns no service records.
- Implemented: `python/envctl_engine/startup/selected_context_startup.py` copies no-system markers back to the effective route used by finalization output.
- Implemented: `python/envctl_engine/startup/finalization_plan_output.py` includes no-system continuation lines in headless plan output.
- Implemented: tests cover the no-system skip, explicit enablement preserving `missing_service_start_command`, clean handoff text, and degraded real-failure wording.
- Implemented: docs in `docs/reference/commands.md` and `docs/reference/configuration.md` explain `--entire-system` no-system behavior and default backend/frontend enablement.
- Remaining: git/test evidence did not show the original real launch command being executed after implementation. That verification must be completed now, and any issue it reveals must be fixed.

## Acceptance criteria (requirement-by-requirement)

1. Original launch command runs to the point where plan-agent handoff output is available and exits successfully or returns the established success code for a launched headless plan-agent session.
2. Captured output includes all required no-system continuation wording.
3. Captured output excludes `missing_service_start_command` and `Implementation session is running, but local app startup failed.`
4. Runtime/event evidence confirms no backend/frontend background service was launched for the no-system case.
5. If a code fix is needed, focused tests prove the corrected behavior and existing regression coverage remains green.
6. If no code fix is needed, record that implementation is complete and only verification evidence was added through the audit/handoff.

## Required implementation scope (frontend/backend/data/integration)

- Frontend: none expected.
- Backend/runtime: only change `python/envctl_engine/startup/**` or directly related runtime startup code if the real launch disproves current behavior.
- Data/migrations: none.
- Integration: plan-agent launch path, service attach selection, finalization/handoff output, runtime event/artifact inspection.
- Documentation: update docs only if the real launch reveals the existing documentation is inaccurate.

## Required tests and quality gates

If no implementation change is required, run:

```bash
envctl test-focused --project broken_envctl_entire_system_no_system_noop-7
```

If implementation changes are required, also run the focused suites that cover this behavior:

```bash
uv run --extra dev python -m pytest tests/python/runtime/test_engine_runtime_requirements_startup.py
uv run --extra dev python -m pytest tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow_handoff.py
uv run --extra dev python -m pytest tests/python/runtime tests/python/startup
```

Before final handoff, run `envctl ship --json -m "<complete commit message>"` or, if a project selector is needed, `envctl ship --json --project broken_envctl_entire_system_no_system_noop-7 -m "<complete commit message>"`. Wait for GitHub checks and confirm required checks pass.

## Edge cases and failure handling

- If the launch command creates or reuses an existing AI session, report the attach/new-session guidance and still verify no-system output.
- If the plan-agent transport itself fails for an environmental reason unrelated to no-system service startup, capture the failure, distinguish it from the startup behavior, and run the closest available startup/handoff verification that proves the no-system path.
- If backend/frontend processes are started, determine whether they were explicitly configured/autodetected or incorrectly started from defaults. Only the incorrect default-start case is a failure for this task.
- If explicit local-system configuration is present in the environment, clear or isolate it for the no-system verification instead of weakening the classifier.

## Definition of done

- `OLD_TASK_1.md` preserves the previous task.
- This `MAIN_TASK.md` reflects only the remaining verification/fix-if-needed scope.
- The original launch shape has been run or an environment-blocked equivalent has been documented with substitute evidence.
- Any discovered behavior gap is fixed with tests and docs as needed.
- Focused validation passes.
- Changes are committed, pushed, PR checks are complete and passing, and no actionable review comments remain.
