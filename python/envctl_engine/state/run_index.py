from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from envctl_engine.state.fingerprints import file_fingerprint
from envctl_engine.state.persistence import (
    advisory_file_lock,
    atomic_write_text,
    durable_mkdir,
    require_path_component,
    scavenge_atomic_write_temps,
)


_INDEX_VERSION = 4


def _normalize_mode(mode: str | None) -> str | None:
    normalized = str(mode or "").strip().casefold()
    return normalized or None


def _normalize_project_names(project_names: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted({name.strip().casefold() for name in project_names if name.strip()}))


@dataclass(frozen=True, slots=True)
class StateSelector:
    mode: str | None
    project_names: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", _normalize_mode(self.mode))
        object.__setattr__(self, "project_names", _normalize_project_names(self.project_names))


@dataclass(frozen=True, slots=True)
class RunIndexCandidate:
    state_path: Path
    run_id: str
    mode: str
    project_names: tuple[str, ...]
    sequence: int
    state_fingerprint: str = ""
    runtime_map_fingerprint: str | None = None
    activation_sequence: int = 0


@dataclass(frozen=True, slots=True)
class _RegistrySnapshot:
    generation: int
    entries: tuple[RunIndexCandidate, ...]
    retired_run_ids: frozenset[str]


class RunIndex:
    """Selection-aware registry of active project ownership by run artifact."""

    def __init__(self, *, runtime_root: Path, runtime_dir: Path, runtime_scope_id: str) -> None:
        self._input_runtime_root = runtime_root.absolute()
        if self._input_runtime_root.is_symlink():
            raise ValueError("runtime_root must not be a symlink")
        self.runtime_dir = runtime_dir.resolve()
        self.runtime_root = runtime_root.resolve()
        self.runtime_scope_id = runtime_scope_id.strip()
        if not self.runtime_scope_id:
            raise ValueError("runtime_scope_id must not be empty")
        if not self._is_within_runtime_dir(self.runtime_root):
            raise ValueError("runtime_root must be contained by runtime_dir")
        self.index_path = self.runtime_root / "run_index.json"
        self.backup_path = self.runtime_root / "run_index.backup.json"
        self._lock_path = self.runtime_root / ".run_index.lock"
        self._runtime_root_identity = self._existing_directory_identity()

    def record(
        self,
        *,
        state_path: Path,
        run_id: str,
        mode: str,
        project_names: Sequence[str],
        supersede_run_ids: Sequence[str] = (),
    ) -> None:
        normalized_run_id = require_path_component(run_id, label="run_id")
        resolved_state_path = self._validated_revision_state_path(state_path, run_id=normalized_run_id)
        normalized_mode = _normalize_mode(mode)
        if normalized_mode is None:
            raise ValueError("mode must not be empty")
        normalized_projects = _normalize_project_names(project_names)
        state_fingerprint = file_fingerprint(resolved_state_path)
        runtime_map_path = resolved_state_path.parent / "runtime_map.json"
        runtime_map_fingerprint = (
            file_fingerprint(runtime_map_path)
            if runtime_map_path.is_file() and not runtime_map_path.is_symlink()
            else None
        )
        superseded = {
            require_path_component(candidate_run_id, label="superseded run_id")
            for candidate_run_id in supersede_run_ids
        }
        superseded.discard(normalized_run_id)

        with self._lock(exclusive=True):
            snapshot = self._read_registry()
            entries = list(snapshot.entries) if snapshot is not None else []
            retired_run_ids = set(snapshot.retired_run_ids) if snapshot is not None else set()
            if normalized_run_id in retired_run_ids:
                raise RuntimeError(f"run_id is retired and cannot publish new state: {normalized_run_id}")
            latest_sequence = max((entry.sequence for entry in entries), default=0)
            latest_activation_sequence = max(
                (entry.activation_sequence for entry in entries),
                default=0,
            )
            existing_entry = next((entry for entry in entries if entry.run_id == normalized_run_id), None)
            if not normalized_projects and existing_entry is not None:
                normalized_projects = existing_entry.project_names
            entries = [
                entry for entry in entries if entry.run_id != normalized_run_id and entry.run_id not in superseded
            ]
            retired_run_ids.update(superseded)
            entries = self._subtract_replaced_project_owners(
                entries,
                mode=normalized_mode,
                project_names=normalized_projects,
                retired_run_ids=retired_run_ids,
            )
            sequence = existing_entry.sequence if existing_entry is not None else latest_sequence + 1
            activates_current_mode = existing_entry is None or self._entry_owns_any_project(
                existing_entry,
                entries,
                normalized_projects,
            )
            activation_sequence = (
                latest_activation_sequence + 1 if activates_current_mode else existing_entry.activation_sequence
            )
            entries.append(
                RunIndexCandidate(
                    state_path=resolved_state_path,
                    run_id=normalized_run_id,
                    mode=normalized_mode,
                    project_names=normalized_projects,
                    sequence=sequence,
                    state_fingerprint=state_fingerprint,
                    runtime_map_fingerprint=runtime_map_fingerprint,
                    activation_sequence=activation_sequence,
                )
            )
            self._write_entries(entries, retired_run_ids=retired_run_ids)

    @staticmethod
    def _subtract_replaced_project_owners(
        entries: Sequence[RunIndexCandidate],
        *,
        mode: str,
        project_names: Sequence[str],
        retired_run_ids: set[str],
    ) -> list[RunIndexCandidate]:
        replaced_projects = frozenset(project_names)
        if not replaced_projects:
            return list(entries)

        retained: list[RunIndexCandidate] = []
        for entry in entries:
            if entry.mode != mode or replaced_projects.isdisjoint(entry.project_names):
                retained.append(entry)
                continue
            remaining_projects = tuple(project for project in entry.project_names if project not in replaced_projects)
            if remaining_projects:
                retained.append(replace(entry, project_names=remaining_projects))
            else:
                retired_run_ids.add(entry.run_id)
        return retained

    def remove(self, run_id: str) -> bool:
        return self.remove_many([run_id])

    def remove_many(self, run_ids: Sequence[str]) -> bool:
        normalized_run_ids = {require_path_component(run_id, label="run_id") for run_id in run_ids}
        with self._lock(exclusive=True):
            snapshot = self._read_registry()
            entries = list(snapshot.entries) if snapshot is not None else []
            retired_run_ids = set(snapshot.retired_run_ids) if snapshot is not None else set()
            retained = [entry for entry in entries if entry.run_id not in normalized_run_ids]
            removed_active_entry = len(retained) != len(entries)
            added_tombstone = not normalized_run_ids.issubset(retired_run_ids)
            if not removed_active_entry and not added_tombstone:
                return False
            retired_run_ids.update(normalized_run_ids)
            self._write_entries(retained, retired_run_ids=retired_run_ids)
            return removed_active_entry

    def candidates(self, selector: StateSelector) -> list[RunIndexCandidate]:
        with self._lock(exclusive=False):
            entries = self._read_entries()
        if entries is None:
            return []

        selected_projects = frozenset(selector.project_names)
        ranked: list[tuple[int, int, str, RunIndexCandidate]] = []
        for entry in entries:
            if selector.mode is not None and entry.mode != selector.mode:
                continue
            relation_rank = self._selection_rank(
                indexed=frozenset(entry.project_names),
                selected=selected_projects,
            )
            if relation_rank is None:
                continue
            ranked.append((-entry.sequence, relation_rank, str(entry.state_path), entry))
        ranked.sort(key=lambda item: (item[0], item[1], item[2]))
        return [entry for _, _, _, entry in ranked]

    def candidate_paths(self, selector: StateSelector) -> list[Path]:
        return [candidate.state_path for candidate in self.candidates(selector)]

    def purge(self) -> None:
        with self._lock(exclusive=True):
            snapshot = self._read_registry()
            retired_run_ids = set(snapshot.retired_run_ids) if snapshot is not None else set()
            if snapshot is not None:
                retired_run_ids.update(entry.run_id for entry in snapshot.entries)
            self._write_entries([], retired_run_ids=retired_run_ids)

    def needs_rebuild(self) -> bool:
        with self._lock(exclusive=False):
            return self._read_snapshot(self.index_path) is None and self._read_snapshot(self.backup_path) is None

    def repair_copies(self) -> None:
        with self._lock(exclusive=True):
            primary = self._read_snapshot(self.index_path)
            backup = self._read_snapshot(self.backup_path)
            if primary is not None and backup is not None and primary == backup:
                return
            snapshot = self._read_registry()
            if snapshot is not None:
                self._write_entries(
                    list(snapshot.entries),
                    retired_run_ids=set(snapshot.retired_run_ids),
                )

    def initialize_empty(self) -> None:
        with self._lock(exclusive=True):
            self._write_entries([], retired_run_ids=set())

    def replace_all(self, entries: Sequence[RunIndexCandidate]) -> None:
        with self._lock(exclusive=True):
            self._write_entries(
                [self._candidate_with_fingerprints(entry) for entry in entries],
                retired_run_ids=set(),
            )

    @staticmethod
    def _selection_rank(*, indexed: frozenset[str], selected: frozenset[str]) -> int | None:
        if not selected:
            return 0
        if not indexed:
            return None
        if indexed == selected:
            return 0
        if indexed.issuperset(selected):
            return 1
        if indexed.issubset(selected):
            return 2
        if indexed.intersection(selected):
            return 3
        return None

    @staticmethod
    def _entry_owns_any_project(
        existing_entry: RunIndexCandidate,
        other_entries: Sequence[RunIndexCandidate],
        updated_projects: Sequence[str],
    ) -> bool:
        if not updated_projects:
            return True
        for project in updated_projects:
            if not any(
                other.mode == existing_entry.mode
                and other.sequence > existing_entry.sequence
                and project in other.project_names
                for other in other_entries
            ):
                return True
        return False

    @contextmanager
    def _lock(self, *, exclusive: bool) -> Iterator[None]:
        self._validate_runtime_root()
        with advisory_file_lock(self._lock_path, exclusive=exclusive):
            self._validate_runtime_root()
            yield

    def _existing_directory_identity(self) -> tuple[int, int] | None:
        if not self.runtime_root.exists():
            return None
        if self.runtime_root.is_symlink() or not self.runtime_root.is_dir():
            raise ValueError(f"runtime_root is not a real directory: {self.runtime_root}")
        metadata = self.runtime_root.stat()
        return metadata.st_dev, metadata.st_ino

    def _validate_runtime_root(self) -> None:
        if self.runtime_root.is_symlink() or self.runtime_root.resolve(strict=False) != self.runtime_root:
            raise RuntimeError(f"runtime_root changed identity or became a symlink: {self.runtime_root}")
        durable_mkdir(self.runtime_root)
        metadata = self.runtime_root.stat()
        current = metadata.st_dev, metadata.st_ino
        if self._runtime_root_identity is not None and current != self._runtime_root_identity:
            raise RuntimeError(f"runtime_root changed identity: {self.runtime_root}")
        self._runtime_root_identity = current

    def _read_entries(self) -> list[RunIndexCandidate] | None:
        snapshot = self._read_registry()
        return list(snapshot.entries) if snapshot is not None else None

    def _read_registry(self) -> _RegistrySnapshot | None:
        primary = self._read_snapshot(self.index_path)
        backup = self._read_snapshot(self.backup_path)
        self._reject_equal_generation_divergence(primary, backup)
        snapshots = [snapshot for snapshot in (primary, backup) if snapshot is not None]
        if not snapshots:
            return None
        return max(snapshots, key=lambda snapshot: snapshot.generation)

    @staticmethod
    def _reject_equal_generation_divergence(
        primary: _RegistrySnapshot | None,
        backup: _RegistrySnapshot | None,
    ) -> None:
        if primary is not None and backup is not None and primary.generation == backup.generation and primary != backup:
            raise RuntimeError(
                "Run registry primary and backup diverged at generation "
                f"{primary.generation}; refusing to choose one copy"
            )

    def _read_snapshot(self, path: Path) -> _RegistrySnapshot | None:
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            generation = payload.get("generation") if isinstance(payload, dict) else None
            if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
                return None
            entries = self._parse_payload(payload)
            raw_retired = payload.get("retired_run_ids")
            if not isinstance(raw_retired, list) or not all(isinstance(run_id, str) for run_id in raw_retired):
                return None
            retired = frozenset(require_path_component(run_id, label="retired run_id") for run_id in raw_retired)
            if retired.intersection(entry.run_id for entry in entries):
                return None
            return _RegistrySnapshot(generation, tuple(entries), retired)
        except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def _parse_payload(self, payload: Any) -> list[RunIndexCandidate]:
        if not isinstance(payload, dict):
            raise ValueError("run index must be a JSON object")
        version = payload.get("version")
        if version not in {2, 3, _INDEX_VERSION}:
            raise ValueError("unsupported run index version")
        if payload.get("runtime_scope_id") != self.runtime_scope_id:
            raise ValueError("run index scope does not match this repository")
        raw_entries = payload.get("entries")
        if not isinstance(raw_entries, list):
            raise ValueError("run index entries must be a list")

        entries: list[RunIndexCandidate] = []
        seen_run_ids: set[str] = set()
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, dict) or raw_entry.get("runtime_scope_id") != self.runtime_scope_id:
                raise ValueError("invalid run index entry scope")
            run_id = raw_entry.get("run_id")
            mode = _normalize_mode(raw_entry.get("mode") if isinstance(raw_entry.get("mode"), str) else None)
            raw_projects = raw_entry.get("project_names")
            sequence = raw_entry.get("sequence")
            raw_state_path = raw_entry.get("state_path")
            raw_state_fingerprint = raw_entry.get("state_fingerprint")
            raw_runtime_map_fingerprint = raw_entry.get("runtime_map_fingerprint")
            raw_activation_sequence = raw_entry.get("activation_sequence")
            if (
                not isinstance(run_id, str)
                or not run_id.strip()
                or mode is None
                or not isinstance(raw_projects, list)
                or not all(isinstance(project, str) for project in raw_projects)
                or not isinstance(sequence, int)
                or isinstance(sequence, bool)
                or sequence < 1
                or not isinstance(raw_state_path, str)
                or not raw_state_path.strip()
            ):
                raise ValueError("invalid run index entry")
            normalized_run_id = require_path_component(run_id, label="indexed run_id")
            if normalized_run_id in seen_run_ids:
                raise ValueError("duplicate run id in run index")
            state_path = self._validated_revision_state_path(Path(raw_state_path), run_id=normalized_run_id)
            if version == 2:
                state_fingerprint = file_fingerprint(state_path)
                runtime_map_path = state_path.parent / "runtime_map.json"
                runtime_map_fingerprint = (
                    file_fingerprint(runtime_map_path)
                    if runtime_map_path.is_file() and not runtime_map_path.is_symlink()
                    else None
                )
            else:
                if not self._valid_fingerprint(raw_state_fingerprint) or (
                    raw_runtime_map_fingerprint is not None and not self._valid_fingerprint(raw_runtime_map_fingerprint)
                ):
                    raise ValueError("invalid run index artifact fingerprint")
                state_fingerprint = str(raw_state_fingerprint)
                runtime_map_fingerprint = (
                    str(raw_runtime_map_fingerprint) if raw_runtime_map_fingerprint is not None else None
                )
            if version in {2, 3}:
                activation_sequence = sequence
            elif (
                not isinstance(raw_activation_sequence, int)
                or isinstance(raw_activation_sequence, bool)
                or raw_activation_sequence < 1
            ):
                raise ValueError("invalid run index activation sequence")
            else:
                activation_sequence = raw_activation_sequence
            seen_run_ids.add(normalized_run_id)
            entries.append(
                RunIndexCandidate(
                    state_path=state_path,
                    run_id=normalized_run_id,
                    mode=mode,
                    project_names=_normalize_project_names(raw_projects),
                    sequence=sequence,
                    state_fingerprint=state_fingerprint,
                    runtime_map_fingerprint=runtime_map_fingerprint,
                    activation_sequence=activation_sequence,
                )
            )
        return entries

    def _write_entries(
        self,
        entries: list[RunIndexCandidate],
        *,
        retired_run_ids: set[str],
    ) -> None:
        primary = self._read_snapshot(self.index_path)
        backup = self._read_snapshot(self.backup_path)
        self._reject_equal_generation_divergence(primary, backup)
        existing_generations = [snapshot.generation for snapshot in (primary, backup) if snapshot is not None]
        payload = {
            "version": _INDEX_VERSION,
            "generation": max(existing_generations, default=0) + 1,
            "runtime_scope_id": self.runtime_scope_id,
            "retired_run_ids": sorted(retired_run_ids),
            "entries": [
                {
                    "state_path": str(entry.state_path),
                    "run_id": entry.run_id,
                    "mode": entry.mode,
                    "project_names": list(entry.project_names),
                    "sequence": entry.sequence,
                    "state_fingerprint": entry.state_fingerprint,
                    "runtime_map_fingerprint": entry.runtime_map_fingerprint,
                    "activation_sequence": entry.activation_sequence,
                    "runtime_scope_id": self.runtime_scope_id,
                }
                for entry in entries
            ],
        }
        text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        errors: list[OSError] = []
        successful_writes = 0
        for path in (self.backup_path, self.index_path):
            try:
                scavenge_atomic_write_temps(path)
                atomic_write_text(path, text)
                successful_writes += 1
            except OSError as exc:
                errors.append(exc)
        expected = _RegistrySnapshot(
            generation=payload["generation"],
            entries=tuple(entries),
            retired_run_ids=frozenset(retired_run_ids),
        )
        if any(self._read_snapshot(path) == expected for path in (self.index_path, self.backup_path)):
            return
        if errors:
            raise errors[0]
        if successful_writes:
            raise RuntimeError("run registry write returned without publishing the expected generation")

    def _validated_revision_state_path(self, state_path: Path, *, run_id: str) -> Path:
        if not state_path.is_absolute():
            raise ValueError("indexed state_path must be absolute")
        resolved = state_path.resolve()
        try:
            relative = resolved.relative_to(self.runtime_root)
        except ValueError as exc:
            raise ValueError("indexed state_path escapes runtime_root") from exc
        parts = relative.parts
        if len(parts) != 5 or parts[0] != "runs" or parts[1] != run_id or parts[2] != "revisions":
            raise ValueError("indexed state_path must identify a run revision")
        _ = require_path_component(parts[3], label="revision id")
        if parts[4] != "run_state.json":
            raise ValueError("indexed state_path must identify run_state.json")
        if ".." in state_path.parts or state_path.is_symlink():
            raise ValueError("indexed state_path must be canonical and must not traverse symlinks")
        lexical_relative: Path | None = None
        lexical_root: Path | None = None
        for candidate_root in (self._input_runtime_root, self.runtime_root):
            try:
                lexical_relative = state_path.relative_to(candidate_root)
                lexical_root = candidate_root
                break
            except ValueError:
                continue
        if lexical_relative is None or lexical_root is None:
            raise ValueError("indexed state_path must be canonical and must not traverse symlinks")
        lexical_parent = lexical_root
        for component in lexical_relative.parts[:-1]:
            lexical_parent /= component
            if lexical_parent.is_symlink():
                raise ValueError("indexed state_path must be canonical and must not traverse symlinks")
        for parent in (
            self.runtime_root / "runs",
            self.runtime_root / "runs" / run_id,
            self.runtime_root / "runs" / run_id / "revisions",
            resolved.parent,
        ):
            if parent.is_symlink():
                raise ValueError("indexed state_path must not traverse symlinks")
        if not self._is_within_runtime_root(resolved):
            raise ValueError("indexed state_path must be canonical inside runtime_root")
        return resolved

    def _candidate_with_fingerprints(self, entry: RunIndexCandidate) -> RunIndexCandidate:
        state_path = self._validated_revision_state_path(entry.state_path, run_id=entry.run_id)
        runtime_map_path = state_path.parent / "runtime_map.json"
        return RunIndexCandidate(
            state_path=state_path,
            run_id=entry.run_id,
            mode=entry.mode,
            project_names=entry.project_names,
            sequence=entry.sequence,
            state_fingerprint=entry.state_fingerprint or file_fingerprint(state_path),
            runtime_map_fingerprint=(
                entry.runtime_map_fingerprint
                if entry.runtime_map_fingerprint is not None
                else (
                    file_fingerprint(runtime_map_path)
                    if runtime_map_path.is_file() and not runtime_map_path.is_symlink()
                    else None
                )
            ),
            activation_sequence=entry.activation_sequence or entry.sequence,
        )

    @staticmethod
    def _valid_fingerprint(value: object) -> bool:
        return (
            isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)
        )

    def _is_within_runtime_dir(self, path: Path) -> bool:
        try:
            path.relative_to(self.runtime_dir)
        except ValueError:
            return False
        return True

    def _is_within_runtime_root(self, path: Path) -> bool:
        try:
            path.relative_to(self.runtime_root)
        except ValueError:
            return False
        return True


__all__ = ["RunIndex", "RunIndexCandidate", "StateSelector"]
