from __future__ import annotations

from envctl_engine.runtime.help_topic_rendering import CommandHelpTopic


LIFECYCLE_HELP_TOPICS: dict[str, CommandHelpTopic] = {
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
            "--shared-deps|--isolated-deps  choose tree dependency source",
            "--only-backend|--only-frontend|--no-deps|--no-infra  reduce startup/plan launch scope",
            "--deps-parallel|--parallel-deps  force managed dependencies to start concurrently",
            "--deps-sequential|--sequential-deps  force managed dependencies to start one at a time",
            "--project <name>        limit startup to selected project/worktree when supported",
            "--no-resume             skip automatic resume of a compatible saved run",
        ),
        examples=(
            "envctl",
            "envctl start --main --headless",
            "envctl start --trees --entire-system --headless",
            "envctl start --project feature-a-1 --backend --headless",
            "envctl --trees --only-backend --headless",
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
}
