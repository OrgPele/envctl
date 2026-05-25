from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
from typing import Callable, Sequence

from envctl_engine.actions import actions_test_bootstrap as bootstrap_support
from envctl_engine.actions import actions_test_command_discovery as command_discovery
from envctl_engine.actions.actions_test_classification import (
    build_test_args,
    classify_test_command_source,
    is_package_test_command,
    is_pytest_command,
    is_unittest_command,
)
from envctl_engine.actions.actions_test_frontend_paths import (
    _directory_contains_test_files,
    _frontend_dir_name_from_package_root,
    _frontend_package_root_for_config,
    _frontend_test_package_root,
    _frontend_test_path_candidates,
    _suggest_frontend_test_path_for_package_root,
    append_frontend_test_path,
    canonicalize_frontend_test_path,
    normalize_frontend_test_path,
)
from envctl_engine.actions.actions_test_models import (
    SuggestionConfidence,
    SuggestionTarget,
    TestCommandSpec,
    TestCommandSuggestion,
    TestPathSuggestion,
)
from envctl_engine.shared.node_tooling import detect_python_bin

__all__ = [
    "SuggestionConfidence",
    "SuggestionTarget",
    "TestCommandSpec",
    "TestCommandSuggestion",
    "TestPathSuggestion",
    "_directory_contains_test_files",
    "_frontend_dir_name_from_package_root",
    "_frontend_package_root_for_config",
    "_frontend_test_package_root",
    "_frontend_test_path_candidates",
    "_suggest_frontend_test_path_for_package_root",
    "append_frontend_test_path",
    "build_test_args",
    "canonicalize_frontend_test_path",
    "classify_test_command_source",
    "default_test_command",
    "default_test_commands",
    "ensure_repo_local_test_prereqs",
    "frontend_test_path_suggestions",
    "is_package_test_command",
    "is_pytest_command",
    "is_unittest_command",
    "normalize_frontend_test_path",
    "suggest_action_test_command",
    "suggest_backend_test_command",
    "suggest_frontend_test_command",
    "suggest_frontend_test_path",
    "test_command_suggestions",
]


def default_test_command(base_dir: Path) -> list[str] | None:
    return command_discovery.default_test_command(base_dir, detect_python_bin_fn=detect_python_bin)


def suggest_action_test_command(base_dir: Path) -> str | None:
    return command_discovery.suggest_action_test_command(base_dir, detect_python_bin_fn=detect_python_bin)


def suggest_backend_test_command(base_dir: Path) -> str | None:
    return command_discovery.suggest_backend_test_command(base_dir, detect_python_bin_fn=detect_python_bin)


def suggest_frontend_test_command(base_dir: Path) -> str | None:
    return command_discovery.suggest_frontend_test_command(base_dir)


def suggest_frontend_test_path(base_dir: Path) -> str | None:
    return command_discovery.suggest_frontend_test_path(base_dir)


def test_command_suggestions(
    base_dir: Path,
    *,
    include_backend: bool = True,
    include_frontend: bool = True,
    frontend_test_path: str | None = None,
) -> list[TestCommandSuggestion]:
    return command_discovery.test_command_suggestions(
        base_dir,
        include_backend=include_backend,
        include_frontend=include_frontend,
        frontend_test_path=frontend_test_path,
        detect_python_bin_fn=detect_python_bin,
    )


def frontend_test_path_suggestions(base_dir: Path) -> list[TestPathSuggestion]:
    return command_discovery.frontend_test_path_suggestions(base_dir)


def default_test_commands(
    base_dir: Path,
    *,
    include_backend: bool = True,
    include_frontend: bool = True,
    frontend_test_path: str | None = None,
) -> list[TestCommandSpec]:
    return command_discovery.default_test_commands(
        base_dir,
        include_backend=include_backend,
        include_frontend=include_frontend,
        frontend_test_path=frontend_test_path,
        detect_python_bin_fn=detect_python_bin,
    )


def _command_text(command: Sequence[str]) -> str:
    return command_discovery.command_text(command)


def _test_command_suggestion(
    spec: TestCommandSpec,
    *,
    target: SuggestionTarget,
    is_default: bool,
) -> TestCommandSuggestion:
    return command_discovery.test_command_suggestion(spec, target=target, is_default=is_default)


def ensure_repo_local_test_prereqs(
    project_root: Path,
    *,
    emit_status: Callable[[str], None] | None = None,
) -> None:
    bootstrap_support.ensure_repo_local_test_prereqs(
        project_root,
        emit_status=emit_status,
        run_process=subprocess.run,
        python_executable=sys.executable,
        which_fn=shutil.which,
    )


def _emit_bootstrap_status(emit_status: Callable[[str], None] | None, message: str) -> None:
    bootstrap_support.emit_bootstrap_status(emit_status, message)


def _is_envctl_repo(project_root: Path) -> bool:
    return bootstrap_support.is_envctl_repo(project_root)


def _repo_local_test_python_ready(python_bin: Path) -> bool:
    return bootstrap_support.repo_local_test_python_ready(python_bin, run_process=subprocess.run)


def _bootstrap_python_executable() -> str:
    return bootstrap_support.bootstrap_python_executable(python_executable=sys.executable, which_fn=shutil.which)


def _run_bootstrap_command(command: list[str], *, cwd: Path) -> None:
    bootstrap_support.run_bootstrap_command(command, cwd=cwd, run_process=subprocess.run)


def _root_unittest_discover_command(base_dir: Path) -> list[str] | None:
    return command_discovery.root_unittest_discover_command(base_dir, detect_python_bin_fn=detect_python_bin)


def _root_pytest_command(base_dir: Path) -> list[str] | None:
    return command_discovery.root_pytest_command(base_dir, detect_python_bin_fn=detect_python_bin)


def _root_has_pytest_config(base_dir: Path) -> bool:
    return command_discovery.root_has_pytest_config(base_dir)


def _backend_pytest_command(base_dir: Path) -> list[str] | None:
    return command_discovery.backend_pytest_command(base_dir, detect_python_bin_fn=detect_python_bin)


def _package_manager_test_command(base_dir: Path) -> list[str] | None:
    return command_discovery.package_manager_test_command(base_dir)


def _frontend_package_manager_test_command(base_dir: Path) -> list[str] | None:
    return command_discovery.frontend_package_manager_test_command(base_dir)


def _root_package_manager_test_command(base_dir: Path) -> list[str] | None:
    return command_discovery.root_package_manager_test_command(base_dir)


def _package_manager_test_command_for_root(package_root: Path) -> list[str] | None:
    return command_discovery.package_manager_test_command_for_root(package_root)
