from __future__ import annotations

import subprocess
import re
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence
from datetime import datetime, timedelta

from envctl_engine.runtime.command_router import list_supported_flag_tokens
from envctl_engine.shell.shell_prune import evaluate_shell_prune_contract

DEFAULT_REQUIRED_PATHS: tuple[str, ...] = (
    "python/envctl_engine",
    "tests/python",
    "tests/bats/parallel_trees_python_e2e.bats",
    "tests/bats/python_engine_parity.bats",
    "contracts/python_engine_parity_manifest.json",
    "contracts/envctl-shell-ownership-ledger.json",
)

DEFAULT_REQUIRED_SCOPES: tuple[str, ...] = (
    "python/envctl_engine",
    "tests/python",
    "tests/bats",
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
    enforce_shell_prune_contract: bool = True,
    enforce_documented_flag_parity: bool = True,
    enforce_shell_flag_parity: bool = True,
    shell_prune_max_unmigrated: int | None = None,
    shell_prune_max_partial_keep: int | None = None,
    shell_prune_max_intentional_keep: int | None = None,
    shell_prune_phase: str | None = None,
    require_shell_budget_complete: bool = False,
) -> ShipabilityResult:
    required_paths = tuple(DEFAULT_REQUIRED_PATHS if required_paths is None else required_paths)
    required_scopes = tuple(DEFAULT_REQUIRED_SCOPES if required_scopes is None else required_scopes)
    errors: list[str] = []
    warnings: list[str] = []

    requested_shell_prune_max_unmigrated = shell_prune_max_unmigrated
    requested_shell_prune_max_partial_keep = shell_prune_max_partial_keep
    requested_shell_prune_max_intentional_keep = shell_prune_max_intentional_keep

    if enforce_shell_prune_contract:
        is_cutover_phase = str(shell_prune_phase or "").strip().lower() == "cutover"
        has_explicit_cutover_unmigrated_budget = shell_prune_max_unmigrated is not None
        require_complete_profile = bool(require_shell_budget_complete) or (
            is_cutover_phase and has_explicit_cutover_unmigrated_budget
        )
        if require_complete_profile:
            if requested_shell_prune_max_unmigrated is None:
                errors.append("shell_unmigrated_budget_undefined")
            if requested_shell_prune_max_partial_keep is None:
                errors.append("shell_partial_keep_budget_undefined")
            if requested_shell_prune_max_intentional_keep is None:
                errors.append("shell_intentional_keep_budget_undefined")
        if shell_prune_max_unmigrated is None:
            shell_prune_max_unmigrated = 0
        if shell_prune_max_partial_keep is None:
            shell_prune_max_partial_keep = 0
        if shell_prune_max_intentional_keep is None:
            shell_prune_max_intentional_keep = 0
        if shell_prune_phase is None:
            shell_prune_phase = "cutover"

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
        
        # Check manifest freshness
        fresh_ok, fresh_msg = _manifest_freshness_is_valid(repo_root)
        if not fresh_ok:
            errors.append(f"manifest freshness check failed: {fresh_msg}")
        
        # Block python_complete declaration until wave acceptance checks pass
        if manifest_status and runtime_status:
            wave_ok, wave_errors = _python_complete_blocked_until_wave_acceptance(repo_root)
            if not wave_ok:
                errors.extend(wave_errors)

    if enforce_shell_prune_contract:
        prune = evaluate_shell_prune_contract(
            repo_root,
            enforce_manifest_coverage=True,
            max_unmigrated=shell_prune_max_unmigrated,
            max_partial_keep=shell_prune_max_partial_keep,
            max_intentional_keep=shell_prune_max_intentional_keep,
            phase=shell_prune_phase,
        )
        if not prune.passed:
            errors.extend(prune.errors)
        warnings.extend(prune.warnings)

    if enforce_documented_flag_parity:
        unsupported = _unsupported_documented_flags(repo_root)
        if unsupported:
            preview = ", ".join(unsupported[:10])
            suffix = " ..." if len(unsupported) > 10 else ""
            errors.append(f"documented flags unsupported by parser: {preview}{suffix}")

    if enforce_shell_flag_parity:
        unsupported_shell_flags = _unsupported_shell_flags(repo_root)
        if unsupported_shell_flags:
            preview = ", ".join(unsupported_shell_flags[:10])
            suffix = " ..." if len(unsupported_shell_flags) > 10 else ""
            errors.append(f"shell flags unsupported by parser: {preview}{suffix}")

    if check_tests:
        python_code = _run_cmd(
            repo_root,
            [".venv/bin/python", "-m", "unittest", "discover", "-s", "tests/python", "-p", "test_*.py"],
        )
        if python_code != 0:
            errors.append("python unit suite failed in release gate")
        bats_lanes = _resolve_python_bats_lanes(repo_root)
        bats_code = _run_cmd(
            repo_root,
            ["bats", *bats_lanes],
        )
        if bats_code != 0:
            errors.append("bats suite failed in release gate")

    if errors and check_tests:
        warnings.append("run with --skip-tests during local iteration to focus on structural shipability checks")

    return ShipabilityResult(passed=not errors, errors=errors, warnings=warnings)


def _manifest_is_complete(repo_root: Path) -> bool:
    manifest_path = repo_root / "contracts/python_engine_parity_manifest.json"
    if not manifest_path.is_file():
        return False
    try:
        import json

        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    commands = payload.get("commands")
    if not isinstance(commands, dict):
        return False
    return all(str(status) == "python_complete" for status in commands.values())


def _runtime_parity_is_complete() -> bool:
    from envctl_engine.runtime.engine_runtime import PythonEngineRuntime

    return len(PythonEngineRuntime.PARTIAL_COMMANDS) == 0


def _manifest_freshness_is_valid(repo_root: Path, max_age_days: int = 7) -> tuple[bool, str]:
    """Check manifest generated_at timestamp is recent and proof references are valid."""
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


def _python_complete_blocked_until_wave_acceptance(repo_root: Path) -> tuple[bool, list[str]]:
    """Block declaring python_complete until wave acceptance checks pass."""
    errors = []
    
    # Check shell prune contract with strict defaults
    prune = evaluate_shell_prune_contract(
        repo_root,
        enforce_manifest_coverage=True,
        max_unmigrated=0,
        max_partial_keep=0,
        max_intentional_keep=0,
        phase="cutover",
    )
    
    if not prune.passed:
        errors.extend(prune.errors)
        return False, errors
    
    # Verify manifest completeness matches runtime
    manifest_complete = _manifest_is_complete(repo_root)
    runtime_complete = _runtime_parity_is_complete()
    
    if not (manifest_complete and runtime_complete):
        errors.append("python_complete blocked: manifest or runtime not fully migrated")
        return False, errors
    
    # Verify manifest freshness
    fresh, reason = _manifest_freshness_is_valid(repo_root)
    if not fresh:
        errors.append(f"python_complete blocked: {reason}")
        return False, errors
    
    return True, []


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
        cmd = " ".join(args)
        completed = subprocess.run(cmd, cwd=str(repo_root), shell=True, check=False)
        return completed.returncode
    completed = subprocess.run(list(args), cwd=str(repo_root), check=False)
    return completed.returncode


def _resolve_python_bats_lanes(repo_root: Path) -> list[str]:
    bats_dir = repo_root / "tests" / "bats"
    python_lanes = sorted(
        str(path.relative_to(repo_root)).replace("\\", "/")
        for path in bats_dir.glob("python_*.bats")
        if path.is_file()
    )
    parallel_lane = "tests/bats/parallel_trees_python_e2e.bats"
    if (repo_root / parallel_lane).is_file():
        python_lanes.append(parallel_lane)
    if python_lanes:
        return python_lanes
    return ["tests/bats/python_*.bats", parallel_lane]


_FLAG_PATTERN = re.compile(r"`(--[a-z0-9][a-z0-9-]*)")
_SHELL_FLAG_PATTERN = re.compile(r"--[a-z0-9][a-z0-9-]*")


def _unsupported_documented_flags(repo_root: Path) -> list[str]:
    docs_candidates = (
        repo_root / "docs" / "reference" / "important-flags.md",
        repo_root / "docs" / "important-flags.md",
    )
    docs_path = next((path for path in docs_candidates if path.is_file()), None)
    if docs_path is None:
        return []
    try:
        raw = docs_path.read_text(encoding="utf-8")
    except OSError:
        return []
    documented = set(match.group(1) for match in _FLAG_PATTERN.finditer(raw))
    supported = set(list_supported_flag_tokens())
    return sorted(documented.difference(supported))


def _unsupported_shell_flags(repo_root: Path) -> list[str]:
    shell_cli_path = repo_root / "lib" / "engine" / "lib" / "run_all_trees_cli.sh"
    if not shell_cli_path.is_file():
        return []
    try:
        raw = shell_cli_path.read_text(encoding="utf-8")
    except OSError:
        return []
    shell_flags = {token for token in _SHELL_FLAG_PATTERN.findall(raw) if token.startswith("--")}
    supported = set(list_supported_flag_tokens())
    return sorted(shell_flags.difference(supported))
