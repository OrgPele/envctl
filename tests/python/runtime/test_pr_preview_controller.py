from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
import sys

import pytest

import envctl_engine.pr_preview_controller as preview_controller


def load_controller():
    return preview_controller


class FakeRunner:
    def __init__(
        self,
        controller,
        *,
        active_prs=None,
        timeline: str = "labeled\t2000-01-01T00:00:00Z\tdeploy-app\n",
        projects=None,
        endpoints=None,
        root_to_branch=None,
        start_returncode: int = 0,
        start_stdout: str = "",
        start_stderr: str = "",
        stop_returncode: int = 0,
        stop_stdout: str = "",
        stop_stderr: str = "",
        blast_returncode: int = 0,
        blast_stdout: str = "",
        blast_stderr: str = "",
        import_results=None,
    ):
        self.controller = controller
        self.active_prs = active_prs or []
        self.timeline = timeline
        self.projects = projects or {"projects": []}
        self.endpoints = endpoints or {}
        self.root_to_branch = root_to_branch or {}
        self.start_returncode = start_returncode
        self.start_stdout = start_stdout
        self.start_stderr = start_stderr
        self.stop_returncode = stop_returncode
        self.stop_stdout = stop_stdout
        self.stop_stderr = stop_stderr
        self.blast_returncode = blast_returncode
        self.blast_stdout = blast_stdout
        self.blast_stderr = blast_stderr
        self.import_results = list(import_results or [])
        self.calls = []
        self.comments = []
        self.deployments = []
        self.deployment_statuses = []
        self.removed_labels = []

    def run(
        self,
        argv,
        *,
        cwd=None,
        check=True,
        input_text=None,
        timeout=None,
        env=None,
        display_argv=None,
    ):
        del check, timeout, display_argv
        self.calls.append(
            {
                "argv": list(argv),
                "cwd": cwd,
                "input_text": input_text,
                "env": dict(env or {}),
            }
        )
        if argv[:3] == ["gh", "issue", "comment"]:
            self.comments.append(input_text or "")
            return self.ok(argv)
        if argv[:3] == ["gh", "issue", "edit"]:
            self.removed_labels.append(argv[-1])
            return self.ok(argv)
        if (
            argv[:4] == ["gh", "api", "-X", "POST"]
            and len(argv) >= 5
            and argv[4].endswith("/deployments")
        ):
            self.deployments.append(json.loads(input_text or "{}"))
            return self.ok(argv, stdout="12345\n")
        if (
            argv[:4] == ["gh", "api", "-X", "POST"]
            and len(argv) >= 5
            and "/deployments/" in argv[4]
            and argv[4].endswith("/statuses")
        ):
            self.deployment_statuses.append(json.loads(input_text or "{}"))
            return self.ok(argv, stdout="{}\n")
        if argv[:2] == ["gh", "api"]:
            return self.ok(argv, stdout=self.timeline)
        if argv[:3] == ["gh", "auth", "setup-git"]:
            return self.ok(argv)
        if argv[:3] == ["gh", "repo", "clone"]:
            repo_path = Path(argv[-1])
            (repo_path / ".git").mkdir(parents=True, exist_ok=True)
            (repo_path / ".envctl").write_text(self.controller.default_envctl_config())
            return self.ok(argv)
        if argv[:3] == ["git", "fetch", "origin"]:
            return self.ok(argv)
        if argv[:2] == ["git", "-C"]:
            branch = self.root_to_branch.get(str(argv[2]), "feature/demo")
            return self.ok(argv, stdout=f"{branch}\n")
        if argv[:5] == ["docker", "ps", "-aq", "--filter", "name=feature-demo"]:
            return self.ok(argv, stdout="container-a\ncontainer-b\n")
        if argv[:6] == [
            "docker",
            "volume",
            "ls",
            "-q",
            "--filter",
            "name=feature-demo",
        ]:
            return self.ok(argv, stdout="volume-a\n")
        if argv[:6] == [
            "docker",
            "network",
            "ls",
            "-q",
            "--filter",
            "name=feature-demo",
        ]:
            return self.ok(argv, stdout="network-a\n")
        if argv[:5] == [
            "docker",
            "ps",
            "-aq",
            "--filter",
            "name=codex-address-pr283-doc-hygiene",
        ]:
            return self.ok(argv, stdout="orphan-container\n")
        if argv[:6] == [
            "docker",
            "volume",
            "ls",
            "-q",
            "--filter",
            "name=codex-address-pr283-doc-hygiene",
        ]:
            return self.ok(argv, stdout="orphan-volume\n")
        if argv[:6] == [
            "docker",
            "network",
            "ls",
            "-q",
            "--filter",
            "name=codex-address-pr283-doc-hygiene",
        ]:
            return self.ok(argv, stdout="orphan-network\n")
        if argv and argv[0] == "docker":
            return self.ok(argv, stdout="db\nredis\n")
        if argv[:2] == ["envctl", "import"]:
            if self.import_results:
                result = self.import_results.pop(0)
                return self.controller.CommandResult(
                    argv=list(argv),
                    returncode=result.get("returncode", 0),
                    stdout=result.get("stdout", ""),
                    stderr=result.get("stderr", ""),
                )
            return self.ok(argv)
        if argv[:2] == ["envctl", "list-trees"]:
            return self.ok(argv, stdout=json.dumps(self.projects))
        if argv[:2] == ["envctl", "endpoints"]:
            return self.ok(argv, stdout=json.dumps(self.endpoints))
        if argv[:2] == ["envctl", "start"]:
            return self.controller.CommandResult(
                argv=list(argv),
                returncode=self.start_returncode,
                stdout=self.start_stdout,
                stderr=self.start_stderr,
            )
        if argv[:3] == ["envctl", "qa-user", "ensure"]:
            return self.ok(argv, stdout="ok\n")
        if argv[:2] == ["envctl", "stop"]:
            return self.controller.CommandResult(
                argv=list(argv),
                returncode=self.stop_returncode,
                stdout=self.stop_stdout,
                stderr=self.stop_stderr,
            )
        if argv[:2] == ["envctl", "blast-worktree"]:
            return self.controller.CommandResult(
                argv=list(argv),
                returncode=self.blast_returncode,
                stdout=self.blast_stdout,
                stderr=self.blast_stderr,
            )
        if argv[:2] in (["envctl", "delete-worktree"], ["envctl", "blast-all"]):
            return self.ok(argv)
        return self.ok(argv)

    def json(self, argv, *, cwd=None):
        self.calls.append({"argv": list(argv), "cwd": cwd, "input_text": None, "env": {}})
        if argv[:3] == ["gh", "pr", "list"]:
            return self.active_prs
        raise AssertionError(f"unexpected json command: {argv}")

    def ok(self, argv, stdout=""):
        return self.controller.CommandResult(
            argv=list(argv),
            returncode=0,
            stdout=stdout,
            stderr="",
        )


def make_config(controller, tmp_path, *, ttl_minutes=30):
    control_repo = tmp_path / "control"
    (control_repo / ".git").mkdir(parents=True)
    (control_repo / ".envctl").write_text(controller.default_envctl_config())
    return controller.ControllerConfig(
        repo_slug="OrgPele/pele-monorepo",
        label="deploy-app",
        ttl_minutes=ttl_minutes,
        preview_root=tmp_path,
        control_repo=control_repo,
        state_dir=tmp_path / "state",
        envctl_bin="envctl",
        public_host="localhost",
        public_base_domain="",
        public_scheme="https",
        public_route_image="alpine:3.20",
        ui_visual_host="localhost",
        public_link_token_configured=False,
        bootstrap_envctl_config=True,
        max_load_per_cpu=999.0,
        min_memory_available_percent=0.0,
        min_disk_free_percent=0.0,
        max_other_active_previews=99,
        dry_run=False,
    )


def test_render_qa_user_email_templates_and_validates_public_address():
    controller = load_controller()

    assert (
        controller.render_qa_user_email(
            "qa-preview+pr{pr_number}@getpele.tech",
            285,
        )
        == "qa-preview+pr285@getpele.tech"
    )
    assert (
        controller.render_qa_user_email("qa-preview@getpele.tech", 285)
        == "qa-preview@getpele.tech"
    )
    with pytest.raises(ValueError, match="reserved or local-only"):
        controller.render_qa_user_email("qa@pele.local", 285)
    with pytest.raises(ValueError, match="supports only"):
        controller.render_qa_user_email("qa+{branch}@getpele.tech", 285)


def supabase_external_pool(controller):
    return controller.parse_external_dependency_pools(
        json.dumps(
            {
                "supabase": [
                    {
                        "id": "supabase-a",
                        "backend_env": {
                            "SUPABASE_URL": "https://slot-a.supabase.test",
                            "SUPABASE_ANON_KEY": "anon-a",
                            "SUPABASE_SERVICE_ROLE_KEY": "service-a",
                        },
                        "frontend_env": {
                            "VITE_SUPABASE_URL": "https://slot-a.supabase.test",
                            "VITE_SUPABASE_ANON_KEY": "anon-a",
                        },
                    }
                ]
            }
        )
    )


def pr_payload(*, action, labels=None, event_label=None, merged=False):
    labels = labels or []
    payload = {
        "action": action,
        "pull_request": {
            "number": 789,
            "title": "Preview me",
            "html_url": "https://github.com/OrgPele/pele-monorepo/pull/789",
            "state": "closed" if action == "closed" else "open",
            "merged": merged,
            "head": {
                "ref": "feature/demo",
                "sha": "abc123456789",
                "repo": {
                    "name": "pele-monorepo",
                    "owner": {"login": "OrgPele"},
                },
            },
            "labels": [{"name": label} for label in labels],
        },
    }
    if event_label:
        payload["label"] = {"name": event_label}
    return payload


def push_payload(ref="refs/heads/feature/demo", *, deleted=False):
    return {
        "deleted": deleted,
        "ref": ref,
        "repository": {
            "name": "pele-monorepo",
            "owner": {"login": "OrgPele"},
        },
    }


def pr_list_payload(number, title, head_ref="feature/demo"):
    return {
        "number": number,
        "title": title,
        "url": f"https://github.com/OrgPele/pele-monorepo/pull/{number}",
        "state": "OPEN",
        "headRefName": head_ref,
        "headRefOid": "abc123456789",
        "headRepository": {
            "name": "pele-monorepo",
            "nameWithOwner": "OrgPele/pele-monorepo",
        },
        "headRepositoryOwner": {"login": "OrgPele"},
        "labels": [{"name": "deploy-app"}],
    }


def command_argvs(runner, *prefix):
    return [
        call["argv"]
        for call in runner.calls
        if call["argv"][: len(prefix)] == list(prefix)
    ]


def test_timeline_label_active_since_uses_latest_label_span():
    controller = load_controller()
    lines = [
        "labeled\t2026-06-14T10:00:00Z\tdeploy-app",
        "unlabeled\t2026-06-14T10:10:00Z\tdeploy-app",
        "labeled\t2026-06-14T10:20:00Z\tother",
        "labeled\t2026-06-14T10:30:00Z\tdeploy-app",
    ]

    result = controller.timeline_label_active_since(lines, "deploy-app")

    assert result == datetime(2026, 6, 14, 10, 30, tzinfo=UTC)


def test_timeline_label_active_since_returns_none_after_unlabel():
    controller = load_controller()
    lines = [
        "labeled\t2026-06-14T10:00:00Z\tdeploy-app",
        "unlabeled\t2026-06-14T10:10:00Z\tdeploy-app",
    ]

    assert controller.timeline_label_active_since(lines, "deploy-app") is None


def test_select_project_prefers_running_project_matching_branch_name():
    controller = load_controller()
    projects = [
        {"name": "feature/demo", "root": "/tmp/demo-old", "running": False},
        {"name": "feature/demo", "root": "/tmp/demo-live", "running": True},
    ]

    result = controller.select_project_for_branch(
        projects,
        "feature/demo",
        lambda root: "feature/demo" if root.endswith("live") else None,
    )

    assert result["root"] == "/tmp/demo-live"


def test_pr_from_gh_payload_accepts_current_gh_repository_shape():
    controller = load_controller()
    payload = {
        "number": 278,
        "title": "Dev",
        "url": "https://github.com/OrgPele/pele-monorepo/pull/278",
        "state": "OPEN",
        "mergedAt": None,
        "headRefName": "dev",
        "headRefOid": "abc123",
        "headRepository": {
            "name": "pele-monorepo",
            "nameWithOwner": "OrgPele/pele-monorepo",
        },
        "headRepositoryOwner": {"login": "OrgPele"},
        "labels": [{"name": "deploy-app"}],
    }

    pr = controller.pr_from_gh_payload(payload)

    assert pr.head_repo_owner == "OrgPele"
    assert pr.head_repo_name == "pele-monorepo"
    assert pr.merged is False
    assert pr.labels == ("deploy-app",)


def test_pr_from_gh_payload_falls_back_to_name_with_owner():
    controller = load_controller()
    payload = {
        "number": 278,
        "title": "Dev",
        "url": "https://github.com/OrgPele/pele-monorepo/pull/278",
        "state": "MERGED",
        "mergedAt": "2026-06-14T12:00:00Z",
        "headRefName": "dev",
        "headRefOid": "abc123",
        "headRepository": {"nameWithOwner": "OrgPele/pele-monorepo"},
        "labels": [],
    }

    pr = controller.pr_from_gh_payload(payload)

    assert pr.head_repo_owner == "OrgPele"
    assert pr.head_repo_name == "pele-monorepo"
    assert pr.merged is True


def test_overload_reasons_report_real_threshold_breaches(tmp_path):
    controller = load_controller()
    config = controller.ControllerConfig(
        repo_slug="OrgPele/pele-monorepo",
        label="deploy-app",
        ttl_minutes=45,
        preview_root=tmp_path,
        control_repo=tmp_path / "repo",
        state_dir=tmp_path / "state",
        envctl_bin="envctl",
        public_host="localhost",
        public_base_domain="",
        public_scheme="https",
        public_route_image="alpine:3.20",
        ui_visual_host="localhost",
        public_link_token_configured=False,
        bootstrap_envctl_config=True,
        max_load_per_cpu=1.0,
        min_memory_available_percent=20.0,
        min_disk_free_percent=10.0,
        max_other_active_previews=1,
        dry_run=False,
    )
    stats = controller.MachineStats(
        load_1m=8.0,
        load_5m=5.0,
        load_15m=3.0,
        cpu_count=4,
        memory_total_bytes=100,
        memory_available_bytes=10,
        disk_total_bytes=100,
        disk_free_bytes=9,
        docker_running_containers=4,
        docker_error=None,
        top_processes=(),
    )
    other = controller.PullRequestInfo(
        number=123,
        title="Other",
        url="https://example.test/pr/123",
        state="OPEN",
        merged=False,
        head_ref="feature/other",
        head_sha="abc",
        head_repo_name="pele-monorepo",
        head_repo_owner="OrgPele",
        labels=("deploy-app",),
    )

    reasons = controller.overload_reasons(stats, [other], 456, config)

    assert any("1m load per CPU" in reason for reason in reasons)
    assert any("available memory" in reason for reason in reasons)
    assert any("free disk" in reason for reason in reasons)
    assert any("other envctl previews" in reason for reason in reasons)


def test_overloaded_start_comments_stats_lists_other_prs_and_removes_label(
    tmp_path,
    monkeypatch,
):
    controller = load_controller()
    base_config = make_config(controller, tmp_path)
    config = controller.ControllerConfig(
        **{**base_config.__dict__, "max_load_per_cpu": 1.0}
    )
    runner = FakeRunner(
        controller,
        active_prs=[
            pr_list_payload(789, "Current", head_ref="feature/demo"),
            pr_list_payload(123, "Other preview", head_ref="feature/other"),
        ],
    )
    instance = controller.PreviewController(config, runner)
    stats = controller.MachineStats(
        load_1m=8.0,
        load_5m=5.0,
        load_15m=3.0,
        cpu_count=4,
        memory_total_bytes=100,
        memory_available_bytes=50,
        disk_total_bytes=100,
        disk_free_bytes=80,
        docker_running_containers=7,
        docker_error=None,
        top_processes=("111 python 250.0 5.0",),
    )
    monkeypatch.setattr(controller, "collect_machine_stats", lambda *_: stats)

    exit_code = instance.run_pull_request_event(
        pr_payload(
            action="labeled",
            labels=["deploy-app"],
            event_label="deploy-app",
        )
    )

    assert exit_code == 0
    assert command_argvs(runner, "envctl", "import") == []
    assert runner.removed_labels == ["deploy-app"]
    comment = runner.comments[-1]
    assert "self-hosted machine is overloaded" in comment
    assert "Load average: 8.00, 5.00, 3.00" in comment
    assert "#123: [Other preview]" in comment
    assert "111 python 250.0 5.0" in comment


def test_overloaded_start_stops_existing_tracked_preview_before_label_removal(
    tmp_path,
    monkeypatch,
):
    controller = load_controller()
    base_config = make_config(controller, tmp_path)
    config = controller.ControllerConfig(
        **{**base_config.__dict__, "max_load_per_cpu": 1.0}
    )
    runner = FakeRunner(
        controller,
        active_prs=[pr_list_payload(789, "Current", head_ref="feature/demo")],
    )
    instance = controller.PreviewController(config, runner)
    instance.save_state(
        controller.PreviewState(
            pr_number=789,
            label="deploy-app",
            project="feature/demo",
            root=str(tmp_path / "control" / "trees" / "imported" / "feature-demo"),
            head_ref="feature/demo",
            head_sha="abc123456789",
            status="running",
            label_added_at="2026-06-14T00:00:00Z",
            started_at="2026-06-14T00:00:00Z",
            expires_at="2026-06-14T00:45:00Z",
            updated_at="2026-06-14T00:00:00Z",
            endpoints={},
        )
    )
    stats = controller.MachineStats(
        load_1m=8.0,
        load_5m=5.0,
        load_15m=3.0,
        cpu_count=4,
        memory_total_bytes=100,
        memory_available_bytes=50,
        disk_total_bytes=100,
        disk_free_bytes=80,
        docker_running_containers=7,
        docker_error=None,
        top_processes=(),
    )
    monkeypatch.setattr(controller, "collect_machine_stats", lambda *_: stats)

    exit_code = instance.run_pull_request_event(
        pr_payload(
            action="synchronize",
            labels=["deploy-app"],
        )
    )

    assert exit_code == 0
    assert command_argvs(runner, "envctl", "stop") == [
        ["envctl", "stop", "--trees", "--project", "feature/demo", "--entire-system"]
    ]
    assert command_argvs(runner, "envctl", "import") == []
    assert instance.load_state(789).status == "stopped"
    assert runner.removed_labels == ["deploy-app"]


def test_labeled_event_imports_branch_with_isolated_deps_and_saves_state(
    tmp_path,
    monkeypatch,
):
    controller = load_controller()
    root = tmp_path / "control" / "trees" / "imported" / "feature-demo"
    root.mkdir(parents=True)
    runner = FakeRunner(
        controller,
        projects={
            "projects": [
                {"name": "feature/demo", "root": str(root), "running": True}
            ]
        },
        endpoints={
            "frontend": {
                "port": 9000,
                "public_url": "https://preview.example.test",
            },
            "backend": {
                "port": 8000,
                "local_url": "http://127.0.0.1:8000",
            },
            "dependencies": {
                "supabase": {
                    "port": 54321,
                    "resources": {
                        "api": 54321,
                    },
                },
            },
        },
        root_to_branch={str(root): "feature/demo"},
    )
    base_config = make_config(controller, tmp_path)
    config = controller.ControllerConfig(
        **{
            **base_config.__dict__,
            "public_host": "preview.getpele.test",
            "public_base_domain": "srv.example.test",
            "public_scheme": "https",
            "ui_visual_host": "visual.getpele.test",
            "public_link_token_configured": True,
        }
    )
    instance = controller.PreviewController(config, runner)
    monkeypatch.setenv("GH_TOKEN", "secret")
    monkeypatch.setenv("CMUX_WORKSPACE_ID", "workspace:1")
    monkeypatch.setenv("ENVCTL_SOURCE_PAYMENT_PROVIDER", "paddle")
    monkeypatch.setenv("ENVCTL_SOURCE_PADDLE_BILLING_ENABLED", "true")
    monkeypatch.setenv(
        "ENVCTL_SOURCE_PADDLE_GROWTH_MONTHLY_PRICE_ID",
        "pri_growth_monthly",
    )
    monkeypatch.setenv("ENVCTL_BACKEND_ENV__PADDLE_BILLING_ENABLED", "true")
    monkeypatch.setenv(
        "ENVCTL_FRONTEND_ENV__VITE_PADDLE_CLIENT_TOKEN",
        "test-client-token",
    )

    exit_code = instance.run_pull_request_event(
        pr_payload(
            action="labeled",
            labels=["deploy-app"],
            event_label="deploy-app",
        )
    )

    assert exit_code == 0
    import_calls = command_argvs(runner, "envctl", "import")
    assert import_calls == [
        [
            "envctl",
            "import",
            "feature/demo",
            "--headless",
            "--no-infra",
            "--isolated-deps",
            "--no-resume",
        ]
    ]
    assert command_argvs(runner, "envctl", "start") == [
        [
            "envctl",
            "start",
            "--trees",
            "--project",
            "feature/demo",
            "--headless",
            "--entire-system",
            "--isolated-deps",
            "--copy-db-storage",
        ]
    ]
    assert command_argvs(runner, "envctl", "qa-user") == [
        [
            "envctl",
            "qa-user",
            "ensure",
            "--project",
            "feature/demo",
            "--email",
            "qa-preview@getpele.tech",
            "--password",
            "Pele-QA-2026!",
            "--update-password",
        ]
    ]
    import_call = next(
        call for call in runner.calls if call["argv"][:2] == ["envctl", "import"]
    )
    start_call = next(
        call for call in runner.calls if call["argv"][:2] == ["envctl", "start"]
    )
    assert import_call["env"]["GH_TOKEN"] == "secret"
    assert "CMUX_WORKSPACE_ID" not in import_call["env"]
    assert import_call["env"]["ENVCTL_PLAN_AGENT_TERMINALS_ENABLE"] == "false"
    assert import_call["env"]["RUN_SH_RUNTIME_DIR"] == str(tmp_path / "runtime")
    assert "GH_TOKEN" not in start_call["env"]
    assert "CMUX_WORKSPACE_ID" not in start_call["env"]
    assert start_call["env"]["ENVCTL_PLAN_AGENT_TERMINALS_ENABLE"] == "false"
    assert start_call["env"]["RUN_SH_RUNTIME_DIR"] == str(tmp_path / "runtime")
    assert start_call["env"]["ENVCTL_SOURCE_PAYMENT_PROVIDER"] == "paddle"
    assert start_call["env"]["ENVCTL_SOURCE_PADDLE_BILLING_ENABLED"] == "true"
    assert (
        start_call["env"]["ENVCTL_SOURCE_PADDLE_GROWTH_MONTHLY_PRICE_ID"]
        == "pri_growth_monthly"
    )
    assert start_call["env"]["ENVCTL_BACKEND_ENV__PADDLE_BILLING_ENABLED"] == "true"
    assert (
        start_call["env"]["ENVCTL_FRONTEND_ENV__VITE_PADDLE_CLIENT_TOKEN"]
        == "test-client-token"
    )
    assert (
        start_call["env"]["ENVCTL_BACKEND_ENV__FRONTEND_BASE_URL"]
        == "https://pele-monorepo-pr-789.srv.example.test"
    )
    assert (
        start_call["env"]["ENVCTL_BACKEND_ENV__BACKEND_PUBLIC_URL"]
        == "https://pele-monorepo-pr-789-api.srv.example.test"
    )
    assert (
        start_call["env"]["ENVCTL_BACKEND_ENV__CORS_ORIGINS_RAW"]
        == "https://pele-monorepo-pr-789.srv.example.test"
    )
    assert start_call["env"]["ENVCTL_BACKEND_ENV__RUN_DB_MIGRATIONS_ON_STARTUP"] == (
        "true"
    )
    assert start_call["env"]["ENVCTL_BACKEND_ENV__PYTHONFAULTHANDLER"] == "1"
    assert start_call["env"].get("PYTHON_BIN")
    assert (
        start_call["env"]["ENVCTL_BACKEND_ENV__ALLOW_LEGACY_SUPABASE_HS256"]
        == "true"
    )
    assert (
        start_call["env"]["ENVCTL_FRONTEND_ENV__VITE_API_URL"]
        == "https://pele-monorepo-pr-789-api.srv.example.test/api/v1"
    )
    assert (
        start_call["env"]["ENVCTL_FRONTEND_ENV__VITE_SUPABASE_URL"]
        == "https://pele-monorepo-pr-789-supabase.srv.example.test"
    )
    state = instance.load_state(789)
    assert state is not None
    assert state.project == "feature/demo"
    assert state.root == str(root)
    assert state.status == "running"
    assert (
        state.endpoints["frontend"]["public_url"]
        == "https://pele-monorepo-pr-789.srv.example.test"
    )
    assert (
        state.endpoints["backend"]["public_url"]
        == "https://pele-monorepo-pr-789-api.srv.example.test"
    )
    assert (
        state.endpoints["supabase"]["public_url"]
        == "https://pele-monorepo-pr-789-supabase.srv.example.test"
    )
    assert state.deployment_id == "12345"
    assert runner.deployments == [
        {
            "ref": "abc123456789",
            "environment": "pele-monorepo-pr-789",
            "description": "Envctl PR preview for PR #789",
            "auto_merge": False,
            "required_contexts": [],
            "transient_environment": True,
            "production_environment": False,
        }
    ]
    assert runner.deployment_statuses == [
        {
            "state": "success",
            "description": "Envctl preview is running",
            "auto_inactive": False,
            "environment_url": "https://pele-monorepo-pr-789.srv.example.test",
            "log_url": "https://github.com/OrgPele/pele-monorepo/pull/789",
        }
    ]
    docker_runs = command_argvs(runner, "docker", "run")
    assert len(docker_runs) == 3
    docker_removes = command_argvs(runner, "docker", "rm", "-f")
    assert [
        "envctl-preview-pr-789-frontend",
        "envctl-preview-pr-789-backend",
        "envctl-preview-pr-789-supabase",
    ] == [argv[-1] for argv in docker_removes]
    assert any(
        "traefik.http.routers.envctl-preview-pr-789-frontend.rule="
        "Host(`pele-monorepo-pr-789.srv.example.test`)" in argv
        for argv in docker_runs
    )
    assert any(
        "traefik.http.routers.envctl-preview-pr-789-supabase.rule="
        "Host(`pele-monorepo-pr-789-supabase.srv.example.test`)" in argv
        for argv in docker_runs
    )
    assert any(
        "traefik.http.services.envctl-preview-pr-789-frontend."
        "loadbalancer.passhostheader=false" in argv
        for argv in docker_runs
    )
    envctl_text = (tmp_path / "control" / ".envctl").read_text()
    assert "ENVCTL_PUBLIC_HOST=preview.getpele.test" in envctl_text
    assert "ENVCTL_UI_VISUAL_HOST=visual.getpele.test" in envctl_text
    backend_start = envctl_text.split("ENVCTL_BACKEND_START_CMD=", 1)[1].split(
        "\n",
        1,
    )[0]
    frontend_start = envctl_text.split("ENVCTL_FRONTEND_START_CMD=", 1)[1].split(
        "\n",
        1,
    )[0]
    assert 'sh -c \'export PATH="$PWD/venv/bin:$PATH" ' in backend_start
    assert "FRONTEND_BASE_URL=https://pele-monorepo-pr-789.srv.example.test" in (
        backend_start
    )
    assert (
        "BACKEND_PUBLIC_URL=https://pele-monorepo-pr-789-api.srv.example.test"
        in backend_start
    )
    assert "CORS_ORIGINS_RAW=https://pele-monorepo-pr-789.srv.example.test" in (
        backend_start
    )
    assert "PYTHONFAULTHANDLER=1" in backend_start
    assert "RUN_DB_MIGRATIONS_ON_STARTUP=true" in backend_start
    assert 'PAYMENT_PROVIDER="${ENVCTL_SOURCE_PAYMENT_PROVIDER:-}"' in backend_start
    assert (
        'CREEM_BILLING_ENABLED="${ENVCTL_SOURCE_CREEM_BILLING_ENABLED:-}"'
        in backend_start
    )
    assert 'CREEM_ENVIRONMENT="${ENVCTL_SOURCE_CREEM_ENVIRONMENT:-}"' in (
        backend_start
    )
    assert 'CREEM_API_KEY="${ENVCTL_SOURCE_CREEM_API_KEY:-}"' in backend_start
    assert (
        'CREEM_STARTER_MONTHLY_PRODUCT_ID="'
        '${ENVCTL_SOURCE_CREEM_STARTER_MONTHLY_PRODUCT_ID:-}"' in backend_start
    )
    assert (
        'PADDLE_BILLING_ENABLED="${ENVCTL_SOURCE_PADDLE_BILLING_ENABLED:-}"'
        in backend_start
    )
    assert 'PADDLE_API_KEY="${ENVCTL_SOURCE_PADDLE_API_KEY:-}"' in backend_start
    assert (
        'PADDLE_GROWTH_MONTHLY_PRICE_ID="'
        '${ENVCTL_SOURCE_PADDLE_GROWTH_MONTHLY_PRICE_ID:-}"' in backend_start
    )
    assert "ALLOW_LEGACY_SUPABASE_HS256=true" in backend_start
    assert "exec python -m uvicorn app.main:app --host 127.0.0.1 --port" in (
        backend_start
    )
    assert (
        "ENVCTL_FRONTEND_START_CMD=sh -c 'export VITE_API_URL="
        "https://pele-monorepo-pr-789-api.srv.example.test/api/v1" in envctl_text
    )
    assert "VITE_BACKEND_URL=https://pele-monorepo-pr-789-api.srv.example.test" in (
        frontend_start
    )
    assert (
        "VITE_SUPABASE_URL=https://pele-monorepo-pr-789-supabase.srv.example.test"
        in frontend_start
    )
    assert (
        'VITE_PADDLE_CLIENT_TOKEN="${ENVCTL_SOURCE_VITE_PADDLE_CLIENT_TOKEN:-}"'
        in frontend_start
    )
    assert "exec npm run dev -- --port" in frontend_start
    assert "# >>> envctl backend launch env >>>" in envctl_text
    assert "DATABASE_URL=${ENVCTL_SOURCE_DATABASE_URL}" in envctl_text
    assert "REDIS_URL=${ENVCTL_SOURCE_REDIS_URL}" in envctl_text
    assert "SUPABASE_URL=${ENVCTL_SOURCE_SUPABASE_URL}" in envctl_text
    assert "SUPABASE_ANON_KEY=${ENVCTL_SOURCE_SUPABASE_ANON_KEY}" in envctl_text
    assert "ALLOW_LEGACY_SUPABASE_HS256=true" in envctl_text
    assert "PYTHONFAULTHANDLER=1" in envctl_text
    assert (
        "ALLOW_LEGACY_SUPABASE_HS256="
        "${ENVCTL_SOURCE_ALLOW_LEGACY_SUPABASE_HS256}" not in envctl_text
    )
    assert (
        "GOOGLE_APPLICATION_CREDENTIALS="
        "${ENVCTL_SOURCE_GOOGLE_APPLICATION_CREDENTIALS}" in envctl_text
    )
    assert (
        "GCP_SERVICE_ACCOUNT_KEY=${ENVCTL_SOURCE_GCP_SERVICE_ACCOUNT_KEY}"
        in envctl_text
    )
    assert (
        "GOOGLE_OAUTH_CLIENT_SECRET=${ENVCTL_SOURCE_GOOGLE_OAUTH_CLIENT_SECRET}"
        in envctl_text
    )
    assert (
        "TWILIO_MASTER_AUTH_TOKEN=${ENVCTL_SOURCE_TWILIO_MASTER_AUTH_TOKEN}"
        in envctl_text
    )
    assert "PADDLE_BILLING_ENABLED=${ENVCTL_SOURCE_PADDLE_BILLING_ENABLED}" in (
        envctl_text
    )
    assert "PADDLE_ENVIRONMENT=${ENVCTL_SOURCE_PADDLE_ENVIRONMENT}" in envctl_text
    assert "PADDLE_API_KEY=${ENVCTL_SOURCE_PADDLE_API_KEY}" in envctl_text
    assert (
        "PADDLE_NOTIFICATION_WEBHOOK_SECRET="
        "${ENVCTL_SOURCE_PADDLE_NOTIFICATION_WEBHOOK_SECRET}" in envctl_text
    )
    assert (
        "PADDLE_GROWTH_MONTHLY_PRICE_ID="
        "${ENVCTL_SOURCE_PADDLE_GROWTH_MONTHLY_PRICE_ID}" in envctl_text
    )
    assert (
        "PADDLE_GROWTH_TRIAL_DAYS=${ENVCTL_SOURCE_PADDLE_GROWTH_TRIAL_DAYS}"
        in envctl_text
    )
    assert (
        "PADDLE_VALIDATE_PRICE_TRIALS="
        "${ENVCTL_SOURCE_PADDLE_VALIDATE_PRICE_TRIALS}" in envctl_text
    )
    assert (
        "FRONTEND_BASE_URL="
        "https://pele-monorepo-pr-789.srv.example.test" in envctl_text
    )
    assert (
        "BACKEND_PUBLIC_URL="
        "https://pele-monorepo-pr-789-api.srv.example.test" in envctl_text
    )
    assert (
        "CORS_ORIGINS_RAW="
        "https://pele-monorepo-pr-789.srv.example.test" in envctl_text
    )
    assert "RUN_DB_MIGRATIONS_ON_STARTUP=true" in envctl_text
    assert "# <<< envctl backend launch env <<<" in envctl_text
    assert "# >>> envctl frontend launch env >>>" in envctl_text
    assert (
        "VITE_SUPABASE_URL=https://pele-monorepo-pr-789-supabase.srv.example.test"
        in envctl_text
    )
    assert (
        "VITE_SUPABASE_ANON_KEY=${ENVCTL_SOURCE_SUPABASE_ANON_KEY}"
        in envctl_text
    )
    assert (
        "VITE_PADDLE_CLIENT_TOKEN=${ENVCTL_SOURCE_VITE_PADDLE_CLIENT_TOKEN}"
        in envctl_text
    )
    assert "PADDLE_API_KEY=${ENVCTL_SOURCE_PADDLE_API_KEY}" not in (
        envctl_text.split("# >>> envctl frontend launch env >>>", 1)[1]
    )
    assert (
        "VITE_API_URL="
        "https://pele-monorepo-pr-789-api.srv.example.test/api/v1" in envctl_text
    )
    assert "VITE_SUPABASE_URL=http://dev.getpele.tech" not in envctl_text
    assert "# <<< envctl frontend launch env <<<" in envctl_text
    assert "Envctl preview is running" in runner.comments[-1]
    assert "- Public host: `preview.getpele.test`" in runner.comments[-1]
    assert "- Public base domain: `srv.example.test`" in runner.comments[-1]
    assert "- Public link token: `configured`" in runner.comments[-1]
    assert "QA user:" in runner.comments[-1]
    assert "- Email: `qa-preview@getpele.tech`" in runner.comments[-1]
    assert "- Password: `Pele-QA-2026!`" in runner.comments[-1]
    assert "https://pele-monorepo-pr-789.srv.example.test" in runner.comments[-1]
    assert "https://pele-monorepo-pr-789-api.srv.example.test" in runner.comments[-1]
    assert "https://pele-monorepo-pr-789-supabase.srv.example.test" in runner.comments[-1]


def test_labeled_event_blasts_wrong_branch_import_target_and_retries(tmp_path):
    controller = load_controller()
    root = tmp_path / "control" / "trees" / "imported" / "feature-demo"
    root.mkdir(parents=True)
    runner = FakeRunner(
        controller,
        projects={
            "projects": [
                {"name": "feature/demo", "root": str(root), "running": True}
            ]
        },
        endpoints={"frontend": {"port": 9000}, "backend": {"port": 8000}},
        root_to_branch={str(root): "feature/demo"},
        import_results=[
            {
                "returncode": 1,
                "stderr": (
                    "Import reuse failed: imported worktree target already "
                    "exists on the wrong branch. actual_branch=main "
                    "expected_branch=feature/demo"
                ),
            },
            {"returncode": 0},
        ],
    )
    config = make_config(controller, tmp_path)
    instance = controller.PreviewController(config, runner)

    exit_code = instance.run_pull_request_event(
        pr_payload(
            action="labeled",
            labels=["deploy-app"],
            event_label="deploy-app",
        )
    )

    assert exit_code == 0
    assert len(command_argvs(runner, "envctl", "import")) == 2
    assert command_argvs(runner, "envctl", "blast-worktree") == [
        ["envctl", "blast-worktree", "--project", "feature/demo", "--yes"]
    ]
    sequence = [
        call["argv"][:2]
        for call in runner.calls
        if call["argv"][:2]
        in (
            ["envctl", "import"],
            ["envctl", "blast-worktree"],
            ["envctl", "start"],
        )
    ]
    assert sequence == [
        ["envctl", "import"],
        ["envctl", "blast-worktree"],
        ["envctl", "import"],
        ["envctl", "start"],
    ]
    state = instance.load_state(789)
    assert state is not None
    assert state.status == "running"


def test_labeled_event_refreshes_legacy_generated_envctl_config(tmp_path, monkeypatch):
    controller = load_controller()
    root = tmp_path / "control" / "trees" / "imported" / "feature-demo"
    root.mkdir(parents=True)
    runner = FakeRunner(
        controller,
        projects={
            "projects": [
                {"name": "feature/demo", "root": str(root), "running": True}
            ]
        },
        endpoints={
            "frontend": {"port": 9000},
            "backend": {"port": 8000},
            "dependencies": {
                "supabase": {"resources": {"api": 54321}},
            },
        },
        root_to_branch={str(root): "feature/demo"},
    )
    base_config = make_config(controller, tmp_path)
    config = controller.ControllerConfig(
        **{
            **base_config.__dict__,
            "public_base_domain": "srv.example.test",
            "public_link_token_configured": True,
        }
    )
    envctl_file = tmp_path / "control" / ".envctl"
    envctl_file.write_text(
        "\n".join(
            [
                "# Generated by .github/scripts/envctl_pr_preview.py for self-hosted PR previews.",
                "ENVCTL_BACKEND_START_CMD=old-pr-281-command",
                "FRONTEND_BASE_URL=https://envctl-pr-281.srv.example.test",
                "DATABASE_URL=${ENVCTL_SOURCE_DATABASE_URL}",
            ]
        )
    )
    instance = controller.PreviewController(config, runner)
    monkeypatch.setenv("GH_TOKEN", "secret")

    exit_code = instance.run_pull_request_event(
        pr_payload(
            action="labeled",
            labels=["deploy-app"],
            event_label="deploy-app",
        )
    )

    assert exit_code == 0
    refreshed = envctl_file.read_text()
    assert refreshed.startswith(controller.GENERATED_ENVCTL_HEADER)
    assert "old-pr-281-command" not in refreshed
    assert "envctl-pr-281" not in refreshed
    assert "https://pele-monorepo-pr-789.srv.example.test" in refreshed
    assert "https://pele-monorepo-pr-789-api.srv.example.test" in refreshed
    assert "https://pele-monorepo-pr-789-supabase.srv.example.test" in refreshed


def test_labeled_event_rejects_non_public_qa_user_email(tmp_path):
    controller = load_controller()
    root = tmp_path / "control" / "trees" / "imported" / "feature-demo"
    root.mkdir(parents=True)
    runner = FakeRunner(
        controller,
        projects={
            "projects": [
                {"name": "feature/demo", "root": str(root), "running": True}
            ]
        },
    )
    base_config = make_config(controller, tmp_path)
    config = controller.ControllerConfig(
        **{
            **base_config.__dict__,
            "qa_user_email": "qa@pele.local",
        }
    )
    instance = controller.PreviewController(config, runner)

    exit_code = instance.run_pull_request_event(
        pr_payload(
            action="labeled",
            labels=["deploy-app"],
            event_label="deploy-app",
        )
    )

    assert exit_code == 2
    assert command_argvs(runner, "envctl", "qa-user") == []
    assert instance.load_state(789).status == "qa_user_failed"
    assert "envctl QA user setup failed" in runner.comments[-1]
    assert "reserved or local-only domain" in runner.comments[-1]
    assert "Envctl preview is running" not in runner.comments[-1]


def test_started_comment_omits_qa_credentials_when_qa_user_disabled(tmp_path):
    controller = load_controller()
    base_config = make_config(controller, tmp_path)
    config = controller.ControllerConfig(
        **{
            **base_config.__dict__,
            "qa_user_enabled": False,
        }
    )
    runner = FakeRunner(controller)
    instance = controller.PreviewController(config, runner)
    comment = instance.render_started_comment(
        controller.PullRequestInfo(
            number=789,
            title="Preview me",
            url="https://github.com/OrgPele/pele-monorepo/pull/789",
            state="OPEN",
            merged=False,
            head_ref="feature/demo",
            head_sha="abc123456789",
            head_repo_name="pele-monorepo",
            head_repo_owner="OrgPele",
            labels=("deploy-app",),
        ),
        controller.PreviewState(
            pr_number=789,
            label="deploy-app",
            project="feature/demo",
            root=str(tmp_path / "control" / "trees" / "imported" / "feature-demo"),
            head_ref="feature/demo",
            head_sha="abc123456789",
            status="running",
            label_added_at="2026-06-14T00:00:00Z",
            started_at="2026-06-14T00:00:00Z",
            expires_at="2026-06-14T00:45:00Z",
            updated_at="2026-06-14T00:01:00Z",
            endpoints={
                "frontend": {"public_url": "https://pele-monorepo-pr-789.example.test"}
            },
        ),
        "label added",
    )

    assert "QA user:" not in comment
    assert "qa@pele.local" not in comment
    assert "Pele-QA-2026!" not in comment


def test_labeled_event_leases_external_supabase_without_storing_tokens(tmp_path):
    controller = load_controller()
    root = tmp_path / "control" / "trees" / "imported" / "feature-demo"
    root.mkdir(parents=True)
    runner = FakeRunner(
        controller,
        projects={
            "projects": [
                {"name": "feature/demo", "root": str(root), "running": True}
            ]
        },
        endpoints={"frontend": {"port": 9000}, "backend": {"port": 8000}},
        root_to_branch={str(root): "feature/demo"},
    )
    base_config = make_config(controller, tmp_path)
    config = controller.ControllerConfig(
        **{
            **base_config.__dict__,
            "external_dependency_pools": supabase_external_pool(controller),
        }
    )
    instance = controller.PreviewController(config, runner)

    exit_code = instance.run_pull_request_event(
        pr_payload(
            action="labeled",
            labels=["deploy-app"],
            event_label="deploy-app",
        )
    )

    assert exit_code == 0
    state = instance.load_state(789)
    assert state is not None
    assert state.external_dependencies == {"supabase": "supabase-a"}
    assert instance.load_external_dependency_leases() == {
        "supabase": {"supabase-a": 789}
    }
    start_call = next(
        call for call in runner.calls if call["argv"][:2] == ["envctl", "start"]
    )
    assert (
        start_call["env"]["ENVCTL_BACKEND_ENV__SUPABASE_URL"]
        == "https://slot-a.supabase.test"
    )
    assert start_call["env"]["ENVCTL_BACKEND_ENV__SUPABASE_ANON_KEY"] == "anon-a"
    assert (
        start_call["env"]["ENVCTL_BACKEND_ENV__SUPABASE_SERVICE_ROLE_KEY"]
        == "service-a"
    )
    assert (
        start_call["env"]["ENVCTL_FRONTEND_ENV__VITE_SUPABASE_URL"]
        == "https://slot-a.supabase.test"
    )
    assert (
        start_call["env"]["ENVCTL_FRONTEND_ENV__VITE_SUPABASE_ANON_KEY"]
        == "anon-a"
    )
    envctl_text = (tmp_path / "control" / ".envctl").read_text()
    assert "TREES_SUPABASE_ENABLE=false" in envctl_text
    assert "TREES_REDIS_ENABLE=true" in envctl_text
    assert "TREES_N8N_ENABLE=true" in envctl_text
    assert "https://slot-a.supabase.test" not in envctl_text
    assert "service-a" not in envctl_text
    assert "supabase=`supabase-a`" in runner.comments[-1]


def test_external_dep_pool_exhaustion_falls_back_to_isolated_deps(tmp_path):
    controller = load_controller()
    root = tmp_path / "control" / "trees" / "imported" / "feature-demo"
    root.mkdir(parents=True)
    runner = FakeRunner(
        controller,
        projects={
            "projects": [
                {"name": "feature/demo", "root": str(root), "running": True}
            ]
        },
        endpoints={"frontend": {"port": 9000}, "backend": {"port": 8000}},
        root_to_branch={str(root): "feature/demo"},
    )
    base_config = make_config(controller, tmp_path)
    config = controller.ControllerConfig(
        **{
            **base_config.__dict__,
            "external_dependency_pools": supabase_external_pool(controller),
        }
    )
    instance = controller.PreviewController(config, runner)
    instance.save_external_dependency_leases({"supabase": {"supabase-a": 111}})

    exit_code = instance.run_pull_request_event(
        pr_payload(
            action="labeled",
            labels=["deploy-app"],
            event_label="deploy-app",
        )
    )

    assert exit_code == 0
    state = instance.load_state(789)
    assert state is not None
    assert state.external_dependencies == {}
    assert instance.load_external_dependency_leases() == {
        "supabase": {"supabase-a": 111}
    }
    start_call = next(
        call for call in runner.calls if call["argv"][:2] == ["envctl", "start"]
    )
    assert "ENVCTL_BACKEND_ENV__SUPABASE_URL" not in start_call["env"]
    envctl_text = (tmp_path / "control" / ".envctl").read_text()
    assert "TREES_SUPABASE_ENABLE=true" in envctl_text
    assert "supabase=`isolated`" in runner.comments[-1]


def test_manual_start_refreshes_preview_ttl_when_label_is_old(tmp_path):
    controller = load_controller()
    root = tmp_path / "control" / "trees" / "imported" / "feature-demo"
    root.mkdir(parents=True)
    runner = FakeRunner(
        controller,
        timeline="labeled\t2000-01-01T00:00:00Z\tdeploy-app\n",
        projects={
            "projects": [
                {"name": "feature/demo", "root": str(root), "running": True}
            ]
        },
        endpoints={"frontend": {"port": 9000}, "backend": {"port": 8000}},
        root_to_branch={str(root): "feature/demo"},
    )
    config = make_config(controller, tmp_path, ttl_minutes=45)
    instance = controller.PreviewController(config, runner)
    pr = controller.pr_from_event(
        pr_payload(
            action="labeled",
            labels=["deploy-app"],
            event_label="deploy-app",
        )
    )

    exit_code = instance.start(
        pr,
        reason="manual workflow dispatch",
        refresh_ttl=True,
    )

    assert exit_code == 0
    state = instance.load_state(789)
    assert state is not None
    started_at = controller.parse_github_datetime(state.started_at)
    expires_at = controller.parse_github_datetime(state.expires_at)
    assert started_at is not None
    assert expires_at is not None
    assert expires_at > started_at
    assert (expires_at - started_at).total_seconds() > 44 * 60
    assert "2000-01-01" not in runner.comments[-1]


def test_push_event_refreshes_preview_ttl_for_labeled_branch(tmp_path):
    controller = load_controller()
    root = tmp_path / "control" / "trees" / "imported" / "feature-demo"
    root.mkdir(parents=True)
    runner = FakeRunner(
        controller,
        active_prs=[pr_list_payload(789, "Preview me", head_ref="feature/demo")],
        timeline="labeled\t2000-01-01T00:00:00Z\tdeploy-app\n",
        projects={
            "projects": [
                {"name": "feature/demo", "root": str(root), "running": True}
            ]
        },
        endpoints={"frontend": {"port": 9000}, "backend": {"port": 8000}},
        root_to_branch={str(root): "feature/demo"},
    )
    config = make_config(controller, tmp_path, ttl_minutes=45)
    instance = controller.PreviewController(config, runner)

    exit_code = instance.run_push_event(push_payload())

    assert exit_code == 0
    state = instance.load_state(789)
    assert state is not None
    started_at = controller.parse_github_datetime(state.started_at)
    expires_at = controller.parse_github_datetime(state.expires_at)
    assert started_at is not None
    assert expires_at is not None
    assert (expires_at - started_at).total_seconds() > 44 * 60
    assert "2000-01-01" not in runner.comments[-1]
    assert "- Reason: push to labeled PR branch feature/demo" in runner.comments[-1]


def test_push_event_ignores_unmatched_labeled_pr_branch(tmp_path):
    controller = load_controller()
    runner = FakeRunner(
        controller,
        active_prs=[pr_list_payload(789, "Other branch", head_ref="feature/other")],
    )
    config = make_config(controller, tmp_path)
    instance = controller.PreviewController(config, runner)

    exit_code = instance.run_push_event(push_payload())

    assert exit_code == 0
    assert command_argvs(runner, "envctl", "import") == []


def test_start_stops_existing_tracked_preview_before_reimport(tmp_path):
    controller = load_controller()
    root = tmp_path / "control" / "trees" / "imported" / "feature-demo"
    root.mkdir(parents=True)
    runner = FakeRunner(
        controller,
        projects={
            "projects": [
                {"name": "feature/demo", "root": str(root), "running": True}
            ]
        },
        endpoints={"frontend": {"port": 9000}, "backend": {"port": 8000}},
        root_to_branch={str(root): "feature/demo"},
    )
    config = make_config(controller, tmp_path)
    instance = controller.PreviewController(config, runner)
    instance.save_state(
        controller.PreviewState(
            pr_number=789,
            label="deploy-app",
            project="feature/demo",
            root=str(root),
            head_ref="feature/demo",
            head_sha="oldsha",
            status="running",
            label_added_at="2026-06-14T00:00:00Z",
            started_at="2026-06-14T00:00:00Z",
            expires_at="2026-06-14T00:45:00Z",
            updated_at="2026-06-14T00:00:00Z",
            endpoints={"frontend": {"port": 9001}, "backend": {"port": 8001}},
        )
    )
    pr = controller.pr_from_event(
        pr_payload(
            action="synchronize",
            labels=["deploy-app"],
            event_label="deploy-app",
        )
    )

    exit_code = instance.start(pr, reason="PR synchronize")

    assert exit_code == 0
    sequence = [
        call["argv"][:2]
        for call in runner.calls
        if call["argv"][:2]
        in (["envctl", "stop"], ["envctl", "import"], ["envctl", "start"])
    ]
    assert sequence == [
        ["envctl", "stop"],
        ["envctl", "import"],
        ["envctl", "stop"],
        ["envctl", "start"],
    ]
    assert command_argvs(runner, "envctl", "stop") == [
        ["envctl", "stop", "--trees", "--project", "feature/demo", "--entire-system"],
        ["envctl", "stop", "--trees", "--project", "feature/demo", "--entire-system"],
    ]
    state = instance.load_state(789)
    assert state is not None
    assert state.status == "running"
    assert state.head_sha == "abc123456789"


def test_synchronize_event_redeploys_labeled_pr(tmp_path):
    controller = load_controller()
    root = tmp_path / "control" / "trees" / "imported" / "feature-demo"
    root.mkdir(parents=True)
    runner = FakeRunner(
        controller,
        projects={
            "projects": [
                {"name": "feature/demo", "root": str(root), "running": True}
            ]
        },
        endpoints={"frontend": {"port": 9000}, "backend": {"port": 8000}},
        root_to_branch={str(root): "feature/demo"},
    )
    config = make_config(controller, tmp_path, ttl_minutes=45)
    instance = controller.PreviewController(config, runner)
    instance.save_state(
        controller.PreviewState(
            pr_number=789,
            label="deploy-app",
            project="feature/demo",
            root=str(root),
            head_ref="feature/demo",
            head_sha="oldsha",
            status="running",
            label_added_at="2026-06-14T00:00:00Z",
            started_at="2026-06-14T00:00:00Z",
            expires_at="2026-06-14T00:45:00Z",
            updated_at="2026-06-14T00:00:00Z",
            endpoints={},
        )
    )

    exit_code = instance.run_pull_request_event(
        pr_payload(action="synchronize", labels=["deploy-app"])
    )

    assert exit_code == 0
    sequence = [
        call["argv"][:2]
        for call in runner.calls
        if call["argv"][:2]
        in (["envctl", "stop"], ["envctl", "import"], ["envctl", "start"])
    ]
    assert sequence == [
        ["envctl", "stop"],
        ["envctl", "import"],
        ["envctl", "stop"],
        ["envctl", "start"],
    ]
    state = instance.load_state(789)
    assert state is not None
    assert state.head_sha == "abc123456789"
    started_at = controller.parse_github_datetime(state.started_at)
    expires_at = controller.parse_github_datetime(state.expires_at)
    assert started_at is not None
    assert expires_at is not None
    assert (expires_at - started_at).total_seconds() > 44 * 60
    assert "- Reason: new commit pushed" in runner.comments[-1]


def test_start_continues_when_pre_start_stop_has_no_selected_services(
    tmp_path,
    capsys,
):
    controller = load_controller()
    root = tmp_path / "control" / "trees" / "imported" / "feature-demo"
    root.mkdir(parents=True)
    runner = FakeRunner(
        controller,
        projects={
            "projects": [
                {"name": "feature/demo", "root": str(root), "running": False}
            ]
        },
        endpoints={"frontend": {"port": 9000}, "backend": {"port": 8000}},
        root_to_branch={str(root): "feature/demo"},
        stop_returncode=1,
        stop_stdout="No matching services selected for stop.",
    )
    config = make_config(controller, tmp_path)
    instance = controller.PreviewController(config, runner)
    pr = controller.pr_from_event(
        pr_payload(
            action="labeled",
            labels=["deploy-app"],
            event_label="deploy-app",
        )
    )

    exit_code = instance.start(pr, reason="label added")

    assert exit_code == 0
    assert command_argvs(runner, "envctl", "stop") == [
        ["envctl", "stop", "--trees", "--project", "feature/demo", "--entire-system"]
    ]
    assert command_argvs(runner, "envctl", "start")
    assert "pre-start stop failed; continuing" in capsys.readouterr().out
    state = instance.load_state(789)
    assert state is not None
    assert state.status == "running"


def test_start_blasts_previous_failed_preview_before_reimport(tmp_path):
    controller = load_controller()
    root = tmp_path / "control" / "trees" / "imported" / "feature-demo"
    root.mkdir(parents=True)
    runner = FakeRunner(
        controller,
        projects={
            "projects": [
                {"name": "feature/demo", "root": str(root), "running": False}
            ]
        },
        endpoints={"frontend": {"port": 9000}, "backend": {"port": 8000}},
        root_to_branch={str(root): "feature/demo"},
    )
    config = make_config(controller, tmp_path)
    instance = controller.PreviewController(config, runner)
    instance.save_state(
        controller.PreviewState(
            pr_number=789,
            label="deploy-app",
            project="feature/demo",
            root=str(root),
            head_ref="feature/demo",
            head_sha="oldsha",
            status="start_failed",
            label_added_at="2026-06-14T00:00:00Z",
            started_at="2026-06-14T00:00:00Z",
            expires_at="2026-06-14T00:45:00Z",
            updated_at="2026-06-14T00:00:00Z",
            endpoints={},
        )
    )
    pr = controller.pr_from_event(
        pr_payload(
            action="labeled",
            labels=["deploy-app"],
            event_label="deploy-app",
        )
    )

    exit_code = instance.start(pr, reason="label added")

    assert exit_code == 0
    sequence = [
        call["argv"][:2]
        for call in runner.calls
        if call["argv"][:2]
        in (
            ["envctl", "blast-worktree"],
            ["envctl", "stop"],
            ["envctl", "import"],
            ["envctl", "start"],
        )
    ]
    assert sequence == [
        ["envctl", "blast-worktree"],
        ["envctl", "import"],
        ["envctl", "stop"],
        ["envctl", "start"],
    ]
    assert command_argvs(runner, "envctl", "blast-worktree") == [
        ["envctl", "blast-worktree", "--project", "feature/demo", "--yes"]
    ]
    assert [
        "docker",
        "ps",
        "-aq",
        "--filter",
        "name=feature-demo",
    ] in command_argvs(runner, "docker", "ps")
    assert [
        "docker",
        "rm",
        "-f",
        "container-a",
        "container-b",
    ] in command_argvs(runner, "docker", "rm")
    assert [
        "docker",
        "volume",
        "rm",
        "-f",
        "volume-a",
    ] in command_argvs(runner, "docker", "volume")
    assert [
        "docker",
        "network",
        "rm",
        "network-a",
    ] in command_argvs(runner, "docker", "network")
    assert command_argvs(runner, "envctl", "stop") == [
        ["envctl", "stop", "--trees", "--project", "feature/demo", "--entire-system"]
    ]
    state = instance.load_state(789)
    assert state is not None
    assert state.status == "running"


def test_start_treats_missing_failed_preview_target_as_clean(tmp_path):
    controller = load_controller()
    root = tmp_path / "control" / "trees" / "imported" / "feature-demo"
    root.mkdir(parents=True)
    runner = FakeRunner(
        controller,
        projects={
            "projects": [
                {"name": "feature/demo", "root": str(root), "running": False}
            ]
        },
        endpoints={"frontend": {"port": 9000}, "backend": {"port": 8000}},
        root_to_branch={str(root): "feature/demo"},
        blast_returncode=1,
        blast_stdout="No matching targets found for: feature/demo\n",
    )
    config = make_config(controller, tmp_path)
    instance = controller.PreviewController(config, runner)
    instance.save_state(
        controller.PreviewState(
            pr_number=789,
            label="deploy-app",
            project="feature/demo",
            root=str(root),
            head_ref="feature/demo",
            head_sha="oldsha",
            status="start_failed",
            label_added_at="2026-06-14T00:00:00Z",
            started_at="2026-06-14T00:00:00Z",
            expires_at="2026-06-14T00:45:00Z",
            updated_at="2026-06-14T00:00:00Z",
            endpoints={},
        )
    )
    pr = controller.pr_from_event(
        pr_payload(
            action="labeled",
            labels=["deploy-app"],
            event_label="deploy-app",
        )
    )

    exit_code = instance.start(pr, reason="label added")

    assert exit_code == 0
    assert command_argvs(runner, "envctl", "blast-worktree") == [
        ["envctl", "blast-worktree", "--project", "feature/demo", "--yes"]
    ]
    assert [
        "docker",
        "ps",
        "-aq",
        "--filter",
        "name=feature-demo",
    ] in command_argvs(runner, "docker", "ps")
    assert command_argvs(runner, "envctl", "start")


def test_labeled_event_fails_closed_when_imported_project_is_unresolved(tmp_path):
    controller = load_controller()
    runner = FakeRunner(controller, projects={"projects": []})
    config = make_config(controller, tmp_path)
    instance = controller.PreviewController(config, runner)

    exit_code = instance.run_pull_request_event(
        pr_payload(
            action="labeled",
            labels=["deploy-app"],
            event_label="deploy-app",
        )
    )

    assert exit_code == 1
    assert command_argvs(runner, "envctl", "import")
    assert command_argvs(runner, "envctl", "start") == []
    state = instance.load_state(789)
    assert state is not None
    assert state.status == "project_unresolved"
    assert state.project is None
    assert "project resolution failed" in runner.comments[-1]
    assert "Envctl preview is running" not in runner.comments[-1]


def test_labeled_event_records_start_failure_after_import(tmp_path):
    controller = load_controller()
    root = tmp_path / "control" / "trees" / "imported" / "feature-demo"
    root.mkdir(parents=True)
    runner = FakeRunner(
        controller,
        projects={
            "projects": [
                {"name": "feature/demo", "root": str(root), "running": False}
            ]
        },
        root_to_branch={str(root): "feature/demo"},
        start_returncode=7,
        start_stdout="Starting 1 project(s)...",
        start_stderr="backend failed to bind",
    )
    config = make_config(controller, tmp_path)
    instance = controller.PreviewController(config, runner)

    exit_code = instance.run_pull_request_event(
        pr_payload(
            action="labeled",
            labels=["deploy-app"],
            event_label="deploy-app",
        )
    )

    assert exit_code == 7
    assert command_argvs(runner, "envctl", "import")
    assert command_argvs(runner, "envctl", "start")
    state = instance.load_state(789)
    assert state is not None
    assert state.status == "start_failed"
    assert state.project == "feature/demo"
    assert state.external_dependencies == {}
    assert "envctl start failed" in runner.comments[-1]
    assert "- Failed-start cleanup exit code: `0`" in runner.comments[-1]
    assert "stderr:" in runner.comments[-1]
    assert "backend failed to bind" in runner.comments[-1]
    assert "stdout:" in runner.comments[-1]
    assert "Starting 1 project(s)..." in runner.comments[-1]
    assert [
        "docker",
        "rm",
        "-f",
        "container-a",
        "container-b",
    ] in command_argvs(runner, "docker", "rm")
    assert [
        "docker",
        "volume",
        "rm",
        "-f",
        "volume-a",
    ] in command_argvs(runner, "docker", "volume")
    assert [
        "docker",
        "network",
        "rm",
        "network-a",
    ] in command_argvs(runner, "docker", "network")


def test_start_removes_backend_venv_created_with_different_python(tmp_path):
    controller = load_controller()
    root = tmp_path / "control" / "trees" / "imported" / "feature-demo"
    backend = root / "backend"
    state_dir = backend / ".envctl-state"
    venv = backend / "venv"
    old_python = tmp_path / "old-python"
    new_python = tmp_path / "new-python"
    old_python.write_text("", encoding="utf-8")
    new_python.write_text("", encoding="utf-8")
    (venv / "bin").mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text(
        f"executable = {old_python}\n",
        encoding="utf-8",
    )
    state_dir.mkdir(parents=True)
    (state_dir / "envctl-backend-bootstrap.json").write_text("{}", encoding="utf-8")
    (state_dir / "envctl-backend-runtime-prep.json").write_text(
        "{}",
        encoding="utf-8",
    )
    runner = FakeRunner(controller)
    instance = controller.PreviewController(make_config(controller, tmp_path), runner)

    instance.reset_incompatible_backend_venv(
        {"root": str(root)},
        {"PYTHON_BIN": str(new_python)},
    )

    assert not venv.exists()
    assert not (state_dir / "envctl-backend-bootstrap.json").exists()
    assert not (state_dir / "envctl-backend-runtime-prep.json").exists()


def test_start_keeps_backend_venv_created_with_same_python(tmp_path):
    controller = load_controller()
    root = tmp_path / "control" / "trees" / "imported" / "feature-demo"
    backend = root / "backend"
    venv = backend / "venv"
    python_bin = tmp_path / "python"
    python_bin.write_text("", encoding="utf-8")
    (venv / "bin").mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text(
        f"executable = {python_bin}\n",
        encoding="utf-8",
    )
    runner = FakeRunner(controller)
    instance = controller.PreviewController(make_config(controller, tmp_path), runner)

    instance.reset_incompatible_backend_venv(
        {"root": str(root)},
        {"PYTHON_BIN": str(python_bin)},
    )

    assert venv.exists()


def test_unlabeled_event_stops_tracked_preview(tmp_path):
    controller = load_controller()
    config = make_config(controller, tmp_path)
    runner = FakeRunner(controller)
    instance = controller.PreviewController(config, runner)
    instance.save_state(
        controller.PreviewState(
            pr_number=789,
            label="deploy-app",
            project="feature/demo",
            root=str(tmp_path / "control" / "trees" / "imported" / "feature-demo"),
            head_ref="feature/demo",
            head_sha="abc123456789",
            status="running",
            label_added_at="2026-06-14T00:00:00Z",
            started_at="2026-06-14T00:00:00Z",
            expires_at="2026-06-14T00:45:00Z",
            updated_at="2026-06-14T00:00:00Z",
            endpoints={},
            deployment_id="12345",
        )
    )

    exit_code = instance.run_pull_request_event(
        pr_payload(
            action="unlabeled",
            labels=[],
            event_label="deploy-app",
        )
    )

    assert exit_code == 0
    assert command_argvs(runner, "envctl", "stop") == [
        ["envctl", "stop", "--trees", "--project", "feature/demo", "--entire-system"]
    ]
    assert command_argvs(runner, "docker", "rm") == [
        ["docker", "rm", "-f", "container-a", "container-b"]
    ]
    assert command_argvs(runner, "docker", "volume") == []
    assert command_argvs(runner, "docker", "network") == []
    assert command_argvs(runner, "envctl", "blast-all") == [
        [
            "envctl",
            "blast-all",
            "--force",
            "--blast-keep-worktree-volumes",
            "--blast-keep-main-volumes",
        ]
    ]
    assert instance.load_state(789).status == "stopped"
    assert runner.deployment_statuses[-1] == {
        "state": "inactive",
        "description": "Envctl preview stopped",
        "auto_inactive": False,
    }
    assert "label removed" in runner.comments[-1]


def test_unlabeled_event_releases_external_dependency_lease(tmp_path):
    controller = load_controller()
    base_config = make_config(controller, tmp_path)
    config = controller.ControllerConfig(
        **{
            **base_config.__dict__,
            "external_dependency_pools": supabase_external_pool(controller),
        }
    )
    runner = FakeRunner(controller)
    instance = controller.PreviewController(config, runner)
    instance.save_external_dependency_leases({"supabase": {"supabase-a": 789}})
    instance.save_state(
        controller.PreviewState(
            pr_number=789,
            label="deploy-app",
            project="feature/demo",
            root=str(tmp_path / "control" / "trees" / "imported" / "feature-demo"),
            head_ref="feature/demo",
            head_sha="abc123456789",
            status="running",
            label_added_at="2026-06-14T00:00:00Z",
            started_at="2026-06-14T00:00:00Z",
            expires_at="2026-06-14T00:45:00Z",
            updated_at="2026-06-14T00:00:00Z",
            endpoints={},
            external_dependencies={"supabase": "supabase-a"},
        )
    )

    exit_code = instance.run_pull_request_event(
        pr_payload(
            action="unlabeled",
            labels=[],
            event_label="deploy-app",
        )
    )

    assert exit_code == 0
    assert instance.load_external_dependency_leases() == {}
    state = instance.load_state(789)
    assert state is not None
    assert state.status == "stopped"
    assert state.external_dependencies == {}


def test_stop_releases_existing_lease_even_when_pool_secret_was_removed(tmp_path):
    controller = load_controller()
    config = make_config(controller, tmp_path)
    runner = FakeRunner(controller)
    instance = controller.PreviewController(config, runner)
    instance.save_external_dependency_leases({"supabase": {"supabase-a": 789}})
    instance.save_state(
        controller.PreviewState(
            pr_number=789,
            label="deploy-app",
            project="feature/demo",
            root=str(tmp_path / "control" / "trees" / "imported" / "feature-demo"),
            head_ref="feature/demo",
            head_sha="abc123456789",
            status="running",
            label_added_at="2026-06-14T00:00:00Z",
            started_at="2026-06-14T00:00:00Z",
            expires_at="2026-06-14T00:45:00Z",
            updated_at="2026-06-14T00:00:00Z",
            endpoints={},
            external_dependencies={"supabase": "supabase-a"},
        )
    )

    exit_code = instance.run_pull_request_event(
        pr_payload(
            action="unlabeled",
            labels=[],
            event_label="deploy-app",
        )
    )

    assert exit_code == 0
    assert instance.load_external_dependency_leases() == {}
    state = instance.load_state(789)
    assert state is not None
    assert state.external_dependencies == {}


def test_restart_cleanup_preserves_external_dependency_lease(tmp_path):
    controller = load_controller()
    root = tmp_path / "control" / "trees" / "imported" / "feature-demo"
    root.mkdir(parents=True)
    runner = FakeRunner(
        controller,
        projects={
            "projects": [
                {"name": "feature/demo", "root": str(root), "running": True}
            ]
        },
        endpoints={"frontend": {"port": 9000}, "backend": {"port": 8000}},
        root_to_branch={str(root): "feature/demo"},
    )
    base_config = make_config(controller, tmp_path)
    config = controller.ControllerConfig(
        **{
            **base_config.__dict__,
            "external_dependency_pools": supabase_external_pool(controller),
        }
    )
    instance = controller.PreviewController(config, runner)
    instance.save_external_dependency_leases({"supabase": {"supabase-a": 789}})
    instance.save_state(
        controller.PreviewState(
            pr_number=789,
            label="deploy-app",
            project="feature/demo",
            root=str(root),
            head_ref="feature/demo",
            head_sha="oldsha",
            status="running",
            label_added_at="2026-06-14T00:00:00Z",
            started_at="2026-06-14T00:00:00Z",
            expires_at="2026-06-14T00:45:00Z",
            updated_at="2026-06-14T00:00:00Z",
            endpoints={},
            external_dependencies={"supabase": "supabase-a"},
        )
    )
    pr = controller.pr_from_event(
        pr_payload(
            action="synchronize",
            labels=["deploy-app"],
            event_label="deploy-app",
        )
    )

    exit_code = instance.start(pr, reason="PR synchronize")

    assert exit_code == 0
    assert instance.load_external_dependency_leases() == {
        "supabase": {"supabase-a": 789}
    }
    state = instance.load_state(789)
    assert state is not None
    assert state.external_dependencies == {"supabase": "supabase-a"}


def test_merged_pr_deletes_tracked_worktree_even_after_label_removed(tmp_path):
    controller = load_controller()
    config = make_config(controller, tmp_path)
    runner = FakeRunner(controller)
    instance = controller.PreviewController(config, runner)
    instance.save_state(
        controller.PreviewState(
            pr_number=789,
            label="deploy-app",
            project="feature/demo",
            root=str(tmp_path / "control" / "trees" / "imported" / "feature-demo"),
            head_ref="feature/demo",
            head_sha="abc123456789",
            status="stopped",
            label_added_at="2026-06-14T00:00:00Z",
            started_at="2026-06-14T00:00:00Z",
            expires_at="2026-06-14T00:45:00Z",
            updated_at="2026-06-14T00:20:00Z",
            endpoints={},
        )
    )

    exit_code = instance.run_pull_request_event(
        pr_payload(action="closed", labels=[], merged=True)
    )

    assert exit_code == 0
    assert command_argvs(runner, "envctl", "stop") == [
        ["envctl", "stop", "--trees", "--project", "feature/demo", "--entire-system"]
    ]
    assert command_argvs(runner, "envctl", "delete-worktree") == [
        ["envctl", "delete-worktree", "--project", "feature/demo", "--yes"]
    ]
    assert command_argvs(runner, "git", "-C") == [
        [
            "git",
            "-C",
            str(config.control_repo),
            "branch",
            "-D",
            "feature/demo",
        ]
    ]
    assert ["docker", "rm", "-f", "container-a", "container-b"] in command_argvs(
        runner,
        "docker",
        "rm",
    )
    assert ["docker", "volume", "rm", "-f", "volume-a"] in command_argvs(
        runner,
        "docker",
        "volume",
    )
    assert ["docker", "network", "rm", "network-a"] in command_argvs(
        runner,
        "docker",
        "network",
    )
    assert runner.removed_labels == ["deploy-app"]
    assert instance.load_state(789) is None
    assert "worktree deleted" in runner.comments[-1]


def test_closed_unmerged_pr_deletes_tracked_worktree(tmp_path):
    controller = load_controller()
    config = make_config(controller, tmp_path)
    runner = FakeRunner(controller)
    instance = controller.PreviewController(config, runner)
    instance.save_state(
        controller.PreviewState(
            pr_number=789,
            label="deploy-app",
            project="feature/demo",
            root=str(tmp_path / "control" / "trees" / "imported" / "feature-demo"),
            head_ref="feature/demo",
            head_sha="abc123456789",
            status="running",
            label_added_at="2026-06-14T00:00:00Z",
            started_at="2026-06-14T00:00:00Z",
            expires_at="2026-06-14T00:45:00Z",
            updated_at="2026-06-14T00:20:00Z",
            endpoints={},
        )
    )

    exit_code = instance.run_pull_request_event(
        pr_payload(action="closed", labels=[], merged=False)
    )

    assert exit_code == 0
    assert command_argvs(runner, "envctl", "stop") == [
        ["envctl", "stop", "--trees", "--project", "feature/demo", "--entire-system"]
    ]
    assert command_argvs(runner, "envctl", "delete-worktree") == [
        ["envctl", "delete-worktree", "--project", "feature/demo", "--yes"]
    ]
    assert command_argvs(runner, "git", "-C") == [
        [
            "git",
            "-C",
            str(config.control_repo),
            "branch",
            "-D",
            "feature/demo",
        ]
    ]
    assert ["docker", "rm", "-f", "container-a", "container-b"] in command_argvs(
        runner,
        "docker",
        "rm",
    )
    assert ["docker", "volume", "rm", "-f", "volume-a"] in command_argvs(
        runner,
        "docker",
        "volume",
    )
    assert ["docker", "network", "rm", "network-a"] in command_argvs(
        runner,
        "docker",
        "network",
    )
    assert runner.removed_labels == ["deploy-app"]
    assert instance.load_state(789) is None
    assert "PR closed without merge" in runner.comments[-1]
    assert "worktree deleted" in runner.comments[-1]


def test_delete_without_worktree_cleans_branch_docker_artifacts(tmp_path):
    controller = load_controller()
    config = make_config(controller, tmp_path)
    runner = FakeRunner(controller, projects={"projects": []})
    instance = controller.PreviewController(config, runner)
    payload = pr_payload(
        action="closed",
        labels=["deploy-app"],
        event_label="deploy-app",
        merged=False,
    )
    payload["pull_request"]["head"] = {
        "ref": "codex/address-pr283-doc-hygiene",
        "sha": "abc123456789",
        "repo": {
            "name": "pele-monorepo",
            "owner": {"login": "OrgPele"},
        },
    }

    exit_code = instance.run_pull_request_event(payload)

    assert exit_code == 0
    assert command_argvs(runner, "envctl", "delete-worktree") == []
    assert command_argvs(runner, "git", "-C") == [
        [
            "git",
            "-C",
            str(config.control_repo),
            "branch",
            "-D",
            "codex/address-pr283-doc-hygiene",
        ]
    ]
    assert ["docker", "rm", "-f", "orphan-container"] in command_argvs(
        runner,
        "docker",
        "rm",
    )
    assert ["docker", "volume", "rm", "-f", "orphan-volume"] in command_argvs(
        runner,
        "docker",
        "volume",
    )
    assert ["docker", "network", "rm", "orphan-network"] in command_argvs(
        runner,
        "docker",
        "network",
    )
    assert runner.removed_labels == ["deploy-app"]
    assert "Docker artifacts matching the PR branch slug were cleaned" in (
        runner.comments[-1]
    )


def test_sweep_expires_label_stops_preview_and_removes_label(tmp_path):
    controller = load_controller()
    root = tmp_path / "control" / "trees" / "imported" / "feature-demo"
    root.mkdir(parents=True)
    config = make_config(controller, tmp_path, ttl_minutes=45)
    runner = FakeRunner(
        controller,
        active_prs=[pr_list_payload(789, "Preview me")],
        timeline="labeled\t2000-01-01T00:00:00Z\tdeploy-app\n",
        projects={
            "projects": [
                {"name": "feature/demo", "root": str(root), "running": True}
            ]
        },
        root_to_branch={str(root): "feature/demo"},
    )
    instance = controller.PreviewController(config, runner)

    exit_code = instance.sweep()

    assert exit_code == 0
    assert command_argvs(runner, "envctl", "stop") == [
        ["envctl", "stop", "--trees", "--project", "feature/demo", "--entire-system"]
    ]
    assert command_argvs(runner, "envctl", "delete-worktree") == []
    assert runner.removed_labels == ["deploy-app"]
    assert "TTL expired" in runner.comments[0]


def test_sweep_redeploys_running_preview_when_head_sha_changes(tmp_path):
    controller = load_controller()
    root = tmp_path / "control" / "trees" / "imported" / "feature-demo"
    root.mkdir(parents=True)
    config = make_config(controller, tmp_path, ttl_minutes=45)
    runner = FakeRunner(
        controller,
        active_prs=[pr_list_payload(789, "Preview me")],
        projects={
            "projects": [
                {"name": "feature/demo", "root": str(root), "running": True}
            ]
        },
        endpoints={"frontend": {"port": 9000}, "backend": {"port": 8000}},
        root_to_branch={str(root): "feature/demo"},
    )
    instance = controller.PreviewController(config, runner)
    instance.save_state(
        controller.PreviewState(
            pr_number=789,
            label="deploy-app",
            project="feature/demo",
            root=str(root),
            head_ref="feature/demo",
            head_sha="oldsha",
            status="running",
            label_added_at="2999-01-01T00:00:00Z",
            started_at="2999-01-01T00:00:00Z",
            expires_at="2999-01-01T00:45:00Z",
            updated_at="2999-01-01T00:00:00Z",
            endpoints={},
        )
    )

    exit_code = instance.sweep()

    assert exit_code == 0
    sequence = [
        call["argv"][:2]
        for call in runner.calls
        if call["argv"][:2]
        in (["envctl", "stop"], ["envctl", "import"], ["envctl", "start"])
    ]
    assert sequence == [
        ["envctl", "stop"],
        ["envctl", "import"],
        ["envctl", "stop"],
        ["envctl", "start"],
    ]
    assert instance.load_state(789).head_sha == "abc123456789"
    assert "scheduled reconciliation for new commit" in runner.comments[-1]


def test_sweep_with_no_active_prs_blasts_processes_without_removing_storage(
    tmp_path,
):
    controller = load_controller()
    config = make_config(controller, tmp_path, ttl_minutes=45)
    runner = FakeRunner(controller, active_prs=[])
    instance = controller.PreviewController(config, runner)
    instance.save_external_dependency_leases({"supabase": {"supabase-a": 789}})
    instance.save_state(
        controller.PreviewState(
            pr_number=789,
            label="deploy-app",
            project="feature/demo",
            root=str(tmp_path / "control" / "trees" / "imported" / "feature-demo"),
            head_ref="feature/demo",
            head_sha="abc123456789",
            status="running",
            label_added_at="2000-01-01T00:00:00Z",
            started_at="2000-01-01T00:00:00Z",
            expires_at="2000-01-01T00:45:00Z",
            updated_at="2000-01-01T00:00:00Z",
            endpoints={},
            external_dependencies={"supabase": "supabase-a"},
            deployment_id="12345",
        )
    )

    exit_code = instance.sweep()

    assert exit_code == 0
    assert command_argvs(runner, "envctl", "blast-all") == [
        [
            "envctl",
            "blast-all",
            "--force",
            "--blast-keep-worktree-volumes",
            "--blast-keep-main-volumes",
        ]
    ]
    state = instance.load_state(789)
    assert state is not None
    assert state.status == "stopped"
    assert state.external_dependencies == {}
    assert instance.load_external_dependency_leases() == {}
    assert runner.deployment_statuses[-1] == {
        "state": "inactive",
        "description": "Envctl preview stopped",
        "auto_inactive": False,
    }


def test_sweep_uses_saved_label_time_when_timeline_is_unavailable(tmp_path):
    controller = load_controller()
    config = make_config(controller, tmp_path, ttl_minutes=45)
    runner = FakeRunner(
        controller,
        active_prs=[pr_list_payload(789, "Preview me")],
        timeline="",
    )
    instance = controller.PreviewController(config, runner)
    instance.save_state(
        controller.PreviewState(
            pr_number=789,
            label="deploy-app",
            project="feature/demo",
            root=str(tmp_path / "control" / "trees" / "imported" / "feature-demo"),
            head_ref="feature/demo",
            head_sha="abc123456789",
            status="running",
            label_added_at="2000-01-01T00:00:00Z",
            started_at="2000-01-01T00:00:00Z",
            expires_at="2000-01-01T00:45:00Z",
            updated_at="2000-01-01T00:00:00Z",
            endpoints={},
        )
    )

    exit_code = instance.sweep()

    assert exit_code == 0
    assert command_argvs(runner, "envctl", "stop") == [
        ["envctl", "stop", "--trees", "--project", "feature/demo", "--entire-system"]
    ]
    assert runner.removed_labels == ["deploy-app"]
    assert "Label added: 2000-01-01T00:00:00Z" in runner.comments[0]


def test_sweep_prefers_newer_saved_manual_start_time(tmp_path):
    controller = load_controller()
    config = make_config(controller, tmp_path, ttl_minutes=45)
    runner = FakeRunner(
        controller,
        active_prs=[pr_list_payload(789, "Preview me")],
        timeline="labeled\t2000-01-01T00:00:00Z\tdeploy-app\n",
    )
    instance = controller.PreviewController(config, runner)
    instance.save_state(
        controller.PreviewState(
            pr_number=789,
            label="deploy-app",
            project="feature/demo",
            root=str(tmp_path / "control" / "trees" / "imported" / "feature-demo"),
            head_ref="feature/demo",
            head_sha="abc123456789",
            status="running",
            label_added_at="2999-01-01T00:00:00Z",
            started_at="2999-01-01T00:00:00Z",
            expires_at="2999-01-01T00:45:00Z",
            updated_at="2999-01-01T00:00:00Z",
            endpoints={},
        )
    )

    exit_code = instance.sweep()

    assert exit_code == 0
    assert command_argvs(runner, "envctl", "stop") == []
    assert runner.removed_labels == []
    assert runner.comments == []


def test_command_runner_returns_timeout_result_when_check_is_false():
    controller = load_controller()
    runner = controller.CommandRunner()

    result = runner.run(
        [sys.executable, "-c", "import time; time.sleep(1)"],
        check=False,
        timeout=0.01,
    )

    assert result.returncode == 124
    assert "timed out" in result.stderr


def test_command_runner_raises_timeout_result_when_check_is_true():
    controller = load_controller()
    runner = controller.CommandRunner()

    try:
        runner.run(
            [sys.executable, "-c", "import time; time.sleep(1)"],
            timeout=0.01,
        )
    except controller.CommandError as exc:
        assert exc.returncode == 124
        assert "timed out" in exc.stderr
    else:
        raise AssertionError("expected CommandError")


def test_dry_run_skips_mutations_but_not_reads():
    controller = load_controller()

    assert controller.dry_run_skips_command(["envctl", "import", "feature/demo"])
    assert controller.dry_run_skips_command(
        ["/tmp/envctl-venv/bin/envctl", "import", "feature/demo"]
    )
    assert controller.dry_run_skips_command(["git", "fetch", "origin"])
    assert controller.dry_run_skips_command(["gh", "issue", "comment", "1"])
    assert controller.dry_run_skips_command(["gh", "issue", "edit", "1"])
    assert controller.dry_run_skips_command(["gh", "repo", "clone", "repo", "path"])
    assert not controller.dry_run_skips_command(["gh", "pr", "view", "1"])
    assert not controller.dry_run_skips_command(["gh", "pr", "list"])
    assert not controller.dry_run_skips_command(["gh", "api", "path"])
    assert not controller.dry_run_skips_command(["docker", "ps"])


def test_generated_envctl_config_forces_isolated_tree_dependencies():
    controller = load_controller()

    rendered = controller.default_envctl_config(
        public_host="preview.getpele.test",
        ui_visual_host="visual.getpele.test",
    )

    assert "ENVCTL_DEFAULT_TREE_DEPENDENCY_SCOPE=isolated" in rendered
    assert "ENVCTL_PUBLIC_HOST=preview.getpele.test" in rendered
    assert "ENVCTL_UI_VISUAL_HOST=visual.getpele.test" in rendered
    assert "ENVCTL_SERVICE_LISTENER_TIMEOUT=300" in rendered
    assert "ENVCTL_SERVICE_STARTUP_GRACE_SECONDS=60" in rendered
    assert "ENVCTL_SERVICE_STARTUP_PROGRESS_TIMEOUT=600" in rendered
    assert "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE=false" in rendered
    assert "ENVCTL_UI_BACKEND=non_interactive" in rendered
    assert (
        "ENVCTL_BACKEND_START_CMD=python -m uvicorn app.main:app "
        "--host 127.0.0.1 --port '{port}'" in rendered
    )
    assert (
        "ENVCTL_FRONTEND_START_CMD=npm run dev -- --port '{port}' "
        "--host 127.0.0.1" in rendered
    )
    assert "TREES_REDIS_ENABLE=true" in rendered
    assert "TREES_SUPABASE_ENABLE=true" in rendered
    assert "TREES_N8N_ENABLE=true" in rendered


def test_generated_envctl_config_can_persist_public_route_launch_env_sections():
    controller = load_controller()

    rendered = controller.default_envctl_config(
        public_host="preview.getpele.test",
        public_urls={
            "frontend": "https://pele-monorepo-pr-789.srv.example.test",
            "backend": "https://pele-monorepo-pr-789-api.srv.example.test",
            "supabase": "https://pele-monorepo-pr-789-supabase.srv.example.test",
        },
    )

    assert "# >>> envctl backend launch env >>>" in rendered
    backend_start = rendered.split("ENVCTL_BACKEND_START_CMD=", 1)[1].split(
        "\n",
        1,
    )[0]
    frontend_start = rendered.split("ENVCTL_FRONTEND_START_CMD=", 1)[1].split(
        "\n",
        1,
    )[0]
    assert backend_start.startswith(
        'sh -c \'export PATH="$PWD/venv/bin:$PATH" '
        "FRONTEND_BASE_URL=https://pele-monorepo-pr-789.srv.example.test "
        "BACKEND_PUBLIC_URL=https://pele-monorepo-pr-789-api.srv.example.test "
    )
    assert "ALLOW_LEGACY_SUPABASE_HS256=true" in backend_start
    assert 'PAYMENT_PROVIDER="${ENVCTL_SOURCE_PAYMENT_PROVIDER:-}"' in backend_start
    assert 'CREEM_API_KEY="${ENVCTL_SOURCE_CREEM_API_KEY:-}"' in backend_start
    assert (
        'CREEM_PROFESSIONAL_MONTHLY_PRODUCT_ID="'
        '${ENVCTL_SOURCE_CREEM_PROFESSIONAL_MONTHLY_PRODUCT_ID:-}"'
        in backend_start
    )
    assert 'PADDLE_API_KEY="${ENVCTL_SOURCE_PADDLE_API_KEY:-}"' in backend_start
    assert (
        'PADDLE_GROWTH_MONTHLY_PRICE_ID="'
        '${ENVCTL_SOURCE_PADDLE_GROWTH_MONTHLY_PRICE_ID:-}"' in backend_start
    )
    assert (
        "exec python -m uvicorn app.main:app --host 127.0.0.1 --port "
        "'\"'\"'{port}'\"'\"''" in backend_start
    )
    assert frontend_start.startswith(
        "sh -c 'export VITE_API_URL="
        "https://pele-monorepo-pr-789-api.srv.example.test/api/v1 "
    )
    assert (
        "VITE_SUPABASE_URL=https://pele-monorepo-pr-789-supabase.srv.example.test"
        in frontend_start
    )
    assert (
        'VITE_PADDLE_CLIENT_TOKEN="${ENVCTL_SOURCE_VITE_PADDLE_CLIENT_TOKEN:-}"'
        in frontend_start
    )
    assert (
        'VITE_PADDLE_ENVIRONMENT="${ENVCTL_SOURCE_VITE_PADDLE_ENVIRONMENT:-}"'
        in frontend_start
    )
    assert (
        "exec npm run dev -- --port '\"'\"'{port}'\"'\"' --host 127.0.0.1"
        in frontend_start
    )
    assert "DATABASE_URL=${ENVCTL_SOURCE_DATABASE_URL}" in rendered
    assert "REDIS_URL=${ENVCTL_SOURCE_REDIS_URL}" in rendered
    assert "N8N_URL=${ENVCTL_SOURCE_N8N_URL}" in rendered
    assert "SUPABASE_URL=${ENVCTL_SOURCE_SUPABASE_URL}" in rendered
    assert "PYTHONFAULTHANDLER=1" in rendered
    assert "SUPABASE_JWKS_URL=${ENVCTL_SOURCE_SUPABASE_JWKS_URL}" in rendered
    assert "SUPABASE_JWT_SECRET=${ENVCTL_SOURCE_SUPABASE_JWT_SECRET}" in rendered
    assert "ALLOW_LEGACY_SUPABASE_HS256=true" in rendered
    assert (
        "ALLOW_LEGACY_SUPABASE_HS256="
        "${ENVCTL_SOURCE_ALLOW_LEGACY_SUPABASE_HS256}" not in rendered
    )
    assert "SUPABASE_ANON_KEY=${ENVCTL_SOURCE_SUPABASE_ANON_KEY}" in rendered
    assert (
        "SUPABASE_SERVICE_ROLE_KEY=${ENVCTL_SOURCE_SUPABASE_SERVICE_ROLE_KEY}"
        in rendered
    )
    assert (
        "GOOGLE_APPLICATION_CREDENTIALS="
        "${ENVCTL_SOURCE_GOOGLE_APPLICATION_CREDENTIALS}" in rendered
    )
    assert (
        "GCP_SERVICE_ACCOUNT_KEY=${ENVCTL_SOURCE_GCP_SERVICE_ACCOUNT_KEY}"
        in rendered
    )
    assert (
        "GOOGLE_OAUTH_CLIENT_SECRET=${ENVCTL_SOURCE_GOOGLE_OAUTH_CLIENT_SECRET}"
        in rendered
    )
    assert (
        "TWILIO_MASTER_AUTH_TOKEN=${ENVCTL_SOURCE_TWILIO_MASTER_AUTH_TOKEN}"
        in rendered
    )
    assert "CREEM_BILLING_ENABLED=${ENVCTL_SOURCE_CREEM_BILLING_ENABLED}" in (
        rendered
    )
    assert "CREEM_ENVIRONMENT=${ENVCTL_SOURCE_CREEM_ENVIRONMENT}" in rendered
    assert "CREEM_API_KEY=${ENVCTL_SOURCE_CREEM_API_KEY}" in rendered
    assert "CREEM_WEBHOOK_SECRET=${ENVCTL_SOURCE_CREEM_WEBHOOK_SECRET}" in rendered
    assert (
        "CREEM_STARTER_MONTHLY_PRODUCT_ID="
        "${ENVCTL_SOURCE_CREEM_STARTER_MONTHLY_PRODUCT_ID}" in rendered
    )
    assert (
        "CREEM_PROFESSIONAL_ANNUAL_PRODUCT_ID="
        "${ENVCTL_SOURCE_CREEM_PROFESSIONAL_ANNUAL_PRODUCT_ID}" in rendered
    )
    assert (
        "CREEM_PROFESSIONAL_TRIAL_DAYS="
        "${ENVCTL_SOURCE_CREEM_PROFESSIONAL_TRIAL_DAYS}" in rendered
    )
    assert "PADDLE_BILLING_ENABLED=${ENVCTL_SOURCE_PADDLE_BILLING_ENABLED}" in (
        rendered
    )
    assert "PADDLE_ENVIRONMENT=${ENVCTL_SOURCE_PADDLE_ENVIRONMENT}" in rendered
    assert "PADDLE_API_KEY=${ENVCTL_SOURCE_PADDLE_API_KEY}" in rendered
    assert (
        "PADDLE_CLIENT_TOKEN=${ENVCTL_SOURCE_PADDLE_CLIENT_TOKEN}" in rendered
    )
    assert (
        "PADDLE_CHECKOUT_SUCCESS_URL="
        "${ENVCTL_SOURCE_PADDLE_CHECKOUT_SUCCESS_URL}" in rendered
    )
    assert (
        "PADDLE_STARTER_MONTHLY_PRICE_ID="
        "${ENVCTL_SOURCE_PADDLE_STARTER_MONTHLY_PRICE_ID}" in rendered
    )
    assert (
        "PADDLE_GROWTH_ANNUAL_PRICE_ID="
        "${ENVCTL_SOURCE_PADDLE_GROWTH_ANNUAL_PRICE_ID}" in rendered
    )
    assert (
        "PADDLE_PROFESSIONAL_TRIAL_DAYS="
        "${ENVCTL_SOURCE_PADDLE_PROFESSIONAL_TRIAL_DAYS}" in rendered
    )
    assert (
        "SQLALCHEMY_DATABASE_URL=${ENVCTL_SOURCE_SQLALCHEMY_DATABASE_URL}"
        in rendered
    )
    assert "ASYNC_DATABASE_URL=${ENVCTL_SOURCE_ASYNC_DATABASE_URL}" in rendered
    assert (
        "FRONTEND_BASE_URL="
        "https://pele-monorepo-pr-789.srv.example.test" in rendered
    )
    assert (
        "BACKEND_PUBLIC_URL="
        "https://pele-monorepo-pr-789-api.srv.example.test" in rendered
    )
    assert (
        "CORS_ORIGINS_RAW="
        "https://pele-monorepo-pr-789.srv.example.test" in rendered
    )
    assert "RUN_DB_MIGRATIONS_ON_STARTUP=true" in rendered
    assert "# <<< envctl backend launch env <<<" in rendered
    assert "# >>> envctl frontend launch env >>>" in rendered
    assert (
        "VITE_SUPABASE_URL=https://pele-monorepo-pr-789-supabase.srv.example.test"
        in rendered
    )
    assert "VITE_SUPABASE_ANON_KEY=${ENVCTL_SOURCE_SUPABASE_ANON_KEY}" in rendered
    assert (
        "VITE_PADDLE_CLIENT_TOKEN=${ENVCTL_SOURCE_VITE_PADDLE_CLIENT_TOKEN}"
        in rendered
    )
    frontend_env = rendered.split("# >>> envctl frontend launch env >>>", 1)[1]
    assert "PADDLE_API_KEY=${ENVCTL_SOURCE_PADDLE_API_KEY}" not in frontend_env
    assert (
        "VITE_API_URL="
        "https://pele-monorepo-pr-789-api.srv.example.test/api/v1" in rendered
    )
    assert (
        "VITE_BACKEND_URL="
        "https://pele-monorepo-pr-789-api.srv.example.test" in rendered
    )
    assert "# <<< envctl frontend launch env <<<" in rendered


def test_generated_public_preview_provider_env_stays_in_launch_sections(monkeypatch):
    controller = load_controller()
    monkeypatch.setenv("ENVCTL_SOURCE_PAYMENT_PROVIDER", "creem")
    monkeypatch.setenv("ENVCTL_SOURCE_CREEM_BILLING_ENABLED", "true")
    monkeypatch.setenv("ENVCTL_SOURCE_CREEM_ENVIRONMENT", "test")
    monkeypatch.setenv("ENVCTL_SOURCE_CREEM_API_KEY", "test-api-key")
    monkeypatch.setenv("ENVCTL_SOURCE_CREEM_WEBHOOK_SECRET", "test-webhook-secret")
    monkeypatch.setenv(
        "ENVCTL_SOURCE_CREEM_PROFESSIONAL_MONTHLY_PRODUCT_ID",
        "prod_professional_monthly",
    )
    monkeypatch.setenv("ENVCTL_SOURCE_CREEM_PROFESSIONAL_TRIAL_DAYS", "0")
    monkeypatch.setenv("ENVCTL_SOURCE_PADDLE_BILLING_ENABLED", "true")
    monkeypatch.setenv("ENVCTL_SOURCE_PADDLE_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("ENVCTL_SOURCE_PADDLE_API_KEY", "test-api-key")
    monkeypatch.setenv(
        "ENVCTL_SOURCE_PADDLE_GROWTH_MONTHLY_PRICE_ID",
        "pri_growth_monthly",
    )
    monkeypatch.setenv("ENVCTL_BACKEND_ENV__PADDLE_GROWTH_TRIAL_DAYS", "0")
    monkeypatch.setenv(
        "ENVCTL_FRONTEND_ENV__VITE_PADDLE_CLIENT_TOKEN",
        "test-client-token",
    )
    monkeypatch.setenv("ENVCTL_SOURCE_VITE_PADDLE_ENVIRONMENT", "sandbox")

    rendered = controller.default_envctl_config(
        public_host="preview.getpele.test",
        public_urls={
            "frontend": "https://pele-monorepo-pr-789.srv.example.test",
            "backend": "https://pele-monorepo-pr-789-api.srv.example.test",
            "supabase": "https://pele-monorepo-pr-789-supabase.srv.example.test",
        },
    )

    backend_start = rendered.split("ENVCTL_BACKEND_START_CMD=", 1)[1].split(
        "\n",
        1,
    )[0]
    frontend_start = rendered.split("ENVCTL_FRONTEND_START_CMD=", 1)[1].split(
        "\n",
        1,
    )[0]

    assert 'PAYMENT_PROVIDER="${ENVCTL_SOURCE_PAYMENT_PROVIDER:-}"' in backend_start
    assert (
        'CREEM_BILLING_ENABLED="${ENVCTL_SOURCE_CREEM_BILLING_ENABLED:-}"'
        in backend_start
    )
    assert 'CREEM_ENVIRONMENT="${ENVCTL_SOURCE_CREEM_ENVIRONMENT:-}"' in (
        backend_start
    )
    assert 'CREEM_API_KEY="${ENVCTL_SOURCE_CREEM_API_KEY:-}"' in backend_start
    assert (
        'CREEM_WEBHOOK_SECRET="${ENVCTL_SOURCE_CREEM_WEBHOOK_SECRET:-}"'
        in backend_start
    )
    assert (
        'CREEM_PROFESSIONAL_MONTHLY_PRODUCT_ID="'
        '${ENVCTL_SOURCE_CREEM_PROFESSIONAL_MONTHLY_PRODUCT_ID:-}"'
        in backend_start
    )
    assert (
        'CREEM_PROFESSIONAL_TRIAL_DAYS="'
        '${ENVCTL_SOURCE_CREEM_PROFESSIONAL_TRIAL_DAYS:-}"' in backend_start
    )
    assert (
        'PADDLE_BILLING_ENABLED="${ENVCTL_SOURCE_PADDLE_BILLING_ENABLED:-}"'
        in backend_start
    )
    assert 'PADDLE_ENVIRONMENT="${ENVCTL_SOURCE_PADDLE_ENVIRONMENT:-}"' in (
        backend_start
    )
    assert 'PADDLE_API_KEY="${ENVCTL_SOURCE_PADDLE_API_KEY:-}"' in backend_start
    assert (
        'PADDLE_GROWTH_MONTHLY_PRICE_ID="'
        '${ENVCTL_SOURCE_PADDLE_GROWTH_MONTHLY_PRICE_ID:-}"' in backend_start
    )
    assert (
        'PADDLE_GROWTH_TRIAL_DAYS="${ENVCTL_SOURCE_PADDLE_GROWTH_TRIAL_DAYS:-}"'
        in backend_start
    )
    assert (
        'VITE_PADDLE_CLIENT_TOKEN="${ENVCTL_SOURCE_VITE_PADDLE_CLIENT_TOKEN:-}"'
        in frontend_start
    )
    assert (
        'VITE_PADDLE_ENVIRONMENT="${ENVCTL_SOURCE_VITE_PADDLE_ENVIRONMENT:-}"'
        in frontend_start
    )
    assert "PAYMENT_PROVIDER=${ENVCTL_SOURCE_PAYMENT_PROVIDER}" in rendered
    assert (
        "CREEM_BILLING_ENABLED=${ENVCTL_SOURCE_CREEM_BILLING_ENABLED}"
        in rendered
    )
    assert "CREEM_ENVIRONMENT=${ENVCTL_SOURCE_CREEM_ENVIRONMENT}" in rendered
    assert "CREEM_API_KEY=${ENVCTL_SOURCE_CREEM_API_KEY}" in rendered
    assert "CREEM_WEBHOOK_SECRET=${ENVCTL_SOURCE_CREEM_WEBHOOK_SECRET}" in rendered
    assert (
        "CREEM_PROFESSIONAL_MONTHLY_PRODUCT_ID="
        "${ENVCTL_SOURCE_CREEM_PROFESSIONAL_MONTHLY_PRODUCT_ID}" in rendered
    )
    assert (
        "CREEM_PROFESSIONAL_TRIAL_DAYS="
        "${ENVCTL_SOURCE_CREEM_PROFESSIONAL_TRIAL_DAYS}" in rendered
    )
    assert (
        "PADDLE_BILLING_ENABLED=${ENVCTL_SOURCE_PADDLE_BILLING_ENABLED}"
        in rendered
    )
    assert "PADDLE_ENVIRONMENT=${ENVCTL_SOURCE_PADDLE_ENVIRONMENT}" in rendered
    assert "PADDLE_API_KEY=${ENVCTL_SOURCE_PADDLE_API_KEY}" in rendered
    assert (
        "PADDLE_GROWTH_MONTHLY_PRICE_ID="
        "${ENVCTL_SOURCE_PADDLE_GROWTH_MONTHLY_PRICE_ID}" in rendered
    )
    assert (
        "PADDLE_GROWTH_TRIAL_DAYS=${ENVCTL_SOURCE_PADDLE_GROWTH_TRIAL_DAYS}"
        in rendered
    )
    assert (
        "VITE_PADDLE_CLIENT_TOKEN=${ENVCTL_SOURCE_VITE_PADDLE_CLIENT_TOKEN}"
        in rendered
    )
    assert (
        "VITE_PADDLE_ENVIRONMENT=${ENVCTL_SOURCE_VITE_PADDLE_ENVIRONMENT}"
        in rendered
    )
    assert "test-api-key" not in rendered
    assert "test-client-token" not in rendered


def test_macos_memory_fallback_parses_vm_stat(monkeypatch):
    controller = load_controller()

    def fake_run_capture(argv, *, timeout):
        del timeout
        if argv == ["sysctl", "-n", "hw.memsize"]:
            return subprocess.CompletedProcess(argv, 0, "68719476736\n", "")
        if argv == ["vm_stat"]:
            return subprocess.CompletedProcess(
                argv,
                0,
                "\n".join(
                    [
                        "Mach Virtual Memory Statistics: (page size of 16384 bytes)",
                        "Pages free: 10.",
                        "Pages inactive: 20.",
                        "Pages speculative: 30.",
                        "Pages purgeable: 40.",
                    ]
                ),
                "",
            )
        return None

    monkeypatch.setattr(controller, "run_capture", fake_run_capture)

    total, available = controller.read_macos_memory()

    assert total == 68719476736
    assert available == (10 + 20 + 30 + 40) * 16384


def test_top_processes_falls_back_to_bsd_ps(monkeypatch):
    controller = load_controller()

    def fake_run_capture(argv, *, timeout):
        del timeout
        if "--sort=-pcpu" in argv:
            return None
        return subprocess.CompletedProcess(
            argv,
            0,
            "\n".join(
                [
                    "PID COMM %CPU %MEM",
                    "123 /usr/bin/python 42.0 1.2",
                    "456 /usr/bin/node 12.0 0.8",
                ]
            ),
            "",
        )

    monkeypatch.setattr(controller, "run_capture", fake_run_capture)

    assert controller.read_top_processes() == [
        "123 /usr/bin/python 42.0 1.2",
        "456 /usr/bin/node 12.0 0.8",
    ]


def test_headless_envctl_env_removes_plan_agent_aliases(monkeypatch):
    controller = load_controller()
    monkeypatch.setenv("CMUX_WORKSPACE_ID", "workspace:1")
    monkeypatch.setenv("SUPERSET_PROJECT", "pele")
    monkeypatch.setenv("ENVCTL_PLAN_AGENT_TERMINALS_ENABLE", "true")
    monkeypatch.setenv("GH_TOKEN", "secret")
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    monkeypatch.setenv("RUNNER_TRACKING_ID", "runner-tracking-id")
    monkeypatch.setenv("ACTIONS_RUNTIME_TOKEN", "secret")
    monkeypatch.setenv("ENVCTL_PREVIEW_EXTERNAL_DEPS_JSON", '{"supabase":[]}')
    monkeypatch.setenv("ENVCTL_PREVIEW_PUBLIC_LINK_TOKEN", "public-link-token")
    monkeypatch.setenv("PADDLE_API_KEY", "wrong-paddle-api-key")
    monkeypatch.setenv("SUPABASE_URL", "https://wrong-supabase.example.test")
    monkeypatch.setenv("VITE_API_URL", "https://wrong-api.example.test/api/v1")
    monkeypatch.setenv("VITE_BACKEND_URL", "https://wrong-api.example.test")
    monkeypatch.setenv("VITE_SUPABASE_URL", "https://wrong-supabase.example.test")
    monkeypatch.setenv("ENVCTL_SOURCE_AI_PROVIDER", "gemini")
    monkeypatch.setenv("ENVCTL_SOURCE_GOOGLE_API_KEY", "google-api-key")
    monkeypatch.setenv("ENVCTL_BACKEND_ENV__PADDLE_API_KEY", "right-paddle-api-key")
    monkeypatch.setenv(
        "ENVCTL_FRONTEND_ENV__VITE_API_URL",
        "https://right-api.example.test/api/v1",
    )

    env = controller.headless_envctl_env()

    assert "CMUX_WORKSPACE_ID" not in env
    assert "SUPERSET_PROJECT" not in env
    assert "GH_TOKEN" not in env
    assert "GITHUB_TOKEN" not in env
    assert "RUNNER_TRACKING_ID" not in env
    assert "ACTIONS_RUNTIME_TOKEN" not in env
    assert "ENVCTL_PREVIEW_EXTERNAL_DEPS_JSON" not in env
    assert "ENVCTL_PREVIEW_PUBLIC_LINK_TOKEN" not in env
    assert "PADDLE_API_KEY" not in env
    assert "SUPABASE_URL" not in env
    assert "VITE_API_URL" not in env
    assert "VITE_BACKEND_URL" not in env
    assert "VITE_SUPABASE_URL" not in env
    assert env["ENVCTL_SOURCE_AI_PROVIDER"] == "gemini"
    assert env["ENVCTL_SOURCE_GOOGLE_API_KEY"] == "google-api-key"
    assert env["ENVCTL_BACKEND_ENV__PADDLE_API_KEY"] == "right-paddle-api-key"
    assert (
        env["ENVCTL_FRONTEND_ENV__VITE_API_URL"]
        == "https://right-api.example.test/api/v1"
    )
    assert env["ENVCTL_PLAN_AGENT_TERMINALS_ENABLE"] == "false"
    assert env["ENVCTL_UI_BACKEND"] == "non_interactive"

    import_env = controller.headless_envctl_env(keep_github_tokens=True)
    assert import_env["GH_TOKEN"] == "secret"
    assert import_env["GITHUB_TOKEN"] == "secret"
    assert "RUNNER_TRACKING_ID" not in import_env
    assert "CMUX_WORKSPACE_ID" not in import_env
    assert "ACTIONS_RUNTIME_TOKEN" not in import_env
    assert "VITE_API_URL" not in import_env


def test_pr_preview_start_env_overrides_keep_app_launch_env(monkeypatch):
    controller = load_controller()
    monkeypatch.setenv("ENVCTL_SOURCE_PADDLE_BILLING_ENABLED", "true")
    monkeypatch.setenv("ENVCTL_BACKEND_ENV__PAYMENT_PROVIDER", "paddle")
    monkeypatch.setenv(
        "ENVCTL_FRONTEND_ENV__VITE_PADDLE_CLIENT_TOKEN",
        "test-client-token",
    )
    monkeypatch.setenv("ENVCTL_PREVIEW_PUBLIC_LINK_TOKEN", "public-link-token")
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    monkeypatch.setenv("UNRELATED", "value")

    env = controller.pr_preview_start_env_overrides()

    assert env == {
        "ENVCTL_SOURCE_PADDLE_BILLING_ENABLED": "true",
        "ENVCTL_BACKEND_ENV__PAYMENT_PROVIDER": "paddle",
        "ENVCTL_FRONTEND_ENV__VITE_PADDLE_CLIENT_TOKEN": "test-client-token",
    }


def test_unsafe_plan_agent_config_entries_rejects_terminal_enablers(tmp_path):
    controller = load_controller()
    envctl_file = tmp_path / ".envctl"
    envctl_file.write_text(
        "\n".join(
            [
                "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE=false",
                "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE=envctl",
                "SUPERSET=false",
                "SUPERSET_PROJECT=preview",
            ]
        )
    )

    result = controller.unsafe_plan_agent_config_entries(envctl_file)

    assert result == [
        "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE",
        "SUPERSET_PROJECT",
    ]


def test_closed_pr_cleanup_requires_label_or_controller_state(tmp_path):
    controller = load_controller()
    config = controller.ControllerConfig(
        repo_slug="OrgPele/pele-monorepo",
        label="deploy-app",
        ttl_minutes=45,
        preview_root=tmp_path,
        control_repo=tmp_path / "repo",
        state_dir=tmp_path / "state",
        envctl_bin="envctl",
        public_host="localhost",
        public_base_domain="",
        public_scheme="https",
        public_route_image="alpine:3.20",
        ui_visual_host="localhost",
        public_link_token_configured=False,
        bootstrap_envctl_config=True,
        max_load_per_cpu=1.0,
        min_memory_available_percent=20.0,
        min_disk_free_percent=10.0,
        max_other_active_previews=1,
        dry_run=False,
    )
    pr = controller.PullRequestInfo(
        number=789,
        title="Closed",
        url="https://example.test/pr/789",
        state="CLOSED",
        merged=True,
        head_ref="feature/closed",
        head_sha="abc",
        head_repo_name="pele-monorepo",
        head_repo_owner="OrgPele",
        labels=(),
    )
    instance = controller.PreviewController(config, controller.CommandRunner())

    assert instance.preview_requested_or_tracked(pr) is False
    assert instance.preview_requested_or_tracked(
        controller.PullRequestInfo(**{**pr.__dict__, "labels": ("deploy-app",)})
    )

    instance.save_state(
        controller.PreviewState(
            pr_number=pr.number,
            label="deploy-app",
            project="feature/closed",
            root=str(tmp_path / "repo" / "trees" / "imported" / "feature-closed"),
            head_ref="feature/closed",
            head_sha="abc",
            status="stopped",
            label_added_at=None,
            started_at=None,
            expires_at=None,
            updated_at="2026-06-14T00:00:00Z",
            endpoints={},
        )
    )

    assert instance.preview_requested_or_tracked(pr) is True
