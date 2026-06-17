Use the normal `create_plan` workflow, then launch implementation with Codex and the shared `implement_task` prompt.

This command must be run from Codex or another agent/runtime that can create the plan file and then execute the envctl launch command. Do not implement in the planning session after launch.

## Inputs
$ARGUMENTS

## Workflow
1. Follow the full `create_plan` prompt contract: research the repo, write exactly one plan under `todo/plans/<category>/<slug>.md`, record launch scope, and choose `recommended_codex_cycles=<n>` from `0` through `3`.
2. Validate the plan path exists and derive `<category>/<slug>` by removing `todo/plans/` and `.md`.
3. Launch Codex implementation from the repo root with the shared `implement_task` preset:

```bash
cd <repo-root> && ENVCTL_PLAN_AGENT_CODEX_CYCLES=<recommended_codex_cycles> envctl --plan <category>/<slug> --cmux --preset implement_task --entire-system --headless --new-session
```

Use a narrower runtime scope only when the plan explicitly records why full-stack E2E does not apply.

## Final Response
Report the plan path, exact command executed, launch result, attach/reconnect guidance, and any residual risks.
