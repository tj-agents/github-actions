"""Publish a non-authoritative main-branch hint (Python 3.9+)."""

import json
import os
from pathlib import Path
import re
import urllib.request


def hint(event, repository, changed=None):
    if not re.fullmatch(r"(?:tj-agents|Concertable|tomjseery)/[A-Za-z0-9_.-]+", repository, re.I):
        raise ValueError("unsupported repository")
    if event.get("deleted") or event.get("ref") != "refs/heads/main":
        return None
    paths = {path for commit in event.get("commits", [])
             for kind in ("added", "modified", "removed") for path in commit.get(kind, [])}
    if changed is not None:
        paths = set(changed)
    changes = ["repository"]
    if ".github/merge-policy.json" in paths:
        changes.append("merge-policy")
    if any(path.startswith(("plugins/", ".agents/", ".claude-plugin/", ".codex-plugin/")) for path in paths):
        changes.append("marketplace")
    return {"v": 1, "repo": repository, "changes": changes}


def publish(topic, message, opener=urllib.request.urlopen):
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", topic):
        raise ValueError("MACHINE_EVENTS_TOPIC must be an unguessable 32-128 character topic")
    request = urllib.request.Request("https://ntfy.sh/" + topic,
                                     data=json.dumps(message).encode("utf-8"),
                                     headers={"Content-Type": "text/plain", "X-Firebase": "no"}, method="POST")
    with opener(request, timeout=20) as response:
        response.read(4096)


def changed_paths(event, repository, token, opener=urllib.request.urlopen):
    before, after = event.get("before", ""), event.get("after", "")
    if not all(re.fullmatch(r"[0-9a-f]{40}", revision) for revision in (before, after)):
        return None
    request = urllib.request.Request(f"https://api.github.com/repos/{repository}/compare/{before}...{after}",
                                     headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"})
    try:
        with opener(request, timeout=20) as response:
            result = json.loads(response.read(4194304))
        files = result.get("files", [])
        if len(files) >= 300:
            return ["plugins/", ".github/merge-policy.json"]
        return [item["filename"] for item in files]
    except (OSError, ValueError, KeyError):
        return ["plugins/", ".github/merge-policy.json"]


def main():
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    repository = os.environ["GITHUB_REPOSITORY"]
    message = hint(event, repository)
    if message is not None and os.environ.get("GH_TOKEN"):
        message = hint(event, repository, changed_paths(event, repository, os.environ["GH_TOKEN"]))
    if os.environ.get("MACHINE_EVENTS_PUBLISHED") == "true":
        message = {"v": 1, "repo": os.environ["GITHUB_REPOSITORY"], "changes": ["marketplace"]}
    if message is not None:
        publish(os.environ["MACHINE_EVENTS_TOPIC"], message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
