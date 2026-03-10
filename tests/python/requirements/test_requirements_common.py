from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.requirements.common import build_container_name, container_host_port


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


if __name__ == "__main__":
    unittest.main()
