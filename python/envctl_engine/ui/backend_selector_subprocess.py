from __future__ import annotations

from contextlib import nullcontext
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Mapping

from envctl_engine.ui.backend_selector_debug import (
    debug_tty_group_enabled,
    emit_debug_tty_group,
    emit_parent_selector_thread_snapshot,
)
from envctl_engine.ui.selection_types import TargetSelection


def run_selector_subprocess(*, runtime: Any, payload: Mapping[str, object]) -> TargetSelection:
    from .terminal_session import temporary_standard_output_pendin

    emit = getattr(runtime, "_emit", None)
    session_id_getter = getattr(runtime, "_current_session_id", None)
    session_id = session_id_getter() if callable(session_id_getter) else None
    if callable(emit):
        emit(
            "ui.selector.subprocess",
            component="ui.backend",
            enabled=True,
            kind=str(payload.get("kind", "")).strip().lower(),
            session_id=session_id if isinstance(session_id, str) else None,
        )
    with tempfile.TemporaryDirectory(prefix="envctl-selector-") as tmpdir:
        payload_path = Path(tmpdir) / "payload.json"
        result_path = Path(tmpdir) / "result.json"
        payload_path.write_text(json.dumps(dict(payload)), encoding="utf-8")
        command = [
            sys.executable,
            "-m",
            "envctl_engine.ui.textual.selector_subprocess_entry",
            str(payload_path),
            str(result_path),
        ]
        env = os.environ.copy()
        runtime_env = getattr(runtime, "env", None)
        if isinstance(runtime_env, Mapping):
            env.update({str(key): str(value) for key, value in runtime_env.items()})
        if isinstance(session_id, str) and session_id.strip():
            _configure_selector_subprocess_debug(
                runtime=runtime,
                payload=payload,
                emit=emit,
                env=env,
                session_id=session_id,
            )
        apple_terminal = str(os.environ.get("TERM_PROGRAM", "")).strip() == "Apple_Terminal"
        reader_enabled = debug_tty_group_enabled(runtime, "reader")
        termios_enabled = debug_tty_group_enabled(runtime, "termios")
        emit_debug_tty_group(
            runtime,
            group="reader",
            action="parent_thread_snapshot",
            enabled=reader_enabled,
            detail="selector_subprocess",
        )
        emit_debug_tty_group(
            runtime,
            group="termios",
            action="temporary_standard_output_pendin",
            enabled=termios_enabled,
            detail="selector_subprocess",
        )
        if reader_enabled:
            emit_parent_selector_thread_snapshot(emit=emit, stage="before_subprocess_launch")
        pendin_mode = (
            temporary_standard_output_pendin(emit=emit, component="ui.backend")
            if apple_terminal and termios_enabled
            else nullcontext()
        )
        with pendin_mode:
            subprocess.run(command, check=True, env=env)
        if reader_enabled:
            emit_parent_selector_thread_snapshot(emit=emit, stage="after_subprocess_exit")
        result = json.loads(result_path.read_text(encoding="utf-8"))
    return TargetSelection(
        all_selected=bool(result.get("all_selected", False)),
        untested_selected=bool(result.get("untested_selected", False)),
        project_names=[str(name) for name in result.get("project_names", [])],
        service_names=[str(name) for name in result.get("service_names", [])],
        cancelled=bool(result.get("cancelled", False)),
    )


def _configure_selector_subprocess_debug(
    *,
    runtime: Any,
    payload: Mapping[str, object],
    emit: Any,
    env: dict[str, str],
    session_id: str,
) -> None:
    debug_path = (
        runtime.runtime_root
        / "debug"
        / session_id.strip()
        / (f"selector-subprocess-{str(payload.get('kind', 'unknown')).strip().lower()}.jsonl")
    )
    try:
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        env["ENVCTL_UI_SELECTOR_SUBPROCESS_DEBUG_PATH"] = str(debug_path)
        if callable(emit):
            emit(
                "ui.selector.subprocess",
                component="ui.backend",
                enabled=True,
                kind=str(payload.get("kind", "")).strip().lower(),
                debug_path=str(debug_path),
            )
    except OSError:
        pass


_run_selector_subprocess = run_selector_subprocess
