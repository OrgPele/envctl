from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import json
from pathlib import Path
import pprint
import re
import sys
from typing import Any, Mapping


LEGACY_HOOK_FILE = ".envctl.sh"
PYTHON_HOOK_FILE = ".envctl_hooks.py"
SUPPORTED_HOOK_NAMES = ("envctl_setup_infrastructure", "envctl_define_services")
_LEGACY_FUNCTION_RE = re.compile(
    r"(?ms)^\s*(?:function\s+)?(?P<name>envctl_[A-Za-z0-9_]+)\s*\(\)\s*\{(?P<body>.*?)^\s*\}",
)
_EXPORT_JSON_RE = re.compile(r"""^(?:export\s+)?ENVCTL_HOOK_JSON=(['"])(?P<value>.*)\1$""")


@dataclass(slots=True)
class HookInvocationResult:
    hook_name: str
    found: bool
    success: bool
    stdout: str
    stderr: str
    payload: dict[str, object] | None
    error: str | None = None


@dataclass(slots=True)
class HookMigrationResult:
    migrated: bool
    python_hook_path: Path
    migrated_hooks: list[str]
    skipped_hooks: list[str]
    error: str | None = None
    starter_stub: str | None = None


def python_hook_module_path(repo_root: Path, hook_file: Path | None = None) -> Path:
    if hook_file is not None and hook_file.suffix == ".py":
        return hook_file
    return repo_root / PYTHON_HOOK_FILE


def legacy_hook_file_path(repo_root: Path, hook_file: Path | None = None) -> Path:
    if hook_file is not None and hook_file.suffix == ".sh":
        return hook_file
    return repo_root / LEGACY_HOOK_FILE


def legacy_shell_hook_names(repo_root: Path, *, hook_file: Path | None = None) -> list[str]:
    legacy_file = legacy_hook_file_path(repo_root, hook_file=hook_file)
    if not legacy_file.is_file():
        return []
    text = legacy_file.read_text(encoding="utf-8")
    names = {
        str(match.group("name")).strip()
        for match in _LEGACY_FUNCTION_RE.finditer(text)
        if str(match.group("name")).strip() in SUPPORTED_HOOK_NAMES
    }
    return sorted(names)


def legacy_shell_hook_issue(repo_root: Path, *, hook_name: str | None = None) -> str | None:
    python_hook_file = python_hook_module_path(repo_root)
    if python_hook_file.is_file():
        return None
    names = legacy_shell_hook_names(repo_root)
    if not names:
        return None
    if hook_name is not None and hook_name not in names:
        return None
    rendered_names = ", ".join(names)
    return (
        f"Legacy shell hook functions remain in {LEGACY_HOOK_FILE}: {rendered_names}. "
        f"Move them to {PYTHON_HOOK_FILE} or run 'envctl migrate-hooks'."
    )


def build_python_hook_starter_stub(*, hook_names: list[str] | None = None) -> str:
    names = hook_names or list(SUPPORTED_HOOK_NAMES)
    lines = [
        "from __future__ import annotations",
        "",
    ]
    for hook_name in names:
        lines.extend(
            [
                f"def {hook_name}(context: dict) -> dict | None:",
                "    # Fill in and return a payload dict, or return None to skip custom behavior.",
                "    return None",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def migrate_legacy_shell_hooks(repo_root: Path, *, force: bool = False) -> HookMigrationResult:
    python_hook_file = python_hook_module_path(repo_root)
    legacy_file = legacy_hook_file_path(repo_root)
    names = legacy_shell_hook_names(repo_root, hook_file=legacy_file)
    if not names:
        return HookMigrationResult(
            migrated=False,
            python_hook_path=python_hook_file,
            migrated_hooks=[],
            skipped_hooks=[],
            error="No legacy shell hook functions were found.",
            starter_stub=build_python_hook_starter_stub(),
        )
    if python_hook_file.exists() and not force:
        return HookMigrationResult(
            migrated=False,
            python_hook_path=python_hook_file,
            migrated_hooks=[],
            skipped_hooks=names,
            error=f"{PYTHON_HOOK_FILE} already exists. Re-run with --force to overwrite it.",
        )

    payloads: dict[str, dict[str, object]] = {}
    unsupported: list[str] = []
    for hook_name in names:
        payload = _parse_legacy_hook_payload(legacy_file=legacy_file, hook_name=hook_name)
        if payload is None:
            unsupported.append(hook_name)
            continue
        payloads[hook_name] = payload
    if unsupported:
        return HookMigrationResult(
            migrated=False,
            python_hook_path=python_hook_file,
            migrated_hooks=sorted(payloads.keys()),
            skipped_hooks=unsupported,
            error=(
                "Unsupported shell hook bodies detected for: "
                + ", ".join(sorted(unsupported))
                + f". Write {PYTHON_HOOK_FILE} manually using the starter stub below."
            ),
            starter_stub=build_python_hook_starter_stub(hook_names=sorted(set(names))),
        )

    rendered = _render_python_hooks(payloads)
    python_hook_file.write_text(rendered, encoding="utf-8")
    return HookMigrationResult(
        migrated=True,
        python_hook_path=python_hook_file,
        migrated_hooks=sorted(payloads.keys()),
        skipped_hooks=[],
        error=None,
    )


def run_envctl_hook(
    *,
    repo_root: Path,
    hook_name: str,
    env: Mapping[str, str] | None = None,
    hook_file: Path | None = None,
    timeout: float = 120.0,
    context: Mapping[str, object] | None = None,
) -> HookInvocationResult:
    del env, timeout
    python_hook_file = python_hook_module_path(repo_root, hook_file=hook_file)
    if python_hook_file.is_file():
        return _run_python_hook(
            repo_root=repo_root,
            hook_name=hook_name,
            hook_file=python_hook_file,
            context=context or {},
        )
    issue = legacy_shell_hook_issue(repo_root, hook_name=hook_name)
    if issue:
        return HookInvocationResult(
            hook_name=hook_name,
            found=True,
            success=False,
            stdout="",
            stderr=issue,
            payload=None,
            error=issue,
        )
    return HookInvocationResult(
        hook_name=hook_name,
        found=False,
        success=True,
        stdout="",
        stderr="",
        payload=None,
    )


def _run_python_hook(
    *,
    repo_root: Path,
    hook_name: str,
    hook_file: Path,
    context: Mapping[str, object],
) -> HookInvocationResult:
    try:
        module = _load_hook_module(hook_file)
    except Exception as exc:  # noqa: BLE001
        message = f"Failed to load {hook_file.name}: {exc}"
        return HookInvocationResult(
            hook_name=hook_name,
            found=True,
            success=False,
            stdout="",
            stderr=message,
            payload=None,
            error=message,
        )
    hook_fn = getattr(module, hook_name, None)
    if not callable(hook_fn):
        return HookInvocationResult(
            hook_name=hook_name,
            found=False,
            success=True,
            stdout="",
            stderr="",
            payload=None,
        )
    try:
        raw = hook_fn(dict(context))
    except Exception as exc:  # noqa: BLE001
        message = f"{hook_name} failed: {exc}"
        return HookInvocationResult(
            hook_name=hook_name,
            found=True,
            success=False,
            stdout="",
            stderr=message,
            payload=None,
            error=message,
        )
    payload = _normalize_hook_payload(raw)
    return HookInvocationResult(
        hook_name=hook_name,
        found=True,
        success=True,
        stdout="",
        stderr="",
        payload=payload,
        error=None,
    )


def _load_hook_module(hook_file: Path) -> Any:
    module_name = f"_envctl_hooks_{abs(hash(hook_file.resolve()))}"
    spec = importlib.util.spec_from_file_location(module_name, hook_file)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load hook module from {hook_file}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _normalize_hook_payload(raw: object) -> dict[str, object] | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return {str(key): value for key, value in raw.items()}
    return {"value": raw}


def _parse_legacy_hook_payload(*, legacy_file: Path, hook_name: str) -> dict[str, object] | None:
    text = legacy_file.read_text(encoding="utf-8")
    for match in _LEGACY_FUNCTION_RE.finditer(text):
        name = str(match.group("name")).strip()
        if name != hook_name:
            continue
        body = str(match.group("body"))
        return _parse_legacy_hook_body(body)
    return None


def _parse_legacy_hook_body(body: str) -> dict[str, object] | None:
    lines = [line.strip() for line in body.splitlines() if line.strip() and not line.strip().startswith("#")]
    if not lines:
        return {}
    if len(lines) == 1:
        match = _EXPORT_JSON_RE.match(lines[0])
        if match is None:
            return None
        raw_json = match.group("value")
        return _json_payload_or_none(raw_json)
    if len(lines) == 2 and lines[1] == "export ENVCTL_HOOK_JSON":
        prefix = "ENVCTL_HOOK_JSON="
        if not lines[0].startswith(prefix):
            return None
        raw_value = lines[0][len(prefix) :].strip()
        if len(raw_value) < 2 or raw_value[0] != raw_value[-1] or raw_value[0] not in {"'", '"'}:
            return None
        return _json_payload_or_none(raw_value[1:-1])
    return None


def _json_payload_or_none(raw_json: str) -> dict[str, object] | None:
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        return payload
    return {"value": payload}


def _render_python_hooks(payloads: Mapping[str, dict[str, object]]) -> str:
    lines = ["from __future__ import annotations", ""]
    for hook_name in SUPPORTED_HOOK_NAMES:
        if hook_name not in payloads:
            continue
        rendered = pprint.pformat(payloads[hook_name], sort_dicts=True, width=88)
        lines.extend(
            [
                f"def {hook_name}(context: dict) -> dict | None:",
                "    del context",
                f"    return {rendered}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"
