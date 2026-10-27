import argparse
from pathlib import Path
import re


def render(revision):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("publisher revision must be a full commit SHA")
    return f"""name: Publish update
on:
  push:
permissions:
  contents: read
jobs:
  publish:
    uses: tj-agents/github-actions/.github/workflows/publish-update.yml@{revision}
    secrets:
      UPDATE_TOPIC: ${{{{ secrets.UPDATE_TOPIC }}}}
"""


def render_updater(revision, repositories):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("publisher revision must be a full commit SHA")
    values = []
    identities = set()
    for repository in re.split(r"[,\n]", repositories):
        repository = repository.strip()
        if not repository:
            continue
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9_.-]{1,100}", repository):
            raise ValueError("invalid repository")
        if repository.lower() not in identities:
            values.append(repository)
            identities.add(repository.lower())
    if not values:
        raise ValueError("at least one repository is required")
    return f"""name: Update shared action pins
on:
  schedule:
    - cron: '17 */6 * * *'
  workflow_dispatch:
permissions:
  contents: read
jobs:
  update:
    uses: tj-agents/github-actions/.github/workflows/update-pins.yml@{revision}
    with:
      repositories: {','.join(values)}
    secrets:
      UPDATE_APP_PRIVATE_KEY: ${{{{ secrets.UPDATE_APP_PRIVATE_KEY }}}}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--updater", action="store_true")
    parser.add_argument("--repositories")
    arguments = parser.parse_args()
    if arguments.updater:
        if arguments.repositories is None:
            parser.error("--repositories is required with --updater")
        content = render_updater(arguments.revision, arguments.repositories)
        filename = "update-pins.yml"
    else:
        content = render(arguments.revision)
        filename = "publish-update.yml"
    if arguments.project:
        path = arguments.project / ".github/workflows" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    else:
        print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
