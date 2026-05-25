from __future__ import annotations

from collections.abc import Mapping

from envctl_engine.runtime_feature_action_command_definitions import ACTION_COMMAND_DEFINITIONS
from envctl_engine.runtime_feature_cli_command_definitions import CLI_COMMAND_DEFINITIONS
from envctl_engine.runtime_feature_diagnostic_command_definitions import DIAGNOSTIC_COMMAND_DEFINITIONS
from envctl_engine.runtime_feature_definition_schema import FeatureDefinition
from envctl_engine.runtime_feature_inspection_command_definitions import INSPECTION_COMMAND_DEFINITIONS
from envctl_engine.runtime_feature_lifecycle_command_definitions import LIFECYCLE_COMMAND_DEFINITIONS
from envctl_engine.runtime_feature_planning_command_definitions import PLANNING_COMMAND_DEFINITIONS


_COMMAND_DEFINITION_SOURCES: tuple[Mapping[str, FeatureDefinition], ...] = (
    LIFECYCLE_COMMAND_DEFINITIONS,
    PLANNING_COMMAND_DEFINITIONS,
    ACTION_COMMAND_DEFINITIONS,
    INSPECTION_COMMAND_DEFINITIONS,
    CLI_COMMAND_DEFINITIONS,
    DIAGNOSTIC_COMMAND_DEFINITIONS,
)

_COMMAND_DEFINITION_BY_NAME: dict[str, FeatureDefinition] = {}
for _definitions in _COMMAND_DEFINITION_SOURCES:
    _COMMAND_DEFINITION_BY_NAME.update(_definitions)

_COMMAND_ORDER = tuple(
    "start plan resume restart stop stop-all blast-all delete-worktree blast-worktree "
    "self-destruct-worktree test test-focused pr commit ship review migrate logs clear-logs "
    "health errors show-config show-state explain-startup preflight dashboard config doctor "
    "migrate-hooks debug-pack debug-report debug-last help list-commands install-prompts "
    "codex-tmux ensure-worktree supabase-user endpoints qa-user playwright session list-targets "
    "list-trees".split()
)

COMMAND_DEFINITIONS: dict[str, FeatureDefinition] = {name: _COMMAND_DEFINITION_BY_NAME[name] for name in _COMMAND_ORDER}
