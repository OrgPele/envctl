from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.network_exposure import (  # noqa: E402
    NetworkExposureError,
    backend_api_url,
    command_replacements,
    resolve_network_exposure,
    service_url,
)


class NetworkExposureTests(unittest.TestCase):
    def test_defaults_keep_localhost_urls_and_loopback_bind(self) -> None:
        exposure = resolve_network_exposure({}, {})

        self.assertFalse(exposure.enabled)
        self.assertEqual(exposure.public_host, "localhost")
        self.assertEqual(exposure.url_host, "localhost")
        self.assertEqual(exposure.bind_host, "127.0.0.1")
        self.assertEqual(service_url(8000, exposure), "http://localhost:8000")
        self.assertEqual(backend_api_url(8000, exposure), "http://localhost:8000/api/v1")

    def test_public_host_enables_all_interface_bind_and_remote_urls(self) -> None:
        exposure = resolve_network_exposure({}, {"ENVCTL_PUBLIC_HOST": "203.0.113.10"})

        self.assertTrue(exposure.enabled)
        self.assertEqual(exposure.public_host, "203.0.113.10")
        self.assertEqual(exposure.url_host, "203.0.113.10")
        self.assertEqual(exposure.bind_host, "0.0.0.0")
        self.assertEqual(service_url(9000, exposure), "http://203.0.113.10:9000")
        self.assertEqual(command_replacements(9000, exposure)["bind_host"], "0.0.0.0")

    def test_loopback_public_host_does_not_enable_remote_exposure(self) -> None:
        for host in ("localhost", "127.0.0.1", "::1", "[::1]"):
            with self.subTest(host=host):
                exposure = resolve_network_exposure({}, {"ENVCTL_PUBLIC_HOST": host})
                self.assertFalse(exposure.enabled)
                self.assertEqual(exposure.bind_host, "127.0.0.1")

    def test_ipv6_public_host_is_bracketed_for_urls(self) -> None:
        unbracketed = resolve_network_exposure({}, {"ENVCTL_PUBLIC_HOST": "2001:db8::1"})
        bracketed = resolve_network_exposure({}, {"ENVCTL_PUBLIC_HOST": "[2001:db8::1]"})

        self.assertEqual(unbracketed.public_host, "2001:db8::1")
        self.assertEqual(unbracketed.url_host, "[2001:db8::1]")
        self.assertEqual(service_url(8000, unbracketed), "http://[2001:db8::1]:8000")
        self.assertEqual(bracketed.url_host, "[2001:db8::1]")

    def test_invalid_full_url_public_host_is_rejected_with_actionable_message(self) -> None:
        with self.assertRaises(NetworkExposureError) as cm:
            resolve_network_exposure({}, {"ENVCTL_PUBLIC_HOST": "http://203.0.113.10:8000"})

        self.assertIn("host/IP only, not a full URL", str(cm.exception))
        self.assertIn("203.0.113.10", str(cm.exception))

    def test_hostname_with_embedded_port_is_rejected(self) -> None:
        with self.assertRaises(NetworkExposureError):
            resolve_network_exposure({}, {"ENVCTL_PUBLIC_HOST": "dev.example.com:8000"})

    def test_public_host_rejects_bind_wildcard_addresses(self) -> None:
        for host in ("0.0.0.0", "::", "[::]"):
            with self.subTest(host=host):
                with self.assertRaises(NetworkExposureError) as cm:
                    resolve_network_exposure({}, {"ENVCTL_PUBLIC_HOST": host})

                self.assertIn("browser-openable", str(cm.exception))
                self.assertIn("ENVCTL_SERVICE_BIND_HOST", str(cm.exception))

    def test_explicit_bind_host_overrides_public_default(self) -> None:
        exposure = resolve_network_exposure(
            {},
            {"ENVCTL_PUBLIC_HOST": "dev.example.com", "ENVCTL_SERVICE_BIND_HOST": "192.0.2.10"},
        )

        self.assertTrue(exposure.enabled)
        self.assertEqual(exposure.bind_host, "192.0.2.10")


if __name__ == "__main__":
    unittest.main()
