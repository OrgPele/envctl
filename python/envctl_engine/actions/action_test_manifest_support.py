from __future__ import annotations

import ast
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Sequence

from envctl_engine.test_output.parser_pytest import PytestOutputParser


@dataclass(frozen=True)
class FailedTestManifestEntry:
    source: str
    suite: str
    failed_tests: tuple[str, ...]
    failed_files: tuple[str, ...]
    invalid_failed_tests: int = 0


@dataclass(frozen=True)
class FailedTestManifest:
    generated_at: str
    head: str
    status_hash: str
    status_lines: int
    entries: tuple[FailedTestManifestEntry, ...]


def sanitize_failed_test_identifiers(*, source: str, failed_tests: Sequence[str]) -> tuple[tuple[str, ...], int]:
    if source not in {"backend_pytest", "root_pytest"}:
        if source == "root_unittest":
            kept: list[str] = []
            invalid = 0
            seen: set[str] = set()
            for raw in failed_tests:
                candidate = normalize_unittest_test_identifier(str(raw).strip())
                if not candidate:
                    invalid += 1
                    continue
                if candidate in seen:
                    continue
                seen.add(candidate)
                kept.append(candidate)
            return tuple(kept), invalid
        normalized = tuple(str(value).strip() for value in failed_tests if str(value).strip())
        return normalized, 0
    kept: list[str] = []
    invalid = 0
    seen: set[str] = set()
    for raw in failed_tests:
        candidate = str(raw).strip()
        if not candidate:
            continue
        if not PytestOutputParser._is_valid_pytest_nodeid(candidate):
            invalid += 1
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        kept.append(candidate)
    return tuple(kept), invalid


_UNITTEST_TEST_ID_RE = r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+"


def normalize_unittest_test_identifier(raw: str) -> str | None:
    candidate = str(raw).strip()
    if not candidate:
        return None
    if re.fullmatch(_UNITTEST_TEST_ID_RE, candidate):
        return candidate
    display_match = re.fullmatch(rf"[^()]+\s+\(({_UNITTEST_TEST_ID_RE})\)", candidate)
    if display_match:
        return display_match.group(1)
    return None


def resolve_unittest_test_identifier_for_project(raw: str, project_root: Path) -> str | None:
    candidate = normalize_unittest_test_identifier(raw)
    if not candidate:
        return None
    tests_root = project_root / "tests"
    if not tests_root.is_dir():
        return candidate
    if _unittest_identifier_exists_for_project(candidate, project_root):
        return candidate
    prefixed = f"tests.{candidate}"
    if _unittest_identifier_exists_for_project(prefixed, project_root):
        return prefixed
    return None


def _unittest_identifier_exists_for_project(identifier: str, project_root: Path) -> bool:
    parts = [part for part in str(identifier).split(".") if part]
    if len(parts) < 3:
        return False
    module_parts = parts[:-2]
    class_name = parts[-2]
    method_name = parts[-1]
    if not module_parts:
        return False
    module_path = project_root.joinpath(*module_parts)
    file_path = module_path.with_suffix(".py")
    if not file_path.is_file():
        init_path = module_path / "__init__.py"
        if not init_path.is_file():
            return False
        file_path = init_path
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return False
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == method_name:
                    return True
            return False
    return False


def load_failed_test_manifest(path: Path) -> FailedTestManifest | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    entries_raw = payload.get("entries")
    if not isinstance(entries_raw, list):
        return None
    entries: list[FailedTestManifestEntry] = []
    for raw_entry in entries_raw:
        if not isinstance(raw_entry, dict):
            continue
        source = str(raw_entry.get("source", "") or "").strip()
        suite = str(raw_entry.get("suite", "") or "").strip()
        sanitized_failed_tests, invalid_failed_tests = sanitize_failed_test_identifiers(
            source=source,
            failed_tests=[
                value.strip() for value in raw_entry.get("failed_tests", []) if isinstance(value, str) and value.strip()
            ],
        )
        raw_failed_files = [
            value.strip() for value in raw_entry.get("failed_files", []) if isinstance(value, str) and value.strip()
        ]
        if source in {"frontend_package_test", "package_test"}:
            derived_failed_files = frontend_failed_files_from_failed_tests(sanitized_failed_tests)
            merged_failed_files: list[str] = []
            seen_failed_files: set[str] = set()
            for failed_file in [*raw_failed_files, *derived_failed_files]:
                if failed_file in seen_failed_files:
                    continue
                seen_failed_files.add(failed_file)
                merged_failed_files.append(failed_file)
            failed_files = tuple(merged_failed_files)
        else:
            failed_files = tuple(raw_failed_files)
        if not source or (not sanitized_failed_tests and not failed_files):
            continue
        entries.append(
            FailedTestManifestEntry(
                source=source,
                suite=suite,
                failed_tests=sanitized_failed_tests,
                failed_files=failed_files,
                invalid_failed_tests=invalid_failed_tests,
            )
        )
    return FailedTestManifest(
        generated_at=str(payload.get("generated_at", "") or ""),
        head=str(payload.get("git_state", {}).get("head", "") or "")
        if isinstance(payload.get("git_state"), dict)
        else "",
        status_hash=(
            str(payload.get("git_state", {}).get("status_hash", "") or "")
            if isinstance(payload.get("git_state"), dict)
            else ""
        ),
        status_lines=(
            int(payload.get("git_state", {}).get("status_lines", 0) or 0)
            if isinstance(payload.get("git_state"), dict)
            else 0
        ),
        entries=tuple(entries),
    )


def frontend_failed_files_from_failed_tests(failed_tests: Sequence[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in failed_tests:
        text = str(raw).strip()
        if not text:
            continue
        file_name = text.split("::", 1)[0].strip()
        if not file_name or file_name in seen:
            continue
        seen.add(file_name)
        ordered.append(file_name)
    return ordered
