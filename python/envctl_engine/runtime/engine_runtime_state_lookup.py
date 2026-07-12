from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from envctl_engine.state.lookup import call_state_loader


def try_load_existing_state(
    runtime: Any,
    *,
    mode: str | None = None,
    strict_mode_match: bool = False,
    project_names: Sequence[str] | None = None,
) -> object | None:
    state = call_state_loader(
        runtime.state_repository.load_latest,
        mode=mode,
        strict_mode_match=strict_mode_match,
        project_names=project_names,
    )
    if state is not None:
        runtime._emit(
            "state.fingerprint.after_reload",
            run_id=state.run_id,
            state_fingerprint=runtime._state_fingerprint(state),
        )
    return state


def state_matches_scope(runtime: Any, state: object) -> bool:
    metadata = getattr(state, "metadata", {})
    if not isinstance(metadata, dict):
        return True
    scope = metadata.get("repo_scope_id")
    if isinstance(scope, str) and scope:
        return scope == runtime.config.runtime_scope_id
    return True
