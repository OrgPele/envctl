# envctl 1.6.9

`envctl` 1.6.9 is a hotfix release on top of `1.6.8`. It expands the shipped `create_plan` guidance so the planning follow-up can explain envctl launch behavior in plain language, include OMX-managed paths, and avoid telling users to type unsupported in-session Codex commands by hand.

## Why This Release Matters

The `create_plan` prompt already suggested repo-scoped tmux launches for Codex and OpenCode, but it did not fully document what each launch surface actually does. That made the follow-up guidance incomplete for users who want OMX-managed Codex sessions, want to understand whether envctl will take over the current terminal, or want to run parallel Codex + OMX follow-ups from the same plan.

This hotfix teaches the shipped planning prompt to explain `--tmux`, `--omx`, `--omx --ralph`, `--omx --team`, `--headless`, and `--tmux-new-session` directly in the handoff so users do not need to consult `--help` first.

## Highlights

### `create_plan` now explains launch behavior, not just flags

- repo-scoped follow-up guidance now includes:
  - `envctl --plan <selector> --tmux`
  - `envctl --plan <selector> --tmux --opencode`
  - `envctl --plan <selector> --omx`
  - `envctl --plan <selector> --omx --ralph`
  - `envctl --plan <selector> --omx --team`
- the prompt now tells the planner to explain, in plain language:
  - whether envctl only prints guidance or actually launches a session
  - whether the session is envctl-managed tmux or OMX-managed tmux/Codex
  - whether the current terminal is taken over
  - how the user can reconnect later
- multi-launch follow-ups now cover both:
  - `codex + opencode`
  - `codex + omx`
- the prompt now explicitly says envctl submits the rendered workflow automatically for managed launches, and should not tell users to manually type `/prompts:implement_task` or `$envctl-implement-task` unless a repo-specific manual step is genuinely required

## Included Changes

- `create_plan` prompt-template follow-up guidance expanded for OMX and richer launch explanations
- prompt-install tests updated to lock the new text contract
- release metadata updated for `1.6.9`

## Verification

Validated in the release worktree with:

- `python -m unittest tests.python.runtime.test_prompt_install_support` ✅
- `python -m build --wheel --sdist --outdir dist .` ✅

Observed during validation:

- `tests.python.runtime.test_cli_packaging` still fails on both `origin/main` and this release worktree in fresh venvs because `pip install --no-build-isolation --no-deps` cannot import `setuptools.build_meta` when the ephemeral venv lacks setuptools. This pre-existing environment/test issue is unchanged by the 1.6.9 prompt-template hotfix.

## Artifacts

This release publishes:

- wheel distribution
- source distribution
- release notes markdown asset

After build, the artifacts are available under `dist/`.

## Summary

`envctl` 1.6.9 is a planning-guidance hotfix. It keeps the shipped `create_plan` instructions aligned with the current tmux and OMX launch surfaces, and makes the handoff understandable without requiring the user to inspect CLI help first.
