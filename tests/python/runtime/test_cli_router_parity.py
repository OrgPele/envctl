from __future__ import annotations

import unittest
from pathlib import Path
import re

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime import command_router
from envctl_engine.runtime.command_router import RouteError, list_supported_flag_tokens, parse_route


class CliRouterParityTests(unittest.TestCase):
    def test_dashed_aliases_map_to_expected_commands(self) -> None:
        expected = {
            "--doctor": "doctor",
            "--dashboard": "dashboard",
            "--config": "config",
            "--init": "config",
            "--logs": "logs",
            "--clear-logs": "clear-logs",
            "--health": "health",
            "--errors": "errors",
            "--test": "test",
            "--test-focused": "test-focused",
            "--pr": "pr",
            "--commit": "commit",
            "--ship": "ship",
            "--review": "review",
            "--analyze": "review",
            "--migrate": "migrate",
            "--restart": "restart",
            "--stop-all": "stop-all",
            "--blast-all": "blast-all",
            "--delete-worktree": "delete-worktree",
            "--blast-worktree": "blast-worktree",
            "--install-prompts": "install-prompts",
            "--codex-tmux": "codex-tmux",
            "--debug-ui-pack": "debug-pack",
            "--endpoints": "endpoints",
            "--qa-user": "qa-user",
        }
        for token, command in expected.items():
            route = parse_route([token], env={})
            self.assertEqual(route.command, command, msg=token)

    def test_bare_direct_inspection_commands_map_to_expected_commands(self) -> None:
        expected = {
            "list-commands": "list-commands",
            "list-targets": "list-targets",
            "list-trees": "list-trees",
            "show-config": "show-config",
            "show-state": "show-state",
            "explain-startup": "explain-startup",
            "preflight": "preflight",
            "endpoints": "endpoints",
            "qa-user": "qa-user",
            "qa-users": "qa-user",
            "playwright": "playwright",
        }
        for token, command in expected.items():
            route = parse_route([token], env={})
            self.assertEqual(route.command, command, msg=token)

    def test_unknown_option_is_rejected(self) -> None:
        with self.assertRaises(RouteError):
            parse_route(["--definitely-unknown"], env={})

    def test_unknown_positional_command_is_rejected(self) -> None:
        with self.assertRaises(RouteError):
            parse_route(["definitely-unknown-command"], env={})

    def test_shared_dependency_scope_flags_are_parsed(self) -> None:
        route = parse_route(["--trees"], env={})

        self.assertEqual(route.mode, "trees")
        self.assertEqual(route.flags.get("runtime_scope"), "entire-system")
        self.assertNotEqual(route.flags.get("dependency_scope"), "isolated")

        route = parse_route(["--trees", "--shared-deps"], env={})

        self.assertEqual(route.mode, "trees")
        self.assertEqual(route.flags.get("dependency_scope"), "shared")

        route = parse_route(["--trees", "--isolated-deps"], env={})

        self.assertEqual(route.flags.get("dependency_scope"), "isolated")

        for token in ("--separate-deps", "--separate-dep", "--separate-dependency", "--separate-dependencies"):
            with self.subTest(token=token):
                route = parse_route(["--trees", token], env={})
                self.assertEqual(route.flags.get("dependency_scope"), "isolated")

    def test_managed_dependency_flags_disable_external_dependencies_for_route(self) -> None:
        for token in (
            "--managed-deps",
            "--managed-dependencies",
            "--no-external-deps",
            "--no-external-dependencies",
        ):
            with self.subTest(token=token):
                route = parse_route(["--main", token], env={})
                self.assertEqual(route.mode, "main")
                self.assertEqual(route.flags.get("external_dependencies_mode"), "managed")

    def test_playwright_preserves_passthrough_after_separator(self) -> None:
        route = parse_route(
            [
                "playwright",
                "--project",
                "feature-a-1",
                "--json",
                "--",
                "npx",
                "playwright",
                "test",
                "--grep",
                "smoke",
            ],
            env={},
        )

        self.assertEqual(route.command, "playwright")
        self.assertEqual(route.projects, ["feature-a-1"])
        self.assertTrue(route.flags.get("json"))
        self.assertEqual(route.passthrough_args, ["npx", "playwright", "test", "--grep", "smoke"])

    def test_qa_user_flags_are_parsed(self) -> None:
        route = parse_route(
            [
                "qa-user",
                "ensure",
                "--project",
                "feature-a-1",
                "--email",
                "qa@example.test",
                "--password",
                "secret",
                "--locale",
                "he-IL",
                "--seed",
                "crm,calendar",
                "--seed=support",
                "--update-password",
                "--update-metadata",
                "--json",
            ],
            env={},
        )

        self.assertEqual(route.command, "qa-user")
        self.assertEqual(route.passthrough_args, ["ensure"])
        self.assertEqual(route.projects, ["feature-a-1"])
        self.assertEqual(route.flags.get("email"), "qa@example.test")
        self.assertEqual(route.flags.get("password"), "secret")
        self.assertEqual(route.flags.get("locale"), "he-IL")
        self.assertEqual(route.flags.get("seed"), ["crm", "calendar", "support"])
        self.assertTrue(route.flags.get("json"))
        self.assertTrue(route.flags.get("update_password"))
        self.assertTrue(route.flags.get("update_metadata"))

    def test_setup_worktrees_allows_isolated_dependency_scope(self) -> None:
        route = parse_route(["--setup-worktrees", "feature-a", "1", "--isolated-deps"], env={})

        self.assertEqual(route.mode, "main")
        self.assertEqual(route.flags.get("dependency_scope"), "isolated")
        self.assertEqual(route.flags.get("setup_worktrees"), [{"feature": "feature-a", "count": "1"}])

    def test_start_and_restart_default_to_entire_system_scope(self) -> None:
        self.assertEqual(parse_route([], env={}).flags.get("runtime_scope"), "entire-system")
        self.assertEqual(parse_route(["--project", "feature-a-1"], env={}).flags.get("runtime_scope"), "entire-system")
        self.assertEqual(parse_route(["restart"], env={}).flags.get("runtime_scope"), "entire-system")

        self.assertIsNone(parse_route(["--only-backend"], env={}).flags.get("runtime_scope"))
        self.assertIsNone(parse_route(["restart", "--project", "feature-a-1"], env={}).flags.get("runtime_scope"))

    def test_shared_dependency_default_does_not_conflict_with_app_only_overrides(self) -> None:
        for args in (
            ["--trees", "--no-deps"],
            ["--trees", "--only-backend"],
            ["--trees", "--only-frontend"],
            ["--trees", "--no-infra"],
        ):
            with self.subTest(args=args):
                route = parse_route(list(args), env={})
                self.assertFalse(route.flags.get("launch_dependencies"))
                self.assertNotEqual(route.flags.get("dependency_scope"), "shared")

    def test_shared_dependency_scope_flags_reject_conflicts(self) -> None:
        for args in (
            ["--trees", "--shared-deps", "--isolated-deps"],
            ["--trees", "--shared-deps", "--no-deps"],
            ["--trees", "--shared-deps", "--only-backend"],
            ["--trees", "--shared-deps", "--only-frontend"],
            ["--trees", "--shared-deps", "--no-infra"],
            ["--main", "--isolated-deps"],
        ):
            with self.subTest(args=args), self.assertRaises(RouteError):
                parse_route(list(args), env={})

        route = parse_route(["--main", "--shared-deps"], env={})
        self.assertEqual(route.mode, "main")
        self.assertEqual(route.flags.get("dependency_scope"), "shared")

    def test_action_flags_are_parsed_for_command_routes(self) -> None:
        route = parse_route(["test", "--all", "--dry-run"], env={})
        self.assertEqual(route.command, "test")
        self.assertTrue(route.flags.get("all"))
        self.assertFalse(route.flags.get("failed"))
        self.assertTrue(route.flags.get("dry_run"))
        self.assertTrue(route.flags.get("skip_startup"))
        self.assertTrue(route.flags.get("load_state"))

        route = parse_route(["test", "--failed"], env={})
        self.assertEqual(route.command, "test")
        self.assertTrue(route.flags.get("failed"))
        self.assertTrue(route.flags.get("skip_startup"))
        self.assertTrue(route.flags.get("load_state"))

        route = parse_route(["commit", "--commit-message", "ship it"], env={})
        self.assertEqual(route.command, "commit")
        self.assertEqual(route.flags.get("commit_message"), "ship it")

        route = parse_route(["commit", "-m", "ship it"], env={})
        self.assertEqual(route.command, "commit")
        self.assertEqual(route.flags.get("commit_message"), "ship it")

        route = parse_route(["ship", "--project", "feature-a-1", "-m", "ship it", "--json"], env={})
        self.assertEqual(route.command, "ship")
        self.assertEqual(route.projects, ["feature-a-1"])
        self.assertEqual(route.flags.get("commit_message"), "ship it")
        self.assertTrue(route.flags.get("json"))

        route = parse_route(["ship", "--project", "feature-a-1", "-m", "ship it", "--human"], env={})
        self.assertEqual(route.command, "ship")
        self.assertEqual(route.projects, ["feature-a-1"])
        self.assertEqual(route.flags.get("commit_message"), "ship it")
        self.assertTrue(route.flags.get("human"))

        route = parse_route(["ship", "--project", "feature-a-1", "--json"], env={})
        self.assertEqual(route.command, "ship")
        self.assertEqual(route.projects, ["feature-a-1"])
        self.assertTrue(route.flags.get("json"))
        self.assertTrue(route.flags.get("skip_startup"))
        self.assertTrue(route.flags.get("load_state"))

        route = parse_route(["test-focused", "--project=feature-a-1", "--json"], env={})
        self.assertEqual(route.command, "test-focused")
        self.assertEqual(route.projects, ["feature-a-1"])
        self.assertTrue(route.flags.get("json"))
        self.assertTrue(route.flags.get("skip_startup"))
        self.assertTrue(route.flags.get("load_state"))

        route = parse_route(["test-focused", "--project=feature-a-1", "--dry-run"], env={})
        self.assertEqual(route.command, "test-focused")
        self.assertEqual(route.projects, ["feature-a-1"])
        self.assertTrue(route.flags.get("dry_run"))
        self.assertTrue(route.flags.get("skip_startup"))
        self.assertTrue(route.flags.get("load_state"))

        route = parse_route(["test-focused", "--project=feature-a-1"], env={})
        self.assertEqual(route.command, "test-focused")
        self.assertEqual(route.projects, ["feature-a-1"])
        self.assertTrue(route.flags.get("skip_startup"))
        self.assertTrue(route.flags.get("load_state"))

        with self.assertRaisesRegex(RouteError, "Unsupported command"):
            parse_route(["test-plan", "--project=feature-a-1"], env={})
        with self.assertRaisesRegex(RouteError, "Unknown option"):
            parse_route(["--test-plan", "--project=feature-a-1"], env={})

        route = parse_route(["review", "--review-mode=grouped"], env={})
        self.assertEqual(route.command, "review")
        self.assertEqual(route.flags.get("analyze_mode"), "grouped")
        self.assertTrue(route.flags.get("skip_startup"))
        self.assertTrue(route.flags.get("load_state"))

        route = parse_route(["review", "--review-base", "release/2026.03"], env={})
        self.assertEqual(route.command, "review")
        self.assertEqual(route.flags.get("review_base"), "release/2026.03")
        self.assertTrue(route.flags.get("skip_startup"))
        self.assertTrue(route.flags.get("load_state"))

        route = parse_route(["migrate"], env={})
        self.assertEqual(route.command, "migrate")
        self.assertTrue(route.flags.get("skip_startup"))
        self.assertTrue(route.flags.get("load_state"))

        route = parse_route(["config"], env={})
        self.assertEqual(route.command, "config")

        route = parse_route(
            [
                "install-prompts",
                "--cli",
                "codex,claude",
                "--preset",
                "implement_task",
                "--dry-run",
                "--with-codex-skills",
            ],
            env={},
        )
        self.assertEqual(route.command, "install-prompts")
        self.assertEqual(route.flags.get("cli"), "codex,claude")
        self.assertEqual(route.flags.get("preset"), "implement_task")
        self.assertTrue(route.flags.get("dry_run"))
        self.assertTrue(route.flags.get("with_codex_skills"))

        route = parse_route(["codex-tmux", "workspace"], env={})
        self.assertEqual(route.command, "codex-tmux")
        self.assertEqual(route.passthrough_args, ["workspace"])

        route = parse_route(["health"], env={})
        self.assertEqual(route.command, "health")
        self.assertTrue(route.flags.get("skip_startup"))
        self.assertTrue(route.flags.get("load_state"))

        route = parse_route(["delete-worktree", "--all", "--yes"], env={})
        self.assertEqual(route.command, "delete-worktree")
        self.assertTrue(route.flags.get("all"))
        self.assertTrue(route.flags.get("yes"))

        route = parse_route(["blast-worktree", "--all", "--yes"], env={})
        self.assertEqual(route.command, "blast-worktree")
        self.assertTrue(route.flags.get("all"))
        self.assertTrue(route.flags.get("yes"))

        route = parse_route(["restart"], env={})
        self.assertEqual(route.command, "restart")
        self.assertTrue(route.flags.get("skip_startup"))
        self.assertTrue(route.flags.get("load_state"))

    def test_mode_force_tokens_apply_shell_compatible_semantics(self) -> None:
        route = parse_route(["--main"], env={})
        self.assertEqual(route.mode, "main")
        self.assertNotIn("no_resume", route.flags)

        route = parse_route(["--trees=false"], env={})
        self.assertEqual(route.mode, "main")
        self.assertNotIn("no_resume", route.flags)

        route = parse_route(["--main", "--no-resume"], env={})
        self.assertEqual(route.mode, "main")
        self.assertTrue(route.flags.get("no_resume"))

        route = parse_route(["main=false"], env={})
        self.assertEqual(route.mode, "trees")

    def test_blast_all_volume_flags_are_parsed(self) -> None:
        route = parse_route(
            ["blast-all", "--blast-keep-worktree-volumes", "--blast-remove-main-volumes"],
            env={},
        )
        self.assertEqual(route.command, "blast-all")
        self.assertIs(route.flags.get("blast_keep_worktree_volumes"), True)
        self.assertIs(route.flags.get("blast_remove_main_volumes"), True)

        route = parse_route(
            ["blast-all", "--blast-remove-worktree-volumes", "--blast-keep-main-volumes"],
            env={},
        )
        self.assertEqual(route.command, "blast-all")
        self.assertIs(route.flags.get("blast_keep_worktree_volumes"), False)
        self.assertIs(route.flags.get("blast_remove_main_volumes"), False)

    def test_high_value_documented_flags_are_parsed(self) -> None:
        route = parse_route(
            [
                "--plan",
                "feature-a",
                "--parallel-trees",
                "--parallel-trees-max",
                "4",
                "--refresh-cache",
                "--fast",
                "--docker",
                "--setup-worktrees",
                "feature-b",
                "3",
                "--setup-worktree",
                "feature-c",
                "2",
                "--include-existing-worktrees",
                "feature-a-1,feature-a-2",
                "--keep-plan",
                "--clear-port-state",
                "--debug-trace",
                "--debug-trace-log",
                "/tmp/trace.log",
                "--main-services-local",
                "--main-services-remote",
                "--seed-requirements-from-base",
            ],
            env={},
        )
        self.assertEqual(route.command, "plan")
        self.assertTrue(route.flags.get("parallel_trees"))
        self.assertEqual(route.flags.get("parallel_trees_max"), "4")
        self.assertTrue(route.flags.get("refresh_cache"))
        self.assertTrue(route.flags.get("fast"))
        self.assertTrue(route.flags.get("docker"))
        self.assertEqual(route.flags.get("include_existing_worktrees"), ["feature-a-1", "feature-a-2"])
        self.assertTrue(route.flags.get("keep_plan"))
        self.assertTrue(route.flags.get("clear_port_state"))
        self.assertTrue(route.flags.get("debug_trace"))
        self.assertEqual(route.flags.get("debug_trace_log"), "/tmp/trace.log")
        self.assertTrue(route.flags.get("main_services_local"))
        self.assertTrue(route.flags.get("main_services_remote"))
        self.assertTrue(route.flags.get("seed_requirements_from_base"))
        self.assertEqual(
            route.flags.get("setup_worktrees"),
            [{"feature": "feature-b", "count": "3"}],
        )
        self.assertEqual(
            route.flags.get("setup_worktree"),
            [{"feature": "feature-c", "iteration": "2"}],
        )

    def test_shell_compatibility_alias_flags_are_parsed(self) -> None:
        route = parse_route(
            [
                "--plan=feature-a,feature-b",
                "--planning-prs",
                "--parallel-plan=feature-c",
                "--sequential-plan=feature-d",
                "--command-only",
                "--command-resume",
                "--no-resume",
                "--no-auto-resume",
                "--stop-docker-on-exit",
                "--docker-temp",
                "--temp-docker",
                "--clear-ports",
                "--clear-port-cache",
                "--fast-startup",
                "--main-local",
                "--main-remote",
                "--reuse-existing-worktree",
                "--setup-worktree-existing",
                "--recreate-existing-worktree",
                "--setup-worktree-recreate",
                "--setup-include-worktrees",
                "feature-a-1,feature-a-2",
                "--log-profile",
                "debug",
                "--log-level=info",
                "--backend-log-profile=quiet",
                "--backend-log-level",
                "warn",
                "--frontend-log-profile=verbose",
                "--frontend-log-level",
                "error",
                "--frontend-test-runner=bun",
                "--test-parallel-max",
                "5",
                "--copy-db-storage",
                "--no-copy-db-storage",
                "--no-seed-requirements-from-base",
                "--no-parallel-trees",
                "--debug-trace-no-xtrace",
                "--debug-trace-no-stdio",
                "--debug-trace-no-interactive",
                "--key-debug",
            ],
            env={},
        )
        self.assertEqual(route.command, "plan")
        self.assertEqual(route.mode, "trees")
        self.assertTrue(route.flags.get("planning_prs"))
        self.assertTrue(route.flags.get("skip_startup"))
        self.assertTrue(route.flags.get("load_state"))
        self.assertTrue(route.flags.get("no_resume"))
        self.assertTrue(route.flags.get("docker_temp"))
        self.assertTrue(route.flags.get("clear_port_state"))
        self.assertTrue(route.flags.get("fast"))
        self.assertTrue(route.flags.get("main_services_local"))
        self.assertTrue(route.flags.get("main_services_remote"))
        self.assertTrue(route.flags.get("setup_worktree_existing"))
        self.assertTrue(route.flags.get("setup_worktree_recreate"))
        self.assertEqual(route.flags.get("include_existing_worktrees"), ["feature-a-1", "feature-a-2"])
        self.assertEqual(route.flags.get("log_profile"), "debug")
        self.assertEqual(route.flags.get("log_level"), "info")
        self.assertEqual(route.flags.get("backend_log_profile"), "quiet")
        self.assertEqual(route.flags.get("backend_log_level"), "warn")
        self.assertEqual(route.flags.get("frontend_log_profile"), "verbose")
        self.assertEqual(route.flags.get("frontend_log_level"), "error")
        self.assertEqual(route.flags.get("frontend_test_runner"), "bun")
        self.assertEqual(route.flags.get("test_parallel_max"), "5")
        self.assertFalse(route.flags.get("seed_requirements_from_base"))
        self.assertFalse(route.flags.get("parallel_trees"))
        self.assertTrue(route.flags.get("debug_trace_no_xtrace"))
        self.assertTrue(route.flags.get("debug_trace_no_stdio"))
        self.assertTrue(route.flags.get("debug_trace_no_interactive"))
        self.assertTrue(route.flags.get("key_debug"))
        self.assertEqual(route.passthrough_args[:4], ["feature-a", "feature-b", "feature-c", "feature-d"])

    def test_runtime_scope_flags_are_parsed_for_start_and_kill_commands(self) -> None:
        route = parse_route(["--backend", "--headless"], env={})
        self.assertEqual(route.command, "start")
        self.assertEqual(route.flags.get("runtime_scope"), "backend")
        self.assertTrue(route.flags.get("batch"))

        route = parse_route(["--frontend"], env={})
        self.assertEqual(route.command, "start")
        self.assertEqual(route.flags.get("runtime_scope"), "frontend")

        route = parse_route(["--both"], env={})
        self.assertEqual(route.command, "start")
        self.assertEqual(route.flags.get("runtime_scope"), "fullstack")

        route = parse_route(["--fullstack"], env={})
        self.assertEqual(route.flags.get("runtime_scope"), "fullstack")

        route = parse_route(["--dependencies"], env={})
        self.assertEqual(route.flags.get("runtime_scope"), "dependencies")

        route = parse_route(["--deps"], env={})
        self.assertEqual(route.flags.get("runtime_scope"), "dependencies")

        route = parse_route(["--entire-system"], env={})
        self.assertEqual(route.flags.get("runtime_scope"), "entire-system")

        route = parse_route(["--tree", "--only-backend"], env={})
        self.assertEqual(route.mode, "trees")
        self.assertTrue(route.flags.get("launch_backend"))
        self.assertFalse(route.flags.get("launch_frontend"))
        self.assertFalse(route.flags.get("launch_dependencies"))

        route = parse_route(["--tree", "--only-frontend"], env={})
        self.assertEqual(route.mode, "trees")
        self.assertFalse(route.flags.get("launch_backend"))
        self.assertTrue(route.flags.get("launch_frontend"))
        self.assertFalse(route.flags.get("launch_dependencies"))

        route = parse_route(["--tree", "--no-infra"], env={})
        self.assertFalse(route.flags.get("launch_backend"))
        self.assertFalse(route.flags.get("launch_frontend"))
        self.assertFalse(route.flags.get("launch_dependencies"))

        route = parse_route(["kill", "--frontend", "--headless"], env={})
        self.assertEqual(route.command, "stop")
        self.assertEqual(route.flags.get("runtime_scope"), "frontend")
        self.assertTrue(route.flags.get("batch"))

        route = parse_route(["kill-all", "--headless"], env={})
        self.assertEqual(route.command, "stop-all")
        self.assertTrue(route.flags.get("batch"))

        with self.assertRaises(RouteError):
            parse_route(["--backend", "--frontend"], env={})

    def test_specific_action_commands_default_to_headless(self) -> None:
        examples = {
            "kill-all": "stop-all",
            "stop-all": "stop-all",
            "blast-all": "blast-all",
            "stop": "stop",
            "logs": "logs",
            "errors": "errors",
            "health": "health",
            "clear-logs": "clear-logs",
            "test": "test",
            "pr": "pr",
            "commit": "commit",
            "review": "review",
            "migrate": "migrate",
            "delete-worktree": "delete-worktree",
            "blast-worktree": "blast-worktree",
            "self-destruct-worktree": "self-destruct-worktree",
        }
        for token, command in examples.items():
            with self.subTest(token=token):
                route = parse_route([token], env={})
                self.assertEqual(route.command, command)
                self.assertTrue(route.flags.get("batch"))
                self.assertTrue(route.flags.get("default_headless"))

    def test_specific_action_interactive_flag_opts_back_into_prompts(self) -> None:
        route = parse_route(["pr", "--interactive"], env={})

        self.assertEqual(route.command, "pr")
        self.assertTrue(route.flags.get("interactive"))
        self.assertFalse(bool(route.flags.get("batch")))
        self.assertFalse(bool(route.flags.get("default_headless")))

    def test_workflow_commands_do_not_default_to_headless(self) -> None:
        for token in ("start", "restart", "resume", "dashboard", "config"):
            with self.subTest(token=token):
                route = parse_route([token], env={})
                self.assertEqual(route.command, token)
                self.assertFalse(bool(route.flags.get("batch")))
                self.assertFalse(bool(route.flags.get("default_headless")))

    def test_python_parser_covers_documented_long_flag_surface(self) -> None:
        docs = (REPO_ROOT / "docs" / "reference" / "important-flags.md").read_text(encoding="utf-8")
        documented_flags = {token for token in re.findall(r"--[a-z0-9][a-z0-9-]*", docs) if token.startswith("--")}
        parser_flags = set(list_supported_flag_tokens())
        ignored = {"--help", "--repo", "--version"}
        missing = sorted(documented_flags.difference(parser_flags).difference(ignored))
        self.assertEqual(missing, [], msg=f"missing documented flags: {missing}")

    def test_frontend_test_runner_env_assignment_is_parsed(self) -> None:
        route = parse_route(["FRONTEND_TEST_RUNNER=vitest"], env={})
        self.assertEqual(route.flags.get("frontend_test_runner"), "vitest")

    def test_shell_style_env_assignment_flags_are_parsed(self) -> None:
        route = parse_route(
            [
                "fresh=true",
                "docker=true",
                "docker-temp=true",
                "force=true",
                "copy-db-storage=true",
                "parallel-trees=true",
                "parallel-trees-max=7",
                "test-parallel-max=3",
            ],
            env={},
        )
        self.assertTrue(route.flags.get("fresh"))
        self.assertTrue(route.flags.get("docker"))
        self.assertTrue(route.flags.get("docker_temp"))
        self.assertTrue(route.flags.get("force"))
        self.assertTrue(route.flags.get("seed_requirements_from_base"))
        self.assertTrue(route.flags.get("parallel_trees"))
        self.assertEqual(route.flags.get("parallel_trees_max"), "7")
        self.assertEqual(route.flags.get("test_parallel_max"), "3")

    def test_shell_style_env_assignment_false_variants_are_parsed(self) -> None:
        route = parse_route(
            [
                "copy-db-storage=false",
                "parallel-trees=false",
            ],
            env={},
        )
        self.assertFalse(route.flags.get("seed_requirements_from_base"))
        self.assertFalse(route.flags.get("parallel_trees"))

    def test_test_backend_frontend_env_assignment_flags_are_parsed(self) -> None:
        route = parse_route(
            [
                "test",
                "backend=false",
                "frontend=true",
            ],
            env={"ENVCTL_DEFAULT_MODE": "trees"},
        )
        self.assertEqual(route.command, "test")
        self.assertEqual(route.flags.get("backend"), False)
        self.assertEqual(route.flags.get("frontend"), True)

    def test_parallel_mode_flags_for_tests_and_service_attach_are_parsed(self) -> None:
        route = parse_route(
            [
                "test",
                "--test-parallel",
                "--service-parallel",
                "--service-prep-parallel",
            ],
            env={"ENVCTL_DEFAULT_MODE": "trees"},
        )
        self.assertEqual(route.flags.get("test_parallel"), True)
        self.assertEqual(route.flags.get("service_parallel"), True)
        self.assertEqual(route.flags.get("service_prep_parallel"), True)

        route = parse_route(
            [
                "test",
                "--test-sequential",
                "--service-sequential",
                "--service-prep-sequential",
            ],
            env={"ENVCTL_DEFAULT_MODE": "trees"},
        )
        self.assertEqual(route.flags.get("test_parallel"), False)
        self.assertEqual(route.flags.get("service_parallel"), False)
        self.assertEqual(route.flags.get("service_prep_parallel"), False)

    def test_requirements_parallel_flags_are_parsed(self) -> None:
        route = parse_route(["--deps-parallel"], env={"ENVCTL_DEFAULT_MODE": "trees"})
        self.assertEqual(route.command, "start")
        self.assertEqual(route.flags.get("requirements_parallel"), True)

        route = parse_route(["--parallel-deps"], env={})
        self.assertEqual(route.flags.get("requirements_parallel"), True)

        route = parse_route(["--requirements-parallel"], env={})
        self.assertEqual(route.flags.get("requirements_parallel"), True)

        route = parse_route(["--deps-sequential"], env={})
        self.assertEqual(route.flags.get("requirements_parallel"), False)

        route = parse_route(["--sequential-deps"], env={})
        self.assertEqual(route.flags.get("requirements_parallel"), False)

        route = parse_route(["--requirements-sequential"], env={})
        self.assertEqual(route.flags.get("requirements_parallel"), False)

        route = parse_route(["--no-requirements-parallel"], env={})
        self.assertEqual(route.flags.get("requirements_parallel"), False)

        with self.assertRaises(RouteError):
            parse_route(["--parallel"], env={})

    def test_value_flags_reject_option_like_values(self) -> None:
        with self.assertRaises(RouteError):
            parse_route(["--project", "--help"], env={})
        with self.assertRaises(RouteError):
            parse_route(["--projects", "--help"], env={})
        with self.assertRaises(RouteError):
            parse_route(["--service", "--help"], env={})
        with self.assertRaises(RouteError):
            parse_route(["--setup-worktrees", "feature-x", "--help"], env={})
        with self.assertRaises(RouteError):
            parse_route(["--setup-worktree", "feature-x", "--help"], env={})

    def test_registry_source_tokens_are_uniqueness_checked(self) -> None:
        boolean_source = getattr(command_router, "_BOOLEAN_FLAG_TOKENS", None)
        alias_source = getattr(command_router, "_COMMAND_ALIAS_PAIRS", None)
        self.assertIsNotNone(boolean_source)
        self.assertIsNotNone(alias_source)
        assert isinstance(boolean_source, tuple)
        assert isinstance(alias_source, tuple)
        self.assertEqual(len(boolean_source), len(set(boolean_source)))
        alias_keys = [key for key, _value in alias_source]
        self.assertEqual(len(alias_keys), len(set(alias_keys)))


if __name__ == "__main__":
    unittest.main()
