from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .command_policy import apply_command_policy, apply_mode_token


class RouteError(ValueError):
    """Raised when CLI route parsing fails."""


def _unique_tokens(*, registry_name: str, tokens: tuple[str, ...]) -> set[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for token in tokens:
        if token in seen and token not in duplicates:
            duplicates.append(token)
            continue
        seen.add(token)
    if duplicates:
        joined = ", ".join(duplicates)
        raise RuntimeError(f"Duplicate tokens in {registry_name}: {joined}")
    return seen


def _unique_mapping(*, registry_name: str, pairs: tuple[tuple[str, str], ...]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    duplicates: list[str] = []
    for key, value in pairs:
        if key in mapping:
            if key not in duplicates:
                duplicates.append(key)
            continue
        mapping[key] = value
    if duplicates:
        joined = ", ".join(duplicates)
        raise RuntimeError(f"Duplicate keys in {registry_name}: {joined}")
    return mapping


MODE_TREE_TOKENS = {
    "--tree",
    "--tree=true",
    "--trees",
    "--trees=true",
    "tree=true",
    "trees=true",
    "TREE=true",
    "TREES=true",
}
MODE_MAIN_TOKENS = {"--main", "--main=true", "main=true", "MAIN=true"}
MODE_FORCE_MAIN_TOKENS = {
    "--tree=false",
    "--trees=false",
    "tree=false",
    "trees=false",
    "TREE=false",
    "TREES=false",
}
MODE_FORCE_TREES_TOKENS = {"main=false", "MAIN=false"}
MODE_FALSE_TOKENS = MODE_FORCE_MAIN_TOKENS.union(MODE_FORCE_TREES_TOKENS)

_BOOLEAN_FLAG_TOKENS = (
    "--all",
    "--untested",
    "--failed",
    "--load-state",
    "--command-resume",
    "--skip-startup",
    "--command-only",
    "--logs-follow",
    "--logs-no-color",
    "--dashboard-interactive",
    "--interactive",
    "--headless",
    "--batch",
    "--json",
    "--stdin-json",
    "--non-interactive",
    "--no-interactive",
    "-b",
    "-f",
    "--dry-run",
    "--yes",
    "--force",
    "--parallel-trees",
    "--test-parallel",
    "--service-parallel",
    "--service-prep-parallel",
    "--refresh-cache",
    "--fast",
    "--fast-startup",
    "--docker",
    "--stop-docker-on-exit",
    "--docker-temp",
    "--temp-docker",
    "--keep-plan",
    "--clear-port-state",
    "--clear-ports",
    "--clear-port-cache",
    "--debug-trace",
    "--debug-trace-no-xtrace",
    "--debug-trace-no-stdio",
    "--debug-trace-no-interactive",
    "--main-services-local",
    "--main-local",
    "--main-services-remote",
    "--main-remote",
    "--key-debug",
    "--debug-ui",
    "--debug-ui-deep",
    "--debug-ui-include-doctor",
    "--reuse-existing-worktree",
    "--setup-worktree-existing",
    "--recreate-existing-worktree",
    "--setup-worktree-recreate",
    "--seed-requirements-from-base",
    "--copy-db-storage",
    "--no-resume",
    "--no-auto-resume",
)
BOOLEAN_FLAGS = _unique_tokens(registry_name="BOOLEAN_FLAGS", tokens=_BOOLEAN_FLAG_TOKENS)

VALUE_FLAGS = {
    "--service",
    "--set",
    "--pr-base",
    "--review-base",
    "--commit-message",
    "--commit-message-file",
    "--analyze-mode",
    "--review-mode",
    "--logs-tail",
    "--logs-duration",
    "--parallel-trees-max",
    "--debug-trace-log",
    "--include-existing-worktrees",
    "--setup-include-worktrees",
    "--log-profile",
    "--log-level",
    "--backend-log-profile",
    "--backend-log-level",
    "--frontend-log-profile",
    "--frontend-log-level",
    "--frontend-test-runner",
    "--test-parallel-max",
    "--cli",
    "--preset",
    "--session-id",
    "--run-id",
    "--scope-id",
    "--output-dir",
    "--timeout",
    "--debug-capture",
    "--debug-auto-pack",
}

PAIR_FLAGS = {"--setup-worktrees", "--setup-worktree"}

SPECIAL_FLAGS = {
    "--blast-keep-worktree-volumes",
    "--blast-remove-worktree-volumes",
    "--blast-remove-main-volumes",
    "--blast-keep-main-volumes",
    "--stop-all-remove-volumes",
    "--remove-volumes",
    "--test-sequential",
    "--no-test-parallel",
    "--service-sequential",
    "--no-service-parallel",
    "--service-prep-sequential",
    "--no-service-prep-parallel",
}

_ENV_ASSIGNMENT_KEYS = {
    "FRONTEND_TEST_RUNNER",
    "frontend-test-runner",
    "PARALLEL_TREES_MAX",
    "parallel-trees-max",
    "RUN_SH_OPT_PARALLEL_TREES_MAX",
    "fresh",
    "FRESH",
    "resume",
    "RESUME",
    "docker",
    "DOCKER",
    "docker-temp",
    "DOCKER_TEMP",
    "force",
    "FORCE",
    "copy-db-storage",
    "COPY_DB_STORAGE",
    "seed-requirements-from-base",
    "SEED_REQUIREMENTS_FROM_BASE",
    "parallel-trees",
    "PARALLEL_TREES",
    "RUN_SH_OPT_PARALLEL_TREES",
    "test-parallel",
    "TEST_PARALLEL",
    "ENVCTL_ACTION_TEST_PARALLEL",
    "service-prep-parallel",
    "SERVICE_PREP_PARALLEL",
    "ENVCTL_SERVICE_PREP_PARALLEL",
    "test-parallel-max",
    "TEST_PARALLEL_MAX",
    "ENVCTL_ACTION_TEST_PARALLEL_MAX",
    "service-parallel",
    "SERVICE_PARALLEL",
    "ENVCTL_SERVICE_ATTACH_PARALLEL",
    "backend",
    "BACKEND",
    "frontend",
    "FRONTEND",
}

_COMMAND_ALIAS_PAIRS = (
    ("start", "start"),
    ("--plan", "plan"),
    ("plan", "plan"),
    ("parallel-plan", "plan"),
    ("--parallel-plan", "plan"),
    ("sequential-plan", "plan"),
    ("--sequential-plan", "plan"),
    ("--plan-selection", "plan"),
    ("--planning-envs", "plan"),
    ("--planning-prs", "plan"),
    ("--plan-parallel", "plan"),
    ("--plan-sequential", "plan"),
    ("--resume", "resume"),
    ("resume", "resume"),
    ("--list-commands", "list-commands"),
    ("--list-targets", "list-targets"),
    ("--list-trees", "list-trees"),
    ("list-trees", "list-trees"),
    ("--show-config", "show-config"),
    ("show-config", "show-config"),
    ("--show-state", "show-state"),
    ("show-state", "show-state"),
    ("--explain-startup", "explain-startup"),
    ("explain-startup", "explain-startup"),
    ("--help", "help"),
    ("-h", "help"),
    ("help", "help"),
    ("--doctor", "doctor"),
    ("--debug-pack", "debug-pack"),
    ("--debug-ui-pack", "debug-pack"),
    ("debug-pack", "debug-pack"),
    ("--debug-report", "debug-report"),
    ("debug-report", "debug-report"),
    ("--debug-last", "debug-last"),
    ("debug-last", "debug-last"),
    ("dashboard", "dashboard"),
    ("--dashboard", "dashboard"),
    ("config", "config"),
    ("--config", "config"),
    ("--init", "config"),
    ("doctor", "doctor"),
    ("--restart", "restart"),
    ("restart", "restart"),
    ("--stop", "stop"),
    ("stop", "stop"),
    ("s", "stop"),
    ("--stop-all", "stop-all"),
    ("stop-all", "stop-all"),
    ("stopall", "stop-all"),
    ("--blast-all", "blast-all"),
    ("blast-all", "blast-all"),
    ("blastall", "blast-all"),
    ("--logs", "logs"),
    ("logs", "logs"),
    ("l", "logs"),
    ("--clear-logs", "clear-logs"),
    ("clear-logs", "clear-logs"),
    ("logs-clear", "clear-logs"),
    ("--test", "test"),
    ("--tests", "test"),
    ("test", "test"),
    ("tests", "test"),
    ("t", "test"),
    ("--errors", "errors"),
    ("errors", "errors"),
    ("e", "errors"),
    ("--health", "health"),
    ("health", "health"),
    ("h", "health"),
    ("--delete-worktree", "delete-worktree"),
    ("--delete-worktrees", "delete-worktree"),
    ("--remove-worktrees", "delete-worktree"),
    ("delete-worktree", "delete-worktree"),
    ("delete-worktrees", "delete-worktree"),
    ("remove-worktrees", "delete-worktree"),
    ("--blast-worktree", "blast-worktree"),
    ("--blast-worktrees", "blast-worktree"),
    ("blast-worktree", "blast-worktree"),
    ("blast-worktrees", "blast-worktree"),
    ("blastworktree", "blast-worktree"),
    ("--pr", "pr"),
    ("--prs", "pr"),
    ("pr", "pr"),
    ("prs", "pr"),
    ("p", "pr"),
    ("--commit", "commit"),
    ("commit", "commit"),
    ("c", "commit"),
    ("--review", "review"),
    ("review", "review"),
    ("reviews", "review"),
    ("v", "review"),
    ("--analyze", "review"),
    ("analyze", "review"),
    ("a", "review"),
    ("--migrate", "migrate"),
    ("migrate", "migrate"),
    ("migration", "migrate"),
    ("migrations", "migrate"),
    ("m", "migrate"),
    ("migrate-hooks", "migrate-hooks"),
    ("--migrate-hooks", "migrate-hooks"),
    ("install-prompts", "install-prompts"),
    ("--install-prompts", "install-prompts"),
    ("dash", "dashboard"),
    ("d", "doctor"),
    ("r", "restart"),
)
COMMAND_ALIASES = _unique_mapping(registry_name="COMMAND_ALIASES", pairs=_COMMAND_ALIAS_PAIRS)

SUPPORTED_COMMANDS = sorted(
    {
        "start",
        "plan",
        "resume",
        "restart",
        "stop",
        "stop-all",
        "blast-all",
        "dashboard",
        "config",
        "doctor",
        "debug-pack",
        "debug-report",
        "debug-last",
        "test",
        "logs",
        "clear-logs",
        "health",
        "errors",
        "delete-worktree",
        "blast-worktree",
        "pr",
        "commit",
        "review",
        "migrate",
        "migrate-hooks",
        "install-prompts",
        "list-commands",
        "list-targets",
        "list-trees",
        "show-config",
        "show-state",
        "explain-startup",
        "help",
    }
)


@dataclass(slots=True)
class Route:
    command: str
    mode: str
    raw_args: list[str] = field(default_factory=list)
    passthrough_args: list[str] = field(default_factory=list)
    projects: list[str] = field(default_factory=list)
    flags: dict[str, object] = field(default_factory=dict)


def list_supported_commands() -> list[str]:
    return list(SUPPORTED_COMMANDS)


def list_supported_flag_tokens() -> list[str]:
    command_flags = {token for token in COMMAND_ALIASES if token.startswith("--")}
    mode_flags = {token for token in MODE_TREE_TOKENS.union(MODE_MAIN_TOKENS) if token.startswith("--")}
    explicit = {
        "--project",
        "--projects",
        "--command",
        "--action",
        "--no-parallel-trees",
        "--no-seed-requirements-from-base",
        "--no-copy-db-storage",
    }
    supported = (
        command_flags.union(mode_flags)
        .union(BOOLEAN_FLAGS)
        .union(VALUE_FLAGS)
        .union(PAIR_FLAGS)
        .union(SPECIAL_FLAGS)
        .union(explicit)
    )
    return sorted(supported)


@dataclass(slots=True)
class _ParserState:
    """Mutable state accumulated through pipeline phases."""

    env: Mapping[str, str]
    mode: str = ""
    command: str = "start"
    command_explicit: bool = False
    projects: list[str] = field(default_factory=list)
    passthrough: list[str] = field(default_factory=list)
    flags: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.mode:
            self.mode = _default_mode(self.env)


def parse_route(argv: list[str], env: Mapping[str, str]) -> Route:
    """Parse CLI arguments through staged declarative pipeline."""
    state = _ParserState(env)

    # Phase 1: Normalization - standardize token formats
    normalized = _phase_normalize(argv)

    # Phase 2: Classification - categorize each token
    classified = _phase_classify(normalized)

    # Phase 3: Command/Mode Resolution - determine command and mode
    _phase_resolve_command_mode(classified, state)

    # Phase 4: Flag Binding - extract and bind flags
    _phase_bind_flags(classified, state)

    # Phase 5: Route Finalization - build final Route object
    return _phase_finalize(state, argv)


def _phase_normalize(argv: list[str]) -> list[tuple[str, str]]:
    """Phase 1: Normalize tokens to (original, normalized) pairs."""
    normalized = []
    for token in argv:
        # Preserve original, create normalized form for matching
        norm = token.lower() if not token.startswith("-") else token
        normalized.append((token, norm))
    return normalized


def _phase_classify(normalized: list[tuple[str, str]]) -> list[dict[str, str | object]]:
    """Phase 2: Classify each token by type."""
    classified: list[dict[str, str | object]] = []
    i = 0
    while i < len(normalized):
        token, norm = normalized[i]
        token_type = _classify_token(token, norm)
        classified.append(
            {
                "original": token,
                "normalized": norm,
                "type": token_type,
                "index": i,
                "next_token": normalized[i + 1][0] if i + 1 < len(normalized) else None,
            }
        )
        i += 1
    return classified


def _classify_token(token: str, norm: str) -> str:
    """Classify token into category."""
    if (
        token in MODE_TREE_TOKENS
        or token in MODE_MAIN_TOKENS
        or token in MODE_FORCE_MAIN_TOKENS
        or token in MODE_FORCE_TREES_TOKENS
    ):
        return "mode"
    if token in {"--project", "--projects"} or token.startswith("--project=") or token.startswith("--projects="):
        return "project"
    if token in COMMAND_ALIASES:
        return "command"
    if token.startswith("--command=") or token.startswith("--action=") or token in {"--command", "--action"}:
        return "command_explicit"
    if token in BOOLEAN_FLAGS:
        return "boolean_flag"
    # Check for plan-related inline flags
    if (
        token.startswith("--plan=")
        or token.startswith("--plan-selection=")
        or token.startswith("--planning-envs=")
        or token.startswith("--planning-prs=")
        or token.startswith("--parallel-plan=")
        or token.startswith("--plan-parallel=")
        or token.startswith("--sequential-plan=")
        or token.startswith("--plan-sequential=")
    ):
        return "plan_flag"
    if token in VALUE_FLAGS or any(token.startswith(f"{f}=") for f in VALUE_FLAGS):
        return "value_flag"
    if token in PAIR_FLAGS or any(token.startswith(f"{f}=") for f in PAIR_FLAGS):
        return "pair_flag"
    if token in SPECIAL_FLAGS or token in {
        "--no-parallel-trees",
        "--no-seed-requirements-from-base",
        "--no-copy-db-storage",
    }:
        return "special_flag"
    # Env-style assignments (KEY=value, no leading dashes) - only known ones
    if "=" in token and not token.startswith("-"):
        # Check if it's a known env-style assignment
        key = token.split("=", 1)[0]
        if key in _ENV_ASSIGNMENT_KEYS:
            return "env_assignment"
        # Unknown env-style assignment - reject it
        return "unknown_env_assignment"
    if token.startswith("--"):
        return "unknown_option"
    if token.startswith("-"):
        return "short_option"
    return "positional"


def _phase_resolve_command_mode(classified: list[dict[str, str | object]], state: _ParserState) -> None:
    """Phase 3: Resolve command and mode from classified tokens."""
    for item in classified:
        token = str(item["original"])
        token_type = str(item["type"])

        # Mode resolution with precedence
        if token_type == "mode":
            state.mode = apply_mode_token(token, flags=state.flags, current_mode=state.mode)
            continue

        # Command resolution with precedence
        if token_type == "command":
            mapped = COMMAND_ALIASES.get(token)
            if mapped:
                state.command = mapped
                state.command_explicit = True
                forced_mode = apply_command_policy(state.flags, command=mapped, token=token)
                if forced_mode is not None:
                    state.mode = forced_mode
            continue

        if token_type == "command_explicit":
            if token.startswith("--command=") or token.startswith("--action="):
                command_token = token.split("=", 1)[1]
                mapped = COMMAND_ALIASES.get(command_token)
                if mapped is None:
                    raise RouteError(f"Unsupported command in Python runtime: {command_token}")
                state.command = mapped
                state.command_explicit = True
                forced_mode = apply_command_policy(state.flags, command=mapped, token=token)
                if forced_mode is not None:
                    state.mode = forced_mode
            continue


def _phase_bind_flags(classified: list[dict[str, str | object]], state: _ParserState) -> None:
    """Phase 4: Extract and bind flags from classified tokens."""
    i = 0
    while i < len(classified):
        item = classified[i]
        token = str(item["original"])
        token_type = str(item["type"])

        # Skip already-processed token types
        if token_type in {"mode", "command"}:
            i += 1
            continue

        # Project handling
        if token_type == "project":
            if token in {"--project", "--projects"}:
                next_token = _require_following_value(classified, i, token)
                state.projects.extend(_parse_projects(next_token))
                i += 2
            elif token.startswith("--project=") or token.startswith("--projects="):
                state.projects.extend(_parse_projects(token.split("=", 1)[1]))
                i += 1
            continue

        # Command explicit (--command/--action with value)
        if token_type == "command_explicit":
            if token in {"--command", "--action"}:
                command_token = _require_following_value(classified, i, token)
                mapped = COMMAND_ALIASES.get(command_token)
                if mapped is None:
                    raise RouteError(f"Unsupported command in Python runtime: {command_token}")
                state.command = mapped
                state.command_explicit = True
                forced_mode = apply_command_policy(state.flags, command=mapped, token=token)
                if forced_mode is not None:
                    state.mode = forced_mode
                i += 2
            else:
                i += 1
            continue

        # Boolean flags
        if token_type == "boolean_flag":
            state.flags[_boolean_flag_name(token)] = True
            i += 1
            continue

        # Value flags
        if token_type == "value_flag":
            if token in VALUE_FLAGS:
                next_token = _require_following_value(classified, i, token)
                _store_value_flag(state.flags, token, next_token)
                i += 2
            else:
                # Inline value flag (--flag=value)
                flag_name = token.split("=", 1)[0]
                flag_value = token.split("=", 1)[1]
                _store_value_flag(state.flags, flag_name, flag_value)
                i += 1
            continue

        # Pair flags
        if token_type == "pair_flag":
            if token in PAIR_FLAGS:
                first = _require_following_value(classified, i, token)
                second = _require_following_value(classified, i + 1, token)
                _store_pair_flag(state.flags, token, first, second)
                i += 3
            else:
                # Inline pair flag (--flag=val1,val2)
                raw = token.split("=", 1)[1]
                _store_inline_pair_flag(state.flags, token.split("=", 1)[0], raw)
                i += 1
            continue

        # Special flags
        if token_type == "special_flag":
            _handle_special_flag(state.flags, token)
            i += 1
            continue

        # Env-style assignments (KEY=value)
        if token_type == "env_assignment":
            _handle_env_assignment(state.flags, token)
            i += 1
            continue

        # Unknown options
        if token_type == "unknown_option":
            raise RouteError(f"Unknown option: {token}")

        # Positional args
        if token_type == "positional":
            if not state.command_explicit:
                raise RouteError(f"Unsupported command in Python runtime: {token}")
            state.passthrough.append(token)
            i += 1
            continue

        # Plan flags (inline plan commands)
        if token_type == "plan_flag":
            _handle_plan_flag(state, token)
            i += 1
            continue

        # Unknown env assignments
        if token_type == "unknown_env_assignment":
            raise RouteError(f"Unknown option: {token}")

        i += 1


def _require_following_value(classified: list[dict[str, str | object]], index: int, token: str) -> str:
    if index + 1 >= len(classified):
        raise RouteError(f"Missing value for {token}")
    next_token = str(classified[index + 1]["original"])
    if next_token.startswith("-"):
        raise RouteError(f"Missing value for {token}")
    return next_token


def _handle_special_flag(flags: dict[str, object], token: str) -> None:
    """Handle special flag tokens with specific semantics."""
    if token == "--blast-keep-worktree-volumes":
        flags["blast_keep_worktree_volumes"] = True
    elif token == "--blast-remove-worktree-volumes":
        flags["blast_keep_worktree_volumes"] = False
    elif token == "--blast-remove-main-volumes":
        flags["blast_remove_main_volumes"] = True
    elif token == "--blast-keep-main-volumes":
        flags["blast_remove_main_volumes"] = False
    elif token in {"--stop-all-remove-volumes", "--remove-volumes"}:
        flags["stop_all_remove_volumes"] = True
    elif token == "--no-parallel-trees":
        flags["parallel_trees"] = False
    elif token in {"--test-sequential", "--no-test-parallel"}:
        flags["test_parallel"] = False
    elif token in {"--service-sequential", "--no-service-parallel"}:
        flags["service_parallel"] = False
    elif token in {"--service-prep-sequential", "--no-service-prep-parallel"}:
        flags["service_prep_parallel"] = False
    elif token in {"--no-seed-requirements-from-base", "--no-copy-db-storage"}:
        flags["seed_requirements_from_base"] = False
    elif token in {"fresh=true", "FRESH=true"}:
        flags["fresh"] = True
    elif token in {"resume=true", "RESUME=true"}:
        # Handled in command resolution
        pass
    elif token in {"docker=true", "DOCKER=true"}:
        flags["docker"] = True
    elif token in {"docker-temp=true", "DOCKER_TEMP=true"}:
        flags["docker_temp"] = True
    elif token in {"force=true", "FORCE=true"}:
        flags["force"] = True
    elif token in {
        "copy-db-storage=true",
        "COPY_DB_STORAGE=true",
        "seed-requirements-from-base=true",
        "SEED_REQUIREMENTS_FROM_BASE=true",
    }:
        flags["seed_requirements_from_base"] = True
    elif token in {
        "copy-db-storage=false",
        "COPY_DB_STORAGE=false",
        "seed-requirements-from-base=false",
        "SEED_REQUIREMENTS_FROM_BASE=false",
    }:
        flags["seed_requirements_from_base"] = False
    elif token in {"parallel-trees=true", "PARALLEL_TREES=true", "RUN_SH_OPT_PARALLEL_TREES=true"}:
        flags["parallel_trees"] = True
    elif token in {"parallel-trees=false", "PARALLEL_TREES=false", "RUN_SH_OPT_PARALLEL_TREES=false"}:
        flags["parallel_trees"] = False
    elif (
        token.startswith("parallel-trees-max=")
        or token.startswith("PARALLEL_TREES_MAX=")
        or token.startswith("RUN_SH_OPT_PARALLEL_TREES_MAX=")
    ):
        flags["parallel_trees_max"] = token.split("=", 1)[1]
    elif token.startswith("frontend-test-runner=") or token.startswith("FRONTEND_TEST_RUNNER="):
        flags["frontend_test_runner"] = token.split("=", 1)[1]


def _handle_env_assignment(flags: dict[str, object], token: str) -> None:
    """Handle env-style assignments (KEY=value, no leading dashes)."""
    key, value = token.split("=", 1)
    lowered = value.lower()
    if key in {"FRONTEND_TEST_RUNNER", "frontend-test-runner"}:
        flags["frontend_test_runner"] = value
        return
    if key in {"test-parallel-max", "TEST_PARALLEL_MAX", "ENVCTL_ACTION_TEST_PARALLEL_MAX"}:
        flags["test_parallel_max"] = value
        return
    if key in {"PARALLEL_TREES_MAX", "parallel-trees-max", "RUN_SH_OPT_PARALLEL_TREES_MAX"}:
        flags["parallel_trees_max"] = value
        return
    if key in {"fresh", "FRESH"} and lowered == "true":
        flags["fresh"] = True
        return
    if key in {"resume", "RESUME"} and lowered == "true":
        flags["resume"] = True
        return
    if key in {"docker", "DOCKER"} and lowered == "true":
        flags["docker"] = True
        return
    if key in {"docker-temp", "DOCKER_TEMP"} and lowered == "true":
        flags["docker_temp"] = True
        return
    if key in {"force", "FORCE"} and lowered == "true":
        flags["force"] = True
        return
    if key in {"backend", "BACKEND"}:
        if lowered in {"true", "1", "yes", "on"}:
            flags["backend"] = True
        elif lowered in {"false", "0", "no", "off"}:
            flags["backend"] = False
        return
    if key in {"test-parallel", "TEST_PARALLEL", "ENVCTL_ACTION_TEST_PARALLEL"}:
        if lowered in {"true", "1", "yes", "on"}:
            flags["test_parallel"] = True
        elif lowered in {"false", "0", "no", "off"}:
            flags["test_parallel"] = False
        return
    if key in {"service-parallel", "SERVICE_PARALLEL", "ENVCTL_SERVICE_ATTACH_PARALLEL"}:
        if lowered in {"true", "1", "yes", "on"}:
            flags["service_parallel"] = True
        elif lowered in {"false", "0", "no", "off"}:
            flags["service_parallel"] = False
        return
    if key in {"service-prep-parallel", "SERVICE_PREP_PARALLEL", "ENVCTL_SERVICE_PREP_PARALLEL"}:
        if lowered in {"true", "1", "yes", "on"}:
            flags["service_prep_parallel"] = True
        elif lowered in {"false", "0", "no", "off"}:
            flags["service_prep_parallel"] = False
        return
    if key in {"frontend", "FRONTEND"}:
        if lowered in {"true", "1", "yes", "on"}:
            flags["frontend"] = True
        elif lowered in {"false", "0", "no", "off"}:
            flags["frontend"] = False
        return
    if key in {"copy-db-storage", "COPY_DB_STORAGE", "seed-requirements-from-base", "SEED_REQUIREMENTS_FROM_BASE"}:
        if lowered == "true":
            flags["seed_requirements_from_base"] = True
        elif lowered == "false":
            flags["seed_requirements_from_base"] = False
        return
    if key in {"parallel-trees", "PARALLEL_TREES", "RUN_SH_OPT_PARALLEL_TREES"}:
        lowered = value.lower()
        if lowered == "true":
            flags["parallel_trees"] = True
        elif lowered == "false":
            flags["parallel_trees"] = False


def _handle_plan_flag(state: _ParserState, token: str) -> None:
    """Handle plan-related inline flags."""
    state.command = "plan"
    state.command_explicit = True
    state.mode = "trees"

    # Extract value if present
    if "=" in token:
        value = token.split("=", 1)[1].strip()
        if value:
            state.passthrough.extend(_parse_projects(value))

    # Set flags based on token type
    if "sequential" in token:
        state.flags["sequential"] = True
        state.flags["parallel_trees"] = False
    if "parallel" in token:
        state.flags["parallel_trees"] = True
    if "planning-prs" in token or "planning_prs" in token:
        state.flags["planning_prs"] = True


def _phase_finalize(state: _ParserState, raw_argv: list[str]) -> Route:
    """Phase 5: Build final Route object."""
    return Route(
        command=state.command,
        mode=state.mode,
        raw_args=list(raw_argv),
        passthrough_args=state.passthrough,
        projects=state.projects,
        flags=state.flags,
    )


def _default_mode(env: Mapping[str, str]) -> str:
    raw = (env.get("ENVCTL_DEFAULT_MODE", "main") or "main").strip().lower()
    if raw in {"main", "trees"}:
        return raw
    raise RouteError(f"Invalid ENVCTL_DEFAULT_MODE: {raw}")


def _parse_projects(raw: str) -> list[str]:
    values = [part.strip() for part in raw.split(",")]
    return [value for value in values if value]


def _boolean_flag_name(token: str) -> str:
    mapping = {
        "--all": "all",
        "--untested": "untested",
        "--failed": "failed",
        "--load-state": "load_state",
        "--command-resume": "load_state",
        "--skip-startup": "skip_startup",
        "--command-only": "skip_startup",
        "--logs-follow": "logs_follow",
        "--logs-no-color": "logs_no_color",
        "--dashboard-interactive": "dashboard_interactive",
        "--interactive": "interactive",
        "--headless": "batch",
        "--batch": "batch",
        "--json": "json",
        "--stdin-json": "stdin_json",
        "--non-interactive": "batch",
        "--no-interactive": "batch",
        "-b": "batch",
        "-f": "force",
        "--dry-run": "dry_run",
        "--yes": "yes",
        "--force": "force",
        "--parallel-trees": "parallel_trees",
        "--test-parallel": "test_parallel",
        "--service-parallel": "service_parallel",
        "--service-prep-parallel": "service_prep_parallel",
        "--refresh-cache": "refresh_cache",
        "--fast": "fast",
        "--fast-startup": "fast",
        "--docker": "docker",
        "--stop-docker-on-exit": "docker_temp",
        "--docker-temp": "docker_temp",
        "--temp-docker": "docker_temp",
        "--keep-plan": "keep_plan",
        "--clear-port-state": "clear_port_state",
        "--clear-ports": "clear_port_state",
        "--clear-port-cache": "clear_port_state",
        "--debug-trace": "debug_trace",
        "--debug-trace-no-xtrace": "debug_trace_no_xtrace",
        "--debug-trace-no-stdio": "debug_trace_no_stdio",
        "--debug-trace-no-interactive": "debug_trace_no_interactive",
        "--main-services-local": "main_services_local",
        "--main-local": "main_services_local",
        "--main-services-remote": "main_services_remote",
        "--main-remote": "main_services_remote",
        "--key-debug": "key_debug",
        "--debug-ui": "debug_ui",
        "--debug-ui-deep": "debug_ui_deep",
        "--debug-ui-include-doctor": "debug_ui_include_doctor",
        "--reuse-existing-worktree": "setup_worktree_existing",
        "--setup-worktree-existing": "setup_worktree_existing",
        "--recreate-existing-worktree": "setup_worktree_recreate",
        "--setup-worktree-recreate": "setup_worktree_recreate",
        "--seed-requirements-from-base": "seed_requirements_from_base",
        "--copy-db-storage": "seed_requirements_from_base",
        "--no-resume": "no_resume",
        "--no-auto-resume": "no_resume",
    }
    return mapping[token]


def _store_value_flag(flags: dict[str, object], token: str, value: str) -> None:
    mapping = {
        "--service": "services",
        "--set": "set_values",
        "--pr-base": "pr_base",
        "--review-base": "review_base",
        "--commit-message": "commit_message",
        "--commit-message-file": "commit_message_file",
        "--analyze-mode": "analyze_mode",
        "--review-mode": "analyze_mode",
        "--logs-tail": "logs_tail",
        "--logs-duration": "logs_duration",
        "--parallel-trees-max": "parallel_trees_max",
        "--debug-trace-log": "debug_trace_log",
        "--include-existing-worktrees": "include_existing_worktrees",
        "--setup-include-worktrees": "include_existing_worktrees",
        "--log-profile": "log_profile",
        "--log-level": "log_level",
        "--backend-log-profile": "backend_log_profile",
        "--backend-log-level": "backend_log_level",
        "--frontend-log-profile": "frontend_log_profile",
        "--frontend-log-level": "frontend_log_level",
        "--frontend-test-runner": "frontend_test_runner",
        "--test-parallel-max": "test_parallel_max",
        "--cli": "cli",
        "--preset": "preset",
        "--session-id": "session_id",
        "--run-id": "run_id",
        "--scope-id": "scope_id",
        "--output-dir": "output_dir",
        "--timeout": "timeout",
        "--debug-capture": "debug_capture",
        "--debug-auto-pack": "debug_auto_pack",
    }
    key = mapping[token]
    if key in {"services", "include_existing_worktrees", "set_values"}:
        existing = flags.get(key)
        values = [value] if key == "set_values" else _parse_projects(value)
        if isinstance(existing, list):
            existing.extend(values)
            return
        flags[key] = values
        return
    flags[key] = value


def _store_pair_flag(flags: dict[str, object], token: str, first: str, second: str) -> None:
    key = "setup_worktrees" if token == "--setup-worktrees" else "setup_worktree"
    entry = {"feature": first, "count": second} if key == "setup_worktrees" else {"feature": first, "iteration": second}
    existing = flags.get(key)
    if isinstance(existing, list):
        existing.append(entry)
        return
    flags[key] = [entry]


def _store_inline_pair_flag(flags: dict[str, object], token: str, raw: str) -> None:
    parts = [part.strip() for part in raw.split(",", 1)]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise RouteError(f"Missing value for {token}")
    _store_pair_flag(flags, token, parts[0], parts[1])
