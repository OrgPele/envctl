from __future__ import annotations

import sys
import threading
from typing import Any

from envctl_engine.ui.color_policy import colors_enabled
from envctl_engine.ui.path_links import local_paths_in_text, render_paths_in_terminal_text


class BaseProjectSpinnerGroup:
    def __init__(
        self,
        *,
        projects: list[str],
        enabled: bool,
        policy: Any,
        emit: Any,
        component: str,
        op_id: str,
        start_message: str,
        idle_message: str,
        env: dict[str, str] | None = None,
    ) -> None:
        self._projects = [str(project).strip() for project in projects if str(project).strip()]
        self._enabled = (
            bool(enabled) and bool(getattr(policy, "enabled", False)) and str(getattr(policy, "backend", "")) == "rich"
        )
        self._style = str(getattr(policy, "style", "dots") or "dots")
        self._emit = emit if callable(emit) else None
        self._component = component
        self._op_id = op_id
        self._start_message = start_message
        self._idle_message = idle_message
        self._env = dict(env or {})
        self._stream = sys.stderr
        self._lock = threading.Lock()
        self._progress: Any = None
        self._console: Any = None
        self._tasks: dict[str, Any] = {}
        self._last_line_by_project: dict[str, str] = {}

    def __enter__(self) -> "BaseProjectSpinnerGroup":
        if not self._enabled:
            return self
        if not bool(getattr(self._stream, "isatty", lambda: False)()):
            self._enabled = False
            return self
        try:
            console_module = __import__("rich.console", fromlist=["Console"])
            progress_module = __import__("rich.progress", fromlist=["Progress", "SpinnerColumn", "TextColumn"])
            console_cls = getattr(console_module, "Console")
            progress_cls = getattr(progress_module, "Progress")
            spinner_column_cls = getattr(progress_module, "SpinnerColumn")
            text_column_cls = getattr(progress_module, "TextColumn")

            class _PerTaskSpinnerColumn(spinner_column_cls):  # type: ignore[misc, valid-type]
                def render(self, task):  # noqa: ANN001
                    if bool(getattr(task, "finished", False)):
                        symbol = task.fields.get("finished_symbol") if hasattr(task, "fields") else None
                        if isinstance(symbol, str) and symbol.strip():
                            from rich.text import Text

                            try:
                                return Text.from_markup(symbol)
                            except Exception:
                                return Text(symbol)
                    return super().render(task)

            console = console_cls(
                file=self._stream,
                no_color=not colors_enabled(self._env, stream=self._stream, interactive_tty=True),
                force_terminal=self._stream.isatty(),
            )
            self._console = console
            self._progress = progress_cls(
                _PerTaskSpinnerColumn(spinner_name=self._style, finished_text=" "),
                text_column_cls("{task.description}"),
                console=console,
                transient=False,
                auto_refresh=True,
            )
            self._progress.start()
            for project in self._projects:
                self._tasks[project] = self._progress.add_task(f"{project}: queued", total=None, finished_symbol=" ")
            self._emit_lifecycle("start", self._start_message)
        except Exception:
            self._enabled = False
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
        _ = exc_type, exc, tb
        with self._lock:
            if self._progress is not None:
                try:
                    self._progress.stop()
                except Exception:
                    pass
                self._progress = None
                self._console = None
            self._emit_lifecycle("stop")
        return False

    def _emit_lifecycle(self, state: str, message: str | None = None, *, project: str | None = None) -> None:
        if not callable(self._emit):
            return
        payload: dict[str, object] = {
            "component": self._component,
            "op_id": self._op_id,
            "state": state,
        }
        if message:
            payload["message"] = message
        if project:
            payload["project"] = project
        self._emit("ui.spinner.lifecycle", **payload)

    def _normalize_line(self, project: str, message: str) -> str:
        text = str(message).strip()
        if not text:
            return f"{project}: {self._idle_message}"
        if project.lower() in text.lower():
            return text
        return f"{project}: {text}"

    def update_project(self, project: str, message: str) -> None:
        project_name = str(project).strip()
        if not project_name:
            return
        line = self._normalize_line(project_name, message)
        with self._lock:
            previous = self._last_line_by_project.get(project_name)
            if previous == line:
                return
            self._last_line_by_project[project_name] = line
        self._emit_lifecycle("update", line, project=project_name)
        with self._lock:
            if self._progress is None:
                return
            task_id = self._tasks.get(project_name)
            if task_id is None:
                task_id = self._progress.add_task(f"{project_name}: queued", total=None)
                self._tasks[project_name] = task_id
            try:
                self._progress.update(task_id, description=line)
            except Exception:
                return

    def mark_success(self, project: str, message: str) -> None:
        project_name = str(project).strip()
        if not project_name:
            return
        line = self._normalize_line(project_name, message)
        self._emit_lifecycle("success", line, project=project_name)
        with self._lock:
            if self._progress is None:
                return
            task_id = self._tasks.get(project_name)
            if task_id is None:
                return
            try:
                self._progress.update(
                    task_id,
                    description=f"+ {line}",
                    total=1,
                    completed=1,
                    finished_symbol="[green]✓[/green]",
                )
                self._progress.stop_task(task_id)
            except Exception:
                return

    def mark_failure(self, project: str, message: str) -> None:
        project_name = str(project).strip()
        if not project_name:
            return
        line = self._normalize_line(project_name, message)
        self._emit_lifecycle("fail", line, project=project_name)
        with self._lock:
            if self._progress is None:
                return
            task_id = self._tasks.get(project_name)
            if task_id is None:
                return
            try:
                self._progress.update(
                    task_id,
                    description=f"! {line}",
                    total=1,
                    completed=1,
                    finished_symbol="[red]✗[/red]",
                )
                self._progress.stop_task(task_id)
            except Exception:
                return

    def print_detail(self, project: str, message: str) -> None:
        project_name = str(project).strip()
        detail = str(message).strip()
        if not project_name or not detail:
            return
        self._emit_lifecycle("detail", detail, project=project_name)
        rendered_detail = render_paths_in_terminal_text(
            detail,
            paths=local_paths_in_text(detail),
            env=self._env,
            stream=self._stream,
            interactive_tty=(True if self._enabled else None),
        )
        with self._lock:
            console = self._console
        if console is not None:
            try:
                console.print(f"  {rendered_detail}")
                return
            except Exception:
                pass
        try:
            print(f"  {rendered_detail}", file=self._stream)
        except Exception:
            return
