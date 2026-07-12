from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.state.runtime_map import build_runtime_map, build_runtime_projection
from envctl_engine.shared.services import frontend_env_for_project


class FrontendProjectionTests(unittest.TestCase):
    def _state(self) -> RunState:
        return RunState(
            run_id="run-1",
            mode="trees",
            services={
                "Tree Alpha Backend": ServiceRecord(
                    name="Tree Alpha Backend",
                    type="backend",
                    cwd="/tmp/tree-alpha/backend",
                    requested_port=8000,
                    actual_port=8111,
                    status="running",
                ),
                "Tree Alpha Frontend": ServiceRecord(
                    name="Tree Alpha Frontend",
                    type="frontend",
                    cwd="/tmp/tree-alpha/frontend",
                    requested_port=9000,
                    actual_port=9122,
                    status="running",
                ),
            },
        )

    def test_backend_final_port_projects_to_frontend_env(self) -> None:
        state = self._state()

        env = frontend_env_for_project(state, "Tree Alpha")

        self.assertEqual(env["VITE_BACKEND_URL"], "http://localhost:8111")
        self.assertEqual(env["VITE_API_URL"], "http://localhost:8111/api/v1")

    def test_backend_final_port_projects_to_frontend_env_with_public_host(self) -> None:
        state = self._state()

        env = frontend_env_for_project(state, "Tree Alpha", host="203.0.113.10")

        self.assertEqual(env["VITE_BACKEND_URL"], "http://203.0.113.10:8111")
        self.assertEqual(env["VITE_API_URL"], "http://203.0.113.10:8111/api/v1")

    def test_runtime_map_tracks_actual_frontend_rebound_port(self) -> None:
        state = self._state()

        runtime = build_runtime_map(state)

        self.assertEqual(runtime["projects"]["Tree Alpha"]["backend_port"], 8111)
        self.assertEqual(runtime["projects"]["Tree Alpha"]["frontend_port"], 9122)
        self.assertEqual(runtime["projects"]["Tree Alpha"]["services"]["frontend"]["port"], 9122)
        self.assertEqual(runtime["service_to_actual_port"]["Tree Alpha Frontend"], 9122)
        self.assertEqual(runtime["port_to_service"][9122], "Tree Alpha Frontend")

    def test_projection_uses_project_metadata_for_opaque_core_service_names(self) -> None:
        state = RunState(
            run_id="run-opaque",
            mode="trees",
            services={
                "Opaque API Process": ServiceRecord(
                    name="Opaque API Process",
                    type="backend",
                    cwd="/tmp/customer-platform/api",
                    actual_port=8181,
                    status="healthy",
                    project="Customer Platform",
                    service_slug="backend",
                ),
                "Opaque Web Process": ServiceRecord(
                    name="Opaque Web Process",
                    type="frontend",
                    cwd="/tmp/customer-platform/web",
                    actual_port=9191,
                    status="running",
                    project="Customer Platform",
                    service_slug="frontend",
                ),
            },
        )

        runtime = build_runtime_map(state)
        projection = runtime["projection"]["Customer Platform"]

        self.assertEqual(projection["backend_url"], "http://localhost:8181")
        self.assertEqual(projection["frontend_url"], "http://localhost:9191")
        self.assertEqual(projection["backend_status"], "healthy")
        self.assertEqual(projection["frontend_status"], "running")
        self.assertEqual(
            frontend_env_for_project(state, "Customer Platform")["VITE_BACKEND_URL"],
            "http://localhost:8181",
        )

    def test_collision_projection_keeps_every_instance_and_uses_one_authoritative_record(self) -> None:
        collision_backend_name = "Main Backend Restart Collision 64001"
        collision_frontend_name = "Main Frontend Restart Collision 64002"
        services = {
            collision_backend_name: ServiceRecord(
                name=collision_backend_name,
                type="backend",
                cwd="/tmp/main/replacement-backend",
                pid=64001,
                actual_port=8251,
                status="termination_failed",
                project="Main",
                service_slug="backend",
                degraded=True,
            ),
            "Main Backend": ServiceRecord(
                name="Main Backend",
                type="backend",
                cwd="/tmp/main/backend",
                pid=63001,
                actual_port=8000,
                status="running",
                project="Main",
                service_slug="backend",
            ),
            collision_frontend_name: ServiceRecord(
                name=collision_frontend_name,
                type="frontend",
                cwd="/tmp/main/replacement-frontend",
                pid=64002,
                actual_port=9251,
                status="termination_failed",
                project="Main",
                service_slug="frontend",
                degraded=True,
            ),
            "Main Frontend": ServiceRecord(
                name="Main Frontend",
                type="frontend",
                cwd="/tmp/main/frontend",
                pid=63002,
                actual_port=9000,
                status="healthy",
                project="Main",
                service_slug="frontend",
            ),
        }
        state = RunState(run_id="run-collision", mode="main", services=services)

        runtime = build_runtime_map(state, host="runtime.test")
        project = runtime["projects"]["Main"]
        projected_services = project["services"]
        projection = runtime["projection"]["Main"]

        self.assertEqual(
            set(projected_services),
            {
                "backend",
                f"backend@{collision_backend_name}",
                "frontend",
                f"frontend@{collision_frontend_name}",
            },
        )
        self.assertEqual(projected_services["backend"]["name"], "Main Backend")
        self.assertEqual(projected_services["backend"]["port"], 8000)
        self.assertEqual(projected_services[f"backend@{collision_backend_name}"]["port"], 8251)
        self.assertEqual(projected_services["frontend"]["name"], "Main Frontend")
        self.assertEqual(projected_services["frontend"]["port"], 9000)
        self.assertEqual(projected_services[f"frontend@{collision_frontend_name}"]["port"], 9251)

        self.assertEqual(project["backend_port"], 8000)
        self.assertEqual(projection["backend_port"], 8000)
        self.assertEqual(projection["backend_url"], "http://runtime.test:8000")
        self.assertEqual(projection["backend_status"], "running")
        self.assertEqual(project["frontend_port"], 9000)
        self.assertEqual(projection["frontend_port"], 9000)
        self.assertEqual(projection["frontend_url"], "http://runtime.test:9000")
        self.assertEqual(projection["frontend_status"], "healthy")

        reversed_state = RunState(
            run_id="run-collision-reversed",
            mode="main",
            services=dict(reversed(list(services.items()))),
        )
        reversed_runtime = build_runtime_map(reversed_state, host="runtime.test")

        self.assertEqual(
            reversed_runtime["projects"]["Main"]["services"],
            projected_services,
        )
        self.assertEqual(reversed_runtime["projection"]["Main"], projection)

    def test_legacy_collision_suffix_without_project_metadata_stays_under_original_project(self) -> None:
        state = RunState(
            run_id="run-legacy-collision",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd="/main",
                    actual_port=8000,
                    status="running",
                ),
                "Main Backend Restart Collision 2": ServiceRecord(
                    name="Main Backend Restart Collision 2",
                    type="backend",
                    cwd="/replacement",
                    actual_port=8001,
                    status="termination_failed",
                ),
            },
        )

        runtime = build_runtime_map(state)

        self.assertEqual(set(runtime["projects"]), {"Main"})
        self.assertEqual(
            set(runtime["projects"]["Main"]["services"]),
            {"backend", "backend@Main Backend Restart Collision 2"},
        )
        self.assertEqual(runtime["projection"]["Main"]["backend_port"], 8000)

    def test_multi_project_projection_uses_per_project_backend_port(self) -> None:
        state = RunState(
            run_id="run-2",
            mode="trees",
            services={
                "Tree Alpha Backend": ServiceRecord(
                    name="Tree Alpha Backend",
                    type="backend",
                    cwd="/tmp/tree-alpha/backend",
                    requested_port=8000,
                    actual_port=8100,
                    status="running",
                ),
                "Tree Alpha Frontend": ServiceRecord(
                    name="Tree Alpha Frontend",
                    type="frontend",
                    cwd="/tmp/tree-alpha/frontend",
                    requested_port=9000,
                    actual_port=9100,
                    status="running",
                ),
                "Tree Beta Backend": ServiceRecord(
                    name="Tree Beta Backend",
                    type="backend",
                    cwd="/tmp/tree-beta/backend",
                    requested_port=8020,
                    actual_port=8200,
                    status="running",
                ),
                "Tree Beta Frontend": ServiceRecord(
                    name="Tree Beta Frontend",
                    type="frontend",
                    cwd="/tmp/tree-beta/frontend",
                    requested_port=9020,
                    actual_port=9200,
                    status="running",
                ),
            },
        )

        alpha_env = frontend_env_for_project(state, "Tree Alpha")
        beta_env = frontend_env_for_project(state, "Tree Beta")
        projection = build_runtime_projection(state)

        self.assertEqual(alpha_env["VITE_BACKEND_URL"], "http://localhost:8100")
        self.assertEqual(beta_env["VITE_BACKEND_URL"], "http://localhost:8200")
        self.assertEqual(alpha_env["VITE_API_URL"], "http://localhost:8100/api/v1")
        self.assertEqual(beta_env["VITE_API_URL"], "http://localhost:8200/api/v1")
        self.assertEqual(projection["Tree Alpha"]["frontend_url"], "http://localhost:9100")
        self.assertEqual(projection["Tree Beta"]["frontend_url"], "http://localhost:9200")

    def test_project_name_match_is_exact_not_prefix_based(self) -> None:
        state = RunState(
            run_id="run-3",
            mode="trees",
            services={
                "feature-a-1 Backend": ServiceRecord(
                    name="feature-a-1 Backend",
                    type="backend",
                    cwd="/tmp/feature-a/1/backend",
                    requested_port=8000,
                    actual_port=8101,
                    status="running",
                ),
                "feature-a-1 Frontend": ServiceRecord(
                    name="feature-a-1 Frontend",
                    type="frontend",
                    cwd="/tmp/feature-a/1/frontend",
                    requested_port=9000,
                    actual_port=9101,
                    status="running",
                ),
                "feature-a-10 Backend": ServiceRecord(
                    name="feature-a-10 Backend",
                    type="backend",
                    cwd="/tmp/feature-a/10/backend",
                    requested_port=8020,
                    actual_port=8110,
                    status="running",
                ),
            },
        )

        env = frontend_env_for_project(state, "feature-a-1")

        self.assertEqual(env["VITE_BACKEND_URL"], "http://localhost:8101")
        self.assertEqual(env["VITE_API_URL"], "http://localhost:8101/api/v1")


if __name__ == "__main__":
    unittest.main()
