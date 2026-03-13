from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.config import discover_local_config_state, load_config


class ConfigLoaderTests(unittest.TestCase):
    def test_env_overrides_envctl_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".envctl").write_text(
                'ENVCTL_DEFAULT_MODE="main"\nBACKEND_PORT_BASE=8000\n',
                encoding="utf-8",
            )

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "ENVCTL_DEFAULT_MODE": "trees",
                    "BACKEND_PORT_BASE": "8100",
                }
            )

            self.assertEqual(config.default_mode, "trees")
            self.assertEqual(config.backend_port_base, 8100)

    def test_envctl_sh_is_parsed_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".envctl.sh").write_text(
                'ENVCTL_DEFAULT_MODE="trees"\nMALICIOUS=$(echo no)\n',
                encoding="utf-8",
            )

            config = load_config({"RUN_REPO_ROOT": str(repo)})

            self.assertEqual(config.default_mode, "trees")
            self.assertEqual(config.raw["MALICIOUS"], "$(echo no)")

    def test_discover_local_config_state_prefers_envctl_and_tracks_legacy_prefill(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".envctl.sh").write_text("ENVCTL_DEFAULT_MODE=trees\n", encoding="utf-8")

            local_state = discover_local_config_state(repo)

            self.assertFalse(local_state.config_file_exists)
            self.assertEqual(local_state.config_source, "legacy_prefill")
            self.assertEqual(local_state.legacy_source_path, (repo / ".envctl.sh").resolve())

    def test_load_config_exposes_profiles_and_compatibility_mirrors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".envctl").write_text(
                "\n".join(
                    [
                        "ENVCTL_DEFAULT_MODE=trees",
                        "MAIN_STARTUP_ENABLE=false",
                        "MAIN_BACKEND_ENABLE=false",
                        "MAIN_FRONTEND_ENABLE=true",
                        "MAIN_POSTGRES_ENABLE=false",
                        "MAIN_REDIS_ENABLE=true",
                        "MAIN_SUPABASE_ENABLE=true",
                        "MAIN_N8N_ENABLE=true",
                        "TREES_BACKEND_ENABLE=true",
                        "TREES_FRONTEND_ENABLE=false",
                        "TREES_POSTGRES_ENABLE=true",
                        "TREES_REDIS_ENABLE=false",
                        "TREES_SUPABASE_ENABLE=false",
                        "TREES_N8N_ENABLE=true",
                        "BACKEND_PORT_BASE=8100",
                        "PORT_SPACING=7",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            config = load_config({"RUN_REPO_ROOT": str(repo)})

            self.assertEqual(config.default_mode, "trees")
            self.assertFalse(config.main_profile.startup_enable)
            self.assertFalse(config.main_profile.backend_enable)
            self.assertTrue(config.main_profile.supabase_enable)
            self.assertFalse(config.trees_profile.frontend_enable)
            self.assertEqual(config.port_defaults.backend_port_base, 8100)
            self.assertEqual(config.port_defaults.port_spacing, 7)
            self.assertFalse(config.postgres_main_enable)
            self.assertTrue(config.redis_main_enable)
            self.assertTrue(config.supabase_main_enable)
            self.assertTrue(config.n8n_main_enable)
            self.assertTrue(config.redis_enable)
            self.assertTrue(config.n8n_enable)
            self.assertFalse(config.startup_enabled_for_mode("main"))
            self.assertTrue(config.startup_enabled_for_mode("trees"))

    def test_load_config_reads_backend_and_frontend_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".envctl").write_text(
                "BACKEND_DIR=api\nFRONTEND_DIR=web\n",
                encoding="utf-8",
            )

            config = load_config({"RUN_REPO_ROOT": str(repo)})

            self.assertEqual(config.backend_dir_name, "api")
            self.assertEqual(config.frontend_dir_name, "web")

    def test_load_config_autodetects_backend_and_frontend_dirs_when_unset(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "src").mkdir(parents=True, exist_ok=True)
            (repo / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
            frontend = repo / "frontend"
            frontend.mkdir(parents=True, exist_ok=True)
            (frontend / "package.json").write_text(
                '{"name":"demo","scripts":{"dev":"vite"}}\n',
                encoding="utf-8",
            )
            (repo / ".envctl").write_text("", encoding="utf-8")

            config = load_config({"RUN_REPO_ROOT": str(repo)})

            self.assertEqual(config.backend_dir_name, "src")
            self.assertEqual(config.frontend_dir_name, "frontend")

    def test_load_config_autodetects_backend_test_command_when_unset(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            tests_dir = repo / "tests"
            tests_dir.mkdir(parents=True, exist_ok=True)
            (tests_dir / "test_sample.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
            (repo / ".envctl").write_text("", encoding="utf-8")

            config = load_config({"RUN_REPO_ROOT": str(repo)})

            self.assertIn("ENVCTL_BACKEND_TEST_CMD", config.raw)
            self.assertEqual(config.raw["ENVCTL_BACKEND_TEST_CMD"], "")
            self.assertTrue(config.backend_test_cmd.endswith(" -m unittest discover -s tests -p test_*.py"))

    def test_load_config_autodetects_frontend_test_path_when_unset(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            frontend = repo / "frontend"
            src_dir = frontend / "src"
            src_dir.mkdir(parents=True, exist_ok=True)
            (frontend / "package.json").write_text(
                '{"name":"app","scripts":{"test":"vitest run"}}\n',
                encoding="utf-8",
            )
            (frontend / "bun.lockb").write_text("", encoding="utf-8")
            (src_dir / "app.test.ts").write_text("it('works', () => {})\n", encoding="utf-8")
            (repo / ".envctl").write_text("", encoding="utf-8")

            config = load_config({"RUN_REPO_ROOT": str(repo)})

            self.assertEqual(config.frontend_test_path, "src")

    def test_load_config_uses_managed_dependency_baseline_when_envctl_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".envctl").write_text(
                "\n".join(
                    [
                        "ENVCTL_DEFAULT_MODE=main",
                        "BACKEND_DIR=src",
                        "ENVCTL_BACKEND_START_CMD=python main.py",
                        "MAIN_FRONTEND_ENABLE=false",
                        "TREES_STARTUP_ENABLE=false",
                        "TREES_FRONTEND_ENABLE=false",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            config = load_config({"RUN_REPO_ROOT": str(repo)})

            self.assertFalse(config.main_profile.postgres_enable)
            self.assertFalse(config.main_profile.redis_enable)
            self.assertFalse(config.main_profile.supabase_enable)
            self.assertFalse(config.main_profile.n8n_enable)
            self.assertFalse(config.trees_profile.postgres_enable)
            self.assertFalse(config.trees_profile.redis_enable)
            self.assertFalse(config.trees_profile.supabase_enable)
            self.assertFalse(config.trees_profile.n8n_enable)
            self.assertFalse(config.postgres_main_enable)
            self.assertFalse(config.redis_main_enable)
            self.assertFalse(config.redis_enable)
            self.assertFalse(config.n8n_main_enable)
            self.assertFalse(config.n8n_enable)


if __name__ == "__main__":
    unittest.main()
