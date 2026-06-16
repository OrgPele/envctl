from __future__ import annotations

from pathlib import Path
import subprocess
from types import SimpleNamespace

from envctl_engine.actions import action_pr_label_support as support


def test_add_ship_pr_label_ensures_label_then_adds_it_to_pr(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    context = SimpleNamespace(env={"ENVCTL_SHIP_PR_LABEL_ENABLE": "true"})

    def run_process(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append([str(token) for token in args])
        if args[1:3] == ["label", "list"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="[]", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    code = support.add_ship_pr_label(
        context,
        tmp_path,
        "https://github.com/acme/repo/pull/7",
        gh_path="/usr/bin/gh",
        run_process=run_process,
    )

    assert code == 0
    assert calls == [
        [
            "/usr/bin/gh",
            "label",
            "list",
            "--search",
            "deploy-app",
            "--json",
            "name",
        ],
        [
            "/usr/bin/gh",
            "label",
            "create",
            "deploy-app",
            "--color",
            support.DEFAULT_SHIP_PR_LABEL_COLOR,
            "--description",
            support.DEFAULT_SHIP_PR_LABEL_DESCRIPTION,
        ],
        [
            "/usr/bin/gh",
            "pr",
            "edit",
            "https://github.com/acme/repo/pull/7",
            "--add-label",
            "deploy-app",
        ],
    ]


def test_add_ship_pr_label_uses_configured_label(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    context = SimpleNamespace(
        env={
            "ENVCTL_SHIP_PR_LABEL_ENABLE": "true",
            "ENVCTL_SHIP_PR_LABEL": "codex",
        }
    )

    def run_process(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append([str(token) for token in args])
        if args[1:3] == ["label", "list"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="[]", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    code = support.add_ship_pr_label(
        context,
        tmp_path,
        "https://github.com/acme/repo/pull/7",
        gh_path="/usr/bin/gh",
        run_process=run_process,
    )

    assert code == 0
    assert calls[0][4] == "codex"
    assert calls[1][3] == "codex"
    assert calls[2][-1] == "codex"


def test_add_ship_pr_label_does_not_recreate_existing_label(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    context = SimpleNamespace(env={"ENVCTL_SHIP_PR_LABEL_ENABLE": "true"})

    def run_process(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append([str(token) for token in args])
        if args[1:3] == ["label", "list"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout='[{"name":"deploy-app"}]', stderr="")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    code = support.add_ship_pr_label(
        context,
        tmp_path,
        "https://github.com/acme/repo/pull/7",
        gh_path="/usr/bin/gh",
        run_process=run_process,
    )

    assert code == 0
    assert [call[1:3] for call in calls] == [["label", "list"], ["pr", "edit"]]


def test_add_ship_pr_label_is_disabled_by_default(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    context = SimpleNamespace(env={})

    def run_process(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append([str(token) for token in args])
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    code = support.add_ship_pr_label(
        context,
        tmp_path,
        "https://github.com/acme/repo/pull/7",
        gh_path="/usr/bin/gh",
        run_process=run_process,
    )

    assert code == 0
    assert calls == []


def test_add_ship_pr_label_can_be_disabled_explicitly(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    context = SimpleNamespace(env={"ENVCTL_SHIP_PR_LABEL_ENABLE": "false"})

    def run_process(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append([str(token) for token in args])
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    code = support.add_ship_pr_label(
        context,
        tmp_path,
        "https://github.com/acme/repo/pull/7",
        gh_path="/usr/bin/gh",
        run_process=run_process,
    )

    assert code == 0
    assert calls == []


def test_add_ship_pr_label_can_skip_blank_label_when_enabled(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    context = SimpleNamespace(
        env={
            "ENVCTL_SHIP_PR_LABEL_ENABLE": "true",
            "ENVCTL_SHIP_PR_LABEL": " ",
        }
    )

    def run_process(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append([str(token) for token in args])
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    code = support.add_ship_pr_label(
        context,
        tmp_path,
        "https://github.com/acme/repo/pull/7",
        gh_path="/usr/bin/gh",
        run_process=run_process,
    )

    assert code == 0
    assert calls == []
