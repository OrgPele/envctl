from __future__ import annotations

from typing import Any, cast

from envctl_engine.requirements.supabase import build_supabase_project_name
from envctl_engine.runtime.command_router import Route
from envctl_engine.ui.status_symbols import STATUS_SUCCESS, STATUS_WARNING


def matches_blast_container(*, image: str, name: str) -> bool:
    image_l = image.lower()
    name_l = name.lower()
    return any(token in name_l or token in image_l for token in ("supabase", "n8n", "redis", "postgres"))


class BlastDockerCleanupSupport:
    runtime: Any

    def blast_all_docker_cleanup(self, *, route: Route | None) -> int:
        owner = cast(Any, self)
        code, stdout, _stderr = owner.run_best_effort_command(
            ["docker", "ps", "-a", "--format", "{{.ID}}|{{.Image}}|{{.Names}}"],
            timeout=10.0,
        )
        if code != 0:
            print("  Docker daemon unavailable; skipping Docker container cleanup.")
            return 0

        keep_worktree_storage, remove_main_storage = self.blast_all_volume_policy(route)
        if keep_worktree_storage:
            print("  Worktree Docker volumes: keep (override enabled)")
        else:
            print("  Worktree Docker volumes: remove (default)")
        if remove_main_storage:
            print("  Main Docker volumes: remove")
        else:
            print("  Main Docker volumes: keep")

        volume_candidates: list[str] = []
        removed = 0
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("|", 2)
            if len(parts) != 3:
                continue
            cid, image, name = parts
            if not self.blast_all_matches_container(image=image, name=name):
                continue
            is_main_container = self.blast_all_is_main_container(name)
            remove_container_storage = remove_main_storage if is_main_container else (not keep_worktree_storage)
            print(f"  Nuking container: {name} ({image})")
            if remove_container_storage:
                self.collect_container_volume_candidates(cid, volume_candidates)
                owner.run_best_effort_command(["docker", "rm", "-f", "-v", cid], timeout=20.0)
            else:
                owner.run_best_effort_command(["docker", "rm", "-f", cid], timeout=20.0)
            removed += 1
        self.remove_container_volume_candidates(volume_candidates)
        return removed

    def remove_container_volume_candidates(self, volume_candidates: list[str]) -> None:
        owner = cast(Any, self)
        for volume_name in volume_candidates:
            print(f"  Nuking volume: {volume_name}")
            rm_code, _rm_out, _rm_err = owner.run_best_effort_command(
                ["docker", "volume", "rm", volume_name],
                timeout=20.0,
            )
            if rm_code == 0:
                print(f"    {STATUS_SUCCESS} removed volume")
            else:
                print(f"    {STATUS_WARNING} volume not removed (in use or already deleted)")

    @staticmethod
    def blast_all_matches_container(*, image: str, name: str) -> bool:
        return matches_blast_container(image=image, name=name)

    def blast_all_volume_policy(self, route: Route | None) -> tuple[bool, bool]:
        keep_worktree_storage = False
        remove_main_storage: bool | None = None
        if route is not None:
            flag_keep_worktree = route.flags.get("blast_keep_worktree_volumes")
            if isinstance(flag_keep_worktree, bool):
                keep_worktree_storage = flag_keep_worktree
            flag_remove_main = route.flags.get("blast_remove_main_volumes")
            if isinstance(flag_remove_main, bool):
                remove_main_storage = flag_remove_main

        if remove_main_storage is None:
            if route is not None and self.runtime._batch_mode_requested(route):  # type: ignore[attr-defined]
                remove_main_storage = False
            elif self.runtime._can_interactive_tty():  # type: ignore[attr-defined]
                remove_main_storage = cast(Any, self).prompt_yes_no(
                    "Delete MAIN project Docker storage volumes as well? (y/N): "
                )
            else:
                remove_main_storage = False
        return keep_worktree_storage, bool(remove_main_storage)

    def blast_all_is_main_container(self, name: str) -> bool:
        name_l = name.lower()
        for candidate in self.blast_all_main_container_names():
            if candidate and name_l == candidate.lower():
                return True
        for supabase_project in self.blast_all_main_supabase_project_names():
            if supabase_project and name_l.startswith((supabase_project + "-").lower()):
                return True
        return False

    def blast_all_main_container_names(self) -> tuple[str, str]:
        config = self.runtime.config  # type: ignore[attr-defined]
        env = self.runtime.env  # type: ignore[attr-defined]
        docker_project_name = (
            env.get("DOCKER_PROJECT_NAME")
            or config.raw.get("DOCKER_PROJECT_NAME")
            or config.base_dir.name
            or "envctl"
        )
        db_container = (
            env.get("DB_CONTAINER_NAME")
            or config.raw.get("DB_CONTAINER_NAME")
            or f"{docker_project_name}-postgres"
        )
        redis_container = (
            env.get("REDIS_CONTAINER_NAME")
            or config.raw.get("REDIS_CONTAINER_NAME")
            or f"{docker_project_name}-redis"
        )
        return db_container, redis_container

    def blast_all_main_supabase_project_name(self) -> str:
        names = self.blast_all_main_supabase_project_names()
        return names[0] if names else "supportopia-supabase-main"

    def blast_all_main_supabase_project_names(self) -> tuple[str, ...]:
        config = self.runtime.config  # type: ignore[attr-defined]
        current = build_supabase_project_name(
            project_root=config.base_dir,
            project_name="Main",
        )
        prefix = (
            self.runtime.env.get("ENVCTL_PROJECT_PREFIX")  # type: ignore[attr-defined]
            or config.raw.get("ENVCTL_PROJECT_PREFIX")
            or "supportopia"
        )
        base_name = config.base_dir.name or "main"
        raw_name = f"{prefix}-supabase-{base_name}"
        slug = []
        prev_dash = False
        for ch in raw_name.lower():
            if ch.isalnum():
                slug.append(ch)
                prev_dash = False
                continue
            if not prev_dash:
                slug.append("-")
                prev_dash = True
        legacy = "".join(slug).strip("-") or "supportopia-supabase-main"
        if legacy == current:
            return (current,)
        return (current, legacy)

    def collect_container_volume_candidates(self, cid: str, volume_candidates: list[str]) -> None:
        inspect_format = '{{range .Mounts}}{{if eq .Type "volume"}}{{println .Name}}{{end}}{{end}}'
        owner = cast(Any, self)
        code, stdout, _stderr = owner.run_best_effort_command(
            ["docker", "inspect", "-f", inspect_format, cid],
            timeout=10.0,
        )
        if code != 0 or not stdout.strip():
            return
        for line in stdout.splitlines():
            volume_name = line.strip()
            if not volume_name:
                continue
            if volume_name not in volume_candidates:
                volume_candidates.append(volume_name)
