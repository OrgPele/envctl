from __future__ import annotations

from types import SimpleNamespace
import unittest

from envctl_engine.requirements.adapter_policy import (
    env_bool,
    env_float,
    env_int,
    port_mismatch_policy,
    retryable_probe_error,
    sleep_between_probes,
    timeout_error,
)


class RequirementsAdapterPolicyTests(unittest.TestCase):
    def test_env_helpers_parse_values_and_apply_minimums(self) -> None:
        env = {
            "FLAG_TRUE": "true",
            "COUNT": "7",
            "LOW_COUNT": "1",
            "TIMEOUT": "1.25",
            "LOW_TIMEOUT": "0.1",
        }
        self.assertTrue(env_bool(env, "FLAG_TRUE", False))
        self.assertFalse(env_bool(env, "MISSING", False))
        self.assertEqual(env_int(env, "COUNT", 0), 7)
        self.assertEqual(env_int(env, "LOW_COUNT", 0, minimum=3), 3)
        self.assertEqual(env_int(env, "COUNT_BAD", 5), 5)
        self.assertAlmostEqual(env_float(env, "TIMEOUT", 0.5), 1.25)
        self.assertAlmostEqual(env_float(env, "LOW_TIMEOUT", 0.5, minimum=0.5), 0.5)
        self.assertEqual(env_float(env, "TIMEOUT_BAD", 0.5), 0.5)

    def test_port_mismatch_policy_defaults_to_adopt_existing(self) -> None:
        self.assertEqual(port_mismatch_policy({}), "adopt_existing")
        self.assertEqual(port_mismatch_policy({"ENVCTL_REQUIREMENTS_PORT_MISMATCH_POLICY": "recreate"}), "recreate")
        self.assertEqual(port_mismatch_policy({"ENVCTL_REQUIREMENTS_PORT_MISMATCH_POLICY": "bad"}), "adopt_existing")

    def test_timeout_sleep_and_retry_helpers(self) -> None:
        calls: list[float] = []
        runner = SimpleNamespace(sleep=lambda seconds: calls.append(seconds))
        sleep_between_probes(runner, 0.2)

        self.assertEqual(calls, [0.2])
        self.assertTrue(timeout_error("command timed out after 1s"))
        self.assertFalse(timeout_error("connection refused"))
        self.assertTrue(retryable_probe_error("connection timeout", ("timeout", "temporarily unavailable")))
        self.assertFalse(retryable_probe_error("permission denied", ("timeout",)))


if __name__ == "__main__":
    unittest.main()
