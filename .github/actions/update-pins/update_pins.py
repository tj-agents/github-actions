import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
from urllib.parse import quote


REPOSITORY = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9_.-]{1,100}")
SHA = re.compile(r"[0-9a-f]{40}")
USES = re.compile(r"(?P<prefix>[ \t]*(?:-[ \t]+)?uses:[ \t]*)(?P<quote>['\"]?)(?P<repository>[A-Za-z0-9][A-Za-z0-9.-]*/[A-Za-z0-9_.-]+)(?P<subpath>/[A-Za-z0-9._/-]+)?@(?P<sha>[0-9a-fA-F]{40})(?P=quote)(?P<suffix>[ \t]*(?:#.*)?)(?P<ending>\r?)")
PROPERTIES = r"(?:[&!][^ \t\r\n]*[ \t]+)*"
SCALAR = re.compile(r"^[ \t]*(?:-[ \t]+)?[^:\r\n]+:[ \t]*" + PROPERTIES + r"[ \t]*[>|](?:[+-]?\d?|\d?[+-]?)[ \t]*(?:#.*)?\r?$")
QUOTED = re.compile(r"^[ \t]*(?:-[ \t]+)?[^:\r\n]+:[ \t]*" + PROPERTIES + r"[ \t]*(?P<quote>['\"])(?P<value>.*)\r?$")


def parse_repositories(value):
    repositories = []
    for repository in re.split(r"[,\n]", value):
        repository = repository.strip()
        if not repository:
            continue
        if not REPOSITORY.fullmatch(repository):
            raise ValueError("invalid repository")
        if repository.lower() not in {item.lower() for item in repositories}:
            repositories.append(repository)
    if not repositories:
        raise ValueError("at least one repository is required")
    return repositories


def command(arguments):
    return subprocess.run(arguments, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)


def resolve_repository(repository, run=command):
    try:
        branch = run(["gh", "api", f"repos/{repository}", "--jq", ".default_branch"]).stdout.strip()
        if not branch or "\x00" in branch:
            raise ValueError
        revision = run(["gh", "api", f"repos/{repository}/commits/{quote(branch, safe='')}", "--jq", ".sha"]).stdout.strip()
    except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise ValueError("repository lookup failed") from None
    if not SHA.fullmatch(revision):
        raise ValueError("repository lookup failed")
    return revision


def compare_revisions(repository, before, after, run=command):
    try:
        status = run(["gh", "api", f"repos/{repository}/compare/{before}...{after}", "--jq", ".status"]).stdout.strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise ValueError("repository comparison failed") from None
    if status not in {"ahead", "identical"}:
        raise ValueError("non-forward repository update")


def tracked_files(project, run=command):
    try:
        result = run(["git", "-C", str(project), "ls-files", "-z", "--", ".github"])
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise ValueError("tracked file lookup failed") from None
    return [item for item in result.stdout.split("\0") if item.endswith((".yml", ".yaml"))]


def read_file(root, relative):
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or not relative.startswith(".github/"):
        raise ValueError("unsafe tracked file")
    target = root.joinpath(*path.parts)
    current = root
    for part in path.parts:
        current = current / part
        if os.path.islink(current):
            raise ValueError("unsafe tracked file")
    try:
        target.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (FileNotFoundError, ValueError):
        raise ValueError("unsafe tracked file") from None
    with target.open("r", encoding="utf-8", newline="") as handle:
        return target, handle.read()


def closes_quote(value, quote):
    if quote == "'":
        index = 0
        while index < len(value):
            if value[index] == "'":
                if index + 1 < len(value) and value[index + 1] == "'":
                    index += 2
                    continue
                return True
            index += 1
        return False
    escaped = False
    for character in value:
        if character == '"' and not escaped:
            return True
        escaped = character == "\\" and not escaped
        if character != "\\":
            escaped = False
    return False


def reference_matches(content):
    position = 0
    scalar_indent = None
    quote = None
    for line in content.splitlines(keepends=True):
        text = line[:-1] if line.endswith("\n") else line
        indent = len(text) - len(text.lstrip(" \t"))
        if scalar_indent is not None:
            if text.strip(" \t\r") and indent <= scalar_indent:
                scalar_indent = None
            else:
                position += len(line)
                continue
        if quote is not None:
            if closes_quote(text, quote):
                quote = None
            position += len(line)
            continue
        if text.lstrip(" \t").startswith("#"):
            position += len(line)
            continue
        if SCALAR.fullmatch(text):
            sequence = re.match(r"^[ \t]*-[ \t]+", text)
            scalar_indent = len(sequence.group(0)) if sequence is not None else indent
            position += len(line)
            continue
        quoted = QUOTED.fullmatch(text)
        if quoted is not None and not closes_quote(quoted.group("value"), quoted.group("quote")):
            quote = quoted.group("quote")
            position += len(line)
            continue
        match = USES.fullmatch(text)
        if match is not None:
            yield position, position + len(text), match
        position += len(line)


def replacement(match, revisions):
    revision = revisions.get(match.group("repository").lower())
    if revision is None or revision == match.group("sha").lower():
        return match.group(0)
    return "".join((match.group("prefix"), match.group("quote"), match.group("repository"), match.group("subpath") or "", "@", revision, match.group("quote"), match.group("suffix"), match.group("ending")))


def replace_references(content, revisions):
    output = []
    position = 0
    for start, end, match in reference_matches(content):
        output.extend((content[position:start], replacement(match, revisions)))
        position = end
    output.append(content[position:])
    return "".join(output)


def pending_comparisons(content, revisions):
    comparisons = set()
    for _, _, match in reference_matches(content):
        candidate = revisions.get(match.group("repository").lower())
        before = match.group("sha").lower()
        if candidate and candidate != before:
            comparisons.add((match.group("repository").lower(), before, candidate))
    return comparisons


def update(project, repositories, check=False, files=None, resolver=resolve_repository, comparer=compare_revisions):
    root = Path(project).resolve()
    if not root.is_dir():
        raise ValueError("project is not a directory")
    documents = [read_file(root, relative) for relative in (tracked_files(root) if files is None else files)]
    revisions = {repository.lower(): resolver(repository) for repository in repositories}
    proposals = [(path, content, replace_references(content, revisions)) for path, content in documents]
    comparisons = set()
    for _, original, _ in proposals:
        comparisons.update(pending_comparisons(original, revisions))
    for repository, before, after in sorted(comparisons):
        comparer(repository, before, after)
    changed = [(path, updated) for path, original, updated in proposals if updated != original]
    if changed and not check:
        for path, content in changed:
            if os.path.islink(path):
                raise ValueError("unsafe tracked file")
            with path.open("w", encoding="utf-8", newline="") as handle:
                handle.write(content)
    return {"changed": bool(changed), "files": len(changed), "repositories": repositories[:20]}


def write_outputs(summary):
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8", newline="") as handle:
            handle.write("changed=" + str(summary["changed"]).lower() + "\n")
            handle.write("summary=" + json.dumps(summary, separators=(",", ":")) + "\n")


def main(arguments=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--repositories", required=True)
    parser.add_argument("--check", action="store_true")
    values = parser.parse_args(arguments)
    try:
        summary = update(values.project, parse_repositories(values.repositories), values.check)
    except ValueError as error:
        print("error: " + str(error))
        return 1
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        print("error: update failed")
        return 1
    write_outputs(summary)
    print(json.dumps(summary, separators=(",", ":")))
    return int(values.check and summary["changed"])


if __name__ == "__main__":
    raise SystemExit(main())
