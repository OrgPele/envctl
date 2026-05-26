from __future__ import annotations

from collections.abc import Iterable

from envctl_engine.runtime.command_policy import DIRECT_INSPECTION_COMMANDS
from envctl_engine.runtime.command_router import list_supported_commands
from envctl_engine.runtime.help_metadata import (
    DEBUG_COMMANDS,
    DEFAULT_HEADLESS_COMMANDS,
    GENERAL_ACTION_ORDER,
    GENERAL_DIAGNOSTIC_ORDER,
    GENERAL_INSPECTION_ORDER,
    GENERAL_UTILITY_ORDER,
    GENERAL_WORKFLOW_ORDER,
    UTILITY_COMMANDS,
    WORKFLOW_COMMANDS,
    ordered_known_commands,
)


def render_general_help() -> str:
    commands = list_supported_commands()
    workflow = _join_commands(ordered_known_commands(GENERAL_WORKFLOW_ORDER, WORKFLOW_COMMANDS))
    actions = _join_commands(ordered_known_commands(GENERAL_ACTION_ORDER, DEFAULT_HEADLESS_COMMANDS))
    inspection = _join_commands(ordered_known_commands(GENERAL_INSPECTION_ORDER, DIRECT_INSPECTION_COMMANDS))
    utility = _join_commands(ordered_known_commands(GENERAL_UTILITY_ORDER, UTILITY_COMMANDS))
    diagnostics = _join_commands(ordered_known_commands(GENERAL_DIAGNOSTIC_ORDER, DEBUG_COMMANDS))
    all_commands = _join_commands(commands)
    return "\n".join(
        [
            "envctl - run, inspect, test, and ship repo services/worktrees",
            "",
            "What envctl does:",
            "  envctl is a repo-local orchestration CLI. It can start managed services,",
            "  restore saved runtime state, show a dashboard, run project actions, create",
            "  implementation worktrees, launch AI implementation sessions, and collect",
            "  diagnostics/debug bundles for troubleshooting.",
            "",
            "Usage:",
            "  envctl [start] [--main|--trees] [--headless] [runtime scope]",
            "  envctl <command> [targets] [flags]",
            "  envctl <command> --help",
            "  envctl --repo <path> <command>      # launcher/repo-wrapper form",
            "  envctl --version",
            "",
            "Command families:",
            "  Workflow commands (may start services or open interactive flows):",
            f"    {workflow}",
            "    Use these when you want envctl to run or restore the local environment,",
            "    enter the dashboard, edit configuration, or create plan worktrees.",
            "",
            "  Specific action commands (non-interactive/headless by default):",
            f"    {actions}",
            "    These execute the requested action immediately. They behave like --headless",
            "    by default; pass --interactive to opt back into prompts/target selectors.",
            "",
            "  Inspection and diagnostics:",
            f"    inspection: {inspection}",
            f"    diagnostics: {diagnostics}",
            "    Use these to understand config, saved state, startup decisions, health,",
            "    logs, and debug evidence before mutating services or worktrees.",
            "",
            "  Utilities and setup:",
            f"    {utility}",
            "    Use these for AI prompt installation, Codex tmux sessions, cheap worktree",
            "    creation, or hook migration without entering full runtime startup.",
            "",
            "Modes:",
            "  --main                  operate on the main repo checkout (default unless .envctl says otherwise)",
            "  --tree / --trees        operate on envctl-managed implementation worktrees",
            "  main=true / trees=true  env-style compatibility aliases for scripts",
            "",
            "Targeting and runtime scopes:",
            "  --project <name>        target one or more projects/worktrees (comma-separated allowed)",
            "  --service <name>        target services such as backend/frontend or saved service names",
            "  --all                   target every discovered/saved project when the command supports it",
            "  --backend               dependencies + backend service only",
            "  --frontend              dependencies + frontend service only",
            "  --fullstack / --both    dependencies + backend + frontend",
            "  --dependencies / --deps dependencies only",
            "  --entire-system         dependencies + every configured app service",
            "  --shared-deps           tree runs use the main/shared managed dependency stack (default)",
            "  --isolated-deps         tree runs use isolated managed dependencies",
            "  --separate-deps         alias for --isolated-deps",
            "  --managed-deps          disable external dependency auto-detection for this run",
            "  --only-frontend         launch only frontend; skip backend and dependencies/prep",
            "  --only-backend          launch only backend; skip frontend and dependencies/prep",
            "  --no-deps               skip managed dependencies and plan-agent dependency prep",
            "  --no-infra              skip backend, frontend, managed dependencies, and plan-agent prep",
            "",
            "Important global flags:",
            "  --headless / --batch    do not prompt; use deterministic automation-friendly output",
            "  --interactive           opt specific action commands back into prompts/selectors",
            "  --json                  machine-readable output where supported",
            "  --dry-run               preview mutations where supported",
            "  --force / --yes         approve destructive or overwrite flows where supported",
            "",
            "Examples:",
            "  envctl --help",
            "  envctl start --main --headless",
            "  envctl --trees --headless",
            "  envctl dashboard",
            "  envctl health --all",
            "  envctl logs --project feature-a-1 --logs-follow",
            "  envctl test --project feature-a-1",
            "  envctl pr --project feature-a-1 --pr-base main",
            "  envctl kill-all",
            "  envctl --plan feature/task --omx --ultragoal --headless",
            "  envctl list-targets --json",
            "  envctl show-config --json",
            "",
            "Get focused help:",
            "  envctl <command> --help       # command-specific usage, flags, examples, and notes",
            "  envctl help <command>         # equivalent prefix form for focused help",
            "  envctl --plan --help          # planning/worktree implementation help",
            "  envctl install-prompts --help # AI workflow preset installation help",
            "  envctl codex-tmux --help      # repo-scoped Codex tmux helper help",
            "  envctl list-commands          # one command per line for scripts/completion",
            "",
            f"  all commands: {all_commands}",
        ]
    )


def _join_commands(commands: Iterable[str]) -> str:
    return ", ".join(commands)
