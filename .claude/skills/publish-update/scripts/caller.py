import argparse
import re
from pathlib import Path


def render(revision: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("publisher revision must be a full commit SHA")
    workflow = "tj-agents/github-actions/.github/workflows/publish-update.yml"
    return f"""name: Publish update
on:
  workflow_run:
    workflows: [ci]
    types: [completed]
permissions:
  contents: read
jobs:
  publish:
    uses: {workflow}@{revision} # main
    secrets:
      UPDATE_TOPIC: ${{{{ secrets.UPDATE_TOPIC }}}}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--project", type=Path)
    arguments = parser.parse_args()
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
