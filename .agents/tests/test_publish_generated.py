"""Tests for safe publication of generated files."""

from __future__ import annotations

import base64
import importlib.util
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/actions/publish-generated/publish_generated.py"
spec = importlib.util.spec_from_file_location("publish_generated", SCRIPT)
assert spec is not None and spec.loader is not None
publish = cast(Any, importlib.util.module_from_spec(spec))
spec.loader.exec_module(publish)


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def repository(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "--initial-branch=main")
    git(root, "config", "user.name", "test")
    git(root, "config", "user.email", "test@example.invalid")
    (root / "generated").mkdir()
    (root / "generated/file.txt").write_text("old\n", encoding="utf-8")
    (root / "untouched.txt").write_text("old\n", encoding="utf-8")
    git(root, "add", "--all")
    git(root, "commit", "-m", "source")
    return root, git(root, "rev-parse", "HEAD")


def call(root: Path, source: str, **overrides: str) -> str:
    values: dict[str, str] = {
        "event": "push",
        "ref": "refs/heads/main",
        "repository": "owner/project",
        "current_repository": "owner/project",
        "source_sha": source,
        "event_sha": source,
        "branch": "main",
        "token": "secret-token",
        "paths": "generated",
    }
    values.update(overrides)
    return cast(str, publish.publish(**values))


@pytest.mark.parametrize(
    "value",
    [
        "",
        ".",
        "./",
        "../outside",
        ".git/config",
        "generated/*.txt",
        "generated\\file.txt",
        "-option",
        "generated\n../outside",
    ],
)
def test_paths_must_be_explicit_safe_relative_paths(value: str) -> None:
    with pytest.raises(publish.PublishError):
        publish.validate_paths(value)


def test_rejects_non_push_wrong_ref_repository_or_source_before_git_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, source = repository(tmp_path)
    monkeypatch.chdir(root)

    def unexpected(*_: Any, **__: Any) -> Any:
        raise AssertionError("invalid invocation reached a git write")

    monkeypatch.setattr(publish, "_run", unexpected)
    for values in (
        {"event": "pull_request"},
        {"ref": "refs/tags/v1"},
        {"repository": "other/project"},
        {"event_sha": "f" * 40},
    ):
        with pytest.raises(publish.PublishError):
            call(root, source, **values)


def test_existing_staged_changes_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, source = repository(tmp_path)
    monkeypatch.chdir(root)
    (root / "untouched.txt").write_text("staged\n", encoding="utf-8")
    git(root, "add", "untouched.txt")

    with pytest.raises(publish.PublishError, match="pre-staged"):
        call(root, source)
    assert git(root, "diff", "--cached", "--name-only") == "untouched.txt"


def test_stale_remote_skips_without_staging_or_changing_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, source = repository(tmp_path)
    monkeypatch.chdir(root)
    monkeypatch.setattr(publish, "_remote_head", lambda *_: "f" * 40)
    (root / "generated/file.txt").write_text("new\n", encoding="utf-8")

    assert call(root, source) == "stale"
    assert not git(root, "diff", "--cached", "--name-only")
    assert git(root, "diff", "--name-only") == "generated/file.txt"


def test_unchanged_generated_tree_is_a_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, source = repository(tmp_path)
    monkeypatch.chdir(root)
    monkeypatch.setattr(publish, "_remote_head", lambda *_: source)

    assert call(root, source) == "unchanged"
    assert git(root, "rev-parse", "HEAD") == source
    assert not git(root, "diff", "--cached", "--name-only")


def test_only_allowlisted_output_is_committed_and_successful_push_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, source = repository(tmp_path)
    monkeypatch.chdir(root)
    state = {"remote": source}
    monkeypatch.setattr(publish, "_remote_head", lambda *_: state["remote"])
    original = publish._run
    remote_environment: list[dict[str, str]] = []

    def run(arguments: Any, **kwargs: Any) -> Any:
        if arguments[0] == "push":
            remote_environment.append(kwargs["environment"])
            state["remote"] = git(root, "rev-parse", "HEAD")
            return subprocess.CompletedProcess(["git", *arguments], 0, "", "")
        return original(arguments, **kwargs)

    monkeypatch.setattr(publish, "_run", run)
    (root / "generated/file.txt").write_text("new\n", encoding="utf-8")
    (root / "untouched.txt").write_text("unrelated\n", encoding="utf-8")

    assert call(root, source) == "published"
    assert (
        git(root, "show", "--pretty=format:", "--name-only", "HEAD")
        == "generated/file.txt"
    )
    assert git(root, "diff", "--name-only") == "untouched.txt"
    assert len(remote_environment) == 1
    assert "PUBLISH_TOKEN" not in remote_environment[0]
    credential = remote_environment[0]["GIT_CONFIG_VALUE_0"].split("basic ", 1)[1]
    assert base64.b64decode(credential).decode() == "x-access-token:secret-token"
    assert remote_environment[0]["GIT_CONFIG_KEY_0"].startswith(
        "http.https://github.com/"
    )


@pytest.mark.parametrize("advance_remote", [True, False])
def test_failed_push_is_stale_only_if_remote_advanced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, advance_remote: bool
) -> None:
    root, source = repository(tmp_path)
    monkeypatch.chdir(root)
    state = {"remote": source}
    monkeypatch.setattr(publish, "_remote_head", lambda *_: state["remote"])
    original = publish._run

    def run(arguments: Any, **kwargs: Any) -> Any:
        if arguments[0] == "push":
            if advance_remote:
                state["remote"] = "f" * 40
            return subprocess.CompletedProcess(["git", *arguments], 1, "", "denied")
        return original(arguments, **kwargs)

    monkeypatch.setattr(publish, "_run", run)
    (root / "generated/file.txt").write_text("new\n", encoding="utf-8")

    if advance_remote:
        assert call(root, source) == "stale"
    else:
        with pytest.raises(publish.PublishError, match="could not be published"):
            call(root, source)
