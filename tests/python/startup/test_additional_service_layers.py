from __future__ import annotations

import unittest

from envctl_engine.config import AppServiceConfig
from envctl_engine.startup.service_execution import ordered_service_layers


class AdditionalServiceLayerTests(unittest.TestCase):
    def test_ordered_service_layers_respects_backend_and_service_dependencies(self) -> None:
        services = (
            AppServiceConfig(
                name="voice-runtime",
                env_suffix="VOICE_RUNTIME",
                enabled_main=True,
                enabled_trees=True,
                dir_name="voice-runtime",
                start_cmd="python voice.py {port}",
                port_base=8010,
                depends_on=("backend", "worker"),
                start_order=20,
            ),
            AppServiceConfig(
                name="worker",
                env_suffix="WORKER",
                enabled_main=True,
                enabled_trees=True,
                dir_name="backend",
                start_cmd="python worker.py",
                expect_listener=False,
                start_order=10,
            ),
        )

        layers = ordered_service_layers(["backend", "frontend", "voice-runtime", "worker"], services)

        self.assertEqual(layers, [("backend", "frontend", "worker"), ("voice-runtime",)])

    def test_ordered_service_layers_reports_cycles(self) -> None:
        services = (
            AppServiceConfig(
                name="voice-runtime",
                env_suffix="VOICE_RUNTIME",
                enabled_main=True,
                enabled_trees=True,
                dir_name="voice-runtime",
                start_cmd="python voice.py {port}",
                port_base=8010,
                depends_on=("worker",),
            ),
            AppServiceConfig(
                name="worker",
                env_suffix="WORKER",
                enabled_main=True,
                enabled_trees=True,
                dir_name="backend",
                start_cmd="python worker.py",
                expect_listener=False,
                depends_on=("voice-runtime",),
            ),
        )

        with self.assertRaisesRegex(RuntimeError, "additional service dependency cycle"):
            ordered_service_layers(["voice-runtime", "worker"], services)


if __name__ == "__main__":
    unittest.main()
