from __future__ import annotations

# Compatibility facade: keep the historical module path as the launch module
# object so existing imports and private test patch paths keep affecting the
# globals used by plan-agent launch execution.
import sys

from envctl_engine.planning.plan_agent import launch as _launch  # envctl_engine.planning.plan_agent.launch

sys.modules[__name__] = _launch
