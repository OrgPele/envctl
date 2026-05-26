from __future__ import annotations

from envctl_engine.runtime.command_catalog import DEFAULT_HEADLESS_COMMANDS
from envctl_engine.runtime.command_models import RouteError

TRUTHY_TOKENS = frozenset({"true", "1", "yes", "on"})
FALSY_TOKENS = frozenset({"false", "0", "no", "off"})


def handle_special_flag(flags: dict[str, object], token: str) -> None:
    if token == "--backend":
        set_runtime_scope(flags, "backend")
    elif token == "--frontend":
        set_runtime_scope(flags, "frontend")
    elif token in {"--both", "--fullstack"}:
        set_runtime_scope(flags, "fullstack")
    elif token in {"--dependencies", "--deps"}:
        set_runtime_scope(flags, "dependencies")
    elif token == "--entire-system":
        set_runtime_scope(flags, "entire-system")
    elif token == "--blast-keep-worktree-volumes":
        flags["blast_keep_worktree_volumes"] = True
    elif token == "--blast-remove-worktree-volumes":
        flags["blast_keep_worktree_volumes"] = False
    elif token == "--blast-remove-main-volumes":
        flags["blast_remove_main_volumes"] = True
    elif token == "--blast-keep-main-volumes":
        flags["blast_remove_main_volumes"] = False
    elif token in {"--stop-all-remove-volumes", "--remove-volumes"}:
        flags["stop_all_remove_volumes"] = True
    elif token == "--no-parallel-trees":
        flags["parallel_trees"] = False
    elif token in {"--test-sequential", "--no-test-parallel"}:
        flags["test_parallel"] = False
    elif token in {"--service-sequential", "--no-service-parallel"}:
        flags["service_parallel"] = False
    elif token in {"--service-prep-sequential", "--no-service-prep-parallel"}:
        flags["service_prep_parallel"] = False
    elif token in {
        "--deps-sequential",
        "--sequential-deps",
        "--requirements-sequential",
        "--no-requirements-parallel",
    }:
        flags["requirements_parallel"] = False
    elif token == "--ignore-service-deps":
        flags["ignore_service_deps"] = True
    elif token == "--only-backend":
        flags["launch_backend"] = True
        flags["launch_frontend"] = False
        flags["launch_dependencies"] = False
    elif token == "--only-frontend":
        flags["launch_backend"] = False
        flags["launch_frontend"] = True
        flags["launch_dependencies"] = False
    elif token in {"--no-dependencies", "--no-deps"}:
        flags["launch_dependencies"] = False
    elif token in {"--no-infra", "--no-infrastructure"}:
        flags["launch_backend"] = False
        flags["launch_frontend"] = False
        flags["launch_dependencies"] = False
    elif token in {"--shared-dep", "--shared-deps", "--shared-dependency", "--shared-dependencies"}:
        set_dependency_scope(flags, "shared")
    elif token in {
        "--managed-dep",
        "--managed-deps",
        "--managed-dependency",
        "--managed-dependencies",
        "--no-external-dep",
        "--no-external-deps",
        "--no-external-dependency",
        "--no-external-dependencies",
    }:
        flags["external_dependencies_mode"] = "managed"
    elif token in {
        "--isolated-dep",
        "--isolated-deps",
        "--isolated-dependency",
        "--isolated-dependencies",
        "--separate-dep",
        "--separate-deps",
        "--separate-dependency",
        "--separate-dependencies",
    }:
        set_dependency_scope(flags, "isolated")
    elif token in {"--no-seed-requirements-from-base", "--no-copy-db-storage"}:
        flags["seed_requirements_from_base"] = False
    elif token in {"fresh=true", "FRESH=true"}:
        flags["fresh"] = True
    elif token in {"resume=true", "RESUME=true"}:
        pass
    elif token in {"docker=true", "DOCKER=true"}:
        flags["docker"] = True
    elif token in {"docker-temp=true", "DOCKER_TEMP=true"}:
        flags["docker_temp"] = True
    elif token in {"force=true", "FORCE=true"}:
        flags["force"] = True
    elif token in {
        "copy-db-storage=true",
        "COPY_DB_STORAGE=true",
        "seed-requirements-from-base=true",
        "SEED_REQUIREMENTS_FROM_BASE=true",
    }:
        flags["seed_requirements_from_base"] = True
    elif token in {
        "copy-db-storage=false",
        "COPY_DB_STORAGE=false",
        "seed-requirements-from-base=false",
        "SEED_REQUIREMENTS_FROM_BASE=false",
    }:
        flags["seed_requirements_from_base"] = False
    elif token in {"parallel-trees=true", "PARALLEL_TREES=true", "RUN_SH_OPT_PARALLEL_TREES=true"}:
        flags["parallel_trees"] = True
    elif token in {"parallel-trees=false", "PARALLEL_TREES=false", "RUN_SH_OPT_PARALLEL_TREES=false"}:
        flags["parallel_trees"] = False
    elif (
        token.startswith("parallel-trees-max=")
        or token.startswith("PARALLEL_TREES_MAX=")
        or token.startswith("RUN_SH_OPT_PARALLEL_TREES_MAX=")
    ):
        flags["parallel_trees_max"] = token.split("=", 1)[1]
    elif token.startswith("frontend-test-runner=") or token.startswith("FRONTEND_TEST_RUNNER="):
        flags["frontend_test_runner"] = token.split("=", 1)[1]


def set_runtime_scope(flags: dict[str, object], scope: str) -> None:
    existing = flags.get("runtime_scope")
    if existing is not None and existing != scope:
        raise RouteError("Use only one runtime scope flag (--backend, --frontend, --fullstack, or --dependencies).")
    flags["runtime_scope"] = scope


def apply_default_runtime_scope_policy(command: str, *, flags: dict[str, object], projects: list[str]) -> None:
    if command not in {"start", "restart"}:
        return
    if flags.get("runtime_scope") is not None:
        return
    if any(key in flags for key in ("launch_backend", "launch_frontend", "launch_dependencies")):
        return
    if command in {"start", "restart"} and flags.get("services"):
        return
    if command == "restart" and projects:
        return
    flags["runtime_scope"] = "entire-system"


def set_dependency_scope(flags: dict[str, object], scope: str) -> None:
    existing = flags.get("dependency_scope")
    if existing is not None and existing != scope:
        raise RouteError("Use only one dependency scope flag (--shared-deps or --isolated-deps).")
    flags["dependency_scope"] = scope


def validate_dependency_scope_flags(mode: str, *, flags: dict[str, object], sets_up_worktrees: bool) -> None:
    scope = flags.get("dependency_scope")
    if scope is None:
        return
    if scope == "isolated" and mode == "main" and not sets_up_worktrees:
        raise RouteError("Main always uses shared dependencies; --isolated-deps only applies to --trees.")
    if scope == "shared" and flags.get("launch_dependencies") is False:
        raise RouteError(
            "--shared-deps requires managed dependencies; remove --no-deps, --only-backend, "
            "--only-frontend, or --no-infra."
        )


def handle_env_assignment(flags: dict[str, object], token: str) -> None:
    key, value = token.split("=", 1)
    lowered = value.lower()
    if key in {"FRONTEND_TEST_RUNNER", "frontend-test-runner"}:
        flags["frontend_test_runner"] = value
        return
    if key in {"test-parallel-max", "TEST_PARALLEL_MAX", "ENVCTL_ACTION_TEST_PARALLEL_MAX"}:
        flags["test_parallel_max"] = value
        return
    if key in {"PARALLEL_TREES_MAX", "parallel-trees-max", "RUN_SH_OPT_PARALLEL_TREES_MAX"}:
        flags["parallel_trees_max"] = value
        return
    if key in {"fresh", "FRESH"} and lowered == "true":
        flags["fresh"] = True
        return
    if key in {"resume", "RESUME"} and lowered == "true":
        flags["resume"] = True
        return
    if key in {"docker", "DOCKER"} and lowered == "true":
        flags["docker"] = True
        return
    if key in {"docker-temp", "DOCKER_TEMP"} and lowered == "true":
        flags["docker_temp"] = True
        return
    if key in {"force", "FORCE"} and lowered == "true":
        flags["force"] = True
        return
    if key in {"backend", "BACKEND"}:
        _store_optional_bool(flags, "backend", lowered)
        return
    if key in {"test-parallel", "TEST_PARALLEL", "ENVCTL_ACTION_TEST_PARALLEL"}:
        _store_optional_bool(flags, "test_parallel", lowered)
        return
    if key in {"service-parallel", "SERVICE_PARALLEL", "ENVCTL_SERVICE_ATTACH_PARALLEL"}:
        _store_optional_bool(flags, "service_parallel", lowered)
        return
    if key in {"service-prep-parallel", "SERVICE_PREP_PARALLEL", "ENVCTL_SERVICE_PREP_PARALLEL"}:
        _store_optional_bool(flags, "service_prep_parallel", lowered)
        return
    if key in {"frontend", "FRONTEND"}:
        _store_optional_bool(flags, "frontend", lowered)
        return
    if key in {"copy-db-storage", "COPY_DB_STORAGE", "seed-requirements-from-base", "SEED_REQUIREMENTS_FROM_BASE"}:
        if lowered == "true":
            flags["seed_requirements_from_base"] = True
        elif lowered == "false":
            flags["seed_requirements_from_base"] = False
        return
    if key in {"parallel-trees", "PARALLEL_TREES", "RUN_SH_OPT_PARALLEL_TREES"}:
        if lowered == "true":
            flags["parallel_trees"] = True
        elif lowered == "false":
            flags["parallel_trees"] = False


def apply_default_headless_policy(command: str, flags: dict[str, object]) -> None:
    if command not in DEFAULT_HEADLESS_COMMANDS:
        return
    if bool(flags.get("interactive")):
        return
    if bool(flags.get("batch")):
        return
    flags["batch"] = True
    flags["default_headless"] = True


def validate_plan_agent_cli_flags(flags: dict[str, object]) -> None:
    if not bool(flags.get("codex")) and not bool(flags.get("opencode")):
        return
    if bool(flags.get("codex")) and bool(flags.get("opencode")):
        raise RouteError("Use only one of --codex or --opencode.")
    if bool(flags.get("omx")) and bool(flags.get("opencode")):
        raise RouteError("--opencode is only supported with cmux or --tmux plan-agent launches; --omx uses Codex.")
    if bool(flags.get("opencode")) and (bool(flags.get("goal")) or bool(flags.get("codex_goal"))):
        raise RouteError(
            "Codex /goal framing is only supported with Codex plan-agent launches; "
            "use --codex or omit --opencode."
        )
    if bool(flags.get("ulw")) and bool(flags.get("no_ulw_loop")):
        raise RouteError("Use only one of --ulw or --no-ulw-loop.")


def validate_plan_agent_workflow_flags(flags: dict[str, object]) -> None:
    enabled_workflows = [
        name
        for name, enabled in (
            ("--ultragoal", bool(flags.get("ultragoal"))),
            ("--ralph", bool(flags.get("ralph"))),
            ("--team", bool(flags.get("team"))),
        )
        if enabled
    ]
    if not enabled_workflows:
        return
    if len(enabled_workflows) > 1:
        raise RouteError("Use only one of --ultragoal, --ralph, or --team.")
    if not bool(flags.get("omx")):
        raise RouteError("--ultragoal, --ralph, and --team are only supported with --omx.")


def _store_optional_bool(flags: dict[str, object], key: str, lowered_value: str) -> None:
    if lowered_value in TRUTHY_TOKENS:
        flags[key] = True
    elif lowered_value in FALSY_TOKENS:
        flags[key] = False
