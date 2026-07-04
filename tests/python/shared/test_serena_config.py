from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
ENGINE_ROOT = REPO_ROOT / "python" / "envctl_engine"


def test_serena_config_scopes_envctl_as_python_project() -> None:
    config_path = REPO_ROOT / ".serena" / "project.yml"

    assert config_path.exists(), "Serena project config should be versioned for repo-local symbol navigation"
    text = config_path.read_text(encoding="utf-8")

    assert 'project_name: "envctl"' in text
    assert "  - python" in text
    assert "trees/**" in text
    assert "initial_prompt:" in text
    assert "Serena's symbolic tools" in text


def test_serena_workflow_is_documented_as_symbol_navigation() -> None:
    guide = REPO_ROOT / "docs" / "developer" / "testing-and-validation.md"
    text = guide.read_text(encoding="utf-8")

    assert "serena project health-check" in text
    assert "symbol/reference layer" in text
    assert "CodeGraph is the repo-wide graph context layer" in text
    assert "codegraph_index_succeeded: true" in text


def test_agent_tooling_does_not_unconditionally_inject_codegraph() -> None:
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "## CodeGraph" not in agents
    assert "ENVCTL_WORKTREE_CGC_INDEX" not in agents
    assert "CODEGRAPH_START" not in agents


def test_agent_tooling_activates_serena_against_current_checkout() -> None:
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "Activate the current checkout/worktree path" in agents
    assert "/Users/kfiramar/projects/envctl" not in agents


def test_agent_workflow_prefers_focused_tests_and_ship_handoff() -> None:
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert agents.count("## Development Discipline") == 1
    assert agents.count("## Envctl Workflow") == 1
    assert 'PATH="$PWD/.venv/bin:$PATH" envctl ...' in agents
    assert "run the current checkout instead of an installed `envctl`" in agents
    assert "Read the owning code path before changing it" in agents
    assert "smallest test that proves the real\n  contract" in agents
    assert "MAIN_TASK.md" not in agents
    assert "run `envctl test-focused` from inside the current\n  worktree" in agents
    assert 'use `envctl test-focused --ship-on-pass "<message>"` from inside\n  the current worktree' in agents
    assert "stages\n  intended non-protected changes via git add" in agents
    assert "commits, pushes, creates/updates\n  the PR, and reports status checks" in agents
    assert "successful ship results stay silent" in agents
    assert "pytest-xdist" not in agents
    assert "ENVCTL_ACTION_TEST_PYTEST_WORKERS" not in agents


def test_python_code_uses_codegraph_only_in_worktree_code_intelligence() -> None:
    violations: list[str] = []
    allowed_compatibility_markers = {
        ENGINE_ROOT / "planning" / "worktree_code_intelligence_config.py",
        ENGINE_ROOT / "planning" / "worktree_code_intelligence.py",
        ENGINE_ROOT / "planning" / "worktree_code_intelligence_codegraph.py",
    }
    legacy_command_markers = ('["codegraph"', "['codegraph'", '"codegraph ', "'codegraph ", "codegraph init")
    for path in ENGINE_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "codegraph" not in text.lower():
            continue
        if path in allowed_compatibility_markers:
            continue
        if not any(marker in text for marker in legacy_command_markers):
            continue
        violations.append(str(path.relative_to(REPO_ROOT)))

    assert violations == []
