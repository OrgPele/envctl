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
- When a handoff message is ready, use `envctl test-focused --ship-on-pass
  "<message>"` from inside the current worktree as the single envctl local
  validation-and-handoff command; do not run standalone `envctl test-focused`
  first or repeat it afterward. Use additional repo-specific test commands only
  when diagnosing a failure or when the focused plan explicitly recommends
  broader validation for a cross-cutting/risky change.
- Fall back to `envctl ship -m "<message>"` only when the combined command is
  unavailable or returns actionable fallback instructions. Both use the ship
  workflow: it stages intended non-protected changes via git add, commits,
  pushes, creates/updates the PR, and reports status checks. Use raw `git` or
  `gh` handoff commands only when `ship` is unavailable.
- If shipping is delegated to a real background worker, it should report only
  blockers; successful ship results stay silent.
- Keep envctl-generated local artifacts uncommitted.
