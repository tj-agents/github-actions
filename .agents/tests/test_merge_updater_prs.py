import base64
import importlib.util
from pathlib import Path
from typing import Any

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

    def api(self, path: str, method: str = "GET", body: Any = None) -> Any:
        self.calls.append(f"{method} {path}")
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
    runs, statuses = merger.check_records(gh, "tj-agents/example", HEAD)
    assert len(runs) == 100
    assert statuses == [{"context": "ok", "state": "success"}]
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
    assert merger.observed_ci_state(accepted, "tj-agents/example", HEAD) == (True, "")


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


@pytest.mark.parametrize("slug", ["updater", "updater-2"])
def test_updater_identity_requires_immutable_bot_id(slug: str) -> None:
    gh = FakeGitHub(
        {f"users/{slug}[bot]": {"login": f"{slug}[bot]", "type": "Bot", "id": 42}}
    )
    assert merger.updater_identity(gh, slug) == 42
