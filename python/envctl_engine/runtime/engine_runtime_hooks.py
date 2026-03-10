from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Mapping

from envctl_engine.shared.dependency_compose_assets import materialize_dependency_compose, supabase_managed_env
from envctl_engine.shared.hooks import HookInvocationResult, legacy_shell_hook_issue, run_envctl_hook
from envctl_engine.state.models import RequirementsResult, ServiceRecord
from envctl_engine.shared.parsing import parse_bool, parse_int
from envctl_engine.requirements.supabase import build_supabase_project_name
from envctl_engine.requirements.core import dependency_definitions


def hook_bridge_enabled(runtime: Any) -> bool:
    raw = runtime.env.get("ENVCTL_ENABLE_HOOK_BRIDGE") or runtime.config.raw.get("ENVCTL_ENABLE_HOOK_BRIDGE")
    return parse_bool(raw, True)


def invoke_envctl_hook(runtime: Any, *, context: Any, hook_name: str) -> HookInvocationResult:
    if not hook_bridge_enabled(runtime):
        return HookInvocationResult(
            hook_name=hook_name,
            found=False,
            success=True,
            stdout="",
            stderr="",
            payload=None,
        )
    repo_root = getattr(runtime.config, "base_dir", context.root)
    default_mode = getattr(runtime.config, "default_mode", "main")
    result = run_envctl_hook(
        repo_root=context.root,
        hook_name=hook_name,
        env=runtime._command_env(port=0),
        hook_file=context.root / ".envctl_hooks.py",
        context={
            "repo_root": str(repo_root),
            "project_name": context.name,
            "project_root": str(context.root),
            "mode": default_mode,
            "run_id": None,
            "ports": {name: int(plan.final) for name, plan in context.ports.items()},
            "env": runtime._command_env(port=0),
        },
    )
    runtime._emit(
        "hook.bridge.invoke",
        project=context.name,
        hook=hook_name,
        found=result.found,
        success=result.success,
        has_payload=isinstance(result.payload, dict),
    )
    return result


def startup_hook_contract_issue(runtime: Any) -> str | None:
    return legacy_shell_hook_issue(getattr(runtime.config, "base_dir", Path.cwd()))


def requirements_result_from_hook_payload(
    runtime: Any,
    *,
    context: Any,
    mode: str,
    payload: Mapping[str, object],
) -> RequirementsResult:
    requirements_payload = payload.get("requirements")
    requirements = requirements_payload if isinstance(requirements_payload, Mapping) else {}

    def component(name: str, plan: Any) -> dict[str, object]:
        raw = requirements.get(name) if isinstance(requirements, Mapping) else None
        raw_map = raw if isinstance(raw, Mapping) else {}
        success = bool(raw_map.get("success", True))
        final = parse_int(str(raw_map.get("final", plan.final)), plan.final)
        retries = parse_int(str(raw_map.get("retries", 0)), 0)
        if final != plan.final:
            plan.final = final
            plan.assigned = final
        return {
            "requested": plan.requested,
            "final": final,
            "retries": retries,
            "success": success,
            "simulated": bool(raw_map.get("simulated", False)),
            "enabled": runtime._requirement_enabled(name, mode=mode),
        }

    components = {
        definition.id: component(definition.id, context.ports[definition.resources[0].legacy_port_key])
        for definition in dependency_definitions()
    }
    failures: list[str] = []
    for name, data in components.items():
        if bool(data.get("enabled")) and not bool(data.get("success")):
            failures.append(f"{name}:hook_failure")

    return RequirementsResult(
        project=context.name,
        components=components,
        health="healthy" if not failures else "degraded",
        failures=failures,
    )


def services_from_hook_payload(
    runtime: Any,
    *,
    context: Any,
    payload: Mapping[str, object],
) -> dict[str, ServiceRecord]:
    raw_services = payload.get("services")
    if not isinstance(raw_services, list):
        return {}
    records: dict[str, ServiceRecord] = {}
    for raw in raw_services:
        if not isinstance(raw, Mapping):
            continue
        name = str(raw.get("name", "")).strip()
        if not name:
            continue
        service_type = str(raw.get("type", "unknown")).strip() or "unknown"
        cwd = str(raw.get("cwd", context.root))
        pid = parse_int(str(raw.get("pid")), 0)
        requested_port = parse_int(str(raw.get("requested_port") or raw.get("port")), 0)
        actual_port = parse_int(str(raw.get("actual_port") or requested_port), 0)
        status = str(raw.get("status", "running"))
        log_path = raw.get("log_path")
        record = ServiceRecord(
            name=name,
            type=service_type,
            cwd=cwd,
            pid=(pid if pid > 0 else None),
            requested_port=(requested_port if requested_port > 0 else None),
            actual_port=(actual_port if actual_port > 0 else None),
            log_path=(str(log_path) if log_path else None),
            status=status,
        )
        records[name] = record
        if service_type == "backend" and actual_port > 0:
            context.ports["backend"].final = actual_port
            context.ports["backend"].assigned = actual_port
        if service_type == "frontend" and actual_port > 0:
            context.ports["frontend"].final = actual_port
            context.ports["frontend"].assigned = actual_port
    return records


def supabase_fingerprint_path(runtime: Any, project_name: str) -> Path:
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", project_name).strip("_") or "project"
    return runtime.runtime_root / "supabase_fingerprints" / f"{safe_name}.json"


def supabase_auto_reinit_enabled(runtime: Any) -> bool:
    raw = runtime.env.get("ENVCTL_SUPABASE_AUTO_REINIT") or runtime.config.raw.get("ENVCTL_SUPABASE_AUTO_REINIT")
    return parse_bool(raw, False)


def supabase_reinit_required_message() -> str:
    return (
        "supabase reliability contract changed; run reinit workflow: "
        "docker compose ... down -v; docker compose ... up -d supabase-db; "
        "wait healthy; docker compose ... up -d supabase-auth supabase-kong"
    )


def run_supabase_reinit(runtime: Any, *, project_root: Path, project_name: str, db_port: int) -> str | None:
    try:
        materialized = materialize_dependency_compose(
            runtime_root=runtime.runtime_root,
            dependency_name="supabase",
            project_name=project_name,
            compose_project_name=build_supabase_project_name(
                project_root=project_root,
                project_name=project_name,
            ),
            env_values=supabase_managed_env(
                db_port=db_port,
                env=runtime._command_env(port=0),
            ),
        )
    except FileNotFoundError as exc:
        return f"supabase reinit unavailable: {exc}"
    base_cmd = [
        "docker",
        "compose",
        "-p",
        materialized.compose_project_name,
        "-f",
        str(materialized.compose_file),
    ]
    steps = (
        ["down", "-v"],
        ["up", "-d", "supabase-db"],
    )
    for step in steps:
        result = runtime.process_runner.run(
            base_cmd + list(step),
            cwd=materialized.stack_root,
            env=runtime._command_env(port=0),
            timeout=120.0,
        )
        if result.returncode != 0:
            error = (result.stderr or result.stdout or f"exit:{result.returncode}").strip()
            return f"supabase reinit step failed ({' '.join(step)}): {error}"
    if db_port > 0 and not runtime._wait_for_requirement_listener(db_port):
        return f"supabase reinit failed: db listener not healthy on port {db_port}"
    result = runtime.process_runner.run(
        base_cmd + ["up", "-d", "supabase-auth", "supabase-kong"],
        cwd=materialized.stack_root,
        env=runtime._command_env(port=0),
        timeout=120.0,
    )
    if result.returncode != 0:
        error = (result.stderr or result.stdout or f"exit:{result.returncode}").strip()
        return f"supabase reinit step failed (up -d supabase-auth supabase-kong): {error}"
    return None
