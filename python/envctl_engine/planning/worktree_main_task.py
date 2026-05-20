from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Callable


def seed_main_task_from_plan(*, target: Path, plan_path: Path) -> None:
    if not plan_path.is_file() or not target.is_dir():
        return
    try:
        plan_text = plan_path.read_text(encoding="utf-8")
    except OSError:
        return
    if not plan_text.strip():
        return
    main_task_path = target / "MAIN_TASK.md"
    try:
        main_task_path.write_text(plan_text if plan_text.endswith("\n") else f"{plan_text}\n", encoding="utf-8")
    except OSError:
        return


def move_plan_to_done(
    *,
    plan_file: str,
    planning_root: Path,
    planning_done_root: Path,
    render_path: Callable[..., str],
    emit_message: Callable[[str], None],
) -> None:
    src = planning_root / plan_file
    if not src.is_file():
        return
    rel_dir = Path(plan_file).parent
    if str(rel_dir) in {"", "."}:
        rel_dir = Path("_misc")
    done_dir = planning_done_root / rel_dir
    done_dir.mkdir(parents=True, exist_ok=True)
    dest = done_dir / src.name
    if dest.exists():
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        dest = done_dir / f"{src.stem}-{stamp}{src.suffix}"
    src.replace(dest)
    relative_done = dest.relative_to(planning_done_root)
    emit_message(
        "Moved "
        f"{render_path(absolute_path=src, display_text=plan_file)} "
        "to "
        f"{render_path(absolute_path=dest, display_text=f'done/{relative_done}')}."
    )


def next_available_iteration(existing_iters: set[int]) -> int:
    candidate = 1
    while candidate in existing_iters:
        candidate += 1
    return candidate
