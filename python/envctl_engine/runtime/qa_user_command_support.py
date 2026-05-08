from __future__ import annotations

import json
import os
import shlex
import subprocess
from typing import Any

from envctl_engine.requirements.supabase_auth_users import SupabaseAuthAdminClient, SupabaseAuthAdminError
from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.supabase_user_command_support import _connection_from_requirements
from envctl_engine.state.project_runtime import active_project_names, dependency_mode_summary, resolve_requested_project_state


def run_qa_user_command(runtime: Any, route: Route) -> int:
    flags = getattr(route, "flags", {}) if isinstance(getattr(route, "flags", {}), dict) else {}
    json_output = bool(flags.get("json"))
    args = [str(arg).strip() for arg in getattr(route, "passthrough_args", []) if str(arg).strip()]
    subcommand = args[0].lower() if args else "ensure"
    if subcommand != "ensure":
        return _emit({"ok": False, "error": f"unsupported qa-user command: {subcommand}"}, json_output=json_output, ok=False)
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
        return _emit(resolution.payload(), json_output=json_output, ok=False)
    project = resolution.selected_projects[0] if resolution.selected_projects else ""
    email = str(flags.get("email") or (args[1] if len(args) > 1 else "") or "").strip()
    password = str(flags.get("password") or "").strip()
    if not email or not password:
        return _emit({"ok": False, "error": "qa-user ensure requires --email and --password"}, json_output=json_output, ok=False)
    try:
        base_url, service_role_key = _resolve_project_supabase_connection(runtime, resolution.state or state, project)
        client = SupabaseAuthAdminClient(base_url=base_url, service_role_key=service_role_key)
        existing = client.find_user_by_email(email)
        if existing is None:
            record = client.create_user(
                email=email,
                password=password,
                email_confirm=True,
                user_metadata={"locale": str(flags.get("locale") or "").strip()} if flags.get("locale") else {},
                app_metadata={},
            )
            created = True
            reused = False
        else:
            record = existing
            created = False
            reused = True
        seed_results = _run_seed_hooks(
            runtime,
            project=project,
            user_id=str(getattr(record, "id", "") or ""),
            email=email,
            locale=str(flags.get("locale") or "").strip(),
            seeds=_seed_values(flags.get("seed")),
        )
        dependency_summary = dependency_mode_summary(resolution.state or state)
        payload = {
            "ok": True,
            "command": "ensure",
            "project": project,
            "run_id": state.run_id,
            "dependency_mode": dependency_summary["dependency_mode"],
            "shared_dependencies": dependency_summary["shared_dependencies"],
            "user": {"id": str(getattr(record, "id", "") or ""), "email": str(getattr(record, "email", email) or email)},
            "credentials": {"email": email, "password": password},
            "created": created,
            "reused": reused,
            "updated": False,
            "seed_results": seed_results,
        }
        return _emit(payload, json_output=json_output, ok=True)
    except SupabaseAuthAdminError as exc:
        return _emit({"ok": False, "error": str(exc)}, json_output=json_output, ok=False)


def _resolve_project_supabase_connection(runtime: Any, state: Any, project: str) -> tuple[str, str]:
    requirements = getattr(state, "requirements", {}).get(project)
    if requirements is None and len(getattr(state, "requirements", {})) == 1:
        requirements = next(iter(getattr(state, "requirements", {}).values()))
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
    project: str,
    user_id: str,
    email: str,
    locale: str,
    seeds: list[str],
) -> list[dict[str, object]]:
    raw = getattr(getattr(runtime, "config", None), "raw", {}) or {}
    env = dict(getattr(runtime, "env", {}) or {})
    results: list[dict[str, object]] = []
    for seed in seeds:
        key = f"ENVCTL_QA_USER_SEED_{seed.upper().replace('-', '_')}_CMD"
        command = str(env.get(key) or raw.get(key) or env.get("ENVCTL_QA_USER_SEED_CMD") or raw.get("ENVCTL_QA_USER_SEED_CMD") or "").strip()
        if not command:
            results.append({"seed": seed, "status": "skipped", "reason": "no_seed_hook_configured"})
            continue
        hook_env = dict(os.environ)
        hook_env.update(env)
        hook_env.update(
            {
                "ENVCTL_PROJECT_NAME": project,
                "ENVCTL_QA_USER_ID": user_id,
                "ENVCTL_QA_USER_EMAIL": email,
                "ENVCTL_QA_USER_LOCALE": locale,
                "ENVCTL_QA_USER_SEEDS": ",".join(seeds),
            }
        )
        completed = subprocess.run(shlex.split(command), env=hook_env, text=True, capture_output=True, check=False)
        results.append({"seed": seed, "status": "ok" if completed.returncode == 0 else "failed", "code": completed.returncode})
    return results


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


def _emit(payload: dict[str, object], *, json_output: bool, ok: bool) -> int:
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif ok:
        print(str(payload.get("status") or "ok"))
    else:
        print(str(payload.get("error") or "qa-user failed"))
    return 0 if ok else 1
