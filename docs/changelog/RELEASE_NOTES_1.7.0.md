# envctl 1.7.0

`envctl` 1.7.0 is a minor release on top of `1.6.10`. It ships the post-1.6.10 work on current `main`: explicit create-plan auto-launch presets, a richer first-run test-command setup experience, safer AI handoff behavior when local startup cannot proceed, and a protected-artifact recovery fix for `envctl commit --headless --main`.

## Why This Release Matters

The 1.6.x series made Codex, OpenCode, OMX, Ralph, Team, and ULW plan-agent launches more reliable. The next layer is making those workflows easier and safer to start. This release adds explicit opt-in planning skills that can write a plan and immediately launch the right AI implementation surface, while keeping the default `$envctl-create-plan` flow approval-first.

It also tightens two important operator paths: first-run configuration now presents backend/frontend test commands as explicit selectable choices, and degraded local startup after a successful AI plan-agent launch now reports a clear handoff instead of obscuring the running implementation session behind a generic startup failure.

## Highlights

### Explicit create-plan auto-launch presets

- Adds packaged `create_plan_auto_codex`, `create_plan_auto_opencode`, and `create_plan_auto_omx` prompt templates.
- Registers explicit-only Codex skill metadata for `$envctl-create-plan-auto-codex`, `$envctl-create-plan-auto-opencode`, and `$envctl-create-plan-auto-omx`.
- Keeps the existing `$envctl-create-plan` preset approval-first; auto-launch behavior is available only through the new explicit presets.
- Locks the generated launch commands for each surface:
  - Codex: `ENVCTL_PLAN_AGENT_CODEX_CYCLES=4 envctl --plan <selector> --tmux --headless --tmux-new-session`
  - OpenCode/ULW: `envctl --plan <selector> --tmux --opencode --ulw --headless --tmux-new-session`
  - OMX/Ralph: `envctl --plan <selector> --omx --ralph --headless --tmux-new-session`

### First-run test setup is more explicit

- The startup/config wizard now exposes backend/frontend test command and path suggestions as visible setup choices.
- Root pytest configuration is detected ahead of unittest fallback, with labeled confidence/source metadata.
- Focused test fields can cycle accepted suggestions without overwriting unrelated fields.
- `ENVCTL_ACTION_TEST_CMD` remains a lower-level runtime/payload override instead of becoming a conflicting first-run wizard field.

### Plan-agent handoff is clearer when local startup degrades

- If an AI implementation session is running but local service startup fails because commands are missing, envctl now treats the result as a degraded handoff rather than a plain fatal startup failure.
- Headless output preserves attach/kill guidance for the running tmux/OMX implementation session.
- Interactive plan-agent launches attempt attach where appropriate.
- Strict runtime-truth reconciliation skips the degraded handoff case so it cannot replace actionable session guidance with a misleading service-truth failure summary.

### `envctl commit --headless --main` recovers protected artifacts

- Broad implementation workflows often run `git add .`, which can accidentally stage envctl-local control files.
- The commit path now unstages only known protected envctl-local artifacts, re-checks commit-worthiness, stages normal changes, and continues.
- `.envctl-commit-message.md` remains protected while still serving as the default commit-message ledger.
- Only-protected staged changes now become a clean no-op instead of an empty commit-message failure.

## Included Changes

- PR #138: Clarify plan-agent handoff when local startup degrades.
- PR #139: Make startup wizard test commands explicit and selectable.
- PR #140: Add create-plan auto-launch presets.
- PR #142: Recover protected task artifacts during envctl commits.

## Verification

Validated in the release worktree with:

- `./.venv/bin/python -m pytest -q` ✅
- `./.venv/bin/python -m build` ✅
- `./.venv/bin/python scripts/release_shipability_gate.py --repo .` ✅
- `git diff --check` ✅
- `./.venv/bin/python -m compileall -q python tests/python` ✅
- `./.venv/bin/ruff check --select F python tests/python` ✅

## Artifacts

This release publishes:

- wheel distribution
- source distribution
- release notes markdown asset

After build, the artifacts are available under `dist/`.

## Upgrade Notes

- No data migration or manual config migration is required.
- The new create-plan auto-launch presets are opt-in; existing `$envctl-create-plan` behavior remains approval-first.
- `envctl commit --headless --main` now intentionally mutates the index only for known protected envctl-local artifact paths by unstaging them before the normal commit flow.

## Summary

`envctl` 1.7.0 turns the new plan-agent surfaces into easier explicit workflows while hardening the setup and commit paths around them. It adds opt-in create-plan auto-launch skills, makes first-run test command configuration clearer, preserves actionable AI handoff guidance when local startup is incomplete, and recovers safely from staged envctl-local artifacts during headless commits.
