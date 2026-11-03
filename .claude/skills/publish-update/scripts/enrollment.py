#!/usr/bin/env python3
"""Enroll Template plugin repositories in protected updater publication.

Requires Python 3.9+ and the GitHub CLI.
"""

import argparse
import base64
import importlib.util
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote

sys.dont_write_bytecode = True

ENVIRONMENT = "update-pins"
SECRET = "UPDATE_APP_PRIVATE_KEY"
VARIABLE = "UPDATE_APP_CLIENT_ID"
SOURCE = ".agents/plugins/template.json"
BRANCH_VARIABLE = "TJ_AGENTS_UPDATE_PINS_BRANCH"
TIMEOUT = 90
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
OWNER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
BRANCH = re.compile(r"[A-Za-z0-9._/-]{1,200}")


class EnrollmentError(Exception):
    pass


class GitHub:
    def __init__(
        self, run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run
    ) -> None:
        self.run = run

    def call(
        self, arguments: list[str], payload: Mapping[str, Any] | None = None
    ) -> subprocess.CompletedProcess[str]:
        command = ["gh", "api", "--hostname", "github.com", *arguments[1:]]
        data = None
        if payload is not None:
            command += ["--input", "-"]
            data = json.dumps(payload)
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
            raise EnrollmentError(f"GitHub CLI request failed: {error}") from error
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()[:300]
            raise EnrollmentError(
                f"GitHub request {' '.join(arguments[:3])} failed: {detail}"
            )
        return result

    def api(
        self, path: str, method: str = "GET", body: Mapping[str, Any] | None = None
    ) -> Any:
        result = self.call(["api", path, "--method", method], body)
        return json.loads(result.stdout) if result.stdout.strip() else None

    def optional(self, path: str) -> Any:
        result = self.run(
            ["gh", "api", "--hostname", "github.com", path, "--method", "GET"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT,
            check=False,
            creationflags=NO_WINDOW,
        )
        if result.returncode and "HTTP 404" in result.stderr:
            return None
        if result.returncode:
            raise EnrollmentError(
                f"GitHub request GET {path} failed: "
                f"{(result.stderr or result.stdout).strip()[:300]}"
            )
        return json.loads(result.stdout) if result.stdout.strip() else None

    def secret(
        self,
        repository: str,
        value: str,
        environment: str = ENVIRONMENT,
        secret: str = SECRET,
    ) -> None:
        result = self.run(
            [
                "gh",
                "secret",
                "set",
                secret,
                "--repo",
                f"github.com/{repository}",
                "--env",
                environment,
            ],
            input=value,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT,
            check=False,
            creationflags=NO_WINDOW,
        )
        if result.returncode:
            raise EnrollmentError(
                f"could not set {secret} for {repository}/{environment}"
            )


def pages(gh: Any, path: str) -> Iterator[dict[str, Any]]:
    page = 1
    while True:
        separator = "&" if "?" in path else "?"
        response = gh.api(f"{path}{separator}per_page=100&page={page}") or []
        batch = response
        if isinstance(response, dict):
            batch = response.get(
                "branch_policies", response.get("repositories", response.get("secrets"))
            )
        if not isinstance(batch, list):
            raise EnrollmentError(f"GitHub returned an invalid list for {path}")
        yield from batch
        if len(batch) < 100:
            return
        page += 1


def protected(
    gh: Any,
    repository: str,
    branch: str,
    apply: bool,
    environment: str = ENVIRONMENT,
    branch_variable: str = BRANCH_VARIABLE,
) -> dict[str, Any]:
    if (
        not BRANCH.fullmatch(branch)
        or branch.startswith("/")
        or branch.endswith("/")
        or ".." in branch
    ):
        raise EnrollmentError(f"{repository} has an invalid default branch name")
    environment_path = f"repos/{repository}/environments/{quote(environment, safe='')}"
    current = gh.optional(environment_path)
    variable_root = f"{environment_path}/variables"
    marker_path = f"{variable_root}/{branch_variable}"
    marker = gh.optional(marker_path) if current else None
    marker_branch = marker.get("value") if marker else None
    if marker_branch is not None and (
        not BRANCH.fullmatch(marker_branch)
        or any(char in marker_branch for char in "*?[]")
    ):
        raise EnrollmentError(
            f"{repository}/{environment} has an invalid ownership marker"
        )
    if current:
        policy = current.get("deployment_branch_policy") or {}
        if (
            policy.get("protected_branches") is not False
            or policy.get("custom_branch_policies") is not True
        ):
            raise EnrollmentError(
                f"{repository}/{environment} is not restricted to custom exact branches"
            )
    else:
        policy = {"protected_branches": False, "custom_branch_policies": True}
    policies_path = environment_path + "/deployment-branch-policies"
    existing = list(pages(gh, policies_path)) if current else []
    names = [item.get("name") for item in existing]
    if len(names) != len(set(names)):
        raise EnrollmentError(
            f"{repository}/{environment} has duplicate deployment branch policies"
        )
    if branch in names and marker_branch != branch:
        existing_branch = next(item for item in existing if item.get("name") == branch)
        if existing_branch.get("type") != "branch":
            raise EnrollmentError(
                f"{repository}/{environment} has an unowned exact-name policy; "
                "refusing to assume it is a branch"
            )
    extras = [item for item in existing if item.get("name") != branch]
    if extras and (
        marker_branch is None
        or any(item.get("name") != marker_branch for item in extras)
    ):
        raise EnrollmentError(
            f"{repository}/{environment} has unowned branch policies; "
            "refusing to broaden access"
        )
    if len(extras) > 1:
        raise EnrollmentError(
            f"{repository}/{environment} has multiple old policies; "
            "refusing automatic cleanup"
        )
    if not apply:
        return {
            "repository": repository,
            "environment": environment,
            "branch": branch,
            "action": "current"
            if not extras and branch in names and marker_branch == branch
            else "enroll",
        }
    protection_body = {}
    if current:
        for rule in current.get("protection_rules", []):
            kind = rule.get("type")
            if kind == "wait_timer":
                protection_body["wait_timer"] = rule["wait_timer"]
            elif kind == "required_reviewers":
                protection_body["reviewers"] = [
                    {"type": item["type"], "id": item["reviewer"]["id"]}
                    for item in rule.get("reviewers", [])
                ]
                protection_body["prevent_self_review"] = rule.get(
                    "prevent_self_review", False
                )
            else:
                raise EnrollmentError(
                    f"{repository}/{environment} has an unsupported protection rule"
                )
    body = {"deployment_branch_policy": policy, **protection_body}
    gh.api(environment_path, "PUT", body)
    actual = gh.api(environment_path)
    actual_policy = actual.get("deployment_branch_policy") or {}
    if (
        actual_policy.get("protected_branches") is not False
        or actual_policy.get("custom_branch_policies") is not True
    ):
        raise EnrollmentError(
            f"{repository}/{environment} branch restriction read-back failed"
        )
    for item in extras:
        gh.api(f"{policies_path}/{item['id']}", "DELETE")
    if branch not in names:
        gh.api(policies_path, "POST", {"name": branch, "type": "branch"})
    actual_names = [item.get("name") for item in pages(gh, policies_path)]
    if actual_names != [branch]:
        raise EnrollmentError(
            f"{repository}/{environment} exact branch restriction read-back failed"
        )
    actual = gh.api(environment_path)
    actual_rules = actual.get("protection_rules", [])
    actual_wait = next(
        (
            rule.get("wait_timer")
            for rule in actual_rules
            if rule.get("type") == "wait_timer"
        ),
        None,
    )
    if protection_body.get("wait_timer") != actual_wait:
        raise EnrollmentError(f"{repository}/{environment} wait timer read-back failed")
    if "reviewers" in protection_body:
        actual_review: dict[str, Any] = next(
            (rule for rule in actual_rules if rule.get("type") == "required_reviewers"),
            {},
        )
        reviewers = [
            {"type": item["type"], "id": item["reviewer"]["id"]}
            for item in actual_review.get("reviewers", [])
        ]
        if (
            reviewers != protection_body["reviewers"]
            or actual_review.get("prevent_self_review", False)
            != protection_body["prevent_self_review"]
        ):
            raise EnrollmentError(
                f"{repository}/{environment} reviewer protection read-back failed"
            )
    variable_body = {"name": branch_variable, "value": branch}
    variable_root = f"{environment_path}/variables"
    variable_path = f"{variable_root}/{branch_variable}"
    if marker:
        gh.api(variable_path, "PATCH", variable_body)
    else:
        gh.api(variable_root, "POST", variable_body)
    if gh.api(variable_path).get("value") != branch:
        raise EnrollmentError(
            f"{repository}/{environment} branch ownership read-back failed"
        )
    return {
        "repository": repository,
        "environment": environment,
        "branch": branch,
        "action": "enrolled",
    }


def template_repository(gh: Any, owner: str, repository: str, branch: str) -> bool:
    head = gh.api(f"repos/{repository}/commits/{quote(branch, safe='')}").get("sha")
    if not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise EnrollmentError(f"{repository} default branch has no verified commit")
    path = f"repos/{repository}/contents/{SOURCE}?ref={head}"
    content = gh.optional(path)
    if content is None:
        return False
    try:
        encoded = b"".join(content["content"].encode("ascii").split())
        config = json.loads(base64.b64decode(encoded, validate=True).decode("utf-8"))
    except (KeyError, TypeError, ValueError) as error:
        raise EnrollmentError(
            f"{repository} has invalid .agents/plugins/{SOURCE}"
        ) from error
    return (
        isinstance(config, dict)
        and config.get("schema_version") == 1
        and isinstance(config.get("repository"), str)
        and config["repository"].casefold() == repository.casefold()
    )


def inventory(gh: Any, owner: str) -> Iterator[str]:
    for repository in pages(gh, f"orgs/{owner}/repos?type=all"):
        if (
            repository.get("archived")
            or repository.get("fork")
            or (repository.get("owner") or {}).get("login", "").lower() != owner.lower()
        ):
            continue
        full_name = repository.get("full_name")
        if not isinstance(full_name, str) or full_name.count("/") != 1:
            raise EnrollmentError("GitHub returned an invalid repository identity")
        yield full_name


def has_repository_secret(gh: Any, repository: str, name: str) -> bool:
    return any(
        item.get("name") == name
        for item in pages(gh, f"repos/{repository}/actions/secrets")
    )


def reconcile_policy(gh: Any, repository: str, app_id: int) -> str:
    """Render the declared policy with the enrolled updater, using trusted code only."""
    branch = gh.api(f"repos/{repository}")["default_branch"]
    head = gh.api(f"repos/{repository}/commits/{quote(branch, safe='')}")["sha"]
    content = gh.optional(
        f"repos/{repository}/contents/.github/merge-policy.json?ref={head}"
    )
    if content is None:
        return "undeclared"
    script = (
        Path(__file__).resolve().parents[2] / "merge-policy/scripts/merge_policy.py"
    )
    spec = importlib.util.spec_from_file_location("enrollment_merge_policy", script)
    if spec is None or spec.loader is None:
        raise EnrollmentError("the trusted merge-policy implementation is missing")
    policy_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(policy_module)
    try:
        policy = policy_module.validate_policy(
            json.loads(base64.b64decode(content["content"]).decode("utf-8")),
            f"{repository}/.github/merge-policy.json",
        )
    except (KeyError, TypeError, ValueError, policy_module.PolicyError) as error:
        raise EnrollmentError(f"{repository} has an invalid merge policy") from error
    desired = policy_module.ruleset(policy, updater_app=app_id)
    rulesets = [
        item
        for item in pages(gh, f"repos/{repository}/rulesets")
        if item.get("name") == "merge-policy"
        and item.get("source_type", "Repository") == "Repository"
    ]
    if len(rulesets) > 1:
        raise EnrollmentError(f"{repository} has duplicate merge-policy rulesets")
    path = f"repos/{repository}/rulesets"
    if rulesets:
        path += f"/{rulesets[0]['id']}"
        if policy_module.matches_owned(gh.api(path), desired):
            return "current"
    actual = gh.api(path, "PUT" if rulesets else "POST", desired)
    if not isinstance(actual, dict) or not isinstance(actual.get("id"), int):
        raise EnrollmentError(f"{repository} merge-policy write has no identity")
    readback = gh.api(f"repos/{repository}/rulesets/{actual['id']}")
    if not policy_module.matches_owned(readback, desired):
        raise EnrollmentError(f"{repository} merge-policy read-back failed")
    return "updated" if rulesets else "created"


def enroll(
    gh: Any,
    owner: str,
    updater_app_id: int,
    updater_key: str,
    apply: bool = False,
    remove_legacy_secret: bool = False,
) -> list[dict[str, Any]]:
    if (
        not OWNER.fullmatch(owner)
        or not isinstance(updater_app_id, int)
        or updater_app_id <= 0
    ):
        raise EnrollmentError("invalid owner or updater App id")
    if apply and (not updater_key or "PRIVATE KEY" not in updater_key):
        raise EnrollmentError(
            "the updater App key must be supplied by the trusted owner or environment"
        )
    results = []
    for repository in inventory(gh, owner):
        metadata = gh.api(f"repos/{repository}")
        branch = metadata.get("default_branch")
        if not isinstance(branch, str) or not branch:
            raise EnrollmentError(f"{repository} has no default branch")
        if not template_repository(gh, owner, repository, branch):
            continue
        result = protected(gh, repository, branch, apply)
        result["app_id"] = updater_app_id
        results.append(result)
        if apply:
            gh.secret(repository, updater_key)
            stored = gh.api(
                f"repos/{repository}/environments/{quote(ENVIRONMENT, safe='')}/secrets"
            )
            if not any(
                item.get("name") == SECRET for item in stored.get("secrets", [])
            ):
                raise EnrollmentError(
                    f"{repository}/{ENVIRONMENT} secret metadata read-back failed"
                )
            if has_repository_secret(gh, repository, SECRET):
                if not remove_legacy_secret:
                    raise EnrollmentError(
                        f"{repository} has an exposed repository-level {SECRET}; "
                        "owner cleanup required"
                    )
                gh.api(f"repos/{repository}/actions/secrets/{SECRET}", "DELETE")
                if has_repository_secret(gh, repository, SECRET):
                    raise EnrollmentError(
                        f"{repository} repository-level {SECRET} removal "
                        "read-back failed"
                    )
            result["merge_policy"] = reconcile_policy(gh, repository, updater_app_id)
    return results


def automation_guard(
    gh: Any,
    owner: str,
    repository: str,
    updater_client_id: str,
    updater_app_id: int,
    environment: Mapping[str, str],
) -> None:
    expected = f"{owner}/{repository}"
    if (
        environment.get("GITHUB_ACTIONS") != "true"
        or environment.get("GITHUB_REPOSITORY", "").lower() != expected.lower()
        or environment.get("EXPECTED_ENROLLMENT_OWNER", "").lower() != owner.lower()
        or environment.get("GITHUB_EVENT_NAME")
        not in {"schedule", "workflow_dispatch", "push"}
    ):
        raise EnrollmentError(
            "apply is restricted to the trusted central GitHub Actions workflow"
        )
    branch = gh.api(f"repos/{expected}").get("default_branch")
    if environment.get("GITHUB_REF") != f"refs/heads/{branch}":
        raise EnrollmentError(
            "apply requires the central repository's current default branch"
        )
    if not environment.get("GH_TOKEN"):
        raise EnrollmentError("the enrollment controller installation token is missing")
    if environment.get("ENROLLMENT_APP_ID") is None:
        raise EnrollmentError("the enrolled controller App id is missing")
    try:
        controller_id = int(environment["ENROLLMENT_APP_ID"])
    except ValueError as error:
        raise EnrollmentError("the enrolled controller App id is invalid") from error
    controller_slug = f"{owner.lower()}-enrollment-controller"
    current_app = gh.api(f"apps/{controller_slug}")
    if (
        current_app.get("id") != controller_id
        or current_app.get("slug") != controller_slug
        or (current_app.get("owner") or {}).get("login", "").lower() != owner.lower()
        or not environment.get("ENROLLMENT_APP_CLIENT_ID")
        or current_app.get("client_id") != environment["ENROLLMENT_APP_CLIENT_ID"]
    ):
        raise EnrollmentError(
            "the controller App does not match its central repository variables"
        )
    if (
        environment.get("UPDATE_APP_CLIENT_ID") != updater_client_id
        or not updater_client_id
        or updater_app_id <= 0
    ):
        raise EnrollmentError(
            "the updater App identity does not match the central repository variables"
        )


def main(
    argv: list[str] | None = None,
    environment: Mapping[str, str] = os.environ,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--repository", default="github-actions")
    parser.add_argument("--updater-client-id", required=True)
    parser.add_argument("--updater-app-id", required=True, type=int)
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        if not OWNER.fullmatch(arguments.owner):
            raise EnrollmentError("--owner must be a GitHub organization login")
        if arguments.apply:
            automation_guard(
                GitHub(run),
                arguments.owner,
                arguments.repository,
                arguments.updater_client_id,
                arguments.updater_app_id,
                environment,
            )
        key = environment.get("UPDATER_PRIVATE_KEY")
        if arguments.apply and not key:
            raise EnrollmentError(
                "the central protected environment did not provide UPDATER_PRIVATE_KEY"
            )
        results = enroll(
            GitHub(run),
            arguments.owner,
            arguments.updater_app_id,
            key or "preview",
            arguments.apply,
        )
        for result in results:
            print(json.dumps(result, sort_keys=True))
        print(
            f"{len(results)} Template repositories "
            f"{'enrolled' if arguments.apply else 'eligible'}"
        )
    except EnrollmentError as error:
        print(f"enrollment: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
