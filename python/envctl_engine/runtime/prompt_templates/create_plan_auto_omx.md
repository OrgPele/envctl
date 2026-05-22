Use the normal `create_plan` workflow, then launch implementation with OMX Ultragoal and the shared `implement_task` prompt.

This command must be run from Codex or another agent/runtime that can create the plan file and then execute the envctl launch command. Do not implement in the planning session after launch.

## Inputs
$ARGUMENTS

## Workflow
1. Follow the full `create_plan` prompt contract: research the repo, write exactly one plan under `todo/plans/<category>/<slug>.md`, record launch scope, and choose an informational Codex-equivalent cycle count from `0` through `3`.
2. Validate the plan path exists and derive `<category>/<slug>` by removing `todo/plans/` and `.md`.
3. Launch OMX Ultragoal implementation from the repo root with the shared `implement_task` preset:

```bash
cd <repo-root> && envctl --plan <category>/<slug> --omx --ultragoal --preset implement_task --entire-system --headless --new-session
```

OMX-managed launches are Codex-only. Use `--ralph` explicitly only when the Ralph compatibility workflow is required. Use a narrower runtime scope only when the plan explicitly records why full-stack E2E does not apply.

## Final Response
Report the plan path, implementation surface, exact command executed, launch result, attach/reconnect guidance, and any residual risks.
