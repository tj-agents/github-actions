from __future__ import annotations

import textwrap
from pathlib import Path
from unittest import mock

import pytest

WORKFLOW = (
    Path(__file__).resolve().parents[2] / ".github/workflows/renovate-acceptance.yml"
)


def exercise(
    label: str,
    head: str = "renovate/non-major-dependencies",
    *,
    repository: str = "tj-agents/github-actions",
) -> tuple[object, list[object]]:
    script = textwrap.dedent(WORKFLOW.read_text(encoding="utf-8").split("run: |\n")[1])
    environment = {
        "GITHUB_REPOSITORY": "tj-agents/github-actions",
        "HEAD_REPOSITORY": repository,
        "HEAD_REF": head,
        "ACCEPTANCE_LABEL": label,
    }
    with (
        mock.patch.dict("os.environ", environment, clear=True),
        mock.patch("time.sleep") as sleep,
        pytest.raises(SystemExit) as result,
    ):
        exec(compile(script, str(WORKFLOW), "exec"), {})
    return result.value.code, list(sleep.call_args_list)


def test_acceptance_runs_as_a_pr_check_without_checkout_or_write_access() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "  pull_request:\n    types: [labeled]" in workflow
    assert "workflow_dispatch" not in workflow
    assert "pull_request_target" not in workflow
    assert "    name: Renovate acceptance\n" in workflow
    assert "permissions:\n  contents: read\n" in workflow
    assert "timeout-minutes: 5" in workflow
    assert "uses:" not in workflow
    assert "secrets." not in workflow
    assert "    if:" not in workflow
    assert "${{" not in workflow.split("run: |\n")[1]


def test_only_explicit_pass_succeeds() -> None:
    assert exercise("renovate-acceptance:pass") == (0, [])


@pytest.mark.parametrize("label", ["renovate-acceptance:fail", "", "unrelated", "pass"])
def test_failure_and_unknown_labels_fail_closed(label: str) -> None:
    code, waits = exercise(label)
    assert isinstance(code, str)
    assert waits == []


def test_pending_stays_running_for_a_bounded_window_and_never_succeeds() -> None:
    code, waits = exercise("renovate-acceptance:pending")
    assert isinstance(code, str)
    assert waits == [mock.call(180)]


@pytest.mark.parametrize("head", ["main", "feature/renovate", "renovate-other/dep"])
def test_other_branches_cannot_succeed(head: str) -> None:
    code, waits = exercise("renovate-acceptance:pass", head)
    assert code == "Expected an in-repository Renovate pull request"
    assert waits == []


def test_fork_cannot_succeed() -> None:
    code, waits = exercise("renovate-acceptance:pass", repository="fork/github-actions")
    assert code == "Expected an in-repository Renovate pull request"
    assert waits == []
