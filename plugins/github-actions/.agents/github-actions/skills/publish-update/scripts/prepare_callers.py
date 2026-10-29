import argparse
import json
from pathlib import Path
import re

from caller import render


def prepare(repositories, revision, output):
    content = render(revision)
    written = []
    for item in repositories:
        repository = item["nameWithOwner"]
        if item.get("isArchived") or item.get("isFork"):
            continue
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9_.-]{1,100}", repository):
            raise ValueError("invalid repository in inventory")
        path = Path(output) / repository / ".github/workflows/publish-update.yml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        written.append(repository)
    return written


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    repositories = json.loads(arguments.inventory.read_text(encoding="utf-8"))
    written = prepare(repositories, arguments.revision, arguments.output)
    print(f"Prepared {len(written)} repository callers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
