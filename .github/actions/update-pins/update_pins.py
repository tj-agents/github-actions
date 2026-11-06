import argparse
import importlib.util
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
CONTENT_QUERY = "query($owner:String!,$name:String!,$before:String!,$after:String!){repository(owner:$owner,name:$name){before:object(expression:$before){oid __typename} after:object(expression:$after){oid __typename}}}"


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


def compare_contents(repository, subpath, before, after, run=command):
    try:
        owner, name = repository.split("/", 1)
        path = subpath.removeprefix("/")
        if not REPOSITORY.fullmatch(repository) or not SHA.fullmatch(before) or not SHA.fullmatch(after):
            raise ValueError
        result = run([
            "gh", "api", "graphql",
            "-f", "query=" + CONTENT_QUERY,
            "-f", "owner=" + owner,
            "-f", "name=" + name,
            "-f", "before=" + before + ":" + path,
            "-f", "after=" + after + ":" + path,
        ])
        response = json.loads(result.stdout)
        if response.get("errors"):
            raise ValueError
        objects = response["data"]["repository"]
        old = objects["before"]
        new = objects["after"]
        if (
            old is None or new is None
            or old.get("__typename") not in {"Tree", "Blob"}
            or new.get("__typename") not in {"Tree", "Blob"}
            or not isinstance(old.get("oid"), str) or not SHA.fullmatch(old["oid"])
            or not isinstance(new.get("oid"), str) or not SHA.fullmatch(new["oid"])
        ):
            raise ValueError
    except (OSError, ValueError, KeyError, TypeError, AttributeError, json.JSONDecodeError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise ValueError("content comparison failed") from None
    return old["oid"] != new["oid"]


def tracked_files(project, run=command):
    try:
        result = run(["git", "-C", str(project), "ls-files", "-z", "--", ".github"])
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise ValueError("tracked file lookup failed") from None
    return [item for item in result.stdout.split("\0") if item.endswith((".yml", ".yaml"))]


def read_file(root, relative):
    if not relative.startswith(".github/"):
        raise ValueError("unsafe tracked file")
    return _read_project_file(root, relative)


def read_declaration(root, relative):
    if relative not in {".agents/plugins/template.json", ".github/update-enrollment.json"}:
        raise ValueError("unsafe enrollment declaration")
    return _read_project_file(root, relative)


def _read_project_file(root, relative):
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts:
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
    revision = revisions.get((match.group("repository").lower(), match.group("subpath") or "", match.group("sha").lower()))
    if revision is None:
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
            comparisons.add((match.group("repository").lower(), match.group("subpath") or "", before, candidate))
    return comparisons


def generated_publisher(path: Path, content: str, revisions: dict[str, str]) -> str:
    revision = revisions.get("tj-agents/github-actions")
    if path.name != "publish-update.yml" or revision is None:
        return content
    references = [match for _, _, match in reference_matches(content)]
    if (len(references) != 1 or references[0].group("repository").lower() != "tj-agents/github-actions"
            or references[0].group("subpath") != "/.github/workflows/publish-update.yml"):
        return content
    normalized = content.replace("\r\n", "\n")
    source = (Path(__file__).resolve().parents[3]
              / ".agents/github-actions/utility/publish-update/scripts/caller.py")
    spec = importlib.util.spec_from_file_location("publisher_caller", source)
    if spec is None or spec.loader is None:
        raise ValueError("published action is missing its caller generator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    current = module.render(references[0].group("sha"))
    if normalized == current:
        return content
    # Only the two exact previously generated trigger shapes are owned here.
    old_trigger = "  workflow_run:\n    workflows: [ci]\n    types: [completed]\n"
    legacy = [current.replace(old_trigger, trigger) for trigger in (
        "  push:\n", "  push:\n    branches: [main]\n")]
    if normalized not in legacy:
        raise ValueError("custom publisher workflow requires review before regeneration")
    rendered = module.render(revision)
    if not isinstance(rendered, str):
        raise ValueError("publisher caller generator returned invalid content")
    return rendered.replace("\n", "\r\n") if "\r\n" in content else rendered


def _caller_module():
    source = (Path(__file__).resolve().parents[3]
              / ".agents/github-actions/utility/publish-update/scripts/caller.py")
    spec = importlib.util.spec_from_file_location("publisher_caller", source)
    if spec is None or spec.loader is None:
        raise ValueError("trusted publisher caller generator is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TEMPLATE_CI = re.compile(
    r"\Aname: ci\n\non:\n  push:\n    branches: \[main\]\n"
    r"  pull_request:\n\njobs:\n  verify:\n"
    r"    uses: tj-agents/template/\.github/workflows/plugin-ci\.yml@"
    r"(?P<revision>main|[0-9a-f]{40})\n    with:\n"
    r"      template_ref: (?P=revision)\n"
    r"(?P<secrets>    secrets:\n(?:      (?:read_token: \$\{\{ secrets\.TJ_AGENTS_READ_TOKEN \}\}|"
    r"UPDATE_APP_PRIVATE_KEY: \$\{\{ secrets\.UPDATE_APP_PRIVATE_KEY \}\})\n)+)?\Z"
)
def migrate_template_ci(content):
    normalized = content.replace("\r\n", "\n")
    match = TEMPLATE_CI.fullmatch(normalized)
    if match is None:
        if "tj-agents/template/.github/workflows/plugin-ci.yml@" in normalized:
            raise ValueError("custom Template CI caller requires review before bootstrap")
        return content
    secret_lines = (match.group("secrets") or "").splitlines()
    updater_secret = "      UPDATE_APP_PRIVATE_KEY: ${{ secrets.UPDATE_APP_PRIVATE_KEY }}"
    if updater_secret not in secret_lines:
        if secret_lines:
            migrated = normalized.replace(
                match.group("secrets"), match.group("secrets") + updater_secret + "\n", 1
            )
        else:
            migrated = normalized + "    secrets:\n" + updater_secret + "\n"
    else:
        migrated = normalized
    return migrated.replace("\n", "\r\n") if "\r\n" in content else migrated


def migrate_updater_caller(content, revision, repositories):
    module = _caller_module()
    normalized = content.replace("\r\n", "\n")
    uses = re.search(
        r"(?m)^    uses: tj-agents/github-actions/\.github/workflows/update-pins\.yml@([0-9a-f]{40})$",
        normalized,
    )
    if uses is None:
        raise ValueError("custom update-pins workflow requires review before bootstrap")
    repositories_match = re.search(r"(?m)^      repositories: ([^\n]+)$", normalized)
    if repositories_match is None:
        raise ValueError("custom update-pins workflow requires review before bootstrap")
    allowlist = parse_repositories(repositories_match.group(1))
    original_repositories = ",".join(allowlist)
    previous = module.render_updater(uses.group(1), original_repositories)
    legacy = previous.replace(
        "    secrets:\n      UPDATE_APP_PRIVATE_KEY: ${{ secrets.UPDATE_APP_PRIVATE_KEY }}\n", ""
    )
    if normalized not in {previous, legacy}:
        raise ValueError("custom update-pins workflow requires review before bootstrap")
    updated = module.render_updater(revision, original_repositories)
    return updated.replace("\n", "\r\n") if "\r\n" in content else updated


def validate_repository_identity(root, repository):
    if not REPOSITORY.fullmatch(repository):
        raise ValueError("invalid target consumer repository")
    found = False
    for relative in (
        ".agents/plugins/template.json",
        ".github/update-enrollment.json",
    ):
        path = root / relative
        if not path.exists():
            continue
        found = True
        try:
            _, text = read_declaration(root, relative)
            declaration = json.loads(text)
        except (OSError, ValueError) as error:
            raise ValueError("consumer enrollment declaration is invalid") from error
        if (
            not isinstance(declaration, dict)
            or type(declaration.get("schema_version")) is not int
            or declaration.get("schema_version") != 1
            or not isinstance(declaration.get("repository"), str)
            or declaration["repository"].casefold() != repository.casefold()
            or (
                relative == ".github/update-enrollment.json"
                and set(declaration) != {"schema_version", "repository"}
            )
        ):
            raise ValueError("consumer enrollment declaration does not match target repository")
    if not found:
        raise ValueError("consumer has no matching enrollment declaration")


def update(
    project,
    repositories,
    check=False,
    files=None,
    resolver=resolve_repository,
    comparer=compare_revisions,
    content_comparer=compare_contents,
    bootstrap_callers=False,
    target_repository=None,
):
    root = Path(project).resolve()
    if not root.is_dir():
        raise ValueError("project is not a directory")
    if bootstrap_callers:
        if not target_repository:
            raise ValueError("bootstrap requires an explicit target repository")
        validate_repository_identity(root, target_repository)
    documents = [read_file(root, relative) for relative in (tracked_files(root) if files is None else files)]
    revisions = {repository.lower(): resolver(repository) for repository in repositories}
    comparisons = set()
    for _, content in documents:
        comparisons.update(pending_comparisons(content, revisions))
    for repository, before, after in sorted({(repository, before, after) for repository, _, before, after in comparisons}):
        comparer(repository, before, after)
    replacements = {}
    for repository, subpath, before, after in sorted(comparisons):
        if content_comparer(repository, subpath, before, after):
            replacements[(repository, subpath, before)] = after
    proposals = [
        (
            path,
            content,
            generated_publisher(
                path, replace_references(content, replacements), revisions
            ),
        )
        for path, content in documents
    ]
    if bootstrap_callers:
        revision = revisions.get("tj-agents/github-actions")
        if revision is None:
            raise ValueError("bootstrap requires tj-agents/github-actions in the pin allowlist")
        proposed_paths = {path.resolve() for path, _, _ in proposals}
        for index, (path, original, content) in enumerate(proposals):
            if path.name == "ci.yml":
                updated = migrate_template_ci(content)
                if updated != content:
                    proposals[index] = (path, original, updated)
        updater_path = root / ".github/workflows/update-pins.yml"
        if target_repository and target_repository.casefold() == "tj-agents/github-actions":
            # This repository owns the canonical workflow called by consumers.
            pass
        elif updater_path.resolve() in proposed_paths:
            for index, (path, original, content) in enumerate(proposals):
                if path.resolve() == updater_path.resolve():
                    updated = migrate_updater_caller(
                        content, revision, ",".join(repositories)
                    )
                    proposals[index] = (path, original, updated)
                    break
        elif updater_path.exists():
            raise ValueError("untracked update-pins workflow requires review before bootstrap")
        else:
            module = _caller_module()
            generated = module.render_updater(revision, ",".join(repositories))
            proposals.append((updater_path, "", generated))
    changed = [(path, updated) for path, original, updated in proposals if updated != original]
    if changed and not check:
        for path, content in changed:
            if os.path.islink(path) or os.path.islink(path.parent):
                raise ValueError("unsafe tracked file")
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8", newline="") as handle:
                handle.write(content)
    extensions = [
        extension for extension in (".yml", ".yaml")
        if any(path.suffix == extension for path, _ in changed)
    ]
    return {"changed": bool(changed), "files": len(changed), "repositories": repositories[:20], "extensions": extensions}


def write_outputs(summary):
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8", newline="") as handle:
            handle.write("changed=" + str(summary["changed"]).lower() + "\n")
            handle.write("summary=" + json.dumps(summary, separators=(",", ":")) + "\n")
            handle.write("add-paths=" + ",".join(".github/**/*" + extension for extension in summary["extensions"]) + "\n")


def main(arguments=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--repositories", required=True)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--bootstrap-callers", action="store_true")
    parser.add_argument("--repository")
    values = parser.parse_args(arguments)
    try:
        summary = update(
            values.project,
            parse_repositories(values.repositories),
            values.check,
            bootstrap_callers=values.bootstrap_callers,
            target_repository=values.repository,
        )
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
