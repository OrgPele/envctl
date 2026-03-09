# Shell Compatibility and Deprecation

This guide explains the current status of the legacy Bash/shell runtime, why it still exists, and how contributors should treat it while the Python engine is primary.

Use it when you are touching compatibility shims, shell-prune gates, shell fallback behavior, or migration docs/tests.

## Current Policy

Today:

- the Python engine is the primary runtime
- the Bash/shell engine still exists
- shell execution is an explicit fallback, not the normal path
- shell fallback is deprecated, but not removed

The practical toggle is:

```bash
ENVCTL_ENGINE_SHELL_FALLBACK=true envctl --resume
```

That path exists for:

- parity debugging
- emergency rollback during cutover
- compatibility support while migration gates remain in place

It should not be treated as a co-primary developer experience.

## Where the Shell Path Still Lives

Important files:

- `lib/envctl.sh`
- `lib/engine/main.sh`
- `lib/engine/lib/**`
- `python/envctl_engine/shell/**`
- `contracts/envctl-shell-ownership-ledger.json`

The Python runtime also still knows about shell compatibility through:

- legacy state readers
- shell prune reports
- shipability gates
- compatibility artifact mirroring

## Why the Shell Path Still Matters

Even though Python is primary, shell compatibility still affects:

- explicit fallback runs
- migration governance
- release gates
- state compatibility
- documentation promises during cutover

That means it is easy to break meaningful behavior if you treat shell code as dead code.

## Fallback Semantics

`lib/engine/main.sh` owns the Python vs shell decision.

Important current facts:

- Python is default
- shell fallback is explicit
- some modern commands are Python-only and should fail clearly under shell fallback

Example:

- `debug-pack` is Python-runtime only

This is the correct pattern: clear capability boundaries, not fake parity.

## Shell Ownership Ledger

The shell ownership ledger lives in:

- `contracts/envctl-shell-ownership-ledger.json`

It exists so the project can answer:

- what shell code remains
- why it remains
- whether it is intentionally kept, partially kept, or ready to delete

Relevant evaluator:

- `python/envctl_engine/shell/shell_prune.py`

Do not remove shell code casually if the ledger and prune contract still consider it active or intentionally retained.

## Shell Prune Report

The runtime persists:

- `shell_ownership_snapshot.json`
- `shell_prune_report.json`

These are not cosmetic.

They are part of:

- doctor output
- cutover readiness
- release governance

If you change shell compatibility behavior, verify these artifacts still make sense.

## Compatibility Shims

The repo still keeps compatibility shims at multiple levels:

- old shell library locations
- old Python flat import paths
- compatibility config aliases
- legacy state readers
- legacy runtime artifact mirroring when configured

The right question is not "can we delete this?" but "what contract does this still serve?"

## What Counts as Safe Shell Cleanup

Usually safe only when all of the following agree:

1. the Python runtime owns the behavior fully
2. tests cover the modern path
3. the shell ownership ledger says it is ready
4. doctor/release gates remain green
5. docs no longer promise the old behavior

## What Not To Do

Do not:

- assume shell fallback is already removed
- silently break the explicit fallback path
- remove compatibility writes/reads without checking resume and doctor
- delete shell modules just because they look unused from the Python path
- document shell behavior as current primary behavior

## When to Mention Shell in User Docs

User docs should mention shell only when it matters operationally:

- there is an explicit fallback command
- a modern feature is Python-only
- a migration/cutover limitation affects troubleshooting

User docs should not make the shell path feel like the normal recommended mode.

## When to Mention Shell in Developer Docs

Developer docs should mention shell whenever the change touches:

- fallback routing
- compatibility state/artifacts
- prune gates
- ledger-driven cleanup
- release gate behavior

This is where the full nuance belongs.

## Checklist for Shell-Adjacent Changes

1. Does `lib/engine/main.sh` still behave correctly?
2. Does the explicit fallback path fail clearly when a Python-only feature is used?
3. Does doctor still report shell migration state correctly?
4. Does the shell ownership ledger or prune report need updating?
5. Do user docs need a brief fallback note?
6. Do migration/cutover docs need updating?

## Long-Term Direction

The long-term direction across the codebase and planning docs is clear:

- Python becomes the only primary runtime
- shell fallback is reduced to a compatibility escape hatch
- shell fallback is eventually retired after migration criteria are met

Until then, contributors should optimize for:

- a strong Python-first experience
- explicit shell compatibility boundaries
- no ambiguity in docs about which runtime is primary
