from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import json
from pathlib import Path
import re
import sys
import threading
from typing import Any, Callable, Mapping, Sequence

from envctl_engine.actions.actions_test import (
    TestCommandSpec,
    append_frontend_test_path,
    build_test_args,
    classify_test_command_source,
    default_test_commands,
    is_package_test_command,
    is_pytest_command,
    is_unittest_command,
)
from envctl_engine.shared.node_tooling import detect_package_manager, detect_python_bin
from envctl_engine.shared.parsing import parse_bool
from envctl_engine.test_output.parser_pytest import PytestOutputParser
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


@dataclass(frozen=True)
class FailedTestManifestEntry:
    source: str
    suite: str
    failed_tests: tuple[str, ...]
    failed_files: tuple[str, ...]
    invalid_failed_tests: int = 0


@dataclass(frozen=True)
class FailedTestManifest:
    generated_at: str
    head: str
    status_hash: str
    status_lines: int
    entries: tuple[FailedTestManifestEntry, ...]


def sanitize_failed_test_identifiers(*, source: str, failed_tests: Sequence[str]) -> tuple[tuple[str, ...], int]:
    if source != "backend_pytest":
        if source == "root_unittest":
            kept: list[str] = []
            invalid = 0
            seen: set[str] = set()
            for raw in failed_tests:
                candidate = normalize_unittest_test_identifier(str(raw).strip())
                if not candidate:
                    invalid += 1
                    continue
                if candidate in seen:
                    continue
                seen.add(candidate)
                kept.append(candidate)
            return tuple(kept), invalid
        normalized = tuple(str(value).strip() for value in failed_tests if str(value).strip())
        return normalized, 0
    kept: list[str] = []
    invalid = 0
    seen: set[str] = set()
    for raw in failed_tests:
        candidate = str(raw).strip()
        if not candidate:
            continue
        if not PytestOutputParser._is_valid_pytest_nodeid(candidate):
            invalid += 1
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        kept.append(candidate)
    return tuple(kept), invalid


_UNITTEST_TEST_ID_RE = r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+"


def normalize_unittest_test_identifier(raw: str) -> str | None:
    candidate = str(raw).strip()
    if not candidate:
        return None
    if re.fullmatch(_UNITTEST_TEST_ID_RE, candidate):
        return candidate
    display_match = re.fullmatch(rf"[^()]+\s+\(({_UNITTEST_TEST_ID_RE})\)", candidate)
    if display_match:
        return display_match.group(1)
    return None


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
    shared_raw_command: str | None,
    backend_raw_command: str | None,
    frontend_raw_command: str | None,
    target_contexts: Sequence[TestTargetContext],
    repo_root: Path,
    include_backend: bool,
    include_frontend: bool,
    frontend_test_path: str | None,
    run_all: bool,
    untested: bool,
    split_command: Callable[[str, Mapping[str, str]], list[str]],
    replacements_for_target: Callable[[object | None], Mapping[str, str]],
    is_legacy_tree_test_script: Callable[[list[str]], bool],
) -> list[TestExecutionSpec]:
    source = "detected"
    execution_specs: list[TestExecutionSpec] = []
    if shared_raw_command is not None:
        source = "configured"
        parsed_command: list[str] | None = None
        for target in target_contexts:
            command = split_command(shared_raw_command, replacements_for_target(target.target_obj))
            cwd = target.project_root
            if include_frontend and not include_backend and is_package_test_command(command):
                cwd = _configured_test_command_cwd(target.project_root, include_frontend=True)
                command = append_frontend_test_path(
                    command,
                    frontend_test_path,
                    project_root=target.project_root,
                    command_cwd=cwd,
                )
            if parsed_command is None:
                parsed_command = command
            if is_legacy_tree_test_script(command):
                parsed_command = command
                break
            classified_source = classify_test_command_source(
                command,
                include_backend=include_backend,
                include_frontend=include_frontend,
            )
            execution_specs.append(
                TestExecutionSpec(
                    index=0,
                    spec=TestCommandSpec(command=command, cwd=cwd, source=classified_source),
                    args=[],
                    resolved_source=classified_source,
                    project_name=target.project_name,
                    project_root=target.project_root,
                    target_obj=target.target_obj,
                )
            )
        if parsed_command is None:
            parsed_command = split_command(shared_raw_command, replacements_for_target(None))
            if include_frontend and not include_backend and is_package_test_command(parsed_command):
                parsed_command = append_frontend_test_path(
                    parsed_command,
                    frontend_test_path,
                    project_root=repo_root,
                    command_cwd=repo_root,
                )
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
            target_specs: list[TestCommandSpec] = []
            if include_backend:
                backend_spec = _configured_or_default_test_spec(
                    raw_command=backend_raw_command,
                    target=target,
                    repo_root=repo_root,
                    include_backend=True,
                    include_frontend=False,
                    frontend_test_path=None,
                    split_command=split_command,
                    replacements_for_target=replacements_for_target,
                )
                if backend_spec is not None:
                    target_specs.append(backend_spec)
            if include_frontend:
                frontend_spec = _configured_or_default_test_spec(
                    raw_command=frontend_raw_command,
                    target=target,
                    repo_root=repo_root,
                    include_backend=False,
                    include_frontend=True,
                    frontend_test_path=frontend_test_path,
                    split_command=split_command,
                    replacements_for_target=replacements_for_target,
                )
                if frontend_spec is not None:
                    target_specs.append(frontend_spec)
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


def _configured_or_default_test_spec(
    *,
    raw_command: str | None,
    target: TestTargetContext,
    repo_root: Path,
    include_backend: bool,
    include_frontend: bool,
    frontend_test_path: str | None,
    split_command: Callable[[str, Mapping[str, str]], list[str]],
    replacements_for_target: Callable[[object | None], Mapping[str, str]],
) -> TestCommandSpec | None:
    if raw_command is not None:
        command = split_command(raw_command, replacements_for_target(target.target_obj))
        source = "configured_frontend" if include_frontend else "configured_backend"
        if include_backend:
            if is_pytest_command(command):
                source = "backend_pytest"
            elif is_unittest_command(command):
                source = "root_unittest"
        if include_frontend and is_package_test_command(command):
            command = append_frontend_test_path(
                command,
                frontend_test_path,
                project_root=target.project_root,
                command_cwd=_configured_test_command_cwd(target.project_root, include_frontend=True),
            )
            source = "frontend_package_test"
        cwd = _configured_test_command_cwd(target.project_root, include_frontend=include_frontend)
        return TestCommandSpec(
            command=command,
            cwd=cwd,
            source=source,
        )
    target_specs = default_test_commands(
        target.project_root,
        include_backend=include_backend,
        include_frontend=include_frontend,
        frontend_test_path=frontend_test_path,
    )
    if not target_specs and target.project_root != repo_root:
        target_specs = default_test_commands(
            repo_root,
            include_backend=include_backend,
            include_frontend=include_frontend,
            frontend_test_path=frontend_test_path,
        )
    if not target_specs:
        return None
    return target_specs[0]


def _configured_test_command_cwd(project_root: Path, *, include_frontend: bool) -> Path:
    if include_frontend and (project_root / "frontend" / "package.json").is_file():
        return project_root / "frontend"
    return project_root


def build_failed_test_execution_specs(
    *,
    target_contexts: Sequence[TestTargetContext],
    repo_root: Path,
    manifests_by_project: Mapping[str, FailedTestManifest],
    shared_raw_command: str | None,
    backend_raw_command: str | None,
    frontend_raw_command: str | None,
) -> list[TestExecutionSpec]:
    execution_specs: list[TestExecutionSpec] = []
    unsupported: list[str] = []
    for target in target_contexts:
        manifest = manifests_by_project.get(target.project_name)
        if manifest is None:
            continue
        for entry in manifest.entries:
            spec = _failed_rerun_spec_for_entry(
                entry,
                project_name=target.project_name,
                project_root=target.project_root,
                repo_root=repo_root,
                target_obj=target.target_obj,
            )
            if isinstance(spec, str):
                unsupported.append(spec)
                continue
            if spec is not None:
                execution_specs.append(spec)
    if unsupported:
        first = unsupported[0]
        raise RuntimeError(first)
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


def load_failed_test_manifest(path: Path) -> FailedTestManifest | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    entries_raw = payload.get("entries")
    if not isinstance(entries_raw, list):
        return None
    entries: list[FailedTestManifestEntry] = []
    for raw_entry in entries_raw:
        if not isinstance(raw_entry, dict):
            continue
        source = str(raw_entry.get("source", "") or "").strip()
        suite = str(raw_entry.get("suite", "") or "").strip()
        sanitized_failed_tests, invalid_failed_tests = sanitize_failed_test_identifiers(
            source=source,
            failed_tests=[
                value.strip()
                for value in raw_entry.get("failed_tests", [])
                if isinstance(value, str) and value.strip()
            ],
        )
        raw_failed_files = [
            value.strip()
            for value in raw_entry.get("failed_files", [])
            if isinstance(value, str) and value.strip()
        ]
        if source in {"frontend_package_test", "package_test"}:
            derived_failed_files = frontend_failed_files_from_failed_tests(sanitized_failed_tests)
            merged_failed_files: list[str] = []
            seen_failed_files: set[str] = set()
            for failed_file in [*raw_failed_files, *derived_failed_files]:
                if failed_file in seen_failed_files:
                    continue
                seen_failed_files.add(failed_file)
                merged_failed_files.append(failed_file)
            failed_files = tuple(merged_failed_files)
        else:
            failed_files = tuple(raw_failed_files)
        if not source or (not sanitized_failed_tests and not failed_files):
            continue
        entries.append(
            FailedTestManifestEntry(
                source=source,
                suite=suite,
                failed_tests=sanitized_failed_tests,
                failed_files=failed_files,
                invalid_failed_tests=invalid_failed_tests,
            )
        )
    return FailedTestManifest(
        generated_at=str(payload.get("generated_at", "") or ""),
        head=str(payload.get("git_state", {}).get("head", "") or "") if isinstance(payload.get("git_state"), dict) else "",
        status_hash=(
            str(payload.get("git_state", {}).get("status_hash", "") or "")
            if isinstance(payload.get("git_state"), dict)
            else ""
        ),
        status_lines=(
            int(payload.get("git_state", {}).get("status_lines", 0) or 0)
            if isinstance(payload.get("git_state"), dict)
            else 0
        ),
        entries=tuple(entries),
    )


def frontend_failed_files_from_failed_tests(failed_tests: Sequence[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in failed_tests:
        text = str(raw).strip()
        if not text:
            continue
        file_name = text.split("::", 1)[0].strip()
        if not file_name or file_name in seen:
            continue
        seen.add(file_name)
        ordered.append(file_name)
    return ordered


def _failed_rerun_spec_for_entry(
    entry: FailedTestManifestEntry,
    *,
    project_name: str,
    project_root: Path,
    repo_root: Path,
    target_obj: object | None,
) -> TestExecutionSpec | str | None:
    source = entry.source
    if source == "backend_pytest":
        if not entry.failed_tests:
            return None
        python_exe = detect_python_bin(project_root / "backend", project_root, repo_root)
        if not python_exe:
            return f"Failed-only reruns are unavailable for {project_name} backend pytest because no Python interpreter was found."
        return TestExecutionSpec(
            index=0,
            spec=TestCommandSpec(
                command=[python_exe, "-m", "pytest", *entry.failed_tests],
                cwd=project_root,
                source=source,
            ),
            args=[],
            resolved_source=source,
            project_name=project_name,
            project_root=project_root,
            target_obj=target_obj,
        )
    if source == "root_unittest":
        if not entry.failed_tests:
            return None
        python_exe = detect_python_bin(project_root, repo_root)
        if not python_exe:
            return f"Failed-only reruns are unavailable for {project_name} unittest because no Python interpreter was found."
        return TestExecutionSpec(
            index=0,
            spec=TestCommandSpec(
                command=[python_exe, "-m", "unittest", *entry.failed_tests],
                cwd=project_root,
                source=source,
            ),
            args=[],
            resolved_source=source,
            project_name=project_name,
            project_root=project_root,
            target_obj=target_obj,
        )
    if source in {"frontend_package_test", "package_test"}:
        failed_files = list(entry.failed_files)
        if not failed_files:
            return None
        package_root = project_root / "frontend" if source == "frontend_package_test" else project_root
        manager = detect_package_manager(package_root)
        if not manager:
            return f"Failed-only reruns are unavailable for {project_name} {entry.suite or source} because no supported package manager was detected."
        command = [manager, "run", "test", "--", *failed_files]
        return TestExecutionSpec(
            index=0,
            spec=TestCommandSpec(
                command=command,
                cwd=package_root,
                source=source,
            ),
            args=[],
            resolved_source=source,
            project_name=project_name,
            project_root=project_root,
            target_obj=target_obj,
        )
    if source == "configured":
        return (
            f"Failed-only reruns are not supported for {project_name} because the previous test run used a custom configured command."
        )
    return f"Failed-only reruns are not supported for {project_name} ({source}). Run the full suite first."


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

    def mark_progress(self, execution: TestExecutionSpec, *, status_text: str) -> None:
        index = execution.index
        label_plain = self._labels_plain.get(index, self._descriptor(execution, render=False))
        label_render = self._labels_render.get(index, self._descriptor(execution, render=True))
        project_name = self._project_for_index.get(index, str(execution.project_name))
        escaped_status = self._escape_markup(status_text)
        plain_line = f"{project_name} / {label_plain}: {status_text}"
        render_line = f"  - {label_render}: [blue]{escaped_status}[/blue]"
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


def is_backend_only_selection(
    backend_flag: object, frontend_flag: object, service_types: set[str]
) -> tuple[bool, bool]:
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
