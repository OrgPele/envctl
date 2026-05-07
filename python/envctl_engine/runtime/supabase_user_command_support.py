from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from envctl_engine.requirements.supabase_auth_users import (
    SupabaseAuthAdminClient,
    SupabaseAuthAdminError,
    sync_supabase_auth_users,
)


def run_supabase_user_command(runtime: Any, route: object) -> int:
    args = [str(value).strip() for value in getattr(route, "passthrough_args", []) if str(value).strip()]
    command = args[0].lower() if args else "sync"
    flags = getattr(route, "flags", {}) if isinstance(getattr(route, "flags", {}), dict) else {}
    mode = str(flags.get("mode_override") or getattr(route, "mode", "main") or "main").strip().lower()
    json_output = bool(flags.get("json"))
    try:
        base_url, service_role_key = _resolve_supabase_admin_connection(runtime, mode=mode)
        client = SupabaseAuthAdminClient(base_url=base_url, service_role_key=service_role_key)
        if command == "sync":
            summary = sync_supabase_auth_users(
                mode=mode,
                configured_users=tuple(getattr(runtime.config, "supabase_auth_users", ()) or ()),
                base_url=base_url,
                service_role_key=service_role_key,
                runtime_root=Path(getattr(runtime, "runtime_root", getattr(runtime.config, "runtime_scope_dir", "."))),
                dry_run=bool(flags.get("dry_run")),
                client=client,
            )
            payload = {
                "command": "sync",
                "status": "ok" if summary.success else "error",
                "results": [asdict(result) for result in summary.results],
            }
            return _emit_result(payload, json_output=json_output, ok=summary.success)
        if command == "list":
            users = client.list_users()
            payload = {
                "command": "list",
                "status": "ok",
                "users": [
                    {
                        "id": user.id,
                        "email": user.email,
                        "created_at": user.created_at,
                        "updated_at": user.updated_at,
                        "confirmed_at": user.confirmed_at,
                    }
                    for user in users
                ],
            }
            return _emit_result(payload, json_output=json_output, ok=True)
        if command == "create":
            email = _arg_or_flag(args, flags, index=1, flag="email")
            password = str(flags.get("password", "") or "").strip()
            if not email or not password:
                raise SupabaseAuthAdminError("create requires email and --password")
            existing = client.find_user_by_email(email)
            if existing is not None:
                payload = {"command": "create", "status": "exists", "id": existing.id, "email": existing.email}
                return _emit_result(payload, json_output=json_output, ok=True)
            record = client.create_user(
                email=email,
                password=password,
                email_confirm=bool(flags.get("confirm", True)),
                user_metadata=_json_flag_object(flags.get("metadata_json"), "--metadata-json"),
                app_metadata=_json_flag_object(flags.get("app_metadata_json"), "--app-metadata-json"),
            )
            payload = {"command": "create", "status": "created", "id": record.id, "email": record.email}
            return _emit_result(payload, json_output=json_output, ok=True)
        if command == "update":
            target = _arg_or_flag(args, flags, index=1, flag="email")
            if not target:
                raise SupabaseAuthAdminError("update requires email or user id")
            record = _resolve_user(client, target)
            if record is None:
                raise SupabaseAuthAdminError(f"Supabase Auth user not found: {target}")
            updated = client.update_user(
                record.id,
                password=str(flags.get("password", "") or "") or None,
                email_confirm=True if bool(flags.get("confirm")) else None,
                user_metadata=_json_flag_object(flags.get("metadata_json"), "--metadata-json")
                if flags.get("metadata_json") is not None
                else None,
                app_metadata=_json_flag_object(flags.get("app_metadata_json"), "--app-metadata-json")
                if flags.get("app_metadata_json") is not None
                else None,
            )
            payload = {"command": "update", "status": "updated", "id": updated.id, "email": updated.email}
            return _emit_result(payload, json_output=json_output, ok=True)
        if command == "delete":
            if not (bool(flags.get("yes")) or bool(flags.get("batch")) or json_output):
                raise SupabaseAuthAdminError("delete requires --yes or --headless")
            target = _arg_or_flag(args, flags, index=1, flag="email")
            if not target:
                raise SupabaseAuthAdminError("delete requires email or user id")
            record = _resolve_user(client, target)
            if record is None:
                payload = {"command": "delete", "status": "missing", "target": target}
                return _emit_result(payload, json_output=json_output, ok=True)
            if not bool(flags.get("dry_run")):
                client.delete_user(record.id)
            payload = {"command": "delete", "status": "deleted", "id": record.id, "email": record.email}
            return _emit_result(payload, json_output=json_output, ok=True)
        if command == "show":
            target = _arg_or_flag(args, flags, index=1, flag="email")
            if not target:
                raise SupabaseAuthAdminError("show requires email or user id")
            record = _resolve_user(client, target)
            if record is None:
                raise SupabaseAuthAdminError(f"Supabase Auth user not found: {target}")
            payload = {"command": "show", "status": "ok", "user": {"id": record.id, "email": record.email}}
            return _emit_result(payload, json_output=json_output, ok=True)
        raise SupabaseAuthAdminError(f"unsupported supabase-user command: {command}")
    except SupabaseAuthAdminError as exc:
        payload = {"command": command, "status": "error", "error": str(exc)}
        return _emit_result(payload, json_output=json_output, ok=False)


def _resolve_supabase_admin_connection(runtime: Any, *, mode: str | None = None) -> tuple[str, str]:
    env = _runtime_env(runtime)
    config_raw = _runtime_config_raw(runtime)
    base_url = str(env.get("SUPABASE_URL") or config_raw.get("SUPABASE_URL") or "").strip()
    service_role_key = str(
        env.get("SUPABASE_SERVICE_ROLE_KEY") or config_raw.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    ).strip()
    managed = _resolve_managed_supabase_connection(runtime, mode=mode)
    if managed is not None:
        base_url = base_url or managed[0]
        service_role_key = service_role_key or managed[1]
    if base_url and service_role_key:
        return base_url, service_role_key
    message = (
        "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required. "
        "Start managed Supabase with `envctl --entire-system --headless` or provide both env vars."
    )
    raise SupabaseAuthAdminError(message)


def _runtime_env(runtime: Any) -> dict[str, str]:
    raw = getattr(runtime, "env", {})
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


def _runtime_config_raw(runtime: Any) -> dict[str, str]:
    raw = getattr(getattr(runtime, "config", None), "raw", {}) or {}
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


def _resolve_managed_supabase_connection(runtime: Any, *, mode: str | None) -> tuple[str, str] | None:
    state = _try_load_state(runtime, mode=mode)
    if state is None:
        return None
    requirements_by_project = getattr(state, "requirements", {})
    if not isinstance(requirements_by_project, dict):
        return None
    project_names = list(requirements_by_project)
    preferred_names = ["Main", *project_names]
    seen: set[str] = set()
    for project_name in preferred_names:
        if project_name in seen:
            continue
        seen.add(project_name)
        requirements = requirements_by_project.get(project_name)
        connection = _connection_from_requirements(runtime, requirements)
        if connection is not None:
            return connection
    return None


def _try_load_state(runtime: Any, *, mode: str | None) -> object | None:
    loader = getattr(runtime, "_try_load_existing_state", None)
    if not callable(loader):
        return None
    normalized_mode = str(mode or "main").strip().lower() or "main"
    for kwargs in (
        {"mode": normalized_mode, "strict_mode_match": True},
        {"mode": normalized_mode},
        {},
    ):
        try:
            return loader(**kwargs)
        except TypeError:
            continue
    return None


def _connection_from_requirements(runtime: Any, requirements: object) -> tuple[str, str] | None:
    component_getter = getattr(requirements, "component", None)
    if not callable(component_getter):
        return None
    component = component_getter("supabase")
    if not isinstance(component, dict):
        return None
    if not bool(component.get("enabled")) or not bool(component.get("success")):
        return None
    raw_resources = component.get("resources")
    resources: dict[object, object] = raw_resources if isinstance(raw_resources, dict) else {}
    db_port = (
        _positive_int(resources.get("db"))
        or _positive_int(resources.get("primary"))
        or _positive_int(component.get("final"))
    )
    api_port = _positive_int(resources.get("api")) or _positive_int(component.get("final")) or db_port
    if api_port is None:
        return None
    context = SimpleNamespace(
        name=str(getattr(requirements, "project", "Main") or "Main"),
        ports={
            "db": SimpleNamespace(final=db_port or api_port),
            "supabase_api": SimpleNamespace(final=api_port),
        },
    )
    from envctl_engine.requirements.dependencies.supabase import project_env as supabase_project_env

    projected = supabase_project_env(
        runtime=_projection_runtime(runtime),
        context=context,
        requirements=requirements,
        route=None,
    )
    base_url = str(projected.get("SUPABASE_URL", "") or "").strip()
    service_role_key = str(projected.get("SUPABASE_SERVICE_ROLE_KEY", "") or "").strip()
    if base_url and service_role_key:
        return base_url, service_role_key
    return None


def _projection_runtime(runtime: Any) -> object:
    env = _runtime_env(runtime)
    config_raw = _runtime_config_raw(runtime)
    original_override = getattr(runtime, "_command_override_value", None)

    def command_override_value(key: str) -> str | None:
        if callable(original_override):
            value = original_override(key)
            if value is not None and str(value).strip():
                return str(value)
        return env.get(key) or config_raw.get(key)

    return SimpleNamespace(
        env=env,
        config=getattr(runtime, "config", None),
        _command_override_value=command_override_value,
    )


def _positive_int(value: object) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    return None


def _emit_result(payload: Mapping[str, object], *, json_output: bool, ok: bool) -> int:
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif ok:
        print(str(payload.get("status", "ok")))
    else:
        print(str(payload.get("error", "supabase-user failed")), file=sys.stderr)
    return 0 if ok else 1


def _arg_or_flag(args: list[str], flags: dict[str, object], *, index: int, flag: str) -> str:
    if len(args) > index and args[index]:
        return args[index]
    return str(flags.get(flag, "") or "").strip()


def _json_flag_object(raw: object, label: str) -> dict[str, object]:
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SupabaseAuthAdminError(f"{label} must be a JSON object: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise SupabaseAuthAdminError(f"{label} must be a JSON object")
    return dict(payload)


def _resolve_user(client: SupabaseAuthAdminClient, target: str):  # noqa: ANN201
    text = str(target).strip()
    if "@" in text:
        return client.find_user_by_email(text)
    users = client.list_users()
    for user in users:
        if user.id == text or user.email == text:
            return user
    return None
