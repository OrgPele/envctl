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
    assert "CodeGraphContext (`cgc`)" in text
    assert "Do not use the legacy `codegraph` CLI" in text


def test_agent_tooling_prefers_cgc_over_legacy_codegraph() -> None:
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "CodeGraphContext (`cgc`)" in agents
    assert agents.count("## CodeGraphContext") == 1
    assert "Do not\nuse the old `codegraph` CLI" in agents
    assert "codegraph init" not in agents
    assert "codegraph_*" not in agents
    assert "CODEGRAPH_START" not in agents


def test_agent_workflow_prefers_focused_tests_and_ship_handoff() -> None:
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert agents.count("## Envctl Workflow") == 1
    assert "run `envctl test-focused` from inside the current\n  worktree" in agents
    assert 'use `envctl ship -m "<message>"` from inside the current\n  worktree' in agents
    assert "Do not run separate raw `git`/`gh` commit, push, PR, or status-check\n  commands" in agents
    assert "a successful ship is silent" in agents


def test_python_code_does_not_shell_out_to_legacy_codegraph() -> None:
    violations: list[str] = []
    allowed_compatibility_markers = {
        ENGINE_ROOT / "planning" / "worktree_code_intelligence_config.py",
    }
    legacy_command_markers = ('["codegraph"', "['codegraph'", '"codegraph ', "'codegraph ", "codegraph init")
    for path in ENGINE_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "codegraph" not in text.lower():
            continue
        if path in allowed_compatibility_markers and ".codegraphcontext" in text:
            continue
        if not any(marker in text for marker in legacy_command_markers):
            continue
        violations.append(str(path.relative_to(REPO_ROOT)))

    assert violations == []
