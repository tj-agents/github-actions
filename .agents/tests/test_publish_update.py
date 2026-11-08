"""Tests for the hosted Renovate preset."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RENOVATE_DEFAULT = ROOT / "renovate-default.json"
RENOVATE_CONFIG = ROOT / ".github/renovate.json"


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


def test_repository_inherits_scheduled_native_pr_automatic_merges() -> None:
    preset = json.loads(RENOVATE_DEFAULT.read_text(encoding="utf-8"))
    canary = json.loads(RENOVATE_CONFIG.read_text(encoding="utf-8"))
    effective = {**preset, **canary}
    assert canary["extends"] == ["github>tj-agents/github-actions:renovate-default"]
    assert "automerge" not in canary
    assert "schedule" not in canary
    assert effective["automerge"] is True
    assert effective["automergeType"] == "pr"
    assert effective["platformAutomerge"] is False
    assert effective["rebaseWhen"] == "behind-base-branch"
    assert effective["schedule"] == ["* 0-5 * * *"]
