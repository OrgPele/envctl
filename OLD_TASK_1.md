# Envctl Entire-System No-System Noop

## Goal

When a user runs an AI plan-agent launch with `--entire-system` in a repository that has no local app system configured, envctl should say that no local system is configured and continue with the AI session only. It should not render this as "local app startup failed" when the only selected app services are backend/frontend defaults with no explicit command and no autodetectable repo layout.

## Problem

`envctl --plan ... --cmux --preset implement_task --entire-system --headless --new-session` currently requests dependencies plus configured app services. In this repo, there is no repo-local `.envctl` and no backend/frontend start command. The default trees startup profile still enables backend and frontend, so the startup path selects both services, command resolution raises `missing_service_start_command`, and the plan-agent degraded handoff reports:

- "Implementation session is running, but local app startup failed."
- `missing_service_start_command`
- guidance to configure backend/frontend commands or disable tree startup

That message is accurate for a configured app with a broken command, but misleading for repos where envctl is configured with no local system at all. In that case, the implementation agent should still run and the user-facing text should clearly explain that `--entire-system` found no configured system to start.

## Non-Goals

- Do not change the low-level command resolver so it silently accepts missing commands for configured services.
- Do not mask broken explicit configuration, such as an explicit `ENVCTL_BACKEND_START_CMD`, explicit service directory, explicit additional service, or explicit service enablement that cannot be started.
- Do not reinterpret `--no-infra`; it should remain the explicit "skip infra" scope.
- Do not add remote/network service discovery.

## Current Code Map

- `python/envctl_engine/config/__init__.py`
  - `EngineConfig.explicit_keys` records keys supplied by `.envctl` or environment.
  - `EngineConfig.all_app_service_names_for_mode()` currently includes backend/frontend when the mode startup profile enables them, even when those values are defaults.
- `python/envctl_engine/startup/service_execution.py`
  - `start_project_services()` builds `configured_service_types`, then selected service types, then prepares backend/frontend and resolves commands.
  - It already emits `service.attach.skipped` with `reason="all_services_disabled"` when no services are selected.
- `python/envctl_engine/runtime/command_resolution.py`
  - `resolve_service_start_command()` returns `configured` or `autodetected`; otherwise raises `CommandResolutionError("missing_service_start_command", ...)`.
- `python/envctl_engine/startup/selected_context_startup.py`
  - Missing service commands can degrade into plan-agent handoff when a plan agent is running.
- `python/envctl_engine/startup/finalization.py`
  - The degraded handoff text currently always frames local startup problems as failures and gives configure/disable guidance.
- Tests already cover the current failure shape in `tests/python/runtime/test_engine_runtime_requirements_startup.py` and handoff text in `tests/python/startup/test_startup_finalization.py`.

## Implementation Plan

1. Add a narrow "no local app system configured" classifier.
   - Prefer a small helper near startup/service selection or config support, not inside low-level command resolution.
   - It should only return true when all selected app services are default backend/frontend selections and none has an explicit local-system signal.
   - Treat these as explicit local-system signals:
     - `ENVCTL_BACKEND_START_CMD` or `ENVCTL_FRONTEND_START_CMD`
     - mode-specific/backend/frontend enable keys such as `TREES_BACKEND_ENABLE`, `MAIN_FRONTEND_ENABLE`, or startup keys that intentionally request local app startup
     - explicit backend/frontend directory keys
     - configured additional services
     - service-specific dependency/env sections that imply a real app surface
   - Use command-resolution probing or existing suggestion/autodetect helpers to distinguish "default service with an autodetectable app" from "default service with no app".

2. Skip app service startup cleanly when the classifier matches.
   - In `start_project_services()`, after service selection but before backend/frontend preparation and command resolution, detect the no-system case.
   - Emit a structured event such as `service.attach.skipped` with `reason="no_system_configured"`, `requested_scope="entire-system"` when available, and the selected default services.
   - Return an empty service map without calling `start_background`.
   - Preserve hard failures when the selection contains additional services or explicit backend/frontend configuration.

3. Render plan-agent output as a clean no-system continuation.
   - Ensure plan-agent handoff/finalization can distinguish a no-system skip from a local startup failure.
   - User-facing output should say:
     - no local app system is configured for this repo/worktree
     - envctl is continuing with the implementation session only
     - `--entire-system` was honored, but there was nothing configured to start
   - Avoid showing `missing_service_start_command` or "local app startup failed" for the no-system case.

4. Keep explicit misconfiguration actionable.
   - If either backend or frontend has an explicit command, explicit directory, explicit enable flag, or an autodetectable service and a selected peer fails, keep the existing `missing_service_start_command` behavior.
   - If an additional service is configured and cannot be started, keep the existing failure/degraded-handoff behavior.
   - If the user explicitly disables app services, keep `reason="all_services_disabled"`.

5. Update documentation.
   - In `docs/reference/commands.md`, clarify that `--entire-system` starts configured/autodetected local services, but in a repo with no configured local app system envctl continues without app services and reports that cleanly.
   - In `docs/reference/configuration.md`, note that backend/frontend default enablement is not the same as an explicit local-system configuration.

## Test Plan

- Add or update runtime startup tests:
  - no `.envctl`, no backend/frontend autodetect, `--plan ... --batch` or plan-agent-equivalent startup should exit successfully for the AI session path, print "no local app system is configured", and make no background start calls.
  - explicit backend/frontend command missing or invalid should still fail with `missing_service_start_command`.
  - explicit backend/frontend enablement should still be treated as intentional local-system configuration and keep actionable failure text if no command resolves.
  - autodetectable backend or frontend layout should still be started under `--entire-system`.
- Update plan-agent handoff/finalization tests:
  - no-system startup must not include "local app startup failed".
  - degraded handoff caused by a real service failure must keep current failure wording and remediation guidance.
- Keep command-resolution tests unchanged except where assertions need to prove the resolver still raises on direct missing-command resolution.
- Run focused tests first:
  - `uv run --extra dev python -m pytest tests/python/runtime/test_engine_runtime_requirements_startup.py`
  - `uv run --extra dev python -m pytest tests/python/startup/test_startup_finalization.py tests/python/startup/test_startup_orchestrator_flow_handoff.py`
- Then run a broader startup/runtime slice if focused tests pass:
  - `uv run --extra dev python -m pytest tests/python/runtime tests/python/startup`

## Verification

- Re-run the original launch shape from the main checkout:
  - `envctl --plan broken/envctl-entire-system-no-system-noop --cmux --preset implement_task --entire-system --headless --new-session`
- Expected result:
  - Codex/plan-agent session launches.
  - Output says no local app system is configured and envctl is running without local services.
  - No `missing_service_start_command` appears for the no-system case.
  - No backend/frontend background process is started.

## Risks

- The hardest boundary is distinguishing default backend/frontend enablement from explicit user intent. Use `EngineConfig.explicit_keys` and keep the no-system classifier conservative.
- Autodetection must remain authoritative. If envctl can autodetect a supported FastAPI/Uvicorn or package.json dev service, `--entire-system` should still start it.
- Plan-agent degraded handoff already returns success in some cases; the implementation should fix the semantics and text, not merely hide the error.

## Implementation Launch

Recommended Codex cycles: 2.

Implementation surface: `--entire-system`, because the bug is specifically that an entire-system plan-agent launch against a repo with no configured app system reports a local startup failure instead of a no-system continuation.
