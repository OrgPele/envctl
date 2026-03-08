# Envctl Port Allocation Strategy ADR

## 1. Problem Statement
Envctl currently mixes four separate concerns into one loose "port bump" model:

- preferred port derivation
- reservation and ownership
- retry and rebound after conflicts
- actual listener truth and URL projection

In the Python runtime, preferred ports are still primarily derived from discovery order plus coarse offsets:

- backend and frontend use `base + index * spacing`
- postgres, redis, and n8n use `base + index`

This works, but it makes `PORT_SPACING` carry too much architectural weight. It functions as identity, collision avoidance, and grouping policy at the same time. That makes the model harder to extend, less stable when discovery order changes, and awkward across service classes.

The ADR question is:

Should envctl keep the current `base + spacing/offset + linear rebound` model as the primary strategy, or move to a better preferred-port allocator while keeping reservation, rebound, and actual-port truth contracts?

## 2. Current System Overview

### User-visible configuration surface
- `BACKEND_PORT_BASE`, `FRONTEND_PORT_BASE`, `DB_PORT`, `REDIS_PORT`, `N8N_PORT_BASE`, and `PORT_SPACING` are loaded in [python/envctl_engine/config/__init__.py](../../../python/envctl_engine/config/__init__.py).
- Managed config read/write and the interactive config wizard surface the same values via [python/envctl_engine/config/persistence.py](../../../python/envctl_engine/config/persistence.py) and [python/envctl_engine/ui/textual/screens/config_wizard.py](../../../python/envctl_engine/ui/textual/screens/config_wizard.py).
- Dependency resource port keys are defined in [python/envctl_engine/requirements/core/models.py](../../../python/envctl_engine/requirements/core/models.py) and [python/envctl_engine/requirements/core/registry.py](../../../python/envctl_engine/requirements/core/registry.py).

### Internal typed model
- `PortDefaults` carries configured base values and spacing in [python/envctl_engine/config/__init__.py](../../../python/envctl_engine/config/__init__.py).
- `PortPlan(requested, assigned, final, source, retries)` is the canonical preferred/reserved/final model in [python/envctl_engine/state/models.py](../../../python/envctl_engine/state/models.py).
- `ServiceRecord(requested_port, actual_port)` is the runtime truth model for application services in [python/envctl_engine/state/models.py](../../../python/envctl_engine/state/models.py).

### Persistence and runtime artifacts
- `ports_manifest.json` persists requested/assigned/final port plans per project in [python/envctl_engine/state/repository.py](../../../python/envctl_engine/state/repository.py).
- `runtime_map.json` projects runtime URLs from actual listener ports.
- `run_state.json` persists `requested_port` and `actual_port` for services.
- Legacy shell compatibility still reads and writes `.envctl-workspaces/*.ports` through [lib/engine/lib/worktrees/worktrees.sh](../../../lib/engine/lib/worktrees/worktrees.sh).

## 3. Canonical Port Lifecycle

### Python preferred-port lifecycle
1. Config loads base values and spacing.
2. `PortPlanner` creates a preferred `PortPlan` for each project and service in [python/envctl_engine/shared/ports.py](../../../python/envctl_engine/shared/ports.py).
3. Startup reserves the preferred port or rebounds upward via `reserve_next` in [python/envctl_engine/runtime/engine_runtime_startup_support.py](../../../python/envctl_engine/runtime/engine_runtime_startup_support.py).
4. Requirement and service startup may retry on bind conflicts in [python/envctl_engine/requirements/orchestrator.py](../../../python/envctl_engine/requirements/orchestrator.py) and [python/envctl_engine/runtime/service_manager.py](../../../python/envctl_engine/runtime/service_manager.py).
5. Actual listener ports are discovered after launch in [python/envctl_engine/runtime/engine_runtime_service_truth.py](../../../python/envctl_engine/runtime/engine_runtime_service_truth.py).
6. `run_state.json`, `runtime_map.json`, and `ports_manifest.json` are written by [python/envctl_engine/state/repository.py](../../../python/envctl_engine/state/repository.py).
7. Frontend and runtime projections use actual backend or service listener ports from [python/envctl_engine/shared/services.py](../../../python/envctl_engine/shared/services.py).

### Legacy shell lifecycle
- Shell still derives ports from base values, spacing, per-worktree config, and existing container mappings in:
  - [lib/engine/lib/shared/ports.sh](../../../lib/engine/lib/shared/ports.sh)
  - [lib/engine/lib/requirements/requirements_core.sh](../../../lib/engine/lib/requirements/requirements_core.sh)
  - [lib/engine/lib/requirements/requirements_supabase.sh](../../../lib/engine/lib/requirements/requirements_supabase.sh)
  - [lib/engine/lib/planning/run_all_trees_helpers.sh](../../../lib/engine/lib/planning/run_all_trees_helpers.sh)
  - [lib/engine/lib/state/state.sh](../../../lib/engine/lib/state/state.sh)

## 4. Current Pain Points
- Discovery-order dependence: the old Python preferred-port model depends on project index, not stable project identity.
- `PORT_SPACING` is overloaded: it is both a human-facing grouping aid and a hidden allocator primitive.
- Cross-service asymmetry: app services use spacing, infra services use plain index increments.
- Shell cleanup logic still assumes spaced ranges, which is broader and more aggressive than the Python runtime’s lock-owned cleanup.
- Existing container adoption and runtime truth are already richer than the preferred-port model, which means the allocator is now the least expressive part of the lifecycle.

## 5. Non-Goals
- Replace reservation, lock reclaim, or actual listener detection.
- Remove `requested_port` vs `actual_port`.
- Remove base port configuration.
- Remove shell compatibility in one step.
- Switch to fully dynamic, opaque free-port allocation.

## 6. Decision Criteria
Each candidate is scored from `1` to `5` on:

- determinism across reruns
- determinism across resume
- uniqueness under parallel planning
- collision resistance
- predictability for humans
- compatibility with existing overrides and artifacts
- restricted-environment behavior
- ease of debugging
- cleanup safety
- migration cost
- extensibility for new dependency classes

## 7. Alternatives Considered

### A. Keep current spacing model
Definition:
- backend/frontend keep `base + index * spacing`
- infra keeps `base + index`
- rebound remains linear upward

Assessment:
- strong human predictability
- weak stability when discovery order changes
- awkward asymmetry across service classes
- makes `PORT_SPACING` too central

Score: `36/55`

### B. Pure dynamic free-port allocation
Definition:
- always take any free port
- persist only actual ports

Assessment:
- simple mechanically
- poor determinism
- poor human predictability
- bad fit for envctl’s planning and resume contracts

Score: `24/55`

### C. Hash-derived preferred ports
Definition:
- preferred port comes from repo scope + project identity + service class

Assessment:
- very strong determinism
- easier to extend than spacing
- less obvious to users unless surfaced clearly

Score: `44/55`

### D. Central slot allocator
Definition:
- persist a stable slot per project and derive service ports from the slot

Assessment:
- strongest long-term identity model
- adds a new metadata and migration layer
- more invasive than necessary for the current runtime

Score: `46/55`

### E. Hybrid preferred-port plus bounded rebound
Definition:
- derive a deterministic preferred port per project/service
- reserve that exact port first
- rebound only when necessary
- persist both preferred and actual

Assessment:
- keeps envctl’s determinism
- preserves explicit reservation and actual-port truth
- decouples identity from spacing
- minimizes migration blast radius

Score: `49/55`

## 8. Recommended Strategy
Adopt the hybrid model in the Python runtime, with deterministic project-slot preferred ports and legacy spacing available as an opt-out.

### Implemented direction
- `PortPlanner` now defaults to `project_slot` preferred-port derivation in [python/envctl_engine/shared/ports.py](../../../python/envctl_engine/shared/ports.py).
- Preferred ports are derived from:
  - runtime scope id
  - stable normalized project identity
  - per-service base port
- `Main` stays pinned to the configured base ports.
- Reservation, rebound, and actual listener truth are unchanged.
- `ENVCTL_PORT_PREFERRED_STRATEGY=legacy_spacing` remains available for compatibility-sensitive flows.

### Why this is better
- Stable project identity matters more than discovery index.
- Rebound should be the exception, not the identity model.
- `PORT_SPACING` is still useful as a compatibility and fallback concept, but no longer needs to define the whole allocator.
- App and infra now share the same identity primitive while keeping separate base ranges.

## 9. Public Contract Impact

### Keep
- `.envctl` base port settings
- `PortDefaults`
- `PortPlan`
- `ServiceRecord.requested_port`
- `ServiceRecord.actual_port`
- `ports_manifest.json`
- `runtime_map.json`

### Change
- Python preferred-port derivation now defaults to project-slot identity instead of index arithmetic.
- Add `ENVCTL_PORT_PREFERRED_STRATEGY` with supported values:
  - `project_slot`
  - `legacy_spacing`

### Demote
- `PORT_SPACING` is demoted from primary Python allocator input to:
  - fallback span when base ranges give no better slot space
  - compatibility input for `legacy_spacing`
  - existing shell compatibility input

### Preserve for migration compatibility
- `.envctl-workspaces/*.ports`
- shell spacing-based cleanup and worktree assumptions

## 10. Migration Strategy
1. Change Python preferred-port derivation first.
2. Keep rebound and actual-port truth unchanged.
3. Keep shell behavior unchanged for now.
4. Preserve `legacy_spacing` opt-out for users or tests that depend on strict old arithmetic.
5. Revisit shell cleanup and `.envctl-workspaces/*.ports` once Python is the uncontested source of truth.

## 11. Risks And Mitigations
- Risk: users expect exact index-based ports.
  - Mitigation: `legacy_spacing` opt-out and retained base port configurability.
- Risk: hashed project slots collide.
  - Mitigation: reservation and bounded rebound already handle collisions.
- Risk: shell cleanup still assumes spaced ranges.
  - Mitigation: treat shell range sweeping as migration compatibility, not Python truth.
- Risk: bases configured too close together reduce slot span.
  - Mitigation: planner computes slot span from configured base gaps and falls back to spacing when needed.

## 12. Test Impact

### Contracts that must remain true
- deterministic preferred ports for the same project
- unique final ports after reservation and rebound
- actual listener ports drive runtime projection
- stale lock reclaim remains session-safe
- `Main` remains pinned to configured base ports

### Assumptions that were overfit to spacing
- exact `index * spacing` values for non-main Python project plans
- discovery order as the stable identity of a project

### Coverage updated
- unit coverage in [tests/python/shared/test_port_plan.py](../../../tests/python/shared/test_port_plan.py) now asserts:
  - project-slot determinism
  - independence from discovery index
  - main-mode base-port stability
  - legacy-spacing compatibility mode

## 13. Final Decision
Envctl should not keep `base + spacing/offset + linear rebound` as the primary Python port allocation strategy.

The Python runtime should use:
- deterministic project-slot preferred ports
- explicit reservation and ownership
- rebound only when necessary
- actual listener ports as runtime truth

`PORT_SPACING` remains part of the public surface for compatibility and advanced control, but it is no longer the core identity mechanism for Python preferred-port allocation.
