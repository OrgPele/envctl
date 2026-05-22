from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping

from envctl_engine.actions.action_test_support import TestExecutionSpec, TestTargetContext, build_test_execution_specs
from envctl_engine.runtime.command_router import Route


def build_test_execution_specs_for_route(
    *,
    route: Route,
    targets: list[object],
    target_contexts: list[TestTargetContext],
    include_backend: bool,
    include_frontend: bool,
    run_all: bool,
    untested: bool,
    env: Mapping[str, str],
    config: object,
    action_replacements_builder: Callable[..., dict[str, str]],
    split_command: Callable[[str, Mapping[str, str]], list[str]],
    failed_spec_builder: Callable[..., list[TestExecutionSpec]],
    additional_service_spec_builder: Callable[..., list[TestExecutionSpec]],
    is_legacy_tree_test_script: Callable[[list[str]], bool],
) -> list[TestExecutionSpec]:
    if bool(route.flags.get("failed")):
        return failed_spec_builder(route=route, target_contexts=target_contexts)
    shared_raw = _first_non_empty(
        env.get("ENVCTL_ACTION_TEST_CMD"),
        getattr(config, "raw", {}).get("ENVCTL_ACTION_TEST_CMD", ""),
    )
    backend_raw = _first_non_empty(
        env.get("ENVCTL_BACKEND_TEST_CMD"),
        getattr(config, "raw", {}).get("ENVCTL_BACKEND_TEST_CMD", ""),
    )
    frontend_raw = _first_non_empty(
        env.get("ENVCTL_FRONTEND_TEST_CMD"),
        getattr(config, "raw", {}).get("ENVCTL_FRONTEND_TEST_CMD", ""),
    )
    service_specs = additional_service_spec_builder(
        route=route,
        targets=targets,
        target_contexts=target_contexts,
    )
    if service_specs:
        return service_specs
    return build_test_execution_specs(
        shared_raw_command=shared_raw,
        backend_raw_command=backend_raw,
        frontend_raw_command=frontend_raw,
        target_contexts=target_contexts,
        repo_root=Path(getattr(config, "base_dir")),
        include_backend=include_backend,
        include_frontend=include_frontend,
        frontend_test_path=_first_non_empty(
            getattr(config, "frontend_test_path", ""),
            env.get("ENVCTL_FRONTEND_TEST_PATH"),
            getattr(config, "raw", {}).get("ENVCTL_FRONTEND_TEST_PATH", ""),
        ),
        run_all=run_all,
        untested=untested,
        split_command=lambda command_raw, replacements: split_command(command_raw, dict(replacements)),
        replacements_for_target=lambda target: action_replacements_builder(targets, target=target),
        is_legacy_tree_test_script=is_legacy_tree_test_script,
    )


def _first_non_empty(*values: object) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None
