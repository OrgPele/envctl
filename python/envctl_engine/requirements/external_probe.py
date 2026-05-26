from __future__ import annotations

import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from envctl_engine.requirements.external_env import ExternalDependencyEnvResolver
from envctl_engine.requirements.external_env import normalize_dependency_id
from envctl_engine.requirements.external_env import url_port
from envctl_engine.shared.parsing import parse_bool


class ExternalDependencyProbe:
    """Performs optional live reachability probes for externally managed dependencies."""

    def __init__(self, runtime: Any) -> None:
        self._env = ExternalDependencyEnvResolver(runtime)

    def probe_error(self, dependency_id: str) -> str | None:
        if not self.enabled():
            return None
        dependency = normalize_dependency_id(dependency_id)
        timeout = self.timeout_seconds()
        if dependency == "postgres":
            return self._tcp_probe_error("postgres", self._env.raw("DATABASE_URL"), timeout=timeout)
        if dependency == "redis":
            return self._tcp_probe_error("redis", self._env.raw("REDIS_URL"), timeout=timeout)
        if dependency == "n8n":
            return self._http_probe_error(
                "n8n",
                self._external_health_url(self._env.raw("N8N_URL"), "healthz"),
                timeout=timeout,
            )
        if dependency == "supabase":
            url = self._env.raw("SUPABASE_URL") or self._env.raw("SUPABASE_PUBLIC_URL")
            anon_key = self._env.supabase_anon_key()
            headers = {"apikey": anon_key, "Authorization": f"Bearer {anon_key}"} if anon_key else {}
            return self._http_probe_error(
                "supabase",
                self._external_health_url(url, "auth/v1/health"),
                timeout=timeout,
                headers=headers,
            )
        return None

    def enabled(self) -> bool:
        raw = self._env.raw("ENVCTL_EXTERNAL_DEPENDENCY_PROBE")
        return parse_bool(raw, True)

    def timeout_seconds(self) -> float:
        raw = self._env.raw("ENVCTL_EXTERNAL_DEPENDENCY_PROBE_TIMEOUT")
        try:
            timeout = float(str(raw).strip()) if raw is not None else 3.0
        except ValueError:
            timeout = 3.0
        return max(timeout, 0.1)

    def _tcp_probe_error(self, dependency: str, raw_url: object, *, timeout: float) -> str | None:
        if not raw_url:
            return f"{dependency} external probe failed: missing URL"
        parsed = urlparse(str(raw_url))
        host = parsed.hostname
        port = url_port(raw_url)
        if not host or port is None:
            return f"{dependency} external probe failed: invalid URL {self._redacted_url(raw_url)!r}"
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return None
        except OSError as exc:
            return f"{dependency} external probe failed: cannot connect to {host}:{port}: {exc}"

    @staticmethod
    def _http_probe_error(
        dependency: str,
        url: str | None,
        *,
        timeout: float,
        headers: dict[str, str] | None = None,
    ) -> str | None:
        if not url:
            return f"{dependency} external probe failed: missing URL"
        request = Request(url, headers=headers or {}, method="GET")
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310
                status = int(getattr(response, "status", 0) or 0)
                if 200 <= status < 400:
                    return None
                return f"{dependency} external probe failed: GET {url} returned HTTP {status}"
        except HTTPError as exc:
            return f"{dependency} external probe failed: GET {url} returned HTTP {exc.code}"
        except (OSError, URLError) as exc:
            return f"{dependency} external probe failed: GET {url} failed: {exc}"

    @staticmethod
    def _external_health_url(raw_url: object, path: str) -> str | None:
        if not raw_url:
            return None
        base = str(raw_url).strip()
        if not base:
            return None
        return f"{base.rstrip('/')}/{path.lstrip('/')}"

    @staticmethod
    def _redacted_url(raw_url: object) -> str:
        if not raw_url:
            return ""
        parsed = urlparse(str(raw_url))
        if parsed.password is None:
            return str(raw_url)
        netloc = parsed.hostname or ""
        try:
            port = parsed.port
        except ValueError:
            port = None
        if port is not None:
            netloc = f"{netloc}:{port}"
        if parsed.username:
            netloc = f"{parsed.username}:<redacted>@{netloc}"
        return parsed._replace(netloc=netloc).geturl()


def external_dependency_probe_error(runtime: Any, dependency_id: str) -> str | None:
    return ExternalDependencyProbe(runtime).probe_error(dependency_id)


__all__ = [
    "ExternalDependencyProbe",
    "external_dependency_probe_error",
]
