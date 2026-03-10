from __future__ import annotations

import json
import hashlib
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from envctl_engine.state.models import RunState
from envctl_engine.state import dump_state, load_legacy_shell_state, load_state, load_state_from_pointer, state_to_dict


@dataclass(slots=True)
class StateRepositoryPaths:
    run_dir: Path
    run_state: Path


class RuntimeStateRepository:
    COMPAT_READ_WRITE = "compat_read_write"
    COMPAT_READ_ONLY = "compat_read_only"
    SCOPED_ONLY = "scoped_only"

    def __init__(
        self,
        *,
        runtime_root: Path,
        runtime_legacy_root: Path,
        runtime_dir: Path,
        runtime_scope_id: str,
        compat_mode: str,
    ) -> None:
        self.runtime_root = runtime_root
        self.runtime_legacy_root = runtime_legacy_root
        self.runtime_dir = runtime_dir
        self.runtime_scope_id = runtime_scope_id
        self.compat_mode = (
            compat_mode
            if compat_mode
            in {
                self.COMPAT_READ_WRITE,
                self.COMPAT_READ_ONLY,
                self.SCOPED_ONLY,
            }
            else self.COMPAT_READ_WRITE
        )

    def run_state_path(self) -> Path:
        return self.runtime_root / "run_state.json"

    def runtime_map_path(self) -> Path:
        return self.runtime_root / "runtime_map.json"

    def ports_manifest_path(self) -> Path:
        return self.runtime_root / "ports_manifest.json"

    def error_report_path(self) -> Path:
        return self.runtime_root / "error_report.json"

    def run_dir_path(self, run_id: str | None) -> Path:
        if run_id is None:
            return self.runtime_root / "runs"
        return self.runtime_root / "runs" / run_id

    def test_results_dir_path(self, run_id: str, stamp: str | None = None) -> Path:
        root = self.run_dir_path(run_id) / "test-results"
        if not stamp:
            return root
        return root / stamp

    def tree_diffs_dir_path(self, run_id: str | None = None, name: str | None = None) -> Path:
        if run_id:
            root = self.run_dir_path(run_id) / "tree-diffs"
        else:
            root = self.runtime_root / "tree-diffs"
        if not name:
            return root
        return root / name

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
    ) -> StateRepositoryPaths:
        run_dir = self.run_dir_path(state.run_id)
        run_dir.mkdir(parents=True, exist_ok=True)

        run_state_path = run_dir / "run_state.json"
        dump_state(state, str(run_state_path))
        self.run_state_path().write_text(run_state_path.read_text(encoding="utf-8"), encoding="utf-8")
        emit("state.save", run_id=state.run_id, path=str(run_state_path))
        emit("state.fingerprint.after_save", run_id=state.run_id, state_fingerprint=self._state_fingerprint(state))

        runtime_map = runtime_map_builder(state)
        runtime_map_text = json.dumps(runtime_map, indent=2, sort_keys=True)
        (run_dir / "runtime_map.json").write_text(runtime_map_text, encoding="utf-8")
        self.runtime_map_path().write_text(runtime_map_text, encoding="utf-8")
        emit("runtime_map.write", path=str(run_dir / "runtime_map.json"))
        emit(
            "runtime_map.fingerprint",
            run_id=state.run_id,
            runtime_map_fingerprint=self._text_fingerprint(runtime_map_text),
        )

        ports_manifest = {
            "run_id": state.run_id,
            "mode": state.mode,
            "projects": [self._context_ports_payload(context) for context in contexts],
        }
        ports_manifest_text = json.dumps(ports_manifest, indent=2, sort_keys=True)
        (run_dir / "ports_manifest.json").write_text(ports_manifest_text, encoding="utf-8")
        self.ports_manifest_path().write_text(ports_manifest_text, encoding="utf-8")

        error_report = {
            "run_id": state.run_id,
            "errors": errors,
            "generated_at": datetime.now(tz=UTC).isoformat(),
        }
        error_report_text = json.dumps(error_report, indent=2, sort_keys=True)
        (run_dir / "error_report.json").write_text(error_report_text, encoding="utf-8")
        self.error_report_path().write_text(error_report_text, encoding="utf-8")

        events_path = run_dir / "events.jsonl"
        with events_path.open("w", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event, sort_keys=True) + "\n")
        events_text = events_path.read_text(encoding="utf-8")
        (self.runtime_root / "events.jsonl").write_text(events_text, encoding="utf-8")

        if write_runtime_readiness_report is not None:
            write_runtime_readiness_report(run_dir)

        self._write_scoped_pointers(run_state_path=run_state_path, state=state, contexts=contexts)

        if self.compat_mode == self.COMPAT_READ_WRITE:
            self._write_legacy_compat(
                run_state_path=run_state_path,
                runtime_map_text=runtime_map_text,
                ports_manifest_text=ports_manifest_text,
                error_report_text=error_report_text,
                events_text=events_text,
                state=state,
                contexts=contexts,
            )

        return StateRepositoryPaths(run_dir=run_dir, run_state=run_state_path)

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
    ) -> dict[str, object]:
        return self._save_runtime_update(
            state=state,
            emit=emit,
            runtime_map_builder=runtime_map_builder,
        )

    def load_latest(self, *, mode: str | None = None, strict_mode_match: bool = False) -> RunState | None:
        allowed_root = str(self.runtime_dir)

        def load_for_mode(expected_mode: str | None) -> RunState | None:
            def candidate_matches(candidate: RunState) -> bool:
                if expected_mode is not None and candidate.mode != expected_mode:
                    return False
                return self._state_matches_scope(candidate)

            candidate = self._load_state_file_candidate(self.run_state_path(), allowed_root=allowed_root)
            if candidate is not None and candidate_matches(candidate):
                return candidate

            candidate = self._load_legacy_shell_candidate(
                self.runtime_root / "run_state.state", allowed_root=allowed_root
            )
            if candidate is not None and candidate_matches(candidate):
                return candidate

            candidate = self._load_pointer_candidates(
                self._ordered_scoped_pointers(mode=expected_mode),
                allowed_root=allowed_root,
                predicate=candidate_matches,
            )
            if candidate is not None:
                return candidate

            if self.compat_mode == self.SCOPED_ONLY:
                return None

            candidate = self._load_state_file_candidate(
                self.runtime_legacy_root / "run_state.json",
                allowed_root=allowed_root,
            )
            if candidate is not None and candidate_matches(candidate):
                return candidate

            candidate = self._load_legacy_shell_candidate(
                self.runtime_legacy_root / "run_state.state",
                allowed_root=allowed_root,
            )
            if candidate is not None and candidate_matches(candidate):
                return candidate

            candidate = self._load_pointer_candidates(
                self._ordered_legacy_pointers(mode=expected_mode),
                allowed_root=allowed_root,
                predicate=candidate_matches,
            )
            if candidate is not None:
                return candidate
            return None

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
    ) -> dict[str, object]:
        run_state_path = self._runtime_update_run_state_path(state)
        run_state_path.parent.mkdir(parents=True, exist_ok=True)
        dump_state(state, str(run_state_path))
        self.run_state_path().write_text(run_state_path.read_text(encoding="utf-8"), encoding="utf-8")
        emit("state.save", run_id=state.run_id, path=str(run_state_path))
        emit("state.fingerprint.after_save", run_id=state.run_id, state_fingerprint=self._state_fingerprint(state))

        runtime_map = runtime_map_builder(state)
        runtime_map_text = json.dumps(runtime_map, indent=2, sort_keys=True)
        run_state_path.parent.mkdir(parents=True, exist_ok=True)
        (run_state_path.parent / "runtime_map.json").write_text(runtime_map_text, encoding="utf-8")
        self.runtime_map_path().write_text(runtime_map_text, encoding="utf-8")
        emit("runtime_map.write", path=str(self.runtime_map_path()))
        emit(
            "runtime_map.fingerprint",
            run_id=state.run_id,
            runtime_map_fingerprint=self._text_fingerprint(runtime_map_text),
        )

        project_names = self._project_names_from_state(state)
        self._write_mode_pointers(
            root=self.runtime_root,
            run_state_path=run_state_path,
            mode=state.mode,
            project_names=project_names,
        )

        if self.compat_mode == self.COMPAT_READ_WRITE:
            self.runtime_legacy_root.mkdir(parents=True, exist_ok=True)
            (self.runtime_legacy_root / "run_state.json").write_text(
                run_state_path.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (self.runtime_legacy_root / "runtime_map.json").write_text(runtime_map_text, encoding="utf-8")
            self._write_mode_pointers(
                root=self.runtime_legacy_root,
                run_state_path=run_state_path,
                mode=state.mode,
                project_names=project_names,
            )

        return runtime_map

    def load_by_pointer(self, pointer_path: str) -> RunState:
        return load_state_from_pointer(pointer_path, allowed_root=str(self.runtime_dir))

    def _load_state_file_candidate(self, path: Path, *, allowed_root: str) -> RunState | None:
        if not path.is_file():
            return None
        try:
            return load_state(str(path), allowed_root=allowed_root)
        except Exception:
            return None

    def _load_legacy_shell_candidate(self, path: Path, *, allowed_root: str) -> RunState | None:
        if not path.is_file():
            return None
        try:
            return load_legacy_shell_state(str(path), allowed_root=allowed_root)
        except Exception:
            return None

    def _load_pointer_candidates(
        self,
        pointers: list[Path],
        *,
        allowed_root: str,
        predicate: Callable[[RunState], bool],
    ) -> RunState | None:
        for pointer in pointers:
            try:
                candidate = load_state_from_pointer(str(pointer), allowed_root=allowed_root)
            except Exception:
                continue
            if predicate(candidate):
                return candidate
        return None

    def purge(self, *, aggressive: bool = False) -> None:
        scoped_paths = (
            self.run_state_path(),
            self.runtime_map_path(),
            self.ports_manifest_path(),
            self.error_report_path(),
            self.runtime_root / "events.jsonl",
            self.runtime_root / "runtime_readiness_report.json",
            self.runtime_root / ".last_state",
            self.runtime_root / ".last_state.main",
        )
        for path in scoped_paths:
            path.unlink(missing_ok=True)
        for pointer in self.runtime_root.glob(".last_state.trees.*"):
            pointer.unlink(missing_ok=True)

        if self.compat_mode != self.SCOPED_ONLY:
            legacy_paths = (
                self.runtime_legacy_root / "run_state.json",
                self.runtime_legacy_root / "runtime_map.json",
                self.runtime_legacy_root / "ports_manifest.json",
                self.runtime_legacy_root / "error_report.json",
                self.runtime_legacy_root / "events.jsonl",
                self.runtime_legacy_root / "runtime_readiness_report.json",
                self.runtime_legacy_root / ".last_state",
                self.runtime_legacy_root / ".last_state.main",
            )
            for path in legacy_paths:
                path.unlink(missing_ok=True)
            for pointer in self.runtime_legacy_root.glob(".last_state.trees.*"):
                pointer.unlink(missing_ok=True)

        if aggressive:
            for runs_dir in (self.runtime_root / "runs", self.runtime_legacy_root / "runs"):
                if runs_dir.is_dir():
                    shutil.rmtree(runs_dir, ignore_errors=True)

    def _ordered_scoped_pointers(self, *, mode: str | None) -> list[Path]:
        main_pointer = self.runtime_root / ".last_state.main"
        tree_pointers = sorted(self.runtime_root.glob(".last_state.trees.*"))
        generic_pointer = self.runtime_root / ".last_state"
        if mode == "trees":
            return [*tree_pointers, generic_pointer, main_pointer]
        if mode == "main":
            return [main_pointer, generic_pointer, *tree_pointers]
        return [main_pointer, *tree_pointers, generic_pointer]

    def _ordered_legacy_pointers(self, *, mode: str | None) -> list[Path]:
        main_pointer = self.runtime_legacy_root / ".last_state.main"
        tree_pointers = sorted(self.runtime_legacy_root.glob(".last_state.trees.*"))
        generic_pointer = self.runtime_legacy_root / ".last_state"
        if mode == "trees":
            return [*tree_pointers, generic_pointer, main_pointer]
        if mode == "main":
            return [main_pointer, generic_pointer, *tree_pointers]
        return [main_pointer, *tree_pointers, generic_pointer]

    def _state_matches_scope(self, state: RunState) -> bool:
        scope = state.metadata.get("repo_scope_id")
        if isinstance(scope, str) and scope:
            return scope == self.runtime_scope_id
        return True

    def _context_ports_payload(self, context: object) -> dict[str, object]:
        ports = getattr(context, "ports", {})
        payload_ports: dict[str, object] = {}
        if isinstance(ports, dict):
            for key, plan in ports.items():
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

    def _write_scoped_pointers(self, *, run_state_path: Path, state: RunState, contexts: list[object]) -> None:
        self._write_mode_pointers(
            root=self.runtime_root,
            run_state_path=run_state_path,
            mode=state.mode,
            project_names=self._context_names(contexts),
        )

    def _write_legacy_compat(
        self,
        *,
        run_state_path: Path,
        runtime_map_text: str,
        ports_manifest_text: str,
        error_report_text: str,
        events_text: str,
        state: RunState,
        contexts: list[object],
    ) -> None:
        self.runtime_legacy_root.mkdir(parents=True, exist_ok=True)
        (self.runtime_legacy_root / "run_state.json").write_text(
            run_state_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (self.runtime_legacy_root / "runtime_map.json").write_text(runtime_map_text, encoding="utf-8")
        (self.runtime_legacy_root / "ports_manifest.json").write_text(ports_manifest_text, encoding="utf-8")
        (self.runtime_legacy_root / "error_report.json").write_text(error_report_text, encoding="utf-8")
        (self.runtime_legacy_root / "events.jsonl").write_text(events_text, encoding="utf-8")
        self._write_mode_pointers(
            root=self.runtime_legacy_root,
            run_state_path=run_state_path,
            mode=state.mode,
            project_names=self._context_names(contexts),
        )

    @staticmethod
    def _context_names(contexts: list[object]) -> list[str]:
        names: set[str] = set()
        for context in contexts:
            name = str(getattr(context, "name", "")).strip()
            if name:
                names.add(name)
        return sorted(names, key=str.lower)

    def _project_names_from_state(self, state: RunState) -> list[str]:
        names: set[str] = set()
        for project in state.requirements:
            normalized = str(project).strip()
            if normalized:
                names.add(normalized)
        for service_name in state.services:
            project_name = self._project_name_from_service_name(service_name)
            if project_name:
                names.add(project_name)
        if state.mode == "main":
            names.add("Main")
        return sorted(names, key=str.lower)

    @staticmethod
    def _text_fingerprint(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _state_fingerprint(state: RunState) -> str:
        serialized = json.dumps(state_to_dict(state), sort_keys=True)
        return RuntimeStateRepository._text_fingerprint(serialized)

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

    def _runtime_update_run_state_path(self, state: RunState) -> Path:
        run_id = str(getattr(state, "run_id", "")).strip()
        if not run_id:
            return self.run_state_path()
        return self.run_dir_path(run_id) / "run_state.json"

    def _write_mode_pointers(
        self,
        *,
        root: Path,
        run_state_path: Path,
        mode: str,
        project_names: list[str],
    ) -> None:
        root.mkdir(parents=True, exist_ok=True)
        pointer_text = str(run_state_path) + "\n"
        (root / ".last_state").write_text(pointer_text, encoding="utf-8")
        existing_tree_pointers = sorted(root.glob(".last_state.trees.*"))
        if mode == "main":
            (root / ".last_state.main").write_text(pointer_text, encoding="utf-8")
            return

        expected_tree_pointer_names: set[str] = set()
        for project_name in project_names:
            normalized_project = str(project_name).strip()
            if not normalized_project or normalized_project.lower() == "main":
                continue
            pointer_name = f".last_state.trees.{normalized_project}"
            expected_tree_pointer_names.add(pointer_name)
            (root / pointer_name).write_text(pointer_text, encoding="utf-8")

        for pointer in existing_tree_pointers:
            if pointer.name not in expected_tree_pointer_names:
                pointer.unlink(missing_ok=True)
