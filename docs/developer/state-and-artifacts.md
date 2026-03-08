# State and Artifacts

This guide documents the runtime data model, artifact layout, persistence contract, and compatibility rules.

Use it when you are changing state models, runtime-map behavior, save/load flows, or per-run artifact generation.

## The Core Model

The typed state model lives in `python/envctl_engine/state/models.py`.

Main dataclasses:

- `PortPlan`
- `ServiceRecord`
- `RequirementsResult`
- `RunState`

These are not incidental implementation details. They are the runtime contract that connects:

- startup
- resume
- dashboard
- doctor
- debug bundles
- state reload
- compatibility layers

## `PortPlan`

`PortPlan` captures:

- `project`
- `requested`
- `assigned`
- `final`
- `source`
- `retries`

Use it whenever you need to explain why a port is what it is.

If a port decision is externally meaningful, it should usually be represented through `PortPlan` and persisted into `ports_manifest.json`.

## `ServiceRecord`

`ServiceRecord` is the runtime truth payload for an application service.

Important fields:

- `name`
- `type`
- `cwd`
- `pid`
- `requested_port`
- `actual_port`
- `log_path`
- `status`
- `synthetic`
- `started_at`
- `listener_pids`

This record is consumed by:

- dashboard rendering
- runtime truth reconciliation
- runtime map projection
- resume logic
- diagnostics

If you change status meaning or ownership semantics, expect to touch more than one subsystem.

## `RequirementsResult`

`RequirementsResult` normalizes dependency startup outcomes by dependency id.

It supports:

- modern component payloads
- legacy keys such as `db`
- health/failure metadata
- normalized resource data through `RequirementComponentResult`

The dependency ids are registry-driven, so the normalized shape matters for:

- state persistence
- doctor
- dashboard
- runtime truth
- projection and env injection

## `RunState`

`RunState` is the top-level persisted runtime object.

Key fields:

- `run_id`
- `mode`
- `schema_version`
- `backend_mode`
- `services`
- `requirements`
- `pointers`
- `metadata`

The `metadata` block is intentionally flexible, but do not treat it as a dumping ground. If a field has stable semantics, prefer moving it into the typed model.

## State Repository

`python/envctl_engine/state/repository.py` owns persistence strategy.

Responsibilities:

- write latest-view artifacts
- write per-run history
- maintain pointers
- mirror compatibility artifacts when configured
- load latest matching state with scope and mode rules

This repository is the place to centralize persistence behavior. Avoid ad hoc writes from orchestrators when the artifact is part of the runtime contract.

## Runtime Roots

Relevant path concepts:

- `config.runtime_dir`: shared envctl runtime root
- `config.runtime_scope_dir`: scoped runtime directory for the current repo
- `runtime.runtime_root`: active scope root
- `runtime.runtime_legacy_root`: compatibility root

The scoped root is the authoritative Python runtime location.

The legacy root exists because cutover compatibility still matters.

## Latest-View Artifacts

The runtime keeps a latest view for active inspection and resume:

- `run_state.json`
- `runtime_map.json`
- `ports_manifest.json`
- `error_report.json`
- `events.jsonl`
- `shell_ownership_snapshot.json`
- `shell_prune_report.json`

These files should be stable enough for operators and tooling to inspect directly.

## Per-Run Artifacts

Each run also gets immutable history under:

```text
runs/<run-id>/
```

Typical contents:

- `run_state.json`
- `runtime_map.json`
- `ports_manifest.json`
- `error_report.json`
- `events.jsonl`
- `shell_prune_report.json`

If you are adding a new artifact, decide whether it belongs:

- only in latest view
- only in per-run history
- in both

## Runtime Map

`python/envctl_engine/state/runtime_map.py` builds the operator-facing projection.

It provides:

- `projects`
- `port_to_service`
- `service_to_actual_port`
- `projection`

The `projection` block is where user-facing backend/frontend URLs and statuses live.

When changing runtime-map logic, ask:

- does dashboard output change?
- does resume output change?
- do integration tests read this file?
- do docs instruct users to rely on the current shape?

## Pointers

Pointers matter because resume and compatibility lookups depend on them.

The repository maintains:

- scoped latest pointers
- mode-specific pointers
- compatibility pointers when allowed

Broken or stale pointers surface in doctor via pointer-status reporting.

If you change pointer behavior, verify:

- `show-state`
- resume lookup
- doctor pointer status
- scoped vs legacy compatibility behavior

## Compatibility Modes

The repository supports:

- `compat_read_write`
- `compat_read_only`
- `scoped_only`

These govern how aggressively Python writes or reads compatibility artifacts outside the scoped root.

This is not just an implementation choice. It affects:

- migration behavior
- shell compatibility
- debugging expectations
- state inspection across mixed runs

## Legacy Shell State

Legacy shell state can still be loaded through `python/envctl_engine/state/__init__.py`.

Important behavior:

- legacy payloads are normalized into modern models
- legacy state is marked in metadata
- resume treats legacy state more conservatively
- legacy compatibility should not silently override modern scoped truth

When changing compatibility behavior, verify both the Python-native and legacy-read paths.

## Error Report Contract

`error_report.json` is the structured summary of recent failures.

It is intentionally simpler than event streams and should remain:

- machine-readable
- compact
- stable enough for doctor and operator inspection

If you expand it, keep the default use case in mind: quick failure triage.

## Event Streams

Two event families are relevant here:

- runtime events in `events.jsonl`
- debug flight recorder events in `debug/session-*/events.debug.jsonl`

Do not conflate them:

- runtime events are the operational ledger
- debug events are opt-in capture artifacts

## Shell Prune Artifacts

The runtime also persists:

- `shell_ownership_snapshot.json`
- `shell_prune_report.json`

These are part of the migration/cutover governance layer.

Even if you are working on pure Python behavior, these artifacts may still need to stay consistent because doctor and release gates read them.

## Adding a New Artifact

Checklist:

1. Define the data contract clearly.
2. Decide whether it belongs in latest view, run history, or both.
3. Persist it through the repository/artifact layer.
4. Decide whether doctor, debug, or user docs should mention it.
5. Add tests for write, read, and compatibility behavior.

## Changing a State Model

Checklist:

1. Update the typed dataclass.
2. Update serialization and normalization code.
3. Update compatibility loaders if legacy data can provide the field.
4. Update runtime map and truth logic if they depend on it.
5. Update tests across runtime, state, and any user-facing projection surfaces.

## Common Mistakes

- writing artifacts directly from orchestrators instead of through repository/artifact helpers
- adding stable fields to `metadata` instead of modeling them explicitly
- changing runtime-map shape without updating consumers
- forgetting legacy shell load compatibility
- treating latest-view files as disposable when resume and doctor depend on them
