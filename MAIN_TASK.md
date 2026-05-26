# Startup-Level Autodetect Coverage for Entire-System No-System Skip

## Context and objective

The prior iteration implemented the core `--entire-system` no-local-app-system behavior for AI plan-agent launches. When a plan launch selects only default backend/frontend services in a repo with no explicit local app configuration and no autodetectable app layout, envctl now skips app startup cleanly, emits `service.attach.skipped` with `reason="no_system_configured"`, and renders a continuation message instead of `missing_service_start_command`.

The remaining work is to close the startup-level coverage gap around autodetection. Autodetection is the boundary that prevents the no-system classifier from skipping real app startup. This must be proven at the same integration layer where the new skip is applied, not only through command-resolution unit tests.

Fully implement this verification end-to-end. If the new test reveals that autodetectable app services are incorrectly skipped or misreported under `--entire-system`, fix the implementation in the smallest appropriate startup/config module and keep the existing no-system behavior intact.

## Remaining requirements (complete and exhaustive)

1. Add startup-level regression coverage for an autodetectable backend or frontend layout under `--plan ... --entire-system --batch`.
   - Build the fixture using existing runtime startup test helpers and fake process runners.
   - Create a repo/worktree layout that `suggest_service_start_command` or the normal service command resolver recognizes as an app service.
   - Assert that the no-system skip path is not taken.
   - Assert that envctl attempts normal service startup for the autodetectable service path.
   - Assert that output/events do not report `reason="no_system_configured"` for the autodetectable layout.

2. Preserve the already-implemented no-system behavior.
   - The existing no-local-system test must continue to pass.
   - The structured skip event must remain `service.attach.skipped` with `reason="no_system_configured"`, `requested_scope="entire-system"`, and selected default services.
   - The output must still include the no-local-app-system continuation text and exclude `missing_service_start_command` for the no-system case.

3. Preserve explicit misconfiguration behavior.
   - Existing explicit backend/frontend enablement or explicit config without a resolvable command must still fail with `missing_service_start_command`.
   - Additional services or service-specific dependency/env sections must not be masked by the no-system classifier.

4. Preserve command-resolution ownership.
   - Do not weaken `resolve_service_start_command` to silently accept missing commands.
   - Keep autodetection logic in the existing command-resolution/autodetect owner modules.
   - Keep the no-system decision near startup/service selection, where the prior iteration placed it.

5. Keep documentation accurate.
   - If implementation behavior changes while closing the test gap, update `docs/reference/commands.md` and `docs/reference/configuration.md` so they continue to describe configured/autodetected app services and the no-system skip boundary accurately.
   - If no behavior changes are required, do not churn docs.

## Gaps from prior iteration (mapped to evidence)

- Implemented: `python/envctl_engine/startup/service_execution_environment.py` contains `no_local_app_system_configured()` and `maybe_skip_no_local_app_system()`, including explicit-key checks, additional-service checks, dependency/env checks, and `suggest_service_start_command()` probing.
- Implemented: `python/envctl_engine/startup/service_execution.py` invokes the no-system skip after service selection and before backend/frontend preparation and command resolution.
- Implemented: `tests/python/runtime/test_engine_runtime_requirements_startup.py` covers the no-system success path and explicit enablement failure path.
- Implemented: `tests/python/startup/test_startup_finalization.py` covers headless plan summary warning rendering.
- Implemented: docs in `docs/reference/commands.md` and `docs/reference/configuration.md` describe configured/autodetected app services and default backend/frontend enablement.
- Remaining gap: the prior task explicitly required startup/runtime coverage proving that an autodetectable backend or frontend layout still starts under `--entire-system`. Existing `tests/python/runtime/test_command_resolution.py` proves command-resolution autodetection, but there is no focused startup-level test proving the new no-system classifier defers to autodetection at the integration point where services are selected and launched.

## Acceptance criteria (requirement-by-requirement)

1. Autodetect startup coverage:
   - A new or expanded runtime startup test creates an autodetectable app layout and dispatches a plan route with `--entire-system --batch`.
   - The test fails against an implementation that skips autodetectable app layouts as `no_system_configured`.
   - The passing test observes normal startup behavior, such as one or more fake `start_background` calls, and no `service.attach.skipped` event with `reason="no_system_configured"`.

2. No-system behavior:
   - The existing no-system test continues to assert exit code `0`, no background starts, no `missing_service_start_command`, and the structured no-system skip event.

3. Explicit misconfiguration:
   - The existing explicit enablement test continues to assert exit code `1`, `missing_service_start_command`, and no no-system continuation text.

4. Ownership and maintainability:
   - No low-level resolver behavior is relaxed.
   - Any implementation fix remains narrowly scoped to startup/service-selection support.
   - Structural guard tests remain green if touched modules approach ownership or line-count limits.

5. Documentation:
   - Docs remain unchanged if the behavior already matches the intended contract.
   - If behavior changes, docs are updated in the same commit and validated by the relevant doc/reference tests if any exist.

## Required implementation scope (frontend/backend/data/integration)

- Frontend: none.
- Backend/runtime: only if the new startup-level autodetect test exposes a bug in the no-system classifier or service startup selection.
- Data/migrations: none.
- Integration: add or expand runtime startup tests under `tests/python/runtime/test_engine_runtime_requirements_startup.py` or the nearest existing startup test file that owns plan-route service startup behavior.
- Docs: only if behavior changes are required.

## Required tests and quality gates

Run focused validation first:

```bash
uv run --extra dev python -m pytest tests/python/runtime/test_engine_runtime_requirements_startup.py
uv run --extra dev python -m pytest tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow_handoff.py
```

Run broader validation after focused tests pass:

```bash
uv run --extra dev python -m pytest tests/python/runtime tests/python/startup
```

If implementation files change beyond tests, also run the relevant structure and lint checks:

```bash
uv run --extra dev ruff check python/envctl_engine/startup/service_execution.py python/envctl_engine/startup/service_execution_environment.py tests/python/runtime/test_engine_runtime_requirements_startup.py
uv run --extra dev python -m pytest tests/python/shared/test_structure_layout.py
```

Before shipping, run the repo-focused validation wrapper with the current project target:

```bash
envctl test-focused --project broken_envctl_entire_system_no_system_noop-8
```

Then ship with an inline commit message:

```bash
envctl ship --json --project broken_envctl_entire_system_no_system_noop-8 -m "Add startup autodetect coverage for no-system entire-system launches"
```

## Edge cases and failure handling

- Autodetectable backend only with default frontend still selected must not be classified as no-system. If frontend command resolution remains missing, envctl should keep the actionable `missing_service_start_command` behavior for the unresolved selected peer.
- Autodetectable frontend only with default backend still selected must follow the same rule.
- A fully autodetectable backend/frontend fixture should proceed to normal fake startup without the no-system skip.
- Explicit enablement, explicit command, explicit app directory, additional services, and service dependency/env sections must continue to prevent the no-system skip.
- `--no-infra` semantics must remain unchanged.
- Remote/network discovery remains out of scope.

## Definition of done

- `OLD_TASK_1.md` preserves the prior task.
- `MAIN_TASK.md` contains only this remaining coverage/validation scope.
- Startup-level autodetect coverage is added and passes.
- Any implementation fix required by that coverage is complete and wired through existing startup paths.
- No-system continuation behavior and explicit misconfiguration behavior remain green.
- Focused and broader relevant tests pass.
- Changes are committed and shipped through `envctl ship --json --project broken_envctl_entire_system_no_system_noop-8 -m "Add startup autodetect coverage for no-system entire-system launches"`.
- GitHub checks complete successfully, and any actionable review comments are addressed.
