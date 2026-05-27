from __future__ import annotations

from pathlib import Path

from envctl_engine.actions.actions_test_frontend_paths import _frontend_test_package_root
from envctl_engine.shared.node_tooling import detect_package_manager, load_package_json


def package_manager_test_command(base_dir: Path) -> list[str] | None:
    for package_root in (base_dir, base_dir / "frontend"):
        command = package_manager_test_command_for_root(package_root)
        if command is not None:
            return command
    return None


def frontend_package_manager_test_command(base_dir: Path) -> list[str] | None:
    package_root = _frontend_test_package_root(base_dir)
    if package_root is None:
        return None
    return package_manager_test_command_for_root(package_root)


def root_package_manager_test_command(base_dir: Path) -> list[str] | None:
    return package_manager_test_command_for_root(base_dir)


def package_manager_test_command_for_root(package_root: Path) -> list[str] | None:
    package_json = package_root / "package.json"
    if not package_json.is_file():
        return None
    payload = load_package_json(package_json)
    if payload is None:
        return None
    scripts = payload.get("scripts")
    if not isinstance(scripts, dict):
        return None
    test_script = scripts.get("test")
    if not isinstance(test_script, str) or not test_script.strip():
        return None
    manager = detect_package_manager(package_root)
    if manager is None:
        return None
    return [manager, "run", "test"]
