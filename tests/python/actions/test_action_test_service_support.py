from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from envctl_engine.actions.action_test_service_support import AdditionalServiceTestPlanner
from envctl_engine.actions.action_test_service_support import additional_service_test_execution_specs
from envctl_engine.runtime.command_router import parse_route


class _Config:
    def __init__(self, services: dict[str, object]) -> None:
        self._services = services

    def app_service_by_name(self, name: str) -> object | None:
        return self._services.get(name)


class ActionTestServiceSupportTests(unittest.TestCase):
    def test_returns_empty_when_no_additional_services_are_selected(self) -> None:
        route = parse_route(["test", "--service", "backend"], env={"ENVCTL_DEFAULT_MODE": "trees"})

        specs = additional_service_test_execution_specs(
            route=route,
            targets=[],
            target_contexts=[],
            config=_Config({}),
            split_command=lambda raw, replacements: raw.split(),
            action_replacements_builder=lambda _targets, target: {},
        )

        self.assertEqual(specs, [])

    def test_unknown_additional_service_is_actionable(self) -> None:
        route = parse_route(["test", "--service", "voice-runtime"], env={"ENVCTL_DEFAULT_MODE": "trees"})

        with self.assertRaisesRegex(RuntimeError, "Unknown additional service 'voice-runtime'"):
            additional_service_test_execution_specs(
                route=route,
                targets=[],
                target_contexts=[],
                config=_Config({}),
                split_command=lambda raw, replacements: raw.split(),
                action_replacements_builder=lambda _targets, target: {},
            )

    def test_missing_additional_service_test_command_mentions_env_key(self) -> None:
        route = parse_route(["test", "--service", "voice-runtime"], env={"ENVCTL_DEFAULT_MODE": "trees"})
        service = SimpleNamespace(test_cmd="", env_suffix="VOICE_RUNTIME", dir_name="services/voice")

        with self.assertRaisesRegex(RuntimeError, "Set ENVCTL_SERVICE_VOICE_RUNTIME_TEST_CMD"):
            additional_service_test_execution_specs(
                route=route,
                targets=[],
                target_contexts=[],
                config=_Config({"voice-runtime": service}),
                split_command=lambda raw, replacements: raw.split(),
                action_replacements_builder=lambda _targets, target: {},
            )

    def test_builds_specs_for_each_target_with_replacements_and_service_cwd(self) -> None:
        route = parse_route(["test", "--service", "voice-runtime"], env={"ENVCTL_DEFAULT_MODE": "trees"})
        service = SimpleNamespace(test_cmd="npm test -- --project {project}", env_suffix="", dir_name="services/voice")
        target_a = SimpleNamespace(name="feature-a-1", root="/repo/trees/feature-a/1")
        target_b = SimpleNamespace(name="feature-b-1", root="/repo/trees/feature-b/1")
        context_a = SimpleNamespace(project_name="feature-a-1", project_root=Path(target_a.root), target_obj=target_a)
        context_b = SimpleNamespace(project_name="feature-b-1", project_root=Path(target_b.root), target_obj=target_b)

        specs = additional_service_test_execution_specs(
            route=route,
            targets=[target_a, target_b],
            target_contexts=[context_a, context_b],
            config=_Config({"voice-runtime": service}),
            split_command=lambda raw, replacements: [
                token.replace("{project}", replacements["project"]) for token in raw.split()
            ],
            action_replacements_builder=lambda _targets, target: {"project": target.name},
        )

        self.assertEqual([spec.index for spec in specs], [1, 2])
        self.assertEqual(specs[0].spec.command, ["npm", "test", "--", "--project", "feature-a-1"])
        self.assertEqual(specs[0].spec.cwd, Path("/repo/trees/feature-a/1/services/voice"))
        self.assertEqual(specs[0].resolved_source, "configured_service:voice-runtime")
        self.assertEqual(specs[1].spec.command, ["npm", "test", "--", "--project", "feature-b-1"])
        self.assertEqual(specs[1].spec.cwd, Path("/repo/trees/feature-b/1/services/voice"))

    def test_planner_object_matches_wrapper_and_keeps_service_policy_cohesive(self) -> None:
        route = parse_route(["test", "--service", "voice-runtime"], env={"ENVCTL_DEFAULT_MODE": "trees"})
        service = SimpleNamespace(test_cmd="npm test -- --project {project}", env_suffix="", dir_name=".")
        target = SimpleNamespace(name="feature-a-1", root="/repo/trees/feature-a/1")
        context = SimpleNamespace(project_name="feature-a-1", project_root=Path(target.root), target_obj=target)
        planner = AdditionalServiceTestPlanner(
            route=route,
            targets=[target],
            target_contexts=[context],
            config=_Config({"voice-runtime": service}),
            split_command=lambda raw, replacements: [
                token.replace("{project}", replacements["project"]) for token in raw.split()
            ],
            action_replacements_builder=lambda _targets, target: {"project": target.name},
        )

        specs = planner.build()
        wrapper_specs = additional_service_test_execution_specs(
            route=route,
            targets=[target],
            target_contexts=[context],
            config=_Config({"voice-runtime": service}),
            split_command=lambda raw, replacements: [
                token.replace("{project}", replacements["project"]) for token in raw.split()
            ],
            action_replacements_builder=lambda _targets, target: {"project": target.name},
        )

        self.assertEqual([spec.spec.command for spec in specs], [["npm", "test", "--", "--project", "feature-a-1"]])
        self.assertEqual(specs[0].spec.cwd, Path("/repo/trees/feature-a/1"))
        self.assertEqual([spec.spec.command for spec in wrapper_specs], [spec.spec.command for spec in specs])


if __name__ == "__main__":
    unittest.main()
