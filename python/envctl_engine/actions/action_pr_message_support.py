from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from pathlib import Path
import re
import tempfile
from typing import Any, Callable

GitOutput = Callable[[Path, list[str]], str]


@dataclass(frozen=True, slots=True)
class PullRequestMessageContext:
    project_root: Path
    project_name: str
    env: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class PullRequestMessageBuilder:
    context: Any
    git_root: Path
    head_branch: str
    base_branch: str = ""
    git_output: GitOutput | None = None
    max_chars: int = 48_000

    def title(self) -> str:
        explicit = normalize_title_text(str(self.context.env.get("ENVCTL_PR_TITLE", "")))
        if explicit:
            return self._truncate_title(explicit)

        main_task_title = main_task_title_from_project(self.context.project_root)
        if main_task_title:
            return self._truncate_title(main_task_title)

        subject = self._git_output(["log", "-1", "--pretty=%s"]).strip()
        title = subject or f"{self.context.project_name}: {self.head_branch}"
        title = " ".join(title.split())
        return self._truncate_title(title)

    def body(self) -> str:
        explicit_body = normalize_text_block(str(self.context.env.get("ENVCTL_PR_BODY", "")))
        if explicit_body:
            return truncate_pr_body(explicit_body, max_chars=self.max_chars)

        main_task = self.context.project_root / "MAIN_TASK.md"
        if main_task.is_file() and file_has_text(main_task):
            return truncate_pr_body(read_text(main_task), max_chars=self.max_chars)

        commits = self.commit_messages()
        if commits:
            return truncate_pr_body(commits, max_chars=self.max_chars)
        return ""

    def commit_messages(self) -> str:
        range_spec = self.commit_range()
        raw = self._git_output(["log", "--reverse", "--no-merges", "--format=%h%x1f%s%x1f%b%x1e", range_spec])
        entries = commit_message_entries(raw)
        if not entries:
            return ""
        return truncate_recent_entries(
            entries,
            max_chars=self.max_chars - 8_000,
            notice="[truncated to most recent commit messages]",
        )

    def diff_stat(self) -> str:
        diff_args = ["diff", "--stat"]
        if self.base_branch:
            diff_args.append(self.compare_range())
        diff_stat = self._git_output(diff_args).strip()
        return truncate_pr_body(diff_stat, max_chars=8_000) if diff_stat else ""

    def commit_range(self) -> str:
        head_ref = self.head_branch or "HEAD"
        if not self.base_branch:
            return head_ref
        base_ref = self.base_ref()
        merge_base = self._git_output(["merge-base", head_ref, base_ref]).strip()
        if merge_base:
            return f"{merge_base}..{head_ref}"
        return f"{base_ref}..{head_ref}"

    def compare_range(self) -> str:
        head_ref = self.head_branch or "HEAD"
        if not self.base_branch:
            return head_ref
        return f"{self.base_ref()}...{head_ref}"

    def base_ref(self) -> str:
        remote_candidate = f"origin/{self.base_branch}"
        if self._git_output(["rev-parse", "--verify", remote_candidate]).strip():
            return remote_candidate
        if self._git_output(["rev-parse", "--verify", self.base_branch]).strip():
            return self.base_branch
        return self.base_branch

    def _truncate_title(self, value: str) -> str:
        return value[: self.max_chars].rstrip() or self.head_branch

    def _git_output(self, args: list[str]) -> str:
        if self.git_output is None:
            return ""
        return self.git_output(self.git_root, args)


def pr_title(
    context: Any,
    git_root: Path,
    head_branch: str,
    *,
    git_output: GitOutput,
    max_chars: int,
) -> str:
    return PullRequestMessageBuilder(
        context=context,
        git_root=git_root,
        head_branch=head_branch,
        git_output=git_output,
        max_chars=max_chars,
    ).title()


def pr_body(
    context: Any,
    git_root: Path,
    head_branch: str,
    base_branch: str,
    *,
    git_output: GitOutput,
    max_chars: int,
) -> str:
    return PullRequestMessageBuilder(
        context=context,
        git_root=git_root,
        head_branch=head_branch,
        base_branch=base_branch,
        git_output=git_output,
        max_chars=max_chars,
    ).body()


def pr_commit_messages(
    git_root: Path,
    *,
    head_branch: str,
    base_branch: str,
    git_output: GitOutput,
    max_chars: int,
) -> str:
    return PullRequestMessageBuilder(
        context=_empty_message_context(git_root),
        git_root=git_root,
        head_branch=head_branch,
        base_branch=base_branch,
        git_output=git_output,
        max_chars=max_chars,
    ).commit_messages()


def commit_message_entries(raw: str) -> list[str]:
    entries: list[str] = []
    for chunk in raw.split("\x1e"):
        normalized = chunk.strip()
        if not normalized:
            continue
        parts = normalized.split("\x1f", 2)
        short_hash = parts[0].strip() if len(parts) > 0 else ""
        subject = " ".join((parts[1] if len(parts) > 1 else "").split()).strip()
        body = normalize_text_block(parts[2] if len(parts) > 2 else "")
        if not short_hash and not subject and not body:
            continue
        header = f"- {subject or short_hash}"
        if short_hash and subject:
            header = f"- {subject} ({short_hash})"
        entry_lines = [header]
        if body:
            entry_lines.append("")
            entry_lines.extend(f"  {line}" if line else "" for line in body.splitlines())
        entries.append("\n".join(entry_lines).strip())
    return entries


def pr_diff_stat(
    git_root: Path,
    *,
    head_branch: str,
    base_branch: str,
    git_output: GitOutput,
) -> str:
    return PullRequestMessageBuilder(
        context=_empty_message_context(git_root),
        git_root=git_root,
        head_branch=head_branch,
        base_branch=base_branch,
        git_output=git_output,
    ).diff_stat()


def pr_commit_range(git_root: Path, *, head_branch: str, base_branch: str, git_output: GitOutput) -> str:
    return PullRequestMessageBuilder(
        context=_empty_message_context(git_root),
        git_root=git_root,
        head_branch=head_branch,
        base_branch=base_branch,
        git_output=git_output,
    ).commit_range()


def pr_compare_range(git_root: Path, *, head_branch: str, base_branch: str, git_output: GitOutput) -> str:
    return PullRequestMessageBuilder(
        context=_empty_message_context(git_root),
        git_root=git_root,
        head_branch=head_branch,
        base_branch=base_branch,
        git_output=git_output,
    ).compare_range()


def pr_base_ref(git_root: Path, base_branch: str, *, git_output: GitOutput) -> str:
    return PullRequestMessageBuilder(
        context=_empty_message_context(git_root),
        git_root=git_root,
        head_branch="HEAD",
        base_branch=base_branch,
        git_output=git_output,
    ).base_ref()


def _empty_message_context(project_root: Path) -> PullRequestMessageContext:
    return PullRequestMessageContext(project_root=project_root, project_name=project_root.name or "project", env={})


def recent_text_excerpt(text: str, *, max_chars: int) -> str:
    cleaned = normalize_text_block(text)
    if len(cleaned) <= max_chars:
        return cleaned
    notice = "[truncated to most recent changelog content]\n\n"
    tail_limit = max(0, max_chars - len(notice))
    tail = cleaned[-tail_limit:] if tail_limit else ""
    if "\n" in tail:
        tail = tail.split("\n", 1)[1]
    return f"{notice}{tail}".strip()


def truncate_recent_entries(entries: list[str], *, max_chars: int, notice: str) -> str:
    cleaned_entries = [entry.strip() for entry in entries if entry.strip()]
    if not cleaned_entries:
        return ""
    full_text = "\n\n".join(cleaned_entries).strip()
    if len(full_text) <= max_chars:
        return full_text
    notice_block = f"{notice}\n\n"
    keep_limit = max(0, max_chars - len(notice_block))
    kept: list[str] = []
    current_len = 0
    for entry in reversed(cleaned_entries):
        extra = len(entry) + (2 if kept else 0)
        if current_len + extra > keep_limit:
            break
        kept.append(entry)
        current_len += extra
    if not kept:
        tail = full_text[-keep_limit:] if keep_limit else ""
        if "\n" in tail:
            tail = tail.split("\n", 1)[1]
        return f"{notice_block}{tail}".strip()
    kept.reverse()
    return f"{notice_block}{'\n\n'.join(kept)}".strip()


def latest_changelog_commit_message(text: str, *, max_chars: int) -> str:
    normalized = normalize_text_block(text)
    if not normalized:
        return ""
    lines = normalized.splitlines()
    latest_heading = ""
    section_lines: list[str] = []
    inside_latest_section = False
    for line in lines:
        if line.startswith("## "):
            if inside_latest_section:
                break
            latest_heading = line[3:].strip()
            inside_latest_section = True
            continue
        if inside_latest_section:
            section_lines.append(line)
    if not inside_latest_section:
        return truncate_pr_body(normalized, max_chars=max_chars)
    body = normalize_text_block("\n".join(section_lines))
    if body:
        subject, remainder = select_changelog_subject(body, fallback=latest_heading)
        if not subject:
            subject = latest_heading
        commit_message = subject if not remainder else f"{subject}\n\n{remainder}"
        return truncate_pr_body(commit_message, max_chars=max_chars)
    if latest_heading:
        return truncate_pr_body(latest_heading, max_chars=max_chars)
    return ""


def select_changelog_subject(body: str, *, fallback: str) -> tuple[str, str]:
    lines = body.splitlines()
    subject_index = -1
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue
        if re.match(r"^#{1,6}\s+", line):
            continue
        subject_index = index
        break
    if subject_index == -1:
        return fallback.strip(), ""
    subject = lines[subject_index].strip()
    remainder = "\n".join(lines[subject_index + 1 :]).strip()
    return subject, remainder


def main_task_title_from_project(project_root: Path) -> str:
    main_task = project_root / "MAIN_TASK.md"
    if not main_task.is_file():
        return ""
    text = read_text(main_task)
    if not text.strip():
        return ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("# "):
            continue
        return normalize_title_text(line[2:])
    return ""


def normalize_title_text(text: str) -> str:
    cleaned = text.replace("`", " ")
    cleaned = " ".join(cleaned.split())
    return cleaned.strip()


def truncate_pr_body(text: str, *, max_chars: int) -> str:
    cleaned = normalize_text_block(text)
    if len(cleaned) <= max_chars:
        return cleaned
    notice = "\n\n[truncated]"
    keep = max(0, max_chars - len(notice))
    return f"{cleaned[:keep].rstrip()}{notice}".strip()


def normalize_text_block(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = [line.rstrip() for line in normalized.splitlines()]
    return "\n".join(lines).strip()


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def write_pr_body_file(body: str) -> Path:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".md") as handle:
        handle.write(body)
        return Path(handle.name)


def file_has_text(path: Path) -> bool:
    try:
        return bool(path.read_text(encoding="utf-8").strip())
    except OSError:
        return False
