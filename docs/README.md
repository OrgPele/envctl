# envctl Documentation

This documentation set is organized by audience and task rather than as one flat list of pages.

Runtime note:

- The Python engine is the primary and documented runtime.
- The legacy Bash/shell engine still exists behind `ENVCTL_ENGINE_SHELL_FALLBACK=true`, but it is deprecated and retained only as a compatibility fallback during cutover.

## Start Here

- First successful run: [User Getting Started](user/getting-started.md)
- Guided setup wizard: [First-Run Wizard](user/first-run-wizard.md)
- Copy-pasteable daily flows: [Common Workflows](user/common-workflows.md)
- Quick answers and common confusion points: [FAQ](user/faq.md)
- Troubleshooting and incident response: [Operations](operations/README.md)

## User Docs

- [User Guides](user/README.md)
- [Getting Started](user/getting-started.md)
- [First-Run Wizard](user/first-run-wizard.md)
- [Common Workflows](user/common-workflows.md)
- [FAQ](user/faq.md)
- [Python Engine Guide](user/python-engine-guide.md)
- [Planning and Worktrees](user/planning-and-worktrees.md)
- [AI Playbooks](user/ai-playbooks.md)

## Reference

- [Reference Index](reference/README.md)
- [Commands](reference/commands.md)
- [Configuration](reference/configuration.md)
- [Important Flags](reference/important-flags.md)

## Developer Docs

- [Developer Guides](developer/README.md)
- [Architecture Overview](developer/architecture-overview.md)
- [Python Runtime Guide](developer/python-runtime-guide.md)
- [Config and Bootstrap](developer/config-and-bootstrap.md)
- [Command Surface and Routing](developer/command-surface.md)
- [UI and Interaction Architecture](developer/ui-and-interaction.md)
- [Module Layout](developer/module-layout.md)
- [Contributing](developer/contributing.md)

## Operations

- [Operations Index](operations/README.md)
- [Troubleshooting](operations/troubleshooting.md)
- [Interactive Selector Key Throughput Investigation (Paused)](troubleshooting/interactive-selector-key-throughput-readme.md)

## Planning, History, and Meta

- [Planning and Roadmaps](planning/README.md)
- [Python Engine Migration Ops](planning/refactoring/envctl-python-engine-migration-operations.md)
- [Changelog](changelog/main_changelog.md)
- [License](license.md)
