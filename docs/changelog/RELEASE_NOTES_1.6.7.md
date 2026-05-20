# envctl 1.6.7

`envctl` 1.6.7 is a hotfix release on top of `1.6.6`. It updates the Codex install path so `envctl install-prompts --cli codex` installs explicit-only Codex skills under `~/.codex/skills` instead of writing prompt files to the older envctl-managed prompt directory.

## Why This Release Matters

Codex now prefers skill bundles over prompt files for reusable workflows. `envctl` was still writing Codex presets to the older prompt path, which made the install surface feel stale and confusing in real usage.

This hotfix aligns the Codex install path with the current Codex skill model while preserving envctl's direct prompt submission behavior for internal launches.

## Highlights

### Codex installs now land as skills

- `envctl install-prompts --cli codex` now writes explicit-only Codex skills under `~/.codex/skills/envctl-*`
- Codex skill installs no longer require the extra `--with-codex-skills` opt-in to get the skill output
- command output and JSON output now report `skill_results` for Codex installs directly

### Envctl still resolves Codex prompt bodies safely

- envctl now extracts the direct prompt body from the installed Codex `SKILL.md` when needed
- installed skill files include explicit prompt-body markers so envctl can keep using the shipped workflow text without relying on deprecated prompt-file locations
- legacy `~/.codex/prompts` fallback remains available for older customized setups

## Included Changes

- default Codex install-prompts path switched to `~/.codex/skills/envctl-*`
- direct prompt resolution from installed Codex skills
- docs/tests updated for the Codex skill-first contract
- release metadata updated for `1.6.7`

## Operator Notes

- for Codex, the primary install surface is now the global user-level skill directory: `~/.codex/skills/`
- Claude Code and OpenCode continue to use their existing prompt/command install roots
- release artifacts are expected under `dist/` after building the package

## Artifacts

This release publishes:

- wheel distribution
- source distribution
- release notes markdown asset

After build, the artifacts are expected under `dist/`.

## Summary

`envctl` 1.6.7 is a targeted Codex compatibility hotfix. It aligns `install-prompts --cli codex` with Codex’s skill-first workflow model while preserving envctl’s internal direct prompt submission behavior.
