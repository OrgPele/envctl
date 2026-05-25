from __future__ import annotations

import os
import shutil
import subprocess

from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.lifecycle_blast_docker import BlastDockerCleanupSupport
from envctl_engine.runtime.lifecycle_blast_ports import BlastPortSweepSupport
from envctl_engine.runtime.lifecycle_blast_processes import BlastProcessCleanupSupport


class LifecycleBlastCleanupSupport(
    BlastPortSweepSupport,
    BlastProcessCleanupSupport,
    BlastDockerCleanupSupport,
):
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
