from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import os
import shutil
import subprocess
import sys
from typing import Mapping

from envctl_engine.shared.parsing import parse_bool


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
    commits = _git_output(git_root, ["log", "--oneline", "-n", "20"]).strip()
    if base_branch and base_branch != "unknown":
        base_range = f"{base_branch}..HEAD"
        commits = _git_output(git_root, ["log", "--oneline", base_range]).strip() or commits
    status = _git_output(git_root, ["status", "--porcelain"]).strip()

    output_path = _summary_output_path(context.repo_root, "pr", "pr_summary", context.project_name)
    _write_markdown_lines(
        output_path,
        [
            f"# PR Summary: {context.project_name}",
            "",
            f"Base: {base_branch or 'unknown'}",
            f"Head: {head_branch}",
            "",
            "## Commits",
            commits or "(no commits found)",
            "",
            "## Working Tree",
            status or "(clean)",
            "",
        ],
    )

    existing_url = existing_pr_url(git_root, head_branch)
    if existing_url:
        print(f"PR already exists: {existing_url}")
        print(f"PR summary written: {output_path}")
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
        print(f"PR summary written: {output_path}")
        return 0

    gh_path = shutil.which("gh")
    if gh_path is None:
        print("gh is required for pr action when utils/create-pr.sh is unavailable")
        print(f"PR summary written: {output_path}")
        return 1
    args = [gh_path, "pr", "create", "--fill"]
    if base_branch:
        args.extend(["--base", base_branch])
    created = subprocess.run(args, cwd=str(git_root), text=True, capture_output=True, check=False)
    _print_process_output(created)
    if created.returncode != 0:
        return 1
    print(f"PR summary written: {output_path}")
    return 0


def run_analyze_action(context: ActionProjectContext) -> int:
    git_root = resolve_git_root(context.project_root, context.repo_root)
    if shutil.which("git") is None:
        print("git is required for analyze action")
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
    output_path = _summary_output_path(
        context.repo_root,
        "analysis",
        f"analysis_{sanitize_label(context.project_name)}_{mode}",
    )
    _write_markdown_lines(
        output_path,
        [
            f"# Analysis Summary: {context.project_name}",
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
    print(f"Analysis summary written: {output_path}")
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
        [gh_path, "pr", "list", "--head", branch_name, "--state", "all", "--json", "url", "--jq", ".[0].url"],
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

    if context.interactive:
        print("Commit message: ", end="", flush=True)
        try:
            prompted = input().strip()
        except EOFError:
            prompted = ""
        if prompted:
            return prompted, "", None

    return "", "", f"MAIN_TASK.md is missing or empty and no commit message provided for {branch}."


def _resolve_pr_base_branch(context: ActionProjectContext, git_root: Path) -> str:
    explicit = str(context.env.get("ENVCTL_PR_BASE", "")).strip()
    if explicit:
        return explicit
    default_branch = detect_default_branch(git_root)
    if not context.interactive:
        return default_branch
    print(f"Base branch for PRs (default: {default_branch}): ", end="", flush=True)
    try:
        response = input().strip()
    except EOFError:
        response = ""
    candidate = response or default_branch
    if _run_git(git_root, ["rev-parse", "--verify", candidate]).returncode != 0:
        print(f"Base branch '{candidate}' not found; using {default_branch}.")
        return default_branch
    return candidate


def _resolve_analyze_mode(context: ActionProjectContext) -> str:
    explicit = str(context.env.get("ENVCTL_ANALYZE_MODE", "")).strip().lower()
    if explicit in {"single", "grouped"}:
        return explicit
    if context.interactive and len(_analysis_iterations(context, mode="grouped")) > 1:
        print("Analysis mode [single/grouped] (default: single): ", end="", flush=True)
        try:
            response = input().strip().lower()
        except EOFError:
            response = ""
        if response in {"single", "grouped"}:
            return response
    return "single"


def _analysis_iterations(context: ActionProjectContext, *, mode: str) -> list[str]:
    project_root = context.project_root.resolve()
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
    args = [
        f"trees={','.join(iterations)}",
        f"approach={approach}",
        f"output-dir=tree-diffs/analysis_{sanitize_label(context.project_name)}_{sanitize_label(scope)}_{mode}_{datetime.now(tz=UTC).strftime('%Y%m%d_%H%M%S')}",
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
    _print_process_output(result)
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


def _print_error(prefix: str, result: subprocess.CompletedProcess[str]) -> None:
    output = result.stderr or result.stdout or f"exit:{result.returncode}"
    print(f"{prefix}: {output}")
