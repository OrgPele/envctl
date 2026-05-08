from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
from typing import Any, Mapping

from envctl_engine.requirements.supabase_auth_users import SupabaseAuthAdminClient, SupabaseAuthAdminError
from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.supabase_user_command_support import _connection_from_requirements
from envctl_engine.state.project_runtime import (
    active_project_names,
    dependency_mode_summary,
    project_resolution_event_payload,
    project_root_for_state,
    resolve_requested_project_state,
)

_REDACTED = "<redacted>"
_SNIPPET_LIMIT = 4096


def run_qa_user_command(runtime: Any, route: Route) -> int:
    flags = getattr(route, "flags", {}) if isinstance(getattr(route, "flags", {}), dict) else {}
    json_output = bool(flags.get("json"))
    args = [str(arg).strip() for arg in getattr(route, "passthrough_args", []) if str(arg).strip()]
    subcommand = args[0].lower() if args else "ensure"
    if subcommand != "ensure":
        return _emit(
            {"ok": False, "error": f"unsupported qa-user command: {subcommand}"},
            json_output=json_output,
            ok=False,
        )
    state = _load_state(runtime, route)
    if state is None:
        return _emit({"ok": False, "error": "state_not_found"}, json_output=json_output, ok=False)
    requested_projects = list(getattr(route, "projects", []) or [])
    active_projects = active_project_names(state, runtime=runtime)
    if not requested_projects and len(active_projects) != 1:
        return _emit(
            {"ok": False, "error": "project_required", "active_projects": active_projects},
            json_output=json_output,
            ok=False,
        )
    resolution = resolve_requested_project_state(
        state,
        requested_projects,
        command="qa-user",
        runtime=runtime,
        allow_multi=False,
    )
    if not resolution.ok:
        _emit_resolution(runtime, "state.project_resolution.failed", resolution, state)
        return _emit(resolution.payload(), json_output=json_output, ok=False)
    _emit_resolution(runtime, "state.project_resolution.ok", resolution, state)
    project = resolution.selected_projects[0] if resolution.selected_projects else ""
    email = str(flags.get("email") or (args[1] if len(args) > 1 else "") or "").strip()
    password = str(flags.get("password") or "").strip()
    if not email or not password:
        return _emit(
            {"ok": False, "error": "qa-user ensure requires --email and --password"},
            json_output=json_output,
            ok=False,
        )
    selected_state = resolution.state or state
    user_metadata = _json_flag_object(flags.get("metadata_json"), "--metadata-json")
    if flags.get("locale") and "locale" not in user_metadata:
        user_metadata["locale"] = str(flags.get("locale") or "").strip()
    app_metadata = _json_flag_object(flags.get("app_metadata_json"), "--app-metadata-json")
    update_password = bool(flags.get("update_password"))
    update_metadata = bool(flags.get("update_metadata"))
    try:
        base_url, service_role_key = _resolve_project_supabase_connection(runtime, selected_state, project)
        client = SupabaseAuthAdminClient(base_url=base_url, service_role_key=service_role_key)
        existing = client.find_user_by_email(email)
        created = False
        reused = False
        updated = False
        updated_fields: list[str] = []
        if existing is None:
            record = client.create_user(
                email=email,
                password=password,
                email_confirm=True,
                user_metadata=user_metadata,
                app_metadata=app_metadata,
            )
            created = True
        else:
            record = existing
            reused = True
            update_kwargs: dict[str, object] = {}
            if update_password:
                update_kwargs["password"] = password
                updated_fields.append("password")
            if update_metadata:
                update_kwargs["user_metadata"] = user_metadata
                update_kwargs["app_metadata"] = app_metadata
                updated_fields.extend(["user_metadata", "app_metadata"])
            if update_kwargs:
                record = client.update_user(str(getattr(existing, "id", "") or ""), **update_kwargs)
                updated = True
        seeds = _seed_values(flags.get("seed"))
        dependency_env = _dependency_env(
            runtime,
            selected_state,
            project,
            base_url=base_url,
            service_role_key=service_role_key,
        )
        seed_results = _run_seed_hooks(
            runtime,
            state=selected_state,
            project=project,
            user_id=str(getattr(record, "id", "") or ""),
            email=email,
            locale=str(flags.get("locale") or "").strip(),
            seeds=seeds,
            dependency_env=dependency_env,
            secrets=[password, service_role_key],
        )
        seed_failed = any(str(result.get("status")) == "failed" for result in seed_results)
        dependency_summary = dependency_mode_summary(selected_state)
        project_resolution = _project_resolution_payload(resolution)
        artifact_path = _write_artifact(
            runtime,
            state=state,
            project=project,
            dependency_summary=dependency_summary,
            user_id=str(getattr(record, "id", "") or ""),
            email=str(getattr(record, "email", email) or email),
            created=created,
            reused=reused,
            updated=updated,
            updated_fields=updated_fields,
            seeds=seeds,
            seed_results=seed_results,
        )
        payload = {
            "ok": not seed_failed,
            "command": "ensure",
            "project": project,
            "run_id": state.run_id,
            "dependency_mode": dependency_summary["dependency_mode"],
            "shared_dependencies": dependency_summary["shared_dependencies"],
            "project_resolution": project_resolution,
            "artifact_path": str(artifact_path),
            "user": {
                "id": str(getattr(record, "id", "") or ""),
                "email": str(getattr(record, "email", email) or email),
            },
            "credentials": {"email": email, "password": password},
            "created": created,
            "reused": reused,
            "updated": updated,
            "updated_fields": updated_fields,
            "seed_results": seed_results,
        }
        _emit_qa_event(
            runtime,
            project=project,
            run_id=state.run_id,
            ok=not seed_failed,
            user_id=str(getattr(record, "id", "") or ""),
            email=email,
            created=created,
            reused=reused,
            updated=updated,
            seeds=seeds,
            seed_results=seed_results,
        )
        return _emit(payload, json_output=json_output, ok=not seed_failed)
    except (SupabaseAuthAdminError, ValueError) as exc:
        return _emit({"ok": False, "error": str(exc)}, json_output=json_output, ok=False)


def _resolve_project_supabase_connection(runtime: Any, state: Any, project: str) -> tuple[str, str]:
    requirements = getattr(state, "requirements", {}).get(project)
    if requirements is None and len(getattr(state, "requirements", {})) == 1:
        requirements = next(iter(getattr(state, "requirements", {}).values()))
    component_env = _supabase_component_env(requirements)
    base_url = str(component_env.get("SUPABASE_URL") or "").strip()
    service_role_key = str(component_env.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if base_url and service_role_key:
        return base_url, service_role_key
    connection = _connection_from_requirements(runtime, requirements)
    if connection is not None:
        return connection
    env = getattr(runtime, "env", {}) if isinstance(getattr(runtime, "env", {}), dict) else {}
    raw = getattr(getattr(runtime, "config", None), "raw", {}) or {}
    base_url = str(env.get("SUPABASE_URL") or raw.get("SUPABASE_URL") or "").strip()
    service_role_key = str(env.get("SUPABASE_SERVICE_ROLE_KEY") or raw.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if base_url and service_role_key:
        return base_url, service_role_key
    raise SupabaseAuthAdminError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for qa-user ensure")


def _run_seed_hooks(
    runtime: Any,
    *,
    state: Any,
    project: str,
    user_id: str,
    email: str,
    locale: str,
    seeds: list[str],
    dependency_env: Mapping[str, str],
    secrets: list[str],
) -> list[dict[str, object]]:
    raw = getattr(getattr(runtime, "config", None), "raw", {}) or {}
    runtime_env = dict(getattr(runtime, "env", {}) or {})
    results: list[dict[str, object]] = []
    cwd = Path(str(project_root_for_state(state, project) or runtime_env.get("ENVCTL_INVOCATION_CWD") or os.getcwd()))
    for seed in seeds:
        key = f"ENVCTL_QA_USER_SEED_{seed.upper().replace('-', '_')}_CMD"
        command = str(
            runtime_env.get(key)
            or raw.get(key)
            or runtime_env.get("ENVCTL_QA_USER_SEED_CMD")
            or raw.get("ENVCTL_QA_USER_SEED_CMD")
            or ""
        ).strip()
        if not command:
            results.append({"seed": seed, "status": "skipped", "reason": "no_seed_hook_configured", "cwd": str(cwd)})
            continue
        hook_env = dict(os.environ)
        hook_env.update({str(key): str(value) for key, value in runtime_env.items()})
        hook_env.update({str(key): str(value) for key, value in dependency_env.items()})
        hook_env.update(
            {
                "ENVCTL_PROJECT_NAME": project,
                "ENVCTL_QA_USER_ID": user_id,
                "ENVCTL_QA_USER_EMAIL": email,
                "ENVCTL_QA_USER_LOCALE": locale,
                "ENVCTL_QA_USER_SEEDS": ",".join(seeds),
            }
        )
        completed = subprocess.run(
            shlex.split(command),
            cwd=str(cwd),
            env=hook_env,
            text=True,
            capture_output=True,
            check=False,
        )
        status = "ok" if completed.returncode == 0 else "failed"
        results.append(
            {
                "seed": seed,
                "status": status,
                "exit_code": completed.returncode,
                "cwd": str(cwd),
                "stdout": _redact_text(completed.stdout, secrets),
                "stderr": _redact_text(completed.stderr, secrets),
            }
        )
    return results


def _dependency_env(
    runtime: Any,
    state: Any,
    project: str,
    *,
    base_url: str,
    service_role_key: str,
) -> dict[str, str]:
    requirements = getattr(state, "requirements", {}).get(project)
    if requirements is None and len(getattr(state, "requirements", {})) == 1:
        requirements = next(iter(getattr(state, "requirements", {}).values()))
    env = _supabase_component_env(requirements)
    env.setdefault("SUPABASE_URL", base_url)
    env.setdefault("SUPABASE_SERVICE_ROLE_KEY", service_role_key)
    return {key: value for key, value in env.items() if value}


def _supabase_component_env(requirements: object | None) -> dict[str, str]:
    component_getter = getattr(requirements, "component", None)
    if not callable(component_getter):
        return {}
    component = component_getter("supabase")
    if not isinstance(component, dict):
        return {}
    raw_env = component.get("env") if isinstance(component.get("env"), dict) else {}
    return {str(key): str(value) for key, value in raw_env.items() if str(value).strip()}


def _seed_values(raw: object) -> list[str]:
    if isinstance(raw, list):
        values = raw
    elif raw is None:
        values = []
    else:
        values = [raw]
    result: list[str] = []
    for value in values:
        for part in str(value).split(","):
            normalized = part.strip()
            if normalized and normalized not in result:
                result.append(normalized)
    return result


def _load_state(runtime: Any, route: Route):  # noqa: ANN201
    loader = getattr(runtime, "_try_load_existing_state", None)
    if not callable(loader):
        return None
    strict = False
    strict_resolver = getattr(runtime, "_state_lookup_strict_mode_match", None)
    if callable(strict_resolver):
        strict = bool(strict_resolver(route))
    return loader(mode=getattr(route, "mode", None), strict_mode_match=strict)


def _json_flag_object(raw: object, flag_name: str) -> dict[str, object]:
    if raw is None or raw == "":
        return {}
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{flag_name} must be valid JSON object: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{flag_name} must be a JSON object")
    return dict(parsed)


def _project_resolution_payload(resolution: Any) -> dict[str, object]:
    return {
        "requested_projects": list(getattr(resolution, "requested_projects", []) or []),
        "selected_projects": list(getattr(resolution, "selected_projects", []) or []),
        "active_projects": list(getattr(resolution, "active_projects", []) or []),
    }


def _write_artifact(
    runtime: Any,
    *,
    state: Any,
    project: str,
    dependency_summary: Mapping[str, object],
    user_id: str,
    email: str,
    created: bool,
    reused: bool,
    updated: bool,
    updated_fields: list[str],
    seeds: list[str],
    seed_results: list[dict[str, object]],
) -> Path:
    path = _artifact_path(runtime, str(getattr(state, "run_id", "") or "unknown"))
    path.parent.mkdir(parents=True, exist_ok=True)
    artifact = {
        "project": project,
        "run_id": getattr(state, "run_id", ""),
        "mode": getattr(state, "mode", ""),
        "dependency_mode": dependency_summary.get("dependency_mode"),
        "shared_dependencies": dependency_summary.get("shared_dependencies"),
        "user": {"id": user_id, "email": email},
        "credentials": {"email": email, "password": _REDACTED},
        "created": created,
        "reused": reused,
        "updated": updated,
        "updated_fields": list(updated_fields),
        "selected_seeds": list(seeds),
        "seed_results": seed_results,
        "generated_at": datetime.now(tz=UTC).isoformat(),
    }
    path.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _artifact_path(runtime: Any, run_id: str) -> Path:
    repository = getattr(runtime, "state_repository", None)
    run_dir = getattr(repository, "run_dir_path", None)
    if callable(run_dir):
        return Path(run_dir(run_id)) / "qa-user-ensure.json"
    return Path(getattr(runtime, "runtime_root", ".")) / "runs" / run_id / "qa-user-ensure.json"


def _emit_resolution(runtime: Any, event: str, resolution: Any, state: Any) -> None:
    emitter = getattr(runtime, "_emit", None)
    if not callable(emitter):
        return
    emitter(event, **project_resolution_event_payload(resolution, state, runtime=runtime))


def _emit_qa_event(
    runtime: Any,
    *,
    project: str,
    run_id: str,
    ok: bool,
    user_id: str,
    email: str,
    created: bool,
    reused: bool,
    updated: bool,
    seeds: list[str],
    seed_results: list[dict[str, object]],
) -> None:
    emitter = getattr(runtime, "_emit", None)
    if not callable(emitter):
        return
    emitter(
        "qa_user.ensure",
        project=project,
        run_id=run_id,
        status="ok" if ok else "failed",
        user_id=user_id,
        email_hash=hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest(),
        created=created,
        reused=reused,
        updated=updated,
        seed_names=list(seeds),
        seed_results=seed_results,
    )


def _redact_text(value: object, secrets: list[str]) -> str:
    text = str(value or "")[-_SNIPPET_LIMIT:]
    for secret in secrets:
        if secret:
            text = text.replace(secret, _REDACTED)
    return text


def _emit(payload: dict[str, object], *, json_output: bool, ok: bool) -> int:
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif ok:
        print(str(payload.get("status") or "ok"))
    else:
        print(str(payload.get("error") or "qa-user failed"))
    return 0 if ok else 1
