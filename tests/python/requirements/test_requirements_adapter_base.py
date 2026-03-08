from __future__ import annotations

import unittest
from pathlib import Path
import sys
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.requirements.adapter_base import (
    env_bool,
    env_float,
    env_int,
    retryable_probe_error,
    sleep_between_probes,
)


class RequirementsAdapterBaseTests(unittest.TestCase):
    def test_env_helpers_parse_values(self) -> None:
        env = {
            "FLAG_TRUE": "true",
            "COUNT": "7",
            "TIMEOUT": "1.25",
        }
        self.assertTrue(env_bool(env, "FLAG_TRUE", False))
        self.assertFalse(env_bool(env, "MISSING", False))
        self.assertEqual(env_int(env, "COUNT", 0), 7)
        self.assertEqual(env_int(env, "COUNT_BAD", 5), 5)
        self.assertAlmostEqual(env_float(env, "TIMEOUT", 0.5), 1.25)
        self.assertEqual(env_float(env, "TIMEOUT_BAD", 0.5), 0.5)

    def test_sleep_between_probes_prefers_runner_sleep(self) -> None:
        calls: list[float] = []
        runner = SimpleNamespace(sleep=lambda seconds: calls.append(seconds))
        sleep_between_probes(runner, 0.2)
        self.assertEqual(calls, [0.2])

    def test_retryable_probe_error_matches_any_token(self) -> None:
        tokens = ("timeout", "temporarily unavailable")
        self.assertTrue(retryable_probe_error("connection timeout", tokens))
        self.assertFalse(retryable_probe_error("permission denied", tokens))


if __name__ == "__main__":
    unittest.main()
