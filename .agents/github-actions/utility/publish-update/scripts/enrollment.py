#!/usr/bin/env python3
"""Enroll explicitly eligible repositories in protected updater publication.

Requires Python 3.12+, the locked project environment and the GitHub CLI.
"""

import argparse
import base64
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

sys.dont_write_bytecode = True

ENVIRONMENT = "update-pins"
SECRET = "UPDATE_APP_PRIVATE_KEY"
VARIABLE = "UPDATE_APP_CLIENT_ID"
SOURCE = ".agents/plugins/template.json"
DECLARATION = ".github/update-enrollment.json"
BRANCH_VARIABLE = "TJ_AGENTS_UPDATE_PINS_BRANCH"
TIMEOUT = 90
if sys.platform == "win32":
    NO_WINDOW = subprocess.CREATE_NO_WINDOW
else:
    NO_WINDOW = 0
OWNER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
BRANCH = re.compile(r"[A-Za-z0-9._/-]{1,200}")


class EnrollmentError(Exception):
    pass


def verify_app_key(
    owner: str,
    app_id: int,
    client_id: str,
    key: str,
    opener: Callable[..., Any] = urlopen,
    clock: Callable[[], float] = time.time,
) -> None:
    """Authenticate the in-memory PEM as its intended App before distributing it."""
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
    except ImportError as error:
        raise EnrollmentError(
            "Use the locked uv environment for App key validation"
        ) from error

    def encode(value: bytes) -> bytes:
        return base64.urlsafe_b64encode(value).rstrip(b"=")

    try:
        private_key = serialization.load_pem_private_key(key.encode(), password=None)
        if not isinstance(private_key, rsa.RSAPrivateKey):
            raise ValueError("GitHub App keys must use RSA")
        now = int(clock())
        claims = {"iat": now - 60, "exp": now + 300, "iss": client_id}
        message = b".".join(
            (
                encode(b'{"alg":"RS256","typ":"JWT"}'),
                encode(json.dumps(claims).encode()),
            )
        )
        signature = private_key.sign(message, padding.PKCS1v15(), hashes.SHA256())
        token = (message + b"." + encode(signature)).decode("ascii")
        request = Request(
            "https://api.github.com/app",
            headers={
                "Authorization": "Bearer " + token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with opener(request, timeout=TIMEOUT) as response:
            actual = json.loads(response.read(1024 * 1024))
        if (
            not isinstance(actual, dict)
            or actual.get("id") != app_id
            or actual.get("client_id") != client_id
            or (actual.get("owner") or {}).get("login", "").casefold()
            != owner.casefold()
        ):
            raise ValueError("App identity mismatch")
    except (ValueError, TypeError, URLError) as error:
        raise EnrollmentError(
            f"The supplied key cannot authenticate as App {app_id}; "
            "no key was distributed"
        ) from error


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
    allow_exposed: bool = False,
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
        policy = current.get("deployment_branch_policy")
        if policy is None:
            # GitHub creates an empty environment when CI first references its name.
            secrets = list(pages(gh, environment_path + "/secrets"))
            if secrets and (
                not allow_exposed or any(item.get("name") != SECRET for item in secrets)
            ):
                raise EnrollmentError(
                    f"{repository}/{environment} already exposes secrets; "
                    "owner credential rotation is required before enrollment"
                )
            policy = {"protected_branches": False, "custom_branch_policies": True}
        elif (
            policy.get("protected_branches") is not False
            or policy.get("custom_branch_policies") is not True
        ):
            raise EnrollmentError(
                f"{repository}/{environment} is not restricted to custom exact branches"
            )
    else:
        policy = {"protected_branches": False, "custom_branch_policies": True}
    policies_path = environment_path + "/deployment-branch-policies"
    existing = (
        list(pages(gh, policies_path))
        if current and current.get("deployment_branch_policy") is not None
        else []
    )
    names = [item.get("name") for item in existing]
    if len(names) != len(set(names)):
        raise EnrollmentError(
            f"{repository}/{environment} has duplicate deployment branch policies"
        )
    if any(item.get("type") != "branch" for item in existing):
        raise EnrollmentError(
            f"{repository}/{environment} must use exact branch policies; "
            "tags and unspecified policy types are refused"
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
            elif kind == "branch_policy":
                # A read-only projection of deployment_branch_policy, not an input.
                continue
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
    actual_branches = list(pages(gh, policies_path))
    if (
        len(actual_branches) != 1
        or actual_branches[0].get("name") != branch
        or actual_branches[0].get("type") != "branch"
    ):
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


def _read_json_content(gh: Any, repository: str, path: str, head: str) -> Any | None:
    content = gh.optional(f"repos/{repository}/contents/{path}?ref={head}")
    if content is None:
        return None
    try:
        encoded = b"".join(content["content"].encode("ascii").split())
        return json.loads(base64.b64decode(encoded, validate=True).decode("utf-8"))
    except (KeyError, TypeError, ValueError) as error:
        raise EnrollmentError(f"{repository} has invalid {path}") from error


def eligible_repository(
    gh: Any,
    owner: str,
    repository: str,
    branch: str,
    metadata: Mapping[str, Any] | None = None,
) -> bool:
    """Check both enrollment declarations at one verified default-branch SHA."""
    actual = metadata or gh.api(f"repos/{repository}")
    full_name = actual.get("full_name")
    actual_owner = actual.get("owner")
    if (
        not isinstance(full_name, str)
        or full_name.casefold() != repository.casefold()
        or not isinstance(actual_owner, dict)
        or not isinstance(actual_owner.get("login"), str)
        or actual_owner["login"].casefold() != owner.casefold()
        or actual.get("fork")
        or actual.get("archived")
        or actual.get("default_branch") != branch
    ):
        return False
    head = gh.api(f"repos/{repository}/commits/{quote(branch, safe='')}").get("sha")
    if not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise EnrollmentError(f"{repository} default branch has no verified commit")
    template = _read_json_content(gh, repository, SOURCE, head)
    declaration = _read_json_content(gh, repository, DECLARATION, head)
    selected_template = (
        isinstance(template, dict)
        and type(template.get("schema_version")) is int
        and template.get("schema_version") == 1
        and isinstance(template.get("repository"), str)
        and template["repository"].casefold() == full_name.casefold()
    )
    selected_custom = (
        isinstance(declaration, dict)
        and set(declaration) == {"schema_version", "repository"}
        and type(declaration.get("schema_version")) is int
        and declaration.get("schema_version") == 1
        and declaration.get("repository") == full_name
    )
    return selected_template or selected_custom


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


def legacy_key_locations(
    gh: Any, owner: str, progress: Callable[[str], None] | None = None
) -> list[str]:
    """Inventory exposed publisher keys without retrieving any secret value."""
    exposed = []
    for repository in inventory(gh, owner):
        if progress is not None:
            progress(f"Checking updater eligibility and exposed keys in {repository}")
        metadata = gh.api(f"repos/{repository}")
        branch = metadata.get("default_branch")
        if not isinstance(branch, str) or not eligible_repository(
            gh, owner, repository, branch, metadata
        ):
            continue
        if has_repository_secret(gh, repository, SECRET):
            exposed.append(repository)
        path = f"repos/{repository}/environments/{ENVIRONMENT}"
        environment = gh.optional(path)
        if (
            environment
            and environment.get("deployment_branch_policy") is None
            and any(item.get("name") == SECRET for item in pages(gh, path + "/secrets"))
        ):
            exposed.append(repository + "/" + ENVIRONMENT)
    return exposed


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
    grant_bypass: bool = True,
    allow_exposed: bool = False,
    progress: Callable[[str], None] | None = None,
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
        if progress is not None:
            progress(f"Checking protected enrollment for {repository}")
        metadata = gh.api(f"repos/{repository}")
        branch = metadata.get("default_branch")
        if not isinstance(branch, str) or not branch:
            raise EnrollmentError(f"{repository} has no default branch")
        if not eligible_repository(gh, owner, repository, branch, metadata):
            continue
        result = protected(gh, repository, branch, apply, allow_exposed=allow_exposed)
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
    if apply and grant_bypass:
        for result in results:
            result["merge_policy"] = reconcile_policy(
                gh, result["repository"], updater_app_id
            )
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


def write_matrix_output(path: Path, owner: str, results: list[dict[str, Any]]) -> None:
    names = []
    for result in results:
        repository = result.get("repository")
        if (
            not isinstance(repository, str)
            or repository.count("/") != 1
            or repository.split("/", 1)[0].casefold() != owner.casefold()
            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", repository.split("/", 1)[1])
        ):
            raise EnrollmentError(
                "eligible repository identity cannot be written to the matrix"
            )
        names.append(repository.split("/", 1)[1])
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(
            "repositories="
            + json.dumps(sorted(set(names)), separators=(",", ":"))
            + "\n"
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
    parser.add_argument("--matrix-output", type=Path)
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
        if arguments.apply:
            verify_app_key(
                arguments.owner,
                arguments.updater_app_id,
                arguments.updater_client_id,
                key or "",
            )
        results = enroll(
            GitHub(run),
            arguments.owner,
            arguments.updater_app_id,
            key or "preview",
            arguments.apply,
        )
        if arguments.matrix_output:
            write_matrix_output(arguments.matrix_output, arguments.owner, results)
        for result in results:
            print(json.dumps(result, sort_keys=True))
        print(
            f"{len(results)} eligible repositories "
            f"{'enrolled' if arguments.apply else 'selected'}"
        )
    except EnrollmentError as error:
        print(f"enrollment: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
