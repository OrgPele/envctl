from __future__ import annotations

# ruff: noqa: F403,F405
from tests.python.runtime.engine_runtime_env_test_support import *


class EngineRuntimeEnvModeTests(EngineRuntimeEnvTestCase):
    def test_runtime_env_overrides_forward_expected_flags(self) -> None:
        route = parse_route(
            [
                "--plan",
                "feature-a",
                "--docker",
                "--setup-worktree-existing",
                "--recreate-existing-worktree",
                "--setup-include-worktrees",
                "feature-a-1,feature-a-2",
                "--seed-requirements-from-base",
                "--stop-all-remove-volumes",
                "--managed-deps",
            ],
            env={},
        )

        env = runtime_env_overrides(route)

        self.assertEqual(env.get("DOCKER_MODE"), "true")
        self.assertEqual(env.get("SETUP_WORKTREE_EXISTING"), "true")
        self.assertEqual(env.get("SETUP_WORKTREE_RECREATE"), "true")
        self.assertEqual(env.get("SETUP_INCLUDE_WORKTREES_RAW"), "feature-a-1,feature-a-2")
        self.assertEqual(env.get("SEED_REQUIREMENTS_FROM_BASE"), "true")
        self.assertEqual(env.get("RUN_SH_COMMAND_STOP_ALL_REMOVE_VOLUMES"), "true")
        self.assertEqual(env.get("ENVCTL_EXTERNAL_DEPENDENCIES_MODE"), "managed")

    def test_main_requirements_mode_rejects_conflicting_flags(self) -> None:
        route = parse_route(
            ["start", "--main-services-local", "--main-services-remote"],
            env={},
        )
        with self.assertRaises(RuntimeError):
            main_requirements_mode(route)

    def test_effective_main_requirement_flags_switch_with_local_mode(self) -> None:
        runtime = SimpleNamespace(
            config=SimpleNamespace(
                postgres_main_enable=True,
                redis_main_enable=True,
                supabase_main_enable=False,
                n8n_main_enable=False,
            )
        )
        route = parse_route(["start", "--main-services-local"], env={})

        flags = effective_main_requirement_flags(runtime, route)

        self.assertFalse(flags["postgres_main_enable"])
        self.assertTrue(flags["supabase_main_enable"])
        self.assertTrue(flags["n8n_main_enable"])
        self.assertTrue(flags["redis_main_enable"])

    def test_validate_mode_toggles_rejects_invalid_main_combo(self) -> None:
        runtime = SimpleNamespace(
            config=SimpleNamespace(
                startup_enabled_for_mode=lambda mode: True,
                postgres_main_enable=True,
                redis_main_enable=True,
                supabase_main_enable=True,
                n8n_main_enable=False,
            )
        )
        with self.assertRaises(RuntimeError):
            validate_mode_toggles(runtime, "main")

    def test_validate_mode_toggles_rejects_disabled_startup(self) -> None:
        runtime = SimpleNamespace(
            config=SimpleNamespace(
                startup_enabled_for_mode=lambda mode: mode != "main",
                profile_for_mode=lambda mode: SimpleNamespace(
                    startup_enable=mode != "main",
                    backend_enable=True,
                    frontend_enable=True,
                    postgres_enable=True,
                    redis_enable=True,
                    supabase_enable=False,
                    n8n_enable=False,
                ),
            )
        )

        with self.assertRaisesRegex(RuntimeError, "envctl runs are disabled for main"):
            validate_mode_toggles(runtime, "main")

    def test_validate_mode_toggles_allows_plan_when_runs_disabled(self) -> None:
        runtime = SimpleNamespace(
            config=SimpleNamespace(
                startup_enabled_for_mode=lambda mode: mode != "main",
                profile_for_mode=lambda mode: SimpleNamespace(
                    startup_enable=mode != "main",
                    backend_enable=True,
                    frontend_enable=True,
                    postgres_enable=True,
                    redis_enable=True,
                    supabase_enable=False,
                    n8n_enable=False,
                ),
            )
        )

        validate_mode_toggles(runtime, "main", route=parse_route(["--plan"], env={}))

    def test_validate_mode_toggles_allows_implicit_start_when_runs_disabled(self) -> None:
        runtime = SimpleNamespace(
            config=SimpleNamespace(
                startup_enabled_for_mode=lambda mode: mode != "main",
                profile_for_mode=lambda mode: SimpleNamespace(
                    startup_enable=mode != "main",
                    backend_enable=True,
                    frontend_enable=True,
                    postgres_enable=True,
                    redis_enable=True,
                    supabase_enable=False,
                    n8n_enable=False,
                ),
            )
        )

        validate_mode_toggles(runtime, "main", route=parse_route(["--main"], env={}))

    def test_route_is_implicit_start_distinguishes_bare_mode_from_explicit_start(self) -> None:
        self.assertTrue(_route_is_implicit_start(parse_route(["--main"], env={})))
        self.assertTrue(_route_is_implicit_start(parse_route([], env={})))
        self.assertFalse(_route_is_implicit_start(parse_route(["start", "--main"], env={})))
        self.assertFalse(_route_is_implicit_start(parse_route(["--command=start", "--main"], env={})))

    def test_external_dependency_mode_implies_requirement_enabled(self) -> None:
        runtime = SimpleNamespace(
            env={"ENVCTL_EXTERNAL_DEPENDENCIES": "supabase"},
            config=SimpleNamespace(
                startup_enabled_for_mode=lambda _mode: True,
                requirement_enabled_for_mode=lambda _mode, _name: False,
            ),
        )

        self.assertTrue(requirement_enabled_for_mode(runtime, "main", "supabase"))
