# Startup Latency Investigation (`main` + `--plan`)

## Scope and Method
- Repository: `/Users/kfiramar/projects/envctl`
- Workload repo: `/Users/kfiramar/projects/supportopia`
- Runtime scope: `repo-b15e3f0c8257`
- Execution harness:
  - `ENVCTL_DEBUG_UI_MODE=deep ENVCTL_DEBUG_RESTORE_TIMING=1 /Users/kfiramar/projects/envctl/bin/envctl --repo /Users/kfiramar/projects/supportopia ...`
- Modes tested:
  - `main_warm`
  - `main_cold` (`--no-resume`)
  - `plan_warm` (single selector)
  - `plan_cold` (`--no-resume`, single selector)

## Repro Matrix Results

| Case | Real Time | Mode Path | Key Events |
|---|---:|---|---|
| `main_warm` | `6.01s` | auto-resume | `state.auto_resume`, `state.resume`, `resume.restore.timing` |
| `main_cold` | `57.97s` | full startup | `startup.execution`, full requirements + services |
| `plan_warm` | `176.17s` | resume skipped -> full startup | `state.auto_resume.skipped(reason=project_selection_mismatch)` |
| `plan_cold` | `82.63s` | full startup | `startup.execution`, full requirements + services |

## Component Breakdown

### `main_warm` (`6.01s`)
- Resume restore total: `~3372ms`
- Service timing total: `~3341ms`
  - `start_project_with_attach`: `~2103ms`
  - `prepare_backend_runtime`: `~1236ms`

### `main_cold` (`57.97s`)
- Requirements total: `~48744ms`
  - `postgres`: `~46527ms`
  - `redis`: `~2216ms`
- Service total: `~7645ms`
  - `prepare_backend_runtime`: `~4480ms`
  - `start_project_with_attach`: `~3160ms`

### `plan_warm` (`176.17s`)
- Auto-resume skipped:
  - reason: `project_selection_mismatch`
  - state projects: 3-tree run
  - selected projects: 1-tree run
- Requirements total: `~169032ms`
  - `redis`: `~93821ms`
  - `postgres`: `~74075ms`
  - `n8n`: `~1134ms`
- Service total: `~5452ms`

### `plan_cold` (`82.63s`)
- Requirements total: `~75688ms`
  - `postgres`: `~42994ms`
  - `redis`: `~31503ms`
  - `n8n`: `~1190ms`
- Service total: `~5422ms`

## Stage Waterfall (Current Evidence)
- Existing coarse timing already isolates dominant latency to `requirements.*`.
- New instrumentation added in code (events + diagnostics):
  - `requirements.adapter.stage`
  - `requirements.adapter.command_timing`
  - `requirements.adapter.probe_attempt`
  - `requirements.adapter.listener_wait`
  - `requirements.adapter.retry_path`
- Adapter summary now carries:
  - `stage_durations_ms`
  - `docker_command_count`
  - `probe_attempt_count`
  - `listener_wait_ms`
  - `container_reused`
  - `container_recreated`

## Confirmed Root Causes (Ranked)
1. Requirement lifecycle dominates startup wall time.
   - Cold and slow warm paths are mostly `postgres`/`redis` requirement phases.
2. `--plan` warm path can become cold due strict project-set auto-resume matching.
   - Single-project selection skips resume if saved state contains different project set.
3. App boot is secondary in measured sessions.
   - Service attach typically `~3-8s`, far lower than requirement delays in slow cases.

## Additional Observations
- Direct control checks on running containers:
  - `docker exec ... pg_isready` and `docker exec ... redis-cli ping` were `~0.04-0.07s` each in control probes.
- This suggests slow sessions are not explained by single exec latency alone; likely cumulative lifecycle path effects (wait/retry/recreate/port churn context).

## Optimization Backlog (Decision-Ready)

### P0 (Warm path <10s)
- Relax/parameterize plan auto-resume matching for subset selections.
  - Candidate: allow subset resume when selected projects are a subset of saved state projects.
- Prioritize requirement reuse/skip checks before expensive startup in warm plan flows.
- Use new diagnostics fields to detect and block regressions.

### P1 (Cold startup reduction)
- Tune requirement lifecycle waits/retries with evidence from stage hotspots.
- Minimize unnecessary recreate/restart paths when containers are already healthy.
- Reduce sequential requirement startup cost where safe.

### P2 (Observability hardening)
- Keep startup latency sections in `--debug-report` and analyzer:
  - `startup_breakdown`
  - `slowest_components`
  - `resume_skip_reasons`
  - `requirements_stage_hotspots`
- Add CI-level contract tests for startup diagnostics payload.

## Acceptance Criteria for Follow-up Optimization
- Warm startup: `<10s` median in `main` and single-project `--plan` runs.
- Unknown/unattributed startup time in diagnostics: `<10%`.
- `--debug-report` must expose startup bottlenecks without manual JSONL parsing.
