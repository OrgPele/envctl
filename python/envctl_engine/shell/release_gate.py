from __future__ import annotations

import json
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Sequence

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

CANONICAL_BOOTSTRAP_COMMANDS: tuple[str, ...] = (
    "python3.12 -m venv .venv",
    ".venv/bin/python -m pip install -e '.[dev]'",
)
CANONICAL_VALIDATION_COMMAND_DISPLAY = ".venv/bin/python -m pytest -q"
CANONICAL_BUILD_COMMAND_DISPLAY = ".venv/bin/python -m build"
CANONICAL_RELEASE_GATE_COMMAND = ".venv/bin/python scripts/release_shipability_gate.py --repo ."
CANONICAL_RELEASE_GATE_WITH_TESTS_COMMAND = f"{CANONICAL_RELEASE_GATE_COMMAND} --check-tests"


@dataclass(slots=True)
class ShipabilityResult:
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CommandExecution:
    returncode: int
    output: str


def evaluate_shipability(
    *,
    repo_root: Path,
    required_paths: Sequence[str] | None = None,
    required_scopes: Sequence[str] | None = None,
    check_tests: bool = False,
    check_packaging: bool = False,
    enforce_parity_sync: bool = True,
    enforce_runtime_readiness_contract: bool = True,
    enforce_documented_flag_parity: bool = True,
    validation_command: Sequence[str] | None = None,
    build_command: Sequence[str] | None = None,
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
        test_command = list(validation_command or canonical_validation_command(repo_root))
        validation_issue = _misconfigured_repo_local_python(
            test_command,
            repo_root=repo_root,
            error_prefix="validation_lane",
        )
        if validation_issue is not None:
            errors.append(validation_issue)
        else:
            validation_result = _run_cmd_capture(repo_root, test_command)
            if validation_result.returncode != 0:
                errors.append(
                    f"validation_lane_failed: {format_command(test_command)} (exit {validation_result.returncode})"
                )

    if check_packaging:
        packaging_command = list(build_command or canonical_packaging_command(repo_root))
        packaging_issue = _misconfigured_repo_local_python(
            packaging_command,
            repo_root=repo_root,
            error_prefix="packaging_build",
        )
        if packaging_issue is not None:
            errors.append(packaging_issue)
        else:
            packaging_result = _run_cmd_capture(repo_root, packaging_command)
            if packaging_result.returncode != 0:
                errors.append(
                    f"packaging_build_failed: {format_command(packaging_command)} "
                    f"(exit {packaging_result.returncode})"
                )
            else:
                warning_line = _warning_line(packaging_result.output)
                if warning_line is not None:
                    errors.append(f"packaging_build_warned: {warning_line}")

    if errors and check_tests:
        warnings.append("run with --skip-tests during local iteration to focus on structural shipability checks")
    if errors and check_packaging:
        warnings.append("run with --skip-build during local iteration to focus on structural shipability checks")

    return ShipabilityResult(passed=not errors, errors=errors, warnings=warnings)


def canonical_repo_python(repo_root: Path) -> Path:
    return repo_root / ".venv" / "bin" / "python"


def canonical_validation_command(repo_root: Path) -> list[str]:
    return [str(canonical_repo_python(repo_root)), "-m", "pytest", "-q"]


def canonical_packaging_command(repo_root: Path) -> list[str]:
    return [str(canonical_repo_python(repo_root)), "-m", "build"]


def format_command(args: Sequence[str]) -> str:
    display: list[str] = []
    for index, token in enumerate(args):
        value = str(token)
        if index == 0:
            try:
                path = Path(value)
            except Exception:
                path = Path()
            if value == str(path) and path.name == "python" and ".venv" in path.parts:
                display.append(str(Path(".venv") / "bin" / "python"))
                continue
        display.append(value)
    return shlex.join(display)


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


def _manifest_freshness_is_valid(
    repo_root: Path,
    max_age_days: int = 7,
    *,
    now: datetime | None = None,
) -> tuple[bool, str]:
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
        generated_at = _parse_generated_at(str(generated_at_str))
        age = _normalize_freshness_clock(now) - generated_at
        if age > timedelta(days=max_age_days):
            return False, f"manifest stale: generated {age.days} days ago (max {max_age_days})"
    except (ValueError, TypeError) as e:
        return False, f"invalid generated_at format: {e}"

    return True, "manifest fresh"


def _parse_generated_at(raw_timestamp: str) -> datetime:
    normalized = str(raw_timestamp).strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _normalize_freshness_clock(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(UTC)
    if now.tzinfo is None:
        return now.replace(tzinfo=UTC)
    return now.astimezone(UTC)


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


def _run_cmd_capture(repo_root: Path, args: Sequence[str]) -> CommandExecution:
    completed = subprocess.run(
        list(args),
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    output = "\n".join(part for part in (completed.stdout.strip(), completed.stderr.strip()) if part)
    return CommandExecution(returncode=int(completed.returncode), output=output)


def _misconfigured_repo_local_python(args: Sequence[str], *, repo_root: Path, error_prefix: str) -> str | None:
    if not args:
        return f"{error_prefix}_misconfigured: empty command"
    executable = Path(str(args[0]))
    expected = canonical_repo_python(repo_root)
    if executable == expected and not executable.exists():
        return (
            f"{error_prefix}_misconfigured: expected repo-local interpreter at "
            f"{expected.relative_to(repo_root)}"
        )
    return None


def _warning_line(output: str) -> str | None:
    for line in output.splitlines():
        text = line.strip()
        if not text:
            continue
        lowered = text.lower()
        if "deprecationwarning" in lowered or "warning:" in lowered or lowered.startswith("warning "):
            return text
    return None


def _unsupported_documented_flags(repo_root: Path) -> list[str]:
    docs_path = repo_root / "docs/reference/important-flags.md"
    if not docs_path.is_file():
        return []
    text = docs_path.read_text(encoding="utf-8")
    tokens = sorted({match.group(0) for match in re.finditer(r"--[a-z0-9][a-z0-9-]*", text)})
    supported = set(list_supported_flag_tokens())
    ignored = {"--help", "--repo", "--version"}
    return [token for token in tokens if token not in supported and token not in ignored]
