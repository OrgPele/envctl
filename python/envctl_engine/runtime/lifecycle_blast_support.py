from __future__ import annotations

import os
import shutil
import subprocess

from envctl_engine.requirements.supabase import build_supabase_project_name
from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.lifecycle_blast_containers import matches_blast_container
from envctl_engine.runtime.lifecycle_blast_processes import (
    BLAST_ALL_PROCESS_PATTERNS,
    is_orchestrator_process,
    looks_like_docker_process,
    process_tree_kill_order_from_ps,
)
from envctl_engine.runtime.runtime_context import resolve_port_allocator
from envctl_engine.shared.parsing import parse_int
from envctl_engine.ui.status_symbols import STATUS_SUCCESS, STATUS_WARNING


class LifecycleBlastCleanupSupport:
    def blast_all_ecosystem_cleanup(self, *, route: Route | None) -> None:
        rt = self.runtime
        palette = rt._dashboard_palette()  # type: ignore[attr-defined]
        red = palette["red"]
        yellow = palette["yellow"]
        green = palette["green"]
        dim = palette["dim"]
        reset = palette["reset"]

        print("")
        print(f"{red}!!! INITIATING BLAST-ALL NUCLEAR CLEANUP !!!{reset}")
        print(f"{yellow}Hunting OS processes...{reset}")
        self.blast_all_kill_orchestrator_processes()
        for pattern in self.blast_all_process_patterns():
            print(f"  Killing match: {pattern}")
            self.run_best_effort_command(["pkill", "-9", "-f", pattern], timeout=5.0)

        print(f"{yellow}Sweeping common development port ranges...{reset}")
        self.blast_all_sweep_ports()

        print(f"{yellow}Annihilating ecosystem Docker containers...{reset}")
        removed = self.blast_all_docker_cleanup(route=route)
        if removed == 0:
            print(f"  {dim}No matching ecosystem containers found (or Docker unavailable).{reset}")

        print(f"{green}✓ Ecosystem blasted.{reset}")
        print("")

    @staticmethod
    def blast_all_process_patterns() -> tuple[str, ...]:
        return BLAST_ALL_PROCESS_PATTERNS

    def blast_all_sweep_ports(self) -> None:
        if self.blast_all_sweep_ports_batched():
            return
        self.blast_all_sweep_ports_by_port()

    def blast_all_sweep_ports_batched(self) -> bool:
        code, stdout, _stderr = self.run_best_effort_command(
            ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"],
            timeout=10.0,
        )
        # lsof exits non-zero when there are no matches; that's still a valid scan result.
        if code == 127:
            return False
        if code not in {0, 1} and not stdout.strip():
            return False

        pid_port_map = self.parse_blast_all_lsof_listeners(stdout)
        if pid_port_map is None:
            return False
        self.blast_all_handle_listener_pid_map(pid_port_map)
        return True

    def blast_all_sweep_ports_by_port(self) -> None:
        kill_pid_ports: dict[int, set[int]] = {}
        docker_pid_ports: dict[int, set[int]] = {}

        for port in self.blast_all_port_range():
            code, stdout, _stderr = self.run_best_effort_command(
                ["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
                timeout=2.0,
            )
            if code != 0 or not stdout.strip():
                continue
            for raw_pid in stdout.splitlines():
                raw_pid = raw_pid.strip()
                if not raw_pid.isdigit():
                    continue
                pid = int(raw_pid)
                _ps_code, ps_out, _ = self.run_best_effort_command(
                    ["ps", "-p", str(pid), "-o", "command="],
                    timeout=2.0,
                )
                if self.looks_like_docker_process(ps_out):
                    docker_pid_ports.setdefault(pid, set()).add(port)
                else:
                    kill_pid_ports.setdefault(pid, set()).add(port)

        self.blast_all_print_and_kill_listener_maps(
            kill_pid_ports=kill_pid_ports,
            docker_pid_ports=docker_pid_ports,
        )

    def blast_all_handle_listener_pid_map(self, pid_port_map: dict[int, set[int]]) -> None:
        rt = self.runtime
        kill_pid_ports, docker_pid_ports = rt.process_probe.split_listener_pid_maps(  # type: ignore[attr-defined]
            pid_port_map=pid_port_map,
            command_for_pid=self.blast_all_process_command,
            is_docker_process=self.looks_like_docker_process,
        )
        self.blast_all_print_and_kill_listener_maps(
            kill_pid_ports=kill_pid_ports,
            docker_pid_ports=docker_pid_ports,
        )

    def blast_all_process_command(self, pid: int) -> str:
        _ps_code, ps_out, _ = self.run_best_effort_command(
            ["ps", "-p", str(pid), "-o", "command="],
            timeout=2.0,
        )
        return ps_out

    def blast_all_print_and_kill_listener_maps(
        self,
        *,
        kill_pid_ports: dict[int, set[int]],
        docker_pid_ports: dict[int, set[int]],
    ) -> None:
        for pid in sorted(kill_pid_ports):
            ports_csv = ",".join(str(port) for port in sorted(kill_pid_ports[pid]))
            print(f"  Killing orphaned PID {pid} across ports: {ports_csv}")
            self.blast_all_kill_pid_tree(pid)

        for pid in sorted(docker_pid_ports):
            ports_csv = ",".join(str(port) for port in sorted(docker_pid_ports[pid]))
            print(f"  Skipping Docker-managed PID {pid} across ports: {ports_csv}")

    def parse_blast_all_lsof_listeners(self, stdout: str) -> dict[int, set[int]] | None:
        rt = self.runtime
        return rt.process_probe.parse_lsof_listener_pid_map(  # type: ignore[attr-defined]
            stdout=stdout,
            target_ports=set(self.blast_all_port_range()),
        )

    def blast_all_port_range(self) -> list[int]:
        rt = self.runtime
        app_span = self.blast_all_scan_span(default=400, minimum=100)
        infra_span = max(40, app_span // 4)

        candidates: set[int] = set()
        for base, span in (
            (rt.config.backend_port_base, app_span),  # type: ignore[attr-defined]
            (rt.config.frontend_port_base, app_span),  # type: ignore[attr-defined]
            (rt.config.db_port_base, infra_span),  # type: ignore[attr-defined]
            (rt.config.redis_port_base, infra_span),  # type: ignore[attr-defined]
            (rt.config.n8n_port_base, infra_span),  # type: ignore[attr-defined]
            (rt.config.port_defaults.dependency_port("supabase", "api"), infra_span),  # type: ignore[attr-defined]
        ):
            if base <= 0:
                continue
            for port in range(base, base + span + 1):
                candidates.add(port)
        for service in getattr(rt.config, "additional_services", ()):  # type: ignore[attr-defined]
            base = getattr(service, "port_base", None)
            if not isinstance(base, int) or base <= 0:
                continue
            for port in range(base, base + app_span + 1):
                candidates.add(port)
        return sorted(candidates)

    def release_all_runtime_ports(self) -> None:
        try:
            port_planner = resolve_port_allocator(self.runtime)
        except RuntimeError:
            port_planner = None
        release_all = getattr(port_planner, "release_all", None)
        if callable(release_all):
            release_all()
            return
        release_session = getattr(self.runtime, "_release_port_session", None)
        if callable(release_session):
            release_session()

    def blast_all_scan_span(self, *, default: int, minimum: int) -> int:
        rt = self.runtime
        raw = rt.env.get("ENVCTL_BLAST_PORT_SCAN_SPAN") or rt.config.raw.get("ENVCTL_BLAST_PORT_SCAN_SPAN")  # type: ignore[attr-defined]
        span = parse_int(raw, default) if raw is not None else default
        return max(span, minimum)

    def blast_all_kill_orchestrator_processes(self) -> None:
        code, stdout, _stderr = self.run_best_effort_command(
            ["ps", "-axo", "pid=,command="],
            timeout=5.0,
        )
        if code != 0 or not stdout.strip():
            return

        current_pid = os.getpid()
        parent_pid = os.getppid()
        for line in stdout.splitlines():
            text = line.strip()
            if not text:
                continue
            parts = text.split(None, 1)
            if len(parts) != 2 or not parts[0].isdigit():
                continue
            pid = int(parts[0])
            command = parts[1]
            if pid <= 0 or pid in {current_pid, parent_pid}:
                continue
            if not self.blast_all_is_orchestrator_process(command):
                continue
            lowered = command.lower()
            if " blast-all" in lowered or "--blast-all" in lowered:
                continue
            preview = self.runtime._truncate_text(command, 100)  # type: ignore[attr-defined]
            print(f"  Killing orchestrator PID {pid}: {preview}")
            self.blast_all_kill_pid_tree(pid, skip_pids={current_pid, parent_pid})

    def blast_all_kill_pid_tree(self, root_pid: int, *, skip_pids: set[int] | None = None) -> None:
        if root_pid <= 0:
            return
        skip = set(skip_pids or set())
        for pid in self.blast_all_process_tree_kill_order(root_pid):
            if pid in skip or pid <= 0:
                continue
            self.run_best_effort_command(["kill", "-9", str(pid)], timeout=2.0)

    def blast_all_process_tree_kill_order(self, root_pid: int) -> list[int]:
        if root_pid <= 0:
            return []

        code, stdout, _stderr = self.run_best_effort_command(
            ["ps", "-axo", "pid=,ppid="],
            timeout=5.0,
        )
        if code != 0 or not stdout.strip():
            return [root_pid]

        return process_tree_kill_order_from_ps(stdout, root_pid=root_pid)

    @staticmethod
    def blast_all_is_orchestrator_process(command_text: str) -> bool:
        return is_orchestrator_process(command_text)

    @staticmethod
    def looks_like_docker_process(command_text: str) -> bool:
        return looks_like_docker_process(command_text)

    def blast_all_docker_cleanup(self, *, route: Route | None) -> int:
        code, stdout, _stderr = self.run_best_effort_command(
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
                self.run_best_effort_command(["docker", "rm", "-f", "-v", cid], timeout=20.0)
            else:
                self.run_best_effort_command(["docker", "rm", "-f", cid], timeout=20.0)
            removed += 1
        for volume_name in volume_candidates:
            print(f"  Nuking volume: {volume_name}")
            rm_code, _rm_out, _rm_err = self.run_best_effort_command(
                ["docker", "volume", "rm", volume_name],
                timeout=20.0,
            )
            if rm_code == 0:
                print(f"    {STATUS_SUCCESS} removed volume")
            else:
                print(f"    {STATUS_WARNING} volume not removed (in use or already deleted)")
        return removed

    @staticmethod
    def blast_all_matches_container(*, image: str, name: str) -> bool:
        return matches_blast_container(image=image, name=name)

    def blast_all_volume_policy(self, route: Route | None) -> tuple[bool, bool]:
        rt = self.runtime
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
            if route is not None and rt._batch_mode_requested(route):  # type: ignore[attr-defined]
                remove_main_storage = False
            elif rt._can_interactive_tty():  # type: ignore[attr-defined]
                remove_main_storage = self.prompt_yes_no("Delete MAIN project Docker storage volumes as well? (y/N): ")
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
        rt = self.runtime
        docker_project_name = (
            rt.env.get("DOCKER_PROJECT_NAME")  # type: ignore[attr-defined]
            or rt.config.raw.get("DOCKER_PROJECT_NAME")  # type: ignore[attr-defined]
            or rt.config.base_dir.name  # type: ignore[attr-defined]
            or "envctl"
        )
        db_container = (
            rt.env.get("DB_CONTAINER_NAME")  # type: ignore[attr-defined]
            or rt.config.raw.get("DB_CONTAINER_NAME")  # type: ignore[attr-defined]
            or f"{docker_project_name}-postgres"
        )
        redis_container = (
            rt.env.get("REDIS_CONTAINER_NAME")  # type: ignore[attr-defined]
            or rt.config.raw.get("REDIS_CONTAINER_NAME")  # type: ignore[attr-defined]
            or f"{docker_project_name}-redis"
        )
        return db_container, redis_container

    def blast_all_main_supabase_project_name(self) -> str:
        names = self.blast_all_main_supabase_project_names()
        return names[0] if names else "supportopia-supabase-main"

    def blast_all_main_supabase_project_names(self) -> tuple[str, ...]:
        rt = self.runtime
        current = build_supabase_project_name(
            project_root=rt.config.base_dir,  # type: ignore[attr-defined]
            project_name="Main",
        )
        prefix = rt.env.get("ENVCTL_PROJECT_PREFIX") or rt.config.raw.get("ENVCTL_PROJECT_PREFIX") or "supportopia"  # type: ignore[attr-defined]
        base_name = rt.config.base_dir.name or "main"  # type: ignore[attr-defined]
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
        code, stdout, _stderr = self.run_best_effort_command(
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

    def blast_all_purge_legacy_state_artifacts(self) -> None:
        rt = self.runtime
        palette = rt._dashboard_palette()  # type: ignore[attr-defined]
        yellow = palette["yellow"]
        reset = palette["reset"]

        print(f"{yellow}Purging leftover state pointers and locks...{reset}")

        runtime_root_dir = rt.config.runtime_dir  # type: ignore[attr-defined]
        for path in (
            runtime_root_dir / ".last_state",
            runtime_root_dir / ".last_state.main",
        ):
            path.unlink(missing_ok=True)
        for pointer in runtime_root_dir.glob(".last_state.trees.*"):
            pointer.unlink(missing_ok=True)

        # Legacy shell reservation directories from pre-runtime-dir migration paths.
        for path in (
            rt.config.base_dir / ".run-sh-port-reservations",  # type: ignore[attr-defined]
            rt.config.base_dir / "utils" / ".run-sh-port-reservations",  # type: ignore[attr-defined]
        ):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)

        # Best-effort cleanup for stale shell state pointers left in repo subdirectories.
        try:
            for pointer in rt.config.base_dir.rglob(".last_state"):  # type: ignore[attr-defined]
                try:
                    if pointer.is_file():
                        pointer.unlink(missing_ok=True)
                except OSError:
                    continue
        except OSError:
            return

    @staticmethod
    def prompt_yes_no(prompt: str) -> bool:
        try:
            answer = input(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("")
            return False
        return answer in {"y", "yes"}

    def run_best_effort_command(
        self,
        cmd: list[str],
        *,
        timeout: float | None = None,
    ) -> tuple[int, str, str]:
        rt = self.runtime
        process_runtime = self._process_runtime(rt)
        try:
            completed = process_runtime.run(  # type: ignore[attr-defined]
                cmd,
                cwd=rt.config.base_dir,  # type: ignore[attr-defined]
                env=rt._command_env(port=0),  # type: ignore[attr-defined]
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return 124, "", "timeout"
        except (OSError, FileNotFoundError):
            return 127, "", "command not found"
        return (
            int(getattr(completed, "returncode", 1)),
            str(getattr(completed, "stdout", "") or ""),
            str(getattr(completed, "stderr", "") or ""),
        )

    def blast_all_ecosystem_enabled(self) -> bool:
        rt = self.runtime
        value = rt.env.get("ENVCTL_BLAST_ALL_ECOSYSTEM")  # type: ignore[attr-defined]
        if value is None:
            value = os.environ.get("ENVCTL_BLAST_ALL_ECOSYSTEM")
        if value is None:
            return True
        return rt._is_truthy(value)  # type: ignore[attr-defined]
