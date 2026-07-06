Use the normal `create_plan` workflow, then launch implementation with OpenCode and the shared `implement_task` prompt.

This command must be run from OpenCode or another agent/runtime that can create the plan file and then execute the envctl launch command. Do not implement in the planning session after launch.

## Inputs
$ARGUMENTS

## Workflow
1. Follow the full `create_plan` prompt contract: research the repo, write exactly one plan under `todo/plans/<category>/<slug>.md`, record the intended launch scope, and add the Manual / real-world check.
2. Validate the plan path exists and derive `<category>/<slug>` by removing `todo/plans/` and `.md`.
3. Launch OpenCode implementation from the repo root with the shared `implement_task` preset:

```bash
cd <repo-root> && envctl --plan <category>/<slug> --cmux --opencode --preset implement_task --entire-system --headless --new-session
```

OpenCode plan-agent launches use the `/ulw-loop` prefix by default. The `--entire-system` flag records the intended implementation surface for the plan-agent workflow; it is not an instruction to prove the feature by starting local services. Use a narrower runtime scope only when the plan explicitly records why full-stack E2E does not apply.

## Success criteria
- Exactly one plan file exists at `todo/plans/<category>/<slug>.md`.
- The implementation launch uses the shared `implement_task` preset through OpenCode.
- The final response includes the plan path, exact command, launch result, and attach/reconnect guidance.

## Final response
Report the plan path, implementation surface, exact command executed, launch result, attach/reconnect guidance, and any residual risks.
