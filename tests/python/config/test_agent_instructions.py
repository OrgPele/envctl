from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from envctl_engine.config import LocalConfigState, StartupProfile
from envctl_engine.config.agent_instructions import (
    MANAGED_AGENTS_END,
    MANAGED_AGENTS_START,
    ensure_repo_agent_instructions,
    merge_repo_agent_instructions,
)
from envctl_engine.config.git_global_ignore import GlobalIgnoreStatus
from envctl_engine.config.persistence import ManagedConfigValues, PortDefaults, save_local_config


def test_agent_instructions_include_serena_and_codegraph_only_when_configured(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".serena").mkdir(parents=True)
    (repo / ".serena" / "project.yml").write_text('project_name: "demo"\n', encoding="utf-8")
    (repo / ".codegraph").mkdir()
    (repo / ".codegraph" / ".gitignore").write_text("*\n!.gitignore\n", encoding="utf-8")

    status = ensure_repo_agent_instructions(repo)

    text = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert status.updated is True
    assert MANAGED_AGENTS_START in text
    assert "## Serena" in text
    assert "## CodeGraph" in text
    assert "## Development Discipline" in text
    assert "## Envctl Workflow" in text
    assert "This project is configured for CodeGraph repo context" in text
    assert "Activate the current checkout/worktree before structural code navigation" in text
    assert "Read the owning code path before changing it" in text
    assert "smallest test that proves the real contract" in text
    assert 'use `envctl test-focused --ship-on-pass "<message>"` from inside the current worktree' in text
    assert "single envctl local validation-and-handoff command" in text
    assert "do not run standalone `envctl test-focused`" in text
    assert "stages intended non-protected changes via git add" in text
    assert "MAIN_TASK.md" not in text
    assert "pytest-xdist" not in text
    assert "ENVCTL_TEST_FOCUSED_PYTEST_WORKERS" not in text
    assert "ENVCTL_WORKTREE_CGC_INDEX" not in text


def test_agent_instructions_file_write_is_idempotent(tmp_path: Path) -> None:
    repo = tmp_path / "repo"

    first = ensure_repo_agent_instructions(repo)
    second = ensure_repo_agent_instructions(repo)

    text = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert first.updated is True
    assert second.updated is False
    assert text.count(MANAGED_AGENTS_START) == 1
    assert text.count("## Development Discipline") == 1
    assert text.count("## Envctl Workflow") == 1


def test_agent_instructions_without_tool_configs_add_general_workflow(tmp_path: Path) -> None:
    repo = tmp_path / "repo"

    status = ensure_repo_agent_instructions(repo)

    text = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert status.updated is True
    assert "## Development Discipline" in text
    assert "## Envctl Workflow" in text
    assert "## Serena" not in text
    assert "## CodeGraph" not in text
    assert "MAIN_TASK.md" not in text


def test_agent_instructions_skip_codegraph_when_explicitly_disabled(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".envctl").write_text("ENVCTL_WORKTREE_CODEGRAPH_INDEX=false\n", encoding="utf-8")
    (repo / ".codegraph").mkdir()
    (repo / ".codegraph" / ".gitignore").write_text("*\n!.gitignore\n", encoding="utf-8")

    status = ensure_repo_agent_instructions(repo)

    text = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert status.updated is True
    assert "## Envctl Workflow" in text
    assert "## CodeGraph" not in text


def test_agent_instructions_include_codegraph_when_explicitly_enabled(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".envctl").write_text("ENVCTL_WORKTREE_CODEGRAPH_INDEX=true\n", encoding="utf-8")

    status = ensure_repo_agent_instructions(repo)

    text = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert status.updated is True
    assert "## CodeGraph" in text
    assert "This project is configured for CodeGraph repo context" in text


def test_agent_instructions_do_not_duplicate_existing_sections(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".serena").mkdir(parents=True)
    (repo / ".serena" / "project.yml").write_text('project_name: "demo"\n', encoding="utf-8")
    existing = "# Project Agents\n\n## Serena\n\nExisting Serena policy.\n"

    first = merge_repo_agent_instructions(existing, base_dir=repo)
    second = merge_repo_agent_instructions(first, base_dir=repo)

    assert first == second
    assert first.count("## Serena") == 1
    assert first.count("## Development Discipline") == 1
    assert first.count("## Envctl Workflow") == 1
    assert MANAGED_AGENTS_END in first


def test_save_local_config_installs_agent_instructions(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".codegraph").mkdir()
    (repo / ".codegraph" / ".gitignore").write_text("*\n!.gitignore\n", encoding="utf-8")
    state = LocalConfigState(
        base_dir=repo,
        config_file_path=repo / ".envctl",
        config_file_exists=False,
        config_source="defaults",
        active_source_path=None,
        legacy_source_path=None,
        explicit_path=None,
        parsed_values={},
        file_text="",
    )
    values = ManagedConfigValues(
        default_mode="main",
        main_profile=StartupProfile(True, True, True, False, False, False, False),
        trees_profile=StartupProfile(True, True, True, False, False, False, False),
        port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
    )

    with patch(
        "envctl_engine.config.persistence.ensure_global_ignore_status",
        return_value=GlobalIgnoreStatus(
            code="already_present",
            updated=False,
            scope="git_global_excludes",
            target_path=None,
            managed_patterns=(".envctl*",),
            warning=None,
        ),
    ):
        result = save_local_config(local_state=state, values=values)

    assert result.agent_instructions_status is not None
    assert result.agent_instructions_status.updated is True
    assert result.agent_instructions_status.path == repo / "AGENTS.md"
    text = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert "## CodeGraph" in text
    assert "Use CodeGraph for broad structure" in text
    assert "stages intended non-protected changes via git add" in text
    assert "commits, pushes, creates/updates the PR, and reports status checks" in text
    assert "ENVCTL_WORKTREE_CGC_INDEX" not in text
