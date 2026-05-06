# envctl 1.8.1

envctl 1.8.1 makes generic sidecar application services first-class, fixes the managed Supabase Auth contract for browser login flows, and improves plan-agent/Codex launch reliability for tree workflows.

## Highlights

- Generic additional app services can now participate in startup, preflight, dashboard health, lifecycle actions, logs, URL projection, and service-specific tests alongside backend and frontend services.
- Managed Supabase now exposes a real public Auth/Kong API endpoint separately from the Postgres DB port, so `ENVCTL_SOURCE_SUPABASE_URL` points at the browser-reachable Supabase API URL instead of a database listener.
- Tree/worktree invocations now resolve repository roots, `.envctl` config, additional-service commands, and resume behavior more reliably from the selected worktree.
- Plan creation prompts now recommend Codex cycle counts from task complexity instead of using a fixed default everywhere.
- Codex/OMX plan-agent startup is more configurable and keeps managed tmux bootstrap sessions alive in headless launches.

## What's Changed

### Generic additional app services

- Added support for `ENVCTL_SERVICE_<SLUG>_*` service definitions with service ports, public URLs, health URLs, commands, working directories, dependency metadata, criticality, and optional path-based enablement.
- Included additional services in `show-config`, `list-trees`, `explain-startup`, preflight/startup evidence, runtime maps, health JSON, state serialization, and dashboard rendering.
- Added layered startup for app-service dependencies with deterministic `START_ORDER` tie-breaking, plus validation for invalid `DEPENDS_ON` references and dependency cycles.
- Added service-targeted lifecycle support for stop, restart, logs, and actions by slug, `service:<slug>`, display name, or full service name while preserving backend/frontend targeting behavior.
- Added `envctl test --service <slug>` routing for configured service test commands and a clear failure when a selected service has no `TEST_CMD`.
- Added non-critical service degradation support: `CRITICAL=false` services can be recorded as degraded with failure details instead of failing the whole run when appropriate.
- Extended the Textual config wizard and managed config persistence for additional-service definitions.

### Supabase dependency contract

- Split managed Supabase into separate database and public API/Auth resources.
- Changed `ENVCTL_SOURCE_SUPABASE_URL` and projected `SUPABASE_URL` values to use the public Supabase Auth/Kong URL, not the Postgres DB port.
- Published the managed Supabase Kong proxy host port and passed the public URL into the managed compose environment.
- Added Auth/Kong health probing so envctl can distinguish "database healthy" from "Supabase Auth API unreachable" and report the failing URL directly.
- Added auto-reinitialization and stale-network recovery paths for existing managed Supabase stacks whose runtime contract predates the public API endpoint.

### Tree startup, resume, and dashboard behavior

- Fixed worktree-oriented invocations so `--repo`, `--tree`, `--main`, config discovery, test/commit/PR actions, and command execution use the intended repository root.
- Resumes now replace only stale services that need replacement when possible instead of treating every service as unrecoverable.
- Additional service commands resolve from the service working directory, which keeps sidecar scripts and relative paths aligned with the configured service.
- Dashboard output avoids duplicate PID/listener PID labels when both values are the same.
- Startup failure reporting for parallel service launches is more stable and includes better per-service evidence.

### Plan-agent, Codex, and OMX launches

- Create-plan prompt surfaces now use a shared `0` through `8` Codex cycle recommendation rubric and pass `ENVCTL_PLAN_AGENT_CODEX_CYCLES=<recommended_codex_cycles>` for auto-Codex planning.
- Auto-OMX Ralph prompts report the recommended Codex-equivalent cycle count without wiring an unsupported Codex cycle override into Ralph commands.
- Codex YOLO/bypass launch behavior is configurable so repos can avoid passing duplicate unsafe-mode flags when a local wrapper already injects them.
- Headless OMX managed tmux launches keep the bootstrap path alive long enough to reconcile the session and force the detached launch policy expected by envctl.

## Upgrade Notes

- Existing managed Supabase stacks created before 1.8.1 may need reinitialization because the release adds a public Auth/Kong endpoint in addition to the DB listener. envctl can perform the supported auto-reinit path with `ENVCTL_SUPABASE_AUTO_REINIT=true`; otherwise stop and recreate the managed Supabase compose stack so Kong is published on the configured public port.
- `ENVCTL_SOURCE_SUPABASE_URL` is now the Supabase API/Auth URL. Use database-specific projected values such as `DATABASE_URL` or `SQLALCHEMY_DATABASE_URL` for direct database connections.
- Additional services can be scoped to worktrees that actually contain the service by using path-based enablement such as `ENVCTL_SERVICE_<SLUG>_ENABLE_IF_PATH=relative/path/to/file`.
- Set the Codex YOLO launch configuration to false in repos where Codex is wrapped with unsafe-mode flags by default to avoid duplicate CLI arguments.

## Validation

- PR #183: `python -m pytest -q tests/python` -> `2011 passed, 12 skipped, 5 warnings, 246 subtests passed`.
- PR #183: `uvx ruff check python tests` -> passed.
- PR #183: `python -m compileall -q python/envctl_engine` -> passed.
- PR #183: `git diff --check` -> passed.
- PR #182: `envctl --trees test --project features_envctl_dynamic_create_plan_cycle_recommendations-1` -> `1980 passed, 0 failed, 12 skipped`.
- PR #182: targeted prompt/install tests -> passed.
- PR #182: `git diff --check` -> passed.

## Pull Requests

- Recommend dynamic create-plan Codex cycles by @kfiramar in https://github.com/OrgPele/envctl/pull/182
- Complete generic additional app service surfaces by @kfiramar in https://github.com/OrgPele/envctl/pull/183

**Full Changelog**: https://github.com/OrgPele/envctl/compare/1.8.0...1.8.1
