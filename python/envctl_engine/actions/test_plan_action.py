from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path
from typing import Iterable, Mapping

from envctl_engine.config.local_artifacts import is_envctl_local_artifact_path

_PREFIX_TESTS: tuple[tuple[str, str, str], ...] = (
    ("python/envctl_engine/planning/", "tests/python/planning", "planning engine change"),
    ("python/envctl_engine/actions/", "tests/python/actions", "action command change"),
    ("python/envctl_engine/config/", "tests/python/config", "configuration change"),
    ("python/envctl_engine/startup/", "tests/python/startup", "startup change"),
    ("python/envctl_engine/runtime/", "tests/python/runtime", "runtime command change"),
    ("python/envctl_engine/requirements/", "tests/python/requirements", "requirements change"),
    ("python/envctl_engine/ui/", "tests/python/ui", "UI command change"),
)

_PROMPT_PREFIX = "python/envctl_engine/runtime/prompt_templates/"
_PROMPT_TEST = "tests/python/runtime/test_prompt_install_support.py"


def build_test_plan(
    *,
    repo_root: Path,
    project_root: Path,
    project_name: str,
    changed_files: Iterable[str] | None = None,
) -> dict[str, object]:
    repo_root = Path(repo_root).resolve()
    project_root = Path(project_root).resolve()
    raw_changed_files = changed_files if changed_files is not None else _collect_changed_files(project_root)
    files = _normalize_changed_files(raw_changed_files)
    commands: list[dict[str, object]] = []
    seen_commands: set[str] = set()

    def add(command: str, *, confidence: str, reason: str, files_for_reason: Iterable[str]) -> None:
        if command in seen_commands:
            return
        seen_commands.add(command)
        commands.append(
            {
                "command": command,
                "confidence": confidence,
                "reason": reason,
                "matched_files": list(files_for_reason),
            }
        )

    for prefix, test_path, reason in _PREFIX_TESTS:
        matched = [path for path in files if path.startswith(prefix)]
        if matched:
            add(f"uv run --extra dev pytest -q {test_path}", confidence="high", reason=reason, files_for_reason=matched)

    prompt_matches = [path for path in files if path.startswith(_PROMPT_PREFIX)]
    if prompt_matches:
        add(
            f"uv run --extra dev pytest -q {_PROMPT_TEST}",
            confidence="high",
            reason="prompt template change",
            files_for_reason=prompt_matches,
        )

    script_matches = [path for path in files if path.startswith("scripts/") or path.endswith(".json")]
    if script_matches:
        add(
            "uv run --extra dev pytest -q tests/python/runtime/test_release_shipability_gate.py "
            "tests/python/runtime/test_release_shipability_gate_cli.py",
            confidence="medium",
            reason="contract-affecting script or JSON change",
            files_for_reason=script_matches,
        )

    ruff_files = [
        path
        for path in files
        if path.endswith(".py")
        and (path.startswith("python/") or path.startswith("tests/") or path.startswith("scripts/"))
    ]
    if ruff_files:
        add(
            "uv run --extra dev ruff check " + " ".join(shlex.quote(path) for path in ruff_files),
            confidence="high",
            reason="Python files changed",
            files_for_reason=ruff_files,
        )

    if not commands:
        add(
            "uv run --extra dev pytest -q tests/python",
            confidence="low",
            reason="no focused mapping matched changed files",
            files_for_reason=files,
        )

    touched_areas = {path.split("/", 3)[2] for path in files if path.startswith("python/envctl_engine/")}
    contract_affecting = bool(script_matches)
    broad = len(touched_areas) > 1 or contract_affecting
    reason = "contract-affecting changes" if contract_affecting else "multiple envctl engine areas changed"
    return {
        "contract_version": "envctl.test_plan.v1",
        "project": project_name,
        "repo_root": str(repo_root),
        "project_root": str(project_root),
        "changed_files": files,
        "commands": commands,
        "full_gate": {
            "recommended": broad,
            "reason": reason if broad else "focused checks cover the changed area",
            "command": "uv run --extra dev pytest -q tests/python",
        },
    }


def run_test_plan_action(context: object, *, json_output: bool = False) -> int:
    repo_root = Path(getattr(context, "repo_root")).resolve()
    project_root = Path(getattr(context, "project_root")).resolve()
    project_name = str(getattr(context, "project_name", project_root.name))
    payload = build_test_plan(repo_root=repo_root, project_root=project_root, project_name=project_name)
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for command in payload["commands"]:
            if isinstance(command, Mapping):
                print(command.get("command", ""))
    return 0


def _collect_changed_files(project_root: Path) -> tuple[str, ...]:
    groups = (
        ["git", "diff", "--name-only"],
        ["git", "diff", "--cached", "--name-only"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    )
    paths: list[str] = []
    for args in groups:
        completed = subprocess.run(args, cwd=str(project_root), text=True, capture_output=True, check=False)
        if completed.returncode != 0:
            continue
        paths.extend(completed.stdout.splitlines())
    return tuple(paths)


def _normalize_changed_files(paths: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        path = str(raw or "").strip().replace("\\", "/")
        while path.startswith("./"):
            path = path[2:]
        if not path or is_envctl_local_artifact_path(path) or path in seen:
            continue
        seen.add(path)
        normalized.append(path)
    return sorted(normalized)
