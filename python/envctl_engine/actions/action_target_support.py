from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


@dataclass(frozen=True)
class ActionCommandResolution:
    command: list[str] | None
    cwd: Path | None
    error: str | None = None


@dataclass(frozen=True)
class ActionTargetContext:
    name: str
    root: Path
    index: int
    total: int
    target_obj: object


def build_action_target_contexts(targets: Sequence[object]) -> list[ActionTargetContext]:
    total = max(len(targets), 1)
    return [
        ActionTargetContext(
            name=str(getattr(target, "name")),
            root=Path(str(getattr(target, "root"))),
            index=index,
            total=total,
            target_obj=target,
        )
        for index, target in enumerate(targets, start=1)
    ]


def emit_action_output(
    output: str | None,
    *,
    emit_status: Callable[[str], None],
    printer: Callable[[str], None] = print,
) -> bool:
    lines: list[str] = []
    for raw in str(output or "").splitlines():
        text = raw.strip()
        if text:
            lines.append(text)
    if not lines:
        return False
    for line in lines:
        printer(line)
        emit_status(line)
    return True


def execute_targeted_action(
    *,
    targets: Sequence[object],
    command_name: str,
    interactive_command: bool,
    resolve_command: Callable[[ActionTargetContext], ActionCommandResolution],
    build_env: Callable[[ActionTargetContext], Mapping[str, str]],
    process_run: Callable[[list[str], Path, Mapping[str, str]], Any],
    emit_status: Callable[[str], None],
    printer: Callable[[str], None] = print,
    interactive_print_failures: bool = True,
    emit_success_output: bool = True,
    on_success: Callable[[ActionTargetContext, Any], None] | None = None,
    on_failure: Callable[[ActionTargetContext, str], None] | None = None,
    failure_status_formatter: Callable[[ActionTargetContext, str], str] | None = None,
    print_noninteractive_failures: bool = True,
    print_noninteractive_successes: bool = True,
) -> int:
    failures = 0
    for context in build_action_target_contexts(targets):
        emit_status(f"Running {command_name} for {context.name} ({context.index}/{context.total})...")
        resolution = resolve_command(context)
        if resolution.command is None or resolution.cwd is None:
            raw_error = resolution.error or "no command resolved"
            message = f"{command_name} action failed for {context.name}: {raw_error}"
            if on_failure is not None:
                on_failure(context, raw_error)
            if (not interactive_command and print_noninteractive_failures) or (interactive_command and interactive_print_failures):
                printer(message)
            if interactive_command:
                if failure_status_formatter is not None:
                    emit_status(failure_status_formatter(context, raw_error))
                else:
                    emit_status(f"{command_name} failed for {context.name}: {raw_error}")
            failures += 1
            continue

        completed = process_run(resolution.command, resolution.cwd, build_env(context))
        if completed.returncode != 0:
            stdout = str(getattr(completed, "stdout", "") or "").strip()
            stderr = str(getattr(completed, "stderr", "") or "").strip()
            if stderr and stdout and stderr != stdout:
                error = f"{stderr}\n\nstdout:\n{stdout}"
            else:
                error = stderr or stdout or f"exit:{completed.returncode}"
            message = f"{command_name} action failed for {context.name}: {error}"
            if on_failure is not None:
                on_failure(context, error)
            if (not interactive_command and print_noninteractive_failures) or (interactive_command and interactive_print_failures):
                printer(message)
            if interactive_command:
                if failure_status_formatter is not None:
                    emit_status(failure_status_formatter(context, error))
                else:
                    emit_status(f"{command_name} failed for {context.name}: {error}")
            failures += 1
            continue

        if emit_success_output:
            emit_action_output(completed.stdout, emit_status=emit_status, printer=printer)
        if on_success is not None:
            on_success(context, completed)
        if not interactive_command and print_noninteractive_successes:
            printer(f"{command_name} action succeeded for {context.name}.")
        emit_status(f"{command_name} succeeded for {context.name}")

    return 0 if failures == 0 else 1
