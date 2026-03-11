from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Mapping

from envctl_engine.shared.parsing import parse_bool
from envctl_engine.ui.color_policy import colors_enabled

PR_BODY_MAX_CHARS = 48_000
PR_TITLE_MAX_CHARS = 240


@dataclass(frozen=True, slots=True)
class ActionProjectContext:
    repo_root: Path
    project_root: Path
    project_name: str
    env: Mapping[str, str]

    @property
    def interactive(self) -> bool:
        return parse_bool(self.env.get("ENVCTL_ACTION_INTERACTIVE"), False) and bool(sys.stdin.isatty())


def run_commit_action(context: ActionProjectContext) -> int:
    git_root = resolve_git_root(context.project_root, context.repo_root)
    if shutil.which("git") is None:
        print("git is required for commit action")
        return 1

    branch = _git_output(git_root, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
    if not branch or branch == "HEAD":
        print(f"Skipping {context.project_name} (detached HEAD).")
        return 0

    add = _run_git(git_root, ["add", "-A"])
    if add.returncode != 0:
        _print_error("git add failed", add)
        return 1

    status = _run_git(git_root, ["status", "--porcelain"])
    if status.returncode != 0:
        _print_error("git status failed", status)
        return 1
    if not status.stdout.strip():
        print(f"No changes to commit for {branch}.")
        return 0

    commit_message, message_file, error = _resolve_commit_message(context, branch=branch)
    if error:
        print(error)
        return 1

    if message_file:
        commit = _run_git(git_root, ["commit", "-F", message_file])
    else:
        commit = _run_git(git_root, ["commit", "-m", commit_message])
    if commit.returncode != 0:
        _print_error("git commit failed", commit)
        return 1

    remote = str(context.env.get("PR_REMOTE") or "origin").strip() or "origin"
    push = _run_git(git_root, ["push", "-u", remote, branch])
    if push.returncode != 0:
        _print_error("git push failed", push)
        return 1

    print(f"Committed and pushed changes for {context.project_name} ({branch}).")
    return 0


def run_pr_action(context: ActionProjectContext) -> int:
    git_root = resolve_git_root(context.project_root, context.repo_root)
    if shutil.which("git") is None:
        print("git is required for pr action")
        return 1

    head_branch = _git_output(git_root, ["rev-parse", "--abbrev-ref", "HEAD"]).strip() or "unknown"
    if head_branch in {"HEAD", "unknown"}:
        print(f"Skipping {context.project_name} (detached HEAD).")
        return 0
    base_branch = _resolve_pr_base_branch(context, git_root)

    existing_url = existing_pr_url(git_root, head_branch)
    if existing_url:
        print(f"PR already exists: {existing_url}")
        return 0

    helper = context.repo_root / "utils" / "create-pr.sh"
    if helper.is_file() and os.access(helper, os.X_OK):
        command = [str(helper)]
        if base_branch:
            command.extend(["--base", base_branch])
        command.extend(["--head", head_branch, "--workdir", str(git_root)])
        created = subprocess.run(
            command,
            cwd=str(context.repo_root),
            text=True,
            capture_output=True,
            check=False,
        )
        _print_process_output(created)
        if created.returncode != 0:
            return 1
        return 0

    gh_path = shutil.which("gh")
    if gh_path is None:
        print("gh is required for pr action when utils/create-pr.sh is unavailable")
        return 1
    title = _pr_title(context, git_root, head_branch)
    body = _pr_body(context, git_root, head_branch, base_branch)
    body_file = _write_pr_body_file(body)
    args = [gh_path, "pr", "create", "--title", title, "--body-file", str(body_file), "--head", head_branch]
    if base_branch:
        args.extend(["--base", base_branch])
    try:
        created = subprocess.run(args, cwd=str(git_root), text=True, capture_output=True, check=False)
        _print_process_output(created)
        if created.returncode != 0:
            return 1
        return 0
    finally:
        try:
            body_file.unlink()
        except OSError:
            pass


def run_review_action(context: ActionProjectContext) -> int:
    git_root = resolve_git_root(context.project_root, context.repo_root)
    if shutil.which("git") is None:
        print("git is required for review action")
        return 1

    mode = _resolve_analyze_mode(context)
    scope = str(context.env.get("ENVCTL_ANALYZE_SCOPE", "all")).strip().lower() or "all"
    helper = context.repo_root / "utils" / "analyze-tree-changes.sh"
    if helper.is_file() and os.access(helper, os.X_OK):
        iterations = _analysis_iterations(context, mode=mode)
        if iterations:
            return _run_analyze_helper(
                context=context,
                helper=helper,
                iterations=iterations,
                mode=mode,
                scope=scope,
            )

    diff_stat = _git_output(git_root, ["diff", "--stat"]).strip()
    status = _git_output(git_root, ["status", "--porcelain"]).strip()
    output_path = _tree_diffs_output_path(
        context,
        "review",
        f"review_{sanitize_label(context.project_name)}_{mode}",
    )
    _write_markdown_lines(
        output_path,
        [
            f"# Review Summary: {context.project_name}",
            "",
            f"Mode: {mode}",
            f"Scope: {scope}",
            "",
            "## Diff Stat",
            diff_stat or "(no diff)",
            "",
            "## Working Tree",
            status or "(clean)",
            "",
        ],
    )
    _print_review_completion(
        context,
        mode=mode,
        scope=scope,
        output_dir=output_path.parent,
        summary_path=output_path,
        all_in_one_path=output_path,
        stats=[],
        tree_count=1,
    )
    return 0


def resolve_git_root(project_root: Path, repo_root: Path) -> Path:
    for candidate in (project_root, repo_root):
        if (candidate / ".git").exists():
            return candidate
    return project_root


def detect_default_branch(git_root: Path) -> str:
    ref = _git_output(git_root, ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"]).strip()
    if ref.startswith("origin/"):
        return ref.split("origin/", 1)[1]
    for candidate in ("main", "master"):
        if _git_output(git_root, ["rev-parse", "--verify", candidate]).strip():
            return candidate
    return "main"


def existing_pr_url(git_root: Path, branch: str) -> str:
    branch_name = branch.strip()
    if not branch_name or branch_name in {"HEAD", "unknown"}:
        return ""
    gh_path = shutil.which("gh")
    if gh_path is None:
        return ""
    listed = subprocess.run(
        [gh_path, "pr", "list", "--head", branch_name, "--state", "open", "--json", "url", "--jq", ".[0].url"],
        cwd=str(git_root),
        text=True,
        capture_output=True,
        check=False,
    )
    if listed.returncode != 0:
        return ""
    return listed.stdout.strip()


def sanitize_label(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)
    return cleaned.strip("_") or "project"


def _resolve_commit_message(
    context: ActionProjectContext,
    *,
    branch: str,
) -> tuple[str, str, str | None]:
    commit_message = str(context.env.get("ENVCTL_COMMIT_MESSAGE", "")).strip()
    commit_message_file = str(context.env.get("ENVCTL_COMMIT_MESSAGE_FILE", "")).strip()
    if commit_message:
        return commit_message, "", None
    if commit_message_file:
        path = Path(commit_message_file)
        if path.is_file() and _file_has_text(path):
            return "", str(path), None
        return "", "", f"Commit message file is missing or empty: {commit_message_file}"

    changelog = _tree_changelog_path(context)
    if changelog is not None:
        return "", str(changelog), None

    main_task = context.project_root / "MAIN_TASK.md"
    if main_task.is_file() and _file_has_text(main_task):
        return "", str(main_task), None

    return "", "", f"MAIN_TASK.md is missing or empty and no commit message provided for {branch}."


def _resolve_pr_base_branch(context: ActionProjectContext, git_root: Path) -> str:
    explicit = str(context.env.get("ENVCTL_PR_BASE", "")).strip()
    if explicit:
        return explicit
    return detect_default_branch(git_root)


def _resolve_analyze_mode(context: ActionProjectContext) -> str:
    explicit = str(context.env.get("ENVCTL_ANALYZE_MODE", "")).strip().lower()
    if explicit in {"single", "grouped"}:
        return explicit
    return "single"


def _pr_title(context: ActionProjectContext, git_root: Path, head_branch: str) -> str:
    subject = _git_output(git_root, ["log", "-1", "--pretty=%s"]).strip()
    title = subject or f"{context.project_name}: {head_branch}"
    title = " ".join(title.split())
    return title[:PR_TITLE_MAX_CHARS].rstrip() or head_branch


def _pr_body(context: ActionProjectContext, git_root: Path, head_branch: str, base_branch: str) -> str:
    sections: list[str] = []
    metadata_lines = [
        f"Project: {context.project_name}",
        f"Head: {head_branch}",
    ]
    if base_branch:
        metadata_lines.append(f"Base: {base_branch}")
    sections.append("\n".join(metadata_lines))

    changelog = _tree_changelog_path(context)
    if changelog is not None:
        excerpt = _recent_text_excerpt(_read_text(changelog), max_chars=PR_BODY_MAX_CHARS - 512)
        if excerpt:
            sections.append(f"## Changelog\n\n{excerpt}")
    else:
        commits = _pr_commit_summary(git_root, head_branch=head_branch, base_branch=base_branch)
        if commits:
            sections.append(f"## Commits\n\n{commits}")
        diff_stat = _pr_diff_stat(git_root, head_branch=head_branch, base_branch=base_branch)
        if diff_stat:
            sections.append(f"## Diff Stat\n\n{diff_stat}")

    body = "\n\n".join(section.strip() for section in sections if section.strip()).strip()
    if not body:
        body = f"Project: {context.project_name}\nHead: {head_branch}"
        if base_branch:
            body += f"\nBase: {base_branch}"
    return _truncate_pr_body(body, max_chars=PR_BODY_MAX_CHARS)


def _pr_commit_summary(git_root: Path, *, head_branch: str, base_branch: str) -> str:
    range_spec = f"{base_branch}..{head_branch}" if base_branch else head_branch
    commits = _git_output(git_root, ["log", "--no-merges", "--format=- %h %s", range_spec]).strip()
    return _truncate_pr_body(commits, max_chars=12_000) if commits else ""


def _pr_diff_stat(git_root: Path, *, head_branch: str, base_branch: str) -> str:
    diff_args = ["diff", "--stat"]
    if base_branch:
        diff_args.append(f"{base_branch}...{head_branch}")
    diff_stat = _git_output(git_root, diff_args).strip()
    return _truncate_pr_body(diff_stat, max_chars=8_000) if diff_stat else ""


def _recent_text_excerpt(text: str, *, max_chars: int) -> str:
    cleaned = _normalize_text_block(text)
    if len(cleaned) <= max_chars:
        return cleaned
    notice = "[truncated to most recent changelog content]\n\n"
    tail_limit = max(0, max_chars - len(notice))
    tail = cleaned[-tail_limit:] if tail_limit else ""
    if "\n" in tail:
        tail = tail.split("\n", 1)[1]
    return f"{notice}{tail}".strip()


def _truncate_pr_body(text: str, *, max_chars: int) -> str:
    cleaned = _normalize_text_block(text)
    if len(cleaned) <= max_chars:
        return cleaned
    notice = "\n\n[truncated]"
    keep = max(0, max_chars - len(notice))
    return f"{cleaned[:keep].rstrip()}{notice}".strip()


def _normalize_text_block(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = [line.rstrip() for line in normalized.splitlines()]
    return "\n".join(lines).strip()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _write_pr_body_file(body: str) -> Path:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".md") as handle:
        handle.write(body)
        return Path(handle.name)


def _analysis_iterations(context: ActionProjectContext, *, mode: str) -> list[str]:
    project_root = context.project_root.resolve()
    if project_root == context.repo_root.resolve():
        return []
    family_dir = _project_family_dir(project_root)
    if family_dir is None:
        return []

    iterations = _git_iteration_dirs(family_dir)
    if not iterations:
        return []
    if mode == "single":
        current_name = project_root.name
        if current_name in iterations:
            return [current_name]
        return [iterations[0]]
    return iterations


def _project_family_dir(project_root: Path) -> Path | None:
    parent = project_root.parent
    if parent == project_root:
        return None
    if project_root.name.isdigit() and parent.is_dir():
        return parent
    child_git_dirs = _git_iteration_dirs(parent)
    if child_git_dirs:
        return parent
    return None


def _git_iteration_dirs(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    iterations: list[str] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        git_marker = child / ".git"
        if git_marker.is_file() or git_marker.is_dir():
            iterations.append(child.name)
    return iterations


def _run_analyze_helper(
    *,
    context: ActionProjectContext,
    helper: Path,
    iterations: list[str],
    mode: str,
    scope: str,
) -> int:
    project_root = context.project_root.resolve()
    family_dir = _project_family_dir(project_root)
    if family_dir is None:
        return 1

    approach = "combine" if mode == "grouped" and len(iterations) > 1 else "optimal"
    output_dir = _tree_diffs_root(context) / (
        f"analysis_{sanitize_label(context.project_name)}_{sanitize_label(scope)}_{mode}_"
        f"{datetime.now(tz=UTC).strftime('%Y%m%d_%H%M%S')}"
    )
    args = [
        f"trees={','.join(iterations)}",
        f"approach={approach}",
        "output-dir=" + str(output_dir),
    ]
    if scope != "all":
        args.append(f"scope={scope}")
    if not (mode == "grouped" and len(iterations) > 1):
        args.extend(["security-check=true", "performance-check=true"])

    env_map = dict(os.environ)
    env_map.update(context.env)
    env_map["BASE_DIR"] = str(context.repo_root)
    env_map["TREES_DIR_NAME"] = str(family_dir)

    result = subprocess.run(
        [str(helper), *args],
        cwd=str(context.repo_root),
        env=env_map,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        short_summary_path = output_dir / "summary_short.txt"
        stats = _parse_review_stats(short_summary_path)
        _prune_review_output_dir(output_dir, keep_names={"summary.md", "all.md"})
        _print_review_completion(
            context,
            mode=mode,
            scope=scope,
            output_dir=output_dir,
            summary_path=_first_existing_path(output_dir / "summary.md", output_dir / "all.md"),
            all_in_one_path=output_dir / "all.md",
            stats=stats,
            tree_count=len(iterations),
        )
    else:
        _print_review_failure(
            context,
            output_dir=output_dir,
            result=result,
        )
    return result.returncode


def _tree_changelog_path(context: ActionProjectContext) -> Path | None:
    tree_name = "main" if context.project_name.strip().lower() == "main" else context.project_name.strip()
    candidate = context.project_root / "docs" / "changelog" / f"{sanitize_label(tree_name)}_changelog.md"
    if candidate.is_file() and _file_has_text(candidate):
        return candidate
    return None


def _file_has_text(path: Path) -> bool:
    try:
        return bool(path.read_text(encoding="utf-8").strip())
    except OSError:
        return False


def _summary_output_path(repo_root: Path, directory: str, prefix: str, label: str | None = None) -> Path:
    output_dir = repo_root / directory
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    if label:
        return output_dir / f"{prefix}_{sanitize_label(label)}_{timestamp}.md"
    return output_dir / f"{prefix}_{timestamp}.md"


def _tree_diffs_root(context: ActionProjectContext) -> Path:
    explicit = str(context.env.get("ENVCTL_ACTION_TREE_DIFFS_ROOT", "")).strip()
    if explicit:
        root = Path(explicit).expanduser()
    else:
        repo_hash = hashlib.sha256(str(context.repo_root.resolve()).encode("utf-8")).hexdigest()[:12]
        root = Path(tempfile.gettempdir()) / "envctl-tree-diffs" / repo_hash
    root.mkdir(parents=True, exist_ok=True)
    return root


def _tree_diffs_output_path(
    context: ActionProjectContext,
    directory: str,
    prefix: str,
    label: str | None = None,
) -> Path:
    output_dir = _tree_diffs_root(context) / directory
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    if label:
        return output_dir / f"{prefix}_{sanitize_label(label)}_{timestamp}.md"
    return output_dir / f"{prefix}_{timestamp}.md"


def _write_markdown_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines), encoding="utf-8")


def _run_git(git_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(git_root), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def _git_output(git_root: Path, args: list[str]) -> str:
    result = _run_git(git_root, args)
    if result.returncode != 0:
        return ""
    return result.stdout


def _print_process_output(result: subprocess.CompletedProcess[str]) -> None:
    stdout = str(result.stdout or "").strip()
    stderr = str(result.stderr or "").strip()
    if stdout:
        print(stdout)
    if result.returncode != 0 and stderr:
        print(stderr)


def _first_existing_path(*paths: Path) -> Path:
    for path in paths:
        if path.is_file():
            return path
    return paths[0]


def _print_review_completion(
    context: ActionProjectContext,
    *,
    mode: str,
    scope: str,
    output_dir: Path,
    summary_path: Path,
    all_in_one_path: Path,
    stats: list[tuple[str, str]],
    tree_count: int,
) -> None:
    if _print_review_completion_rich(
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
    color = _review_colorizer(context)
    print(color(f"Review Ready: {context.project_name}", fg="cyan", bold=True))
    print(f"  Mode: {mode}")
    print(f"  Scope: {scope}")
    print(f"  Trees: {tree_count}")
    print()
    print(color("  Output directory", fg="blue", bold=True))
    print(f"    {_display_path(output_dir)}")
    print(color("  Summary file", fg="blue", bold=True))
    print(f"    {_display_path(summary_path)}")
    print(color("  Full review bundle", fg="blue", bold=True))
    print(f"    {_display_path(all_in_one_path)}")
    if stats:
        print()
        print(color("  Quick stats", fg="green", bold=True))
        for label, value in stats:
            print(f"    {label}: {value}")

    print()
    print(color("  Next steps", fg="green", bold=True))
    print("    1. Start with the summary file.")
    print("    2. Open the full review when you need the complete context.")


def _print_review_completion_rich(
    context: ActionProjectContext,
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
    if not force_rich and not sys.stdout.isatty():
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
    details.add_row("Output", _display_path(output_dir))
    details.add_row("Summary", _display_path(summary_path))
    details.add_row("Bundle", _display_path(all_in_one_path))
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


def _print_review_failure(
    context: ActionProjectContext,
    *,
    output_dir: Path,
    result: subprocess.CompletedProcess[str],
) -> None:
    color = _review_colorizer(context)
    print(color(f"Review failed: {context.project_name}", fg="red", bold=True))
    print(color("  Output directory", fg="blue", bold=True))
    print(f"    {_display_path(output_dir)}")
    stderr = str(result.stderr or "").strip()
    stdout = str(result.stdout or "").strip()
    details = stderr or stdout or f"exit:{result.returncode}"
    print(f"  Details: {details}")


def _parse_review_stats(summary_short_path: Path | None) -> list[tuple[str, str]]:
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


def _prune_review_output_dir(output_dir: Path, *, keep_names: set[str]) -> None:
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


def _review_colorizer(context: ActionProjectContext):
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


def _display_path(path: Path) -> str:
    text = str(path)
    if text == "/private/tmp":
        return "/tmp"
    if text.startswith("/private/tmp/"):
        return "/tmp/" + text[len("/private/tmp/") :]
    return text


def _print_error(prefix: str, result: subprocess.CompletedProcess[str]) -> None:
    output = result.stderr or result.stdout or f"exit:{result.returncode}"
    print(f"{prefix}: {output}")
