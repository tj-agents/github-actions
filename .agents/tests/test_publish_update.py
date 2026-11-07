"""Tests for verified repository update publication."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".agents/github-actions/utility/publish-update/scripts"
PUBLISH = ROOT / ".github/actions/publish-update/publish.py"
PUBLISH_WORKFLOW = ROOT / ".github/workflows/publish-update.yml"
UPDATER_WORKFLOW = ROOT / ".github/workflows/update-pins.yml"
RENOVATE_DEFAULT = ROOT / "renovate-default.json"


def load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


caller = load("caller", SCRIPTS / "caller.py")
publish = load("publish", PUBLISH)
updater = load("publisher_updater", ROOT / ".github/actions/update-pins/update_pins.py")


def completed(repository: str = "octo/example", branch: str = "main") -> dict[str, Any]:
    return {
        "repository": {"default_branch": branch},
        "workflow_run": {
            "name": "ci",
            "status": "completed",
            "conclusion": "success",
            "event": "push",
            "head_branch": branch,
            "head_sha": "b" * 40,
            "head_repository": {"full_name": repository},
        },
    }


def test_verified_default_branch_reports_categories_without_contents() -> None:
    event = completed()
    assert publish.hint(
        event,
        "octo/example",
        ["plugins/a", ".github/merge-policy.json"],
    ) == {
        "v": 1,
        "repo": "octo/example",
        "sha": "b" * 40,
        "changes": ["repository", "merge-policy", "marketplace"],
    }
    failure_cases: dict[str, list[Any]] = {
        "status": ["in_progress"],
        "conclusion": ["failure", "cancelled"],
        "event": ["pull_request"],
        "head_branch": ["feature"],
        "head_repository": [{"full_name": "fork/example"}],
    }
    for field, values in failure_cases.items():
        for value in values:
            changed = {
                **event,
                "workflow_run": {**event["workflow_run"], field: value},
            }
            assert publish.hint(changed, "octo/example") is None
    assert (
        publish.hint(
            {"ref": "refs/heads/main", "repository": {"default_branch": "main"}},
            "octo/example",
        )
        is None
    )


def test_uses_actual_default_branch() -> None:
    event = completed("openai/tools", "trunk")
    assert publish.hint(event, "openai/tools") == {
        "v": 1,
        "repo": "openai/tools",
        "sha": "b" * 40,
        "changes": ["repository", "merge-policy", "marketplace"],
    }


def test_payload_never_uses_a_hinted_url_or_shell() -> None:
    with pytest.raises(ValueError):
        publish.hint({}, "evil/repository/extra")
    opener = mock.MagicMock()
    with pytest.raises(ValueError):
        publish.publish("../../bad", {}, opener)
    opener.assert_not_called()
    message = publish.hint(
        completed("any-owner/any-repository"),
        "any-owner/any-repository",
        ["private-token.txt"],
    )
    assert message is not None
    assert "private-token" not in json.dumps(message)
    publish.publish("a" * 48, message, opener)
    request = opener.call_args.args[0]
    assert request.full_url == "https://ntfy.sh/" + "a" * 48
    assert json.loads(request.data) == message
    assert opener.call_args.kwargs["timeout"] == 20


def test_head_verification_blocks_stale_and_failed_runs() -> None:
    event = completed("tj-agents/core")
    opener = mock.MagicMock()
    response = opener.return_value.__enter__.return_value
    response.read.return_value = json.dumps(
        {"sha": "b" * 40, "parents": [{"sha": "a" * 40}]}
    ).encode()
    revision = publish.verified_revision(event, "tj-agents/core", "token", opener)
    assert revision == {"after": "b" * 40}
    response.read.return_value = json.dumps({"sha": "c" * 40}).encode()
    assert publish.verified_revision(event, "tj-agents/core", "token", opener) is None
    opener.reset_mock()
    event["workflow_run"]["conclusion"] = "failure"
    assert publish.verified_revision(event, "tj-agents/core", "token", opener) is None
    opener.assert_not_called()


def test_unknown_push_range_includes_all_categories() -> None:
    # The head may be regeneration or the last commit of a multi-commit push.
    message = publish.hint(completed("tj-agents/core"), "tj-agents/core")
    assert message is not None
    assert message["changes"] == ["repository", "merge-policy", "marketplace"]


def test_uniform_caller_waits_for_ci_and_has_read_only_permissions() -> None:
    value = caller.render("a" * 40)
    assert (
        "uses: tj-agents/github-actions/.github/workflows/publish-update.yml@"
        + "a" * 40
        in value
    )
    assert "workflow_run:" in value
    assert "workflows: [ci]" in value
    assert "types: [completed]" in value
    assert "contents: read" in value
    assert "schedule:" not in value
    assert "UPDATE_TOPIC: ${{ secrets.UPDATE_TOPIC }}" in value
    assert "runs-on:" not in value
    assert "steps:" not in value
    with pytest.raises(ValueError):
        caller.render("main")


def test_canonical_workflows_guard_verified_origin_and_secret_contracts() -> None:
    publisher = PUBLISH_WORKFLOW.read_text(encoding="utf-8")
    updater = UPDATER_WORKFLOW.read_text(encoding="utf-8")
    assert (
        "workflow_call:\n    secrets:\n      UPDATE_TOPIC:\n        required: false"
        in publisher
    )
    assert "github.event.workflow_run.conclusion == 'success'" in publisher
    assert (
        "github.event.workflow_run.head_repository.full_name == github.repository"
        in publisher
    )
    assert "uses: $/.github/actions/publish-update" in publisher
    assert "tj-agents/github-actions/.github/actions/publish-update@" not in publisher
    assert "actions/checkout" not in publisher
    assert "UPDATE_APP_PRIVATE_KEY:\n        required: true" in updater
    assert "permission-contents: write" in updater
    assert "permission-pull-requests: write" in updater
    assert "permission-workflows: write" in updater


def test_shared_renovate_preset_uses_native_dependency_management() -> None:
    assert json.loads(RENOVATE_DEFAULT.read_text(encoding="utf-8")) == {
        "$schema": "https://docs.renovatebot.com/renovate-schema.json",
        "extends": ["config:recommended", "helpers:pinGitHubActionDigests"],
        "automerge": True,
        "automergeType": "pr",
        "automergeStrategy": "squash",
        "platformAutomerge": False,
        "rebaseWhen": "behind-base-branch",
        "updateNotScheduled": True,
        "dependencyDashboardApproval": False,
        "timezone": "Europe/London",
        "schedule": ["* 0-5 * * *"],
        "packageRules": [
            {
                "matchUpdateTypes": ["minor", "patch", "digest", "pin", "pinDigest"],
                "groupName": "non-major dependencies",
            },
            {
                "matchManagers": ["github-actions"],
                "matchPackageNames": ["tj-agents/template"],
                "enabled": False,
            },
        ],
        "lockFileMaintenance": {"enabled": True},
    }


@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_scheduled_updates_regenerate_an_enrolled_caller(
    tmp_path: Path, ending: str
) -> None:
    path = tmp_path / ".github/workflows/publish-update.yml"
    path.parent.mkdir(parents=True)
    before = (
        caller.render("a" * 40)
        .replace(
            "  workflow_run:\n    workflows: [ci]\n    types: [completed]\n",
            "  push:\n",
        )
        .replace("\n", ending)
    )
    path.write_bytes(before.encode())
    summary = updater.update(
        tmp_path,
        ["tj-agents/github-actions"],
        files=[".github/workflows/publish-update.yml"],
        resolver=lambda _: "b" * 40,
        comparer=lambda *_: None,
        content_comparer=lambda *_: True,
    )
    assert summary["changed"]
    assert path.read_bytes().decode() == caller.render("b" * 40).replace("\n", ending)


def test_caller_regeneration_refuses_to_drop_custom_jobs(tmp_path: Path) -> None:
    path = tmp_path / ".github/workflows/publish-update.yml"
    path.parent.mkdir(parents=True)
    before = caller.render("a" * 40) + "  custom:\n    runs-on: ubuntu-latest\n"
    path.write_text(before, encoding="utf-8")
    with pytest.raises(ValueError, match="custom publisher workflow"):
        updater.update(
            tmp_path,
            ["tj-agents/github-actions"],
            files=[".github/workflows/publish-update.yml"],
            resolver=lambda _: "b" * 40,
            comparer=lambda *_: None,
            content_comparer=lambda *_: True,
        )
    assert path.read_text(encoding="utf-8") == before


def test_unchanged_publisher_workflow_preserves_its_pin(tmp_path: Path) -> None:
    path = tmp_path / ".github/workflows/publish-update.yml"
    path.parent.mkdir(parents=True)
    before = caller.render("a" * 40)
    path.write_text(before, encoding="utf-8")
    summary = updater.update(
        tmp_path,
        ["tj-agents/github-actions"],
        files=[".github/workflows/publish-update.yml"],
        resolver=lambda _: "b" * 40,
        comparer=lambda *_: None,
        content_comparer=lambda *_: False,
    )
    assert not summary["changed"]
    assert path.read_text(encoding="utf-8") == before


@pytest.mark.parametrize("custom", ["condition", "secret"])
def test_caller_regeneration_preserves_custom_publication_controls(
    tmp_path: Path, custom: str
) -> None:
    path = tmp_path / ".github/workflows/publish-update.yml"
    path.parent.mkdir(parents=True)
    before = caller.render("a" * 40)
    if custom == "condition":
        before = before.replace("  publish:\n", "  publish:\n    if: false\n")
    else:
        before = before.replace("secrets.UPDATE_TOPIC", "secrets.CUSTOM_TOPIC")
    path.write_text(before, encoding="utf-8")
    with pytest.raises(ValueError, match="custom publisher workflow"):
        updater.update(
            tmp_path,
            ["tj-agents/github-actions"],
            files=[".github/workflows/publish-update.yml"],
            resolver=lambda _: "b" * 40,
            comparer=lambda *_: None,
            content_comparer=lambda *_: True,
        )
    assert path.read_text(encoding="utf-8") == before
