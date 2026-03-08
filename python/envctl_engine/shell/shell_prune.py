from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


LEDGER_RELATIVE_PATH = Path("docs/planning/refactoring/envctl-shell-ownership-ledger.json")
PARITY_MANIFEST_RELATIVE_PATH = Path("docs/planning/python_engine_parity_manifest.json")
ENGINE_MAIN_RELATIVE_PATH = Path("lib/engine/main.sh")

LEDGER_ALLOWED_STATUSES: tuple[str, ...] = (
    "python_verified_delete_now",
    "python_partial_keep_temporarily",
    "shell_intentional_keep",
    "unmigrated",
)

_FUNCTION_PATTERN = re.compile(r"^\s*(?:function\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\(\)\s*\{")
_LIB_SOURCE_PATTERN = re.compile(r'^\s*source\s+"?\$\{LIB_DIR\}/([^"\s]+)"?')
_SCRIPT_LIB_SOURCE_PATTERN = re.compile(r'^\s*source\s+"?\$\{SCRIPT_DIR\}/lib/([^"\s]+)"?')


@dataclass(slots=True)
class ShellPruneContractResult:
    passed: bool
    ledger_exists: bool
    ledger_path: Path
    ledger_generated_at: str
    ledger_hash: str
    status_counts: dict[str, int] = field(default_factory=dict)
    missing_python_complete_commands: list[str] = field(default_factory=list)
    partial_keep_covered_count: int = 0
    partial_keep_uncovered_count: int = 0
    partial_keep_budget_actual: int = 0
    partial_keep_budget_basis: str = "uncovered"
    intentional_keep_budget_actual: int = 0
    max_unmigrated: int | None = None
    max_partial_keep: int | None = None
    max_intentional_keep: int | None = None
    phase: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def load_shell_ownership_ledger(repo_root: Path) -> dict[str, object]:
    ledger_path = repo_root / LEDGER_RELATIVE_PATH
    payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"ledger must be a JSON object: {ledger_path}")
    return payload


def evaluate_shell_prune_contract(
    repo_root: Path,
    *,
    enforce_manifest_coverage: bool = True,
    max_unmigrated: int | None = None,
    max_partial_keep: int | None = None,
    max_intentional_keep: int | None = None,
    phase: str | None = None,
) -> ShellPruneContractResult:
    ledger_path = repo_root / LEDGER_RELATIVE_PATH
    errors: list[str] = []
    warnings: list[str] = []
    status_counts = {status: 0 for status in LEDGER_ALLOWED_STATUSES}
    missing_commands: list[str] = []
    partial_keep_covered_count = 0
    partial_keep_uncovered_count = 0
    generated_at = "missing"
    digest = "missing"
    partial_keep_budget_basis = "uncovered"

    if not ledger_path.is_file():
        errors.append(f"shell ownership ledger missing: {LEDGER_RELATIVE_PATH}")
        return ShellPruneContractResult(
            passed=False,
            ledger_exists=False,
            ledger_path=ledger_path,
            ledger_generated_at=generated_at,
            ledger_hash=digest,
            status_counts=status_counts,
            missing_python_complete_commands=missing_commands,
            partial_keep_covered_count=partial_keep_covered_count,
            partial_keep_uncovered_count=partial_keep_uncovered_count,
            partial_keep_budget_actual=partial_keep_uncovered_count,
            partial_keep_budget_basis=partial_keep_budget_basis,
            intentional_keep_budget_actual=0,
            max_unmigrated=max_unmigrated,
            max_partial_keep=max_partial_keep,
            max_intentional_keep=max_intentional_keep,
            phase=phase,
            errors=errors,
            warnings=warnings,
        )

    try:
        raw_text = ledger_path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"failed to read shell ownership ledger: {exc}")
        return ShellPruneContractResult(
            passed=False,
            ledger_exists=True,
            ledger_path=ledger_path,
            ledger_generated_at=generated_at,
            ledger_hash=digest,
            status_counts=status_counts,
            missing_python_complete_commands=missing_commands,
            partial_keep_covered_count=partial_keep_covered_count,
            partial_keep_uncovered_count=partial_keep_uncovered_count,
            partial_keep_budget_actual=partial_keep_uncovered_count,
            partial_keep_budget_basis=partial_keep_budget_basis,
            intentional_keep_budget_actual=0,
            max_unmigrated=max_unmigrated,
            max_partial_keep=max_partial_keep,
            max_intentional_keep=max_intentional_keep,
            phase=phase,
            errors=errors,
            warnings=warnings,
        )

    digest = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        errors.append(f"invalid shell ownership ledger JSON: {exc}")
        return ShellPruneContractResult(
            passed=False,
            ledger_exists=True,
            ledger_path=ledger_path,
            ledger_generated_at=generated_at,
            ledger_hash=digest,
            status_counts=status_counts,
            missing_python_complete_commands=missing_commands,
            partial_keep_covered_count=partial_keep_covered_count,
            partial_keep_uncovered_count=partial_keep_uncovered_count,
            partial_keep_budget_actual=partial_keep_uncovered_count,
            partial_keep_budget_basis=partial_keep_budget_basis,
            intentional_keep_budget_actual=0,
            max_unmigrated=max_unmigrated,
            max_partial_keep=max_partial_keep,
            max_intentional_keep=max_intentional_keep,
            phase=phase,
            errors=errors,
            warnings=warnings,
        )

    if not isinstance(payload, dict):
        errors.append("shell ownership ledger must be a JSON object")
        return ShellPruneContractResult(
            passed=False,
            ledger_exists=True,
            ledger_path=ledger_path,
            ledger_generated_at=generated_at,
            ledger_hash=digest,
            status_counts=status_counts,
            missing_python_complete_commands=missing_commands,
            partial_keep_covered_count=partial_keep_covered_count,
            partial_keep_uncovered_count=partial_keep_uncovered_count,
            partial_keep_budget_actual=partial_keep_uncovered_count,
            partial_keep_budget_basis=partial_keep_budget_basis,
            intentional_keep_budget_actual=0,
            max_unmigrated=max_unmigrated,
            max_partial_keep=max_partial_keep,
            max_intentional_keep=max_intentional_keep,
            phase=phase,
            errors=errors,
            warnings=warnings,
        )

    generated_at = str(payload.get("generated_at", "missing"))
    source_modules = discover_sourced_shell_modules(repo_root)
    entries = payload.get("entries")
    if not isinstance(entries, list):
        errors.append("shell ownership ledger entries must be a list")
        entries = []
    elif not entries and source_modules:
        errors.append("shell ownership ledger must include a non-empty entries list")

    delete_now_modules: set[str] = set()

    for index, raw in enumerate(entries):
        if not isinstance(raw, dict):
            errors.append(f"entries[{index}] must be an object")
            continue
        for field in (
            "shell_module",
            "shell_function",
            "python_owner_module",
            "python_owner_symbol",
            "status",
            "evidence_tests",
            "delete_wave",
            "notes",
        ):
            if field not in raw:
                errors.append(f"entries[{index}] missing required field: {field}")
        status = str(raw.get("status", ""))
        if status not in LEDGER_ALLOWED_STATUSES:
            errors.append(f"entries[{index}] has invalid status: {status}")
            continue
        shell_module = str(raw.get("shell_module", "")).strip()
        shell_function = str(raw.get("shell_function", "")).strip()
        if not shell_module:
            errors.append(f"entries[{index}] shell_module must be non-empty")
            continue
        if not shell_function:
            errors.append(f"entries[{index}] shell_function must be non-empty")
            continue

        if shell_module in source_modules:
            status_counts[status] = status_counts.get(status, 0) + 1

        evidence_tests = raw.get("evidence_tests")
        if not isinstance(evidence_tests, list):
            errors.append(f"entries[{index}] evidence_tests must be a list")
        elif status != "unmigrated" and not evidence_tests:
            warnings.append(f"entries[{index}] has non-unmigrated status without evidence_tests")

        shell_path = repo_root / shell_module
        functions = parse_shell_functions(shell_path)
        if status == "python_verified_delete_now":
            delete_now_modules.add(shell_module)
            if shell_function in functions:
                errors.append(
                    f"entries[{index}] python_verified_delete_now still present in shell: {shell_module}:{shell_function}"
                )
            continue

        if status == "python_partial_keep_temporarily":
            coverage_missing: list[str] = []
            owner_module = str(raw.get("python_owner_module", "")).strip()
            if not owner_module:
                coverage_missing.append("python_owner_module")

            if isinstance(evidence_tests, list):
                if not evidence_tests:
                    coverage_missing.append("evidence_tests_empty")
                else:
                    missing_evidence = _missing_evidence_paths(repo_root, evidence_tests)
                    if missing_evidence:
                        coverage_missing.append("missing_evidence_tests:" + ",".join(missing_evidence))
            else:
                coverage_missing.append("evidence_tests_invalid")

            if coverage_missing:
                partial_keep_uncovered_count += 1
                warnings.append(
                    f"entries[{index}] partial_keep coverage missing: {';'.join(coverage_missing)}"
                )
            else:
                partial_keep_covered_count += 1

        if not shell_path.is_file():
            errors.append(f"entries[{index}] shell module missing: {shell_module}")
            continue
        if shell_function not in functions:
            errors.append(
                f"entries[{index}] shell function missing from module: {shell_module}:{shell_function}"
            )

    for module in sorted(delete_now_modules):
        if module in source_modules:
            errors.append(f"deleted shell module still sourced by {ENGINE_MAIN_RELATIVE_PATH}: {module}")

    command_mappings = payload.get("command_mappings")
    mapped_commands: set[str] = set()
    if not isinstance(command_mappings, list):
        errors.append("shell ownership ledger command_mappings must be a list")
        command_mappings = []
    for index, raw in enumerate(command_mappings):
        if not isinstance(raw, dict):
            errors.append(f"command_mappings[{index}] must be an object")
            continue
        command = str(raw.get("command", "")).strip()
        owner_module = str(raw.get("python_owner_module", "")).strip()
        owner_symbol = str(raw.get("python_owner_symbol", "")).strip()
        evidence_tests = raw.get("evidence_tests")
        if not command:
            errors.append(f"command_mappings[{index}] command must be non-empty")
            continue
        if not owner_module or not owner_symbol:
            errors.append(f"command_mappings[{index}] owner module/symbol must be non-empty")
            continue
        if not isinstance(evidence_tests, list) or not evidence_tests:
            errors.append(f"command_mappings[{index}] evidence_tests must be a non-empty list")
            continue
        mapped_commands.add(command)

    if enforce_manifest_coverage:
        required_commands = python_complete_commands(repo_root)
        missing_commands = sorted(required_commands.difference(mapped_commands))
        if missing_commands:
            errors.append("python_complete command mapping missing: " + ", ".join(missing_commands))

    unmigrated_count = int(status_counts.get("unmigrated", 0))
    if max_unmigrated is not None:
        if unmigrated_count > max_unmigrated:
            phase_text = f" for phase {phase}" if phase else ""
            errors.append(
                "unmigrated entries exceed budget"
                f"{phase_text}: {unmigrated_count} > {max_unmigrated}"
            )
    elif unmigrated_count > 0:
        warnings.append(f"unmigrated shell entries remain: {unmigrated_count}")

    partial_keep_count = int(status_counts.get("python_partial_keep_temporarily", 0))
    if str(phase or "").strip().lower() == "cutover":
        partial_keep_budget_actual = int(partial_keep_count)
        partial_keep_budget_basis = "total"
    else:
        partial_keep_budget_actual = int(partial_keep_uncovered_count)
        partial_keep_budget_basis = "uncovered"
    if max_partial_keep is not None:
        if partial_keep_budget_actual > max_partial_keep:
            phase_text = f" for phase {phase}" if phase else ""
            errors.append(
                "partial_keep entries exceed budget"
                f"{phase_text}: {partial_keep_budget_actual} > {max_partial_keep}"
            )
    elif partial_keep_count > 0:
        warnings.append(
            "partial_keep shell entries remain: "
            f"{partial_keep_count} (covered={partial_keep_covered_count}, "
            f"uncovered={partial_keep_uncovered_count}, "
            f"budget_actual={partial_keep_budget_actual}, "
            f"budget_basis={partial_keep_budget_basis})"
        )

    intentional_keep_count = int(status_counts.get("shell_intentional_keep", 0))
    intentional_keep_budget_actual = int(intentional_keep_count)
    if max_intentional_keep is not None:
        if intentional_keep_budget_actual > max_intentional_keep:
            phase_text = f" for phase {phase}" if phase else ""
            errors.append(
                "intentional_keep entries exceed budget"
                f"{phase_text}: {intentional_keep_budget_actual} > {max_intentional_keep}"
            )
    elif intentional_keep_count > 0:
        warnings.append(f"intentional_keep shell entries remain: {intentional_keep_count}")

    return ShellPruneContractResult(
        passed=not errors,
        ledger_exists=True,
        ledger_path=ledger_path,
        ledger_generated_at=generated_at,
        ledger_hash=digest,
        status_counts=status_counts,
        missing_python_complete_commands=missing_commands,
        partial_keep_covered_count=partial_keep_covered_count,
        partial_keep_uncovered_count=partial_keep_uncovered_count,
        partial_keep_budget_actual=partial_keep_budget_actual,
        partial_keep_budget_basis=partial_keep_budget_basis,
        intentional_keep_budget_actual=intentional_keep_budget_actual,
        max_unmigrated=max_unmigrated,
        max_partial_keep=max_partial_keep,
        max_intentional_keep=max_intentional_keep,
        phase=phase,
        errors=errors,
        warnings=warnings,
    )


def discover_sourced_shell_modules(repo_root: Path) -> set[str]:
    main_path = repo_root / ENGINE_MAIN_RELATIVE_PATH
    if not main_path.is_file():
        return set()
    modules: set[str] = set()
    for raw_line in main_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _LIB_SOURCE_PATTERN.match(line)
        if match:
            modules.add(str(Path("lib/engine/lib") / match.group(1)))
            continue
        match = _SCRIPT_LIB_SOURCE_PATTERN.match(line)
        if match:
            modules.add(str(Path("lib/engine/lib") / match.group(1)))
    return modules


def parse_shell_functions(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    functions: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = _FUNCTION_PATTERN.match(raw_line)
        if match:
            functions.add(match.group(1))
    return functions


def _list_shell_modules_from_repo(repo_root: Path) -> list[str]:
    lib_dir = repo_root / "lib" / "engine" / "lib"
    if not lib_dir.is_dir():
        return []
    return sorted(
        str(path.relative_to(repo_root)).replace("\\", "/")
        for path in lib_dir.glob("*.sh")
        if path.is_file()
    )


def list_shell_modules_from_main(repo_root: Path) -> list[str]:
    modules = sorted(discover_sourced_shell_modules(repo_root))
    if modules:
        return modules
    return _list_shell_modules_from_repo(repo_root)


def python_complete_commands(repo_root: Path) -> set[str]:
    manifest_path = repo_root / PARITY_MANIFEST_RELATIVE_PATH
    if not manifest_path.is_file():
        return set()
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(payload, dict):
        return set()
    commands: set[str] = set()

    raw_commands = payload.get("commands")
    if isinstance(raw_commands, dict):
        for command, status in raw_commands.items():
            if str(status) == "python_complete":
                commands.add(str(command))

    raw_modes = payload.get("modes")
    if isinstance(raw_modes, dict):
        for mode_payload in raw_modes.values():
            if not isinstance(mode_payload, dict):
                continue
            for command, status in mode_payload.items():
                if str(status) == "python_complete":
                    commands.add(str(command))
    return commands


def summarize_unmigrated_entries(repo_root: Path, *, limit: int = 50) -> list[dict[str, str]]:
    payload = load_shell_ownership_ledger(repo_root)
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return []
    selected: list[dict[str, str]] = []
    for raw in entries:
        if not isinstance(raw, dict):
            continue
        status = str(raw.get("status", ""))
        if status not in {"unmigrated", "shell_intentional_keep", "python_partial_keep_temporarily"}:
            continue
        selected.append(
            {
                "status": status,
                "shell_module": str(raw.get("shell_module", "")),
                "shell_function": str(raw.get("shell_function", "")),
                "python_owner_module": str(raw.get("python_owner_module", "")),
                "python_owner_symbol": str(raw.get("python_owner_symbol", "")),
            }
        )
        if len(selected) >= max(limit, 0):
            break
    return selected


def iter_module_functions(repo_root: Path, modules: Iterable[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for module in modules:
        module_path = repo_root / module
        for function_name in sorted(parse_shell_functions(module_path)):
            pairs.append((module, function_name))
    return pairs


def _missing_evidence_paths(repo_root: Path, evidence_tests: list[object]) -> list[str]:
    missing: list[str] = []
    for raw in evidence_tests:
        text = str(raw).strip()
        if not text:
            continue
        if not (repo_root / text).is_file():
            missing.append(text)
    return missing
