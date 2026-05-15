from __future__ import annotations

import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.requirements.common import (
    _docker_port_publish_lock_enabled,
    build_container_name,
    container_host_port,
    docker_image_pull_policy,
    docker_port_publish_lock,
)


class _Runner:
    def __init__(self) -> None:
        self.inspect_payload = '{"6379/tcp":[{"HostIp":"","HostPort":"6440"}]}'

    def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
        _ = cwd, env, timeout
        command = list(cmd)
        if command[:2] == ["docker", "port"]:
            return subprocess.CompletedProcess(
                command,
                1,
                "",
                "no public port '6379' published for envctl-redis-main",
            )
        if command[:3] == ["docker", "inspect", "-f"]:
            return subprocess.CompletedProcess(command, 0, self.inspect_payload, "")
        return subprocess.CompletedProcess(command, 0, "", "")


class RequirementsCommonTests(unittest.TestCase):
    def test_build_container_name_preserves_digest_for_long_names(self) -> None:
        root = Path("/tmp/repo-a")
        name = build_container_name(
            prefix="envctl-supabase",
            project_root=root,
            project_name="implementations_hebrew_rtl_full_app_localization_100_percent_gap_closure-1",
        )
        self.assertLessEqual(len(name), 63)
        self.assertRegex(name, r"-[0-9a-f]{8}$")

    def test_build_container_name_distinguishes_long_similar_names(self) -> None:
        name_a = build_container_name(
            prefix="envctl-supabase",
            project_root=Path("/tmp/repo-a"),
            project_name="implementations_hebrew_rtl_full_app_localization_plan-1",
        )
        name_b = build_container_name(
            prefix="envctl-supabase",
            project_root=Path("/tmp/repo-b"),
            project_name="implementations_hebrew_rtl_full_app_localization_100_percent_gap_closure-1",
        )
        self.assertNotEqual(name_a, name_b)

    def test_container_host_port_uses_inspect_fallback_for_stopped_container(self) -> None:
        runner = _Runner()
        mapped_port, error = container_host_port(
            runner,
            container_name="envctl-redis-main",
            container_port=6379,
        )
        self.assertIsNone(error)
        self.assertEqual(mapped_port, 6440)

    def test_container_host_port_returns_none_when_inspect_payload_missing_port(self) -> None:
        runner = _Runner()
        runner.inspect_payload = "{}"
        mapped_port, error = container_host_port(
            runner,
            container_name="envctl-redis-main",
            container_port=6379,
        )
        self.assertIsNone(error)
        self.assertIsNone(mapped_port)

    def test_docker_port_publish_lock_auto_defaults_to_darwin_only(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch(
            "envctl_engine.requirements.common.sys.platform",
            "darwin",
        ):
            self.assertTrue(_docker_port_publish_lock_enabled({}))
            self.assertTrue(_docker_port_publish_lock_enabled({"ENVCTL_DOCKER_PORT_PUBLISH_LOCK": "auto"}))

        with mock.patch.dict(os.environ, {}, clear=True), mock.patch(
            "envctl_engine.requirements.common.sys.platform",
            "linux",
        ):
            self.assertFalse(_docker_port_publish_lock_enabled({}))
            self.assertFalse(_docker_port_publish_lock_enabled({"ENVCTL_DOCKER_PORT_PUBLISH_LOCK": "auto"}))

    def test_docker_port_publish_lock_env_overrides_auto_default(self) -> None:
        with mock.patch("envctl_engine.requirements.common.sys.platform", "linux"):
            self.assertTrue(_docker_port_publish_lock_enabled({"ENVCTL_DOCKER_PORT_PUBLISH_LOCK": "true"}))

        with mock.patch("envctl_engine.requirements.common.sys.platform", "darwin"):
            self.assertFalse(_docker_port_publish_lock_enabled({"ENVCTL_DOCKER_PORT_PUBLISH_LOCK": "false"}))

    def test_docker_image_pull_policy_defaults_to_missing(self) -> None:
        self.assertEqual(docker_image_pull_policy({}, "ENVCTL_TEST_PULL_POLICY"), "missing")
        self.assertEqual(
            docker_image_pull_policy({"ENVCTL_TEST_PULL_POLICY": "if-missing"}, "ENVCTL_TEST_PULL_POLICY"),
            "missing",
        )

    def test_docker_image_pull_policy_supports_legacy_boolean_override(self) -> None:
        self.assertEqual(
            docker_image_pull_policy(
                {"ENVCTL_TEST_PULL_IMAGE": "true"},
                "ENVCTL_TEST_PULL_POLICY",
                legacy_bool_key="ENVCTL_TEST_PULL_IMAGE",
            ),
            "always",
        )
        self.assertEqual(
            docker_image_pull_policy(
                {"ENVCTL_TEST_PULL_IMAGE": "false"},
                "ENVCTL_TEST_PULL_POLICY",
                legacy_bool_key="ENVCTL_TEST_PULL_IMAGE",
            ),
            "never",
        )

    def test_docker_port_publish_lock_serializes_threads(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"RUN_SH_RUNTIME_DIR": tmpdir, "ENVCTL_DOCKER_PORT_PUBLISH_LOCK": "true"}
            first_entered = threading.Event()
            release_first = threading.Event()
            second_entered = threading.Event()

            def hold_lock() -> None:
                with docker_port_publish_lock(env):
                    first_entered.set()
                    release_first.wait(timeout=5.0)

            def wait_for_lock() -> None:
                first_entered.wait(timeout=5.0)
                with docker_port_publish_lock(env):
                    second_entered.set()

            first = threading.Thread(target=hold_lock)
            second = threading.Thread(target=wait_for_lock)
            first.start()
            self.assertTrue(first_entered.wait(timeout=5.0))
            second.start()
            time.sleep(0.1)
            self.assertFalse(second_entered.is_set())
            release_first.set()
            first.join(timeout=5.0)
            second.join(timeout=5.0)
            self.assertTrue(second_entered.is_set())


if __name__ == "__main__":
    unittest.main()
