from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


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
