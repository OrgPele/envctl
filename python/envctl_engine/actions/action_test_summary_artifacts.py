from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, ClassVar

from envctl_engine.shared.artifact_names import project_artifact_dir
from envctl_engine.actions.action_target_support import action_target_identities
from envctl_engine.actions.action_test_summary_collection import (
    collect_failed_test_manifest_entries,
    collect_failed_tests,
    collect_generic_suite_failures,
    collect_suite_failure_contexts,
)
from envctl_engine.actions.action_test_summary_formatting import format_summary_error_lines
from envctl_engine.actions.action_test_summary_git import default_git_state_components
from envctl_engine.actions.action_test_support import load_failed_test_manifest
from envctl_engine.runtime.runtime_context import save_resume_state, test_results_dir_path
from envctl_engine.state.runtime_map import build_runtime_map
from envctl_engine.test_output.failure_summary import extract_failure_summary_excerpt
from envctl_engine.test_output.parser_base import strip_ansi


def short_failed_summary_path(*, run_dir: Path, project_name: str) -> Path:
    digest = hashlib.sha1(project_name.encode("utf-8")).hexdigest()[:10]
    run_root = run_dir.parent.parent
    return run_root / f"ft_{digest}.txt"


@dataclass(frozen=True, slots=True)
class TestSummaryArtifactPersistor:
    __test__: ClassVar[bool] = False

    runtime: object
    route: object
    targets: list[object]
    outcomes: list[dict[str, object]]
    new_test_results_run_dir: Callable[[object, str], Path] | None = None
    write_failed_tests_summary_fn: Callable[..., dict[str, object]] | None = None
    runtime_map_builder: Callable[..., dict[str, object]] = build_runtime_map

    def persist(self) -> dict[str, dict[str, object]]:
        if not self.targets:
            return {}

        project_roots = self._project_roots()
        if not project_roots:
            return {}

        state = self.runtime.load_existing_state(mode=getattr(self.route, "mode", None))  # type: ignore[attr-defined]
        if state is None:
            return {}

        run_dir = self._run_dir(state)
        metadata = self._existing_summary_metadata(state)
        summaries = self._write_project_summaries(run_dir=run_dir, project_roots=project_roots, metadata=metadata)
        self._persist_metadata(state=state, run_dir=run_dir, metadata=metadata, summaries=summaries)
        return summaries

    def _project_roots(self) -> dict[str, Path]:
        project_roots = _project_roots_from_targets(self.targets)
        if project_roots:
            return project_roots
        return _project_roots_from_outcomes(self.outcomes)

    def _run_dir(self, state: object) -> Path:
        run_dir_builder = self.new_test_results_run_dir or new_test_results_run_dir_path
        return run_dir_builder(self.runtime, str(getattr(state, "run_id")))

    @staticmethod
    def _existing_summary_metadata(state: object) -> dict[str, object]:
        existing = getattr(state, "metadata", {}).get("project_test_summaries")
        return dict(existing) if isinstance(existing, dict) else {}

    def _write_project_summaries(
        self,
        *,
        run_dir: Path,
        project_roots: dict[str, Path],
        metadata: dict[str, object],
    ) -> dict[str, dict[str, object]]:
        writer = self.write_failed_tests_summary_fn or write_failed_tests_summary
        summaries: dict[str, dict[str, object]] = {}
        for project_name, project_root in project_roots.items():
            previous_entry = metadata.get(project_name)
            summaries[project_name] = writer(
                run_dir=run_dir,
                project_name=project_name,
                project_root=project_root,
                outcomes=self.outcomes,
                previous_entry=previous_entry if isinstance(previous_entry, dict) else None,
            )
        return summaries

    def _persist_metadata(
        self,
        *,
        state: Any,
        run_dir: Path,
        metadata: dict[str, object],
        summaries: dict[str, dict[str, object]],
    ) -> None:
        metadata.update(summaries)
        state.metadata["project_test_summaries"] = metadata
        state.metadata["project_test_results_root"] = str(run_dir)
        state.metadata["project_test_results_updated_at"] = datetime.now(tz=UTC).isoformat()

        save_resume_state(
            self.runtime,
            state=state,
            runtime_map_builder=self.runtime_map_builder,
        )
        self.runtime.emit(  # type: ignore[attr-defined]
            "test.summary.persisted",
            mode=getattr(self.route, "mode", None),
            projects=sorted(summaries),
            run_dir=str(run_dir),
        )


def persist_test_summary_artifacts(
    *,
    runtime: object,
    route: object,
    targets: list[object],
    outcomes: list[dict[str, object]],
    new_test_results_run_dir: Callable[[object, str], Path] | None = None,
    write_failed_tests_summary_fn: Callable[..., dict[str, object]] | None = None,
    runtime_map_builder: Callable[..., dict[str, object]] = build_runtime_map,
) -> dict[str, dict[str, object]]:
    return TestSummaryArtifactPersistor(
        runtime=runtime,
        route=route,
        targets=targets,
        outcomes=outcomes,
        new_test_results_run_dir=new_test_results_run_dir,
        write_failed_tests_summary_fn=write_failed_tests_summary_fn,
        runtime_map_builder=runtime_map_builder,
    ).persist()


def new_test_results_run_dir_path(runtime: object, run_id: str) -> Path:
    results_root = test_results_dir_path(runtime, run_id)
    results_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=UTC).strftime("run_%Y%m%d_%H%M%S")
    candidate = results_root / stamp
    if not candidate.exists():
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate
    suffix = 1
    while True:
        suffixed = results_root / f"{stamp}_{suffix}"
        if not suffixed.exists():
            suffixed.mkdir(parents=True, exist_ok=True)
            return suffixed
        suffix += 1


def _project_roots_from_targets(targets: list[object]) -> dict[str, Path]:
    return {identity.name: identity.root for identity in action_target_identities(targets)}


def _project_roots_from_outcomes(outcomes: list[dict[str, object]]) -> dict[str, Path]:
    project_roots: dict[str, Path] = {}
    for outcome in outcomes:
        name = str(outcome.get("project_name", "")).strip()
        root_raw = str(outcome.get("project_root", "")).strip()
        if not name or not root_raw:
            continue
        project_roots[name] = Path(root_raw)
    return project_roots


@dataclass(frozen=True, slots=True)
class FailedTestSummaryWriter:
    __test__: ClassVar[bool] = False

    run_dir: Path
    project_name: str
    project_root: Path
    outcomes: list[dict[str, object]]
    previous_entry: dict[str, object] | None = None
    short_failed_summary_path_fn: Callable[..., Path] = short_failed_summary_path
    format_summary_error_lines_fn: Callable[[str], list[str]] = format_summary_error_lines
    git_state_components_fn: Callable[[Path], tuple[str, str, int]] | None = None

    def write(self) -> dict[str, object]:
        output_dir = project_artifact_dir(self.run_dir, self.project_name)
        output_dir.mkdir(parents=True, exist_ok=True)
        paths = self._artifact_paths(output_dir)
        failures = collect_failed_tests(self.outcomes, project_name=self.project_name)
        generic_suite_failures = collect_generic_suite_failures(self.outcomes, project_name=self.project_name)
        suite_failure_contexts = collect_suite_failure_contexts(self.outcomes, project_name=self.project_name)
        manifest_entries = collect_failed_test_manifest_entries(self.outcomes, project_name=self.project_name)
        generated_at = datetime.now().astimezone()
        summary_text = self._summary_text(
            generated_at=generated_at,
            failures=failures,
            generic_suite_failures=generic_suite_failures,
            suite_failure_contexts=suite_failure_contexts,
        )
        paths["summary_path"].write_text(summary_text, encoding="utf-8")
        paths["short_summary_path"].write_text(summary_text, encoding="utf-8")

        head, status_hash, status_lines = self._write_git_state(paths["state_path"])
        self._write_manifest(
            paths["manifest_path"],
            generated_at=generated_at,
            head=head,
            status_hash=status_hash,
            status_lines=status_lines,
            manifest_entries=manifest_entries,
        )

        preserved = self._preserved_previous_entry(
            generated_at=generated_at,
            failures=failures,
            generic_suite_failures=generic_suite_failures,
            manifest_entries=manifest_entries,
        )
        if preserved is not None:
            return preserved

        return {
            "summary_path": str(paths["summary_path"]),
            "short_summary_path": str(paths["short_summary_path"]),
            "state_path": str(paths["state_path"]),
            "manifest_path": str(paths["manifest_path"]),
            "status": "failed" if failures or generic_suite_failures else "passed",
            "failed_tests": len(failures),
            "failed_manifest_entries": len(manifest_entries),
            "summary_excerpt": extract_failure_summary_excerpt(summary_text, max_lines=3),
            "updated_at": generated_at.isoformat(),
        }

    def _artifact_paths(self, output_dir: Path) -> dict[str, Path]:
        return {
            "summary_path": output_dir / "failed_tests_summary.txt",
            "short_summary_path": self.short_failed_summary_path_fn(
                run_dir=self.run_dir,
                project_name=self.project_name,
            ),
            "state_path": output_dir / "test_state.txt",
            "manifest_path": output_dir / "failed_tests_manifest.json",
        }

    def _summary_text(
        self,
        *,
        generated_at: datetime,
        failures: list[tuple[str, str, str]],
        generic_suite_failures: list[tuple[str, str]],
        suite_failure_contexts: list[tuple[str, str]],
    ) -> str:
        lines = [
            "# envctl Failed Test Summary",
            f"# Generated at: {generated_at.strftime('%a %b %d %H:%M:%S %Z %Y')}",
            "",
        ]
        if failures:
            self._append_failed_tests(lines, failures)
            self._append_suite_contexts(lines, suite_failure_contexts)
        elif generic_suite_failures:
            self._append_generic_suite_failures(lines, generic_suite_failures)
        else:
            lines.append("No failed tests.")
            lines.append("")
        return "\n".join(lines)

    def _append_failed_tests(self, lines: list[str], failures: list[tuple[str, str, str]]) -> None:
        for suite_name, failed_test, error_text in failures:
            clean_suite_name = strip_ansi(str(suite_name)).strip()
            clean_failed_test = strip_ansi(str(failed_test)).strip()
            lines.append(f"[{clean_suite_name}]")
            lines.append(f"- {clean_failed_test}")
            if error_text:
                for detail in self.format_summary_error_lines_fn(str(error_text)):
                    lines.append(f"    {detail}")
            lines.append("")

    def _append_suite_contexts(self, lines: list[str], suite_failure_contexts: list[tuple[str, str]]) -> None:
        for suite_name, context_text in suite_failure_contexts:
            clean_suite_name = strip_ansi(str(suite_name)).strip()
            lines.append(f"[{clean_suite_name}]")
            lines.append("suite context:")
            for detail in self.format_summary_error_lines_fn(str(context_text)):
                lines.append(f"    {detail}")
            lines.append("")

    def _append_generic_suite_failures(self, lines: list[str], generic_suite_failures: list[tuple[str, str]]) -> None:
        for suite_name, summary in generic_suite_failures:
            clean_suite_name = strip_ansi(str(suite_name)).strip()
            lines.append(f"[{clean_suite_name}]")
            lines.append("- suite failed before envctl could extract failed tests")
            for detail in self.format_summary_error_lines_fn(str(summary)):
                lines.append(f"    {detail}")
            lines.append("")

    def _write_git_state(self, state_path: Path) -> tuple[str, str, int]:
        state_components = self.git_state_components_fn or default_git_state_components
        head, status_hash, status_lines = state_components(self.project_root)
        state_path.write_text(
            f"state|{self.project_name}|{self.project_root}|{head}|{status_hash}|{status_lines}\n",
            encoding="utf-8",
        )
        return head, status_hash, status_lines

    def _write_manifest(
        self,
        manifest_path: Path,
        *,
        generated_at: datetime,
        head: str,
        status_hash: str,
        status_lines: int,
        manifest_entries: list[dict[str, object]],
    ) -> None:
        manifest_payload = {
            "generated_at": generated_at.isoformat(),
            "project_name": self.project_name,
            "project_root": str(self.project_root),
            "git_state": {
                "head": head,
                "status_hash": status_hash,
                "status_lines": status_lines,
            },
            "entries": manifest_entries,
        }
        manifest_path.write_text(json.dumps(manifest_payload, indent=2, sort_keys=True), encoding="utf-8")

    def _preserved_previous_entry(
        self,
        *,
        generated_at: datetime,
        failures: list[tuple[str, str, str]],
        generic_suite_failures: list[tuple[str, str]],
        manifest_entries: list[dict[str, object]],
    ) -> dict[str, object] | None:
        if not (
            self._failed_only()
            and not failures
            and bool(generic_suite_failures)
            and not manifest_entries
            and self.previous_entry is not None
        ):
            return None

        previous_manifest_path_raw = str(self.previous_entry.get("manifest_path", "") or "").strip()
        previous_manifest = (
            load_failed_test_manifest(Path(previous_manifest_path_raw)) if previous_manifest_path_raw else None
        )
        if previous_manifest is None or not previous_manifest.entries:
            return None
        preserved = dict(self.previous_entry)
        preserved["status"] = "failed"
        preserved["updated_at"] = generated_at.isoformat()
        preserved["preserved_after_failed_only_extraction_failure"] = True
        return preserved

    def _failed_only(self) -> bool:
        return any(
            bool(item.get("failed_only", False))
            for item in self.outcomes
            if str(item.get("project_name", "")).strip() == self.project_name
        )


def write_failed_tests_summary(
    *,
    run_dir: Path,
    project_name: str,
    project_root: Path,
    outcomes: list[dict[str, object]],
    previous_entry: dict[str, object] | None = None,
    short_failed_summary_path: Callable[..., Path] = short_failed_summary_path,
    format_summary_error_lines: Callable[[str], list[str]] = format_summary_error_lines,
    git_state_components: Callable[[Path], tuple[str, str, int]] | None = None,
) -> dict[str, object]:
    return FailedTestSummaryWriter(
        run_dir=run_dir,
        project_name=project_name,
        project_root=project_root,
        outcomes=outcomes,
        previous_entry=previous_entry,
        short_failed_summary_path_fn=short_failed_summary_path,
        format_summary_error_lines_fn=format_summary_error_lines,
        git_state_components_fn=git_state_components,
    ).write()


def persist_test_summary_artifacts_for_orchestrator(
    orchestrator: object,
    *,
    route: object,
    targets: list[object],
    outcomes: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    return persist_test_summary_artifacts(
        runtime=orchestrator.runtime,  # type: ignore[attr-defined]
        route=route,
        targets=targets,
        outcomes=outcomes,
        new_test_results_run_dir=lambda _runtime, run_id: new_test_results_run_dir_path(
            orchestrator.runtime,  # type: ignore[attr-defined]
            run_id,
        ),
        write_failed_tests_summary_fn=lambda **kwargs: write_failed_tests_summary_for_orchestrator(
            orchestrator,
            **kwargs,
        ),
        runtime_map_builder=build_runtime_map,
    )


def write_failed_tests_summary_for_orchestrator(
    orchestrator: object,
    *,
    run_dir: Path,
    project_name: str,
    project_root: Path,
    outcomes: list[dict[str, object]],
    previous_entry: dict[str, object] | None = None,
) -> dict[str, object]:
    from envctl_engine.actions import action_test_summary_support

    return action_test_summary_support.write_failed_tests_summary(
        run_dir=run_dir,
        project_name=project_name,
        project_root=project_root,
        outcomes=outcomes,
        previous_entry=previous_entry,
        short_failed_summary_path=short_failed_summary_path,
        format_summary_error_lines=format_summary_error_lines,
        git_state_components=default_git_state_components,
    )
