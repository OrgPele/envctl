from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import sys
from collections.abc import Mapping, Sequence
from typing import Callable

from envctl_engine.runtime.command_router import Route, RouteError, parse_route
from envctl_engine.config import EngineConfig, discover_local_config_state, load_config
from envctl_engine.requirements.core import dependency_definitions
from envctl_engine.config.wizard_domain import ensure_local_config
from envctl_engine.runtime.engine_runtime import dispatch_route


def _best_effort_restore_terminal_state() -> None:
    try:
        from envctl_engine.ui.terminal_session import _restore_stdin_terminal_sane  # noqa: PLC2701

        _restore_stdin_terminal_sane()
    except Exception:
        return


def _python_dependency_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def check_prereqs(route: Route, config: EngineConfig) -> tuple[bool, str | None]:
    required_tools = {"git"}
    required_python_modules = {"rich"}
    effective_mode = _effective_prereq_mode(route)
    if route.command in {"start", "plan", "restart"} and _requires_docker(effective_mode, config):
        required_tools.add("docker")
    if config.port_availability_mode == "listener_query":
        required_tools.add("lsof")
    missing = sorted(tool for tool in required_tools if shutil.which(tool) is None)
    if missing:
        return False, f"Missing required executables: {', '.join(missing)}"
    missing_modules = sorted(module for module in required_python_modules if not _python_dependency_available(module))
    if missing_modules:
        return (
            False,
            "Missing required Python packages: "
            + ", ".join(missing_modules)
            + ". Install with: python -m pip install -r python/requirements.txt",
        )
    return True, None


def _effective_prereq_mode(route: Route) -> str:
    if route.mode != "main":
        return route.mode
    if route.command not in {"start", "plan", "restart"}:
        return route.mode
    if bool(route.flags.get("setup_worktrees")) or bool(route.flags.get("setup_worktree")):
        return "trees"
    return route.mode


def _requires_docker(mode: str, config: EngineConfig) -> bool:
    return any(
        config.requirement_enabled_for_mode(mode, definition.id)
        for definition in dependency_definitions()
    )


def run(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    shell_runner: Callable[[Sequence[str]], int] | None = None,
    dispatcher: Callable[[object, EngineConfig], int] | None = None,
) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    env_map = dict(os.environ if env is None else env)
    use_shell_runner = shell_runner is not None and dispatcher is None
    dispatcher = dispatcher or (lambda route, config: dispatch_route(route, config, env=env_map))

    try:
        try:
            route = _parse_initial_route(argv, env_map)
        except RouteError as exc:
            print(str(exc), file=sys.stderr)
            return 1

        base_dir = Path(env_map.get("RUN_REPO_ROOT") or Path.cwd()).resolve()
        local_state = discover_local_config_state(base_dir, env_map.get("ENVCTL_CONFIG_FILE"))
        if not local_state.config_file_exists and not _command_can_skip_local_config_bootstrap(route):
            try:
                bootstrap_result = ensure_local_config(
                    base_dir=base_dir,
                    env=env_map,
                )
            except RuntimeError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            if bootstrap_result.message:
                print(bootstrap_result.message)
            if route.command == "config":
                return 0

        config = load_config(env_map)
        route_env = dict(env_map)
        route_env.setdefault("ENVCTL_DEFAULT_MODE", config.default_mode)
        try:
            route = parse_route(argv, env=route_env)
        except RouteError as exc:
            print(str(exc), file=sys.stderr)
            return 1

        def invoke_route() -> int:
            if use_shell_runner:
                assert shell_runner is not None
                return int(shell_runner(argv))
            return int(dispatcher(route, config))

        if route.command in {
            "help",
            "list-commands",
            "list-targets",
            "list-trees",
            "show-config",
            "show-state",
            "explain-startup",
        }:
            try:
                return invoke_route()
            except KeyboardInterrupt:
                return 2

        if route.command in {"start", "plan", "restart"}:
            ok, reason = check_prereqs(route, config)
            if not ok:
                print(reason, file=sys.stderr)
                return 1

        try:
            code = invoke_route()
        except KeyboardInterrupt:
            return 2

        if code == 0:
            return 0
        if code in {2, 130}:
            return 2
        return 1
    finally:
        _best_effort_restore_terminal_state()


def main() -> int:
    return run()


def _parse_initial_route(argv: Sequence[str], env_map: Mapping[str, str]) -> Route:
    base_dir = Path(env_map.get("RUN_REPO_ROOT") or Path.cwd()).resolve()
    local_state = discover_local_config_state(base_dir, env_map.get("ENVCTL_CONFIG_FILE"))
    initial_env = dict(env_map)
    default_mode = local_state.parsed_values.get("ENVCTL_DEFAULT_MODE")
    if default_mode and "ENVCTL_DEFAULT_MODE" not in initial_env:
        initial_env["ENVCTL_DEFAULT_MODE"] = default_mode
    return parse_route(list(argv), env=initial_env)


def _command_can_skip_local_config_bootstrap(route: Route) -> bool:
    if route.command in {
        "help",
        "list-commands",
        "list-targets",
        "list-trees",
        "show-config",
        "show-state",
        "explain-startup",
    }:
        return True
    if route.command != "config":
        return False
    return bool(route.flags.get("stdin_json")) or bool(route.flags.get("set_values")) or bool(route.passthrough_args)


if __name__ == "__main__":
    raise SystemExit(main())
