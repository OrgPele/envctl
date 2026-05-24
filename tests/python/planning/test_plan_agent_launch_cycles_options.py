# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *


class PlanAgentLaunchCyclesOptionsTests(PlanAgentLaunchSupportTestCase):
    def test_resolve_plan_agent_launch_config_parses_codex_cycles(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                config = load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                        "ENVCTL_PLAN_AGENT_CODEX_CYCLES": "2",
                    }
                )

                launch_config = launch_support.resolve_plan_agent_launch_config(config, {})

            self.assertEqual(launch_config.codex_cycles, 2)
            self.assertIsNone(launch_config.codex_cycles_warning)

    def test_resolve_plan_agent_launch_config_applies_cycles_alias(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                config = load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                        "CYCLES": "3",
                    }
                )

                launch_config = launch_support.resolve_plan_agent_launch_config(config, {})

            self.assertEqual(launch_config.codex_cycles, 3)
            self.assertIsNone(launch_config.codex_cycles_warning)

    def test_resolve_plan_agent_launch_config_prefers_canonical_cycles_over_alias(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                config = load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                        "ENVCTL_PLAN_AGENT_CODEX_CYCLES": "3",
                        "CYCLES": "2",
                    }
                )

                launch_config = launch_support.resolve_plan_agent_launch_config(config, {})

            self.assertEqual(launch_config.codex_cycles, 3)
            self.assertIsNone(launch_config.codex_cycles_warning)

    def test_resolve_plan_agent_launch_config_bounds_above_maximum_canonical_cycles(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                config = load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                        "ENVCTL_PLAN_AGENT_CODEX_CYCLES": "4",
                    }
                )

                launch_config = launch_support.resolve_plan_agent_launch_config(config, {})

            self.assertEqual(launch_config.codex_cycles, 3)
            self.assertEqual(launch_config.codex_cycles_warning, "bounded_codex_cycles")

    def test_resolve_plan_agent_launch_config_reports_invalid_cycles_alias(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                config = load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                        "CYCLES": "many",
                    }
                )

                launch_config = launch_support.resolve_plan_agent_launch_config(config, {})

            self.assertEqual(launch_config.codex_cycles, 0)
            self.assertEqual(launch_config.codex_cycles_warning, "invalid_codex_cycles")

    def test_resolve_plan_agent_launch_config_bounds_large_cycles_alias(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                config = load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                        "CYCLES": "999",
                    }
                )

                launch_config = launch_support.resolve_plan_agent_launch_config(config, {})

            self.assertEqual(launch_config.codex_cycles, 3)
            self.assertEqual(launch_config.codex_cycles_warning, "bounded_codex_cycles")

    def test_resolve_plan_agent_launch_config_ignores_invalid_codex_cycles(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                config = load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                        "ENVCTL_PLAN_AGENT_CODEX_CYCLES": "many",
                    }
                )

                launch_config = launch_support.resolve_plan_agent_launch_config(config, {})

            self.assertEqual(launch_config.codex_cycles, 0)
            self.assertEqual(launch_config.codex_cycles_warning, "invalid_codex_cycles")
