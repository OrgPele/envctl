from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import tempfile

from envctl_engine.actions.action_review_context import ReviewActionContext
from envctl_engine.planning import planning_feature_name

WORKTREE_PROVENANCE_PATH = Path(".envctl-state") / "worktree-provenance.json"
PLANNING_ROOT = Path("todo") / "plans"
DONE_PLANNING_ROOT = Path("todo") / "done"


@dataclass(frozen=True, slots=True)
class OriginalPlanResolution:
    path: Path | None
    source: str


def resolve_original_plan(context: ReviewActionContext) -> OriginalPlanResolution:
    if context.project_root.resolve() == context.repo_root.resolve():
        return OriginalPlanResolution(path=None, source="not_applicable")

    provenance = read_worktree_provenance(context.project_root)
    recorded_plan = str(provenance.get("plan_file", "")).strip()
    resolved = resolve_plan_file_from_record(provenance_root=context.repo_root, recorded_plan=recorded_plan)
    if resolved is not None:
        return OriginalPlanResolution(path=resolved, source="provenance")

    inferred = infer_original_plan_file(
        context.repo_root,
        feature_name=feature_name_from_project_name(context.project_name),
    )
    if inferred is not None:
        return OriginalPlanResolution(path=inferred, source="feature_inference")
    return OriginalPlanResolution(path=None, source="unresolved")


def read_worktree_provenance(project_root: Path) -> dict[str, object]:
    path = project_root / WORKTREE_PROVENANCE_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def resolve_plan_file_from_record(*, provenance_root: Path, recorded_plan: str) -> Path | None:
    normalized = str(recorded_plan or "").strip()
    if not normalized:
        return None
    relative = Path(normalized.replace("\\", "/").lstrip("./"))
    for root in (PLANNING_ROOT, DONE_PLANNING_ROOT):
        candidate = provenance_root / root / relative
        if candidate.is_file():
            return candidate.resolve()
    return None


def infer_original_plan_file(repo_root: Path, *, feature_name: str) -> Path | None:
    normalized_feature = str(feature_name).strip()
    if not normalized_feature:
        return None
    matches: list[Path] = []
    for root in (PLANNING_ROOT, DONE_PLANNING_ROOT):
        planning_root = repo_root / root
        if not planning_root.is_dir():
            continue
        for candidate in sorted(planning_root.glob("*/*.md")):
            if candidate.name == "README.md":
                continue
            relative = candidate.relative_to(planning_root)
            if planning_feature_name(str(relative).replace("\\", "/")) != normalized_feature:
                continue
            matches.append(candidate.resolve())
    if len(matches) == 1:
        return matches[0]
    return None


def feature_name_from_project_name(project_name: str) -> str:
    normalized = str(project_name).strip()
    return re.sub(r"-\d+$", "", normalized)


def original_plan_markdown_lines(resolution: OriginalPlanResolution, *, include_contents: bool) -> list[str]:
    resolved_path = str(resolution.path) if resolution.path is not None else "(unresolved)"
    lines = [
        "## Original plan file",
        resolved_path,
        "",
        "## Original plan resolution",
        resolution.source,
        "",
    ]
    if include_contents:
        plan_text = read_text(resolution.path) if resolution.path is not None else ""
        lines.extend(
            [
                "## Original plan",
                plan_text or "(unavailable)",
                "",
            ]
        )
    return lines


def augment_review_output_dir(output_dir: Path, *, original_plan: OriginalPlanResolution) -> None:
    augment_review_markdown_file(output_dir / "all.md", original_plan=original_plan, include_contents=True)
    augment_review_markdown_file(output_dir / "summary.md", original_plan=original_plan, include_contents=False)


def augment_review_markdown_file(path: Path, *, original_plan: OriginalPlanResolution, include_contents: bool) -> None:
    if not path.is_file():
        return
    original_text = read_text(path)
    if not original_text:
        return
    if "## Original plan file" in original_text:
        return
    metadata_block = "\n".join(original_plan_markdown_lines(original_plan, include_contents=include_contents)).strip()
    if not metadata_block:
        return
    lines = original_text.splitlines()
    if lines and lines[0].startswith("# "):
        title = lines[0]
        remainder = "\n".join(lines[1:]).strip()
        rewritten = f"{title}\n\n{metadata_block}\n\n{remainder}".rstrip() + "\n"
    else:
        rewritten = f"{metadata_block}\n\n{original_text.strip()}".rstrip() + "\n"
    atomic_write(path, rewritten)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        Path(temp_name).replace(path)
    finally:
        try:
            if Path(temp_name).exists():
                Path(temp_name).unlink()
        except OSError:
            pass


def first_existing_path(*paths: Path) -> Path:
    for path in paths:
        if path.is_file():
            return path
    return paths[0]
