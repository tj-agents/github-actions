#!/usr/bin/env python3
"""Merge exactly reproducible pull requests created by the protected pin updater."""

import argparse
import base64
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

sys.dont_write_bytecode = True

BRANCH = "Chore/UpdateSharedPins"
SHA = re.compile(r"[0-9a-f]{40}")
SLUG = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,98}[a-z0-9])?")
TIMEOUT = 90
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


class MergeError(Exception):
    pass


class GitHub:
    def __init__(
        self, run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run
    ) -> None:
        self.run = run

    def api(
        self, path: str, method: str = "GET", body: Mapping[str, Any] | None = None
    ) -> Any:
        command = ["gh", "api", "--hostname", "github.com", path, "--method", method]
        data = None
        if body is not None:
            command += ["--input", "-"]
            data = json.dumps(body)
        try:
            result = self.run(
                command,
                input=data,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=TIMEOUT,
                check=False,
                creationflags=NO_WINDOW,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise MergeError("GitHub request failed") from error
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()[:300]
            raise MergeError(f"GitHub request {method} {path} failed: {detail}")
        try:
            return json.loads(result.stdout) if result.stdout.strip() else None
        except json.JSONDecodeError as error:
            raise MergeError(f"GitHub returned invalid JSON for {path}") from error

    def optional(self, path: str) -> Any | None:
        try:
            return self.api(path)
        except MergeError as error:
            if "HTTP 404" in str(error):
                return None
            raise


def pages(gh: Any, path: str) -> Iterable[Mapping[str, Any]]:
    separator = "&" if "?" in path else "?"
    page = 1
    while True:
        data = gh.api(f"{path}{separator}per_page=100&page={page}")
        if not isinstance(data, list) or not all(
            isinstance(item, dict) for item in data
        ):
            raise MergeError("GitHub returned an invalid page")
        yield from data
        if len(data) < 100:
            return
        page += 1


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise MergeError(f"trusted implementation is missing: {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[5]
UPDATER = load_module(
    "trusted_update_pins", ROOT / ".github/actions/update-pins/update_pins.py"
)
ENROLLMENT = load_module(
    "trusted_enrollment",
    ROOT / ".agents/github-actions/utility/publish-update/scripts/enrollment.py",
)
MERGE_POLICY = load_module(
    "trusted_merge_policy",
    ROOT / ".agents/github-actions/utility/merge-policy/scripts/merge_policy.py",
)


def valid_sha(value: Any) -> str:
    if not isinstance(value, str) or SHA.fullmatch(value) is None:
        raise MergeError("GitHub returned an invalid commit identity")
    return value


def blob_sha(content: bytes) -> str:
    return hashlib.sha1(
        b"blob " + str(len(content)).encode("ascii") + b"\0" + content
    ).hexdigest()


def tree(gh: Any, repository: str, revision: str) -> dict[str, tuple[str, str, str]]:
    data = gh.api(f"repos/{repository}/git/trees/{revision}?recursive=1")
    if not isinstance(data, dict) or data.get("truncated"):
        raise MergeError("GitHub returned an incomplete tree")
    entries = data.get("tree")
    if not isinstance(entries, list):
        raise MergeError("GitHub returned an invalid tree")
    result: dict[str, tuple[str, str, str]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise MergeError("GitHub returned an invalid tree entry")
        path, mode, kind, oid = (
            entry.get("path"),
            entry.get("mode"),
            entry.get("type"),
            entry.get("sha"),
        )
        if (
            not isinstance(path, str)
            or PurePosixPath(path).is_absolute()
            or ".." in PurePosixPath(path).parts
            or not isinstance(mode, str)
            or not isinstance(kind, str)
            or not isinstance(oid, str)
            or SHA.fullmatch(oid) is None
            or path in result
        ):
            raise MergeError("GitHub returned an unsafe tree entry")
        result[path] = (mode, kind, oid)
    return result


def blob(gh: Any, repository: str, oid: str) -> bytes:
    data = gh.api(f"repos/{repository}/git/blobs/{oid}")
    if (
        not isinstance(data, dict)
        or data.get("encoding") != "base64"
        or not isinstance(data.get("content"), str)
    ):
        raise MergeError("GitHub returned an invalid blob")
    try:
        return base64.b64decode("".join(data["content"].split()), validate=True)
    except ValueError as error:
        raise MergeError("GitHub returned an invalid blob") from error


def text_blob(
    gh: Any, repository: str, entries: Mapping[str, tuple[str, str, str]], path: str
) -> str:
    entry = entries.get(path)
    if entry is None or entry[0] != "100644" or entry[1] != "blob":
        raise MergeError(f"expected regular file is missing: {path}")
    try:
        return blob(gh, repository, entry[2]).decode("utf-8")
    except UnicodeDecodeError as error:
        raise MergeError(f"expected UTF-8 file is invalid: {path}") from error


def updater_files(entries: Mapping[str, tuple[str, str, str]]) -> list[str]:
    return sorted(
        path
        for path, (mode, kind, _) in entries.items()
        if path.startswith(".github/")
        and path.endswith((".yml", ".yaml"))
        and mode == "100644"
        and kind == "blob"
    )


def updater_allowlist(
    entries: Mapping[str, tuple[str, str, str]], gh: Any, repository: str
) -> list[str]:
    path = ".github/workflows/update-pins.yml"
    if path not in entries:
        return ["tj-agents/github-actions"]
    content = text_blob(gh, repository, entries, path)
    if "inputs.repositories" in content and "tj-agents/github-actions" in content:
        return ["tj-agents/github-actions"]
    found = re.search(r"(?m)^\s+repositories: ([^\n]+)$", content)
    if found is None:
        raise MergeError("updater caller has no trusted repository allowlist")
    try:
        values = UPDATER.parse_repositories(found.group(1))
    except ValueError as error:
        raise MergeError(
            "updater caller has an invalid repository allowlist"
        ) from error
    if "tj-agents/github-actions" not in {value.casefold() for value in values}:
        raise MergeError("updater caller must permit its trusted source")
    if not isinstance(values, list) or not all(
        isinstance(value, str) for value in values
    ):
        raise MergeError("updater caller has an invalid repository allowlist")
    return values


def proposal_candidates(
    gh: Any,
    repository: str,
    before: Mapping[str, tuple[str, str, str]],
    after: Mapping[str, tuple[str, str, str]],
    allowlist: Iterable[str],
) -> dict[str, str]:
    allowed = {value.casefold() for value in allowlist}
    found: dict[str, set[str]] = {value: set() for value in allowed}
    paths = set(before) | set(after)
    for path in paths:
        if not path.startswith(".github/") or not path.endswith((".yml", ".yaml")):
            continue
        before_text = text_blob(gh, repository, before, path) if path in before else ""
        after_text = text_blob(gh, repository, after, path) if path in after else ""
        before_refs = list(UPDATER.reference_matches(before_text))
        after_refs = list(UPDATER.reference_matches(after_text))
        pairs = zip(before_refs, after_refs, strict=False)
        for (_, _, old), (_, _, new) in pairs:
            owner = new.group("repository").casefold()
            if owner in allowed and (
                old.group("repository").casefold() != owner
                or old.group("subpath") != new.group("subpath")
                or old.group("sha").casefold() != new.group("sha").casefold()
            ):
                found[owner].add(new.group("sha").casefold())
        if path not in before:
            for _, _, item in after_refs:
                owner = item.group("repository").casefold()
                if owner in allowed:
                    found[owner].add(item.group("sha").casefold())
    for path in (
        ".github/workflows/update-pins.yml",
        ".github/workflows/publish-update.yml",
    ):
        if path in after and not any(found.values()):
            for _, _, item in UPDATER.reference_matches(
                text_blob(gh, repository, after, path)
            ):
                owner = item.group("repository").casefold()
                if owner in allowed:
                    found[owner].add(item.group("sha").casefold())
    selected: dict[str, str] = {}
    for source, candidates in found.items():
        if len(candidates) > 1:
            raise MergeError("candidate proposes ambiguous source revisions")
        if candidates:
            selected[source] = next(iter(candidates))
    if not selected:
        raise MergeError("candidate has no reproducible source revision")
    return selected


def source_object(gh: Any, repository: str, revision: str, subpath: str) -> str:
    commit = gh.api(f"repos/{repository}/commits/{revision}")
    try:
        current = valid_sha(commit["commit"]["tree"]["sha"])
    except (KeyError, TypeError) as error:
        raise MergeError("source commit has no tree") from error
    for part in PurePosixPath(subpath.lstrip("/")).parts if subpath else ():
        data = gh.api(f"repos/{repository}/git/trees/{current}")
        entries = data.get("tree") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            raise MergeError("source tree is invalid")
        match = next(
            (
                entry
                for entry in entries
                if isinstance(entry, dict)
                and entry.get("path") == part
                and entry.get("type") in {"blob", "tree"}
            ),
            None,
        )
        if not isinstance(match, dict):
            raise MergeError("source path is absent")
        current = valid_sha(match.get("sha"))
    return current


def source_content_changed(
    gh: Any, repository: str, subpath: str, before: str, after: str
) -> bool:
    return source_object(gh, repository, before, subpath) != source_object(
        gh, repository, after, subpath
    )


def validate_sources(
    gh: Any, targets: Mapping[str, str]
) -> Callable[[str, str, str], None]:
    for repository, target in targets.items():
        data = gh.api(f"repos/{repository}")
        if not isinstance(data, dict) or not isinstance(
            data.get("default_branch"), str
        ):
            raise MergeError("source repository has no default branch")
        head = valid_sha(
            gh.api(
                f"repos/{repository}/commits/{quote(data['default_branch'], safe='')}"
            ).get("sha")
        )
        status = gh.api(f"repos/{repository}/compare/{target}...{head}")
        if not isinstance(status, dict) or status.get("status") not in {
            "ahead",
            "identical",
        }:
            raise MergeError("proposed source revision is not on its default branch")

    def comparer(repository: str, before: str, after: str) -> None:
        if targets.get(repository.casefold()) != after:
            raise MergeError("generator requested an unproven source revision")
        status = gh.api(f"repos/{repository}/compare/{before}...{after}")
        if not isinstance(status, dict) or status.get("status") not in {
            "ahead",
            "identical",
        }:
            raise MergeError("candidate moves a source revision backwards")

    return comparer


def materialize(
    directory: Path,
    gh: Any,
    repository: str,
    entries: Mapping[str, tuple[str, str, str]],
    files: Iterable[str],
) -> None:
    required = set(files) | {
        ".agents/plugins/template.json",
        ".github/update-enrollment.json",
    }
    for path in required:
        entry = entries.get(path)
        if entry is None:
            continue
        if entry[0] != "100644" or entry[1] != "blob":
            raise MergeError("candidate input includes an unsafe file")
        target = directory.joinpath(*PurePosixPath(path).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob(gh, repository, entry[2]))


def expected_tree(
    directory: Path,
    before: Mapping[str, tuple[str, str, str]],
    files: Iterable[str],
) -> dict[str, tuple[str, str, str]]:
    result = dict(before)
    inspected = set(files) | {".github/workflows/update-pins.yml"}
    for path in inspected:
        local = directory.joinpath(*PurePosixPath(path).parts)
        if local.exists():
            if not local.is_file():
                raise MergeError("trusted generator produced an unsafe file")
            result[path] = ("100644", "blob", blob_sha(local.read_bytes()))
        elif path in result:
            raise MergeError("trusted generator removed a tracked file")
    return result


def replay(
    gh: Any,
    owner: str,
    repository: str,
    base: str,
    head: str,
) -> bool:
    before = tree(gh, repository, base)
    after = tree(gh, repository, head)
    files = updater_files(before)
    if not files:
        raise MergeError("candidate base has no tracked GitHub YAML")
    allowlist = updater_allowlist(before, gh, repository)
    targets = proposal_candidates(gh, repository, before, after, allowlist)
    comparer = validate_sources(gh, targets)
    for bootstrap in (False, True):
        with tempfile.TemporaryDirectory(prefix="merge-updater-prs-") as temporary:
            root = Path(temporary)
            materialize(root, gh, repository, before, files)
            try:
                UPDATER.validate_repository_identity(root, repository)
                UPDATER.update(
                    root,
                    allowlist,
                    files=files,
                    resolver=lambda source: targets[source.casefold()],
                    comparer=comparer,
                    content_comparer=lambda source, path, old, new: (
                        source_content_changed(gh, source, path, old, new)
                    ),
                    bootstrap_callers=bootstrap,
                    target_repository=repository if bootstrap else None,
                )
            except (KeyError, ValueError):
                continue
            if leaf_entries(expected_tree(root, before, files)) == leaf_entries(after):
                return True
    return False


def leaf_entries(
    entries: Mapping[str, tuple[str, str, str]],
) -> dict[str, tuple[str, str, str]]:
    return {path: entry for path, entry in entries.items() if entry[1] != "tree"}


def merge_base(gh: Any, repository: str, base: str, head: str) -> str:
    data = gh.api(f"repos/{repository}/compare/{base}...{head}")
    try:
        return valid_sha(data["merge_base_commit"]["sha"])
    except (KeyError, TypeError) as error:
        raise MergeError("candidate has no merge base") from error


def policy_contexts(
    gh: Any, repository: str, policy_ref: str
) -> set[tuple[str, int | None]]:
    entries = tree(gh, repository, policy_ref)
    path = ".github/merge-policy.json"
    contexts: set[tuple[str, int | None]] = set()
    if path in entries:
        try:
            policy = MERGE_POLICY.validate_policy(
                json.loads(text_blob(gh, repository, entries, path)), path
            )
            contexts.update(
                (name, None) for name in MERGE_POLICY.required_contexts(policy)
            )
        except (ValueError, MERGE_POLICY.PolicyError) as error:
            raise MergeError("candidate base has invalid merge policy") from error
    return contexts


def required_contexts(
    gh: Any, repository: str, branch: str, policy_ref: str
) -> set[tuple[str, int | None]]:
    contexts = policy_contexts(gh, repository, policy_ref)
    rules = gh.api(
        f"repos/{repository}/rules/branches/{quote(branch, safe='')}?per_page=100"
    )
    if not isinstance(rules, list):
        raise MergeError("GitHub returned invalid effective branch rules")
    for rule in rules:
        if isinstance(rule, dict) and rule.get("type") == "merge_queue":
            raise MergeError("effective branch rules require a merge queue")
        if not isinstance(rule, dict) or rule.get("type") != "required_status_checks":
            continue
        values = (rule.get("parameters") or {}).get("required_status_checks")
        if not isinstance(values, list):
            raise MergeError("GitHub returned invalid required checks")
        for value in values:
            if not isinstance(value, dict) or not isinstance(value.get("context"), str):
                raise MergeError("GitHub returned invalid required check")
            integration = value.get("integration_id")
            if integration is not None and (
                type(integration) is not int or integration <= 0
            ):
                raise MergeError("GitHub returned invalid check integration")
            contexts.add((value["context"], integration))
    branch_data = gh.optional(f"repos/{repository}/branches/{quote(branch, safe='')}")
    protection = (
        branch_data.get("protection") if isinstance(branch_data, dict) else None
    )
    checks = (
        protection.get("required_status_checks")
        if isinstance(protection, dict)
        else None
    )
    if isinstance(checks, dict) and checks.get("enforcement_level") != "off":
        values = checks.get("checks", [])
        names = checks.get("contexts", [])
        if not isinstance(values, list) or not isinstance(names, list):
            raise MergeError("GitHub returned invalid legacy required checks")
        for name in names:
            if not isinstance(name, str):
                raise MergeError("GitHub returned invalid legacy required check")
            contexts.add((name, None))
        for value in values:
            if not isinstance(value, dict) or not isinstance(value.get("context"), str):
                raise MergeError("GitHub returned invalid legacy required check")
            app_id = value.get("app_id")
            if app_id is not None and (type(app_id) is not int or app_id <= 0):
                raise MergeError("GitHub returned invalid legacy check integration")
            contexts.add((value["context"], app_id))
    return contexts


def check_records(
    gh: Any, repository: str, revision: str
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    return (
        object_pages(
            gh,
            f"repos/{repository}/commits/{revision}/check-runs?filter=latest",
            "check_runs",
        ),
        list(pages(gh, f"repos/{repository}/commits/{revision}/statuses")),
    )


def object_pages(gh: Any, path: str, key: str) -> list[Mapping[str, Any]]:
    result: list[Mapping[str, Any]] = []
    separator = "&" if "?" in path else "?"
    page = 1
    while True:
        data = gh.api(f"{path}{separator}per_page=100&page={page}")
        values = data.get(key) if isinstance(data, dict) else None
        if not isinstance(values, list) or not all(
            isinstance(item, dict) for item in values
        ):
            raise MergeError(f"GitHub returned invalid {key}")
        result.extend(values)
        if len(values) < 100:
            return result
        page += 1


def latest_records(
    records: Iterable[Mapping[str, Any]], key: Callable[[Mapping[str, Any]], str | None]
) -> dict[str, Mapping[str, Any]]:
    selected: dict[str, Mapping[str, Any]] = {}
    for record in records:
        identity = key(record)
        record_id = record.get("id")
        if identity is None or type(record_id) is not int or record_id <= 0:
            raise MergeError("GitHub returned a record without a monotonic identity")
        current = selected.get(identity)
        if current is None:
            selected[identity] = record
            continue
        if record_id > current["id"]:
            selected[identity] = record
    return selected


def check_key(record: Mapping[str, Any]) -> str | None:
    name = record.get("name")
    app = record.get("app")
    app_id = app.get("id") if isinstance(app, dict) else None
    if not isinstance(name, str) or type(app_id) is not int or app_id <= 0:
        return None
    return f"{name}\0{app_id}"


def status_key(record: Mapping[str, Any]) -> str | None:
    context = record.get("context")
    return context if isinstance(context, str) else None


def passing_check(record: Mapping[str, Any], revision: str) -> bool:
    return (
        record.get("head_sha") == revision
        and record.get("status") == "completed"
        and record.get("conclusion") in {"success", "neutral", "skipped"}
    )


def passing_status(record: Mapping[str, Any]) -> bool:
    return record.get("state") == "success"


def suite_key(record: Mapping[str, Any]) -> str | None:
    app = record.get("app")
    app_id = app.get("id") if isinstance(app, dict) else None
    return str(app_id) if type(app_id) is int and app_id > 0 else None


def suite_state(gh: Any, repository: str, revision: str) -> tuple[bool, str]:
    suites = object_pages(
        gh, f"repos/{repository}/commits/{revision}/check-suites", "check_suites"
    )
    latest = latest_records(suites, suite_key)
    if any(
        suite.get("head_sha") != revision
        or suite.get("status") != "completed"
        or suite.get("conclusion") not in {"success", "neutral", "skipped"}
        for suite in latest.values()
    ):
        return False, "check suite is pending or failing"
    return True, ""


def observed_ci_state(gh: Any, repository: str, revision: str) -> tuple[bool, str]:
    runs, statuses = check_records(gh, repository, revision)
    latest_runs = latest_records(runs, check_key)
    latest_statuses = latest_records(statuses, status_key)
    if not latest_runs and not latest_statuses:
        return False, "no current check or status evidence"
    if any(not passing_check(record, revision) for record in latest_runs.values()):
        return False, "current check is pending or failing"
    if any(not passing_status(record) for record in latest_statuses.values()):
        return False, "current status is pending or failing"
    return suite_state(gh, repository, revision)


def check_state(
    gh: Any, repository: str, revision: str, contexts: set[tuple[str, int | None]]
) -> tuple[bool, bool]:
    runs, statuses = check_records(gh, repository, revision)
    current_runs = latest_records(runs, check_key)
    current_statuses = latest_records(statuses, status_key)
    any_evidence = False
    for context, integration in contexts:
        runs_for_context = [
            run
            for key, run in current_runs.items()
            if key.partition("\0")[0] == context
            and (integration is None or key.partition("\0")[2] == str(integration))
        ]
        status = current_statuses.get(context)
        matching_run = bool(runs_for_context)
        matching_status = status is not None
        if matching_run or matching_status:
            any_evidence = True
        if integration is not None and matching_status:
            return False, any_evidence
        if not matching_run and not matching_status:
            return False, any_evidence
        if matching_run and any(
            not passing_check(run, revision) for run in runs_for_context
        ):
            return False, any_evidence
        if matching_status and status is not None and not passing_status(status):
            return False, any_evidence
    return True, any_evidence


def checks_pass(
    gh: Any,
    repository: str,
    pr: Mapping[str, Any],
    contexts: set[tuple[str, int | None]],
) -> tuple[bool, str]:
    head = valid_sha((pr.get("head") or {}).get("sha"))
    merge = pr.get("merge_commit_sha")
    if isinstance(merge, str) and SHA.fullmatch(merge) and merge != head:
        if contexts:
            passed, observed = check_state(gh, repository, merge, contexts)
            if observed:
                return passed, "required checks are pending or failing"
        else:
            return observed_ci_state(gh, repository, merge)
    if contexts:
        passed, _ = check_state(gh, repository, head, contexts)
        return passed, "required checks are pending or failing"
    return observed_ci_state(gh, repository, head)


def official_pr(
    pr: Mapping[str, Any], repository: Mapping[str, Any], updater_id: int
) -> tuple[int, str, str] | None:
    try:
        number = pr["number"]
        head = pr["head"]
        base = pr["base"]
        author = pr["user"]
        repository_id = repository["id"]
        default_branch = repository["default_branch"]
    except KeyError:
        return None
    if (
        type(number) is not int
        or pr.get("draft")
        or not isinstance(head, dict)
        or not isinstance(base, dict)
        or not isinstance(author, dict)
        or head.get("ref") != BRANCH
        or base.get("ref") != default_branch
        or (head.get("repo") or {}).get("id") != repository_id
        or author.get("id") != updater_id
        or author.get("type") != "Bot"
    ):
        return None
    try:
        return number, valid_sha(base.get("sha")), valid_sha(head.get("sha"))
    except MergeError:
        return None


def same_pr(
    pr: Mapping[str, Any],
    number: int,
    base: str,
    head: str,
    branch: str,
    repository_id: int,
    updater_id: int,
) -> bool:
    official = official_pr(
        pr,
        {"id": repository_id, "default_branch": branch},
        updater_id,
    )
    return official == (number, base, head)


def merge_candidate(
    gh: Any,
    owner: str,
    name: str,
    metadata: Mapping[str, Any],
    pr: Mapping[str, Any],
    updater_id: int,
) -> tuple[str, str | None]:
    repository = f"{owner}/{name}"
    candidate = official_pr(pr, metadata, updater_id)
    if candidate is None:
        return "ignored", None
    number, base, head = candidate
    if not ENROLLMENT.eligible_repository(
        gh, owner, repository, metadata["default_branch"], metadata
    ):
        return "skipped", "repository is no longer eligible"
    replay_base = merge_base(gh, repository, base, head)
    if not replay(gh, owner, repository, replay_base, head):
        return "skipped", "trusted generator replay differs"
    branch = metadata["default_branch"]
    policy_ref = valid_sha(
        gh.api(f"repos/{repository}/commits/{quote(branch, safe='')}").get("sha")
    )
    contexts = required_contexts(gh, repository, branch, policy_ref)
    ready, reason = checks_pass(gh, repository, pr, contexts)
    if not ready:
        return "waiting", reason
    fresh_metadata = gh.api(f"repos/{repository}")
    fresh = gh.api(f"repos/{repository}/pulls/{number}")
    if (
        not isinstance(fresh_metadata, dict)
        or fresh_metadata.get("id") != metadata["id"]
        or fresh_metadata.get("default_branch") != branch
        or valid_sha(
            gh.api(f"repos/{repository}/commits/{quote(branch, safe='')}").get("sha")
        )
        != policy_ref
    ):
        return "raced", "default branch changed during admission"
    if not isinstance(fresh, dict) or not same_pr(
        fresh, number, base, head, branch, metadata["id"], updater_id
    ):
        return "raced", "pull request changed during admission"
    ready, reason = checks_pass(gh, repository, fresh, contexts)
    if not ready:
        return "waiting", reason
    result = gh.api(
        f"repos/{repository}/pulls/{number}/merge",
        "PUT",
        {"sha": head, "merge_method": "squash"},
    )
    if not isinstance(result, dict) or result.get("merged") is not True:
        return "waiting", "GitHub did not merge the current head"
    return "merged", None


def updater_identity(gh: Any, slug: str) -> int:
    if SLUG.fullmatch(slug) is None:
        raise MergeError("updater App slug is invalid")
    data = gh.api(f"users/{slug}[bot]")
    if (
        not isinstance(data, dict)
        or data.get("login") != f"{slug}[bot]"
        or data.get("type") != "Bot"
    ):
        raise MergeError("updater App identity is invalid")
    value = data.get("id")
    if type(value) is not int or value <= 0:
        raise MergeError("updater App identity is invalid")
    return value


def reconcile(gh: Any, owner: str, slug: str) -> dict[str, Any]:
    updater_id = updater_identity(gh, slug)
    result: dict[str, Any] = {
        "merged": 0,
        "waiting": 0,
        "skipped": 0,
        "raced": 0,
        "errors": 0,
    }
    diagnostics: list[str] = []
    for item in pages(gh, f"orgs/{owner}/repos?type=all"):
        if (
            item.get("archived")
            or item.get("fork")
            or (item.get("owner") or {}).get("login", "").casefold() != owner.casefold()
        ):
            continue
        name = item.get("name")
        if not isinstance(name, str):
            raise MergeError("GitHub returned an invalid repository identity")
        repository = f"{owner}/{name}"
        try:
            metadata = gh.api(f"repos/{repository}")
            if (
                not isinstance(metadata, dict)
                or metadata.get("full_name", "").casefold() != repository.casefold()
            ):
                raise MergeError("GitHub returned an invalid repository")
            branch = metadata.get("default_branch")
            if not isinstance(branch, str):
                raise MergeError(
                    "GitHub returned a repository without a default branch"
                )
            for pr in pages(
                gh, f"repos/{repository}/pulls?state=open&base={quote(branch, safe='')}"
            ):
                try:
                    outcome, reason = merge_candidate(
                        gh, owner, name, metadata, pr, updater_id
                    )
                except MergeError as error:
                    result["errors"] += 1
                    number = pr.get("number")
                    if type(number) is int:
                        diagnostics.append(f"{repository}#{number}: {str(error)[:160]}")
                    continue
                if outcome == "ignored":
                    continue
                result[outcome] += 1
                if reason is not None:
                    number = pr.get("number")
                    if type(number) is int:
                        diagnostics.append(f"{repository}#{number}: {reason}")
        except MergeError as error:
            result["errors"] += 1
            diagnostics.append(f"{repository}: {str(error)[:160]}")
    result["diagnostics"] = diagnostics[:20]
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--updater-app-slug", required=True)
    arguments = parser.parse_args(argv)
    try:
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", arguments.owner):
            raise MergeError("--owner must be a GitHub organization login")
        result = reconcile(GitHub(), arguments.owner, arguments.updater_app_slug)
        print(json.dumps(result, sort_keys=True))
        return int(result["errors"] > 0)
    except MergeError as error:
        print(f"merge-updater-prs: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
