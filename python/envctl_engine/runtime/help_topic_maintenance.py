from __future__ import annotations

from envctl_engine.runtime.help_topic_rendering import CommandHelpTopic


MAINTENANCE_HELP_TOPICS: dict[str, CommandHelpTopic] = {
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
    "supabase-user": CommandHelpTopic(
        command="supabase-user",
        summary="manage Supabase Auth users through the Admin API",
        usage=(
            "envctl supabase-user sync [--mode main|trees] [--json] [--dry-run]",
            "envctl supabase-user list [--json]",
            "envctl supabase-user create <email> --password <password> [--metadata-json <json>]",
            "envctl supabase-user update <email|id> [--password <password>] [--metadata-json <json>]",
            "envctl supabase-user delete <email|id> --yes",
        ),
        what_it_does=(
            "uses the Supabase Auth Admin API with the service-role key from active managed state or explicit env",
            "syncs configured .envctl Auth users idempotently for local E2E credentials",
            "lists, creates, updates, shows, or deletes Auth users without direct auth.users SQL edits",
        ),
        flags=(
            "--mode main|trees        choose which saved managed Supabase state to inspect for connection details",
            "--json                   emit a stable machine-readable result",
            "--dry-run                preview sync/delete mutations where supported",
            "--email <email>          provide a target email when not passed positionally",
            "--password <password>    set a password for create/update",
            "--metadata-json <json>   set user_metadata object for create/update",
            "--app-metadata-json <json> set app_metadata object for create/update",
            "--yes | --headless       required for delete in non-JSON interactive paths",
        ),
        notes=(
            "The service-role key is never printed; errors redact secrets through the Admin client.",
            "Standalone commands require managed Supabase state or explicit SUPABASE_URL/service-role env.",
        ),
        examples=(
            "envctl supabase-user sync --headless --json",
            "envctl supabase-user list --json",
            "envctl supabase-user create e2e@example.test --password local-secret",
            "envctl supabase-user delete e2e@example.test --yes",
        ),
        aliases=("supabase-users", "auth-user", "--supabase-user", "--supabase-users", "--auth-user"),
        related=("start", "show-state", "health"),
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
