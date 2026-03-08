from __future__ import annotations

from typing import Any


def try_load_existing_state(
    runtime: Any,
    *,
    mode: str | None = None,
    strict_mode_match: bool = False,
) -> object | None:
    state = runtime.state_repository.load_latest(mode=mode, strict_mode_match=strict_mode_match)
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
