from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Mapping

from envctl_engine.runtime.command_router import Route
from envctl_engine.shared.node_tooling import detect_package_manager, load_package_json
from envctl_engine.shared.parsing import parse_bool
from envctl_engine.startup.protocols import ProjectContextLike
from envctl_engine.startup.public_urls import browser_backend_url, resolve_public_host
from envctl_engine.startup.service_runtime_state_support import (
    _frontend_runtime_prep_required,
    _write_frontend_runtime_prep_state,
)

def _prepare_frontend_runtime(
    self: Any,
    *,
    context: ProjectContextLike,
    frontend_cwd: Path,
    frontend_log_path: str,
    project_env_base: Mapping[str, str],
    frontend_env_file: Path | None,
    backend_port: int,
    route: Route | None = None,
) -> None:
    _ = route
    prepare_started = time.monotonic()
    backend_url = ""
    api_url = ""
    if backend_port > 0:
        backend_url = browser_backend_url(host=resolve_public_host(env=self.env, config=self.config), port=backend_port)
        api_url = f"{backend_url}/api/v1"

    package_json = frontend_cwd / "package.json"
    if not package_json.is_file():
        return

    payload = load_package_json(package_json)
    if payload is None:
        return
    scripts = payload.get("scripts")
    if not isinstance(scripts, dict):
        return
    dev_script = scripts.get("dev")
    if not isinstance(dev_script, str) or not dev_script.strip():
        return

    manager = detect_package_manager(frontend_cwd, command_exists=self._command_exists)
    if manager is None:
        return
    missing_dependency = _frontend_missing_direct_dependency(frontend_cwd=frontend_cwd, payload=payload)
    if missing_dependency is not None and not parse_bool(
        self.env.get("ENVCTL_SKIP_FRONTEND_DEPENDENCY_CHECK"),
        False,
    ):
        install_command, _fallback_command = _frontend_install_commands(frontend_cwd=frontend_cwd, manager=manager)
        command_text = " ".join(install_command)
        self._emit(
            "service.bootstrap.dependency_check",
            project=context.name,
            service="frontend",
            status="failed",
            package=missing_dependency,
            install_command=command_text,
        )
        raise RuntimeError(
            "frontend dependency check failed for "
            f"{context.name}: missing direct dependency {missing_dependency!r} in {frontend_cwd}. "
            f"Run `{command_text}` in {frontend_cwd}."
        )
    env = self._command_env(port=0, extra=project_env_base)
    if frontend_env_file is not None and frontend_env_file.is_file():
        loaded_env = self._read_env_file_safe(frontend_env_file)
        for key, value in loaded_env.items():
            env[key] = value
        env["APP_ENV_FILE"] = str(frontend_env_file)
    if backend_url:
        env["VITE_BACKEND_URL"] = backend_url
    if api_url:
        env["VITE_API_URL"] = api_url
    runtime_required, runtime_reason, runtime_state = _frontend_runtime_prep_required(
        frontend_cwd=frontend_cwd,
        manager=manager,
        env=env,
        dev_script=dev_script,
    )
    if not runtime_required:
        self._emit(
            "service.bootstrap.skip",
            project=context.name,
            service="frontend",
            manager=manager,
            step="prepare",
            reason=runtime_reason,
        )
        _emit_bootstrap_phase(
            self,
            project=context.name,
            service="frontend",
            phase="prepare",
            started=prepare_started,
            status="reused",
            reason=runtime_reason,
        )
        return
    install_check_started = time.monotonic()
    install_required, install_reason = _frontend_dependency_install_required(
        frontend_cwd=frontend_cwd,
        dev_script=dev_script,
    )
    _emit_bootstrap_phase(
        self,
        project=context.name,
        service="frontend",
        phase="dependency_install_check",
        started=install_check_started,
        reason=install_reason,
    )
    if not install_required:
        _write_frontend_runtime_prep_state(frontend_cwd=frontend_cwd, state=runtime_state)
        _emit_bootstrap_phase(
            self,
            project=context.name,
            service="frontend",
            phase="dependency_install",
            started=time.monotonic(),
            status="reused",
            reason=install_reason,
        )
        _emit_bootstrap_phase(
            self,
            project=context.name,
            service="frontend",
            phase="prepare",
            started=prepare_started,
        )
        return

    install_command, fallback_command = _frontend_install_commands(
        frontend_cwd=frontend_cwd,
        manager=manager,
    )
    install_started = time.monotonic()
    self._emit(
        "service.bootstrap",
        project=context.name,
        service="frontend",
        manager=manager,
        step="install",
        reason=install_reason,
    )
    try:
        self._run_frontend_bootstrap_command(
            context=context,
            command=install_command,
            cwd=frontend_cwd,
            frontend_log_path=frontend_log_path,
            env=env,
            step=f"{manager} install",
        )
    except RuntimeError:
        if not fallback_command:
            raise
        self._emit(
            "service.bootstrap.retry",
            project=context.name,
            service="frontend",
            step="install",
            reason="install_fallback",
        )
        self._run_frontend_bootstrap_command(
            context=context,
            command=fallback_command,
            cwd=frontend_cwd,
            frontend_log_path=frontend_log_path,
            env=env,
            step=f"{manager} install (fallback)",
        )
    _write_frontend_runtime_prep_state(frontend_cwd=frontend_cwd, state=runtime_state)
    _emit_bootstrap_phase(
        self,
        project=context.name,
        service="frontend",
        phase="dependency_install",
        started=install_started,
        reason=install_reason,
    )
    _emit_bootstrap_phase(
        self,
        project=context.name,
        service="frontend",
        phase="prepare",
        started=prepare_started,
    )


def _run_frontend_bootstrap_command(
    self: Any,
    *,
    context: ProjectContextLike,
    command: list[str],
    cwd: Path,
    frontend_log_path: str,
    env: Mapping[str, str],
    step: str,
) -> None:
    result = self.process_runner.run(
        command,
        cwd=cwd,
        env=env,
        timeout=300.0,
    )
    if result.returncode == 0:
        return
    error = self._command_result_error_text(result=result)
    if frontend_log_path:
        try:
            Path(frontend_log_path).parent.mkdir(parents=True, exist_ok=True)
            with Path(frontend_log_path).open("a", encoding="utf-8") as handle:
                handle.write(f"[envctl] frontend bootstrap step failed ({step}): {error}\n")
        except OSError:
            pass
    log_hint = f" Log: {frontend_log_path}" if frontend_log_path else ""
    raise RuntimeError(f"frontend bootstrap failed for {context.name} during {step}: {error}{log_hint}")


def _frontend_dependency_install_required(*, frontend_cwd: Path, dev_script: str) -> tuple[bool, str]:
    node_modules_dir = frontend_cwd / "node_modules"
    if not node_modules_dir.is_dir():
        return True, "node_modules_missing"

    if "vite" in dev_script.lower():
        vite_bin = node_modules_dir / ".bin" / "vite"
        if not vite_bin.is_file():
            return True, "vite_binary_missing"
    return False, "up_to_date"


def _frontend_missing_direct_dependency(*, frontend_cwd: Path, payload: Mapping[str, object]) -> str | None:
    node_modules_dir = frontend_cwd / "node_modules"
    if not node_modules_dir.is_dir():
        return None
    declared: list[str] = []
    for section_name in ("dependencies", "devDependencies"):
        section = payload.get(section_name)
        if not isinstance(section, dict):
            continue
        for package_name in section:
            name = str(package_name).strip()
            if name and not name.startswith("@types/"):
                declared.append(name)
    for package_name in sorted(set(declared)):
        if not _frontend_dependency_installed(node_modules_dir=node_modules_dir, package_name=package_name):
            return package_name
    return None


def _frontend_dependency_installed(*, node_modules_dir: Path, package_name: str) -> bool:
    package_path = node_modules_dir
    for part in package_name.split("/"):
        if not part:
            return False
        package_path = package_path / part
    return package_path.exists()


def _frontend_install_commands(*, frontend_cwd: Path, manager: str) -> tuple[list[str], list[str] | None]:
    if manager == "bun":
        return ["bun", "install"], None

    if manager == "pnpm":
        if (frontend_cwd / "pnpm-lock.yaml").is_file():
            return ["pnpm", "install", "--frozen-lockfile"], None
        return ["pnpm", "install"], None

    if manager == "yarn":
        if (frontend_cwd / "yarn.lock").is_file():
            return ["yarn", "install", "--frozen-lockfile"], None
        return ["yarn", "install"], None

    if (frontend_cwd / "package-lock.json").is_file():
        return (
            ["npm", "ci", "--include=dev", "--prefer-offline", "--no-audit"],
            ["npm", "install", "--include=dev"],
        )
    return ["npm", "install", "--include=dev"], None


def _emit_bootstrap_phase(
    self: Any,
    *,
    project: str,
    service: str,
    phase: str,
    started: float,
    status: str = "ok",
    reason: str | None = None,
) -> None:
    emit = getattr(self, "_emit", None)
    if not callable(emit):
        return
    emit(
        "service.bootstrap.phase",
        project=project,
        service=service,
        phase=phase,
        status=status,
        reason=reason,
        duration_ms=round((time.monotonic() - started) * 1000.0, 2),
    )
