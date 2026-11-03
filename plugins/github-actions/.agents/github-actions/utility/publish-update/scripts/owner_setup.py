#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["cryptography==50.0.2"]
# ///
"""Configure the protected publisher and enrollment GitHub Apps once.

Requires Python 3.12+, uv and the GitHub CLI.

Without --apply it only describes the changes. With --apply, run by an
organization owner in their own terminal, it creates or finds
`<owner>-pin-updater` and `<owner>-enrollment-controller`. Their keys are stored
as environment secrets restricted to the exact default branch. The updater key
is copied only to the `update-pins` environments of same-owner repositories
that select Template.
"""

import argparse
import html
import importlib.util
import json
import os
import re
import secrets
import subprocess
import sys
import time
import webbrowser
from collections.abc import Callable, Mapping
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

PERMISSIONS = {"contents": "write", "pull_requests": "write", "workflows": "write"}
CONTROLLER_PERMISSIONS = {
    "contents": "read",
    "administration": "write",
    "environments": "write",
    "secrets": "read",
}
VARIABLE = "UPDATE_APP_CLIENT_ID"
SECRET = "UPDATE_APP_PRIVATE_KEY"
CONTROLLER_VARIABLE = "ENROLLMENT_APP_CLIENT_ID"
CENTRAL_ENVIRONMENT = "update-enrollment"
CENTRAL_BRANCH_VARIABLE = "TJ_AGENTS_ENROLLMENT_BRANCH"
GH_TIMEOUT_SECONDS = 90
WAIT_SECONDS = 300
POLL_SECONDS = 5
if sys.platform == "win32":
    NO_WINDOW = subprocess.CREATE_NO_WINDOW
else:
    NO_WINDOW = 0
OWNER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
PEM = re.compile(
    r"-----BEGIN (?:RSA )?PRIVATE KEY-----\r?\n"
    r"[A-Za-z0-9+/=\r\n]+-----END (?:RSA )?PRIVATE KEY-----\s*"
)
ENROLLMENT = Path(__file__).resolve().with_name("enrollment.py")


@lru_cache(maxsize=1)
def load_enrollment() -> Any:
    spec = importlib.util.spec_from_file_location("owner_enrollment", ENROLLMENT)
    if spec is None or spec.loader is None:
        raise SetupError("could not load trusted enrollment helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SetupError(Exception):
    pass


class GitHub:
    def __init__(
        self, run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run
    ) -> None:
        self.run = run

    def call(
        self, arguments: list[str], data: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        try:
            if arguments[0] == "api":
                command = ["gh", "api", "--hostname", "github.com", *arguments[1:]]
            else:
                command = ["gh", *arguments]
                if arguments[:2] == ["secret", "set"] and "--repo" in command:
                    repository_index = command.index("--repo") + 1
                    command[repository_index] = (
                        f"github.com/{command[repository_index]}"
                    )
            return self.run(
                command,
                input=data,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=GH_TIMEOUT_SECONDS,
                check=False,
                creationflags=NO_WINDOW,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise SetupError(f"gh {' '.join(arguments[:3])} failed: {error}") from error

    def api(
        self, path: str, method: str = "GET", body: Mapping[str, Any] | None = None
    ) -> Any:
        arguments = ["api", path, "--method", method]
        data = None
        if body is not None:
            arguments += ["--input", "-"]
            data = json.dumps(body)
        result = self.call(arguments, data)
        if result.returncode:
            raise SetupError(
                f"gh api {method} {path} failed: "
                f"{(result.stderr or result.stdout).strip()[:300]}"
            )
        return json.loads(result.stdout) if result.stdout.strip() else None

    def optional(self, path: str, absent: tuple[str, ...] = ("HTTP 404",)) -> Any:
        result = self.call(["api", path, "--method", "GET"])
        if result.returncode == 0:
            return json.loads(result.stdout) if result.stdout.strip() else None
        if any(marker in result.stderr for marker in absent):
            return None
        raise SetupError(
            f"gh api GET {path} failed: "
            f"{(result.stderr or result.stdout).strip()[:300]}"
        )

    def set_secret(
        self, repository: str, environment: str, secret: str, value: str
    ) -> None:
        result = self.call(
            ["secret", "set", secret, "--repo", repository, "--env", environment], value
        )
        if result.returncode:
            raise SetupError(f"could not set {secret} for {repository}/{environment}")

    def remove_org_secret(self, owner: str, secret: str) -> None:
        result = self.call(
            ["api", f"orgs/{owner}/actions/secrets/{secret}", "--method", "DELETE"]
        )
        if result.returncode:
            raise SetupError(f"could not remove exposed organization secret {secret}")


def app_slug(owner: str, role: str = "pin-updater") -> str:
    return f"{owner.lower()}-{role}"


def controller_slug(owner: str) -> str:
    return app_slug(owner, "enrollment-controller")


def owner_only(environment: Mapping[str, str] = os.environ) -> None:
    if environment.get("TJ_AGENT") == "1":
        raise SetupError(
            "owner setup must run in the owner's own terminal; "
            "agent execution is refused"
        )
    present = [
        name
        for name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_CONFIG_DIR")
        if environment.get(name)
    ]
    if present:
        raise SetupError(
            "unset " + ", ".join(present) + " so gh uses the owner's own sign-in"
        )


def granted(permissions: Mapping[str, str] | None) -> dict[str, str]:
    return {
        key: value for key, value in (permissions or {}).items() if key != "metadata"
    }


def default_branch_ruleset(ruleset: Mapping[str, Any]) -> bool:
    include = ((ruleset.get("conditions") or {}).get("ref_name") or {}).get(
        "include"
    ) or []
    return ruleset.get("target", "branch") == "branch" and bool(
        {"~DEFAULT_BRANCH", "~ALL"} & set(include)
    )


def bypasses(ruleset: Mapping[str, Any], app_id: int) -> bool:
    return any(
        actor.get("actor_type") == "Integration"
        and actor.get("actor_id") == app_id
        and actor.get("bypass_mode") == "always"
        for actor in ruleset.get("bypass_actors") or []
    )


def discover(gh: GitHub, owner: str) -> dict[str, Any]:
    login = gh.api("user")["login"]
    membership = gh.optional(f"user/memberships/orgs/{owner}")
    if (
        not membership
        or membership.get("role") != "admin"
        or membership.get("state") != "active"
    ):
        raise SetupError(f"{login} is not an active owner of {owner}")
    installations, page = [], 1
    while True:
        batch = gh.api(f"orgs/{owner}/installations?per_page=100&page={page}").get(
            "installations", []
        )
        installations.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    rulesets, page = [], 1
    while True:
        batch = gh.api(f"orgs/{owner}/rulesets?per_page=100&page={page}")
        rulesets.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    updater, controller = app_slug(owner), controller_slug(owner)
    return {
        "login": login,
        "org_id": gh.api(f"orgs/{owner}")["id"],
        "slug": updater,
        "controller_slug": controller,
        "app": gh.optional(f"apps/{updater}"),
        "controller": gh.optional(f"apps/{controller}"),
        "installation": next(
            (item for item in installations if item.get("app_slug") == updater), None
        ),
        "controller_installation": next(
            (item for item in installations if item.get("app_slug") == controller), None
        ),
        "variable": gh.optional(f"orgs/{owner}/actions/variables/{VARIABLE}"),
        "legacy_org_secret": gh.optional(f"orgs/{owner}/actions/secrets/{SECRET}"),
        "legacy_repositories": load_enrollment().legacy_key_locations(
            load_enrollment().GitHub(gh.run), owner
        ),
        "rulesets": rulesets,
    }


def check_app(
    app: Mapping[str, Any], owner: str, permissions: Mapping[str, str]
) -> None:
    if (app.get("owner") or {}).get("login", "").lower() != owner.lower():
        raise SetupError(f"{app.get('slug')} must be owned by {owner}")
    if granted(app.get("permissions")) != permissions:
        raise SetupError(
            f"{app.get('slug')} must have exactly {permissions}: "
            f"https://github.com/organizations/{owner}/settings/apps/"
            f"{app.get('slug')}/permissions"
        )


def wait(
    condition: Callable[[], Any],
    open_url: Callable[[str], Any],
    url: str,
    message: str,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Any:
    value = condition()
    if value:
        return value
    print(message + ": " + url, flush=True)
    open_url(url)
    deadline = clock() + WAIT_SECONDS
    while not value and clock() < deadline:
        sleep(POLL_SECONDS)
        value = condition()
    if not value:
        raise SetupError(
            message + " was not completed within 5 minutes; rerun to resume"
        )
    return value


def installations(gh: GitHub, owner: str) -> Any:
    page = 1
    while True:
        batch = gh.api(f"orgs/{owner}/installations?per_page=100&page={page}").get(
            "installations", []
        )
        yield from batch
        if len(batch) < 100:
            return
        page += 1


def ensure_installation(
    gh: GitHub,
    owner: str,
    slug: str,
    app_id: int,
    permissions: Mapping[str, str],
    open_url: Callable[[str], Any],
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> Any:
    org_id = gh.api(f"orgs/{owner}")["id"]

    def installation() -> dict[str, Any] | None:
        return next(
            (item for item in installations(gh, owner) if item.get("app_slug") == slug),
            None,
        )

    current = wait(
        installation,
        open_url,
        f"https://github.com/apps/{slug}/installations/new/permissions?"
        f"target_id={org_id}",
        f"Install {slug} on All repositories of {owner}",
        sleep,
        clock,
    )
    settings = (
        f"https://github.com/organizations/{owner}/settings/installations/"
        f"{current['id']}"
    )

    def complete() -> dict[str, Any] | None:
        item = installation()
        return (
            item
            if (
                item
                and item.get("repository_selection") == "all"
                and not item.get("suspended_at")
                and granted(item.get("permissions")) == permissions
                and item.get("app_id") == app_id
            )
            else None
        )

    return wait(
        complete,
        open_url,
        settings,
        f"Set {slug} to All repositories, accept its permissions and unsuspend it",
        sleep,
        clock,
    )


def ensure_variable(gh: GitHub, owner: str, client_id: str, variable: Any) -> None:
    if variable and variable.get("value") != client_id:
        raise SetupError(
            f"organization variable {VARIABLE} names a different App; "
            "preserved for review"
        )
    body = {"name": VARIABLE, "value": client_id, "visibility": "all"}
    if variable is None:
        gh.api(f"orgs/{owner}/actions/variables", "POST", body)
    elif variable.get("visibility") != "all":
        gh.api(f"orgs/{owner}/actions/variables/{VARIABLE}", "PATCH", body)
    readback = gh.api(f"orgs/{owner}/actions/variables/{VARIABLE}")
    if readback.get("value") != client_id or readback.get("visibility") != "all":
        raise SetupError(f"organization variable {VARIABLE} read-back failed")


def read_key(text: str) -> str:
    if not PEM.fullmatch(text.strip() + "\n"):
        raise SetupError("the supplied private key is not a PEM private key")
    return text.strip() + "\n"


def create_app(
    gh: GitHub,
    owner: str,
    slug: str,
    permissions: Mapping[str, str],
    open_url: Callable[[str], Any],
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    nonce = secrets.token_urlsafe(32)
    received: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *arguments: Any) -> None:
            pass

        def respond(self, text: str, code: int = 200) -> None:
            body = text.encode("utf-8")
            self.send_response(code)
            for name, value in (
                ("Content-Type", "text/html; charset=utf-8"),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store"),
                ("Referrer-Policy", "no-referrer"),
            ):
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            if self.headers.get("Host") != address or not parsed.path.startswith(
                f"/{nonce}/"
            ):
                self.respond("Invalid setup request.", 403)
            elif parsed.path.endswith("/start"):
                manifest = {
                    "name": slug,
                    "url": f"https://github.com/{owner}",
                    "public": False,
                    "redirect_url": base + "/created",
                    "hook_attributes": {
                        "url": f"https://github.com/{owner}",
                        "active": False,
                    },
                    "default_permissions": permissions,
                    "default_events": [],
                }
                self.respond(
                    f'<form method="post" action="https://github.com/organizations/'
                    f'{quote(owner)}/settings/apps/new?state={nonce}">'
                    '<input type="hidden" name="manifest" value="'
                    f'{html.escape(json.dumps(manifest), quote=True)}">'
                    f"<button>Create {html.escape(slug)}"
                    "</button></form><script>document.forms[0].submit();</script>"
                )
            elif (
                parsed.path.endswith("/created")
                and query.get("state") == [nonce]
                and re.fullmatch(
                    r"[A-Za-z0-9_-]{1,200}", (query.get("code") or [""])[0]
                )
            ):
                received["code"] = query["code"][0]
                self.respond("App created. Continue in the terminal.")
            else:
                self.respond("Invalid or completed setup request.", 400)

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        address = f"127.0.0.1:{server.server_port}"
        base = f"http://{address}/{nonce}"
        server.timeout = 1
        print(f"Create the private {slug} App on GitHub: {base}/start", flush=True)
        open_url(base + "/start")
        deadline = clock() + WAIT_SECONDS
        while "code" not in received and clock() < deadline:
            server.handle_request()
    if "code" not in received:
        raise SetupError(
            "GitHub did not return the App registration within 5 minutes; "
            "rerun to resume"
        )
    app = gh.api(f"app-manifests/{received['code']}/conversions", "POST")
    if app.get("slug") != slug:
        raise SetupError(
            f"GitHub created {app.get('slug')}, not {slug}; rename or delete it, "
            "then rerun"
        )
    if not isinstance(app, dict):
        raise SetupError("GitHub returned an invalid App manifest conversion")
    return app


def app_key(
    owner: str,
    slug: str,
    supplied: str | None,
    created: Mapping[str, Any] | None,
    open_url: Callable[[str], Any],
    prompt: Callable[[str], str],
) -> str:
    if supplied:
        return read_key(supplied)
    if created and created.get("pem"):
        return read_key(created["pem"])
    url = f"https://github.com/organizations/{owner}/settings/apps/{slug}#private-key"
    print(
        f"Generate a private key for {slug} (Private keys > Generate a private key): "
        f"{url}",
        flush=True,
    )
    open_url(url)
    path = prompt(f"Path to the downloaded {slug} .pem file: ").strip().strip('"')
    try:
        return read_key(Path(path).expanduser().read_text(encoding="utf-8"))
    except OSError as error:
        raise SetupError(f"cannot read {path}: {error.strerror}") from error


def set_repo_variable(gh: GitHub, repository: str, name: str, value: str) -> None:
    path = f"repos/{repository}/actions/variables/{name}"
    current = gh.optional(path)
    body = {"name": name, "value": value}
    if current is None:
        gh.api(f"repos/{repository}/actions/variables", "POST", body)
    elif current.get("value") != value:
        gh.api(path, "PATCH", body)
    if gh.api(path).get("value") != value:
        raise SetupError(f"{repository} variable {name} read-back failed")


def put_env_secret(
    gh: GitHub, repository: str, environment: str, name: str, value: str
) -> None:
    gh.set_secret(repository, environment, name, value)
    path = f"repos/{repository}/environments/{quote(environment, safe='')}/secrets"
    if not any(
        item.get("name") == name for item in (gh.api(path) or {}).get("secrets", [])
    ):
        raise SetupError(f"{repository}/{environment} secret metadata read-back failed")


def ensure_org_rulesets(
    gh: GitHub, owner: str, app_id: int, rulesets: list[Mapping[str, Any]]
) -> list[Any]:
    covered: list[Any] = []
    for summary in rulesets:
        path = f"orgs/{owner}/rulesets/{summary['id']}"
        ruleset = gh.api(path)
        if not default_branch_ruleset(ruleset):
            continue
        if not bypasses(ruleset, app_id):
            actors = [
                actor
                for actor in ruleset.get("bypass_actors") or []
                if not (
                    actor.get("actor_type") == "Integration"
                    and actor.get("actor_id") == app_id
                )
            ]
            gh.api(
                path,
                "PUT",
                {
                    **{
                        key: ruleset[key]
                        for key in (
                            "name",
                            "target",
                            "enforcement",
                            "conditions",
                            "rules",
                        )
                        if key in ruleset
                    },
                    "bypass_actors": [
                        *actors,
                        {
                            "actor_id": app_id,
                            "actor_type": "Integration",
                            "bypass_mode": "always",
                        },
                    ],
                },
            )
            if not bypasses(gh.api(path), app_id):
                raise SetupError(
                    f"organization ruleset {ruleset.get('name')} bypass "
                    "read-back failed"
                )
        covered.append(ruleset.get("name"))
    return covered


def setup(
    owner: str,
    gh: GitHub,
    key: str | None = None,
    open_url: Callable[[str], Any] = webbrowser.open,
    prompt: Callable[[str], str] = input,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    controller_key: str | None = None,
) -> None:
    state = discover(gh, owner)
    legacy_rotation = state["legacy_org_secret"] is not None or bool(
        state.get("legacy_repositories")
    )
    if legacy_rotation:
        url = (
            f"https://github.com/organizations/{owner}/settings/apps/"
            f"{state['slug']}#private-key"
        )
        print(
            "An unprotected publisher key was exposed to repository branches. "
            "Revoke previously distributed publisher keys on GitHub and supply a "
            "fresh key; removing the secret alone does not revoke copied keys.",
            flush=True,
        )
        open_url(url)
        if (
            prompt("Type the updater App slug after revoking old keys: ").strip()
            != state["slug"]
        ):
            raise SetupError(
                "owner key-rotation confirmation is required before migration"
            )
    updater_slug, enroll_slug = state["slug"], state["controller_slug"]
    updater_created = None
    enroll_created = None
    updater = state["app"]
    controller = state["controller"]
    if updater is None:
        updater_created = create_app(
            gh, owner, updater_slug, PERMISSIONS, open_url, clock
        )
        updater = gh.api(f"apps/{updater_slug}")
    if controller is None:
        enroll_created = create_app(
            gh, owner, enroll_slug, CONTROLLER_PERMISSIONS, open_url, clock
        )
        controller = gh.api(f"apps/{enroll_slug}")
    check_app(updater, owner, PERMISSIONS)
    check_app(controller, owner, CONTROLLER_PERMISSIONS)
    updater_key = app_key(owner, updater_slug, key, updater_created, open_url, prompt)
    controller_key = app_key(
        owner, enroll_slug, controller_key, enroll_created, open_url, prompt
    )
    enrollment = load_enrollment()
    enrollment.verify_app_key(owner, updater["id"], updater["client_id"], updater_key)
    enrollment.verify_app_key(
        owner, controller["id"], controller["client_id"], controller_key
    )
    ensure_installation(
        gh, owner, updater_slug, updater["id"], PERMISSIONS, open_url, sleep, clock
    )
    ensure_installation(
        gh,
        owner,
        enroll_slug,
        controller["id"],
        CONTROLLER_PERMISSIONS,
        open_url,
        sleep,
        clock,
    )
    ensure_variable(gh, owner, updater["client_id"], state["variable"])
    central = f"{owner}/github-actions"
    central_branch = gh.api(f"repos/{central}").get("default_branch")
    if not isinstance(central_branch, str) or not central_branch:
        raise SetupError(f"{central} has no default branch")
    for environment, variable in (
        ("update-pins", "TJ_AGENTS_UPDATE_PINS_BRANCH"),
        (CENTRAL_ENVIRONMENT, CENTRAL_BRANCH_VARIABLE),
    ):
        enrollment.protected(
            enrollment.GitHub(gh.run),
            central,
            central_branch,
            True,
            environment,
            variable,
        )
    set_repo_variable(gh, central, CONTROLLER_VARIABLE, controller["client_id"])
    set_repo_variable(gh, central, "ENROLLMENT_APP_ID", str(controller["id"]))
    set_repo_variable(gh, central, "UPDATE_APP_ID", str(updater["id"]))
    put_env_secret(gh, central, CENTRAL_ENVIRONMENT, SECRET, updater_key)
    put_env_secret(
        gh, central, CENTRAL_ENVIRONMENT, "ENROLLMENT_APP_PRIVATE_KEY", controller_key
    )
    results = enrollment.enroll(
        enrollment.GitHub(gh.run),
        owner,
        updater["id"],
        updater_key,
        apply=True,
        remove_legacy_secret=True,
        grant_bypass=False,
        allow_exposed=legacy_rotation,
    )
    if state["legacy_org_secret"] is not None:
        gh.remove_org_secret(owner, SECRET)
        if gh.optional(f"orgs/{owner}/actions/secrets/{SECRET}") is not None:
            raise SetupError(
                f"exposed organization secret {SECRET} removal read-back failed"
            )
    covered = ensure_org_rulesets(gh, owner, updater["id"], state["rulesets"])
    for result in results:
        result["merge_policy"] = enrollment.reconcile_policy(
            enrollment.GitHub(gh.run), result["repository"], updater["id"]
        )
    print(
        f"Owner setup complete: {len(results)} Template repositories enrolled; "
        f"org rulesets {covered}",
        flush=True,
    )


def preview(owner: str) -> None:
    print(f"Preview for {owner} (run with --apply as an organization owner):")
    print(
        f"- configure {app_slug(owner)} with contents, pull requests and "
        "workflows write"
    )
    print(
        f"- configure {controller_slug(owner)} with contents read, administration "
        "and environments write"
    )
    print(
        "- install both Apps on all repositories; the enrollment App can set up "
        "protected environments only"
    )
    print(
        f"- restrict {owner}/github-actions environments to its exact default "
        "branch before adding either key"
    )
    print(
        "- copy only the updater key to update-pins on repositories whose default "
        "branch selects Template"
    )
    print(
        f"- store the enrollment key only in {owner}/github-actions/update-enrollment"
    )
    print(
        "- add the updater as an org-ruleset bypass; repository bypasses apply "
        "only to enrolled Template repos"
    )
    print("Nothing is written until --apply is supplied.")


def main(
    argv: list[str] | None = None,
    environment: Mapping[str, str] = os.environ,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    stdin: Any = sys.stdin,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--updater-key-file", type=Path)
    parser.add_argument("--enrollment-key-file", type=Path)
    arguments = parser.parse_args(argv)
    enrollment = load_enrollment()
    try:
        if not OWNER.fullmatch(arguments.owner):
            raise SetupError("--owner must be a GitHub organization login")
        if not arguments.apply:
            preview(arguments.owner)
            return 0
        owner_only(environment)
        updater_key = None
        enrollment_key = None
        if arguments.updater_key_file:
            try:
                updater_key = read_key(
                    arguments.updater_key_file.expanduser().read_text(encoding="utf-8")
                )
            except OSError as error:
                raise SetupError(
                    f"cannot read {arguments.updater_key_file}: {error.strerror}"
                ) from error
        if arguments.enrollment_key_file:
            try:
                enrollment_key = read_key(
                    arguments.enrollment_key_file.expanduser().read_text(
                        encoding="utf-8"
                    )
                )
            except OSError as error:
                raise SetupError(
                    f"cannot read {arguments.enrollment_key_file}: {error.strerror}"
                ) from error
        setup(
            arguments.owner,
            GitHub(run),
            updater_key,
            open_url=webbrowser.open,
            controller_key=enrollment_key,
        )
    except (SetupError, enrollment.EnrollmentError) as error:
        print(f"owner_setup: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
