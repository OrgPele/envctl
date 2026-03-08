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
) -> int:
    failures = 0
    for context in build_action_target_contexts(targets):
        emit_status(f"Running {command_name} for {context.name} ({context.index}/{context.total})...")
        resolution = resolve_command(context)
        if resolution.command is None or resolution.cwd is None:
            message = f"{command_name} action failed for {context.name}: {resolution.error or 'no command resolved'}"
            if not interactive_command or interactive_print_failures:
                printer(message)
            if interactive_command:
                emit_status(f"{command_name} failed for {context.name}: {resolution.error or 'no command resolved'}")
            failures += 1
            continue

        completed = process_run(resolution.command, resolution.cwd, build_env(context))
        if completed.returncode != 0:
            error = (completed.stderr or completed.stdout or f"exit:{completed.returncode}").strip()
            message = f"{command_name} action failed for {context.name}: {error}"
            if not interactive_command or interactive_print_failures:
                printer(message)
            if interactive_command:
                emit_status(f"{command_name} failed for {context.name}: {error}")
            failures += 1
            continue

        emit_action_output(completed.stdout, emit_status=emit_status, printer=printer)
        if not interactive_command:
            printer(f"{command_name} action succeeded for {context.name}.")
        emit_status(f"{command_name} succeeded for {context.name}")

    return 0 if failures == 0 else 1
