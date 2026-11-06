import base64
import importlib.util
from pathlib import Path
from typing import Any, cast

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "merge_updater_prs",
    ROOT / ".agents/github-actions/utility/publish-update/scripts/merge_updater_prs.py",
)
assert SPEC is not None and SPEC.loader is not None
merger = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(merger)

OLD = "a" * 40
NEW = "b" * 40
BASE = "c" * 40
HEAD = "d" * 40


def entry(content: str) -> tuple[tuple[str, str, str], dict[str, Any]]:
    encoded = content.encode()
    oid = merger.blob_sha(encoded)
    return ("100644", "blob", oid), {
        "encoding": "base64",
        "content": base64.b64encode(encoded).decode(),
    }


class FakeGitHub:
    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = responses
        self.calls: list[str] = []
        self.bodies: list[Any] = []

    def api(self, path: str, method: str = "GET", body: Any = None) -> Any:
        self.calls.append(f"{method} {path}")
        self.bodies.append(body)
        try:
            value = self.responses[path]
        except KeyError as error:
            raise AssertionError(path) from error
        if isinstance(value, Exception):
            raise value
        return value

    def optional(self, path: str) -> Any:
        return self.responses.get(path)


def trees(
    before: dict[str, tuple[str, str, str]], after: dict[str, tuple[str, str, str]]
) -> dict[str, Any]:
    def render(values: dict[str, tuple[str, str, str]]) -> dict[str, Any]:
        return {
            "truncated": False,
            "tree": [
                {"path": path, "mode": mode, "type": kind, "sha": oid}
                for path, (mode, kind, oid) in values.items()
            ],
        }

    return {
        f"repos/tj-agents/example/git/trees/{BASE}?recursive=1": render(before),
        f"repos/tj-agents/example/git/trees/{HEAD}?recursive=1": render(after),
    }


@pytest.mark.parametrize("path", [".github/..\\outside.yml", "C:/outside.yml"])
def test_tree_rejects_windows_escaping_paths(path: str) -> None:
    gh = FakeGitHub(
        {
            f"repos/tj-agents/example/git/trees/{BASE}?recursive=1": {
                "truncated": False,
                "tree": [
                    {
                        "path": path,
                        "mode": "100644",
                        "type": "blob",
                        "sha": OLD,
                    }
                ],
            }
        }
    )
    with pytest.raises(merger.MergeError, match="unsafe tree entry"):
        merger.tree(gh, "tj-agents/example", BASE)


def source_responses() -> dict[str, Any]:
    root_old, root_new = "1" * 40, "2" * 40
    github_old, github_new = "3" * 40, "4" * 40
    actions_old, actions_new = "5" * 40, "6" * 40
    check_old, check_new = "7" * 40, "8" * 40

    def tree_entry(path: str, oid: str) -> dict[str, Any]:
        return {"tree": [{"path": path, "type": "tree", "sha": oid}]}

    return {
        "repos/tj-agents/github-actions": {"default_branch": "main"},
        "repos/tj-agents/github-actions/commits/main": {"sha": NEW},
        f"repos/tj-agents/github-actions/compare/{NEW}...{NEW}": {
            "status": "identical"
        },
        f"repos/tj-agents/github-actions/compare/{OLD}...{NEW}": {"status": "ahead"},
        f"repos/tj-agents/github-actions/commits/{OLD}": {
            "commit": {"tree": {"sha": root_old}}
        },
        f"repos/tj-agents/github-actions/commits/{NEW}": {
            "commit": {"tree": {"sha": root_new}}
        },
        f"repos/tj-agents/github-actions/git/trees/{root_old}": tree_entry(
            ".github", github_old
        ),
        f"repos/tj-agents/github-actions/git/trees/{root_new}": tree_entry(
            ".github", github_new
        ),
        f"repos/tj-agents/github-actions/git/trees/{github_old}": tree_entry(
            "actions", actions_old
        ),
        f"repos/tj-agents/github-actions/git/trees/{github_new}": tree_entry(
            "actions", actions_new
        ),
        f"repos/tj-agents/github-actions/git/trees/{actions_old}": tree_entry(
            "check", check_old
        ),
        f"repos/tj-agents/github-actions/git/trees/{actions_new}": tree_entry(
            "check", check_new
        ),
    }


def enrollment() -> str:
    return '{"schema_version":1,"repository":"tj-agents/example"}\n'


def test_replay_accepts_exact_normal_generator_output() -> None:
    source = "uses: tj-agents/github-actions/.github/actions/check@" + OLD + "\n"
    updated = "uses: tj-agents/github-actions/.github/actions/check@" + NEW + "\n"
    before_entry, before_blob = entry(source)
    declaration_entry, declaration_blob = entry(enrollment())
    after_entry, after_blob = entry(updated)
    before = {
        ".github": ("040000", "tree", "e" * 40),
        ".github/workflows": ("040000", "tree", "f" * 40),
        ".github/workflows/ci.yml": before_entry,
        ".github/update-enrollment.json": declaration_entry,
    }
    after = {
        ".github": ("040000", "tree", "0" * 40),
        ".github/workflows": ("040000", "tree", "1" * 40),
        ".github/workflows/ci.yml": after_entry,
        ".github/update-enrollment.json": declaration_entry,
    }
    responses = (
        trees(before, after)
        | source_responses()
        | {
            f"repos/tj-agents/example/git/blobs/{before_entry[2]}": before_blob,
            f"repos/tj-agents/example/git/blobs/{after_entry[2]}": after_blob,
            (
                f"repos/tj-agents/example/git/blobs/{declaration_entry[2]}"
            ): declaration_blob,
        }
    )
    assert merger.replay(
        FakeGitHub(responses), "tj-agents", "tj-agents/example", BASE, HEAD
    )


def test_replay_accepts_exact_bootstrap_caller() -> None:
    ci = """name: ci

on:
  push:
    branches: [main]
  pull_request:

jobs:
  verify:
    uses: tj-agents/template/.github/workflows/plugin-ci.yml@main
    with:
      template_ref: main
"""
    before_ci, ci_blob = entry(ci)
    declaration_entry, declaration_blob = entry(enrollment())
    caller = merger.UPDATER._caller_module().render_updater(
        NEW, "tj-agents/github-actions"
    )
    migrated_ci = merger.UPDATER.migrate_template_ci(ci)
    after_ci, migrated_ci_blob = entry(migrated_ci)
    after_caller, caller_blob = entry(caller)
    before = {
        ".github/workflows/ci.yml": before_ci,
        ".github/update-enrollment.json": declaration_entry,
    }
    after = {
        ".github/workflows/ci.yml": after_ci,
        ".github/update-enrollment.json": declaration_entry,
        ".github/workflows/update-pins.yml": after_caller,
    }
    responses = (
        trees(before, after)
        | source_responses()
        | {
            f"repos/tj-agents/example/git/blobs/{before_ci[2]}": ci_blob,
            f"repos/tj-agents/example/git/blobs/{after_ci[2]}": migrated_ci_blob,
            (
                f"repos/tj-agents/example/git/blobs/{declaration_entry[2]}"
            ): declaration_blob,
            f"repos/tj-agents/example/git/blobs/{after_caller[2]}": caller_blob,
        }
    )
    assert merger.replay(
        FakeGitHub(responses), "tj-agents", "tj-agents/example", BASE, HEAD
    )


def test_replay_rejects_any_extra_file_or_mode_change() -> None:
    source = "uses: tj-agents/github-actions/.github/actions/check@" + OLD + "\n"
    updated = "uses: tj-agents/github-actions/.github/actions/check@" + NEW + "\n"
    before_entry, before_blob = entry(source)
    declaration_entry, declaration_blob = entry(enrollment())
    after_entry, after_blob = entry(updated)
    extra_entry, extra_blob = entry("untrusted\n")
    before = {
        ".github/workflows/ci.yml": before_entry,
        ".github/update-enrollment.json": declaration_entry,
    }
    after = {
        ".github/workflows/ci.yml": after_entry,
        ".github/update-enrollment.json": declaration_entry,
        "README.md": extra_entry,
    }
    responses = (
        trees(before, after)
        | source_responses()
        | {
            f"repos/tj-agents/example/git/blobs/{before_entry[2]}": before_blob,
            f"repos/tj-agents/example/git/blobs/{after_entry[2]}": after_blob,
            (
                f"repos/tj-agents/example/git/blobs/{declaration_entry[2]}"
            ): declaration_blob,
            f"repos/tj-agents/example/git/blobs/{extra_entry[2]}": extra_blob,
        }
    )
    assert not merger.replay(
        FakeGitHub(responses), "tj-agents", "tj-agents/example", BASE, HEAD
    )


def test_checks_require_current_matching_check_and_status_evidence() -> None:
    context = {("verify", 7)}
    runs_path = (
        f"repos/tj-agents/example/commits/{HEAD}/check-runs?filter=latest"
        "&per_page=100&page=1"
    )
    gh = FakeGitHub(
        {
            runs_path: {
                "check_runs": [
                    {
                        "id": 1,
                        "name": "verify",
                        "head_sha": HEAD,
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"id": 7},
                    }
                ]
            },
            f"repos/tj-agents/example/commits/{HEAD}/statuses?per_page=100&page=1": [],
        }
    )
    assert merger.check_state(gh, "tj-agents/example", HEAD, context) == (True, True)
    stale = FakeGitHub(
        {
            runs_path: {
                "check_runs": [
                    {
                        "id": 1,
                        "name": "verify",
                        "head_sha": BASE,
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"id": 7},
                    }
                ]
            },
            f"repos/tj-agents/example/commits/{HEAD}/statuses?per_page=100&page=1": [],
        }
    )
    assert merger.check_state(stale, "tj-agents/example", HEAD, context) == (
        False,
        True,
    )
    wrong_status = FakeGitHub(
        {
            runs_path: {
                "check_runs": [
                    {
                        "id": 1,
                        "name": "verify",
                        "head_sha": HEAD,
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"id": 7},
                    }
                ]
            },
            f"repos/tj-agents/example/commits/{HEAD}/statuses?per_page=100&page=1": [
                {"id": 1, "context": "verify", "state": "success"}
            ],
        }
    )
    assert merger.check_state(wrong_status, "tj-agents/example", HEAD, context) == (
        False,
        True,
    )


def test_check_records_reads_all_pages() -> None:
    first = [{"name": "first"}] * 100
    check_runs = f"repos/tj-agents/example/commits/{HEAD}/check-runs"
    statuses = f"repos/tj-agents/example/commits/{HEAD}/statuses"
    gh = FakeGitHub(
        {
            f"{check_runs}?filter=latest&per_page=100&page=1": {"check_runs": first},
            f"{check_runs}?filter=latest&per_page=100&page=2": {"check_runs": []},
            f"{statuses}?per_page=100&page=1": [{"context": "ok", "state": "success"}],
        }
    )
    runs, statuses, blocked = merger.check_records(gh, "tj-agents/example", HEAD)
    assert len(runs) == 100
    assert statuses == [{"context": "ok", "state": "success"}]
    assert blocked == set()
    assert any(
        "check-runs?filter=latest&per_page=100&page=2" in call for call in gh.calls
    )


def test_observed_ci_blocks_newer_pending_or_failing_check() -> None:
    runs_path = (
        f"repos/tj-agents/example/commits/{HEAD}/check-runs?filter=latest"
        "&per_page=100&page=1"
    )
    suites_path = (
        f"repos/tj-agents/example/commits/{HEAD}/check-suites?per_page=100&page=1"
    )
    for newest in (
        {"id": 2, "status": "in_progress", "conclusion": None},
        {"id": 2, "status": "completed", "conclusion": "failure"},
    ):
        statuses_path = (
            f"repos/tj-agents/example/commits/{HEAD}/statuses?per_page=100&page=1"
        )
        gh = FakeGitHub(
            {
                runs_path: {
                    "check_runs": [
                        {
                            "id": 1,
                            "name": "verify",
                            "head_sha": HEAD,
                            "status": "completed",
                            "conclusion": "success",
                            "app": {"id": 7},
                        },
                        {
                            "name": "verify",
                            "head_sha": HEAD,
                            "app": {"id": 7},
                            **newest,
                        },
                    ]
                },
                statuses_path: [],
                suites_path: {"check_suites": []},
            }
        )
        assert merger.observed_ci_state(gh, "tj-agents/example", HEAD) == (
            False,
            True,
            "current check is pending or failing",
        )


def test_observed_ci_uses_newest_status_and_requires_completed_suite() -> None:
    runs_path = (
        f"repos/tj-agents/example/commits/{HEAD}/check-runs?filter=latest"
        "&per_page=100&page=1"
    )
    statuses_path = (
        f"repos/tj-agents/example/commits/{HEAD}/statuses?per_page=100&page=1"
    )
    suites_path = (
        f"repos/tj-agents/example/commits/{HEAD}/check-suites?per_page=100&page=1"
    )
    gh = FakeGitHub(
        {
            runs_path: {"check_runs": []},
            statuses_path: [
                {"id": 1, "context": "ci", "state": "success"},
                {"id": 2, "context": "ci", "state": "pending"},
            ],
            suites_path: {"check_suites": []},
        }
    )
    assert merger.observed_ci_state(gh, "tj-agents/example", HEAD) == (
        False,
        True,
        "current status is pending or failing",
    )
    accepted = FakeGitHub(
        {
            runs_path: {
                "check_runs": [
                    {
                        "id": 8,
                        "name": "verify",
                        "head_sha": HEAD,
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"id": 7},
                    },
                    {
                        "id": 9,
                        "name": "portable",
                        "head_sha": HEAD,
                        "status": "completed",
                        "conclusion": "skipped",
                        "app": {"id": 7},
                    },
                ]
            },
            statuses_path: [],
            suites_path: {
                "check_suites": [
                    {
                        "id": 10,
                        "head_sha": HEAD,
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"id": 7},
                    }
                ]
            },
        }
    )
    assert merger.observed_ci_state(accepted, "tj-agents/example", HEAD) == (
        True,
        True,
        "",
    )


def test_dispatch_check_cannot_override_pending_pull_request_check() -> None:
    runs_path = (
        f"repos/tj-agents/example/commits/{HEAD}/check-runs?filter=latest"
        "&per_page=100&page=1"
    )
    suite_path = (
        f"repos/tj-agents/example/commits/{HEAD}/check-suites?per_page=100&page=1"
    )
    first_run_path = (
        f"repos/tj-agents/example/actions/runs?check_suite_id=101&head_sha={HEAD}"
        "&per_page=100&page=1"
    )
    second_run_path = (
        f"repos/tj-agents/example/actions/runs?check_suite_id=102&head_sha={HEAD}"
        "&per_page=100&page=1"
    )
    gh = FakeGitHub(
        {
            runs_path: {
                "check_runs": [
                    {
                        "id": 10,
                        "name": "verify",
                        "head_sha": HEAD,
                        "status": "in_progress",
                        "conclusion": None,
                        "app": {"id": merger.GITHUB_ACTIONS_APP_ID},
                        "check_suite": {"id": 101},
                    },
                    {
                        "id": 11,
                        "name": "verify",
                        "head_sha": HEAD,
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"id": merger.GITHUB_ACTIONS_APP_ID},
                        "check_suite": {"id": 102},
                    },
                ]
            },
            f"repos/tj-agents/example/commits/{HEAD}/statuses?per_page=100&page=1": [],
            suite_path: {"check_suites": []},
            first_run_path: {
                "workflow_runs": [
                    {
                        "check_suite_id": 101,
                        "head_sha": HEAD,
                        "event": "pull_request",
                        "workflow_id": 1,
                    }
                ]
            },
            second_run_path: {
                "workflow_runs": [
                    {
                        "check_suite_id": 102,
                        "head_sha": HEAD,
                        "event": "workflow_dispatch",
                        "workflow_id": 2,
                    }
                ]
            },
        }
    )
    assert merger.observed_ci_state(gh, "tj-agents/example", HEAD) == (
        False,
        True,
        "current check is pending or failing",
    )


def test_dispatch_check_does_not_block_eligible_pull_request_check() -> None:
    runs_path = (
        f"repos/tj-agents/example/commits/{HEAD}/check-runs?filter=latest"
        "&per_page=100&page=1"
    )
    suite_path = (
        f"repos/tj-agents/example/commits/{HEAD}/check-suites?per_page=100&page=1"
    )
    first_run_path = (
        f"repos/tj-agents/example/actions/runs?check_suite_id=101&head_sha={HEAD}"
        "&per_page=100&page=1"
    )
    second_run_path = (
        f"repos/tj-agents/example/actions/runs?check_suite_id=102&head_sha={HEAD}"
        "&per_page=100&page=1"
    )
    gh = FakeGitHub(
        {
            runs_path: {
                "check_runs": [
                    {
                        "id": 10,
                        "name": "verify",
                        "head_sha": HEAD,
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"id": merger.GITHUB_ACTIONS_APP_ID},
                        "check_suite": {"id": 101},
                    },
                    {
                        "id": 11,
                        "name": "verify",
                        "head_sha": HEAD,
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"id": merger.GITHUB_ACTIONS_APP_ID},
                        "check_suite": {"id": 102},
                    },
                ]
            },
            f"repos/tj-agents/example/commits/{HEAD}/statuses?per_page=100&page=1": [],
            suite_path: {"check_suites": []},
            first_run_path: {
                "workflow_runs": [
                    {
                        "check_suite_id": 101,
                        "head_sha": HEAD,
                        "event": "pull_request",
                        "workflow_id": 1,
                    }
                ]
            },
            second_run_path: {
                "workflow_runs": [
                    {
                        "check_suite_id": 102,
                        "head_sha": HEAD,
                        "event": "workflow_dispatch",
                        "workflow_id": 2,
                    }
                ]
            },
        }
    )
    assert merger.observed_ci_state(gh, "tj-agents/example", HEAD) == (True, True, "")


def test_observed_ci_requires_each_eligible_github_actions_suite() -> None:
    runs_path = (
        f"repos/tj-agents/example/commits/{HEAD}/check-runs?filter=latest"
        "&per_page=100&page=1"
    )
    statuses_path = (
        f"repos/tj-agents/example/commits/{HEAD}/statuses?per_page=100&page=1"
    )
    suites_path = (
        f"repos/tj-agents/example/commits/{HEAD}/check-suites?per_page=100&page=1"
    )
    first_run_path = (
        f"repos/tj-agents/example/actions/runs?check_suite_id=101&head_sha={HEAD}"
        "&per_page=100&page=1"
    )
    second_run_path = (
        f"repos/tj-agents/example/actions/runs?check_suite_id=102&head_sha={HEAD}"
        "&per_page=100&page=1"
    )
    gh = FakeGitHub(
        {
            runs_path: {
                "check_runs": [
                    {
                        "id": 1,
                        "name": "verify",
                        "head_sha": HEAD,
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"id": 7},
                    }
                ]
            },
            statuses_path: [],
            suites_path: {
                "check_suites": [
                    {
                        "id": 101,
                        "head_sha": HEAD,
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"id": merger.GITHUB_ACTIONS_APP_ID},
                    },
                    {
                        "id": 102,
                        "head_sha": HEAD,
                        "status": "completed",
                        "conclusion": "failure",
                        "app": {"id": merger.GITHUB_ACTIONS_APP_ID},
                    },
                ]
            },
            first_run_path: {
                "workflow_runs": [
                    {
                        "check_suite_id": 101,
                        "head_sha": HEAD,
                        "event": "pull_request",
                        "workflow_id": 1,
                    }
                ]
            },
            second_run_path: {
                "workflow_runs": [
                    {
                        "check_suite_id": 102,
                        "head_sha": HEAD,
                        "event": "pull_request",
                        "workflow_id": 2,
                    }
                ]
            },
        }
    )
    assert merger.observed_ci_state(gh, "tj-agents/example", HEAD) == (
        False,
        True,
        "check suite is pending or failing",
    )


def test_observed_ci_ignores_ineligible_github_actions_suite() -> None:
    runs_path = (
        f"repos/tj-agents/example/commits/{HEAD}/check-runs?filter=latest"
        "&per_page=100&page=1"
    )
    statuses_path = (
        f"repos/tj-agents/example/commits/{HEAD}/statuses?per_page=100&page=1"
    )
    suites_path = (
        f"repos/tj-agents/example/commits/{HEAD}/check-suites?per_page=100&page=1"
    )
    first_run_path = (
        f"repos/tj-agents/example/actions/runs?check_suite_id=101&head_sha={HEAD}"
        "&per_page=100&page=1"
    )
    second_run_path = (
        f"repos/tj-agents/example/actions/runs?check_suite_id=102&head_sha={HEAD}"
        "&per_page=100&page=1"
    )
    gh = FakeGitHub(
        {
            runs_path: {
                "check_runs": [
                    {
                        "id": 1,
                        "name": "verify",
                        "head_sha": HEAD,
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"id": 7},
                    }
                ]
            },
            statuses_path: [],
            suites_path: {
                "check_suites": [
                    {
                        "id": 101,
                        "head_sha": HEAD,
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"id": merger.GITHUB_ACTIONS_APP_ID},
                    },
                    {
                        "id": 102,
                        "head_sha": HEAD,
                        "status": "completed",
                        "conclusion": "failure",
                        "app": {"id": merger.GITHUB_ACTIONS_APP_ID},
                    },
                ]
            },
            first_run_path: {
                "workflow_runs": [
                    {
                        "check_suite_id": 101,
                        "head_sha": HEAD,
                        "event": "pull_request",
                        "workflow_id": 1,
                    }
                ]
            },
            second_run_path: {
                "workflow_runs": [
                    {
                        "check_suite_id": 102,
                        "head_sha": HEAD,
                        "event": "workflow_dispatch",
                        "workflow_id": 2,
                    }
                ]
            },
        }
    )
    assert merger.observed_ci_state(gh, "tj-agents/example", HEAD) == (True, True, "")


def test_observed_ci_uses_latest_eligible_suite_per_workflow() -> None:
    prefix = "repos/tj-agents/example"
    runs_path = f"{prefix}/commits/{HEAD}/check-runs?filter=latest&per_page=100&page=1"
    statuses_path = f"{prefix}/commits/{HEAD}/statuses?per_page=100&page=1"
    suites_path = f"{prefix}/commits/{HEAD}/check-suites?per_page=100&page=1"

    def observed(
        suites: list[dict[str, Any]], origins: dict[int, tuple[str, int]]
    ) -> tuple[bool, bool, str]:
        responses: dict[str, Any] = {
            runs_path: {
                "check_runs": [
                    {
                        "id": 1,
                        "name": "verify",
                        "head_sha": HEAD,
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"id": 7},
                    }
                ]
            },
            statuses_path: [],
            suites_path: {"check_suites": suites},
        }
        for suite_id, (event, workflow_id) in origins.items():
            responses[
                f"{prefix}/actions/runs?check_suite_id={suite_id}&head_sha={HEAD}"
                "&per_page=100&page=1"
            ] = {
                "workflow_runs": [
                    {
                        "check_suite_id": suite_id,
                        "head_sha": HEAD,
                        "event": event,
                        "workflow_id": workflow_id,
                    }
                ]
            }
        return cast(
            tuple[bool, bool, str],
            merger.observed_ci_state(FakeGitHub(responses), "tj-agents/example", HEAD),
        )

    def suite(identifier: int, status: str, conclusion: str | None) -> dict[str, Any]:
        return {
            "id": identifier,
            "head_sha": HEAD,
            "status": status,
            "conclusion": conclusion,
            "app": {"id": merger.GITHUB_ACTIONS_APP_ID},
        }

    assert observed(
        [
            suite(101, "completed", "cancelled"),
            suite(102, "completed", "success"),
        ],
        {101: ("pull_request", 123), 102: ("pull_request", 123)},
    ) == (True, True, "")
    assert observed(
        [
            suite(101, "completed", "cancelled"),
            suite(102, "completed", "success"),
            suite(103, "in_progress", None),
        ],
        {
            101: ("pull_request", 123),
            102: ("pull_request", 123),
            103: ("pull_request", 456),
        },
    ) == (False, True, "check suite is pending or failing")
    assert observed(
        [
            suite(101, "completed", "success"),
            suite(102, "completed", "failure"),
        ],
        {101: ("pull_request", 123), 102: ("workflow_dispatch", 123)},
    ) == (True, True, "")


def test_required_test_merge_evidence_blocks_head_fallback() -> None:
    merge = NEW
    merge_runs = (
        f"repos/tj-agents/example/commits/{merge}/check-runs?filter=latest"
        "&per_page=100&page=1"
    )
    merge_statuses = (
        f"repos/tj-agents/example/commits/{merge}/statuses?per_page=100&page=1"
    )
    gh = FakeGitHub(
        {
            merge_runs: {
                "check_runs": [
                    {
                        "id": 1,
                        "name": "failed",
                        "head_sha": merge,
                        "status": "completed",
                        "conclusion": "failure",
                        "app": {"id": 7},
                    }
                ]
            },
            merge_statuses: [],
        }
    )
    pr = {"head": {"sha": HEAD}, "merge_commit_sha": merge}
    assert merger.checks_pass(
        gh,
        "tj-agents/example",
        pr,
        {("missing", 7), ("failed", 7)},
    ) == (False, "required checks are pending or failing")
    assert not any(f"commits/{HEAD}/" in call for call in gh.calls)


def test_empty_required_contexts_fall_back_only_when_test_merge_has_no_evidence() -> (
    None
):
    merge = NEW
    merge_runs = (
        f"repos/tj-agents/example/commits/{merge}/check-runs?filter=latest"
        "&per_page=100&page=1"
    )
    merge_statuses = (
        f"repos/tj-agents/example/commits/{merge}/statuses?per_page=100&page=1"
    )
    merge_suites = (
        f"repos/tj-agents/example/commits/{merge}/check-suites?per_page=100&page=1"
    )
    head_runs = (
        f"repos/tj-agents/example/commits/{HEAD}/check-runs?filter=latest"
        "&per_page=100&page=1"
    )
    head_statuses = (
        f"repos/tj-agents/example/commits/{HEAD}/statuses?per_page=100&page=1"
    )
    head_suites = (
        f"repos/tj-agents/example/commits/{HEAD}/check-suites?per_page=100&page=1"
    )
    pr = {"head": {"sha": HEAD}, "merge_commit_sha": merge}
    fallback = FakeGitHub(
        {
            merge_runs: {"check_runs": []},
            merge_statuses: [],
            merge_suites: {"check_suites": []},
            head_runs: {
                "check_runs": [
                    {
                        "id": 1,
                        "name": "verify",
                        "head_sha": HEAD,
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"id": 7},
                    }
                ]
            },
            head_statuses: [],
            head_suites: {
                "check_suites": [
                    {
                        "id": 2,
                        "head_sha": HEAD,
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"id": 7},
                    }
                ]
            },
        }
    )
    assert merger.checks_pass(fallback, "tj-agents/example", pr, set()) == (True, "")
    pending = FakeGitHub(
        {
            merge_runs: {
                "check_runs": [
                    {
                        "id": 3,
                        "name": "verify",
                        "head_sha": merge,
                        "status": "in_progress",
                        "conclusion": None,
                        "app": {"id": 7},
                    }
                ]
            },
            merge_statuses: [],
            merge_suites: {"check_suites": []},
        }
    )
    assert merger.checks_pass(pending, "tj-agents/example", pr, set()) == (
        False,
        "current check is pending or failing",
    )
    assert not any(f"commits/{HEAD}/" in call for call in pending.calls)


def test_empty_required_contexts_do_not_accept_suite_only_test_merge_evidence() -> None:
    merge = NEW
    runs = (
        f"repos/tj-agents/example/commits/{merge}/check-runs?filter=latest"
        "&per_page=100&page=1"
    )
    statuses = f"repos/tj-agents/example/commits/{merge}/statuses?per_page=100&page=1"
    suites = f"repos/tj-agents/example/commits/{merge}/check-suites?per_page=100&page=1"
    gh = FakeGitHub(
        {
            runs: {"check_runs": []},
            statuses: [],
            suites: {
                "check_suites": [
                    {
                        "id": 1,
                        "head_sha": merge,
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"id": 7},
                    }
                ]
            },
        }
    )
    assert merger.checks_pass(
        gh,
        "tj-agents/example",
        {"head": {"sha": HEAD}, "merge_commit_sha": merge},
        set(),
    ) == (False, "no current check or status evidence")
    assert not any(f"commits/{HEAD}/" in call for call in gh.calls)


def test_base_source_revisions_keeps_unchanged_allowlisted_source_pins() -> None:
    template = "e" * 40
    workflow, workflow_blob = entry(
        "uses: tj-agents/github-actions/.github/actions/check@"
        + OLD
        + "\nuses: tj-agents/template/.github/workflows/plugin-ci.yml@"
        + template
        + "\n"
    )
    gh = FakeGitHub({f"repos/tj-agents/example/git/blobs/{workflow[2]}": workflow_blob})
    assert merger.base_source_revisions(
        gh,
        "tj-agents/example",
        {".github/workflows/ci.yml": workflow},
        [".github/workflows/ci.yml"],
        ["tj-agents/github-actions", "tj-agents/template"],
        {"tj-agents/github-actions": NEW},
    ) == {
        "tj-agents/github-actions": NEW,
        "tj-agents/template": template,
    }
    assert all("repos/tj-agents/template" not in call for call in gh.calls)


def test_replay_accepts_divergent_unchanged_source_pins() -> None:
    template_old_one = "e" * 40
    template_old_two = "f" * 40
    template_current = "9" * 40
    ci, ci_blob = entry(
        "uses: tj-agents/github-actions/.github/actions/check@" + OLD + "\n"
    )
    updated_ci, updated_ci_blob = entry(
        "uses: tj-agents/github-actions/.github/actions/check@" + NEW + "\n"
    )
    template_one, template_one_blob = entry(
        "uses: tj-agents/template/.github/actions/check@" + template_old_one + "\n"
    )
    template_two, template_two_blob = entry(
        "uses: tj-agents/template/.github/actions/check@" + template_old_two + "\n"
    )
    updater, updater_blob = entry(
        "      repositories: tj-agents/github-actions,tj-agents/template\n"
    )
    declaration, declaration_blob = entry(enrollment())
    before = {
        ".github/workflows/ci.yml": ci,
        ".github/workflows/template-one.yml": template_one,
        ".github/workflows/template-two.yml": template_two,
        ".github/workflows/update-pins.yml": updater,
        ".github/update-enrollment.json": declaration,
    }
    after = {**before, ".github/workflows/ci.yml": updated_ci}
    root, github, actions, check = ("1" * 40, "2" * 40, "3" * 40, "4" * 40)
    first_compare = (
        f"repos/tj-agents/template/compare/{template_old_one}...{template_current}"
    )
    second_compare = (
        f"repos/tj-agents/template/compare/{template_old_two}...{template_current}"
    )

    def template_tree(path: str, oid: str) -> dict[str, Any]:
        return {"tree": [{"path": path, "type": "tree", "sha": oid}]}

    responses = (
        trees(before, after)
        | source_responses()
        | {
            f"repos/tj-agents/example/git/blobs/{ci[2]}": ci_blob,
            f"repos/tj-agents/example/git/blobs/{updated_ci[2]}": updated_ci_blob,
            f"repos/tj-agents/example/git/blobs/{template_one[2]}": template_one_blob,
            f"repos/tj-agents/example/git/blobs/{template_two[2]}": template_two_blob,
            f"repos/tj-agents/example/git/blobs/{updater[2]}": updater_blob,
            f"repos/tj-agents/example/git/blobs/{declaration[2]}": declaration_blob,
            "repos/tj-agents/template": {"default_branch": "main"},
            "repos/tj-agents/template/commits/main": {"sha": template_current},
            first_compare: {"status": "ahead"},
            second_compare: {"status": "ahead"},
        }
    )
    for revision in (template_old_one, template_old_two, template_current):
        responses[f"repos/tj-agents/template/commits/{revision}"] = {
            "commit": {"tree": {"sha": root}}
        }
    responses |= {
        f"repos/tj-agents/template/git/trees/{root}": template_tree(".github", github),
        f"repos/tj-agents/template/git/trees/{github}": template_tree(
            "actions", actions
        ),
        f"repos/tj-agents/template/git/trees/{actions}": template_tree("check", check),
    }
    assert merger.replay(
        FakeGitHub(responses), "tj-agents", "tj-agents/example", BASE, HEAD
    )


def test_pull_request_must_be_up_to_date_with_default_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata: dict[str, Any] = {
        "id": 12,
        "full_name": "tj-agents/example",
        "default_branch": "main",
    }
    pr: dict[str, Any] = {
        "number": 4,
        "draft": False,
        "head": {"ref": merger.BRANCH, "sha": HEAD, "repo": {"id": 12}},
        "base": {"ref": "main", "sha": BASE},
        "user": {"id": 99, "type": "Bot"},
    }
    gh = FakeGitHub({"repos/tj-agents/example/commits/main": {"sha": NEW}})
    monkeypatch.setattr(merger.ENROLLMENT, "eligible_repository", lambda *args: True)
    monkeypatch.setattr(merger, "merge_base", lambda *args: BASE)
    monkeypatch.setattr(merger, "replay", lambda *args: True)
    monkeypatch.setattr(merger, "required_contexts", lambda *args: set())
    assert merger.merge_candidate(gh, "tj-agents", "example", metadata, pr, 99) == (
        "waiting",
        "pull request must be up to date with default branch",
    )
    assert not any(call.endswith("/merge") for call in gh.calls)


def test_official_pr_ignores_reviews_but_rejects_foreign_head() -> None:
    repository: dict[str, Any] = {"id": 12, "default_branch": "main"}
    pr: dict[str, Any] = {
        "number": 4,
        "draft": False,
        "head": {"ref": merger.BRANCH, "sha": HEAD, "repo": {"id": 12}},
        "base": {"ref": "main", "sha": BASE},
        "user": {"id": 99, "type": "Bot"},
        "requested_reviewers": [{"id": 1}],
    }
    assert merger.official_pr(pr, repository, 99) == (4, BASE, HEAD)
    foreign = {**pr, "head": {**pr["head"], "repo": {"id": 13}}}
    assert merger.official_pr(foreign, repository, 99) is None


def test_refresh_race_never_reaches_the_merge_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata: dict[str, Any] = {
        "id": 12,
        "full_name": "tj-agents/example",
        "default_branch": "main",
    }
    initial: dict[str, Any] = {
        "number": 4,
        "draft": False,
        "head": {"ref": merger.BRANCH, "sha": HEAD, "repo": {"id": 12}},
        "base": {"ref": "main", "sha": BASE},
        "user": {"id": 99, "type": "Bot"},
    }
    changed = {**initial, "head": {**initial["head"], "sha": NEW}}
    gh = FakeGitHub(
        {
            "repos/tj-agents/example/commits/main": {"sha": BASE},
            "repos/tj-agents/example": metadata,
            "repos/tj-agents/example/pulls/4": changed,
        }
    )
    monkeypatch.setattr(merger.ENROLLMENT, "eligible_repository", lambda *args: True)
    monkeypatch.setattr(merger, "merge_base", lambda *args: BASE)
    monkeypatch.setattr(merger, "replay", lambda *args: True)
    monkeypatch.setattr(merger, "required_contexts", lambda *args: {("verify", None)})
    monkeypatch.setattr(merger, "checks_pass", lambda *args: (True, ""))
    assert merger.merge_candidate(
        gh, "tj-agents", "example", metadata, initial, 99
    ) == ("raced", "pull request changed during admission")
    assert not any(call.endswith("/merge") for call in gh.calls)


def test_merge_candidate_merges_the_verified_head_without_reviews(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata: dict[str, Any] = {
        "id": 12,
        "full_name": "tj-agents/example",
        "default_branch": "main",
    }
    pr: dict[str, Any] = {
        "number": 4,
        "draft": False,
        "head": {"ref": merger.BRANCH, "sha": HEAD, "repo": {"id": 12}},
        "base": {"ref": "main", "sha": BASE},
        "user": {"id": 99, "type": "Bot"},
    }
    gh = FakeGitHub(
        {
            "repos/tj-agents/example/commits/main": {"sha": BASE},
            "repos/tj-agents/example": metadata,
            "repos/tj-agents/example/pulls/4": pr,
            "repos/tj-agents/example/pulls/4/merge": {"merged": True},
        }
    )
    monkeypatch.setattr(merger.ENROLLMENT, "eligible_repository", lambda *args: True)
    monkeypatch.setattr(merger, "merge_base", lambda *args: BASE)
    monkeypatch.setattr(merger, "replay", lambda *args: True)
    monkeypatch.setattr(merger, "required_contexts", lambda *args: {("verify", None)})
    monkeypatch.setattr(merger, "checks_pass", lambda *args: (True, ""))
    assert merger.merge_candidate(gh, "tj-agents", "example", metadata, pr, 99) == (
        "merged",
        None,
    )
    assert "PUT repos/tj-agents/example/pulls/4/merge" in gh.calls
    assert gh.bodies[-1] == {"sha": HEAD, "merge_method": "squash"}


def test_second_readiness_check_prevents_the_merge_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata: dict[str, Any] = {
        "id": 12,
        "full_name": "tj-agents/example",
        "default_branch": "main",
    }
    pr: dict[str, Any] = {
        "number": 4,
        "draft": False,
        "head": {"ref": merger.BRANCH, "sha": HEAD, "repo": {"id": 12}},
        "base": {"ref": "main", "sha": BASE},
        "user": {"id": 99, "type": "Bot"},
    }
    gh = FakeGitHub(
        {
            "repos/tj-agents/example/commits/main": {"sha": BASE},
            "repos/tj-agents/example": metadata,
            "repos/tj-agents/example/pulls/4": pr,
        }
    )
    readiness = iter([(True, ""), (False, "current check is pending or failing")])
    monkeypatch.setattr(merger.ENROLLMENT, "eligible_repository", lambda *args: True)
    monkeypatch.setattr(merger, "merge_base", lambda *args: BASE)
    monkeypatch.setattr(merger, "replay", lambda *args: True)
    monkeypatch.setattr(merger, "required_contexts", lambda *args: {("verify", None)})
    monkeypatch.setattr(merger, "checks_pass", lambda *args: next(readiness))
    assert merger.merge_candidate(gh, "tj-agents", "example", metadata, pr, 99) == (
        "waiting",
        "current check is pending or failing",
    )
    assert not any(call.endswith("/merge") for call in gh.calls)


def test_reconcile_continues_after_one_candidate_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gh = FakeGitHub(
        {
            "users/updater[bot]": {"login": "updater[bot]", "type": "Bot", "id": 99},
            "orgs/tj-agents/repos?type=all&per_page=100&page=1": [
                {
                    "name": "broken",
                    "archived": False,
                    "fork": False,
                    "owner": {"login": "tj-agents"},
                },
                {
                    "name": "healthy",
                    "archived": False,
                    "fork": False,
                    "owner": {"login": "tj-agents"},
                },
            ],
            "repos/tj-agents/broken": {
                "full_name": "tj-agents/broken",
                "default_branch": "main",
            },
            "repos/tj-agents/healthy": {
                "full_name": "tj-agents/healthy",
                "default_branch": "main",
            },
            "repos/tj-agents/broken/pulls?state=open&base=main&per_page=100&page=1": [
                {"number": 1}
            ],
            "repos/tj-agents/healthy/pulls?state=open&base=main&per_page=100&page=1": [
                {"number": 2}
            ],
        }
    )

    def admit(_gh: Any, _owner: str, name: str, *_args: Any) -> tuple[str, str | None]:
        if name == "broken":
            raise merger.MergeError("GitHub request failed")
        return "merged", None

    monkeypatch.setattr(merger, "merge_candidate", admit)
    assert merger.reconcile(gh, "tj-agents", "updater") == {
        "merged": 1,
        "waiting": 0,
        "skipped": 0,
        "raced": 0,
        "errors": 1,
        "diagnostics": ["tj-agents/broken#1: GitHub request failed"],
    }


def test_main_fails_when_reconcile_reports_api_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(merger, "reconcile", lambda *_args: {"errors": 1})
    assert merger.main(["--owner", "tj-agents", "--updater-app-slug", "updater"]) == 1


@pytest.mark.parametrize("slug", ["updater", "updater-2"])
def test_updater_identity_requires_immutable_bot_id(slug: str) -> None:
    gh = FakeGitHub(
        {f"users/{slug}[bot]": {"login": f"{slug}[bot]", "type": "Bot", "id": 42}}
    )
    assert merger.updater_identity(gh, slug) == 42
