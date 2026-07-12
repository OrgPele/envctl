from __future__ import annotations

import json
import shutil
import stat
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, cast

from envctl_engine.dashboard_metadata import DASHBOARD_STOPPED_SERVICES_KEY
from envctl_engine.shared.artifact_names import safe_artifact_stem
from envctl_engine.state import load_legacy_shell_state, load_state, load_state_from_pointer, state_to_dict
from envctl_engine.state.fingerprints import file_fingerprint, state_fingerprint, text_fingerprint
from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.state.persistence import (
    advisory_file_lock,
    atomic_write_text,
    durable_mkdir,
    fsync_directory,
    require_path_component,
    scavenge_atomic_write_temps,
)
from envctl_engine.state.project_runtime import filter_project_scoped_metadata
from envctl_engine.state.run_index import RunIndex, RunIndexCandidate, StateSelector
from envctl_engine.state.runtime_map import build_runtime_map
from envctl_engine.state.state_aggregation import (
    IndexedState as _IndexedState,
    filter_state_to_owned_projects,
    normalized_project_names,
    select_indexed_owners,
    state_from_indexed_owners,
)


@dataclass(slots=True)
class StateRepositoryPaths:
    run_dir: Path
    run_state: Path


class RuntimeStateRepository:
    COMPAT_READ_WRITE: str = "compat_read_write"
    COMPAT_READ_ONLY: str = "compat_read_only"
    SCOPED_ONLY: str = "scoped_only"
    _RUNTIME_ARTIFACT_NAMES = frozenset(
        {
            "events.jsonl",
            "runtime_readiness_report.json",
        }
    )
    _REVISION_ANCILLARY_ARTIFACT_NAMES = (
        "ports_manifest.json",
        "error_report.json",
        "events.jsonl",
        "runtime_readiness_report.json",
    )
    _RUN_ALIAS_ARTIFACT_NAMES = (
        "run_state.json",
        "runtime_map.json",
        *_REVISION_ANCILLARY_ARTIFACT_NAMES,
    )
    _RUN_ALIAS_MANIFEST_NAME = ".revision_alias_manifest.json"
    _REVISION_CLEANUP_DIR_NAME = ".revision-cleanup"

    def __init__(
        self,
        *,
        runtime_root: Path,
        runtime_legacy_root: Path,
        runtime_dir: Path,
        runtime_scope_id: str,
        compat_mode: str,
    ) -> None:
        input_runtime_root = runtime_root.expanduser().absolute()
        input_legacy_root = runtime_legacy_root.expanduser().absolute()
        if input_runtime_root.is_symlink() or input_legacy_root.is_symlink():
            raise ValueError("runtime roots must not be symlinks")
        self.runtime_dir: Path = runtime_dir.resolve()
        self.runtime_root: Path = runtime_root.resolve()
        self.runtime_legacy_root: Path = runtime_legacy_root.resolve()
        try:
            self.runtime_root.relative_to(self.runtime_dir)
            self.runtime_legacy_root.relative_to(self.runtime_dir)
        except ValueError as exc:
            raise ValueError("runtime roots must be contained by runtime_dir") from exc
        self.runtime_scope_id: str = runtime_scope_id
        self.compat_mode: str = (
            compat_mode
            if compat_mode
            in {
                self.COMPAT_READ_WRITE,
                self.COMPAT_READ_ONLY,
                self.SCOPED_ONLY,
            }
            else self.COMPAT_READ_WRITE
        )
        self.run_index = RunIndex(
            runtime_root=self.runtime_root,
            runtime_dir=self.runtime_dir,
            runtime_scope_id=self.runtime_scope_id,
        )
        self._lock_path = self.runtime_root / ".state_repository.lock"
        self._registry_marker_path = self.runtime_root / "run_registry.json"
        self._alias_manifest_path = self.runtime_root / "current_alias.json"
        self._runtime_root_identity = self._existing_directory_identity(self.runtime_root)
        self._legacy_root_identity = self._existing_directory_identity(self.runtime_legacy_root)

    def run_state_path(self) -> Path:
        return self.runtime_root / "run_state.json"

    def runtime_map_path(self) -> Path:
        return self.runtime_root / "runtime_map.json"

    def ports_manifest_path(self) -> Path:
        return self.runtime_root / "ports_manifest.json"

    def error_report_path(self) -> Path:
        return self.runtime_root / "error_report.json"

    def lifecycle_operation_lock_path(self) -> Path:
        self._validate_runtime_roots()
        return self.runtime_root / ".lifecycle_operation.lock"

    def ensure_runtime_roots(self) -> None:
        self._validate_runtime_roots()

    def run_dir_path(self, run_id: str | None) -> Path:
        runs_root = self._contained_child(self.runtime_root, "runs", label="runs directory")
        if run_id is None:
            return runs_root
        normalized_run_id = require_path_component(run_id, label="run_id")
        return self._contained_child(runs_root, normalized_run_id, label="run_id")

    def test_results_dir_path(self, run_id: str, stamp: str | None = None) -> Path:
        root = self._contained_child(self.run_dir_path(run_id), "test-results", label="test results directory")
        if not stamp:
            return root
        normalized_stamp = require_path_component(stamp, label="test result stamp")
        return self._contained_child(root, normalized_stamp, label="test result stamp")

    def tree_diffs_dir_path(self, run_id: str | None = None, name: str | None = None) -> Path:
        if run_id:
            root = self._contained_child(self.run_dir_path(run_id), "tree-diffs", label="tree diffs directory")
        else:
            root = self._contained_child(self.runtime_root, "tree-diffs", label="tree diffs directory")
        if not name:
            return root
        normalized_name = require_path_component(name, label="tree diff name")
        return self._contained_child(root, normalized_name, label="tree diff name")

    def save_run(
        self,
        *,
        state: RunState,
        contexts: list[object],
        errors: list[str],
        events: list[dict[str, object]],
        emit: Callable[..., None],
        runtime_map_builder: Callable[[RunState], dict[str, object]],
        write_runtime_readiness_report: Callable[[Path], None] | None = None,
        on_commit: Callable[[], None] | None = None,
    ) -> StateRepositoryPaths:
        project_names = sorted(
            {
                *self._context_names(contexts),
                *self._runtime_project_names_from_state(state),
            },
            key=str.casefold,
        )
        self._prepare_state_for_save(state, project_names=project_names, contexts=contexts)
        runtime_map = runtime_map_builder(state)
        artifacts = {
            "run_state.json": self._json_text(state_to_dict(state)),
            "runtime_map.json": self._json_text(runtime_map),
            "ports_manifest.json": self._json_text(
                {
                    "run_id": state.run_id,
                    "mode": state.mode,
                    "projects": [self._context_ports_payload(context) for context in contexts],
                }
            ),
            "error_report.json": self._json_text(
                {
                    "run_id": state.run_id,
                    "errors": errors,
                    "generated_at": datetime.now(tz=UTC).isoformat(),
                }
            ),
            "events.jsonl": self._events_text(events),
        }
        with self._repository_lock(exclusive=True):
            self._ensure_active_index_unlocked()
            self._carry_forward_runtime_artifacts_unlocked(state, artifacts)
            revision_state_path = self._commit_revision_unlocked(
                state=state,
                project_names=project_names,
                artifacts=artifacts,
                supersede_run_ids=self._source_run_ids(state),
                on_commit=on_commit,
            )
        run_dir = self.run_dir_path(state.run_id)
        if write_runtime_readiness_report is not None:
            try:
                write_runtime_readiness_report(run_dir)
            except Exception as exc:
                self._safe_emit(emit, "state.readiness_report.error", run_id=state.run_id, error=str(exc))
        self._emit_saved_state(
            emit,
            state=state,
            state_path=revision_state_path,
            runtime_map_text=artifacts["runtime_map.json"],
        )
        return StateRepositoryPaths(run_dir=run_dir, run_state=run_dir / "run_state.json")

    def save_resume_state(
        self,
        *,
        state: RunState,
        emit: Callable[..., None],
        runtime_map_builder: Callable[[RunState], dict[str, object]],
    ) -> dict[str, object]:
        return self._save_runtime_update(
            state=state,
            emit=emit,
            runtime_map_builder=runtime_map_builder,
        )

    def save_selected_stop_state(
        self,
        *,
        state: RunState,
        emit: Callable[..., None],
        runtime_map_builder: Callable[[RunState], dict[str, object]],
        authoritative_project_names: Sequence[str] | None = None,
    ) -> dict[str, object]:
        return self._save_runtime_update(
            state=state,
            emit=emit,
            runtime_map_builder=runtime_map_builder,
            authoritative_project_names=authoritative_project_names,
        )

    def load_latest(
        self,
        *,
        mode: str | None = None,
        strict_mode_match: bool = False,
        project_names: Sequence[str] | None = None,
    ) -> RunState | None:
        with self._repository_lock(exclusive=True):
            self._ensure_active_index_unlocked()
            self._reconcile_current_aliases_unlocked()
            return self._load_latest_unlocked(
                mode=mode,
                strict_mode_match=strict_mode_match,
                project_names=project_names,
            )

    def load_all(self, *, mode: str | None = None) -> list[RunState]:
        with self._repository_lock(exclusive=True):
            self._ensure_active_index_unlocked()
            self._reconcile_current_aliases_unlocked()
            candidates = self.run_index.candidates(StateSelector(mode=mode, project_names=()))
            indexed_states = self._load_valid_index_states(candidates, allowed_root=str(self.runtime_dir))
            if len(indexed_states) != len(candidates):
                invalid_run_ids = sorted(
                    {candidate.run_id for candidate in candidates}
                    - {indexed.candidate.run_id for indexed in indexed_states}
                )
                raise RuntimeError(
                    "Active runtime state failed integrity validation for run(s): " + ", ".join(invalid_run_ids)
                )
            active_states: list[RunState] = []
            for indexed_state in indexed_states:
                candidate_projects = normalized_project_names(indexed_state.candidate.project_names)
                active_states.append(
                    filter_state_to_owned_projects(
                        indexed_state.state,
                        candidate_projects,
                        service_project_name=self._service_project_name,
                        fallback_project=(
                            next(iter(candidate_projects)) if len(candidate_projects) == 1 else None
                        ),
                    )
                )
            return active_states

    def has_active_runs(self) -> bool:
        """Return registry activity without trusting or loading mutable run payloads."""

        with self._repository_lock(exclusive=True):
            self._ensure_active_index_unlocked()
            return bool(self.run_index.candidates(StateSelector(mode=None, project_names=())))

    def deactivate_run(self, run_id: str) -> bool:
        return self.deactivate_runs([run_id])

    def deactivate_runs(self, run_ids: Sequence[str]) -> bool:
        normalized_run_ids = {require_path_component(run_id, label="run_id") for run_id in run_ids}
        with self._repository_lock(exclusive=True):
            self._ensure_active_index_unlocked()
            candidates = self.run_index.candidates(StateSelector(mode=None, project_names=()))
            removed_candidates = [candidate for candidate in candidates if candidate.run_id in normalized_run_ids]
            if not removed_candidates:
                return False
            removed_run_ids = sorted({candidate.run_id for candidate in removed_candidates})
            self.run_index.remove_many(removed_run_ids)
            for candidate in removed_candidates:
                self._remove_pointers_to_state(self.runtime_root, candidate.state_path)
                if self.compat_mode == self.COMPAT_READ_WRITE:
                    self._remove_pointers_to_state(self.runtime_legacy_root, candidate.state_path)
            try:
                self._promote_latest_active_state()
            finally:
                for candidate in removed_candidates:
                    self._prune_or_enqueue_revision_cleanup_unlocked(candidate)
            return True

    def write_runtime_artifact(
        self,
        *,
        run_id: str | None,
        artifact_name: str,
        text: str,
    ) -> bool:
        """Persist a mutable runtime artifact without bypassing lifecycle fencing.

        Run-bound writers are accepted only while that exact run remains in the
        active registry. An unbound writer is a deliberate scope-level diagnostic
        write (for example, ``envctl doctor``) and is never guessed onto a run.
        """
        safe_artifact_name = require_path_component(artifact_name, label="runtime artifact name")
        if safe_artifact_name not in self._RUNTIME_ARTIFACT_NAMES:
            raise ValueError(f"unsupported mutable runtime artifact: {safe_artifact_name}")
        normalized_run_id = require_path_component(run_id, label="run_id") if run_id is not None else None

        with self._repository_lock(exclusive=True):
            self._ensure_active_index_unlocked()
            if normalized_run_id is None:
                candidates = self.run_index.candidates(StateSelector(mode=None, project_names=()))
                if candidates:
                    self._write_scope_diagnostic_artifact(safe_artifact_name, text)
                else:
                    self._remove_scope_diagnostic_artifact(safe_artifact_name)
                    self._write_scope_artifact_aliases(safe_artifact_name, text)
                return True

            candidates = self.run_index.candidates(StateSelector(mode=None, project_names=()))
            indexed_states = self._load_valid_index_states(
                candidates,
                allowed_root=str(self.runtime_dir),
            )
            indexed_state = next(
                (candidate for candidate in indexed_states if candidate.candidate.run_id == normalized_run_id),
                None,
            )
            if indexed_state is None:
                return False

            candidate = indexed_state.candidate
            self._write_text(candidate.state_path.parent / safe_artifact_name, text)
            self._write_text(self.run_dir_path(candidate.run_id) / safe_artifact_name, text)
            self._run_alias_manifest_path(candidate.run_id).unlink(missing_ok=True)
            self._promote_latest_active_state()
            return True

    def _write_scope_diagnostic_artifact(self, artifact_name: str, text: str) -> None:
        diagnostics_dir = self._contained_child(
            self.runtime_root,
            "diagnostics",
            label="diagnostics directory",
        )
        durable_mkdir(diagnostics_dir)
        self._write_text(diagnostics_dir / artifact_name, text)

    def _remove_scope_diagnostic_artifact(self, artifact_name: str) -> None:
        diagnostics_dir = self.runtime_root / "diagnostics"
        if diagnostics_dir.is_symlink() or not diagnostics_dir.is_dir():
            return
        (diagnostics_dir / artifact_name).unlink(missing_ok=True)
        try:
            diagnostics_dir.rmdir()
        except OSError:
            pass

    def _write_scope_artifact_aliases(self, artifact_name: str, text: str) -> None:
        self._write_text(self.runtime_root / artifact_name, text)
        if self.compat_mode == self.COMPAT_READ_WRITE:
            self._write_text(self.runtime_legacy_root / artifact_name, text)

    def _load_latest_unlocked(
        self,
        *,
        mode: str | None = None,
        strict_mode_match: bool = False,
        project_names: Sequence[str] | None = None,
    ) -> RunState | None:
        allowed_root = str(self.runtime_dir)
        selected_projects = tuple(project_names or ())

        def load_for_mode(expected_mode: str | None) -> RunState | None:
            candidates = self.run_index.candidates(StateSelector(mode=expected_mode, project_names=()))
            if expected_mode is None and candidates:
                valid_candidates = self._load_valid_index_states(
                    candidates,
                    allowed_root=allowed_root,
                )
                selected_project_keys = normalized_project_names(selected_projects)
                if selected_project_keys:
                    valid_candidates = [
                        indexed
                        for indexed in valid_candidates
                        if selected_project_keys.intersection(
                            normalized_project_names(
                                self._project_names_from_state(indexed.state)
                            )
                        )
                    ]
                if not valid_candidates:
                    return None
                newest_mode = max(
                    valid_candidates,
                    key=lambda indexed: indexed.candidate.activation_sequence,
                ).candidate.mode
                candidates = [
                    indexed.candidate
                    for indexed in valid_candidates
                    if indexed.candidate.mode == newest_mode
                ]
            indexed_candidate = self._load_index_candidates(
                candidates,
                allowed_root=allowed_root,
                selected_projects=selected_projects,
            )
            return indexed_candidate

        matched = load_for_mode(mode)
        if matched is not None:
            return matched
        if mode is not None and not strict_mode_match:
            return load_for_mode(None)
        return None

    def _save_runtime_update(
        self,
        *,
        state: RunState,
        emit: Callable[..., None],
        runtime_map_builder: Callable[[RunState], dict[str, object]],
        authoritative_project_names: Sequence[str] | None = None,
    ) -> dict[str, object]:
        project_names = (
            self._runtime_project_names_from_state(state)
            if authoritative_project_names is None
            else sorted(
                {
                    str(project_name).strip()
                    for project_name in authoritative_project_names
                    if str(project_name).strip()
                },
                key=str.casefold,
            )
        )
        self._prepare_state_for_save(state, project_names=project_names, authoritative_projects=True)
        runtime_map = runtime_map_builder(state)
        if not project_names:
            run_ids = [state.run_id, *self._source_run_ids(state)]
            with self._repository_lock(exclusive=True):
                self._ensure_active_index_unlocked()
                self.run_index.remove_many(run_ids)
                self._promote_latest_active_state()
            self._safe_emit(emit, "state.deactivate", run_ids=sorted(set(run_ids)))
            return runtime_map
        artifacts = {
            "run_state.json": self._json_text(state_to_dict(state)),
            "runtime_map.json": self._json_text(runtime_map),
        }
        with self._repository_lock(exclusive=True):
            self._ensure_active_index_unlocked()
            self._carry_forward_runtime_artifacts_unlocked(state, artifacts)
            revision_state_path = self._commit_revision_unlocked(
                state=state,
                project_names=project_names,
                artifacts=artifacts,
                supersede_run_ids=self._source_run_ids(state),
            )
        self._emit_saved_state(
            emit,
            state=state,
            state_path=revision_state_path,
            runtime_map_text=artifacts["runtime_map.json"],
        )
        return runtime_map

    def _carry_forward_runtime_artifacts_unlocked(
        self,
        state: RunState,
        artifacts: dict[str, str],
    ) -> None:
        source_run_ids = {state.run_id, *self._source_run_ids(state)}
        source_candidates = [
            candidate
            for candidate in self.run_index.candidates(StateSelector(mode=state.mode, project_names=()))
            if candidate.run_id in source_run_ids
        ]
        current_ports_manifest = artifacts.get("ports_manifest.json")
        artifacts["ports_manifest.json"] = self._merged_ports_manifest_text(
            state,
            source_candidates,
            current_manifest_text=current_ports_manifest,
        )
        artifacts.setdefault(
            "error_report.json",
            self._merged_error_report_text(state, source_candidates),
        )
        if not source_candidates:
            return
        source_candidate = max(
            source_candidates,
            key=lambda candidate: candidate.activation_sequence,
        )
        source_directories = (
            source_candidate.state_path.parent,
            self.run_dir_path(source_candidate.run_id),
        )
        for artifact_name in self._RUNTIME_ARTIFACT_NAMES:
            if artifact_name in artifacts:
                continue
            for source_directory in source_directories:
                source = source_directory / artifact_name
                if source.is_file() and not source.is_symlink():
                    try:
                        artifacts[artifact_name] = source.read_text(encoding="utf-8")
                    except (OSError, UnicodeError):
                        continue
                    break

    def _merged_ports_manifest_text(
        self,
        state: RunState,
        source_candidates: Sequence[RunIndexCandidate],
        *,
        current_manifest_text: str | None = None,
    ) -> str:
        project_names = self._project_names_from_state(state)
        selected = normalized_project_names(project_names)
        projects_by_key: dict[str, dict[str, object]] = {}
        for candidate in sorted(
            source_candidates,
            key=lambda item: item.activation_sequence,
        ):
            payload = self._read_revision_json_artifact(candidate, "ports_manifest.json")
            raw_projects = payload.get("projects") if isinstance(payload, Mapping) else None
            if not isinstance(raw_projects, list):
                continue
            for raw_project in raw_projects:
                if not isinstance(raw_project, Mapping):
                    continue
                project_name = str(raw_project.get("project", "")).strip()
                project_key = project_name.casefold()
                if project_key and project_key in selected:
                    projects_by_key[project_key] = dict(raw_project)

        if current_manifest_text is not None:
            try:
                current_payload = json.loads(current_manifest_text)
            except (TypeError, ValueError, json.JSONDecodeError):
                current_payload = {}
            raw_current_projects = current_payload.get("projects") if isinstance(current_payload, Mapping) else None
            if isinstance(raw_current_projects, list):
                for raw_project in raw_current_projects:
                    if not isinstance(raw_project, Mapping):
                        continue
                    project_name = str(raw_project.get("project", "")).strip()
                    project_key = project_name.casefold()
                    if project_key and project_key in selected:
                        projects_by_key[project_key] = dict(raw_project)

        roots = state.metadata.get("project_roots")
        project_roots = roots if isinstance(roots, Mapping) else {}
        for project_name in project_names:
            project_key = project_name.casefold()
            project_payload = projects_by_key.get(project_key)
            if project_payload is None:
                project_payload = {
                    "project": project_name,
                    "root": next(
                        (
                            str(root)
                            for name, root in project_roots.items()
                            if str(name).strip().casefold() == project_key
                        ),
                        "",
                    ),
                    "ports": {},
                }
                projects_by_key[project_key] = project_payload
            raw_ports = project_payload.get("ports")
            ports = dict(raw_ports) if isinstance(raw_ports, Mapping) else {}
            for service_name, service in state.services.items():
                if self._service_project_name(service_name, service).casefold() != project_key:
                    continue
                service_key = str(service.type or service_name).strip().casefold() or "service"
                ports.setdefault(
                    service_key,
                    {
                        "requested": service.requested_port,
                        "assigned": service.actual_port or service.requested_port,
                        "final": service.actual_port,
                        "source": "runtime_state",
                        "retries": None,
                    },
                )
            project_payload["ports"] = ports
        return self._json_text(
            {
                "run_id": state.run_id,
                "mode": state.mode,
                "projects": [projects_by_key[key] for key in sorted(projects_by_key)],
            }
        )

    def _merged_error_report_text(
        self,
        state: RunState,
        source_candidates: Sequence[RunIndexCandidate],
    ) -> str:
        errors: list[str] = []
        for candidate in sorted(source_candidates, key=lambda item: item.activation_sequence):
            payload = self._read_revision_json_artifact(candidate, "error_report.json")
            raw_errors = payload.get("errors") if isinstance(payload, Mapping) else None
            if not isinstance(raw_errors, list):
                continue
            for raw_error in raw_errors:
                error = str(raw_error).strip()
                if error and error not in errors:
                    errors.append(error)
        return self._json_text(
            {
                "run_id": state.run_id,
                "errors": errors,
                "source_run_ids": sorted({candidate.run_id for candidate in source_candidates}),
                "generated_at": datetime.now(tz=UTC).isoformat(),
            }
        )

    @staticmethod
    def _read_revision_json_artifact(
        candidate: RunIndexCandidate,
        artifact_name: str,
    ) -> Mapping[str, object]:
        path = candidate.state_path.parent / artifact_name
        if path.is_symlink() or not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, Mapping) else {}

    def _commit_revision_unlocked(
        self,
        *,
        state: RunState,
        project_names: Sequence[str],
        artifacts: Mapping[str, str],
        supersede_run_ids: Sequence[str] = (),
        on_commit: Callable[[], None] | None = None,
    ) -> Path:
        superseded_run_ids = {
            require_path_component(run_id, label="superseded run_id")
            for run_id in supersede_run_ids
            if str(run_id).strip() and str(run_id).strip() != state.run_id
        }
        superseded_candidates = [
            candidate
            for candidate in self.run_index.candidates(StateSelector(mode=None, project_names=()))
            if candidate.run_id in superseded_run_ids
        ]
        run_dir = self.run_dir_path(state.run_id)
        revisions_dir = self._contained_child(run_dir, "revisions", label="revisions directory")
        revision_id = f"{datetime.now(tz=UTC).strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex[:12]}"
        revision_dir = self._contained_child(revisions_dir, revision_id, label="revision id")
        revision_state_path = revision_dir / "run_state.json"
        retain_revision = False
        try:
            durable_mkdir(revision_dir)
            for artifact_name, text in artifacts.items():
                safe_name = require_path_component(artifact_name, label="artifact name")
                self._write_text(revision_dir / safe_name, text)
            try:
                self.run_index.record(
                    state_path=revision_state_path,
                    run_id=state.run_id,
                    mode=state.mode,
                    project_names=project_names,
                    supersede_run_ids=supersede_run_ids,
                )
            except BaseException:
                indexed = self._revision_index_commit_state_unlocked(
                    state=state,
                    revision_state_path=revision_state_path,
                )
                # An unreadable registry has an uncertain commit outcome. Keep
                # the immutable revision so a visible primary/backup can never
                # be left pointing at artifacts this writer deleted.
                retain_revision = indexed is not False
                if indexed and on_commit is not None:
                    on_commit()
                raise
            retain_revision = True
            if on_commit is not None:
                on_commit()
        finally:
            if not retain_revision:
                shutil.rmtree(revision_dir, ignore_errors=True)

        try:
            self._publish_revision_aliases(
                state=state,
                artifacts=artifacts,
            )
            self._promote_latest_active_state()
            for candidate in superseded_candidates:
                self._prune_or_enqueue_revision_cleanup_unlocked(candidate)
        except OSError:
            # The index is the commit point. Aliases are repaired on the next repository read.
            for candidate in superseded_candidates:
                self._enqueue_revision_cleanup_if_needed_unlocked(candidate)
        except BaseException:
            for candidate in superseded_candidates:
                self._enqueue_revision_cleanup_if_needed_unlocked(candidate)
            raise
        return revision_state_path

    def _revision_index_commit_state_unlocked(
        self,
        *,
        state: RunState,
        revision_state_path: Path,
    ) -> bool | None:
        try:
            expected_state_path = revision_state_path.resolve()
            expected_state_fingerprint = file_fingerprint(expected_state_path)
            runtime_map_path = expected_state_path.parent / "runtime_map.json"
            expected_runtime_map_fingerprint = file_fingerprint(runtime_map_path)
            candidates = self.run_index.candidates(
                StateSelector(mode=None, project_names=())
            )
        except BaseException:  # noqa: BLE001 - unreadable authority is uncertain, never negative
            return None
        expected_mode = str(state.mode or "").strip().casefold()
        return any(
            candidate.run_id == state.run_id
            and candidate.mode == expected_mode
            and candidate.state_path == expected_state_path
            and candidate.state_fingerprint == expected_state_fingerprint
            and candidate.runtime_map_fingerprint == expected_runtime_map_fingerprint
            for candidate in candidates
        )

    def _publish_revision_aliases(
        self,
        *,
        state: RunState,
        artifacts: Mapping[str, str],
    ) -> None:
        run_dir = self.run_dir_path(state.run_id)
        for artifact_name in self._RUN_ALIAS_ARTIFACT_NAMES:
            alias = run_dir / artifact_name
            text = artifacts.get(artifact_name)
            if text is None:
                alias.unlink(missing_ok=True)
            else:
                self._write_text(alias, text)
        candidates = self.run_index.candidates(StateSelector(mode=state.mode, project_names=()))
        committed = next(
            (candidate for candidate in candidates if candidate.run_id == state.run_id),
            None,
        )
        if committed is not None:
            self._write_run_alias_manifest(committed)

    def _run_alias_manifest_path(self, run_id: str) -> Path:
        return self.run_dir_path(run_id) / self._RUN_ALIAS_MANIFEST_NAME

    def _write_run_alias_manifest(self, candidate: RunIndexCandidate) -> None:
        source_dir = candidate.state_path.parent
        run_dir = self.run_dir_path(candidate.run_id)
        artifacts = {
            artifact_name: {
                "source": self._path_lstat_signature(source_dir / artifact_name),
                "alias": self._path_lstat_signature(run_dir / artifact_name),
            }
            for artifact_name in self._RUN_ALIAS_ARTIFACT_NAMES
        }
        self._write_text(
            self._run_alias_manifest_path(candidate.run_id),
            self._json_text(
                {
                    "version": 1,
                    "source_dir": str(source_dir),
                    "artifacts": artifacts,
                }
            ),
        )

    def _run_aliases_match_manifest(self, candidate: RunIndexCandidate) -> bool:
        manifest_path = self._run_alias_manifest_path(candidate.run_id)
        if manifest_path.is_symlink() or not manifest_path.is_file():
            return False
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return False
        if not isinstance(manifest, Mapping):
            return False
        if manifest.get("version") != 1 or manifest.get("source_dir") != str(candidate.state_path.parent):
            return False
        expected_artifacts = manifest.get("artifacts")
        if not isinstance(expected_artifacts, Mapping):
            return False
        source_dir = candidate.state_path.parent
        run_dir = self.run_dir_path(candidate.run_id)
        actual_artifacts = {
            artifact_name: {
                "source": self._path_lstat_signature(source_dir / artifact_name),
                "alias": self._path_lstat_signature(run_dir / artifact_name),
            }
            for artifact_name in self._RUN_ALIAS_ARTIFACT_NAMES
        }
        return expected_artifacts == actual_artifacts

    @staticmethod
    def _path_lstat_signature(path: Path) -> dict[str, object]:
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            return {"kind": "missing"}
        if not stat.S_ISREG(metadata.st_mode):
            return {
                "kind": "unsafe",
                "mode": metadata.st_mode,
                "inode": metadata.st_ino,
                "size": metadata.st_size,
                "mtime_ns": metadata.st_mtime_ns,
                "ctime_ns": metadata.st_ctime_ns,
            }
        return {
            "kind": "file",
            "inode": metadata.st_ino,
            "size": metadata.st_size,
            "mtime_ns": metadata.st_mtime_ns,
            "ctime_ns": metadata.st_ctime_ns,
        }

    def _prune_revisions_for_candidates_unlocked(
        self,
        indexed_states: Sequence[_IndexedState],
    ) -> None:
        seen_run_ids: set[str] = set()
        for indexed in indexed_states:
            candidate = indexed.candidate
            if candidate.run_id in seen_run_ids:
                continue
            seen_run_ids.add(candidate.run_id)
            try:
                self._prune_run_revisions_unlocked(candidate)
            except OSError:
                # Active candidates are retried by the next reconciliation.
                continue
        self._retry_pending_revision_cleanups_unlocked()

    def _prune_run_revisions_unlocked(self, candidate: RunIndexCandidate) -> None:
        run_dir = self.run_dir_path(candidate.run_id)
        revisions_dir = self._contained_child(
            run_dir,
            "revisions",
            label="revisions directory",
        )
        current_revision = candidate.state_path.parent
        if (
            revisions_dir.is_symlink()
            or not revisions_dir.is_dir()
            or current_revision.is_symlink()
            or not current_revision.is_dir()
            or current_revision.resolve().parent != revisions_dir.resolve()
        ):
            return
        siblings: list[tuple[int, str, Path]] = []
        for path in revisions_dir.iterdir():
            if path == current_revision or path.is_symlink() or not path.is_dir():
                continue
            try:
                if path.resolve().parent != revisions_dir.resolve():
                    continue
                metadata = path.stat()
            except OSError:
                continue
            siblings.append((metadata.st_mtime_ns, path.name, path))
        siblings.sort(reverse=True)
        removed = False
        try:
            for _, _, stale_revision in siblings[1:]:
                shutil.rmtree(stale_revision)
                removed = True
        finally:
            if removed:
                fsync_directory(revisions_dir)

    def _enqueue_revision_cleanup_unlocked(self, candidate: RunIndexCandidate) -> None:
        marker_path = self._revision_cleanup_marker_path(candidate.run_id)
        run_dir = self.run_dir_path(candidate.run_id)
        revisions_dir = self._contained_child(
            run_dir,
            "revisions",
            label="revisions directory",
        )
        state_path = candidate.state_path.resolve()
        if state_path.name != "run_state.json" or state_path.parent.parent != revisions_dir.resolve():
            raise ValueError("revision cleanup state path is outside the run revisions directory")
        cleanup_dir = marker_path.parent
        durable_mkdir(cleanup_dir)
        self._write_text(
            marker_path,
            self._json_text(
                {
                    "version": 1,
                    "runtime_scope_id": self.runtime_scope_id,
                    "run_id": candidate.run_id,
                    "mode": candidate.mode,
                    "state_path": str(state_path),
                }
            ),
        )

    def _prune_or_enqueue_revision_cleanup_unlocked(
        self,
        candidate: RunIndexCandidate,
    ) -> None:
        try:
            self._prune_run_revisions_unlocked(candidate)
        except OSError:
            self._enqueue_revision_cleanup_if_needed_unlocked(candidate)

    def _enqueue_revision_cleanup_if_needed_unlocked(
        self,
        candidate: RunIndexCandidate,
    ) -> None:
        if self._run_revision_count(candidate.run_id) <= 2:
            return
        try:
            self._enqueue_revision_cleanup_unlocked(candidate)
        except (OSError, RuntimeError, ValueError):
            return

    def _retry_pending_revision_cleanups_unlocked(self) -> None:
        cleanup_dir = self.runtime_root / self._REVISION_CLEANUP_DIR_NAME
        if cleanup_dir.is_symlink() or not cleanup_dir.is_dir():
            return
        try:
            marker_paths = list(cleanup_dir.iterdir())
        except OSError:
            return
        for marker_path in marker_paths:
            if marker_path.is_symlink() or not marker_path.is_file():
                continue
            candidate = self._revision_cleanup_candidate(marker_path)
            if candidate is None:
                self._remove_revision_cleanup_marker(marker_path)
                continue
            try:
                self._prune_run_revisions_unlocked(candidate)
            except OSError:
                continue
            if self._run_revision_count(candidate.run_id) <= 2:
                self._remove_revision_cleanup_marker(marker_path)
        try:
            cleanup_dir.rmdir()
        except OSError:
            return
        try:
            fsync_directory(self.runtime_root)
        except OSError:
            pass

    def _revision_cleanup_candidate(
        self,
        marker_path: Path,
    ) -> RunIndexCandidate | None:
        try:
            payload = json.loads(marker_path.read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping):
                return None
            if payload.get("version") != 1 or payload.get("runtime_scope_id") != self.runtime_scope_id:
                return None
            raw_run_id = payload.get("run_id")
            raw_mode = payload.get("mode")
            raw_state_path = payload.get("state_path")
            if not all(isinstance(value, str) and value for value in (raw_run_id, raw_mode, raw_state_path)):
                return None
            run_id = require_path_component(raw_run_id, label="run_id")
            if marker_path != self._revision_cleanup_marker_path(run_id):
                return None
            run_dir = self.run_dir_path(run_id)
            revisions_dir = self._contained_child(
                run_dir,
                "revisions",
                label="revisions directory",
            )
            state_path = Path(raw_state_path).expanduser().resolve()
            if state_path.name != "run_state.json" or state_path.parent.parent != revisions_dir.resolve():
                return None
            state = self._load_state_file_candidate(
                state_path,
                allowed_root=str(self.runtime_dir),
            )
            if state is None or state.run_id != run_id:
                return None
            if state.metadata.get("repo_scope_id") != self.runtime_scope_id:
                return None
            if state.mode.casefold() != raw_mode.casefold():
                return None
            return RunIndexCandidate(
                state_path=state_path,
                run_id=run_id,
                mode=state.mode,
                project_names=(),
                sequence=0,
            )
        except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def _revision_cleanup_marker_path(self, run_id: str) -> Path:
        normalized_run_id = require_path_component(run_id, label="run_id")
        cleanup_dir = self._contained_child(
            self.runtime_root,
            self._REVISION_CLEANUP_DIR_NAME,
            label="revision cleanup directory",
        )
        digest = text_fingerprint(normalized_run_id)
        marker_name = f"{digest}.json"
        return self._contained_child(
            cleanup_dir,
            marker_name,
            label="revision cleanup marker",
        )

    def _remove_revision_cleanup_marker(self, marker_path: Path) -> None:
        try:
            marker_path.unlink(missing_ok=True)
            fsync_directory(marker_path.parent)
        except OSError:
            return

    def _run_revision_count(self, run_id: str) -> int:
        revisions_dir = self.run_dir_path(run_id) / "revisions"
        if revisions_dir.is_symlink() or not revisions_dir.is_dir():
            return 0
        try:
            return sum(1 for path in revisions_dir.iterdir() if not path.is_symlink() and path.is_dir())
        except OSError:
            return 3

    def _emit_saved_state(
        self,
        emit: Callable[..., None],
        *,
        state: RunState,
        state_path: Path,
        runtime_map_text: str,
    ) -> None:
        self._safe_emit(emit, "state.save", run_id=state.run_id, path=str(state_path))
        self._safe_emit(
            emit,
            "state.fingerprint.after_save",
            run_id=state.run_id,
            state_fingerprint=state_fingerprint(state),
        )
        self._safe_emit(emit, "runtime_map.write", path=str(state_path.parent / "runtime_map.json"))
        self._safe_emit(
            emit,
            "runtime_map.fingerprint",
            run_id=state.run_id,
            runtime_map_fingerprint=text_fingerprint(runtime_map_text),
        )

    @staticmethod
    def _safe_emit(emit: Callable[..., None], event: str, **payload: object) -> None:
        try:
            emit(event, **payload)
        except Exception:
            return

    def _load_state_file_candidate(self, path: Path, *, allowed_root: str) -> RunState | None:
        if not path.is_file():
            return None
        try:
            return load_state(str(path), allowed_root=allowed_root)
        except Exception:
            return None

    def _load_index_candidates(
        self,
        candidates: Sequence[RunIndexCandidate],
        *,
        allowed_root: str,
        selected_projects: Sequence[str],
    ) -> RunState | None:
        indexed_states = self._load_valid_index_states(candidates, allowed_root=allowed_root)
        if not indexed_states:
            return None
        chosen_states = select_indexed_owners(
            indexed_states,
            selected_projects=selected_projects,
            service_project_name=self._service_project_name,
        )
        return state_from_indexed_owners(
            chosen_states,
            project_names_from_state=self._project_names_from_state,
            source_run_ids=self._source_run_ids,
        )

    def _ensure_active_index_unlocked(self) -> None:
        if not self.run_index.needs_rebuild():
            self.run_index.repair_copies()
            if not self._registry_marker_path.is_file():
                self._write_text(
                    self._registry_marker_path,
                    self._json_text({"version": 1, "runtime_scope_id": self.runtime_scope_id}),
                )
            return
        if self._registry_marker_path.is_file():
            raise RuntimeError(
                "Active run registry is unavailable because both the primary and backup indexes are invalid."
            )

        recovered: list[tuple[int, Path, RunState, list[str]]] = []
        runs_root = self.run_dir_path(None)
        if runs_root.is_dir():
            for run_dir in runs_root.iterdir():
                if run_dir.is_symlink() or not run_dir.is_dir():
                    continue
                state_path = run_dir / "run_state.json"
                if state_path.is_symlink() or not state_path.is_file():
                    continue
                try:
                    run_id = require_path_component(run_dir.name, label="run_id")
                    if run_dir.resolve().parent != runs_root.resolve():
                        continue
                    state = self._load_state_file_candidate(state_path, allowed_root=str(self.runtime_dir))
                    if state is None or state.run_id != run_id:
                        continue
                    scope = state.metadata.get("repo_scope_id")
                    if isinstance(scope, str) and scope and scope != self.runtime_scope_id:
                        continue
                    project_names = self._project_names_from_state(state)
                    if not project_names:
                        project_names = self._project_names_from_ports_manifest(
                            state_path.parent / "ports_manifest.json"
                        )
                    if not project_names:
                        project_names = self._project_names_from_pointers(
                            self.runtime_root,
                            state_path,
                        )
                    modified_at = state_path.stat().st_mtime_ns
                    state.metadata["repo_scope_id"] = self.runtime_scope_id
                    state.metadata["project_names"] = sorted(set(project_names), key=str.casefold)
                    recovered.append((modified_at, state_path, state, project_names))
                except (OSError, RuntimeError, ValueError):
                    continue
        recovered_run_ids = {state.run_id for _, _, state, _ in recovered}
        for root in self._legacy_migration_roots():
            legacy_candidates = [
                (root / "run_state.json", self._load_state_file_candidate),
                (root / "run_state.state", self._load_legacy_shell_candidate),
            ]
            legacy_candidates.extend(
                (pointer, self._load_pointer_candidate) for pointer in self._legacy_pointer_paths(root)
            )
            for candidate_path, legacy_loader in legacy_candidates:
                if candidate_path.is_symlink() or not candidate_path.is_file():
                    continue
                try:
                    state = legacy_loader(candidate_path, allowed_root=str(self.runtime_dir))
                    if state is None or state.run_id in recovered_run_ids:
                        continue
                    existing_scope = state.metadata.get("repo_scope_id")
                    if isinstance(existing_scope, str) and existing_scope and existing_scope != self.runtime_scope_id:
                        continue
                    project_names = self._project_names_from_state(state)
                    if not project_names:
                        project_names = self._project_names_from_ports_manifest(root / "ports_manifest.json")
                    if not project_names:
                        project_names = self._project_names_from_pointers(root, candidate_path)
                    if not project_names and candidate_path.name.startswith(".last_state.trees."):
                        project_name = candidate_path.name.removeprefix(".last_state.trees.").strip()
                        if project_name:
                            project_names = [project_name]
                    state.metadata["repo_scope_id"] = self.runtime_scope_id
                    state.metadata["project_names"] = sorted(set(project_names), key=str.casefold)
                    recovered.append((candidate_path.stat().st_mtime_ns, candidate_path, state, project_names))
                    recovered_run_ids.add(state.run_id)
                except (OSError, RuntimeError, ValueError):
                    continue

        indexed_entries: list[RunIndexCandidate] = []
        registry_committed = False
        try:
            for sequence, (_, source_path, state, project_names) in enumerate(
                sorted(recovered, key=lambda item: (item[0], str(item[1]))),
                start=1,
            ):
                revision_state_path = self._stage_legacy_revision(
                    state=state,
                    source_path=source_path,
                )
                indexed_entries.append(
                    RunIndexCandidate(
                        state_path=revision_state_path,
                        run_id=state.run_id,
                        mode=state.mode,
                        project_names=tuple(sorted(normalized_project_names(project_names))),
                        sequence=sequence,
                    )
                )
            self.run_index.replace_all(indexed_entries)
            registry_committed = True
        finally:
            if not registry_committed:
                for entry in indexed_entries:
                    shutil.rmtree(entry.state_path.parent, ignore_errors=True)
        self._write_text(
            self._registry_marker_path,
            self._json_text({"version": 1, "runtime_scope_id": self.runtime_scope_id}),
        )

    def _legacy_migration_roots(self) -> list[Path]:
        roots = [self.runtime_root]
        if self.compat_mode != self.SCOPED_ONLY and self.runtime_legacy_root != self.runtime_root:
            roots.append(self.runtime_legacy_root)
        return roots

    @staticmethod
    def _legacy_pointer_paths(root: Path) -> list[Path]:
        candidates = [
            root / ".last_state.main",
            *sorted(root.glob(".last_state.trees.*")),
            root / ".last_state",
        ]
        return [pointer for pointer in candidates if not pointer.is_symlink() and pointer.is_file()]

    @staticmethod
    def _load_pointer_candidate(path: Path, *, allowed_root: str) -> RunState | None:
        try:
            return load_state_from_pointer(str(path), allowed_root=allowed_root)
        except Exception:
            return None

    def _stage_legacy_revision(self, *, state: RunState, source_path: Path) -> Path:
        run_dir = self.run_dir_path(state.run_id)
        revisions_dir = self._contained_child(run_dir, "revisions", label="revisions directory")
        revision_id = f"legacy-{uuid.uuid4().hex}"
        revision_dir = self._contained_child(revisions_dir, revision_id, label="revision id")
        revision_state_path = revision_dir / "run_state.json"
        staged = False
        try:
            durable_mkdir(revision_dir)
            self._write_text(revision_state_path, self._json_text(state_to_dict(state)))
            for artifact_name in (
                "runtime_map.json",
                *self._REVISION_ANCILLARY_ARTIFACT_NAMES,
            ):
                source_artifact = source_path.parent / artifact_name
                if source_artifact.is_symlink() or not source_artifact.is_file():
                    continue
                try:
                    self._write_text(
                        revision_dir / artifact_name,
                        source_artifact.read_text(encoding="utf-8"),
                    )
                except (OSError, UnicodeError):
                    continue
            staged = True
        finally:
            if not staged:
                shutil.rmtree(revision_dir, ignore_errors=True)
        return revision_state_path

    @staticmethod
    def _project_names_from_ports_manifest(path: Path) -> list[str]:
        if not path.is_file():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return []
        raw_projects = payload.get("projects") if isinstance(payload, Mapping) else None
        if not isinstance(raw_projects, list):
            return []
        return sorted(
            {
                str(project.get("project", "")).strip()
                for project in raw_projects
                if isinstance(project, Mapping) and str(project.get("project", "")).strip()
            },
            key=str.casefold,
        )

    @staticmethod
    def _project_names_from_pointers(root: Path, state_path: Path) -> list[str]:
        expected = state_path.resolve()
        project_names: set[str] = set()
        for pointer in root.glob(".last_state.trees.*"):
            if pointer.is_symlink() or not pointer.is_file():
                continue
            try:
                raw_target = pointer.read_text(encoding="utf-8").splitlines()[0].strip()
                target = Path(raw_target).expanduser().resolve()
            except (IndexError, OSError, RuntimeError, ValueError):
                continue
            if target == expected:
                project_names.add(pointer.name.removeprefix(".last_state.trees."))
        return sorted(project_names, key=str.casefold)

    def _load_valid_index_states(
        self,
        candidates: Sequence[RunIndexCandidate],
        *,
        allowed_root: str,
    ) -> list[_IndexedState]:
        loaded: list[_IndexedState] = []
        for indexed in candidates:
            try:
                if file_fingerprint(indexed.state_path) != indexed.state_fingerprint:
                    continue
                if indexed.runtime_map_fingerprint is not None:
                    runtime_map_path = indexed.state_path.parent / "runtime_map.json"
                    if (
                        runtime_map_path.is_symlink()
                        or not runtime_map_path.is_file()
                        or file_fingerprint(runtime_map_path) != indexed.runtime_map_fingerprint
                    ):
                        continue
            except OSError:
                continue
            state = self._load_state_file_candidate(indexed.state_path, allowed_root=allowed_root)
            if state is None:
                continue
            if state.run_id != indexed.run_id or state.mode.casefold() != indexed.mode:
                continue
            if state.metadata.get("repo_scope_id") != self.runtime_scope_id:
                continue
            state_projects = normalized_project_names(self._project_names_from_state(state))
            indexed_projects = frozenset(indexed.project_names)
            if indexed_projects and not indexed_projects.issubset(state_projects):
                continue
            loaded.append(_IndexedState(candidate=indexed, state=state))
        return loaded

    def _promote_latest_active_state(self) -> None:
        candidates = self.run_index.candidates(StateSelector(mode=None, project_names=()))
        if not candidates:
            self._remove_current_aliases()
            return
        valid_candidates = self._load_valid_index_states(
            candidates,
            allowed_root=str(self.runtime_dir),
        )
        if not valid_candidates:
            self._remove_current_aliases()
            return
        latest_candidate = max(
            valid_candidates,
            key=lambda indexed: indexed.candidate.activation_sequence,
        ).candidate
        mode_candidates = [indexed for indexed in valid_candidates if indexed.candidate.mode == latest_candidate.mode]
        chosen_states = select_indexed_owners(
            mode_candidates,
            selected_projects=(),
            service_project_name=self._service_project_name,
        )
        latest_state = state_from_indexed_owners(
            chosen_states,
            project_names_from_state=self._project_names_from_state,
            source_run_ids=self._source_run_ids,
        )
        if latest_state is None:
            self._remove_current_aliases()
            return
        selected_candidates = [indexed.candidate for indexed in chosen_states]
        latest_selected = max(
            selected_candidates,
            key=lambda candidate: (
                candidate.activation_sequence,
                candidate.sequence,
                str(candidate.state_path),
            ),
        )
        source_dir = latest_selected.state_path.parent
        current_state_text = self._json_text(state_to_dict(latest_state))
        current_runtime_map_text = self._json_text(build_runtime_map(latest_state))
        aggregate_artifacts = {
            "ports_manifest.json": self._merged_ports_manifest_text(
                latest_state,
                selected_candidates,
            ),
            "error_report.json": self._merged_error_report_text(
                latest_state,
                selected_candidates,
            ),
        }
        self._write_text(self.run_state_path(), current_state_text)
        self._write_text(self.runtime_map_path(), current_runtime_map_text)
        for artifact_name in self._REVISION_ANCILLARY_ARTIFACT_NAMES:
            current = self.runtime_root / artifact_name
            aggregate_text = aggregate_artifacts.get(artifact_name)
            if aggregate_text is not None:
                self._write_text(current, aggregate_text)
            else:
                source = source_dir / artifact_name
                if source.is_file() and not source.is_symlink():
                    self._write_text(current, source.read_text(encoding="utf-8"))
                else:
                    current.unlink(missing_ok=True)
        self._rebuild_mode_pointers(self.runtime_root, valid_candidates)
        if self.compat_mode == self.COMPAT_READ_WRITE:
            self._write_text(self.runtime_legacy_root / "run_state.json", current_state_text)
            self._write_text(self.runtime_legacy_root / "runtime_map.json", current_runtime_map_text)
            for artifact_name in self._REVISION_ANCILLARY_ARTIFACT_NAMES:
                current = self.runtime_legacy_root / artifact_name
                aggregate_text = aggregate_artifacts.get(artifact_name)
                if aggregate_text is not None:
                    self._write_text(current, aggregate_text)
                else:
                    source = source_dir / artifact_name
                    if source.is_file() and not source.is_symlink():
                        self._write_text(current, source.read_text(encoding="utf-8"))
                    else:
                        current.unlink(missing_ok=True)
            self._rebuild_mode_pointers(self.runtime_legacy_root, valid_candidates)
        self._write_text(
            self._alias_manifest_path,
            self._json_text(
                {
                    "version": 2,
                    "sources": {
                        indexed.candidate.run_id: str(indexed.candidate.state_path) for indexed in valid_candidates
                    },
                    "source_fingerprints": {
                        indexed.candidate.run_id: state_fingerprint(indexed.state) for indexed in valid_candidates
                    },
                    "state_fingerprint": text_fingerprint(current_state_text),
                    "runtime_map_fingerprint": text_fingerprint(current_runtime_map_text),
                    "source_artifact_signatures": self._revision_artifact_signatures(valid_candidates),
                    "scoped_alias_signatures": self._artifact_signatures(self.runtime_root),
                    "legacy_alias_signatures": (
                        self._artifact_signatures(self.runtime_legacy_root)
                        if self.compat_mode == self.COMPAT_READ_WRITE
                        else None
                    ),
                }
            ),
        )
        self._prune_revisions_for_candidates_unlocked(valid_candidates)

    def _reconcile_current_aliases_unlocked(self) -> None:
        candidates = self.run_index.candidates(StateSelector(mode=None, project_names=()))
        if not candidates:
            if self.run_state_path().exists() or (self.runtime_root / ".last_state").exists():
                self._remove_current_aliases()
            return
        valid_candidates = self._load_valid_index_states(
            candidates,
            allowed_root=str(self.runtime_dir),
        )
        expected_sources = {indexed.candidate.run_id: str(indexed.candidate.state_path) for indexed in valid_candidates}
        expected_source_fingerprints = {
            indexed.candidate.run_id: state_fingerprint(indexed.state) for indexed in valid_candidates
        }
        expected_source_artifact_signatures = self._revision_artifact_signatures(valid_candidates)
        try:
            self._reconcile_run_aliases_unlocked(valid_candidates)
        except OSError:
            pass
        try:
            manifest = json.loads(self._alias_manifest_path.read_text(encoding="utf-8"))
            state_text = self.run_state_path().read_text(encoding="utf-8")
            runtime_map_text = self.runtime_map_path().read_text(encoding="utf-8")
            if (
                isinstance(manifest, Mapping)
                and manifest.get("version") == 2
                and manifest.get("sources") == expected_sources
                and manifest.get("source_fingerprints") == expected_source_fingerprints
                and manifest.get("source_artifact_signatures") == expected_source_artifact_signatures
                and manifest.get("state_fingerprint") == text_fingerprint(state_text)
                and manifest.get("runtime_map_fingerprint") == text_fingerprint(runtime_map_text)
                and manifest.get("scoped_alias_signatures") == self._artifact_signatures(self.runtime_root)
                and manifest.get("legacy_alias_signatures")
                == (
                    self._artifact_signatures(self.runtime_legacy_root)
                    if self.compat_mode == self.COMPAT_READ_WRITE
                    else None
                )
                and self._mode_pointers_match(self.runtime_root, valid_candidates)
                and (
                    self.compat_mode != self.COMPAT_READ_WRITE
                    or self._mode_pointers_match(self.runtime_legacy_root, valid_candidates)
                )
            ):
                self._prune_revisions_for_candidates_unlocked(valid_candidates)
                return
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
        try:
            self._promote_latest_active_state()
        except OSError:
            return

    def _revision_artifact_signatures(
        self,
        indexed_states: Sequence[_IndexedState],
    ) -> dict[str, dict[str, dict[str, object]]]:
        return {
            indexed.candidate.run_id: self._artifact_signatures(indexed.candidate.state_path.parent)
            for indexed in indexed_states
        }

    def _artifact_signatures(self, root: Path) -> dict[str, dict[str, object]]:
        return {
            artifact_name: self._path_lstat_signature(root / artifact_name)
            for artifact_name in self._RUN_ALIAS_ARTIFACT_NAMES
        }

    def _reconcile_run_aliases_unlocked(
        self,
        indexed_states: Sequence[_IndexedState],
    ) -> None:
        for indexed in indexed_states:
            candidate = indexed.candidate
            if self._run_aliases_match_manifest(candidate):
                continue
            source_dir = candidate.state_path.parent
            run_dir = self.run_dir_path(candidate.run_id)
            for artifact_name in self._RUN_ALIAS_ARTIFACT_NAMES:
                source = source_dir / artifact_name
                alias = run_dir / artifact_name
                if not source.is_file() or source.is_symlink():
                    alias.unlink(missing_ok=True)
                    continue
                self._write_text(alias, source.read_text(encoding="utf-8"))
            self._write_run_alias_manifest(candidate)

    def _remove_current_aliases(self) -> None:
        roots = [self.runtime_root]
        if self.compat_mode == self.COMPAT_READ_WRITE and self.runtime_legacy_root != self.runtime_root:
            roots.append(self.runtime_legacy_root)
        for root in roots:
            for name in (
                "run_state.json",
                "runtime_map.json",
                "ports_manifest.json",
                "error_report.json",
                "events.jsonl",
                "runtime_readiness_report.json",
                "current_alias.json",
            ):
                (root / name).unlink(missing_ok=True)
            self._remove_owned_mode_pointers(root)

    @staticmethod
    def _remove_pointers_to_state(root: Path, state_path: Path) -> None:
        expected = str(state_path.resolve())
        for pointer in root.glob(".last_state*"):
            if not pointer.is_file():
                continue
            try:
                target = pointer.read_text(encoding="utf-8").splitlines()[0].strip()
            except (IndexError, OSError, UnicodeError):
                continue
            try:
                resolved_target = str(Path(target).expanduser().resolve())
            except (OSError, RuntimeError, ValueError):
                continue
            if resolved_target == expected:
                pointer.unlink(missing_ok=True)

    def _load_legacy_shell_candidate(self, path: Path, *, allowed_root: str) -> RunState | None:
        if not path.is_file():
            return None
        try:
            return load_legacy_shell_state(str(path), allowed_root=allowed_root)
        except Exception:
            return None

    @staticmethod
    def _json_text(payload: Mapping[str, object]) -> str:
        return json.dumps(payload, indent=2, sort_keys=True)

    @staticmethod
    def _events_text(events: list[dict[str, object]]) -> str:
        return "".join(json.dumps(event, sort_keys=True) + "\n" for event in events)

    @staticmethod
    def _write_text(path: Path, text: str) -> None:
        scavenge_atomic_write_temps(path)
        atomic_write_text(path, text)

    @contextmanager
    def _repository_lock(self, *, exclusive: bool) -> Iterator[None]:
        self._validate_runtime_roots()
        with advisory_file_lock(self._lock_path, exclusive=exclusive):
            self._validate_runtime_roots()
            yield

    def _validate_runtime_roots(self) -> None:
        self._runtime_root_identity = self._validate_directory_identity(
            self.runtime_root,
            expected=self._runtime_root_identity,
            create=True,
            label="runtime_root",
        )
        if self.compat_mode == self.SCOPED_ONLY:
            return
        self._legacy_root_identity = self._validate_directory_identity(
            self.runtime_legacy_root,
            expected=self._legacy_root_identity,
            create=self.compat_mode == self.COMPAT_READ_WRITE,
            label="runtime_legacy_root",
        )

    @staticmethod
    def _existing_directory_identity(path: Path) -> tuple[int, int] | None:
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_dir():
            raise ValueError(f"runtime root is not a real directory: {path}")
        metadata = path.stat()
        return metadata.st_dev, metadata.st_ino

    @staticmethod
    def _validate_directory_identity(
        path: Path,
        *,
        expected: tuple[int, int] | None,
        create: bool,
        label: str,
    ) -> tuple[int, int] | None:
        if path.is_symlink() or path.resolve(strict=False) != path:
            raise RuntimeError(f"{label} changed identity or became a symlink: {path}")
        if create:
            durable_mkdir(path)
        if not path.exists():
            return expected
        if not path.is_dir():
            raise RuntimeError(f"{label} is not a directory: {path}")
        metadata = path.stat()
        current = metadata.st_dev, metadata.st_ino
        if expected is not None and current != expected:
            raise RuntimeError(f"{label} changed identity: {path}")
        return current

    def purge(self, *, aggressive: bool = False) -> None:
        with self._repository_lock(exclusive=True):
            self._purge_unlocked(aggressive=aggressive)

    def _purge_unlocked(self, *, aggressive: bool) -> None:
        self._retry_pending_revision_cleanups_unlocked()
        self.run_index.purge()
        self._write_text(
            self._registry_marker_path,
            self._json_text({"version": 1, "runtime_scope_id": self.runtime_scope_id}),
        )
        scoped_paths = (
            self.run_state_path(),
            self.runtime_map_path(),
            self.ports_manifest_path(),
            self.error_report_path(),
            self.runtime_root / "events.jsonl",
            self.runtime_root / "runtime_readiness_report.json",
            self._alias_manifest_path,
        )
        for path in scoped_paths:
            path.unlink(missing_ok=True)
        diagnostics_dir = self.runtime_root / "diagnostics"
        if diagnostics_dir.is_symlink():
            diagnostics_dir.unlink(missing_ok=True)
        elif diagnostics_dir.is_dir():
            shutil.rmtree(diagnostics_dir)
        self._remove_owned_mode_pointers(self.runtime_root)

        if self.compat_mode == self.COMPAT_READ_WRITE:
            legacy_paths = (
                self.runtime_legacy_root / "run_state.json",
                self.runtime_legacy_root / "runtime_map.json",
                self.runtime_legacy_root / "ports_manifest.json",
                self.runtime_legacy_root / "error_report.json",
                self.runtime_legacy_root / "events.jsonl",
                self.runtime_legacy_root / "runtime_readiness_report.json",
            )
            for path in legacy_paths:
                path.unlink(missing_ok=True)
            self._remove_owned_mode_pointers(self.runtime_legacy_root)

        if aggressive:
            runs_dirs = [self.runtime_root / "runs"]
            if self.compat_mode == self.COMPAT_READ_WRITE and self.runtime_legacy_root != self.runtime_root:
                runs_dirs.append(self.runtime_legacy_root / "runs")
            for runs_dir in runs_dirs:
                if runs_dir.is_dir():
                    shutil.rmtree(runs_dir)
            cleanup_dir = self.runtime_root / self._REVISION_CLEANUP_DIR_NAME
            if cleanup_dir.is_symlink():
                cleanup_dir.unlink(missing_ok=True)
            elif cleanup_dir.is_dir():
                shutil.rmtree(cleanup_dir)
            self._scavenge_atomic_temps()

    def _scavenge_atomic_temps(self) -> None:
        roots = {self.runtime_root}
        if self.compat_mode == self.COMPAT_READ_WRITE:
            roots.add(self.runtime_legacy_root)
        for root in roots:
            if not root.is_dir():
                continue
            for temporary_path in root.rglob(".*.tmp"):
                if temporary_path.is_file() and not temporary_path.is_symlink():
                    temporary_path.unlink(missing_ok=True)

    def _context_ports_payload(self, context: object) -> dict[str, object]:
        ports = getattr(context, "ports", {})
        payload_ports: dict[str, object] = {}
        if isinstance(ports, Mapping):
            ports_by_name = cast(Mapping[object, object], ports)
            for key, plan in ports_by_name.items():
                payload_ports[str(key)] = {
                    "requested": getattr(plan, "requested", None),
                    "assigned": getattr(plan, "assigned", None),
                    "final": getattr(plan, "final", None),
                    "source": getattr(plan, "source", None),
                    "retries": getattr(plan, "retries", None),
                }
        return {
            "project": str(getattr(context, "name", "")),
            "root": str(getattr(context, "root", "")),
            "ports": payload_ports,
        }

    @staticmethod
    def _context_names(contexts: list[object]) -> list[str]:
        names: set[str] = set()
        for context in contexts:
            name = str(getattr(context, "name", "")).strip()
            if name:
                names.add(name)
        return sorted(names, key=str.lower)

    def _prepare_state_for_save(
        self,
        state: RunState,
        *,
        project_names: Sequence[str],
        contexts: Sequence[object] = (),
        authoritative_projects: bool = False,
    ) -> None:
        _ = self.run_dir_path(state.run_id)
        if state.mode not in {"main", "trees"}:
            raise ValueError("state mode must be 'main' or 'trees'")
        existing_scope = state.metadata.get("repo_scope_id")
        if isinstance(existing_scope, str) and existing_scope and existing_scope != self.runtime_scope_id:
            raise ValueError("state repo_scope_id does not match this repository")
        state.metadata["repo_scope_id"] = self.runtime_scope_id

        canonical_names = sorted(
            {str(name).strip() for name in project_names if str(name).strip()},
            key=str.casefold,
        )
        if canonical_names or authoritative_projects:
            state.metadata["project_names"] = canonical_names

        existing_roots = state.metadata.get("project_roots")
        project_roots = dict(existing_roots) if isinstance(existing_roots, Mapping) else {}
        for context in contexts:
            name = str(getattr(context, "name", "")).strip()
            root = getattr(context, "root", None)
            if name and root is not None and str(root).strip():
                project_roots[name] = str(Path(str(root)).expanduser().resolve(strict=False))
        if authoritative_projects:
            normalized_names = normalized_project_names(canonical_names)
            project_roots = {
                str(name): root
                for name, root in project_roots.items()
                if str(name).strip().casefold() in normalized_names
            }
        if project_roots:
            state.metadata["project_roots"] = project_roots
        elif authoritative_projects:
            state.metadata.pop("project_roots", None)
        if canonical_names or authoritative_projects:
            state.metadata = filter_project_scoped_metadata(
                state.metadata,
                canonical_names,
                case_sensitive=False,
            )
            state.metadata["project_names"] = canonical_names

    def _runtime_project_names_from_state(self, state: RunState) -> list[str]:
        names: set[str] = set()
        for storage_name, requirements in state.requirements.items():
            normalized = str(getattr(requirements, "project", "") or storage_name).strip()
            if normalized:
                names.add(normalized)
        for service_name, service in state.services.items():
            project_name = self._service_project_name(service_name, service)
            if project_name:
                names.add(project_name)
        non_main_names = {name for name in names if name.casefold() != "main"}
        if state.mode == "trees" and non_main_names:
            names = non_main_names
        if state.mode == "main":
            names.add("Main")
        if names:
            return sorted(names, key=str.casefold)
        if bool(state.metadata.get("dashboard_runs_disabled")) or bool(
            state.metadata.get(DASHBOARD_STOPPED_SERVICES_KEY)
        ):
            return self._project_names_from_state(state)
        return []

    @staticmethod
    def _source_run_ids(state: RunState) -> list[str]:
        raw = state.metadata.get("state_source_run_ids")
        values = raw if isinstance(raw, list) else []
        return [str(run_id).strip() for run_id in values if str(run_id).strip()]

    def _project_names_from_state(self, state: RunState) -> list[str]:
        names: set[str] = set()
        metadata_names = state.metadata.get("project_names")
        if isinstance(metadata_names, Sequence) and not isinstance(metadata_names, (str, bytes)):
            for project in metadata_names:
                normalized = str(project).strip()
                if normalized:
                    names.add(normalized)
        metadata_roots = state.metadata.get("project_roots")
        if isinstance(metadata_roots, Mapping):
            for project in metadata_roots:
                normalized = str(project).strip()
                if normalized:
                    names.add(normalized)
        if names:
            return sorted(names, key=str.casefold)
        for storage_name, requirements in state.requirements.items():
            normalized = str(getattr(requirements, "project", "") or storage_name).strip()
            if normalized:
                names.add(normalized)
        for service_name, service in state.services.items():
            project_name = str(getattr(service, "project", "") or "").strip()
            if not project_name:
                project_name = self._project_name_from_service_name(service_name) or ""
            if project_name:
                names.add(project_name)
        if state.mode == "trees" and len(names) > 1:
            names.discard("Main")
        if state.mode == "main":
            names.add("Main")
        return sorted(names, key=str.lower)

    @staticmethod
    def _project_name_from_service_name(service_name: str) -> str | None:
        normalized = str(service_name).strip()
        if not normalized:
            return None
        lowered = normalized.lower()
        if lowered.endswith(" backend"):
            project_name = normalized[: -len(" backend")].strip()
            return project_name or None
        if lowered.endswith(" frontend"):
            project_name = normalized[: -len(" frontend")].strip()
            return project_name or None
        return None

    def _service_project_name(self, service_name: str, service: ServiceRecord) -> str:
        explicit_project = str(getattr(service, "project", "") or "").strip()
        if explicit_project:
            return explicit_project
        return self._project_name_from_service_name(service_name) or ""

    def _contained_child(self, root: Path, component: str, *, label: str) -> Path:
        runtime_root = self.runtime_root.resolve()
        if root.is_symlink():
            raise ValueError(f"{label} root must not be a symlink")
        resolved_root = root.resolve()
        try:
            resolved_root.relative_to(runtime_root)
        except ValueError as exc:
            raise ValueError(f"{label} root escapes runtime_root") from exc
        candidate = root / component
        if candidate.is_symlink():
            raise ValueError(f"{label} must not be a symlink")
        if candidate.resolve().parent != resolved_root:
            raise ValueError(f"{label} escapes its expected directory")
        return candidate

    def _rebuild_mode_pointers(
        self,
        root: Path,
        indexed_states: Sequence[_IndexedState],
    ) -> None:
        desired = self._desired_mode_pointers(indexed_states)
        stale_names = self._owned_pointer_names(root).difference(desired)
        for name, target in desired.items():
            self._write_text(root / name, target + "\n")
        for name in stale_names:
            (root / name).unlink(missing_ok=True)
        self._write_text(
            self._pointer_manifest_path(root),
            self._json_text(
                {
                    "version": 1,
                    "runtime_scope_id": self.runtime_scope_id,
                    "pointers": desired,
                }
            ),
        )

    def _desired_mode_pointers(
        self,
        indexed_states: Sequence[_IndexedState],
    ) -> dict[str, str]:
        if not indexed_states:
            return {}
        latest_active = max(
            indexed_states,
            key=lambda indexed: indexed.candidate.activation_sequence,
        )
        desired = {".last_state": str(latest_active.candidate.state_path)}
        owned_tree_projects: set[str] = set()
        latest_main = max(
            (indexed for indexed in indexed_states if indexed.candidate.mode == "main"),
            key=lambda indexed: indexed.candidate.activation_sequence,
            default=None,
        )
        if latest_main is not None:
            desired[".last_state.main"] = str(latest_main.candidate.state_path)
        for indexed in indexed_states:
            candidate = indexed.candidate
            target = str(candidate.state_path)
            if candidate.mode != "trees":
                continue
            display_names = {name.casefold(): name for name in self._project_names_from_state(indexed.state)}
            for project_key in candidate.project_names:
                if project_key in owned_tree_projects:
                    continue
                owned_tree_projects.add(project_key)
                display_name = display_names.get(project_key, project_key)
                pointer_name = self._tree_pointer_name(display_name)
                if pointer_name is None:
                    continue
                if pointer_name in desired and desired[pointer_name] != target:
                    digest = text_fingerprint(display_name)[:10]
                    pointer_name = f"{pointer_name}-{digest}"
                desired[pointer_name] = target
        return desired

    def _mode_pointers_match(
        self,
        root: Path,
        indexed_states: Sequence[_IndexedState],
    ) -> bool:
        desired = self._desired_mode_pointers(indexed_states)
        try:
            payload = json.loads(self._pointer_manifest_path(root).read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping) or payload.get("pointers") != desired:
                return False
            if self._owned_pointer_names(root) != set(desired):
                return False
            return all((root / name).read_text(encoding="utf-8") == target + "\n" for name, target in desired.items())
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return False

    def _remove_owned_mode_pointers(self, root: Path) -> None:
        for name in self._owned_pointer_names(root):
            (root / name).unlink(missing_ok=True)
        self._pointer_manifest_path(root).unlink(missing_ok=True)

    def _owned_pointer_names(self, root: Path) -> set[str]:
        names: set[str] = set()
        try:
            payload = json.loads(self._pointer_manifest_path(root).read_text(encoding="utf-8"))
            raw_pointers = payload.get("pointers") if isinstance(payload, Mapping) else None
            if isinstance(raw_pointers, Mapping):
                for raw_name in raw_pointers:
                    name = str(raw_name)
                    if name not in {".last_state", ".last_state.main"} and not name.startswith(".last_state.trees."):
                        continue
                    if root == self.runtime_root or self._pointer_targets_runtime_root(root / name):
                        names.add(name)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
        for pointer in root.glob(".last_state*"):
            if pointer.name not in {".last_state", ".last_state.main"} and not pointer.name.startswith(
                ".last_state.trees."
            ):
                continue
            if root == self.runtime_root or self._pointer_targets_runtime_root(pointer):
                names.add(pointer.name)
        return names

    def _pointer_targets_runtime_root(self, pointer: Path) -> bool:
        if pointer.is_symlink() or not pointer.is_file():
            return False
        try:
            target = Path(pointer.read_text(encoding="utf-8").splitlines()[0].strip()).resolve()
            target.relative_to(self.runtime_root)
        except (IndexError, OSError, RuntimeError, ValueError):
            return False
        return True

    def _pointer_manifest_path(self, root: Path) -> Path:
        if root == self.runtime_root:
            return root / "pointer_manifest.json"
        scope_stem = safe_artifact_stem(self.runtime_scope_id, fallback="scope")
        scope_hash = text_fingerprint(self.runtime_scope_id)[:10]
        return root / f".pointer_manifest.{scope_stem}-{scope_hash}.json"

    @staticmethod
    def _tree_pointer_name(project_name: str) -> str | None:
        normalized_project = str(project_name).strip()
        if not normalized_project or normalized_project.lower() == "main":
            return None
        pointer_suffix = safe_artifact_stem(normalized_project, fallback="project")
        if pointer_suffix != normalized_project:
            digest = text_fingerprint(normalized_project)[:10]
            pointer_suffix = f"{pointer_suffix}-{digest}"
        return f".last_state.trees.{pointer_suffix}"
