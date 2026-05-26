from __future__ import annotations

from envctl_engine.runtime.command_alias_catalog import (
    COMMAND_ALIASES as COMMAND_ALIASES,
    SUPPORTED_COMMANDS as SUPPORTED_COMMANDS,
    _COMMAND_ALIAS_PAIRS as _COMMAND_ALIAS_PAIRS,
    list_supported_commands as list_supported_commands,
)
from envctl_engine.runtime.command_flag_catalog import (
    BOOLEAN_FLAGS as BOOLEAN_FLAGS,
    MODE_FALSE_TOKENS as MODE_FALSE_TOKENS,
    MODE_FORCE_MAIN_TOKENS as MODE_FORCE_MAIN_TOKENS,
    MODE_FORCE_TREES_TOKENS as MODE_FORCE_TREES_TOKENS,
    MODE_MAIN_TOKENS as MODE_MAIN_TOKENS,
    MODE_TREE_TOKENS as MODE_TREE_TOKENS,
    PAIR_FLAGS as PAIR_FLAGS,
    SPECIAL_FLAGS as SPECIAL_FLAGS,
    VALUE_FLAGS as VALUE_FLAGS,
    _BOOLEAN_FLAG_TOKENS as _BOOLEAN_FLAG_TOKENS,
    _ENV_ASSIGNMENT_KEYS as _ENV_ASSIGNMENT_KEYS,
    list_supported_flag_tokens as list_supported_flag_tokens,
)
from envctl_engine.runtime.command_policy import (
    ACTION_COMMANDS,
    LIFECYCLE_CLEANUP_COMMANDS,
    STATE_ACTION_COMMANDS,
)

DEFAULT_HEADLESS_COMMANDS = ACTION_COMMANDS | LIFECYCLE_CLEANUP_COMMANDS | STATE_ACTION_COMMANDS
