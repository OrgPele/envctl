from __future__ import annotations

from envctl_engine.runtime.help_topic_lifecycle import (
    LIFECYCLE_HELP_TOPICS,
)
from envctl_engine.runtime.help_topic_planning import (
    PLANNING_HELP_TOPICS,
)
from envctl_engine.runtime.help_topic_actions import (
    ACTIONS_HELP_TOPICS,
)
from envctl_engine.runtime.help_topic_inspection import (
    INSPECTION_HELP_TOPICS,
)
from envctl_engine.runtime.help_topic_maintenance import (
    MAINTENANCE_HELP_TOPICS,
)
from envctl_engine.runtime.help_topic_rendering import CommandHelpTopic


COMMAND_HELP_TOPICS: dict[str, CommandHelpTopic] = {
    **LIFECYCLE_HELP_TOPICS,
    **PLANNING_HELP_TOPICS,
    **ACTIONS_HELP_TOPICS,
    **INSPECTION_HELP_TOPICS,
    **MAINTENANCE_HELP_TOPICS,
}
