## Serena

This project is configured for Serena symbolic code navigation via `.serena/project.yml`.

Use Serena for precise, symbol-aware code work when it is available:
- Activate the current checkout/worktree path before structural navigation.
- Use symbol lookup, reference lookup, and diagnostics for definitions,
  refactors, call-path work, and changed Python files.
- Use `rg` for exact strings such as flags, env keys, log messages, docs prose,
  and error text.

Serena boundaries:
- After structural code changes, let Serena refresh automatically. If results
  look stale, run `serena project health-check` from the repo root.
- Use `.serena/project.local.yml` for machine-specific overrides; keep
  `.serena/project.yml` versioned.

## Development Discipline

- For code changes, start with `git status --short` and inspect the relevant
  diff before editing. Preserve unrelated user changes.
- Read the owning code path before changing it. Prefer existing local helpers,
  patterns, and tests over new abstractions.
- Keep changes scoped to the task; avoid unrelated refactors, formatting churn,
  or generated metadata changes.
- For behavior changes, add or update the smallest test that proves the real
  contract, then report the validation actually run.
- If a required check cannot run, say why and name the remaining risk.

## Envctl Workflow

- In envctl source checkouts, prefer `PATH="$PWD/.venv/bin:$PATH" envctl ...`
  or `ENVCTL_USE_REPO_WRAPPER=1 ./bin/envctl ...` so validation and shipping
  run the current checkout instead of an installed `envctl`.
- Keep edits inside the current checkout/worktree and preserve unrelated user
  changes.
- During implementation, run `envctl test-focused` from inside the current
  worktree for the normal validation loop. Use broader validation only when the
  focused plan recommends it or the change is cross-cutting/risky.
- For handoff, use `envctl ship -m "<message>"` from inside the current
  worktree. `ship` owns commit, push, PR creation/update, and status-check
  reporting. Use raw `git` or `gh` handoff commands only when `ship` is
  unavailable or returns actionable fallback instructions.
- If shipping is delegated to a real background worker, it should report only
  blockers; successful ship results stay silent.
- Keep envctl-generated local artifacts uncommitted.
