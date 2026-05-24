from __future__ import annotations

from typing import Any, Callable, Mapping


def noop_restore() -> None:
    return None


def install_action_spinner_status_bridge(
    *,
    runtime: Any,
    command: str,
    op_id: str,
    active_spinner: Any,
) -> Callable[[], None]:
    runtime_raw = runtime.raw_runtime

    def update_spinner(message: object) -> None:
        text = str(message).strip()
        if not text:
            return
        active_spinner.update(text)
        runtime.emit(
            "ui.spinner.lifecycle",
            component="action.command",
            command=command,
            op_id=op_id,
            state="update",
            message=text,
        )

    add_listener = getattr(runtime_raw, "add_emit_listener", None)
    if callable(add_listener):

        def listener(event_name: str, payload: Mapping[str, object]) -> None:
            if event_name != "ui.status":
                return
            update_spinner(payload.get("message", ""))

        remove = add_listener(listener)
        if callable(remove):
            return remove
        return noop_restore

    emit = getattr(runtime_raw, "_emit", None)
    if not callable(emit):
        return noop_restore

    def bridged_emit(event_name: str, **payload: object) -> None:
        emit(event_name, **payload)
        if event_name == "ui.status":
            update_spinner(payload.get("message", ""))

    try:
        setattr(runtime_raw, "_emit", bridged_emit)
    except Exception:
        return noop_restore

    def restore() -> None:
        try:
            setattr(runtime_raw, "_emit", emit)
        except Exception:
            return

    return restore
