"""Render the shared event publisher caller for any repository (Python 3.9+)."""

import argparse
from pathlib import Path
import re


def render(revision):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("publisher revision must be a full commit SHA")
    return f"""name: machine-events
on:
  push:
    branches: [main]
  workflow_run:
    workflows: [ci, CI]
    types: [completed]
    branches: [main]
permissions:
  contents: read
concurrency:
  group: machine-events-${{{{ github.ref }}}}
  cancel-in-progress: false
jobs:
  publish:
    if: vars.MACHINE_EVENTS_TOPIC != '' && (github.event_name == 'push' || (github.event.workflow_run.event == 'push' && github.event.workflow_run.conclusion == 'success' && github.event.workflow_run.head_repository.full_name == github.repository))
    runs-on: ubuntu-latest
    timeout-minutes: 2
    steps:
      - name: Publish repository hint
        uses: tj-agents/github-actions/.github/actions/machine-events@{revision}
        with:
          topic: ${{{{ vars.MACHINE_EVENTS_TOPIC }}}}
          published: ${{{{ github.event_name == 'workflow_run' }}}}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--project", type=Path)
    arguments = parser.parse_args()
    content = render(arguments.revision)
    if arguments.project:
        path = arguments.project / ".github/workflows/machine-events.yml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    else:
        print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
