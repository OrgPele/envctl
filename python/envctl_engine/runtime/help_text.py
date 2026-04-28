from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from envctl_engine.runtime.command_policy import (
    ACTION_COMMANDS,
    DIRECT_INSPECTION_COMMANDS,
    LIFECYCLE_CLEANUP_COMMANDS,
    STATE_ACTION_COMMANDS,
)
from envctl_engine.runtime.command_router import Route, list_supported_commands, parse_route


@dataclass(frozen=True, slots=True)
class CommandHelpTopic:
    command: str
    summary: str
    usage: tuple[str, ...]
    what_it_does: tuple[str, ...]
    examples: tuple[str, ...]
    flags: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    related: tuple[str, ...] = ()


WORKFLOW_COMMANDS = frozenset({"start", "restart", "resume", "dashboard", "config", "plan"})
DEBUG_COMMANDS = frozenset({"debug-pack", "debug-report", "debug-last", "doctor"})
UTILITY_COMMANDS = frozenset({"codex-tmux", "ensure-worktree", "install-prompts", "migrate-hooks"})
DEFAULT_HEADLESS_COMMANDS = ACTION_COMMANDS | LIFECYCLE_CLEANUP_COMMANDS | STATE_ACTION_COMMANDS
GENERAL_WORKFLOW_ORDER = ("start", "resume", "restart", "dashboard", "config", "plan")
GENERAL_ACTION_ORDER = (
    "stop",
    "stop-all",
    "blast-all",
    "logs",
    "clear-logs",
    "health",
    "errors",
    "test",
    "commit",
    "pr",
    "review",
    "migrate",
    "delete-worktree",
    "blast-worktree",
    "self-destruct-worktree",
)
GENERAL_INSPECTION_ORDER = (
    "list-commands",
    "list-targets",
    "list-trees",
    "show-config",
    "show-state",
    "explain-startup",
    "preflight",
    "session",
)
GENERAL_DIAGNOSTIC_ORDER = ("doctor", "debug-pack", "debug-report", "debug-last")
GENERAL_UTILITY_ORDER = ("install-prompts", "codex-tmux", "ensure-worktree", "migrate-hooks")


def render_help_text(route: Route | None) -> str:
    target = _help_target_command(route)
    if target is not None:
        topic = COMMAND_HELP_TOPICS.get(target)
        if topic is not None:
            return _render_command_help(topic)
    return _render_general_help()


def _help_target_command(route: Route | None) -> str | None:
    if route is None:
        return None
    raw_args = [str(token) for token in list(getattr(route, "raw_args", []) or []) if str(token).strip()]
    filtered = [token for token in raw_args if token not in {"--help", "-h", "help"}]
    if not filtered:
        return None
    try:
        resolved = parse_route(filtered, env={})
    except Exception:
        return None
    command = str(getattr(resolved, "command", "")).strip()
    return command if command and command != "help" else None


def _render_general_help() -> str:
    commands = list_supported_commands()
    workflow = _join_commands(_ordered_known_commands(GENERAL_WORKFLOW_ORDER, WORKFLOW_COMMANDS))
    actions = _join_commands(_ordered_known_commands(GENERAL_ACTION_ORDER, DEFAULT_HEADLESS_COMMANDS))
    inspection = _join_commands(_ordered_known_commands(GENERAL_INSPECTION_ORDER, DIRECT_INSPECTION_COMMANDS))
    utility = _join_commands(_ordered_known_commands(GENERAL_UTILITY_ORDER, UTILITY_COMMANDS))
    diagnostics = _join_commands(_ordered_known_commands(GENERAL_DIAGNOSTIC_ORDER, DEBUG_COMMANDS))
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
            "  envctl --plan feature/task --omx --ralph --headless",
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


def _render_command_help(topic: CommandHelpTopic) -> str:
    lines: list[str] = [f"envctl {topic.command} - {topic.summary}", ""]
    _extend_section(lines, "Usage:", topic.usage, bullet=False)
    _extend_section(lines, "What it does:", topic.what_it_does)
    lines.extend(["Default interactivity:", f"  {_default_interactivity(topic.command)}", ""])
    if topic.flags:
        _extend_section(lines, "Common flags:", topic.flags, bullet=False)
    if topic.notes:
        _extend_section(lines, "Notes:", topic.notes)
    _extend_section(lines, "Examples:", topic.examples, bullet=False)
    if topic.aliases:
        lines.extend(["Aliases:", f"  {_join_commands(topic.aliases)}", ""])
    if topic.related:
        lines.extend(["Related commands:", f"  {_join_commands(topic.related)}", ""])
    lines.append("Tip: use `envctl --help` for the full command map and global flags.")
    return "\n".join(lines).rstrip()


def _extend_section(lines: list[str], heading: str, values: Iterable[str], *, bullet: bool = True) -> None:
    materialized = tuple(values)
    if not materialized:
        return
    lines.append(heading)
    prefix = "  - " if bullet else "  "
    for value in materialized:
        lines.append(f"{prefix}{value}")
    lines.append("")


def _default_interactivity(command: str) -> str:
    if command in DEFAULT_HEADLESS_COMMANDS:
        return "headless by default; pass --interactive when you intentionally want prompts/selectors."
    if command in WORKFLOW_COMMANDS:
        return "interactive-capable by default; pass --headless for automation or deterministic CI output."
    if command in DIRECT_INSPECTION_COMMANDS or command in DEBUG_COMMANDS or command in UTILITY_COMMANDS:
        return "prints or performs the specific requested utility/inspection work; use --json where supported."
    return "depends on the selected command path; pass --headless to avoid prompts when supported."


def _join_commands(commands: Iterable[str]) -> str:
    return ", ".join(commands)


def _ordered_known_commands(preferred_order: Iterable[str], commands: Iterable[str]) -> tuple[str, ...]:
    remaining = set(commands)
    ordered = [command for command in preferred_order if command in remaining]
    remaining.difference_update(ordered)
    ordered.extend(sorted(remaining))
    return tuple(ordered)


COMMAND_HELP_TOPICS: dict[str, CommandHelpTopic] = {
    "start": CommandHelpTopic(
        command="start",
        summary="start the configured repo services for main or worktree mode",
        usage=(
            "envctl [start] [--main|--trees] [--headless] [runtime scope]",
            "envctl start --project <name> [--headless]",
        ),
        what_it_does=(
            "discovers configured projects for the selected mode",
            "allocates ports, starts enabled dependencies/backend/frontend services, and writes runtime state",
            "prints service URLs and dashboard-ready status once startup completes",
        ),
        flags=(
            "--main | --trees        choose main checkout or envctl-managed worktrees",
            "--headless              run without dashboard prompts",
            "--backend|--frontend|--fullstack|--dependencies|--entire-system  choose startup scope",
            "--project <name>        limit startup to selected project/worktree when supported",
            "--no-resume             skip automatic resume of a compatible saved run",
        ),
        examples=(
            "envctl",
            "envctl start --main --headless",
            "envctl start --trees --entire-system --headless",
            "envctl start --project feature-a-1 --backend --headless",
        ),
        related=("restart", "resume", "dashboard", "stop", "health"),
    ),
    "restart": CommandHelpTopic(
        command="restart",
        summary="restart selected envctl-managed services",
        usage=(
            "envctl restart [--project <name>|--service <name>|--all] [runtime scope] [--headless]",
        ),
        what_it_does=(
            "loads saved runtime state, stops the selected services, and starts them again",
            "keeps the same target model as startup while using existing envctl state as the source of truth",
        ),
        flags=(
            "--project <name>        restart services for selected project/worktree",
            "--service <name>        restart a specific saved service",
            "--all                   restart all eligible saved services",
            "--backend|--frontend|--fullstack|--entire-system  limit restart scope",
            "--headless              avoid dashboard prompts",
        ),
        examples=(
            "envctl restart --project feature-a-1 --headless",
            "envctl restart --backend --headless",
            "envctl restart --all --headless",
        ),
        related=("start", "resume", "stop", "health"),
    ),
    "resume": CommandHelpTopic(
        command="resume",
        summary="restore and reattach to a saved envctl runtime state",
        usage=("envctl resume [--main|--trees] [--headless]", "envctl --resume [--headless]"),
        what_it_does=(
            "loads the previous run state for the selected mode",
            "checks whether saved services are still running and restores stale services when possible",
            "prints the recovered run/session IDs and current service URLs",
        ),
        flags=(
            "--main | --trees        choose which saved state scope to resume",
            "--headless              print deterministic resume output instead of entering an interactive surface",
        ),
        examples=("envctl resume --headless", "envctl --resume --trees --headless"),
        related=("start", "dashboard", "health", "show-state"),
    ),
    "dashboard": CommandHelpTopic(
        command="dashboard",
        summary="show the envctl dashboard for the current saved state",
        usage=("envctl dashboard [--main|--trees]", "envctl dashboard --headless"),
        what_it_does=(
            "renders service status, ports, URLs, dependency rows, and available dashboard actions",
            "enters the interactive command loop when a TTY is available unless headless output is requested",
        ),
        flags=(
            "--main | --trees        choose the state scope to display",
            "--headless              print a one-shot dashboard snapshot",
            "--json                  prefer machine-readable output where available through inspection commands",
        ),
        examples=("envctl dashboard", "envctl dashboard --trees --headless", "envctl show-state --json"),
        related=("health", "logs", "errors", "show-state"),
    ),
    "config": CommandHelpTopic(
        command="config",
        summary="create or update the repo-local .envctl configuration",
        usage=("envctl config", "envctl config --set KEY=value", "printf '{...}' | envctl config --stdin-json"),
        what_it_does=(
            "opens the configuration wizard when interactive",
            "updates managed .envctl values such as service commands, ports, modes, and UI display settings",
            "can apply scriptable changes with --set or --stdin-json",
        ),
        flags=(
            "--set KEY=value         set one managed config key",
            "--stdin-json            read config updates as JSON from stdin",
            "--headless              fail cleanly instead of prompting when input is required",
        ),
        examples=(
            "envctl config",
            "envctl config --set ENVCTL_DEFAULT_MODE=trees",
            "printf '%s\n' '{\"default_mode\":\"trees\"}' | envctl config --stdin-json",
        ),
        related=("show-config", "preflight", "explain-startup"),
    ),
    "plan": CommandHelpTopic(
        command="plan",
        summary="create/reuse implementation worktrees from todo/plans selectors and optionally launch AI sessions",
        usage=(
            "envctl --plan <selector> [--headless] [--dry-run] [--tmux|--omx] [--codex|--opencode] [--ulw]",
            "envctl --plan <selector> [--omx --ralph | --omx --team]",
        ),
        what_it_does=(
            "resolves the requested plan selector against todo/plans",
            "creates or reuses the matching implementation worktree(s) unless --dry-run is used",
            "optionally launches the implementation workflow in tmux or OMX-managed Codex sessions",
        ),
        flags=(
            "--headless          stay non-interactive and print follow-up/attach guidance",
            "--dry-run           preview selected/reused/created worktrees without mutating git worktrees or trees/",
            "--tmux              envctl owns the tmux session/window and submits the workflow there",
            "--omx               envctl asks OMX to create/manage the detached Codex tmux session",
            "--ralph             OMX-only: start the launched Codex session in Ralph mode",
            "--team              OMX-only: start the launched Codex session in Team mode",
            "--codex             force Codex for tmux launches",
            "--opencode          force OpenCode for tmux launches",
            "--ulw               tmux + OpenCode only: prepend /ulw_loop to the launched prompt",
            "--tmux-new-session  create another tmux/OMX session instead of reusing an attachable existing one",
        ),
        examples=(
            "envctl --plan feature/task --headless",
            "envctl --plan feature/task --headless --dry-run",
            "envctl --plan feature/task --tmux --codex",
            "envctl --plan feature/task --tmux --opencode --ulw --headless",
            "envctl --plan feature/task --omx --ralph",
            "envctl --plan feature/task --omx --team",
        ),
        aliases=("--plan", "parallel-plan", "sequential-plan", "--parallel-plan", "--sequential-plan"),
        related=("ensure-worktree", "list-trees", "install-prompts", "codex-tmux"),
    ),
    "stop": CommandHelpTopic(
        command="stop",
        summary="stop selected envctl-managed services and update runtime state",
        usage=("envctl stop [--project <name>|--service <name>|--all] [runtime scope]",),
        what_it_does=(
            "loads saved runtime state and terminates selected services",
            "supports service-scope flags so you can stop backend, frontend, dependencies, or the entire system",
        ),
        flags=(
            "--project <name>        stop services for selected project/worktree",
            "--service <name>        stop one saved service",
            "--all                   stop all matching saved services",
            "--backend|--frontend|--fullstack|--dependencies|--entire-system  choose scope",
        ),
        examples=(
            "envctl stop --backend",
            "envctl stop --project feature-a-1 --frontend",
            "envctl kill --service feature-a-1-backend",
        ),
        aliases=("kill", "s", "--stop", "--kill"),
        related=("stop-all", "blast-all", "restart", "health"),
    ),
    "stop-all": CommandHelpTopic(
        command="stop-all",
        summary="stop every saved envctl-managed service in the selected scope",
        usage=("envctl stop-all [runtime scope]", "envctl kill-all [runtime scope]"),
        what_it_does=(
            "terminates all saved services for the selected runtime state",
            "can optionally remove volumes when supported by the selected cleanup flags",
        ),
        flags=(
            "--backend|--frontend|--fullstack|--dependencies|--entire-system  choose cleanup scope",
            "--stop-all-remove-volumes / --remove-volumes  remove supported volumes too",
        ),
        examples=("envctl stop-all", "envctl kill-all", "envctl stop-all --entire-system --remove-volumes"),
        aliases=("kill-all", "killall", "stopall", "--stop-all", "--kill-all"),
        related=("stop", "blast-all", "show-state"),
    ),
    "blast-all": CommandHelpTopic(
        command="blast-all",
        summary="perform aggressive envctl cleanup for services, state, and optional volumes",
        usage=("envctl blast-all [--force] [volume flags]",),
        what_it_does=(
            "stops saved envctl processes and clears runtime state more aggressively than stop-all",
            "can include Docker ecosystem and volume cleanup depending on flags/config",
        ),
        flags=(
            "--force                         skip confirmation gates where supported",
            "--blast-remove-worktree-volumes remove worktree dependency volumes when supported",
            "--blast-keep-worktree-volumes   keep worktree dependency volumes",
            "--blast-remove-main-volumes     remove main dependency volumes when supported",
            "--blast-keep-main-volumes       keep main dependency volumes",
        ),
        examples=("envctl blast-all", "envctl blast-all --force", "envctl blast-all --blast-remove-worktree-volumes"),
        aliases=("blastall", "--blast-all"),
        related=("stop-all", "blast-worktree", "debug-pack"),
    ),
    "logs": CommandHelpTopic(
        command="logs",
        summary="print logs for saved envctl-managed services",
        usage=("envctl logs [--project <name>|--service <name>|--all] [--logs-follow]",),
        what_it_does=(
            "reads saved run artifacts and service log paths from runtime state",
            "prints selected service logs with optional following and color policy controls",
        ),
        flags=(
            "--project <name>        show logs for selected project/worktree",
            "--service <name>        show logs for a specific saved service",
            "--all                   show all available logs",
            "--logs-follow           follow logs where supported",
            "--logs-tail <n>         limit displayed log lines where supported",
            "--logs-no-color         disable log highlighting",
        ),
        examples=("envctl logs --all", "envctl logs --project feature-a-1 --logs-follow"),
        aliases=("l", "--logs"),
        related=("errors", "health", "show-state"),
    ),
    "clear-logs": CommandHelpTopic(
        command="clear-logs",
        summary="clear selected saved service log files",
        usage=("envctl clear-logs [--project <name>|--service <name>|--all]",),
        what_it_does=(
            "loads current runtime state and truncates/removes selected envctl-owned log artifacts",
            "keeps service state metadata intact while clearing noisy local logs",
        ),
        flags=("--project <name>", "--service <name>", "--all"),
        examples=("envctl clear-logs --project feature-a-1", "envctl clear-logs --all"),
        aliases=("logs-clear", "--clear-logs"),
        related=("logs", "errors"),
    ),
    "health": CommandHelpTopic(
        command="health",
        summary="summarize saved service health and status",
        usage=("envctl health [--project <name>|--service <name>|--all] [--json]",),
        what_it_does=(
            "loads saved state and prints running/healthy/stale/unreachable service status",
            "uses envctl's status glyph policy so failures are easy to scan in terminal output",
        ),
        flags=("--project <name>", "--service <name>", "--all", "--json"),
        examples=("envctl health --all", "envctl health --project feature-a-1", "envctl health --json"),
        aliases=("h", "--health"),
        related=("logs", "errors", "dashboard"),
    ),
    "errors": CommandHelpTopic(
        command="errors",
        summary="surface known service errors and warning/error log lines",
        usage=("envctl errors [--project <name>|--service <name>|--all]",),
        what_it_does=(
            "combines saved service failure metadata with log scanning for error/warning patterns",
            "helps triage startup/runtime problems without opening every raw log manually",
        ),
        flags=("--project <name>", "--service <name>", "--all", "--logs-tail <n>"),
        examples=("envctl errors --all", "envctl errors --project feature-a-1"),
        aliases=("e", "--errors"),
        related=("logs", "health", "debug-pack"),
    ),
    "test": CommandHelpTopic(
        command="test",
        summary="run configured backend/frontend/repository tests for selected targets",
        usage=("envctl test [--project <name>|--all|--failed|--untested] [test flags]",),
        what_it_does=(
            "runs configured test commands from .envctl for selected projects/worktrees",
            "parses test output, renders summaries, and tracks failed/untested suites for reruns",
        ),
        flags=(
            "--project <name>        test one project/worktree",
            "--all                   test every eligible target",
            "--failed                rerun previously failed suites where tracked",
            "--untested              run targets without recorded test evidence",
            "--test-parallel / --test-sequential  choose suite parallelism",
            "--frontend-test-runner <name>         select frontend runner integration",
        ),
        examples=("envctl test --project feature-a-1", "envctl test --all", "envctl test --failed"),
        aliases=("tests", "t", "--test", "--tests"),
        related=("health", "logs", "review"),
    ),
    "pr": CommandHelpTopic(
        command="pr",
        summary="create a pull request for the selected branch/worktree",
        usage=("envctl pr [--project <name>] [--pr-base <branch>]",),
        what_it_does=(
            "resolves the current branch, checks for an existing PR, and creates one with gh or repo helper scripts",
            "commits and pushes dirty worktree changes first using envctl commit behavior when needed",
            "uses MAIN_TASK.md or commit history to build a useful PR title/body unless explicit env is provided",
        ),
        flags=(
            "--project <name>        create PR for selected worktree/project",
            "--pr-base <branch>      set the target base branch",
            "--interactive           opt into prompts/selection instead of default headless action mode",
        ),
        examples=("envctl pr --project feature-a-1 --pr-base main", "envctl pr --main --pr-base main"),
        aliases=("prs", "p", "--pr", "--prs"),
        related=("commit", "review", "test"),
    ),
    "commit": CommandHelpTopic(
        command="commit",
        summary="commit normal repo changes while preserving envctl-local control artifacts",
        usage=("envctl commit [--project <name>|--main] [--commit-message <text>|--commit-message-file <path>]",),
        what_it_does=(
            "stages normal changed paths and intentionally skips protected envctl-local artifacts",
            "uses .envctl-commit-message.md after the Envctl pointer marker as the default message",
            "advances the commit-message pointer after a successful commit",
        ),
        flags=(
            "--commit-message <text>       use explicit commit message text",
            "--commit-message-file <path>  read commit message from a file",
            "--project <name>              commit inside selected worktree/project",
            "--main                        target the main checkout",
        ),
        examples=("envctl commit --main", "envctl commit --project feature-a-1 --commit-message-file /tmp/msg.md"),
        aliases=("c", "--commit"),
        related=("pr", "review"),
    ),
    "review": CommandHelpTopic(
        command="review",
        summary="generate a branch/worktree review bundle and diff summary",
        usage=("envctl review [--project <name>|--main] [--review-base <branch>]",),
        what_it_does=(
            "resolves a review base branch/ref, computes the branch diff, and writes a review bundle",
            "can scope analysis to backend/frontend when service flags are provided",
        ),
        flags=(
            "--review-base <branch>   override automatic base-branch resolution",
            "--project <name>         review a selected worktree/project",
            "--backend | --frontend   narrow review scope metadata where supported",
        ),
        examples=("envctl review --project feature-a-1", "envctl review --project feature-a-1 --review-base main"),
        aliases=("reviews", "analyze", "a", "v", "--review", "--analyze"),
        related=("test", "pr", "commit"),
    ),
    "migrate": CommandHelpTopic(
        command="migrate",
        summary="run backend database migrations for selected targets",
        usage=("envctl migrate [--project <name>|--main|--all]",),
        what_it_does=(
            "runs the configured/default backend migration command, usually Alembic upgrade head",
            "loads backend env files and reuses saved dependency URLs when a current run exists",
            "persists raw migration failure logs under envctl run artifacts",
        ),
        flags=(
            "--project <name>        migrate one worktree/project",
            "--main                  migrate the main checkout",
            "--all                   migrate all selected/discovered targets where supported",
        ),
        examples=("envctl migrate --project feature-a-1", "envctl migrate --main"),
        aliases=("migration", "migrations", "m", "--migrate"),
        related=("logs", "errors", "health"),
    ),
    "delete-worktree": CommandHelpTopic(
        command="delete-worktree",
        summary="remove selected envctl-managed implementation worktrees",
        usage=("envctl delete-worktree --project <name> [--yes]", "envctl delete-worktree --all --yes"),
        what_it_does=(
            "removes selected worktree directories and unregisters them from git worktree state",
            "keeps deletion explicit and target-driven in headless mode to prevent accidental cleanup",
        ),
        flags=("--project <name>", "--all", "--yes | --force"),
        examples=("envctl delete-worktree --project feature-a-1 --yes", "envctl delete-worktree --all --yes"),
        aliases=("delete-worktrees", "remove-worktrees", "--delete-worktree", "--remove-worktrees"),
        related=("blast-worktree", "ensure-worktree", "list-trees"),
    ),
    "blast-worktree": CommandHelpTopic(
        command="blast-worktree",
        summary="stop/clean selected worktrees more aggressively than delete-worktree",
        usage=("envctl blast-worktree --project <name> [--yes|--force]",),
        what_it_does=(
            "runs worktree-scoped cleanup before removal, including supported Docker/dependency cleanup",
            "is intended for stale or broken implementation worktrees that need stronger cleanup",
        ),
        flags=("--project <name>", "--all", "--yes | --force"),
        examples=("envctl blast-worktree --project feature-a-1 --yes",),
        aliases=("blast-worktrees", "blastworktree", "--blast-worktree"),
        related=("delete-worktree", "blast-all", "list-trees"),
    ),
    "self-destruct-worktree": CommandHelpTopic(
        command="self-destruct-worktree",
        summary="remove the current envctl-managed worktree from inside itself",
        usage=("envctl self-destruct-worktree [--yes|--force]",),
        what_it_does=(
            "identifies the current checkout as an envctl-managed worktree and schedules/removes it safely",
            "exists for implementation sessions that need to clean up their own worktree after merging",
        ),
        flags=("--yes | --force",),
        examples=("envctl self-destruct-worktree --yes",),
        aliases=("--self-destruct-worktree",),
        related=("delete-worktree", "blast-worktree"),
    ),
    "list-commands": CommandHelpTopic(
        command="list-commands",
        summary="print the supported runtime command inventory",
        usage=("envctl list-commands", "envctl list-commands --json"),
        what_it_does=(
            "prints every command known to the Python runtime router",
            "is useful for scripts, shell completion, and checking installed/runtime parity",
        ),
        flags=("--json",),
        examples=("envctl list-commands", "envctl list-commands --json"),
        aliases=("--list-commands",),
        related=("help",),
    ),
    "list-targets": CommandHelpTopic(
        command="list-targets",
        summary="list targetable projects for the selected mode",
        usage=("envctl list-targets [--main|--trees] [--json]",),
        what_it_does=(
            "discovers project/worktree targets without starting services",
            "in JSON mode includes ports, roots, selection hints, and running-state metadata where available",
        ),
        flags=("--main | --trees", "--json"),
        examples=("envctl list-targets --json", "envctl list-targets --trees"),
        aliases=("--list-targets",),
        related=("list-trees", "show-state", "test"),
    ),
    "list-trees": CommandHelpTopic(
        command="list-trees",
        summary="list envctl-managed implementation worktrees",
        usage=("envctl list-trees [--json]",),
        what_it_does=(
            "discovers tree-mode projects/worktrees without starting services",
            "helps choose --project values for test/pr/review/delete-worktree commands",
        ),
        flags=("--json",),
        examples=("envctl list-trees", "envctl list-trees --json"),
        aliases=("--list-trees",),
        related=("ensure-worktree", "delete-worktree", "plan"),
    ),
    "show-config": CommandHelpTopic(
        command="show-config",
        summary="print effective envctl configuration",
        usage=("envctl show-config [--json]",),
        what_it_does=(
            "shows the resolved configuration from defaults, environment, and repo-local .envctl",
            "helps debug service commands, ports, managed keys, profiles, and UI settings",
        ),
        flags=("--json",),
        examples=("envctl show-config --json", "envctl show-config"),
        aliases=("--show-config",),
        related=("config", "preflight", "explain-startup"),
    ),
    "show-state": CommandHelpTopic(
        command="show-state",
        summary="print saved envctl runtime state",
        usage=("envctl show-state [--main|--trees] [--json]",),
        what_it_does=(
            "loads the saved run state for the selected mode/scope",
            "shows run/session IDs, service records, ports, logs, and runtime map data where available",
        ),
        flags=("--main | --trees", "--json"),
        examples=("envctl show-state --json", "envctl show-state --trees --json"),
        aliases=("--show-state",),
        related=("dashboard", "health", "logs", "session"),
    ),
    "explain-startup": CommandHelpTopic(
        command="explain-startup",
        summary="explain what envctl would start and why",
        usage=("envctl explain-startup [--main|--trees] [runtime scope] [--json]",),
        what_it_does=(
            "evaluates startup mode, scopes, dependency enablement, configured commands, and reuse decisions",
            "helps diagnose why envctl will or will not start a service before running startup",
        ),
        flags=("--main | --trees", "--backend|--frontend|--fullstack|--dependencies|--entire-system", "--json"),
        examples=("envctl explain-startup --json", "envctl explain-startup --trees --backend --json"),
        aliases=("--explain-startup",),
        related=("preflight", "show-config", "start"),
    ),
    "preflight": CommandHelpTopic(
        command="preflight",
        summary="print startup readiness/preflight information",
        usage=("envctl preflight [--main|--trees] [--json]",),
        what_it_does=(
            "runs lightweight startup/readiness analysis without launching services",
            "emits the versioned envctl.preflight.v1 contract in JSON mode",
        ),
        flags=("--main | --trees", "--json"),
        examples=("envctl preflight --json", "envctl preflight --trees --json"),
        aliases=("--preflight",),
        related=("explain-startup", "doctor", "show-config"),
    ),
    "session": CommandHelpTopic(
        command="session",
        summary="inspect or operate on saved envctl terminal/session records",
        usage=("envctl session", "envctl session --json", "envctl session --command <attach|kill>"),
        what_it_does=(
            "lists known envctl-managed sessions and prints attach/kill guidance where available",
            "supports session cleanup/attach workflows used by AI plan-agent launches",
        ),
        flags=("--json", "--command <name>", "--session-id <id>"),
        examples=("envctl session", "envctl session --json"),
        aliases=("--session",),
        related=("plan", "codex-tmux", "dashboard"),
    ),
    "doctor": CommandHelpTopic(
        command="doctor",
        summary="run envctl diagnostics for runtime readiness and parity",
        usage=("envctl doctor [--json]", "envctl --doctor [--json]"),
        what_it_does=(
            "prints runtime paths, state health, parity/readiness status, and recent failures",
            "helps determine whether envctl itself is healthy before debugging app services",
        ),
        flags=("--json",),
        examples=("envctl doctor", "envctl --doctor --json"),
        aliases=("--doctor", "d"),
        related=("debug-pack", "debug-report", "preflight"),
    ),
    "debug-pack": CommandHelpTopic(
        command="debug-pack",
        summary="collect a debug bundle for the current/latest envctl run",
        usage=("envctl debug-pack [debug flags]",),
        what_it_does=(
            "captures state, runtime maps, event traces, logs, and diagnostic metadata into a bundle",
            "is the first command to run when a startup or service issue needs shareable evidence",
        ),
        flags=("--debug-capture <mode>", "--output-dir <path>", "--debug-auto-pack"),
        examples=("envctl debug-pack", "envctl debug-pack --output-dir /tmp/envctl-debug"),
        aliases=("--debug-pack", "--debug-ui-pack"),
        related=("debug-report", "debug-last", "doctor"),
    ),
    "debug-report": CommandHelpTopic(
        command="debug-report",
        summary="collect and summarize an envctl debug bundle",
        usage=("envctl debug-report",),
        what_it_does=(
            "creates a debug bundle, summarizes probable root causes, and prints next data needed",
            "is useful when you want a compact triage report instead of raw bundle paths only",
        ),
        examples=("envctl debug-report",),
        aliases=("--debug-report",),
        related=("debug-pack", "debug-last", "doctor"),
    ),
    "debug-last": CommandHelpTopic(
        command="debug-last",
        summary="print the path to the latest envctl debug bundle",
        usage=("envctl debug-last",),
        what_it_does=("looks up the latest debug bundle pointer and prints a terminal-friendly path",),
        examples=("envctl debug-last",),
        aliases=("--debug-last",),
        related=("debug-pack", "debug-report"),
    ),
    "install-prompts": CommandHelpTopic(
        command="install-prompts",
        summary="install envctl AI workflow presets for supported AI CLIs",
        usage=(
            "envctl install-prompts --cli <codex|claude|opencode|all> [--preset <name>|all] [--dry-run]",
            "envctl install-prompts --cli codex --preset implement_task --json",
        ),
        what_it_does=(
            "installs envctl AI workflow surfaces for selected CLI targets",
            "Codex installs envctl workflows as skills under ~/.codex/skills",
            "Claude/OpenCode install prompt/command files in their respective config roots",
        ),
        flags=(
            "--cli <targets>        comma-separated target CLIs or all",
            "--preset <name>|all    choose one built-in preset or all presets",
            "--dry-run              preview written paths without changing files",
            "--json                 machine-readable output, including Codex skill invocation guidance",
            "--yes | --force        approve overwrites without prompting",
        ),
        notes=(
            "envctl-managed plan launches submit the rendered workflow automatically; "
            "manual $envctl-* invocation is only for direct Codex/OMX use",
            "Codex skills are installed below ~/.codex/skills and can be edited by the user after installation",
        ),
        examples=(
            "envctl install-prompts --cli codex --preset implement_task",
            "envctl install-prompts --cli codex --preset implement_task --dry-run --json",
            "envctl install-prompts --cli claude,opencode --preset all",
        ),
        aliases=("--install-prompts",),
        related=("plan", "codex-tmux"),
    ),
    "codex-tmux": CommandHelpTopic(
        command="codex-tmux",
        summary="launch or reuse a repo-scoped tmux session for Codex",
        usage=("envctl codex-tmux [codex args...]", "envctl codex-tmux --dry-run [--json] [codex args...]"),
        what_it_does=(
            "creates or reuses a repo-scoped tmux session for Codex",
            "starts Codex with --dangerously-bypass-approvals-and-sandbox in that session",
            "attaches to the tmux session unless --dry-run is used",
        ),
        flags=(
            "--dry-run              show the session command without starting/attaching",
            "--json                 JSON output; supported only with --dry-run",
        ),
        notes=("extra Codex arguments are only applied when creating a new session",),
        examples=("envctl codex-tmux", "envctl codex-tmux review", "envctl codex-tmux --dry-run --json review"),
        aliases=("--codex-tmux",),
        related=("plan", "session", "install-prompts"),
    ),
    "ensure-worktree": CommandHelpTopic(
        command="ensure-worktree",
        summary="create or reuse one envctl-managed worktree without starting services",
        usage=("envctl ensure-worktree <selector> [--json]",),
        what_it_does=(
            "resolves one planning/worktree selector and ensures the corresponding worktree exists",
            "returns cheap automation-friendly metadata without launching runtime services",
        ),
        flags=("--json", "--reuse-existing-worktree", "--recreate-existing-worktree"),
        examples=("envctl ensure-worktree feature-a --json",),
        aliases=("--ensure-worktree",),
        related=("plan", "list-trees", "delete-worktree"),
    ),
    "migrate-hooks": CommandHelpTopic(
        command="migrate-hooks",
        summary="migrate legacy shell hooks into the Python hook entrypoint",
        usage=("envctl migrate-hooks [--force]",),
        what_it_does=(
            "writes the Python hook migration target and reports migrated/skipped legacy hooks",
            "helps projects move from legacy shell hook wiring to envctl's Python-owned hook path",
        ),
        flags=("--force",),
        examples=("envctl migrate-hooks", "envctl migrate-hooks --force"),
        aliases=("--migrate-hooks",),
        related=("doctor", "debug-pack"),
    ),
    "help": CommandHelpTopic(
        command="help",
        summary="print top-level or command-specific help",
        usage=("envctl --help", "envctl <command> --help", "envctl help <command>"),
        what_it_does=(
            "prints the full command map when no target command is provided",
            "prints focused command usage, flags, examples, aliases, and related commands when used after a command",
        ),
        examples=("envctl --help", "envctl pr --help", "envctl help pr", "envctl --plan --help"),
        aliases=("--help", "-h"),
        related=("list-commands",),
    ),
}
