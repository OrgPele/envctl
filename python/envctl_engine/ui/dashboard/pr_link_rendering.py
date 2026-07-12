from __future__ import annotations

import concurrent.futures
import json
import shutil
import time
from pathlib import Path
from typing import Any

from envctl_engine.shared.services import service_for_project_type
from envctl_engine.state.models import RunState


def dashboard_project_pr(self: Any, *, state: RunState, project: str) -> tuple[str, str] | None:
    if not dashboard_pr_lookup_enabled(self):
        return None
    project_root = dashboard_project_root(self, state=state, project=project)
    if project_root is None:
        return None
    return dashboard_lookup_pr(self, project=project, project_root=project_root)


def dashboard_project_pr_map(
    self: Any,
    *,
    state: RunState,
    projects: list[str],
) -> dict[str, tuple[str, str] | None]:
    if not projects or not dashboard_pr_lookup_enabled(self):
        return {}
    if len(projects) <= 1:
        project = projects[0]
        return {project: dashboard_project_pr(self, state=state, project=project)}

    results: dict[str, tuple[str, str] | None] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(projects))) as executor:
        future_map = {
            executor.submit(dashboard_project_pr, self, state=state, project=project): project for project in projects
        }
        for future in concurrent.futures.as_completed(future_map):
            results[future_map[future]] = future.result()
    return results


def dashboard_pr_lookup_enabled(self: Any) -> bool:
    env = getattr(self, "env", {})
    if not isinstance(env, dict):
        return True
    raw = str(env.get("ENVCTL_DASHBOARD_PR_LINKS", "")).strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    return True


def dashboard_pr_cache_ttl_seconds(self: Any) -> float:
    env = getattr(self, "env", {})
    if not isinstance(env, dict):
        return 60.0
    raw = str(env.get("ENVCTL_DASHBOARD_PR_CACHE_SECONDS", "60")).strip()
    try:
        parsed = float(raw)
    except ValueError:
        return 60.0
    if parsed <= 0:
        return 0.0
    return parsed


def dashboard_project_root(self: Any, *, state: RunState, project: str) -> Path | None:
    metadata_roots = state.metadata.get("project_roots")
    if isinstance(metadata_roots, dict):
        root_raw = metadata_roots.get(project)
        if isinstance(root_raw, str) and root_raw.strip():
            return Path(root_raw).expanduser()

    for service_type in ("backend", "frontend"):
        service = service_for_project_type(state, project=project, service_type=service_type)
        cwd_raw = getattr(service, "cwd", None)
        if not isinstance(cwd_raw, str) or not cwd_raw.strip():
            continue
        cwd_path = Path(cwd_raw).expanduser()
        if cwd_path.name.lower() in {"backend", "frontend"}:
            return cwd_path.parent
        return cwd_path

    if project.strip().lower() == "main":
        base_dir = getattr(getattr(self, "config", None), "base_dir", None)
        if isinstance(base_dir, Path):
            return base_dir
        if isinstance(base_dir, str) and base_dir.strip():
            return Path(base_dir).expanduser()
    return None


def dashboard_relative_component_path(project_root: Path, component_path: Path) -> str:
    try:
        relative = component_path.relative_to(project_root)
    except ValueError:
        return str(component_path)
    if str(relative) == ".":
        return "."
    return str(relative)


def dashboard_lookup_pr(self: Any, *, project: str, project_root: Path) -> tuple[str, str] | None:
    if not project_root.exists():
        return None

    process_runner = getattr(self, "process_runner", None)
    run_cmd = getattr(process_runner, "run", None)
    if not callable(run_cmd):
        return None

    cache = getattr(self, "_dashboard_pr_url_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        setattr(self, "_dashboard_pr_url_cache", cache)
    now = time.monotonic()
    gh_bin = shutil.which("gh")
    if gh_bin is None:
        return None

    try:
        branch_result = run_cmd(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_root,
            timeout=1.5,
        )
        head_result = run_cmd(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            timeout=1.5,
        )
    except Exception:
        return None
    branch = first_non_empty_line(getattr(branch_result, "stdout", ""))
    head_oid = first_non_empty_line(getattr(head_result, "stdout", ""))
    if int(getattr(branch_result, "returncode", 1)) != 0 or not branch or branch == "HEAD":
        return None
    if int(getattr(head_result, "returncode", 1)) != 0 or not head_oid:
        return None

    cache_key = f"{project}|{project_root}|{branch}|{head_oid}"
    cache_entry = cache.get(cache_key)
    if isinstance(cache_entry, tuple) and len(cache_entry) == 2:
        expiry_raw, cached_pr = cache_entry
        if isinstance(expiry_raw, (int, float)) and now <= float(expiry_raw):
            if isinstance(cached_pr, tuple) and len(cached_pr) == 2:
                url_raw, state_raw = cached_pr
                if isinstance(url_raw, str) and isinstance(state_raw, str):
                    return (url_raw, state_raw)
            return None

    try:
        pr_result = run_cmd(
            [gh_bin, "pr", "list", "--head", branch, "--state", "all", "--json", "url,state,mergedAt,headRefOid"],
            cwd=project_root,
            timeout=2.5,
        )
    except Exception:
        cache[cache_key] = (now + dashboard_pr_cache_ttl_seconds(self), None)
        return None
    if int(getattr(pr_result, "returncode", 1)) != 0:
        cache[cache_key] = (now + dashboard_pr_cache_ttl_seconds(self), None)
        return None
    pr_info = select_dashboard_pr(getattr(pr_result, "stdout", ""), head_oid=head_oid)
    cache[cache_key] = (now + dashboard_pr_cache_ttl_seconds(self), pr_info)
    return pr_info


def select_dashboard_pr(raw: object, *, head_oid: str) -> tuple[str, str] | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list):
        return None

    merged_candidate: tuple[str, str] | None = None
    normalized_head_oid = head_oid.strip()
    for item in payload:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", "") or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            continue
        state = str(item.get("state", "") or "").strip().upper()
        if state == "OPEN":
            return (url, "active")
        if state == "MERGED":
            merged_at = str(item.get("mergedAt", "") or "").strip()
            pr_head_oid = str(item.get("headRefOid", "") or "").strip()
            if merged_at and pr_head_oid and pr_head_oid == normalized_head_oid and merged_candidate is None:
                merged_candidate = (url, "merged")
    return merged_candidate


def first_non_empty_line(value: object) -> str:
    if not isinstance(value, str):
        return ""
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if line:
            return line
    return ""
