## Serena

This project is configured for Serena symbolic code navigation via `.serena/project.yml`.

Use Serena for precise, symbol-aware code work when it is available:
- Activate the current checkout/worktree path before structural navigation.
- Use Serena for Python symbol definitions, references, diagnostics, call-path
  checks, and semantic edits.
- Use normal shell/file tools for exact strings, docs, prompts, tests, git,
  envctl commands, and other literal-text workflows; use `rg` for flags, env
  keys, log messages, config values, docs prose, and error text.

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
- When a handoff message is ready and focused validation has not already passed
  for the final tree, use `envctl test-focused --ship-on-pass "<message>"` from
  inside the current worktree as the single envctl local validation-and-handoff
  command. If focused validation already passed for the final tree, use
  `envctl ship -m "<message>"` and do not rerun tests. Do not run standalone
  `envctl test-focused`, repeat passing tests, or run `envctl test --all` /
  other broad local suites before handoff. Full suites are CI-owned; use narrow
  diagnostic commands only when a focused validation failure needs investigation.
- Fall back to `envctl ship -m "<message>"` when the combined command is
  unavailable, returns actionable fallback instructions, or focused validation
  already passed for the final tree. Both use the ship
  workflow: it stages intended non-protected changes via git add, commits,
  pushes, creates/updates the PR, and reports status checks. Use raw `git` or
  `gh` handoff commands only when `ship` is unavailable.
- At the end of implementation/fix/change work, report the PR URL if one
  exists, preferably as the final line of the response.
- If shipping is delegated to a real background worker, it should report only
  blockers; successful ship results stay silent.
- Keep envctl-generated local artifacts uncommitted.
