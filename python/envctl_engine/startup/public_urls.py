from __future__ import annotations

from typing import Any, Mapping


def resolve_public_host(*, env: Mapping[str, str] | None = None, config: Any | None = None) -> str:
    for source in (env, getattr(config, "raw", None)):
        if isinstance(source, Mapping):
            host = str(source.get("ENVCTL_PUBLIC_HOST") or "").strip()
            if host:
                return host
    return "localhost"


def browser_backend_url(*, host: str, port: int) -> str:
    return f"http://{host}:{int(port)}"
