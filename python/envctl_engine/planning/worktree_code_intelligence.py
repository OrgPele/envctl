from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


WORKTREE_CODE_INTELLIGENCE_SCHEMA_VERSION = 1
WORKTREE_CODE_INTELLIGENCE_PATH = Path(".envctl-state") / "code-intelligence.json"
WORKTREE_CGC_DATABASE_DEFAULT = "kuzudb"

_WORKTREE_CODE_INTELLIGENCE_DISABLED_VALUES = frozenset(("disabled", "disable", "off", "false", "0", "no"))
_WORKTREE_CODE_INTELLIGENCE_ENABLED_VALUES = frozenset(("auto", "enabled", "enable", "on", "true", "1", "yes"))
_WORKTREE_CGC_INDEX_DISABLED_VALUES = frozenset(("disabled", "disable", "off", "false", "0", "no"))
_WORKTREE_CGC_INDEX_ENABLED_VALUES = frozenset(("enabled", "enable", "on", "true", "1", "yes"))
_WORKTREE_CGC_INDEX_AUTO_VALUES = frozenset(("auto",))
_WORKTREE_CGC_INDEX_MODE_AUTO = "auto"
_WORKTREE_CGC_INDEX_MODE_DISABLED = "disabled"
_WORKTREE_CGC_INDEX_MODE_ENABLED = "enabled"


@dataclass(frozen=True)
class WorktreeCodeIntelligenceIdentity:
    worktree_name: str
    feature: str
    iteration: str
    cgc_context: str
    serena_project_name: str


def prepare_worktree_code_intelligence(
    self: Any,
    *,
    target: Path,
    trees_root_for_worktree: Callable[[Any, Path], Path],
) -> None:
    if not target.is_dir() or not _worktree_code_intelligence_enabled(self):
        return
    identity = _worktree_code_intelligence_identity(
        self,
        target=target,
        trees_root_for_worktree=trees_root_for_worktree,
    )
    copied_files: dict[str, bool] = {}
    cgc_result: dict[str, object] = {
        "cgc_index_mode": _WORKTREE_CGC_INDEX_MODE_DISABLED,
        "cgc_index_requested": False,
        "cgc_available": None,
        "cgc_context_managed": False,
        "cgc_context_created": False,
        "cgc_context_already_exists": False,
        "cgc_context_returncode": None,
        "cgc_index_succeeded": False,
        "cgc_index_returncode": None,
        "cgc_commands": [],
    }
    copied_files[".serena/project.yml"] = _copy_worktree_serena_project_file(
        source=self.config.base_dir / ".serena" / "project.yml",
        target=target / ".serena" / "project.yml",
        project_name=identity.serena_project_name,
        emit=getattr(self, "_emit", None),
    )
    copied_files[".serena/.gitignore"] = _copy_worktree_code_intelligence_file(
        source=self.config.base_dir / ".serena" / ".gitignore",
        target=target / ".serena" / ".gitignore",
    )
    copied_files[".cgcignore"] = _copy_worktree_code_intelligence_file(
        source=self.config.base_dir / ".cgcignore",
        target=target / ".cgcignore",
    )
    cgc_mode = _worktree_cgc_index_mode(self)
    if cgc_mode == _WORKTREE_CGC_INDEX_MODE_ENABLED:
        cgc_result = _index_worktree_with_cgc(self, target=target, context=identity.cgc_context)
    elif cgc_mode == _WORKTREE_CGC_INDEX_MODE_AUTO:
        cgc_result = _reuse_or_index_worktree_with_cgc(self, target=target, context=identity.cgc_context)
    _write_worktree_code_intelligence_metadata(
        target=target,
        identity=identity,
        copied_files=copied_files,
        cgc_database=_worktree_cgc_database(self),
        cgc_result=cgc_result,
    )


def _copy_worktree_code_intelligence_file(*, source: Path, target: Path) -> bool:
    if not source.is_file() or target.exists() or target.is_symlink():
        return False
    try:
        text = source.read_text(encoding="utf-8")
    except OSError:
        return False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    except OSError:
        return False
    return True


def _copy_worktree_serena_project_file(
    *,
    source: Path,
    target: Path,
    project_name: str,
    emit: Callable[..., object] | None,
) -> bool:
    if not source.is_file() or target.exists() or target.is_symlink():
        return False
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        if emit:
            emit(
                "setup.worktree.code_intelligence.serena_config",
                target=str(target),
                project_name=project_name,
                success=False,
                error=str(exc),
            )
        return False
    rewritten = _rewrite_serena_project_name(text, project_name=project_name)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rewritten, encoding="utf-8")
    except OSError as exc:
        if emit:
            emit(
                "setup.worktree.code_intelligence.serena_config",
                target=str(target),
                project_name=project_name,
                success=False,
                error=str(exc),
            )
        return False
    if emit:
        emit(
            "setup.worktree.code_intelligence.serena_config",
            target=str(target),
            project_name=project_name,
            success=True,
        )
    return True


def _rewrite_serena_project_name(text: str, *, project_name: str) -> str:
    pattern = re.compile(
        r"^(?P<prefix>project_name:\s*)(?P<quote>[\"']?)(?P<value>.*?)(?P=quote)(?P<suffix>\s*)$",
        re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        return f"project_name: {project_name}\n{text}"
    quote = match.group("quote") or ""
    replacement = f"{match.group('prefix')}{quote}{project_name}{quote}{match.group('suffix')}"
    return text[: match.start()] + replacement + text[match.end() :]


def _worktree_code_intelligence_enabled(self: Any) -> bool:
    raw = str(
        self.env.get("ENVCTL_WORKTREE_CODE_INTELLIGENCE")
        or self.config.raw.get("ENVCTL_WORKTREE_CODE_INTELLIGENCE")
        or "auto"
    ).strip().lower()
    if raw in _WORKTREE_CODE_INTELLIGENCE_ENABLED_VALUES:
        return True
    if raw in _WORKTREE_CODE_INTELLIGENCE_DISABLED_VALUES:
        return False
    raise RuntimeError(
        "Invalid ENVCTL_WORKTREE_CODE_INTELLIGENCE value. "
        "Use auto/on/true or off/false."
    )


def _worktree_cgc_index_mode(self: Any) -> str:
    raw = str(
        self.env.get("ENVCTL_WORKTREE_CGC_INDEX")
        or self.config.raw.get("ENVCTL_WORKTREE_CGC_INDEX")
        or "auto"
    ).strip().lower()
    if raw in _WORKTREE_CGC_INDEX_ENABLED_VALUES:
        return _WORKTREE_CGC_INDEX_MODE_ENABLED
    if raw in _WORKTREE_CGC_INDEX_DISABLED_VALUES:
        return _WORKTREE_CGC_INDEX_MODE_DISABLED
    if raw in _WORKTREE_CGC_INDEX_AUTO_VALUES:
        repo_root = self.config.base_dir
        if (repo_root / ".cgcignore").is_file() or (repo_root / ".codegraphcontext").exists():
            return _WORKTREE_CGC_INDEX_MODE_AUTO
        return _WORKTREE_CGC_INDEX_MODE_DISABLED
    raise RuntimeError("Invalid ENVCTL_WORKTREE_CGC_INDEX value. Use auto/on/true or off/false.")


def _worktree_code_intelligence_identity(
    self: Any,
    *,
    target: Path,
    trees_root_for_worktree: Callable[[Any, Path], Path],
) -> WorktreeCodeIntelligenceIdentity:
    source_project = _read_source_serena_project_name(self.config.base_dir) or self.config.base_dir.name or "project"
    worktree_name, feature, iteration = _worktree_identity_parts(
        self,
        target=target,
        trees_root_for_worktree=trees_root_for_worktree,
    )
    serena_template = _worktree_template_value(
        self,
        env_key="ENVCTL_WORKTREE_SERENA_PROJECT_TEMPLATE",
        default="{project}-{worktree}",
    )
    cgc_template = _worktree_template_value(
        self,
        env_key="ENVCTL_WORKTREE_CGC_CONTEXT_TEMPLATE",
        default="{project}-{worktree}",
    )
    serena_project = _render_worktree_identity_template(
        serena_template,
        project=_sanitize_worktree_identity(source_project, lowercase=True),
        worktree=worktree_name,
        feature=feature,
        iteration=iteration,
    )
    cgc_context = _render_worktree_identity_template(
        cgc_template,
        project=_sanitize_worktree_identity(source_project, titlecase=True),
        worktree=worktree_name,
        feature=feature,
        iteration=iteration,
    )
    return WorktreeCodeIntelligenceIdentity(
        worktree_name=worktree_name,
        feature=feature,
        iteration=iteration,
        serena_project_name=serena_project,
        cgc_context=cgc_context,
    )


def _read_source_serena_project_name(repo_root: Path) -> str:
    path = repo_root / ".serena" / "project.yml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    match = re.search(r"^project_name:\s*[\"']?(.*?)[\"']?\s*$", text, flags=re.MULTILINE)
    return str(match.group(1)).strip() if match else ""


def _worktree_identity_parts(
    self: Any,
    *,
    target: Path,
    trees_root_for_worktree: Callable[[Any, Path], Path],
) -> tuple[str, str, str]:
    trees_root = trees_root_for_worktree(self, target)
    try:
        relative = target.resolve().relative_to(trees_root.resolve())
    except ValueError:
        relative = Path(target.name)
    parts = list(relative.parts)
    if not parts:
        parts = [target.name]
    iteration = _sanitize_worktree_identity(parts[-1])
    feature_raw = "_".join(parts[:-1]) if len(parts) > 1 else parts[0]
    feature = _sanitize_worktree_identity(feature_raw)
    worktree_name = _sanitize_worktree_identity(f"{feature}-{iteration}")
    return worktree_name, feature, iteration


def _worktree_template_value(self: Any, *, env_key: str, default: str) -> str:
    raw = self.env.get(env_key) or self.config.raw.get(env_key) or default
    value = str(raw).strip()
    return value or default


def _render_worktree_identity_template(
    template: str,
    *,
    project: str,
    worktree: str,
    feature: str,
    iteration: str,
) -> str:
    values = {
        "project": project,
        "worktree": worktree,
        "feature": feature,
        "iteration": iteration,
    }
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", value)
    return _sanitize_worktree_identity(rendered) or worktree


def _sanitize_worktree_identity(raw: str, *, lowercase: bool = False, titlecase: bool = False, limit: int = 96) -> str:
    text = str(raw or "").strip()
    if lowercase:
        text = text.lower()
    text = text.replace("/", "_").replace("\\", "_").replace(".", "-")
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", text)
    text = re.sub(r"_+", "_", text)
    text = re.sub(r"-+", "-", text)
    text = text.strip("_-")
    if titlecase:
        pieces = re.split(r"([_-])", text)
        text = "".join(piece[:1].upper() + piece[1:] if piece not in {"_", "-"} else piece for piece in pieces)
    if len(text) > limit:
        text = text[:limit].rstrip("_-")
    return text or "worktree"


def _worktree_cgc_database(self: Any) -> str:
    for raw in (
        self.env.get("ENVCTL_WORKTREE_CGC_DATABASE"),
        self.config.raw.get("ENVCTL_WORKTREE_CGC_DATABASE"),
    ):
        value = str(raw or "").strip()
        if value:
            return _sanitize_worktree_identity(value)
    return WORKTREE_CGC_DATABASE_DEFAULT


def _source_cgc_context(self: Any) -> str:
    for raw in (
        self.env.get("ENVCTL_WORKTREE_CGC_SOURCE_CONTEXT"),
        self.config.raw.get("ENVCTL_WORKTREE_CGC_SOURCE_CONTEXT"),
    ):
        value = str(raw or "").strip()
        if value:
            return _sanitize_worktree_identity(value)
    source_project = _read_source_serena_project_name(self.config.base_dir) or self.config.base_dir.name or "project"
    return _sanitize_worktree_identity(source_project, titlecase=True)


def _short_command_output(value: object, *, limit: int = 500) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _cgc_context_already_exists(result: object) -> bool:
    combined = f"{getattr(result, 'stdout', '')}\n{getattr(result, 'stderr', '')}".lower()
    return "already exists" in combined or "already exist" in combined


def _reuse_or_index_worktree_with_cgc(self: Any, *, target: Path, context: str) -> dict[str, object]:
    source_context = _source_cgc_context(self)
    metadata: dict[str, object] = {
        "cgc_index_mode": _WORKTREE_CGC_INDEX_MODE_AUTO,
        "cgc_index_requested": False,
        "cgc_available": False,
        "cgc_context_managed": False,
        "cgc_context_created": False,
        "cgc_context_already_exists": False,
        "cgc_context_returncode": None,
        "cgc_index_succeeded": False,
        "cgc_index_returncode": None,
        "cgc_commands": [],
        "cgc_source_context": source_context,
        "cgc_active_context": source_context,
    }
    if not getattr(self, "_command_exists", lambda _name: False)("cgc"):
        metadata["cgc_active_context"] = context
        metadata["cgc_index_skipped_reason"] = "cgc_not_available"
        return metadata
    metadata["cgc_available"] = True
    commands = metadata["cgc_commands"]
    assert isinstance(commands, list)
    list_command = ["cgc", "list", "--context", source_context]
    try:
        result = self.process_runner.run(
            list_command,
            cwd=self.config.base_dir,
            env=self._command_env(port=0),
            timeout=30.0,
        )
    except OSError as exc:
        commands.append({"command": list_command, "error": str(exc)})
        self._emit(
            "setup.worktree.code_intelligence.cgc_reuse",
            target=str(target.resolve()),
            source_context=source_context,
            success=False,
            error=str(exc),
        )
        indexed = _index_worktree_with_cgc(self, target=target, context=context)
        indexed["cgc_index_mode"] = _WORKTREE_CGC_INDEX_MODE_AUTO
        indexed["cgc_source_context"] = source_context
        indexed_commands = indexed.get("cgc_commands")
        if isinstance(indexed_commands, list):
            indexed_commands.insert(0, commands[0])
        return indexed
    returncode = getattr(result, "returncode", 1)
    raw_stdout = str(getattr(result, "stdout", "") or "")
    raw_stderr = str(getattr(result, "stderr", "") or "")
    stdout = _short_command_output(raw_stdout)
    stderr = _short_command_output(raw_stderr)
    source_root = str(self.config.base_dir.resolve())
    source_matches = returncode == 0 and source_root in f"{raw_stdout}\n{raw_stderr}"
    commands.append(
        {
            "command": list_command,
            "returncode": returncode,
            "stdout": stdout,
            "stderr": stderr,
        }
    )
    self._emit(
        "setup.worktree.code_intelligence.cgc_reuse",
        target=str(target.resolve()),
        source_context=source_context,
        source_root=source_root,
        success=source_matches,
        returncode=returncode,
    )
    if source_matches:
        metadata["cgc_index_skipped_reason"] = "source_context_reused"
        return metadata
    indexed = _index_worktree_with_cgc(self, target=target, context=context)
    indexed["cgc_index_mode"] = _WORKTREE_CGC_INDEX_MODE_AUTO
    indexed["cgc_source_context"] = source_context
    indexed["cgc_reuse_returncode"] = returncode
    indexed["cgc_reuse_stdout"] = stdout
    indexed["cgc_reuse_stderr"] = stderr
    indexed_commands = indexed.get("cgc_commands")
    if isinstance(indexed_commands, list):
        indexed_commands.insert(0, commands[0])
    return indexed


def _index_worktree_with_cgc(self: Any, *, target: Path, context: str) -> dict[str, object]:
    database = _worktree_cgc_database(self)
    metadata: dict[str, object] = {
        "cgc_index_mode": _WORKTREE_CGC_INDEX_MODE_ENABLED,
        "cgc_index_requested": True,
        "cgc_available": False,
        "cgc_context_managed": False,
        "cgc_context_created": False,
        "cgc_context_already_exists": False,
        "cgc_context_returncode": None,
        "cgc_index_succeeded": False,
        "cgc_index_returncode": None,
        "cgc_commands": [],
    }
    if not getattr(self, "_command_exists", lambda _name: False)("cgc"):
        return metadata
    metadata["cgc_available"] = True
    context_command = ["cgc", "context", "create", context]
    if database:
        context_command.extend(["--database", database])
    commands = metadata["cgc_commands"]
    assert isinstance(commands, list)
    try:
        context_result = self.process_runner.run(
            context_command,
            cwd=target,
            env=self._command_env(port=0),
            timeout=600.0,
        )
    except OSError as exc:
        self._emit(
            "setup.worktree.code_intelligence.cgc_context",
            target=str(target.resolve()),
            context=context,
            database=database,
            success=False,
            error=str(exc),
        )
        commands.append({"command": context_command, "error": str(exc)})
        return metadata
    context_returncode = getattr(context_result, "returncode", 1)
    already_exists = context_returncode != 0 and _cgc_context_already_exists(context_result)
    context_success = context_returncode == 0 or already_exists
    metadata["cgc_context_returncode"] = context_returncode
    metadata["cgc_context_created"] = context_returncode == 0
    metadata["cgc_context_already_exists"] = already_exists
    metadata["cgc_context_managed"] = context_success
    commands.append(
        {
            "command": context_command,
            "returncode": context_returncode,
            "stdout": _short_command_output(getattr(context_result, "stdout", "")),
            "stderr": _short_command_output(getattr(context_result, "stderr", "")),
        }
    )
    context_payload: dict[str, object] = {
        "target": str(target.resolve()),
        "context": context,
        "database": database,
        "created": context_returncode == 0,
        "already_exists": already_exists,
        "success": context_success,
        "returncode": context_returncode,
    }
    if not context_success:
        context_payload["stdout"] = _short_command_output(getattr(context_result, "stdout", ""))
        context_payload["stderr"] = _short_command_output(getattr(context_result, "stderr", ""))
    self._emit("setup.worktree.code_intelligence.cgc_context", **context_payload)
    if not context_success:
        return metadata

    index_command = ["cgc", "index", str(target), "--context", context]
    try:
        result = self.process_runner.run(
            index_command,
            cwd=target,
            env=self._command_env(port=0),
            timeout=600.0,
        )
    except OSError as exc:
        self._emit(
            "setup.worktree.code_intelligence.cgc_index",
            target=str(target.resolve()),
            context=context,
            command=index_command,
            success=False,
            error=str(exc),
        )
        commands.append({"command": index_command, "error": str(exc)})
        return metadata
    returncode = getattr(result, "returncode", 1)
    metadata["cgc_index_returncode"] = returncode
    metadata["cgc_index_succeeded"] = returncode == 0
    commands.append(
        {
            "command": index_command,
            "returncode": returncode,
            "stdout": _short_command_output(getattr(result, "stdout", "")),
            "stderr": _short_command_output(getattr(result, "stderr", "")),
        }
    )
    index_payload: dict[str, object] = {
        "target": str(target.resolve()),
        "context": context,
        "command": index_command,
        "returncode": returncode,
        "success": returncode == 0,
    }
    if returncode != 0:
        index_payload["stdout"] = _short_command_output(getattr(result, "stdout", ""))
        index_payload["stderr"] = _short_command_output(getattr(result, "stderr", ""))
    self._emit(
        "setup.worktree.code_intelligence.cgc_index",
        **index_payload,
    )
    return metadata


def _write_worktree_code_intelligence_metadata(
    *,
    target: Path,
    identity: WorktreeCodeIntelligenceIdentity,
    copied_files: Mapping[str, bool],
    cgc_database: str,
    cgc_result: Mapping[str, object],
) -> None:
    if not target.is_dir():
        return
    payload: dict[str, object] = {
        "schema_version": WORKTREE_CODE_INTELLIGENCE_SCHEMA_VERSION,
        "serena_project_name": identity.serena_project_name,
        "cgc_context": identity.cgc_context,
        "cgc_active_context": identity.cgc_context,
        "worktree_name": identity.worktree_name,
        "feature": identity.feature,
        "iteration": identity.iteration,
        "files": dict(copied_files),
        "cgc_database": cgc_database,
    }
    payload.update(dict(cgc_result))
    path = target / WORKTREE_CODE_INTELLIGENCE_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return
