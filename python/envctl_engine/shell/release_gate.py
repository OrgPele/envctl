from __future__ import annotations

import json
import subprocess
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence
from datetime import datetime, timedelta

from envctl_engine.runtime.command_router import list_supported_flag_tokens
from envctl_engine.runtime.runtime_readiness import evaluate_runtime_readiness

DEFAULT_REQUIRED_PATHS: tuple[str, ...] = (
    "python/envctl_engine",
    "tests/python",
    "contracts/python_engine_parity_manifest.json",
    "contracts/python_runtime_gap_report.json",
)

DEFAULT_REQUIRED_SCOPES: tuple[str, ...] = (
    "python/envctl_engine",
    "tests/python",
    "contracts",
)


@dataclass(slots=True)
class ShipabilityResult:
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def evaluate_shipability(
    *,
    repo_root: Path,
    required_paths: Sequence[str] | None = None,
    required_scopes: Sequence[str] | None = None,
    check_tests: bool = False,
    enforce_parity_sync: bool = True,
    enforce_runtime_readiness_contract: bool = True,
    enforce_documented_flag_parity: bool = True,
) -> ShipabilityResult:
    required_paths = tuple(DEFAULT_REQUIRED_PATHS if required_paths is None else required_paths)
    required_scopes = tuple(DEFAULT_REQUIRED_SCOPES if required_scopes is None else required_scopes)
    errors: list[str] = []
    warnings: list[str] = []

    if not (repo_root / ".git").exists():
        errors.append(f"repo is not a git repository: {repo_root}")
        return ShipabilityResult(passed=False, errors=errors, warnings=warnings)

    for raw_path in required_paths:
        relative = Path(raw_path)
        abs_path = repo_root / relative
        if not abs_path.exists():
            errors.append(f"required path missing: {relative}")
            continue
        if abs_path.is_file():
            if not _is_file_tracked(repo_root, str(relative)):
                errors.append(f"required file is not tracked: {relative}")
            continue
        tracked = _git_lines(repo_root, ["ls-files", "--", str(relative)])
        if not tracked:
            errors.append(f"required directory has no tracked files: {relative}")

    untracked = _git_lines(repo_root, ["ls-files", "--others", "--exclude-standard", "--", *required_scopes])
    if untracked:
        preview = ", ".join(untracked[:5])
        suffix = " ..." if len(untracked) > 5 else ""
        errors.append(f"untracked files found in required scopes: {preview}{suffix}")

    if enforce_parity_sync:
        manifest_status = _manifest_is_complete(repo_root)
        runtime_status = _runtime_parity_is_complete()
        if manifest_status != runtime_status:
            errors.append(
                "parity manifest/runtime mismatch: manifest completeness does not match runtime partial command list"
            )

        fresh_ok, fresh_msg = _manifest_freshness_is_valid(repo_root)
        if not fresh_ok:
            errors.append(f"manifest freshness check failed: {fresh_msg}")

        if manifest_status and runtime_status:
            readiness = evaluate_runtime_readiness(repo_root)
            if not readiness.passed:
                errors.append(
                    "python_complete blocked: runtime readiness contract failed with "
                    f"{readiness.blocking_gap_count} blocking gaps"
                )

    if enforce_runtime_readiness_contract:
        readiness = evaluate_runtime_readiness(
            repo_root,
            require_gap_free=True,
            require_manifest_complete=True,
        )
        if not readiness.passed:
            errors.extend(readiness.errors)
        warnings.extend(readiness.warnings)

    if enforce_documented_flag_parity:
        unsupported = _unsupported_documented_flags(repo_root)
        if unsupported:
            preview = ", ".join(unsupported[:10])
            suffix = " ..." if len(unsupported) > 10 else ""
            errors.append(f"documented flags unsupported by parser: {preview}{suffix}")

    if check_tests:
        python_code = _run_cmd(
            repo_root,
            [".venv/bin/python", "-m", "unittest", "discover", "-s", "tests/python", "-p", "test_*.py"],
        )
        if python_code != 0:
            errors.append("python unit suite failed in release gate")

    if errors and check_tests:
        warnings.append("run with --skip-tests during local iteration to focus on structural shipability checks")

    return ShipabilityResult(passed=not errors, errors=errors, warnings=warnings)


def _manifest_is_complete(repo_root: Path) -> bool:
    manifest_path = repo_root / "contracts/python_engine_parity_manifest.json"
    if not manifest_path.is_file():
        return False
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    commands = payload.get("commands")
    modes = payload.get("modes")
    if not isinstance(commands, dict) or not isinstance(modes, dict):
        return False
    if not all(str(status) == "python_complete" for status in commands.values()):
        return False
    for mode_payload in modes.values():
        if not isinstance(mode_payload, dict):
            return False
        if not all(str(status) == "python_complete" for status in mode_payload.values()):
            return False
    return True


def _runtime_parity_is_complete() -> bool:
    from envctl_engine.runtime.engine_runtime import PythonEngineRuntime

    return len(PythonEngineRuntime.PARTIAL_COMMANDS) == 0


def _manifest_freshness_is_valid(repo_root: Path, max_age_days: int = 7) -> tuple[bool, str]:
    manifest_path = repo_root / "contracts/python_engine_parity_manifest.json"
    if not manifest_path.is_file():
        return False, "manifest file missing"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        return False, f"manifest parse error: {e}"

    generated_at_str = payload.get("generated_at")
    if not generated_at_str:
        return False, "manifest missing generated_at timestamp"

    try:
        generated_at = datetime.fromisoformat(str(generated_at_str))
        age = datetime.now() - generated_at
        if age > timedelta(days=max_age_days):
            return False, f"manifest stale: generated {age.days} days ago (max {max_age_days})"
    except (ValueError, TypeError) as e:
        return False, f"invalid generated_at format: {e}"

    return True, "manifest fresh"


def _is_file_tracked(repo_root: Path, relative_path: str) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "--error-unmatch", "--", relative_path],
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.returncode == 0


def _git_lines(repo_root: Path, args: Sequence[str]) -> list[str]:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def _run_cmd(repo_root: Path, args: Sequence[str], *, shell: bool = False) -> int:
    if shell:
        command = " ".join(args)
        completed = subprocess.run(command, cwd=repo_root, shell=True, check=False)
    else:
        completed = subprocess.run(args, cwd=repo_root, check=False)
    return int(completed.returncode)


def _unsupported_documented_flags(repo_root: Path) -> list[str]:
    docs_path = repo_root / "docs/reference/important-flags.md"
    if not docs_path.is_file():
        return []
    text = docs_path.read_text(encoding="utf-8")
    tokens = sorted({match.group(0) for match in re.finditer(r"--[a-z0-9][a-z0-9-]*", text)})
    supported = set(list_supported_flag_tokens())
    ignored = {"--help"}
    return [token for token in tokens if token not in supported and token not in ignored]
