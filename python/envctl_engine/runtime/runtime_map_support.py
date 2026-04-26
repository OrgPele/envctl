from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from envctl_engine.runtime.network_exposure import resolve_network_exposure
from envctl_engine.state.models import RunState
from envctl_engine.state.runtime_map import build_runtime_map


def runtime_url_host_for_runtime(runtime: Any) -> str:
    config = getattr(runtime, "config", None)
    config_raw = getattr(config, "raw", {}) if config is not None else {}
    env = getattr(runtime, "env", {})
    exposure = resolve_network_exposure(
        env if isinstance(env, Mapping) else {},
        config_raw if isinstance(config_raw, Mapping) else {},
    )
    return exposure.url_host


def runtime_map_builder_for_runtime(runtime: Any) -> Callable[[RunState], dict[str, object]]:
    url_host = runtime_url_host_for_runtime(runtime)

    def build(state: RunState) -> dict[str, object]:
        return build_runtime_map(state, host=url_host)

    return build
