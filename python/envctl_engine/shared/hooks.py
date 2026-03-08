from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(slots=True)
class HookInvocationResult:
    hook_name: str
    found: bool
    success: bool
    stdout: str
    stderr: str
    payload: dict[str, object] | None
    error: str | None = None


def run_envctl_hook(
    *,
    repo_root: Path,
    hook_name: str,
    env: Mapping[str, str] | None = None,
    hook_file: Path | None = None,
    timeout: float = 120.0,
) -> HookInvocationResult:
    resolved_hook_file = hook_file or (repo_root / ".envctl.sh")
    if not resolved_hook_file.is_file():
        return HookInvocationResult(
            hook_name=hook_name,
            found=False,
            success=True,
            stdout="",
            stderr="",
            payload=None,
        )

    script = (
        "set -euo pipefail\n"
        'source "$ENVCTL_HOOK_FILE"\n'
        'if [ "$(type -t "$ENVCTL_HOOK_NAME" 2>/dev/null || true)" != "function" ]; then\n'
        "  exit 11\n"
        "fi\n"
        '"$ENVCTL_HOOK_NAME"\n'
        'if [ -n "${ENVCTL_HOOK_JSON:-}" ]; then\n'
        '  printf "__ENVCTL_HOOK_JSON__%s\\n" "$ENVCTL_HOOK_JSON"\n'
        "fi\n"
    )

    merged_env = os.environ.copy()
    merged_env.update(dict(env or {}))
    merged_env["ENVCTL_HOOK_FILE"] = str(resolved_hook_file)
    merged_env["ENVCTL_HOOK_NAME"] = hook_name
    completed = subprocess.run(
        ["bash", "-lc", script],
        cwd=str(repo_root),
        env=merged_env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )

    if completed.returncode == 11:
        return HookInvocationResult(
            hook_name=hook_name,
            found=False,
            success=True,
            stdout="",
            stderr=completed.stderr or "",
            payload=None,
        )

    payload, clean_stdout = _extract_hook_payload(completed.stdout or "")
    if completed.returncode != 0:
        error = (completed.stderr or clean_stdout or f"exit:{completed.returncode}").strip()
        return HookInvocationResult(
            hook_name=hook_name,
            found=True,
            success=False,
            stdout=clean_stdout,
            stderr=completed.stderr or "",
            payload=payload,
            error=error or None,
        )

    return HookInvocationResult(
        hook_name=hook_name,
        found=True,
        success=True,
        stdout=clean_stdout,
        stderr=completed.stderr or "",
        payload=payload,
        error=None,
    )


def _extract_hook_payload(stdout: str) -> tuple[dict[str, object] | None, str]:
    marker = "__ENVCTL_HOOK_JSON__"
    payload: dict[str, object] | None = None
    clean_lines: list[str] = []
    for line in stdout.splitlines():
        if line.startswith(marker):
            raw = line[len(marker) :].strip()
            if raw:
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    payload = {"_raw": raw}
                else:
                    if isinstance(parsed, dict):
                        payload = parsed
                    else:
                        payload = {"value": parsed}
            continue
        clean_lines.append(line)
    clean_stdout = "\n".join(clean_lines).strip()
    return payload, clean_stdout
