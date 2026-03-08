# User Guides

This section is for people using `envctl` to:

- bring up a local environment quickly
- run and compare multiple implementations or worktrees
- inspect what `envctl` will do before it starts anything
- debug real runs when startup or interaction goes wrong

## Start Here

- [Getting Started](getting-started.md)
- [First-Run Wizard](first-run-wizard.md)
- [Common Workflows](common-workflows.md)
- [FAQ](faq.md)
- [Troubleshooting](../operations/troubleshooting.md)
- [Python Engine Guide](python-engine-guide.md)
- [Planning and Worktrees](planning-and-worktrees.md)
- [AI Playbooks](ai-playbooks.md)

## Choose Your Path

- New to `envctl`: start with [Getting Started](getting-started.md).
- Want the guided setup path `envctl` actually shows on first run: use [First-Run Wizard](first-run-wizard.md).
- Already installed and want copy-pasteable flows: use [Common Workflows](common-workflows.md).
- Something is broken or surprising: start with [Troubleshooting](../operations/troubleshooting.md).
- Working with plans and multiple implementations: use [Planning and Worktrees](planning-and-worktrees.md).
- Debugging runtime behavior, artifacts, or doctor/debug-pack flows: use [Python Engine Guide](python-engine-guide.md).
- Looking for short answers: check [FAQ](faq.md).

## Important Runtime Note

- The Python engine is the primary runtime and the one these guides are written for.
- A deprecated Bash/shell fallback still exists behind `ENVCTL_ENGINE_SHELL_FALLBACK=true`, but it is only for compatibility, parity debugging, or emergency rollback.

## Related Sections

- [Troubleshooting](../operations/troubleshooting.md)
- [Reference](../reference/README.md)
- [Operations](../operations/README.md)
- [Documentation Hub](../README.md)
