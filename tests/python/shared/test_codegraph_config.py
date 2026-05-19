from __future__ import annotations

import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_codegraph_config_scopes_to_real_envctl_python_packages() -> None:
    config_path = REPO_ROOT / "codegraph.toml"

    assert config_path.exists(), "codegraph index should not require ad hoc -p flags"
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))

    assert config["packages"] == ["python/envctl_engine", "tests/python"]
    for package in config["packages"]:
        package_path = REPO_ROOT / package
        assert package_path.is_dir()
        assert (package_path / "__init__.py").is_file()

    assert "frontend" not in config["packages"]
    assert "backend" not in config["packages"]


def test_codegraph_validation_workflow_is_documented() -> None:
    guide = REPO_ROOT / "docs" / "developer" / "testing-and-validation.md"
    text = guide.read_text(encoding="utf-8")

    assert "codegraph index . --since HEAD~1" in text
    assert "codegraph arch-check --json" in text
    assert "python/envctl_engine" in text
    assert "tests/python" in text


def test_codegraph_arch_policy_keeps_structural_checks_and_disables_python_orphan_noise() -> None:
    policy_path = REPO_ROOT / ".arch-policies.toml"

    assert policy_path.exists(), "arch-check should use repo-specific policy tuning"
    policies = tomllib.loads(policy_path.read_text(encoding="utf-8"))["policies"]

    assert policies["orphan_detection"]["enabled"] is False
    assert "import_cycles" not in policies or policies["import_cycles"].get("enabled", True) is True
    assert "cross_package" not in policies or policies["cross_package"].get("enabled", True) is True
    assert "layer_bypass" not in policies or policies["layer_bypass"].get("enabled", True) is True
    assert "coupling_ceiling" not in policies or policies["coupling_ceiling"].get("enabled", True) is True

    suppressions = tomllib.loads(policy_path.read_text(encoding="utf-8"))["suppress"]
    assert {item["key"] for item in suppressions} == {
        "python/envctl_engine/actions/action_command_orchestrator.py",
        "python/envctl_engine/runtime/engine_runtime.py",
        "python/envctl_engine/startup/startup_orchestrator.py",
        "python/envctl_engine/ui/dashboard/orchestrator.py",
    }
    assert all(item["policy"] == "coupling_ceiling" for item in suppressions)
    assert all(item["reason"] for item in suppressions)
