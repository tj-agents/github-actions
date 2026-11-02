import json
import os
import re
import urllib.request
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any
from urllib.parse import quote

REPOSITORY = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9_.-]{1,100}"
)


def validate_repository(repository: str) -> None:
    if not REPOSITORY.fullmatch(repository):
        raise ValueError("invalid repository")


def hint(
    event: dict[str, Any], repository: str, changed: Iterable[str] | None = None
) -> dict[str, Any] | None:
    validate_repository(repository)
    repository_data = event.get("repository")
    if not isinstance(repository_data, dict):
        return None
    default_branch = repository_data.get("default_branch")
    if not isinstance(default_branch, str) or not default_branch:
        return None
    run = event.get("workflow_run", {})
    if (
        not isinstance(run, dict)
        or run.get("name") != "ci"
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
        or run.get("event") != "push"
        or run.get("head_branch") != default_branch
        or (run.get("head_repository") or {}).get("full_name") != repository
        or not re.fullmatch(r"[0-9a-f]{40}", run.get("head_sha", ""))
    ):
        return None
    # workflow_run does not retain the original push's before SHA. Include every
    # category when the unpublished range is unknown; consumers re-read source.
    paths = (
        set(changed)
        if changed is not None
        else {"plugins/", ".github/merge-policy.json"}
    )
    changes = ["repository"]
    if ".github/merge-policy.json" in paths:
        changes.append("merge-policy")
    if any(
        path.startswith(("plugins/", ".agents/", ".claude-plugin/", ".codex-plugin/"))
        for path in paths
    ):
        changes.append("marketplace")
    return {"v": 1, "repo": repository, "sha": run["head_sha"], "changes": changes}


def verified_revision(
    event: dict[str, Any],
    repository: str,
    token: str,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, str] | None:
    if hint(event, repository) is None:
        return None
    branch = event["repository"]["default_branch"]
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/commits/{quote(branch, safe='')}",
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
        },
    )
    with opener(request, timeout=20) as response:
        commit = json.loads(response.read(1048576))
    revision = event["workflow_run"]["head_sha"]
    if commit.get("sha") != revision:
        return None
    return {"after": revision}


def publish(
    topic: str,
    message: dict[str, Any],
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", topic):
        raise ValueError("UPDATE_TOPIC must be an unguessable 32-128 character topic")
    request = urllib.request.Request(
        "https://ntfy.sh/" + topic,
        data=json.dumps(message).encode("utf-8"),
        headers={"Content-Type": "text/plain", "X-Firebase": "no"},
        method="POST",
    )
    with opener(request, timeout=20) as response:
        response.read(4096)


def main() -> int:
    event = json.loads(
        Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8")
    )
    repository = os.environ["GITHUB_REPOSITORY"]
    validate_repository(repository)
    token = os.environ["GH_TOKEN"]
    revision = verified_revision(event, repository, token)
    message = hint(event, repository) if revision is not None else None
    if message is not None:
        publish(os.environ["UPDATE_TOPIC"], message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
