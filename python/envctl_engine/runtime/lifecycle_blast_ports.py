from __future__ import annotations

from typing import Any, cast

from envctl_engine.runtime.runtime_context import resolve_port_allocator
from envctl_engine.shared.parsing import parse_int


class BlastPortSweepSupport:
    runtime: Any

    def blast_all_sweep_ports(self) -> None:
        if self.blast_all_sweep_ports_batched():
            return
        self.blast_all_sweep_ports_by_port()

    def blast_all_sweep_ports_batched(self) -> bool:
        owner = cast(Any, self)
        code, stdout, _stderr = owner.run_best_effort_command(
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
        owner = cast(Any, self)
        kill_pid_ports: dict[int, set[int]] = {}
        docker_pid_ports: dict[int, set[int]] = {}

        for port in self.blast_all_port_range():
            code, stdout, _stderr = owner.run_best_effort_command(
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
                _ps_code, ps_out, _ = owner.run_best_effort_command(
                    ["ps", "-p", str(pid), "-o", "command="],
                    timeout=2.0,
                )
                if owner.looks_like_docker_process(ps_out):
                    docker_pid_ports.setdefault(pid, set()).add(port)
                else:
                    kill_pid_ports.setdefault(pid, set()).add(port)

        self.blast_all_print_and_kill_listener_maps(
            kill_pid_ports=kill_pid_ports,
            docker_pid_ports=docker_pid_ports,
        )

    def blast_all_handle_listener_pid_map(self, pid_port_map: dict[int, set[int]]) -> None:
        owner = cast(Any, self)
        kill_pid_ports, docker_pid_ports = self.runtime.process_probe.split_listener_pid_maps(  # type: ignore[attr-defined]
            pid_port_map=pid_port_map,
            command_for_pid=self.blast_all_process_command,
            is_docker_process=owner.looks_like_docker_process,
        )
        self.blast_all_print_and_kill_listener_maps(
            kill_pid_ports=kill_pid_ports,
            docker_pid_ports=docker_pid_ports,
        )

    def blast_all_process_command(self, pid: int) -> str:
        owner = cast(Any, self)
        _ps_code, ps_out, _ = owner.run_best_effort_command(
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
            cast(Any, self).blast_all_kill_pid_tree(pid)

        for pid in sorted(docker_pid_ports):
            ports_csv = ",".join(str(port) for port in sorted(docker_pid_ports[pid]))
            print(f"  Skipping Docker-managed PID {pid} across ports: {ports_csv}")

    def parse_blast_all_lsof_listeners(self, stdout: str) -> dict[int, set[int]] | None:
        return self.runtime.process_probe.parse_lsof_listener_pid_map(  # type: ignore[attr-defined]
            stdout=stdout,
            target_ports=set(self.blast_all_port_range()),
        )

    def blast_all_port_range(self) -> list[int]:
        app_span = self.blast_all_scan_span(default=400, minimum=100)
        infra_span = max(40, app_span // 4)

        candidates: set[int] = set()
        config = self.runtime.config  # type: ignore[attr-defined]
        for base, span in (
            (config.backend_port_base, app_span),
            (config.frontend_port_base, app_span),
            (config.db_port_base, infra_span),
            (config.redis_port_base, infra_span),
            (config.n8n_port_base, infra_span),
            (config.port_defaults.dependency_port("supabase", "api"), infra_span),
        ):
            if base <= 0:
                continue
            for port in range(base, base + span + 1):
                candidates.add(port)
        for service in getattr(config, "additional_services", ()):
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
        raw = self.runtime.env.get("ENVCTL_BLAST_PORT_SCAN_SPAN") or self.runtime.config.raw.get(  # type: ignore[attr-defined]
            "ENVCTL_BLAST_PORT_SCAN_SPAN"
        )
        span = parse_int(raw, default) if raw is not None else default
        return max(span, minimum)
