from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from envctl_engine.runtime.lifecycle_service_termination import (
    _wait_for_pid_exit,
    failed_listener_pids,
    service_port,
    terminate_service_record,
    terminate_services_from_state,
    terminate_started_services,
    unconfirmed_service_names,
)
from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.shared.ports import PortPlanner


class LifecycleServiceTerminationTests(unittest.TestCase):
    def test_pending_docker_cleanup_timestamp_reaches_tokenized_stop(self) -> None:
        runtime = SimpleNamespace(
            process_runner=SimpleNamespace(),
            _emit=lambda *_args, **_kwargs: None,
        )
        service = ServiceRecord(
            name="Main Backend",
            type="backend",
            cwd=".",
            runtime_kind="docker",
            container_id="envctl-app-main-backend",
            container_name="envctl-app-main-backend",
            container_launch_token="pending-token",
            container_cleanup_pending_since=1_700_000_000.25,
        )

        with patch(
            "envctl_engine.runtime.docker_service_runtime.DockerServiceRuntime.stop",
            return_value=False,
        ) as stop:
            self.assertFalse(
                terminate_service_record(
                    runtime,
                    service,
                    aggressive=False,
                    verify_ownership=True,
                )
            )

        stop.assert_called_once_with(
            "envctl-app-main-backend",
            verify_ownership=True,
            expected_launch_token="pending-token",
            pending_cleanup_since=1_700_000_000.25,
        )

    def test_termination_result_normalization_fails_closed_for_missing_or_unknown_identities(self) -> None:
        requested = {"Main Backend", "Main Frontend"}

        self.assertEqual(unconfirmed_service_names(None, requested), requested)
        self.assertEqual(unconfirmed_service_names("Main Backend", requested), requested)
        self.assertEqual(unconfirmed_service_names({"unknown"}, requested), requested)
        self.assertEqual(unconfirmed_service_names(["   "], requested), requested)
        self.assertEqual(unconfirmed_service_names(["", "Main Backend"], requested), requested)
        self.assertEqual(unconfirmed_service_names({"Main Backend"}, requested), {"Main Backend"})
        self.assertEqual(unconfirmed_service_names([], requested), set())
        self.assertEqual(failed_listener_pids(set()), set())
        self.assertEqual(failed_listener_pids({4242}), {4242})
        self.assertIsNone(failed_listener_pids(None))
        self.assertIsNone(failed_listener_pids({"4242"}))

    def test_terminate_started_services_uses_non_aggressive_unverified_shutdown(self) -> None:
        calls: list[tuple[int, bool, bool]] = []
        runtime = SimpleNamespace(
            _terminate_service_record=lambda service, *, aggressive, verify_ownership: (
                calls.append((service.pid, aggressive, verify_ownership)) or True
            )
        )

        failed = terminate_started_services(
            runtime,
            {
                "Main Backend": ServiceRecord(name="Main Backend", type="backend", cwd=".", pid=1),
                "Main Frontend": ServiceRecord(name="Main Frontend", type="frontend", cwd=".", pid=2),
            },
        )

        self.assertEqual(calls, [(1, False, False), (2, False, False)])
        self.assertEqual(failed, set())

    def test_terminate_started_services_reports_every_unconfirmed_exit(self) -> None:
        runtime = SimpleNamespace(_terminate_service_record=lambda service, **_kwargs: service.name != "Main Backend")

        failed = terminate_started_services(
            runtime,
            {
                "Main Backend": ServiceRecord(name="Main Backend", type="backend", cwd=".", pid=1),
                "Main Frontend": ServiceRecord(name="Main Frontend", type="frontend", cwd=".", pid=2),
            },
        )

        self.assertEqual(failed, {"Main Backend"})

    def test_terminate_started_services_continues_after_terminator_exception(self) -> None:
        calls: list[str] = []
        events: list[tuple[str, dict[str, object]]] = []

        def terminate(service: ServiceRecord, **_kwargs: object) -> bool:
            calls.append(service.name)
            if service.name == "Main Backend":
                raise RuntimeError("probe failed")
            return True

        runtime = SimpleNamespace(
            _terminate_service_record=terminate,
            _emit=lambda event, **payload: events.append((event, payload)),
        )

        failed = terminate_started_services(
            runtime,
            {
                "Main Backend": ServiceRecord(name="Main Backend", type="backend", cwd="."),
                "Main Frontend": ServiceRecord(name="Main Frontend", type="frontend", cwd="."),
            },
        )

        self.assertEqual(calls, ["Main Backend", "Main Frontend"])
        self.assertEqual(failed, {"Main Backend"})
        self.assertEqual(events[0][0], "cleanup.error")

    def test_terminate_services_from_state_filters_selected_services_and_releases_terminated_ports(self) -> None:
        released: list[int] = []
        terminated: list[tuple[int, bool, bool]] = []
        runtime = SimpleNamespace(
            port_planner=SimpleNamespace(release=lambda port: released.append(port)),
            _terminate_service_record=lambda service, *, aggressive, verify_ownership: (
                terminated.append((service.pid, aggressive, verify_ownership)) or True
            ),
        )
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(name="Main Backend", type="backend", cwd=".", pid=1, actual_port=8000),
                "Main Frontend": ServiceRecord(
                    name="Main Frontend", type="frontend", cwd=".", pid=2, requested_port=3000
                ),
            },
        )

        failed = terminate_services_from_state(
            runtime,
            state,
            selected_services={"Main Frontend"},
            aggressive=True,
            verify_ownership=True,
        )

        self.assertEqual(terminated, [(2, True, True)])
        self.assertEqual(released, [3000])
        self.assertEqual(failed, set())

    def test_terminated_service_releases_verified_prior_session_port_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prior = PortPlanner(
                lock_dir=tmpdir,
                session_id="prior-session",
                availability_checker=lambda _port: True,
            )
            current = PortPlanner(
                lock_dir=tmpdir,
                session_id="current-session",
                availability_checker=lambda _port: True,
            )
            prior.reserve_next(8000, owner="Main:backend")
            runtime = SimpleNamespace(
                port_planner=current,
                _terminate_service_record=lambda _service, **_kwargs: True,
                _project_name_from_service=lambda _name: "Main",
            )
            state = RunState(
                run_id="run-prior",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=".",
                        project="Main",
                        pid=1,
                        actual_port=8000,
                        port_lock_session="prior-session",
                    )
                },
            )

            failed = terminate_services_from_state(
                runtime,
                state,
                selected_services=None,
                aggressive=False,
                verify_ownership=True,
            )

            self.assertEqual(failed, set())
            self.assertEqual(list(Path(tmpdir).glob("*.lock")), [])

    def test_legacy_collision_name_releases_original_project_owner_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prior = PortPlanner(
                lock_dir=tmpdir,
                session_id="prior-session",
                availability_checker=lambda _port: True,
            )
            current = PortPlanner(
                lock_dir=tmpdir,
                session_id="current-session",
                availability_checker=lambda _port: True,
            )
            prior.reserve_next(8001, owner="Main:backend")
            collision_name = "Main Backend Restart Collision 2"
            state = RunState(
                run_id="run-collision",
                mode="main",
                services={
                    collision_name: ServiceRecord(
                        name=collision_name,
                        type="backend",
                        cwd=".",
                        pid=2,
                        actual_port=8001,
                        port_lock_session="prior-session",
                        project=None,
                    )
                },
            )
            runtime = SimpleNamespace(
                port_planner=current,
                _terminate_service_record=lambda _service, **_kwargs: True,
                _project_name_from_service=lambda _name: "Main Backend Restart Collision",
            )

            failed = terminate_services_from_state(
                runtime,
                state,
                selected_services=None,
                aggressive=False,
                verify_ownership=True,
            )

            self.assertEqual(failed, set())
            self.assertEqual(list(Path(tmpdir).glob("*.lock")), [])

    def test_terminated_rebound_frontend_releases_launch_owner_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prior = PortPlanner(
                lock_dir=tmpdir,
                session_id="prior-session",
                availability_checker=lambda _port: True,
            )
            current = PortPlanner(
                lock_dir=tmpdir,
                session_id="current-session",
                availability_checker=lambda _port: True,
            )
            prior.reserve_next(5173, owner="Main:frontend")
            prior.reserve_next(5174, owner="Main:services:frontend-launch")
            runtime = SimpleNamespace(
                port_planner=current,
                _terminate_service_record=lambda _service, **_kwargs: True,
                _project_name_from_service=lambda _name: "Main",
            )
            state = RunState(
                run_id="run-prior",
                mode="main",
                services={
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=".",
                        project="Main",
                        pid=1,
                        requested_port=5173,
                        actual_port=5174,
                        port_lock_session="prior-session",
                    )
                },
            )

            failed = terminate_services_from_state(
                runtime,
                state,
                selected_services=None,
                aggressive=False,
                verify_ownership=True,
            )

            self.assertEqual(failed, set())
            self.assertEqual(list(Path(tmpdir).glob("*.lock")), [])

    def test_stale_service_state_cannot_release_newer_live_same_owner_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            newer = PortPlanner(
                lock_dir=tmpdir,
                session_id="newer-session",
                availability_checker=lambda _port: True,
            )
            cleanup = PortPlanner(
                lock_dir=tmpdir,
                session_id="cleanup-session",
                availability_checker=lambda _port: True,
            )
            newer.reserve_next(8000, owner="Main:backend")
            runtime = SimpleNamespace(
                port_planner=cleanup,
                _terminate_service_record=lambda _service, **_kwargs: True,
            )
            state = RunState(
                run_id="stale-run",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=".",
                        project="Main",
                        pid=1,
                        actual_port=8000,
                        port_lock_session="stale-session",
                    )
                },
            )

            failed = terminate_services_from_state(
                runtime,
                state,
                selected_services=None,
                aggressive=False,
                verify_ownership=True,
            )

            self.assertEqual(failed, set())
            self.assertTrue((Path(tmpdir) / "8000.lock").exists())

    def test_startup_rollback_releases_confirmed_service_ports_but_preserves_failed_service_ports(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            planner = PortPlanner(
                lock_dir=tmpdir,
                session_id="startup-session",
                availability_checker=lambda _port: True,
            )
            planner.reserve_next(5173, owner="Main:frontend")
            planner.reserve_next(5174, owner="Main:services:frontend-launch")
            planner.reserve_next(8000, owner="Main:backend")
            frontend = ServiceRecord(
                name="Main Frontend",
                type="frontend",
                cwd=".",
                project="Main",
                pid=1,
                requested_port=5173,
                actual_port=5174,
            )
            backend = ServiceRecord(
                name="Main Backend",
                type="backend",
                cwd=".",
                project="Main",
                pid=2,
                requested_port=8000,
                actual_port=8000,
            )
            runtime = SimpleNamespace(
                port_planner=planner,
                _terminate_service_record=lambda service, **_kwargs: service is frontend,
            )

            failed = terminate_started_services(
                runtime,
                {frontend.name: frontend, backend.name: backend},
            )

            self.assertEqual(failed, {backend.name})
            remaining = list(Path(tmpdir).glob("*.lock"))
            self.assertEqual([path.name for path in remaining], ["8000.lock"])

    def test_terminate_services_reports_failures_without_releasing_their_ports(self) -> None:
        released: list[int] = []
        runtime = SimpleNamespace(
            port_planner=SimpleNamespace(release=lambda port: released.append(port)),
            _terminate_service_record=lambda service, **_kwargs: service.name != "Main Backend",
        )
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd=".",
                    pid=1,
                    actual_port=8000,
                ),
                "Main Frontend": ServiceRecord(
                    name="Main Frontend",
                    type="frontend",
                    cwd=".",
                    pid=2,
                    actual_port=3000,
                ),
            },
        )

        failed = terminate_services_from_state(
            runtime,
            state,
            selected_services=None,
            aggressive=False,
            verify_ownership=True,
        )

        self.assertEqual(failed, {"Main Backend"})
        self.assertEqual(released, [3000])

    def test_terminate_service_record_skips_self_parent_and_missing_ownership_port(self) -> None:
        events: list[dict[str, object]] = []
        runtime = SimpleNamespace(
            _emit=lambda _event, **payload: events.append(payload),
            process_runner=SimpleNamespace(is_pid_running=lambda _pid: True),
        )

        with patch.object(os, "getpid", return_value=100), patch.object(os, "getppid", return_value=200):
            self.assertFalse(
                terminate_service_record(
                    runtime,
                    SimpleNamespace(name="Self", pid=100, actual_port=8000),
                    aggressive=False,
                    verify_ownership=False,
                )
            )
        self.assertFalse(
            terminate_service_record(
                runtime,
                SimpleNamespace(name="No Port", pid=300, actual_port=None, requested_port=None),
                aggressive=False,
                verify_ownership=True,
            )
        )

        self.assertEqual(events[0]["reason"], "self_or_parent")
        self.assertEqual(events[1]["reason"], "missing_port_for_ownership")

    def test_terminate_service_record_accepts_verified_listener_child_and_prefers_process_group(self) -> None:
        calls: list[tuple[str, int]] = []
        live_pids = {111, 222}

        def pid_owns_port(pid: int, port: int) -> bool:
            return pid == 222 and port == 9000

        runtime = SimpleNamespace(
            _emit=lambda *_args, **_kwargs: None,
            process_runner=SimpleNamespace(
                is_pid_running=lambda pid: pid in live_pids,
                pid_owns_port=pid_owns_port,
                terminate_process_group=lambda pid, **_kwargs: (
                    calls.append(("group", pid)),
                    live_pids.discard(pid),
                    True,
                )[-1],
                terminate=lambda pid, **_kwargs: calls.append(("single", pid)) or True,
            ),
        )

        terminated = terminate_service_record(
            runtime,
            SimpleNamespace(name="Main Frontend", pid=111, actual_port=9000, listener_pids=[222]),
            aggressive=False,
            verify_ownership=True,
        )

        self.assertTrue(terminated)
        self.assertEqual(calls, [("group", 111), ("group", 222)])

    def test_terminate_service_record_stops_non_listener_with_matching_recorded_cwd(self) -> None:
        calls: list[int] = []
        live_pids = {333}
        runtime = SimpleNamespace(
            _emit=lambda *_args, **_kwargs: None,
            process_runner=SimpleNamespace(
                is_pid_running=lambda pid: pid in live_pids,
                process_cwd=lambda _pid: "/repo/worker",
                terminate_process_group=lambda pid, **_kwargs: (calls.append(pid), live_pids.discard(pid), True)[-1],
            ),
        )

        terminated = terminate_service_record(
            runtime,
            ServiceRecord(
                name="Main Worker",
                type="worker",
                cwd="/repo/worker",
                pid=333,
                listener_expected=False,
            ),
            aggressive=False,
            verify_ownership=True,
        )

        self.assertTrue(terminated)
        self.assertEqual(calls, [333])

    def test_terminate_service_record_keeps_non_listener_when_cwd_cannot_be_verified(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(
            _emit=lambda event, **payload: events.append((event, payload)),
            process_runner=SimpleNamespace(
                is_pid_running=lambda _pid: True,
                process_cwd=lambda _pid: "/foreign/worker",
                terminate_process_group=lambda *_args, **_kwargs: self.fail("foreign PID must not be signalled"),
            ),
        )

        terminated = terminate_service_record(
            runtime,
            ServiceRecord(
                name="Main Worker",
                type="worker",
                cwd="/repo/worker",
                pid=334,
                listener_expected=False,
            ),
            aggressive=False,
            verify_ownership=True,
        )

        self.assertFalse(terminated)
        self.assertEqual(events[0][1]["reason"], "missing_port_for_ownership")

    def test_parent_dead_live_listener_child_is_still_terminated(self) -> None:
        calls: list[int] = []
        live_pids = {402}
        runtime = SimpleNamespace(
            _emit=lambda *_args, **_kwargs: None,
            process_runner=SimpleNamespace(
                is_pid_running=lambda pid: pid in live_pids,
                pid_owns_port=lambda pid, port: pid == 402 and port == 8000,
                terminate_process_group=lambda pid, **_kwargs: (calls.append(pid), live_pids.discard(pid), True)[-1],
            ),
        )

        terminated = terminate_service_record(
            runtime,
            ServiceRecord(
                name="Main Backend",
                type="backend",
                cwd="/repo/backend",
                pid=401,
                listener_pids=[402],
                actual_port=8000,
            ),
            aggressive=False,
            verify_ownership=True,
        )

        self.assertTrue(terminated)
        self.assertEqual(calls, [402])

    def test_missing_primary_pid_does_not_hide_live_listener_child(self) -> None:
        calls: list[int] = []
        live_pids = {403}
        runtime = SimpleNamespace(
            _emit=lambda *_args, **_kwargs: None,
            process_runner=SimpleNamespace(
                is_pid_running=lambda pid: pid in live_pids,
                pid_owns_port=lambda pid, port: pid == 403 and port == 8001,
                terminate_process_group=lambda pid, **_kwargs: (calls.append(pid), live_pids.discard(pid), True)[-1],
            ),
        )

        terminated = terminate_service_record(
            runtime,
            ServiceRecord(
                name="Main Backend",
                type="backend",
                cwd="/repo/backend",
                pid=None,
                listener_pids=[403],
                actual_port=8001,
            ),
            aggressive=False,
            verify_ownership=True,
        )

        self.assertTrue(terminated)
        self.assertEqual(calls, [403])

    def test_dead_parent_with_unrecorded_live_listener_keeps_state_without_signalling_foreign_pid(self) -> None:
        runtime = SimpleNamespace(
            _emit=lambda *_args, **_kwargs: None,
            _listener_pids_for_port=lambda _port: [406],
            process_runner=SimpleNamespace(
                is_pid_running=lambda pid: pid == 406,
                pid_owns_port=lambda *_args, **_kwargs: self.fail("no recorded live PID should be probed"),
                terminate_process_group=lambda *_args, **_kwargs: self.fail("foreign PID must not be signalled"),
            ),
        )

        terminated = terminate_service_record(
            runtime,
            ServiceRecord(
                name="Main Backend",
                type="backend",
                cwd="/repo/backend",
                pid=404,
                listener_pids=None,
                actual_port=8002,
            ),
            aggressive=False,
            verify_ownership=True,
        )

        self.assertFalse(terminated)

    def test_pidless_unconfirmed_launch_remains_tracked(self) -> None:
        runtime = SimpleNamespace(
            _emit=lambda *_args, **_kwargs: None,
            process_runner=SimpleNamespace(),
        )

        terminated = terminate_service_record(
            runtime,
            ServiceRecord(
                name="Main Worker",
                type="worker",
                cwd="/repo/worker",
                pid=None,
                listener_expected=False,
                status="termination_failed",
            ),
            aggressive=False,
            verify_ownership=False,
        )

        self.assertFalse(terminated)

    def test_live_port_listener_after_termination_keeps_service_tracked(self) -> None:
        runtime = SimpleNamespace(
            _emit=lambda *_args, **_kwargs: None,
            _listener_pids_for_port=lambda _port: [405],
            process_runner=SimpleNamespace(
                is_pid_running=lambda _pid: True,
                pid_owns_port=lambda pid, port: pid == 404 and port == 8002,
                terminate_process_group=lambda *_args, **_kwargs: True,
            ),
        )

        terminated = terminate_service_record(
            runtime,
            ServiceRecord(
                name="Main Backend",
                type="backend",
                cwd="/repo/backend",
                pid=404,
                actual_port=8002,
            ),
            aggressive=False,
            verify_ownership=True,
        )

        self.assertFalse(terminated)

    def test_malformed_listener_probe_result_fails_closed(self) -> None:
        runtime = SimpleNamespace(
            _emit=lambda *_args, **_kwargs: None,
            _listener_pids_for_port=lambda _port: None,
            process_runner=SimpleNamespace(is_pid_running=lambda _pid: False),
        )

        terminated = terminate_service_record(
            runtime,
            ServiceRecord(
                name="Main Backend",
                type="backend",
                cwd="/repo/backend",
                pid=999,
                actual_port=8003,
            ),
            aggressive=False,
            verify_ownership=True,
        )

        self.assertFalse(terminated)

    def test_terminate_service_record_treats_already_dead_pid_as_success_before_ownership_check(self) -> None:
        ownership_checks: list[tuple[int, int]] = []
        terminate_calls: list[int] = []
        runtime = SimpleNamespace(
            _emit=lambda *_args, **_kwargs: None,
            process_runner=SimpleNamespace(
                is_pid_running=lambda _pid: False,
                pid_owns_port=lambda pid, port: ownership_checks.append((pid, port)) or False,
                terminate_process_group=lambda pid, **_kwargs: terminate_calls.append(pid) or True,
            ),
        )

        terminated = terminate_service_record(
            runtime,
            SimpleNamespace(name="Shadow Backend", pid=777, actual_port=8000),
            aggressive=False,
            verify_ownership=True,
        )

        self.assertTrue(terminated)
        self.assertEqual(ownership_checks, [])
        self.assertEqual(terminate_calls, [])

    def test_terminate_service_record_keeps_live_non_owner_fail_closed(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(
            _emit=lambda event, **payload: events.append((event, payload)),
            process_runner=SimpleNamespace(
                is_pid_running=lambda _pid: True,
                pid_owns_port=lambda _pid, _port: False,
                terminate_process_group=lambda *_args, **_kwargs: self.fail("non-owner must not be signalled"),
            ),
        )

        terminated = terminate_service_record(
            runtime,
            SimpleNamespace(name="Foreign Backend", pid=778, actual_port=8001),
            aggressive=False,
            verify_ownership=True,
        )

        self.assertFalse(terminated)
        self.assertEqual(
            events,
            [
                (
                    "cleanup.skip",
                    {
                        "service": "Foreign Backend",
                        "pid": 778,
                        "port": 8001,
                        "reason": "ownership_mismatch",
                    },
                )
            ],
        )

    def test_raw_signal_fallback_escalates_and_fails_when_pid_survives(self) -> None:
        sent_signals: list[tuple[int, signal.Signals]] = []
        runtime = SimpleNamespace(
            _emit=lambda *_args, **_kwargs: None,
            process_runner=SimpleNamespace(
                is_pid_running=lambda _pid: True,
                terminate_process_group=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("unsupported")),
                terminate=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("unsupported")),
            ),
        )

        with (
            patch(
                "envctl_engine.shared.process_termination.os.kill",
                side_effect=lambda pid, requested_signal: sent_signals.append((pid, requested_signal)),
            ),
            patch(
                "envctl_engine.shared.process_termination.wait_for_pid_exit",
                side_effect=[False, False],
            ) as wait_for_exit,
        ):
            terminated = terminate_service_record(
                runtime,
                SimpleNamespace(name="Main Backend", pid=779, actual_port=8002),
                aggressive=False,
                verify_ownership=False,
            )

        self.assertFalse(terminated)
        self.assertEqual(sent_signals, [(779, signal.SIGTERM), (779, signal.SIGKILL)])
        self.assertEqual(
            [call.kwargs["timeout"] for call in wait_for_exit.call_args_list],
            [2.0, 1.0],
        )

    def test_raw_signal_fallback_does_not_escalate_after_confirmed_sigterm_exit(self) -> None:
        sent_signals: list[tuple[int, signal.Signals]] = []
        runtime = SimpleNamespace(
            _emit=lambda *_args, **_kwargs: None,
            process_runner=SimpleNamespace(
                is_pid_running=lambda _pid: True,
                terminate_process_group=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("unsupported")),
                terminate=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("unsupported")),
            ),
        )

        with (
            patch(
                "envctl_engine.shared.process_termination.os.kill",
                side_effect=lambda pid, requested_signal: sent_signals.append((pid, requested_signal)),
            ),
            patch(
                "envctl_engine.shared.process_termination.wait_for_pid_exit",
                return_value=True,
            ),
        ):
            terminated = terminate_service_record(
                runtime,
                SimpleNamespace(name="Main Backend", pid=780, actual_port=8003),
                aggressive=True,
                verify_ownership=False,
            )

        self.assertTrue(terminated)
        self.assertEqual(sent_signals, [(780, signal.SIGTERM)])

    def test_raw_signal_fallback_accepts_process_lookup_race_as_clean_exit(self) -> None:
        runtime = SimpleNamespace(
            _emit=lambda *_args, **_kwargs: None,
            process_runner=SimpleNamespace(
                is_pid_running=lambda _pid: True,
                terminate_process_group=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("unsupported")),
                terminate=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("unsupported")),
            ),
        )

        with patch(
            "envctl_engine.shared.process_termination.os.kill",
            side_effect=ProcessLookupError,
        ):
            terminated = terminate_service_record(
                runtime,
                SimpleNamespace(name="Main Backend", pid=781, actual_port=8004),
                aggressive=False,
                verify_ownership=False,
            )

        self.assertTrue(terminated)

    def test_raw_signal_exit_wait_polls_until_pid_is_confirmed_dead(self) -> None:
        runtime = SimpleNamespace(
            process_runner=SimpleNamespace(is_pid_running=Mock(side_effect=[True, False])),
        )

        with (
            patch(
                "envctl_engine.shared.process_termination.time.monotonic",
                side_effect=[10.0, 10.0],
            ),
            patch("envctl_engine.shared.process_termination.time.sleep") as sleep_mock,
        ):
            exited = _wait_for_pid_exit(
                runtime,
                782,
                timeout=1.0,
                initial_identity=None,
            )

        self.assertTrue(exited)
        sleep_mock.assert_called_once_with(0.05)

    def test_raw_signal_fallback_really_escalates_sigterm_resistant_process(self) -> None:
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import signal,time; "
                    "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                    "print('ready', flush=True); "
                    "time.sleep(30)"
                ),
            ],
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            assert process.stdout is not None
            self.assertEqual(process.stdout.readline().strip(), "ready")
            runtime = SimpleNamespace(
                _emit=lambda *_args, **_kwargs: None,
                process_runner=SimpleNamespace(
                    is_pid_running=lambda _pid: process.poll() is None,
                    terminate_process_group=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                        RuntimeError("unsupported")
                    ),
                    terminate=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("unsupported")),
                ),
            )

            terminated = terminate_service_record(
                runtime,
                SimpleNamespace(name="Main Backend", pid=process.pid, actual_port=8005),
                aggressive=True,
                verify_ownership=False,
            )

            self.assertTrue(terminated)
            self.assertEqual(process.wait(timeout=2.0), -signal.SIGKILL)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=2.0)

    def test_service_port_prefers_actual_then_requested(self) -> None:
        self.assertEqual(service_port(SimpleNamespace(actual_port=9000, requested_port=8000)), 9000)
        self.assertEqual(service_port(SimpleNamespace(actual_port=None, requested_port=8000)), 8000)
        self.assertIsNone(service_port(SimpleNamespace(actual_port=None, requested_port=None)))


if __name__ == "__main__":
    unittest.main()
