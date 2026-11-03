"""Commit an explicit generated-file allowlist to its current default branch."""

from __future__ import annotations

import base64
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath

SHA = re.compile(r"[0-9a-f]{40}")
REPOSITORY = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9_.-]{1,100}"
)
BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}")


class PublishError(Exception):
    """A safe-to-report publication failure."""


def validate_paths(value: str) -> list[str]:
    paths: list[str] = []
    for raw in value.splitlines():
        path = raw.strip()
        parsed = PurePosixPath(path)
        if (
            not path
            or parsed == PurePosixPath(".")
            or parsed.is_absolute()
            or ".." in parsed.parts
            or any(part.casefold() == ".git" for part in parsed.parts)
            or any(character in path for character in "*?[]\\\x00")
            or any(ord(character) < 32 for character in path)
            or not re.fullmatch(r"[A-Za-z0-9._/-]+", path)
        ):
            raise PublishError("generated paths must be explicit safe relative paths")
        if path.startswith("-") or any(part.startswith("-") for part in parsed.parts):
            raise PublishError("generated paths cannot begin with an option marker")
        normalized = parsed.as_posix()
        if normalized not in paths:
            paths.append(normalized)
    if not paths:
        raise PublishError("at least one generated path is required")
    return paths


def _run(
    arguments: Sequence[str],
    *,
    environment: Mapping[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    command_environment = (
        dict(environment) if environment is not None else os.environ.copy()
    )
    command_environment.pop("PUBLISH_TOKEN", None)
    try:
        result = subprocess.run(
            ["git", *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=command_environment,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PublishError("git publication command could not complete") from error
    if check and result.returncode:
        raise PublishError("git publication command failed")
    return result


def _remote_environment(token: str) -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PUBLISH_TOKEN", None)
    credential = base64.b64encode(f"x-access-token:{token}".encode()).decode("ascii")
    # Git reads this transient configuration from its environment. The token is
    # never placed in argv, the remote URL, a credential helper, or repository config.
    environment["GIT_CONFIG_COUNT"] = "1"
    environment["GIT_CONFIG_KEY_0"] = "http.https://github.com/.extraheader"
    environment["GIT_CONFIG_VALUE_0"] = f"AUTHORIZATION: basic {credential}"
    return environment


def _remote_head(url: str, branch: str, token: str) -> str:
    result = _run(
        ["ls-remote", "--exit-code", url, f"refs/heads/{branch}"],
        environment=_remote_environment(token),
        check=False,
    )
    if result.returncode:
        raise PublishError("could not verify the repository default branch")
    rows = result.stdout.splitlines()
    if len(rows) != 1:
        raise PublishError("repository default branch lookup was ambiguous")
    revision, ref = rows[0].split("\t", 1)
    if ref != f"refs/heads/{branch}" or not SHA.fullmatch(revision):
        raise PublishError("repository default branch returned an invalid revision")
    return revision


def _emit(published: bool, reason: str) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"published={'true' if published else 'false'}\n")
            handle.write(f"result={reason}\n")


def publish(
    *,
    event: str,
    ref: str,
    repository: str,
    current_repository: str,
    source_sha: str,
    event_sha: str,
    branch: str,
    token: str,
    paths: str,
) -> str:
    if event != "push":
        raise PublishError("publication is allowed only for a default-branch push")
    if (
        not REPOSITORY.fullmatch(repository)
        or repository.casefold() != current_repository.casefold()
    ):
        raise PublishError(
            "repository input does not match the current workflow repository"
        )
    if not SHA.fullmatch(source_sha) or event_sha != source_sha:
        raise PublishError("source SHA does not match the triggering push")
    if not BRANCH.fullmatch(branch) or any(char in branch for char in "*?[]"):
        raise PublishError("invalid default branch")
    if ref != f"refs/heads/{branch}":
        raise PublishError("publication ref is not the repository default branch")
    if not token:
        raise PublishError("repository publication token is missing")
    allowed = validate_paths(paths)
    head = _run(["rev-parse", "HEAD"]).stdout.strip()
    if head != source_sha:
        raise PublishError("checked-out source is not the triggering commit")
    staged = _run(["diff", "--cached", "--quiet"], check=False)
    if staged.returncode == 1:
        raise PublishError("refusing to publish with pre-staged changes")
    if staged.returncode:
        raise PublishError("could not inspect staged changes")

    url = f"https://github.com/{repository}.git"
    if _remote_head(url, branch, token) != source_sha:
        _emit(False, "stale")
        return "stale"

    _run(["add", "--", *allowed])
    changed = _run(["diff", "--cached", "--quiet"], check=False)
    if changed.returncode == 0:
        _emit(False, "unchanged")
        return "unchanged"
    if changed.returncode != 1:
        raise PublishError("could not inspect generated changes")

    staged_paths = _run(["diff", "--cached", "--name-only", "-z"]).stdout.split("\0")
    staged_paths = [path for path in staged_paths if path]
    if any(
        not any(
            path == root or path.startswith(root.rstrip("/") + "/") for root in allowed
        )
        for path in staged_paths
    ):
        raise PublishError("staged output exceeded its generated path allowlist")

    _run(["config", "user.name", "github-actions[bot]"])
    _run(
        [
            "config",
            "user.email",
            "41898282+github-actions[bot]@users.noreply.github.com",
        ]
    )
    _run(["commit", "-m", f"Regenerate packages for {source_sha}"])
    pushed = _run(
        ["push", url, f"HEAD:refs/heads/{branch}"],
        environment=_remote_environment(token),
        check=False,
    )
    if pushed.returncode:
        latest = _remote_head(url, branch, token)
        if latest != source_sha:
            _emit(False, "stale")
            return "stale"
        raise PublishError("generated files could not be published")
    _emit(True, "published")
    return "published"


def main() -> int:
    try:
        result = publish(
            event=os.environ.get("GITHUB_EVENT_NAME", ""),
            ref=os.environ.get("GITHUB_REF", ""),
            repository=os.environ.get("PUBLISH_REPOSITORY", ""),
            current_repository=os.environ.get("GITHUB_REPOSITORY", ""),
            source_sha=os.environ.get("PUBLISH_SOURCE_SHA", ""),
            event_sha=os.environ.get("GITHUB_SHA", ""),
            branch=os.environ.get("PUBLISH_BRANCH", ""),
            token=os.environ.get("PUBLISH_TOKEN", ""),
            paths=os.environ.get("PUBLISH_PATHS", ""),
        )
    except PublishError as error:
        print(f"publish-generated: {error}", file=sys.stderr)
        return 1
    print(f"publish-generated: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
