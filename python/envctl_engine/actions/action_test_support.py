from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from pathlib import Path
import sys
import threading
from typing import Any, Callable, Mapping, Sequence

from envctl_engine.actions.actions_test import TestCommandSpec, build_test_args, default_test_commands
from envctl_engine.shared.parsing import parse_bool
from envctl_engine.ui.color_policy import colors_enabled


@dataclass(frozen=True)
class TestTargetContext:
    project_name: str
    project_root: Path
    target_obj: object | None


@dataclass(frozen=True)
class TestExecutionSpec:
    index: int
    spec: TestCommandSpec
    args: list[str]
    resolved_source: str
    project_name: str
    project_root: Path
    target_obj: object | None = None


def build_test_target_contexts(targets: Sequence[object], *, repo_root: Path) -> list[TestTargetContext]:
    contexts: list[TestTargetContext] = []
    if targets:
        for target in targets:
            name = str(getattr(target, "name", "")).strip()
            root_raw = str(getattr(target, "root", "")).strip()
            if not root_raw:
                continue
            project_name = name or Path(root_raw).name
            contexts.append(
                TestTargetContext(
                    project_name=project_name,
                    project_root=Path(root_raw),
                    target_obj=target,
                )
            )
        if contexts:
            return contexts
    return [
        TestTargetContext(
            project_name="Main",
            project_root=repo_root,
            target_obj=None,
        )
    ]


def build_test_execution_specs(
    *,
    raw_command: str | None,
    target_contexts: Sequence[TestTargetContext],
    repo_root: Path,
    include_backend: bool,
    include_frontend: bool,
    run_all: bool,
    untested: bool,
    split_command: Callable[[str, Mapping[str, str]], list[str]],
    replacements_for_target: Callable[[object | None], Mapping[str, str]],
    is_legacy_tree_test_script: Callable[[list[str]], bool],
) -> list[TestExecutionSpec]:
    source = "detected"
    execution_specs: list[TestExecutionSpec] = []
    if raw_command is not None:
        source = "configured"
        parsed_command: list[str] | None = None
        for target in target_contexts:
            command = split_command(raw_command, replacements_for_target(target.target_obj))
            if parsed_command is None:
                parsed_command = command
            if is_legacy_tree_test_script(command):
                parsed_command = command
                break
            execution_specs.append(
                TestExecutionSpec(
                    index=0,
                    spec=TestCommandSpec(command=command, cwd=target.project_root, source="configured"),
                    args=[],
                    resolved_source=source,
                    project_name=target.project_name,
                    project_root=target.project_root,
                    target_obj=target.target_obj,
                )
            )
        if parsed_command is None:
            parsed_command = split_command(raw_command, replacements_for_target(None))
        if is_legacy_tree_test_script(parsed_command):
            project_names = [target.project_name for target in target_contexts]
            execution_specs = [
                TestExecutionSpec(
                    index=0,
                    spec=TestCommandSpec(command=parsed_command, cwd=repo_root, source="configured"),
                    args=build_test_args(project_names, run_all=run_all, untested=untested),
                    resolved_source=source,
                    project_name="all-targets",
                    project_root=repo_root,
                    target_obj=None,
                )
            ]
    else:
        for target in target_contexts:
            target_specs = default_test_commands(
                target.project_root,
                include_backend=include_backend,
                include_frontend=include_frontend,
            )
            if not target_specs and target.project_root != repo_root:
                target_specs = default_test_commands(
                    repo_root,
                    include_backend=include_backend,
                    include_frontend=include_frontend,
                )
            for spec in target_specs:
                execution_specs.append(
                    TestExecutionSpec(
                        index=0,
                        spec=spec,
                        args=[],
                        resolved_source=spec.source,
                        project_name=target.project_name,
                        project_root=target.project_root,
                        target_obj=target.target_obj,
                    )
                )
    return [
        TestExecutionSpec(
            index=index,
            spec=spec.spec,
            args=spec.args,
            resolved_source=spec.resolved_source,
            project_name=spec.project_name,
            project_root=spec.project_root,
            target_obj=spec.target_obj,
        )
        for index, spec in enumerate(execution_specs, start=1)
    ]


def rich_progress_available() -> tuple[bool, str]:
    try:
        if importlib.util.find_spec("rich.progress") is not None:
            return True, ""
    except Exception as exc:  # pragma: no cover - defensive
        return False, f"find_spec_error:{type(exc).__name__}"
    try:
        __import__("rich.progress")
        return True, ""
    except Exception as exc:  # pragma: no cover - defensive
        return False, f"import_error:{type(exc).__name__}"


class TestSuiteSpinnerGroup:
    def __init__(
        self,
        *,
        execution_specs: list[TestExecutionSpec],
        enabled: bool,
        policy: Any,
        emit: Any,
        suite_label_resolver: Callable[[str], str],
        multi_project: bool,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._execution_specs = list(execution_specs)
        self._enabled = bool(enabled) and str(getattr(policy, "backend", "")) == "rich"
        self._style = str(getattr(policy, "style", "dots") or "dots")
        self._emit = emit if callable(emit) else None
        self._suite_label_resolver = suite_label_resolver
        self._multi_project = bool(multi_project)
        self._env = dict(env or {})
        self._stream = sys.stderr
        self._lock = threading.Lock()
        self._progress: Any = None
        self._tasks: dict[int, Any] = {}
        self._labels_plain: dict[int, str] = {}
        self._labels_render: dict[int, str] = {}
        self._project_for_index: dict[int, str] = {}
        ordered_projects: list[str] = []
        for item in self._execution_specs:
            name = str(item.project_name).strip()
            if not name or name in ordered_projects:
                continue
            ordered_projects.append(name)
        self._ordered_projects = list(ordered_projects)
        self._project_header_color = "cyan"

    def __enter__(self) -> "TestSuiteSpinnerGroup":
        if not self._enabled:
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
                    if bool(getattr(task, "fields", {}).get("is_header", False)):
                        from rich.text import Text

                        return Text(" ")
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
                force_terminal=True,
            )
            self._progress = progress_cls(
                _PerTaskSpinnerColumn(spinner_name=self._style, finished_text=" "),
                text_column_cls("{task.description}", markup=True),
                console=console,
                transient=False,
                auto_refresh=True,
            )
            self._progress.start()
            grouped_specs: dict[str, list[TestExecutionSpec]] = {}
            for execution in self._execution_specs:
                grouped_specs.setdefault(execution.project_name, []).append(execution)

            for project_name in self._ordered_projects:
                execution_list = grouped_specs.get(project_name, [])
                if self._multi_project:
                    project_color = self._project_header_color
                    escaped_project = self._escape_markup(project_name)
                    header_line = f"[bold {project_color}]{escaped_project}[/]"
                    self._progress.add_task(
                        header_line,
                        total=1,
                        completed=1,
                        finished_symbol=" ",
                        is_header=True,
                    )
                for execution in execution_list:
                    label_plain = self._descriptor(execution, render=False)
                    label_render = self._descriptor(execution, render=True)
                    self._labels_plain[execution.index] = label_plain
                    self._labels_render[execution.index] = label_render
                    self._project_for_index[execution.index] = project_name
                    queued_line = f"  - {label_render}: [yellow]queued[/yellow]"
                    task_id = self._progress.add_task(queued_line, total=None)
                    self._tasks[execution.index] = task_id
            self._emit_lifecycle("start", f"Tracking {len(self._execution_specs)} test suites")
        except Exception:
            self._enabled = False
            self._progress = None
            self._tasks.clear()
            self._labels_plain.clear()
            self._labels_render.clear()
            self._project_for_index.clear()
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
            self._emit_lifecycle("stop")
        return False

    def _emit_lifecycle(self, state: str, message: str | None = None, *, suite_index: int | None = None) -> None:
        if not callable(self._emit):
            return
        payload: dict[str, object] = {
            "component": "action.test.parallel",
            "op_id": "action.test.parallel",
            "state": state,
        }
        if message:
            payload["message"] = message
        if suite_index is not None:
            payload["suite_index"] = suite_index
        self._emit("ui.spinner.lifecycle", **payload)

    @staticmethod
    def _escape_markup(text: str) -> str:
        return str(text).replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")

    def _suite_color(self, source: str) -> str:
        normalized = str(source).strip().lower()
        if normalized in {"backend_pytest", "root_unittest"}:
            return "cyan"
        if normalized == "frontend_package_test":
            return "magenta"
        if normalized == "package_test":
            return "blue"
        return "yellow"

    def _descriptor(self, execution: TestExecutionSpec, *, render: bool) -> str:
        suite_label = self._suite_label_resolver(execution.spec.source)
        if not render:
            return suite_label
        suite_color = self._suite_color(execution.spec.source)
        escaped_suite = self._escape_markup(suite_label)
        return f"[{suite_color}]{escaped_suite}[/]"

    def mark_running(self, execution: TestExecutionSpec) -> None:
        index = execution.index
        label_plain = self._labels_plain.get(index, self._descriptor(execution, render=False))
        label_render = self._labels_render.get(index, self._descriptor(execution, render=True))
        project_name = self._project_for_index.get(index, str(execution.project_name))
        plain_line = f"{project_name} / {label_plain}: running"
        render_line = f"  - {label_render}: [blue]running[/blue]"
        self._update_line(index, plain_line=plain_line, render_line=render_line, state="update")

    def mark_finished(
        self,
        execution: TestExecutionSpec,
        *,
        success: bool,
        duration_text: str,
        parsed: object | None,
    ) -> None:
        passed = int(getattr(parsed, "passed", 0) or 0) if parsed is not None else 0
        failed = int(getattr(parsed, "failed", 0) or 0) if parsed is not None else 0
        skipped = int(getattr(parsed, "skipped", 0) or 0) if parsed is not None else 0
        total = int(getattr(parsed, "total", 0) or 0) if parsed is not None else 0
        status = "passed" if success else "failed"
        label_plain = self._labels_plain.get(execution.index, self._descriptor(execution, render=False))
        label_render = self._labels_render.get(execution.index, self._descriptor(execution, render=True))
        project_name = self._project_for_index.get(execution.index, str(execution.project_name))
        metrics = f" [dim]• {passed}p/{failed}f/{skipped}s[/dim]" if total > 0 else ""
        status_text = "[green]passed[/green]" if success else "[red]failed[/red]"
        plain_line = f"{project_name} / {label_plain}: {status} ({duration_text})"
        render_line = f"  - {label_render}: {status_text} ({duration_text}){metrics}"
        self._update_line(
            execution.index,
            plain_line=plain_line,
            render_line=render_line,
            state="success" if success else "fail",
            stop_task=True,
            finished_symbol=("[green]✓[/green]" if success else "[red]✗[/red]"),
        )

    def _update_line(
        self,
        index: int,
        *,
        plain_line: str,
        render_line: str,
        state: str,
        stop_task: bool = False,
        finished_symbol: str = "",
    ) -> None:
        self._emit_lifecycle(state, plain_line, suite_index=index)
        with self._lock:
            if self._progress is None:
                return
            task_id = self._tasks.get(index)
            if task_id is None:
                return
            try:
                if stop_task:
                    self._progress.update(
                        task_id,
                        description=render_line,
                        total=1,
                        completed=1,
                        finished_symbol=finished_symbol,
                    )
                else:
                    self._progress.update(task_id, description=render_line)
                if stop_task:
                    self._progress.stop_task(task_id)
            except Exception:
                return


def is_backend_only_selection(backend_flag: object, frontend_flag: object, service_types: set[str]) -> tuple[bool, bool]:
    include_backend = backend_flag if isinstance(backend_flag, bool) else parse_bool(backend_flag, True)
    include_frontend = frontend_flag if isinstance(frontend_flag, bool) else parse_bool(frontend_flag, True)
    if backend_flag is None and frontend_flag is None:
        if service_types == {"backend"}:
            include_backend = True
            include_frontend = False
        elif service_types == {"frontend"}:
            include_backend = False
            include_frontend = True
    return include_backend, include_frontend
