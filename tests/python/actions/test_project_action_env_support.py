from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from envctl_engine.actions.project_action_support import (
    action_env,
    action_replacements,
    migrate_action_env,
    test_action_extra_env as build_test_action_extra_env,
)
from envctl_engine.runtime.command_router import parse_route
from envctl_engine.state.models import RequirementsResult


@dataclass(frozen=True)
class _EnvContract:
    env: dict[str, str]
    env_file_path: Path | None = None
    env_file_source: str = "default"
    override_requested: bool = False
    override_resolution: str = "not_requested"
    override_authoritative: bool = False
    scrubbed_keys: tuple[str, ...] = ()
    projected_keys: tuple[str, ...] = ()


class ProjectActionEnvSupportTests(unittest.TestCase):
    def test_action_replacements_include_repo_projects_and_selected_target(self) -> None:
        repo = Path("/repo")
        targets = [
            SimpleNamespace(name="feature-a-1", root="/repo/trees/feature-a/1"),
            SimpleNamespace(name="feature-b-1", root="/repo/trees/feature-b/1"),
        ]
        runtime = SimpleNamespace(config=SimpleNamespace(base_dir=repo))

        replacements = action_replacements(runtime=runtime, targets=targets, target=targets[0])

        self.assertEqual(replacements["repo_root"], "/repo")
        self.assertEqual(replacements["projects_csv"], "feature-a-1,feature-b-1")
        self.assertEqual(replacements["project"], "feature-a-1")
        self.assertEqual(replacements["project_root"], "/repo/trees/feature-a/1")

    def test_action_env_uses_runtime_state_paths_and_strips_wrapper_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            target = SimpleNamespace(name="feature-a-1", root=repo / "trees" / "feature-a" / "1")
            route = parse_route(["review", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            runtime = SimpleNamespace(
                env={"ENVCTL_USE_REPO_WRAPPER": "1", "RUNTIME_FLAG": "yes"},
                config=SimpleNamespace(base_dir=repo),
                state_repository=SimpleNamespace(
                    runtime_root=runtime_root,
                    tree_diffs_dir_path=lambda run_id: runtime_root / "runs" / str(run_id) / "tree-diffs",
                ),
                load_existing_state=lambda mode: SimpleNamespace(run_id="run-1") if mode == "trees" else None,
            )

            env = action_env(
                runtime=runtime,
                command_name="review",
                targets=[target],
                route=route,
                target=target,
                process_env={"ENVCTL_WRAPPER_PYTHON_REEXEC": "1", "PROCESS_FLAG": "yes"},
            )

        self.assertEqual(env["ENVCTL_ACTION_RUN_ID"], "run-1")
        self.assertEqual(env["ENVCTL_ACTION_RUNTIME_ROOT"], str(runtime_root))
        self.assertEqual(env["ENVCTL_ACTION_TREE_DIFFS_ROOT"], str(runtime_root / "runs" / "run-1" / "tree-diffs"))
        self.assertEqual(env["ENVCTL_ACTION_PROJECT"], "feature-a-1")
        self.assertEqual(env["ENVCTL_ACTION_INTERACTIVE"], "0")
        self.assertEqual(env["RUNTIME_FLAG"], "yes")
        self.assertEqual(env["PROCESS_FLAG"], "yes")
        self.assertNotIn("ENVCTL_USE_REPO_WRAPPER", env)
        self.assertNotIn("ENVCTL_WRAPPER_PYTHON_REEXEC", env)

    def test_test_action_extra_env_projects_backend_env_for_backend_suites(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            target_root = repo / "trees" / "feature-a" / "1"
            requirements = RequirementsResult(project="feature-a-1")
            route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            target = SimpleNamespace(name="feature-a-1", root=target_root)
            projected_calls: list[dict[str, object]] = []

            def project_service_env(context: object, **kwargs: object) -> dict[str, object]:
                projected_calls.append({"context": context, **kwargs})
                return {"DATABASE_URL": "postgres://db", "IGNORED_NONE": None, 123: "not-a-string-key"}

            runtime = SimpleNamespace(
                raw_runtime=SimpleNamespace(_project_service_env=project_service_env),
                load_existing_state=lambda mode: (
                    SimpleNamespace(requirements={"feature-a-1": requirements}) if mode == "trees" else None
                ),
            )

            env = build_test_action_extra_env(
                runtime=runtime,
                route=route,
                target=target,
                suite_source="backend_pytest",
                project_context_builder=lambda **kwargs: SimpleNamespace(**kwargs),
            )

        self.assertEqual(env, {"DATABASE_URL": "postgres://db"})
        self.assertEqual(projected_calls[0]["requirements"], requirements)
        self.assertEqual(projected_calls[0]["route"], route)
        self.assertEqual(projected_calls[0]["service_name"], "backend")

    def test_migrate_action_env_stores_backend_contract_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            target_root = repo / "trees" / "feature-a" / "1"
            route = parse_route(["migrate", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            target = SimpleNamespace(name="feature-a-1", root=target_root)
            requirements = RequirementsResult(project="feature-a-1")
            contracts: dict[str, dict[str, object]] = {}
            projected_calls: list[dict[str, object]] = []
            resolved_calls: list[dict[str, object]] = []

            def project_service_env_internal(context: object, **kwargs: object) -> dict[str, object]:
                projected_calls.append({"context": context, **kwargs})
                return {"DATABASE_URL": "postgres://projected", "NON_STRING": 123}

            raw_runtime = SimpleNamespace(_project_service_env_internal=project_service_env_internal)
            runtime = SimpleNamespace(raw_runtime=raw_runtime)

            def resolve_backend_env_contract(_runtime: object, **kwargs: object) -> _EnvContract:
                resolved_calls.append(kwargs)
                return _EnvContract(
                    env={**dict(kwargs["base_env"]), "DATABASE_URL": "postgres://contract"},
                    env_file_path=repo / "backend" / ".env",
                    env_file_source="override",
                    override_requested=True,
                    override_resolution="found",
                    override_authoritative=True,
                    scrubbed_keys=("SECRET",),
                    projected_keys=("DATABASE_URL",),
                )

            env = migrate_action_env(
                runtime=runtime,
                targets=[target],
                route=route,
                target=target,
                migrate_env_contracts=contracts,
                base_env_builder=lambda command_name, targets, route, target, extra=None: {
                    "ENVCTL_ACTION_COMMAND": command_name,
                    "BASE": "1",
                },
                backend_cwd=lambda root: root / "backend",
                requirements_for_target=lambda **_kwargs: requirements,
                project_context_builder=lambda **kwargs: SimpleNamespace(**kwargs),
                contract_context_builder=lambda **kwargs: SimpleNamespace(**kwargs),
                resolve_backend_env_contract=resolve_backend_env_contract,
            )

        self.assertEqual(env["DATABASE_URL"], "postgres://contract")
        self.assertEqual(projected_calls[0]["requirements"], requirements)
        self.assertEqual(resolved_calls[0]["backend_cwd"], target_root / "backend")
        self.assertEqual(resolved_calls[0]["projected_env"], {"DATABASE_URL": "postgres://projected"})
        self.assertEqual(
            contracts["feature-a-1"],
            {
                "env_file_path": str(repo / "backend" / ".env"),
                "env_file_source": "override",
                "override_requested": True,
                "override_resolution": "found",
                "override_authoritative": True,
                "scrubbed_keys": ["SECRET"],
                "projected_keys": ["DATABASE_URL"],
            },
        )


if __name__ == "__main__":
    unittest.main()
