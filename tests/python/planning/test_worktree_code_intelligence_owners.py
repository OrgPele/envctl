from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from envctl_engine.planning.worktree_code_intelligence_cgc import (
    index_worktree_with_cgc,
    reuse_or_index_worktree_with_cgc,
)
from envctl_engine.planning.worktree_code_intelligence_config import (
    WORKTREE_CGC_INDEX_MODE_AUTO,
    WORKTREE_CGC_INDEX_MODE_DISABLED,
    WORKTREE_CGC_INDEX_MODE_ENABLED,
    worktree_cgc_index_mode,
    worktree_code_intelligence_identity,
)
from envctl_engine.planning.worktree_code_intelligence_files import (
    copy_worktree_code_intelligence_file,
    copy_worktree_serena_project_file,
    rewrite_serena_project_name,
)
from envctl_engine.planning.worktree_code_intelligence_metadata import (
    write_worktree_code_intelligence_metadata,
)
from envctl_engine.planning.worktree_code_intelligence_models import WorktreeCodeIntelligenceIdentity


@dataclass
class _Config:
    base_dir: Path
    raw: dict[str, str]


class _Runner:
    def __init__(self, results: dict[tuple[str, ...], subprocess.CompletedProcess[str]]) -> None:
        self.results = results
        self.calls: list[tuple[list[str], Path | None]] = []

    def run(self, cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None, timeout: float) -> Any:
        _ = env, timeout
        command = [str(token) for token in cmd]
        self.calls.append((command, cwd))
        return self.results[tuple(command)]


class _Runtime:
    def __init__(
        self,
        repo: Path,
        *,
        env: dict[str, str] | None = None,
        runner: _Runner | None = None,
        command_exists: bool = True,
    ) -> None:
        self.config = _Config(base_dir=repo, raw={})
        self.env = env or {}
        self.process_runner = runner
        self.command_exists = command_exists
        self.emitted: list[dict[str, object]] = []

    def _command_exists(self, name: str) -> bool:
        return name == "cgc" and self.command_exists

    def _command_env(self, *, port: int) -> dict[str, str]:
        return {"PORT": str(port)}

    def _emit(self, event: str, **payload: object) -> None:
        self.emitted.append({"event": event, **payload})


def _trees_root_for_worktree(_runtime: object, target: Path) -> Path:
    return target.parents[2]


def test_identity_templates_are_sanitized_from_repo_and_worktree_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    target = repo / "trees" / "feature.a/with spaces" / "7"
    (repo / ".serena").mkdir(parents=True)
    (repo / ".serena" / "project.yml").write_text("project_name: Envctl Main\n", encoding="utf-8")
    runtime = _Runtime(
        repo,
        env={
            "ENVCTL_WORKTREE_SERENA_PROJECT_TEMPLATE": "serena_{project}_{worktree}",
            "ENVCTL_WORKTREE_CGC_CONTEXT_TEMPLATE": "ctx_{project}_{feature}_{iteration}",
        },
    )

    identity = worktree_code_intelligence_identity(
        runtime,
        target=target,
        trees_root_for_worktree=_trees_root_for_worktree,
    )

    assert identity.worktree_name == "feature-a_with_spaces-7"
    assert identity.feature == "feature-a_with_spaces"
    assert identity.iteration == "7"
    assert identity.serena_project_name == "serena_envctl_main_feature-a_with_spaces-7"
    assert identity.cgc_context == "ctx_Envctl_Main_feature-a_with_spaces_7"


def test_cgc_index_mode_auto_requires_cgc_artifacts(tmp_path: Path) -> None:
    runtime = _Runtime(tmp_path / "repo")
    runtime.config.base_dir.mkdir()

    assert worktree_cgc_index_mode(runtime) == WORKTREE_CGC_INDEX_MODE_DISABLED

    (runtime.config.base_dir / ".cgcignore").write_text(".git/\n", encoding="utf-8")
    assert worktree_cgc_index_mode(runtime) == WORKTREE_CGC_INDEX_MODE_DISABLED

    runtime.env["ENVCTL_WORKTREE_CGC_INDEX"] = "auto"
    assert worktree_cgc_index_mode(runtime) == WORKTREE_CGC_INDEX_MODE_AUTO

    runtime.env["ENVCTL_WORKTREE_CGC_INDEX"] = "true"
    assert worktree_cgc_index_mode(runtime) == WORKTREE_CGC_INDEX_MODE_ENABLED


def test_serena_project_copy_rewrites_name_and_reports_success(tmp_path: Path) -> None:
    source = tmp_path / "source.yml"
    target = tmp_path / "target" / "project.yml"
    events: list[dict[str, object]] = []
    source.write_text("project_name: old\nlanguage: python\n", encoding="utf-8")

    copied = copy_worktree_serena_project_file(
        source=source,
        target=target,
        project_name="new-name",
        emit=lambda event, **payload: events.append({"event": event, **payload}),
    )

    assert copied is True
    assert target.read_text(encoding="utf-8") == "project_name: new-name\nlanguage: python\n"
    assert events == [
        {
            "event": "setup.worktree.code_intelligence.serena_config",
            "target": str(target),
            "project_name": "new-name",
            "success": True,
        }
    ]


def test_code_intelligence_copy_does_not_overwrite_existing_target(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.write_text("new\n", encoding="utf-8")
    target.write_text("existing\n", encoding="utf-8")

    assert copy_worktree_code_intelligence_file(source=source, target=target) is False
    assert target.read_text(encoding="utf-8") == "existing\n"
    assert rewrite_serena_project_name("language: python\n", project_name="repo-tree") == (
        "project_name: repo-tree\nlanguage: python\n"
    )


def test_cgc_reuse_uses_source_context_without_indexing_when_source_root_matches(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    target = repo / "trees" / "feature-a" / "1"
    repo.mkdir(parents=True)
    target.mkdir(parents=True)
    (repo / ".serena").mkdir()
    (repo / ".serena" / "project.yml").write_text("project_name: envctl\n", encoding="utf-8")
    runner = _Runner(
        {
            ("cgc", "list", "--context", "Envctl"): subprocess.CompletedProcess(
                args=["cgc", "list", "--context", "Envctl"],
                returncode=0,
                stdout=f"Envctl {repo.resolve()}\n",
                stderr="",
            )
        }
    )
    runtime = _Runtime(repo, runner=runner)

    result = reuse_or_index_worktree_with_cgc(runtime, target=target, context="Envctl-feature-a-1")

    assert [call[0] for call in runner.calls] == [["cgc", "list", "--context", "Envctl"]]
    assert result["cgc_active_context"] == "Envctl"
    assert result["cgc_index_skipped_reason"] == "source_context_reused"
    assert result["cgc_index_requested"] is False
    assert runtime.emitted[-1]["event"] == "setup.worktree.code_intelligence.cgc_reuse"
    assert runtime.emitted[-1]["success"] is True


def test_cgc_index_treats_existing_context_as_managed_and_continues_to_index(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    target = repo / "trees" / "feature-a" / "1"
    target.mkdir(parents=True)
    runner = _Runner(
        {
            (
                "cgc",
                "context",
                "create",
                "Repo-feature-a-1",
                "--database",
                "kuzudb",
            ): subprocess.CompletedProcess(
                args=["cgc"],
                returncode=1,
                stdout="",
                stderr="context already exists",
            ),
            (
                "cgc",
                "index",
                str(target),
                "--context",
                "Repo-feature-a-1",
            ): subprocess.CompletedProcess(args=["cgc"], returncode=0, stdout="", stderr=""),
        }
    )
    runtime = _Runtime(repo, runner=runner)

    result = index_worktree_with_cgc(runtime, target=target, context="Repo-feature-a-1")

    assert [call[0] for call in runner.calls] == [
        ["cgc", "context", "create", "Repo-feature-a-1", "--database", "kuzudb"],
        ["cgc", "index", str(target), "--context", "Repo-feature-a-1"],
    ]
    assert result["cgc_context_already_exists"] is True
    assert result["cgc_context_managed"] is True
    assert result["cgc_index_succeeded"] is True


def test_metadata_writer_preserves_cgc_result_overrides(tmp_path: Path) -> None:
    target = tmp_path / "tree"
    target.mkdir()

    write_worktree_code_intelligence_metadata(
        target=target,
        identity=WorktreeCodeIntelligenceIdentity(
            worktree_name="feature-a-1",
            feature="feature-a",
            iteration="1",
            cgc_context="Repo-feature-a-1",
            serena_project_name="repo-feature-a-1",
        ),
        copied_files={".serena/project.yml": True},
        cgc_database="kuzudb",
        cgc_result={"cgc_active_context": "Repo", "cgc_index_mode": "auto"},
    )

    payload = json.loads((target / ".envctl-state" / "code-intelligence.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["cgc_context"] == "Repo-feature-a-1"
    assert payload["cgc_active_context"] == "Repo"
    assert payload["files"] == {".serena/project.yml": True}
