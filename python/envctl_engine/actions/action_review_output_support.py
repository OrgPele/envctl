from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
from typing import Mapping

from envctl_engine.actions.action_review_context import ReviewActionContext
from envctl_engine.shared.parsing import parse_bool
from envctl_engine.ui.color_policy import colors_enabled
from envctl_engine.ui.path_links import (
    normalize_local_path_text,
    render_path_for_terminal,
    rich_path_text,
)


def print_review_completion(
    context: ReviewActionContext,
    *,
    mode: str,
    scope: str,
    output_dir: Path,
    summary_path: Path,
    all_in_one_path: Path,
    stats: list[tuple[str, str]],
    tree_count: int,
) -> None:
    if parse_bool(context.env.get("ENVCTL_ACTION_FORCE_RICH"), False):
        if print_review_completion_rich(
            context,
            mode=mode,
            scope=scope,
            output_dir=output_dir,
            summary_path=summary_path,
            all_in_one_path=all_in_one_path,
            stats=stats,
            tree_count=tree_count,
        ):
            return
    color = review_colorizer(context)
    print(color(f"Review Ready: {context.project_name}", fg="cyan", bold=True))
    print(f"  Mode: {mode}")
    print(f"  Scope: {scope}")
    print(f"  Trees: {tree_count}")
    print()
    print(color("  Output directory", fg="blue", bold=True))
    print(f"    {display_path(output_dir, env=context.env)}")
    print(color("  Summary file", fg="blue", bold=True))
    print(f"    {display_path(summary_path, env=context.env)}")
    print(color("  Full review bundle", fg="blue", bold=True))
    print(f"    {display_path(all_in_one_path, env=context.env)}")
    if stats:
        print()
        print(color("  Quick stats", fg="green", bold=True))
        for label, value in stats:
            print(f"    {label}: {value}")

    print()
    print(color("  Next steps", fg="green", bold=True))
    print("    1. Start with the summary file.")
    print("    2. Open the full review when you need the complete context.")


def print_review_completion_rich(
    context: ReviewActionContext,
    *,
    mode: str,
    scope: str,
    output_dir: Path,
    summary_path: Path,
    all_in_one_path: Path,
    stats: list[tuple[str, str]],
    tree_count: int,
) -> bool:
    force_rich = parse_bool(context.env.get("ENVCTL_ACTION_FORCE_RICH"), False)
    if not force_rich:
        return False
    try:
        from rich import box
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text
    except Exception:
        return False

    console = Console(
        file=sys.stdout,
        no_color=not colors_enabled(context.env, stream=sys.stdout, interactive_tty=force_rich or sys.stdout.isatty()),
        force_terminal=True,
    )

    details = Table.grid(padding=(0, 1))
    details.add_column(style="bold")
    details.add_column()
    details.add_row("Mode", mode)
    details.add_row("Scope", scope)
    details.add_row("Trees", str(tree_count))
    link_tty = force_rich or sys.stdout.isatty()
    details.add_row(
        "Output",
        rich_path_text(output_dir, text_cls=Text, env=context.env, stream=sys.stdout, interactive_tty=link_tty),
    )
    details.add_row(
        "Summary",
        rich_path_text(summary_path, text_cls=Text, env=context.env, stream=sys.stdout, interactive_tty=link_tty),
    )
    details.add_row(
        "Bundle",
        rich_path_text(all_in_one_path, text_cls=Text, env=context.env, stream=sys.stdout, interactive_tty=link_tty),
    )
    for label, value in stats:
        details.add_row(label, value)

    steps = Table.grid(padding=(0, 1))
    steps.add_column(width=3, style="bold")
    steps.add_column()
    steps.add_row("1.", "Start with the summary file.")
    steps.add_row("2.", "Open the full review when you need the complete context.")

    title = Text.assemble(("Review Ready", "bold"), (": ", "bold"), (context.project_name, "cyan"))
    body = Table.grid(padding=(1, 0))
    body.add_row(details)
    body.add_row(Text(""))
    body.add_row(Text("Next steps", style="bold"))
    body.add_row(steps)
    console.print(Panel(body, title=title, box=box.ROUNDED, expand=True))
    return True


def print_review_failure(
    context: ReviewActionContext,
    *,
    output_dir: Path,
    result: subprocess.CompletedProcess[str],
) -> None:
    color = review_colorizer(context)
    print(color(f"Review failed: {context.project_name}", fg="red", bold=True))
    print(color("  Output directory", fg="blue", bold=True))
    print(f"    {display_path(output_dir, env=context.env)}")
    stderr = str(result.stderr or "").strip()
    stdout = str(result.stdout or "").strip()
    details = stderr or stdout or f"exit:{result.returncode}"
    print(f"  Details: {details}")


def parse_review_stats(summary_short_path: Path | None) -> list[tuple[str, str]]:
    if summary_short_path is None or not summary_short_path.is_file():
        return []
    wanted = {
        "Trees analyzed": "Trees analyzed",
        "Base branch": "Base branch",
        "Trees with changes": "Trees with changes",
        "Trees with no changes": "Trees with no changes",
    }
    rows: list[tuple[str, str]] = []
    try:
        for raw in summary_short_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if ":" not in line:
                continue
            key, value = [part.strip() for part in line.split(":", 1)]
            if key in wanted and value:
                rows.append((wanted[key], value))
    except OSError:
        return []
    return rows


def prune_review_output_dir(output_dir: Path, *, keep_names: set[str]) -> None:
    for child in list(output_dir.iterdir()):
        if child.name in keep_names:
            continue
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
            continue
        try:
            child.unlink()
        except OSError:
            continue


def review_colorizer(context: ReviewActionContext):
    enabled = colors_enabled(context.env, stream=sys.stdout, interactive_tty=context.interactive)

    def colorize(text: str, *, fg: str | None = None, bold: bool = False) -> str:
        if not enabled:
            return text
        palette = {
            "red": "31",
            "green": "32",
            "yellow": "33",
            "blue": "34",
            "magenta": "35",
            "cyan": "36",
            "gray": "90",
        }
        codes: list[str] = []
        if bold:
            codes.append("1")
        if fg is not None and fg in palette:
            codes.append(palette[fg])
        if not codes:
            return text
        return f"\x1b[{';'.join(codes)}m{text}\x1b[0m"

    return colorize


def display_path(path: Path, *, env: Mapping[str, str] | None = None) -> str:
    return render_path_for_terminal(normalize_local_path_text(path), env=env, stream=sys.stdout)
