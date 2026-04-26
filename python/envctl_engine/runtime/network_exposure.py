from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import re
from typing import Mapping


PUBLIC_HOST_KEY = "ENVCTL_PUBLIC_HOST"
SERVICE_BIND_HOST_KEY = "ENVCTL_SERVICE_BIND_HOST"

_LOOPBACK_HOSTS = {"", "localhost", "127.0.0.1", "::1", "[::1]"}
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}\.?$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(?:\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*\.?$"
)


class NetworkExposureError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class NetworkExposure:
    public_host: str
    url_host: str
    bind_host: str
    enabled: bool


def resolve_network_exposure(env: Mapping[str, str], config_raw: Mapping[str, str]) -> NetworkExposure:
    public_host_raw = _override_value(PUBLIC_HOST_KEY, env=env, config_raw=config_raw)
    bind_host_raw = _override_value(SERVICE_BIND_HOST_KEY, env=env, config_raw=config_raw)

    public_host = _normalize_host_value(public_host_raw or "", key=PUBLIC_HOST_KEY, allow_empty=True)
    public_for_loopback = _loopback_key(public_host)
    enabled = public_for_loopback not in _LOOPBACK_HOSTS
    displayed_public_host = public_host if public_host else "localhost"
    url_host = format_url_host(displayed_public_host)

    if bind_host_raw is not None and str(bind_host_raw).strip():
        bind_host = _normalize_host_value(bind_host_raw, key=SERVICE_BIND_HOST_KEY, allow_empty=False)
    else:
        bind_host = "0.0.0.0" if enabled else "127.0.0.1"

    return NetworkExposure(
        public_host=displayed_public_host,
        url_host=url_host,
        bind_host=bind_host,
        enabled=enabled,
    )


def service_url(port: int, exposure: NetworkExposure) -> str:
    return f"http://{exposure.url_host}:{int(port)}"


def backend_api_url(port: int, exposure: NetworkExposure) -> str:
    return f"{service_url(port, exposure)}/api/v1"


def command_replacements(port: int, exposure: NetworkExposure) -> dict[str, str]:
    return {
        "port": str(int(port)),
        "bind_host": exposure.bind_host,
        "public_host": exposure.public_host,
        "url_host": exposure.url_host,
    }


def format_url_host(host: str) -> str:
    normalized = _normalize_host_value(host, key=PUBLIC_HOST_KEY, allow_empty=True)
    if not normalized:
        return "localhost"
    try:
        ip = ipaddress.ip_address(_strip_ipv6_brackets(normalized))
    except ValueError:
        return normalized
    if ip.version == 6:
        return f"[{ip.compressed}]"
    return str(ip)


def validate_public_host(value: str) -> None:
    _normalize_host_value(value, key=PUBLIC_HOST_KEY, allow_empty=True)


def validate_bind_host(value: str) -> None:
    _normalize_host_value(value, key=SERVICE_BIND_HOST_KEY, allow_empty=True)


def _override_value(key: str, *, env: Mapping[str, str], config_raw: Mapping[str, str]) -> str | None:
    if key in env:
        return str(env.get(key) or "")
    if key in config_raw:
        return str(config_raw.get(key) or "")
    return None


def _normalize_host_value(raw: str, *, key: str, allow_empty: bool) -> str:
    value = str(raw or "").strip()
    if not value:
        if allow_empty:
            return ""
        raise NetworkExposureError(f"Set {key} only to a bind address such as `127.0.0.1` or `0.0.0.0`.")
    if "://" in value:
        example = "203.0.113.10" if key == PUBLIC_HOST_KEY else "0.0.0.0"
        raise NetworkExposureError(
            f"Set {key} to a host/IP only, not a full URL. Use `{example}`, not `http://{example}:8000`."
        )
    if "/" in value:
        raise NetworkExposureError(f"Set {key} to a host/IP only, without paths or slash characters.")

    unbracketed = _strip_ipv6_brackets(value)
    try:
        ip = ipaddress.ip_address(unbracketed)
    except ValueError:
        if ":" in value:
            raise NetworkExposureError(
                f"Set {key} to a host/IP only, without an embedded port. "
                "Use an IPv6 literal without a port or a DNS hostname."
            )
        if not _HOSTNAME_RE.match(value):
            raise NetworkExposureError(f"Set {key} to a valid IPv4 address, IPv6 address, or DNS hostname.")
        return value.rstrip(".")

    if key == PUBLIC_HOST_KEY and ip.is_unspecified:
        raise NetworkExposureError(
            f"Set {key} to a browser-openable host/IP, not a bind wildcard such as `0.0.0.0`. "
            "Use ENVCTL_SERVICE_BIND_HOST=0.0.0.0 when you only need to override the bind address."
        )

    return ip.compressed


def _strip_ipv6_brackets(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("[") or text.endswith("]"):
        if not (text.startswith("[") and text.endswith("]")):
            raise NetworkExposureError("IPv6 literals must use matching brackets.")
        return text[1:-1]
    return text


def _loopback_key(host: str) -> str:
    value = str(host or "").strip().lower()
    if value in {"localhost", ""}:
        return value
    try:
        ip = ipaddress.ip_address(_strip_ipv6_brackets(value))
    except ValueError:
        return value
    if ip.is_loopback:
        return "::1" if ip.version == 6 else "127.0.0.1"
    return ip.compressed
