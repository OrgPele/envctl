from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import os
import sys
import threading
import time
from typing import Callable, Mapping, TextIO
from .color_policy import colors_enabled
from envctl_engine.shared.parsing import parse_bool


def _parse_int(value: object, default: int) -> int:
    if value is None:
        return default
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _rich_available() -> bool:
    return importlib.util.find_spec("rich") is not None


def _prompt_toolkit_available() -> bool:
    return importlib.util.find_spec("prompt_toolkit") is not None


_SPINNER_SUCCESS_SYMBOL = "✓"
_SPINNER_FAILURE_SYMBOL = "✗"


@dataclass(slots=True)
class SpinnerPolicy:
    mode: str
    enabled: bool
    reason: str
    backend: str
    min_ms: int
    verbose_events: bool
    style: str = "dots"


def resolve_spinner_policy(
    env: Mapping[str, str] | None = None,
    *,
    stream_isatty: bool | None = None,
    input_phase: bool = False,
) -> SpinnerPolicy:
    merged = dict(os.environ)
    if env:
        merged.update(env)

    mode_raw = str(merged.get("ENVCTL_UI_SPINNER_MODE", "auto")).strip().lower()
    mode = mode_raw if mode_raw in {"auto", "on", "off"} else "auto"
    style_raw = str(merged.get("ENVCTL_UI_SPINNER_STYLE", "dots")).strip().lower()
    style = style_raw if style_raw else "dots"
    min_ms = max(0, _parse_int(merged.get("ENVCTL_UI_SPINNER_MIN_MS"), 120))
    verbose_events = parse_bool(merged.get("ENVCTL_UI_SPINNER_VERBOSE_EVENTS"), False)

    if input_phase:
        return SpinnerPolicy(
            mode=mode,
            enabled=False,
            reason="input_phase_guard",
            backend="rich",
            style=style,
            min_ms=min_ms,
            verbose_events=verbose_events,
        )

    if mode == "off":
        return SpinnerPolicy(
            mode=mode,
            enabled=False,
            reason="env_off",
            backend="rich",
            style=style,
            min_ms=min_ms,
            verbose_events=verbose_events,
        )

    rich_available = _rich_available()
    prompt_available = _prompt_toolkit_available()
    backend = "rich" if rich_available else ("prompt_toolkit" if prompt_available else "rich")
    backend_missing = not rich_available and not prompt_available
    if backend_missing:
        return SpinnerPolicy(
            mode=mode,
            enabled=False,
            reason="spinner_backend_missing",
            backend="rich",
            style=style,
            min_ms=min_ms,
            verbose_events=verbose_events,
        )

    compatibility_disabled = parse_bool(merged.get("ENVCTL_UI_SPINNER"), True) is False
    rich_compat_disabled = parse_bool(merged.get("ENVCTL_UI_RICH"), True) is False
    is_tty = bool(sys.stderr.isatty() if stream_isatty is None else stream_isatty)
    ci_mode = bool(str(merged.get("CI", "")).strip())

    if mode == "on":
        if not is_tty:
            return SpinnerPolicy(
                mode=mode,
                enabled=False,
                reason="non_tty",
                backend=backend,
                style=style,
                min_ms=min_ms,
                verbose_events=verbose_events,
            )
        return SpinnerPolicy(
            mode=mode,
            enabled=True,
            reason="",
            backend=backend,
            style=style,
            min_ms=min_ms,
            verbose_events=verbose_events,
        )

    if compatibility_disabled or rich_compat_disabled:
        return SpinnerPolicy(
            mode=mode,
            enabled=False,
            reason="env_off",
            backend=backend,
            style=style,
            min_ms=min_ms,
            verbose_events=verbose_events,
        )
    if ci_mode:
        return SpinnerPolicy(
            mode=mode,
            enabled=False,
            reason="ci_mode",
            backend=backend,
            style=style,
            min_ms=min_ms,
            verbose_events=verbose_events,
        )
    if not is_tty:
        return SpinnerPolicy(
            mode=mode,
            enabled=False,
            reason="non_tty",
            backend=backend,
            style=style,
            min_ms=min_ms,
            verbose_events=verbose_events,
        )
    return SpinnerPolicy(
        mode=mode,
        enabled=True,
        reason="",
        backend=backend,
        style=style,
        min_ms=min_ms,
        verbose_events=verbose_events,
    )


def emit_spinner_policy(
    emit: Callable[..., None] | None,
    policy: SpinnerPolicy,
    *,
    context: Mapping[str, object] | None = None,
) -> None:
    if not callable(emit):
        return
    payload = dict(context or {})
    style = str(getattr(policy, "style", "dots") or "dots")
    emit(
        "ui.spinner.policy",
        backend=policy.backend,
        style=style,
        enabled=policy.enabled,
        reason=policy.reason,
        mode=policy.mode,
        min_ms=policy.min_ms,
        **payload,
    )
    if not policy.enabled:
        emit("ui.spinner.disabled", reason=policy.reason, mode=policy.mode, backend=policy.backend, **payload)


class RichSpinnerOperation:
    def __init__(
        self,
        *,
        message: str,
        policy: SpinnerPolicy,
        stream: TextIO | None = None,
        emit: Callable[..., None] | None = None,
        op_id: str | None = None,
        context: Mapping[str, object] | None = None,
        start_immediately: bool = True,
    ) -> None:
        self._message = str(message).strip() or "Working..."
        self._policy = policy
        self._style = str(getattr(policy, "style", "dots") or "dots")
        self._stream = stream or sys.stderr
        self._emit = emit if callable(emit) else None
        self._op_id = op_id or "spinner-operation"
        self._context = dict(context or {})
        self._lock = threading.Lock()
        stream_is_tty = bool(getattr(self._stream, "isatty", lambda: False)())
        self._no_color = not colors_enabled(
            os.environ,
            stream=self._stream,
            interactive_tty=stream_is_tty,
        )
        self._status = None
        self._console = None
        self._prompt_output = None
        self._prompt_thread: threading.Thread | None = None
        self._prompt_stop = threading.Event()
        self._prompt_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self._started = False
        self._stopped = False
        self._final_state: tuple[bool, str] | None = None
        self._defer_until = time.monotonic() + (float(policy.min_ms) / 1000.0)
        if start_immediately:
            self.begin(self._op_id)

    def _clear_current_line(self) -> None:
        try:
            if bool(getattr(self._stream, "isatty", lambda: False)()):
                self._stream.write("\r\033[2K\r")
                self._stream.flush()
        except Exception:
            return

    def _emit_lifecycle(self, state: str, message: str | None = None) -> None:
        if not callable(self._emit):
            return
        payload = dict(self._context)
        payload.update({"op_id": self._op_id, "state": state})
        if message:
            payload["message"] = message
        self._emit("ui.spinner.lifecycle", **payload)

    def _start_backend(self, *, force: bool = False) -> bool:
        if not self._policy.enabled:
            return False
        if self._started:
            return True
        if not force and time.monotonic() < self._defer_until:
            return False
        if self._policy.backend == "rich":
            try:
                console_module = __import__("rich.console", fromlist=["Console"])
                status_module = __import__("rich.status", fromlist=["Status"])
                console_cls = getattr(console_module, "Console")
                status_cls = getattr(status_module, "Status")
                self._console = console_cls(
                    file=self._stream, no_color=self._no_color, force_terminal=self._stream.isatty()
                )
                self._status = status_cls(self._message, spinner=self._style, console=self._console)
                self._status.start()
                self._started = True
                return True
            except Exception:
                return False
        if self._policy.backend == "prompt_toolkit":
            try:
                defaults_module = __import__("prompt_toolkit.output.defaults", fromlist=["create_output"])
                create_output = getattr(defaults_module, "create_output")
                self._prompt_output = create_output(stdout=self._stream)
                self._prompt_stop.clear()
                self._prompt_thread = threading.Thread(
                    target=self._prompt_render_loop, name="envctl-spinner", daemon=True
                )
                self._prompt_thread.start()
                self._started = True
                return True
            except Exception:
                return False
        return False

    def _prompt_render_loop(self) -> None:
        frame_index = 0
        while not self._prompt_stop.wait(0.09):
            frame = self._prompt_frames[frame_index % len(self._prompt_frames)]
            frame_index += 1
            try:
                if self._prompt_output is not None:
                    self._prompt_output.write_raw(f"\r{frame} {self._message}")
                    self._prompt_output.flush()
            except Exception:
                return

    def begin(self, op_id: str | None = None, context: Mapping[str, object] | None = None) -> None:
        with self._lock:
            if op_id:
                self._op_id = op_id
            if context:
                self._context.update(dict(context))
            self._emit_lifecycle("start", self._message)
            # Start immediately when begin() is explicit so long-running phases are always visible.
            self._start_backend(force=True)

    def start(self) -> None:
        self.begin(self._op_id)

    def update(self, message: str) -> None:
        text = str(message).strip()
        if not text:
            return
        with self._lock:
            self._message = text
            self._emit_lifecycle("update", text)
            if self._start_backend(force=False):
                if self._policy.backend == "rich" and self._status is not None:
                    try:
                        self._status.update(text)
                    except Exception:
                        pass

    def succeed(self, message: str) -> None:
        text = str(message).strip() or "Completed"
        with self._lock:
            self._final_state = (True, text)
            self._emit_lifecycle("success", text)

    def fail(self, message: str) -> None:
        text = str(message).strip() or "Failed"
        with self._lock:
            self._final_state = (False, text)
            self._emit_lifecycle("fail", text)

    def end(self) -> None:
        with self._lock:
            if self._stopped:
                return
            if self._started and self._status is not None:
                try:
                    self._status.stop()
                except Exception:
                    pass
                self._clear_current_line()
            if self._started and self._policy.backend == "prompt_toolkit":
                self._prompt_stop.set()
                if self._prompt_thread is not None:
                    self._prompt_thread.join(timeout=0.25)
                try:
                    if self._prompt_output is not None:
                        self._prompt_output.write_raw("\r\033[2K\r")
                        self._prompt_output.flush()
                except Exception:
                    pass
            if self._final_state is not None:
                ok, message = self._final_state
                if self._started and self._console is not None:
                    symbol = _SPINNER_SUCCESS_SYMBOL if ok else _SPINNER_FAILURE_SYMBOL
                    text = f"{symbol} {message}"
                    if not self._no_color:
                        color = "green" if ok else "red"
                        text = f"[{color}]{symbol}[/{color}] {message}"
                    try:
                        self._console.print(text)
                    except Exception:
                        pass
                elif self._started and self._policy.backend == "prompt_toolkit":
                    symbol = _SPINNER_SUCCESS_SYMBOL if ok else _SPINNER_FAILURE_SYMBOL
                    try:
                        if self._prompt_output is not None:
                            self._prompt_output.write_raw(f"{symbol} {message}\n")
                            self._prompt_output.flush()
                    except Exception:
                        pass
                elif not ok:
                    # Failure should still be visible when spinner stayed deferred.
                    print(f"! {message}", file=self._stream)
            self._emit_lifecycle("stop", self._final_state[1] if self._final_state else self._message)
            self._stopped = True
            self._started = False

    def stop(self) -> None:
        self.end()
