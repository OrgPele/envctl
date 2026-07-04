from __future__ import annotations

from envctl_engine.runtime.help_topic_rendering import CommandHelpTopic


ACTIONS_HELP_TOPICS: dict[str, CommandHelpTopic] = {
    "test": CommandHelpTopic(
        command="test",
        summary="run configured backend/frontend/repository tests for selected targets",
        usage=("envctl test [--project <name>|--all|--failed|--untested] [--ship-on-pass <message>] [test flags]",),
        what_it_does=(
            "runs configured test commands from .envctl for selected projects/worktrees",
            "parses test output, renders summaries, and tracks failed/untested suites for reruns",
            "auto-sizes pytest-xdist workers from free CPU cores when pytest-xdist is available",
        ),
        flags=(
            "--project <name>        test one project/worktree",
            "--all                   test every eligible target",
            "--failed                rerun previously failed suites where tracked",
            "--untested              run targets without recorded test evidence",
            "--test-parallel / --test-sequential  choose suite parallelism",
            "--test-parallel-max <n>              cap suite concurrency and pytest-xdist workers",
            "--frontend-test-runner <name>         select frontend runner integration",
            "--ship-on-pass <text>                 run envctl ship with this message after tests pass",
        ),
        examples=(
            "envctl test --project feature-a-1",
            "envctl test --all",
            "envctl test --failed",
            "envctl test --all --ship-on-pass 'Ship focused fix'",
        ),
        aliases=("tests", "t", "--test", "--tests"),
        related=("health", "logs", "review"),
    ),
    "test-focused": CommandHelpTopic(
        command="test-focused",
        summary="run focused validation commands for the current or selected project",
        usage=("envctl test-focused [--project <name>] [--dry-run] [--json] [--ship-on-pass <message>]",),
        what_it_does=(
            "collects changed files from git and maps common envctl code areas to focused test commands",
            "when run inside a generated worktree, infers that worktree without requiring --project",
            "includes reasons, confidence, ruff suggestions for touched Python paths, and full-gate guidance",
            "auto-sizes pytest-xdist workers from free CPU cores when pytest-xdist is available",
            "runs the focused commands by default in order and stops at the first failure",
        ),
        flags=(
            "--project <name>        plan validation for one project/worktree",
            "--dry-run               print the focused commands without executing them",
            "--json                  print the envctl.test_plan.v1 payload",
            "--test-parallel-max <n> cap pytest-xdist workers for this run",
            "--no-test-parallel      disable pytest-xdist auto-injection for this run",
            "--ship-on-pass <text>   run envctl ship with this message after focused tests pass",
        ),
        examples=(
            "envctl test-focused",
            "envctl test-focused --project feature-a-1",
            "envctl test-focused --ship-on-pass 'Ship focused fix'",
        ),
        aliases=("--test-focused",),
        related=("test", "ship", "commit"),
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
        summary="commit-only fallback that preserves envctl-local control artifacts",
        usage=("envctl commit [--project <name>|--main] [-m <text>|--commit-message-file <path>]",),
        what_it_does=(
            "use envctl ship for normal AI handoff; reserve commit for commit-only maintenance or fallback flows",
            "stages normal changed paths and intentionally skips protected envctl-local artifacts",
            "uses the inline -m/--commit-message text when provided",
            "falls back to .envctl-commit-message.md after the Envctl pointer marker when no message is provided",
            "advances the commit-message pointer after a successful fallback-ledger commit",
        ),
        flags=(
            "-m, --commit-message <text>   use explicit commit message text",
            "--commit-message-file <path>  read commit message from a file",
            "--project <name>              commit inside selected worktree/project",
            "--main                        target the main checkout",
        ),
        examples=(
            "envctl commit --main -m 'Ship focused fix'",
            "envctl commit --project feature-a-1 -m 'Ship feature'",
        ),
        aliases=("c", "--commit"),
        related=("pr", "review"),
    ),
    "ship": CommandHelpTopic(
        command="ship",
        summary="commit, push, create/update PR, and report GitHub checks for the current or selected target",
        usage=("envctl ship [--project <name>] [-m <text>] [--human]",),
        what_it_does=(
            "when run inside a generated worktree, infers that worktree without requiring --project",
            "owns the normal AI handoff flow instead of requiring separate commit, push, or PR commands",
            "reuses envctl commit behavior, including -m/--commit-message, fallback ledger messages, "
            "and protected local artifacts",
            "creates a PR when needed and reuses or updates an existing PR when one already exists",
            "predicts merge conflicts and returns conflicting files, messages, and resolution steps",
            "waits for target GitHub PR checks whose rendered names start with Tests and returns passed, "
            "failed, pending-timeout, no-checks-reported, "
            "or gh-unavailable status "
            "with failing_checks and pending_checks",
            "prints the structured envctl.ship.v1 JSON payload by default; --json is accepted as a compatibility no-op",
        ),
        flags=(
            "--project <name>        ship one worktree/project",
            "-m <text>              use explicit commit message text for the commit phase",
            "--json                  compatibility no-op; JSON is the default",
            "--human                 print compact terminal output instead of JSON",
        ),
        examples=(
            "envctl ship -m 'Ship focused fix'",
            "envctl ship --project feature-a-1 -m 'Ship feature'",
            "envctl ship -m 'Ship focused fix' --human",
        ),
        aliases=("--ship",),
        related=("test-focused", "commit", "pr"),
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
}
