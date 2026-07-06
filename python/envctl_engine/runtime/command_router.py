from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from envctl_engine.runtime.command_flag_storage import (
    boolean_flag_name,
    parse_projects,
    store_inline_pair_flag,
    store_pair_flag,
    store_value_flag,
)
from envctl_engine.runtime.command_catalog import (
    BOOLEAN_FLAGS as BOOLEAN_FLAGS,
    COMMAND_ALIASES as COMMAND_ALIASES,
    DEFAULT_HEADLESS_COMMANDS as DEFAULT_HEADLESS_COMMANDS,
    MODE_FALSE_TOKENS as MODE_FALSE_TOKENS,
    MODE_FORCE_MAIN_TOKENS as MODE_FORCE_MAIN_TOKENS,
    MODE_FORCE_TREES_TOKENS as MODE_FORCE_TREES_TOKENS,
    MODE_MAIN_TOKENS as MODE_MAIN_TOKENS,
    MODE_TREE_TOKENS as MODE_TREE_TOKENS,
    PAIR_FLAGS as PAIR_FLAGS,
    SPECIAL_FLAGS as SPECIAL_FLAGS,
    SUPPORTED_COMMANDS as SUPPORTED_COMMANDS,
    VALUE_FLAGS as VALUE_FLAGS,
    _BOOLEAN_FLAG_TOKENS as _BOOLEAN_FLAG_TOKENS,
    _COMMAND_ALIAS_PAIRS as _COMMAND_ALIAS_PAIRS,
    _ENV_ASSIGNMENT_KEYS as _ENV_ASSIGNMENT_KEYS,
    list_supported_commands as list_supported_commands,
    list_supported_flag_tokens as list_supported_flag_tokens,
)
from envctl_engine.runtime.command_models import Route, RouteError
from envctl_engine.runtime.command_policy import apply_command_policy, apply_mode_token
from envctl_engine.runtime.command_special_flags import (
    apply_default_dependency_scope_policy,
    apply_default_headless_policy,
    apply_default_runtime_scope_policy,
    handle_command_scoped_flag,
    handle_env_assignment,
    passthrough_after_command,
    handle_special_flag,
    set_dependency_scope,
    set_runtime_scope,
    validate_dependency_scope_flags,
    validate_plan_agent_cli_flags,
    validate_plan_agent_workflow_flags,
)


@dataclass(slots=True)
class _ParserState:
    """Mutable state accumulated through pipeline phases."""

    env: Mapping[str, str]
    mode: str = ""
    command: str = "start"
    command_explicit: bool = False
    explain_startup_requested: bool = False
    projects: list[str] = field(default_factory=list)
    passthrough: list[str] = field(default_factory=list)
    flags: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.mode:
            self.mode = _default_mode(self.env)


def parse_route(argv: list[str], env: Mapping[str, str]) -> Route:
    """Parse CLI arguments through staged declarative pipeline."""
    state = _ParserState(env)

    argv, passthrough_after_separator = _split_passthrough_separator(argv)

    # Phase 1: Normalization - standardize token formats
    normalized = _phase_normalize(argv)

    # Phase 2: Classification - categorize each token
    classified = _phase_classify(normalized)

    # Phase 3: Command/Mode Resolution - determine command and mode
    _phase_resolve_command_mode(classified, state)
    if state.command == "pr-preview-controller":
        state.passthrough.extend(passthrough_after_command(argv, "pr-preview-controller", COMMAND_ALIASES))
        state.passthrough.extend(passthrough_after_separator)
        return _phase_finalize(state, argv)

    # Phase 4: Flag Binding - extract and bind flags
    _phase_bind_flags(classified, state)
    state.passthrough.extend(passthrough_after_separator)
    _apply_mode_override_flag(state)
    _apply_default_runtime_scope_policy(state)
    _apply_default_headless_policy(state)
    _apply_default_dependency_scope_policy(state)
    _validate_plan_agent_cli_flags(state)
    _validate_plan_agent_workflow_flags(state)
    _validate_import_branch_argument(state)
    _validate_dependency_scope_flags(state)

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


def _split_passthrough_separator(argv: list[str]) -> tuple[list[str], list[str]]:
    if "--" not in argv:
        return list(argv), []
    index = argv.index("--")
    return list(argv[:index]), list(argv[index + 1 :])


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
        or token.startswith("--import=")
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
                if state.command == "help":
                    continue
                if mapped == "help":
                    state.command = "help"
                    state.command_explicit = True
                    continue
                if mapped == "explain-startup":
                    state.explain_startup_requested = True
                if mapped == "explain-startup" or not state.explain_startup_requested:
                    state.command = mapped
                state.command_explicit = True
                forced_mode = apply_command_policy(state.flags, command=mapped, token=token)
                if forced_mode is not None:
                    state.mode = forced_mode
            continue

        if token_type == "command_explicit":
            if state.command == "help":
                continue
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
            if state.command == "help":
                i += 2 if token in {"--command", "--action"} else 1
                continue
            if token in {"--command", "--action"}:
                command_token = _require_following_value(classified, i, token)
                mapped = COMMAND_ALIASES.get(command_token)
                if mapped is None:
                    raise RouteError(f"Unsupported command in Python runtime: {command_token}")
                if mapped == "explain-startup":
                    state.explain_startup_requested = True
                if mapped == "explain-startup" or not state.explain_startup_requested:
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

        if token_type == "unknown_option" and handle_command_scoped_flag(state.command, state.flags, token):
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
    handle_special_flag(flags, token)


def _set_runtime_scope(flags: dict[str, object], scope: str) -> None:
    set_runtime_scope(flags, scope)


def _apply_default_runtime_scope_policy(state: _ParserState) -> None:
    apply_default_runtime_scope_policy(state.command, flags=state.flags, projects=state.projects)


def _apply_default_dependency_scope_policy(state: _ParserState) -> None:
    apply_default_dependency_scope_policy(state.mode, flags=state.flags, env=state.env)


def _set_dependency_scope(flags: dict[str, object], scope: str) -> None:
    set_dependency_scope(flags, scope)


def _validate_dependency_scope_flags(state: _ParserState) -> None:
    validate_dependency_scope_flags(state.mode, flags=state.flags, sets_up_worktrees=_route_sets_up_worktrees(state))


def _route_sets_up_worktrees(state: _ParserState) -> bool:
    return "setup_worktrees" in state.flags or "setup_worktree" in state.flags


def _handle_env_assignment(flags: dict[str, object], token: str) -> None:
    handle_env_assignment(flags, token)


def _handle_plan_flag(state: _ParserState, token: str) -> None:
    """Handle plan-related inline flags."""
    if token.startswith("--import="):
        state.command = "import"
        state.command_explicit = True
        state.mode = "trees"
        value = token.split("=", 1)[1].strip()
        if not value:
            raise RouteError("--import requires a remote branch argument.")
        state.passthrough.extend(_parse_projects(value))
        return

    if not state.explain_startup_requested:
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


def _validate_import_branch_argument(state: _ParserState) -> None:
    if state.command != "import":
        return


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


def _apply_mode_override_flag(state: _ParserState) -> None:
    mode_override = state.flags.get("mode_override")
    if isinstance(mode_override, str) and mode_override in {"main", "trees"}:
        state.mode = mode_override


def _apply_default_headless_policy(state: _ParserState) -> None:
    apply_default_headless_policy(state.command, state.flags)


def _validate_plan_agent_cli_flags(state: _ParserState) -> None:
    validate_plan_agent_cli_flags(state.flags)


def _validate_plan_agent_workflow_flags(state: _ParserState) -> None:
    validate_plan_agent_workflow_flags(state.flags)


def _default_mode(env: Mapping[str, str]) -> str:
    raw = (env.get("ENVCTL_DEFAULT_MODE", "main") or "main").strip().lower()
    if raw in {"main", "trees"}:
        return raw
    raise RouteError(f"Invalid ENVCTL_DEFAULT_MODE: {raw}")


def _parse_projects(raw: str) -> list[str]:
    return parse_projects(raw)


def _boolean_flag_name(token: str) -> str:
    return boolean_flag_name(token)


def _store_value_flag(flags: dict[str, object], token: str, value: str) -> None:
    store_value_flag(flags, token, value)


def _store_pair_flag(flags: dict[str, object], token: str, first: str, second: str) -> None:
    store_pair_flag(flags, token, first, second)


def _store_inline_pair_flag(flags: dict[str, object], token: str, raw: str) -> None:
    store_inline_pair_flag(flags, token, raw)
