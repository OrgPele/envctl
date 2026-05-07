from __future__ import annotations

import json
from dataclasses import dataclass, field
import re
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, build_opener



class SupabaseAuthUserRecordLike(Protocol):
    id: str
    email: str


class SupabaseAuthAdminClientLike(Protocol):
    def find_user_by_email(self, email: str) -> SupabaseAuthUserRecordLike | None: ...

    def create_user(
        self,
        *,
        email: str,
        password: str | None,
        email_confirm: bool,
        user_metadata: dict[str, object],
        app_metadata: dict[str, object],
    ) -> SupabaseAuthUserRecordLike: ...

    def update_user(
        self,
        user_id: str,
        *,
        password: str | None = None,
        email_confirm: bool | None = None,
        user_metadata: dict[str, object] | None = None,
        app_metadata: dict[str, object] | None = None,
    ) -> SupabaseAuthUserRecordLike: ...


@dataclass(slots=True)
class SupabaseAuthUserRecord:
    id: str
    email: str
    created_at: str = ""
    updated_at: str = ""
    confirmed_at: str = ""
    user_metadata: dict[str, object] = field(default_factory=dict)
    app_metadata: dict[str, object] = field(default_factory=dict)
    raw: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class SupabaseAuthUserSyncResult:
    name: str
    email: str
    status: str
    id: str | None = None
    error: str | None = None


@dataclass(slots=True)
class SupabaseAuthUserSyncSummary:
    success: bool
    results: tuple[SupabaseAuthUserSyncResult, ...]
    artifact: dict[str, object]


class SupabaseAuthAdminError(RuntimeError):
    pass


class SupabaseAuthAdminClient:
    def __init__(
        self,
        *,
        base_url: str,
        service_role_key: str,
        opener: Any | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.service_role_key = str(service_role_key or "").strip()
        self.opener = opener or build_opener()
        self.timeout = timeout
        if not self.base_url:
            raise SupabaseAuthAdminError("missing SUPABASE_URL for Supabase Auth Admin API")
        if not self.service_role_key:
            raise SupabaseAuthAdminError("missing SUPABASE_SERVICE_ROLE_KEY for Supabase Auth Admin API")

    def list_users(self, *, page: int = 1, per_page: int = 100) -> list[SupabaseAuthUserRecord]:
        query = urlencode({"page": max(int(page), 1), "per_page": max(int(per_page), 1)})
        payload = self._request("GET", f"/auth/v1/admin/users?{query}")
        if isinstance(payload, dict) and isinstance(payload.get("users"), list):
            return [_record_from_payload(item) for item in payload["users"] if isinstance(item, dict)]
        if isinstance(payload, list):
            return [_record_from_payload(item) for item in payload if isinstance(item, dict)]
        return []

    def find_user_by_email(self, email: str) -> SupabaseAuthUserRecord | None:
        target = str(email).strip().lower()
        page = 1
        while True:
            users = self.list_users(page=page, per_page=100)
            for user in users:
                if user.email.lower() == target:
                    return user
            if len(users) < 100:
                return None
            page += 1

    def create_user(
        self,
        *,
        email: str,
        password: str | None,
        email_confirm: bool,
        user_metadata: dict[str, object],
        app_metadata: dict[str, object],
    ) -> SupabaseAuthUserRecord:
        payload: dict[str, object] = {
            "email": email,
            "email_confirm": bool(email_confirm),
            "user_metadata": dict(user_metadata),
            "app_metadata": dict(app_metadata),
        }
        if password:
            payload["password"] = password
        result = self._request("POST", "/auth/v1/admin/users", payload=payload)
        return _record_from_payload(result if isinstance(result, dict) else {})

    def update_user(
        self,
        user_id: str,
        *,
        password: str | None = None,
        email_confirm: bool | None = None,
        user_metadata: dict[str, object] | None = None,
        app_metadata: dict[str, object] | None = None,
    ) -> SupabaseAuthUserRecord:
        payload: dict[str, object] = {}
        if password:
            payload["password"] = password
        if email_confirm is not None:
            payload["email_confirm"] = bool(email_confirm)
        if user_metadata is not None:
            payload["user_metadata"] = dict(user_metadata)
        if app_metadata is not None:
            payload["app_metadata"] = dict(app_metadata)
        result = self._request("PUT", f"/auth/v1/admin/users/{quote(user_id, safe='')}", payload=payload)
        return _record_from_payload(result if isinstance(result, dict) else {})

    def delete_user(self, user_id: str) -> None:
        self._request("DELETE", f"/auth/v1/admin/users/{quote(user_id, safe='')}")

    def _request(self, method: str, path: str, *, payload: dict[str, object] | None = None) -> object:
        path_text = path if path.startswith("/") else f"/{path}"
        url = f"{self.base_url}{path_text}"
        data = None
        headers = {
            "Authorization": f"Bearer {self.service_role_key}",
            "apikey": self.service_role_key,
            "Accept": "application/json",
        }
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=data, headers=headers, method=method.upper())
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            raw_error = exc.read().decode("utf-8", errors="replace")
            raise SupabaseAuthAdminError(
                _redact_message(
                    f"HTTP {exc.code} {path_text}: {_compact_error_payload(raw_error)}",
                    self.service_role_key,
                    payload,
                )
            ) from exc
        except URLError as exc:
            raise SupabaseAuthAdminError(
                _redact_message(
                    f"Supabase Auth Admin request failed {path_text}: {exc.reason}",
                    self.service_role_key,
                    payload,
                )
            ) from exc
        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SupabaseAuthAdminError(
                _redact_message(
                    f"Supabase Auth Admin returned invalid JSON {path_text}: {exc.msg}",
                    self.service_role_key,
                    payload,
                )
            ) from exc


def sync_supabase_auth_users(
    *,
    mode: str,
    configured_users: tuple[object, ...],
    base_url: str,
    service_role_key: str,
    runtime_root: Path,
    dry_run: bool = False,
    client: SupabaseAuthAdminClientLike | None = None,
) -> SupabaseAuthUserSyncSummary:
    admin: SupabaseAuthAdminClientLike = client or SupabaseAuthAdminClient(
        base_url=base_url, service_role_key=service_role_key
    )
    results: list[SupabaseAuthUserSyncResult] = []
    artifact_users: dict[str, dict[str, str]] = {}
    for user in configured_users:
        name = str(getattr(user, "name", "") or "").strip()
        email = str(getattr(user, "email", "") or "").strip()
        if not name:
            continue
        enabled_for_mode = getattr(user, "enabled_for_mode", None)
        if callable(enabled_for_mode) and not bool(enabled_for_mode(mode)):
            results.append(SupabaseAuthUserSyncResult(name=name, email=email, status="skipped"))
            continue
        try:
            existing = admin.find_user_by_email(email)
            if existing is None:
                if dry_run:
                    results.append(SupabaseAuthUserSyncResult(name=name, email=email, status="created"))
                    continue
                record = admin.create_user(
                    email=email,
                    password=getattr(user, "password", None),
                    email_confirm=bool(getattr(user, "auto_confirm", True)),
                    user_metadata=dict(getattr(user, "user_metadata", {}) or {}),
                    app_metadata=dict(getattr(user, "app_metadata", {}) or {}),
                )
                status = "created"
            elif _record_needs_update(existing, user):
                if dry_run:
                    record = existing
                else:
                    record = admin.update_user(
                        existing.id,
                        password=getattr(user, "password", None),
                        email_confirm=bool(getattr(user, "auto_confirm", True)),
                        user_metadata=dict(getattr(user, "user_metadata", {}) or {}),
                        app_metadata=dict(getattr(user, "app_metadata", {}) or {}),
                    )
                status = "updated"
            else:
                record = existing
                status = "unchanged"
            user_id = str(getattr(record, "id", "") or "")
            results.append(SupabaseAuthUserSyncResult(name=name, email=email, status=status, id=user_id))
            if user_id:
                artifact_users[name] = {"id": user_id, "email": email, "status": status}
        except Exception as exc:  # noqa: BLE001
            results.append(SupabaseAuthUserSyncResult(name=name, email=email, status="failed", error=str(exc)))
    artifact: dict[str, object] = {"mode": mode, "users": artifact_users}
    runtime_root.mkdir(parents=True, exist_ok=True)
    (runtime_root / "supabase_auth_users.json").write_text(
        json.dumps(artifact, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return SupabaseAuthUserSyncSummary(
        success=not any(result.status == "failed" for result in results),
        results=tuple(results),
        artifact=artifact,
    )


def sync_results_to_requirement_payload(summary: SupabaseAuthUserSyncSummary) -> dict[str, dict[str, str]]:
    users = summary.artifact.get("users")
    if isinstance(users, dict):
        return {
            str(slug): {str(key): str(value) for key, value in payload.items() if value is not None}
            for slug, payload in users.items()
            if isinstance(payload, dict)
        }
    return {}


def _record_needs_update(record: object, user: object) -> bool:
    desired_user_metadata = dict(getattr(user, "user_metadata", {}) or {})
    desired_app_metadata = dict(getattr(user, "app_metadata", {}) or {})
    if desired_user_metadata and dict(getattr(record, "user_metadata", {}) or {}) != desired_user_metadata:
        return True
    if desired_app_metadata and dict(getattr(record, "app_metadata", {}) or {}) != desired_app_metadata:
        return True
    if (
        bool(getattr(user, "auto_confirm", True))
        and hasattr(record, "confirmed_at")
        and not str(getattr(record, "confirmed_at", "") or "").strip()
    ):
        return True
    return bool(getattr(user, "password", None))


def _record_from_payload(payload: dict[str, object]) -> SupabaseAuthUserRecord:
    return SupabaseAuthUserRecord(
        id=str(payload.get("id", "") or ""),
        email=str(payload.get("email", "") or ""),
        created_at=str(payload.get("created_at", "") or ""),
        updated_at=str(payload.get("updated_at", "") or ""),
        confirmed_at=str(payload.get("confirmed_at", "") or ""),
        user_metadata=_object_dict(payload.get("user_metadata")),
        app_metadata=_object_dict(payload.get("app_metadata")),
        raw=dict(payload),
    )


def _object_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _compact_error_payload(raw: str) -> str:
    text = raw.strip()
    if not text:
        return "empty error response"
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text[:500]
    if isinstance(payload, dict):
        selected = {
            key: value
            for key, value in payload.items()
            if key in {"message", "msg", "error", "error_description", "code"}
        }
        return json.dumps(selected or payload, sort_keys=True)[:500]
    return json.dumps(payload, sort_keys=True)[:500]


def _redact_message(message: str, service_role_key: str, payload: dict[str, object] | None) -> str:
    redacted = message
    for secret in (service_role_key, str((payload or {}).get("password", "") or "")):
        if secret:
            redacted = redacted.replace(secret, "<redacted>")
    return re.sub(
        r"(?i)\b(authorization|apikey)\s*([:=])\s*\S+",
        lambda match: f"{match.group(1)}{match.group(2)}<redacted>",
        redacted,
    )
