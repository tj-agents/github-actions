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
that explicitly select updater publication.
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
from datetime import UTC, datetime
from enum import StrEnum
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, TypedDict
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


class SetupState(StrEnum):
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class SetupAction(TypedDict):
    kind: str
    summary: str
    locations: list[str]
    steps: list[str]
    url: str | None


def safe_diagnostic(message: str) -> str:
    message = re.sub(
        r"app-manifests/[^/\s]+/conversions",
        "app-manifests/[redacted]/conversions",
        message,
    )
    message = re.sub(
        r"-----BEGIN (?:RSA )?PRIVATE KEY-----.*?-----END (?:RSA )?PRIVATE KEY-----",
        "[redacted private key]",
        message,
        flags=re.DOTALL,
    )
    message = re.sub(
        r"\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+)\b",
        "[redacted token]",
        message,
    )
    return re.sub(r"Bearer\s+\S+", "Bearer [redacted]", message)[:1000]


def print_progress(message: str) -> None:
    print(message, flush=True)


class SetupReporter:
    def __init__(self, owner: str, result_file: Path | None) -> None:
        self.owner = owner
        self.result_file = result_file
        self.phase = "Starting owner setup"
        self.action: SetupAction | None = None

    def progress(self, message: str) -> None:
        self.action = None
        self.phase = message
        self._write(SetupState.RUNNING, None)
        print_progress(message)

    def awaiting(self, action: SetupAction) -> None:
        self.action = action
        self.phase = action["summary"]
        self._write(SetupState.RUNNING, None)

    def finish(self, exit_code: int, error: str | None = None) -> None:
        self._write(
            SetupState.COMPLETE if exit_code == 0 else SetupState.FAILED,
            exit_code,
            error,
        )

    def _write(
        self, state: SetupState, exit_code: int | None, error: str | None = None
    ) -> None:
        if self.result_file is None:
            return
        result = {
            "schema_version": 1,
            "owner": self.owner,
            "pid": os.getpid(),
            "state": state.value,
            "phase": self.phase,
            "exit_code": exit_code,
            "observed_at": datetime.now(UTC).isoformat(),
        }
        if error is not None:
            result["error"] = safe_diagnostic(error)
        if self.action is not None:
            result["action"] = self.action
        self.result_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.result_file.with_name(
            f".{self.result_file.name}.{os.getpid()}.tmp"
        )
        temporary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.result_file)


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

    def organization_rulesets(self, owner: str) -> list[dict[str, Any]]:
        rulesets: list[dict[str, Any]] = []
        page = 1
        while True:
            path = f"orgs/{owner}/rulesets?per_page=100&page={page}"
            result = self.call(["api", path, "--method", "GET"])
            try:
                data = json.loads(result.stdout)
            except ValueError:
                data = None
            if result.returncode:
                if (
                    page == 1
                    and isinstance(data, dict)
                    and str(data.get("status")) == "403"
                    and data.get("message")
                    == "Upgrade to GitHub Team to enable this feature."
                ):
                    print(
                        "Organization rulesets are unavailable on this GitHub plan; "
                        "declared repository policies remain enforced.",
                        flush=True,
                    )
                    return []
                raise SetupError(
                    f"gh api GET {path} failed: "
                    f"{(result.stderr or result.stdout).strip()[:300]}"
                )
            if not isinstance(data, list) or any(
                not isinstance(item, dict) for item in data
            ):
                raise SetupError(f"invalid organization ruleset response for {owner}")
            rulesets.extend(data)
            if len(data) < 100:
                return rulesets
            page += 1

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


def discover(
    gh: GitHub, owner: str, progress: Callable[[str], None] = print_progress
) -> dict[str, Any]:
    progress(f"Checking the signed-in owner's membership in {owner}")
    login = gh.api("user")["login"]
    membership = gh.optional(f"user/memberships/orgs/{owner}")
    if (
        not membership
        or membership.get("role") != "admin"
        or membership.get("state") != "active"
    ):
        raise SetupError(f"{login} is not an active owner of {owner}")
    progress("Checking existing App installations and organization capabilities")
    installations, page = [], 1
    while True:
        batch = gh.api(f"orgs/{owner}/installations?per_page=100&page={page}").get(
            "installations", []
        )
        installations.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    rulesets = gh.organization_rulesets(owner)
    updater, controller = app_slug(owner), controller_slug(owner)
    progress("Checking existing Apps, updater configuration and exposed key locations")
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
            load_enrollment().GitHub(gh.run), owner, progress=progress
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


def confirm_legacy_rotation(
    owner: str,
    state: Mapping[str, Any],
    open_url: Callable[[str], Any],
    prompt: Callable[[str], str],
    progress: Callable[[str], None],
    request_action: Callable[[SetupAction], None],
) -> None:
    locations = []
    if state["legacy_org_secret"] is not None:
        locations.append(
            f"Organization {owner}: https://github.com/organizations/{owner}"
            f"/settings/secrets/actions/{SECRET}"
        )
    for location in state.get("legacy_repositories", []):
        parts = location.split("/")
        repository = "/".join(parts[:2])
        settings = "environments" if len(parts) == 3 else "secrets/actions"
        locations.append(
            f"{location}: https://github.com/{repository}/settings/{settings}"
        )
    action: SetupAction = {
        "kind": "identify_legacy_app",
        "summary": "Verify the issuing App for legacy updater credentials",
        "locations": locations,
        "steps": [
            f"Found {SECRET} metadata at the listed locations. Secret values "
            "were not read; their name does not identify the issuing App or "
            "prove that a key was copied.",
            "Use the original provisioning records to identify every App whose "
            "keys were distributed there. Do not revoke an unrelated bot App's keys.",
        ],
        "url": None,
    }
    progress(action["summary"])
    request_action(action)
    for line in [*action["locations"], *action["steps"]]:
        print_progress(line)
    updater = state.get("app")
    if updater is None:
        raise SetupError(
            "legacy credential identity is unresolved: the expected updater App "
            "does not exist. Identify the issuing Apps from provisioning records "
            "before retiring their credentials; no revocation was requested"
        )
    check_app(updater, owner, PERMISSIONS)
    variable = state.get("variable")
    if not variable or variable.get("value") != updater.get("client_id"):
        raise SetupError(
            f"legacy credential identity is unresolved: organization {VARIABLE} "
            "does not match the verified updater App. Reconcile provisioning "
            "records and configuration before retrying; no revocation was requested"
        )
    slug = state["slug"]
    identity = (
        f"{owner}/{slug} (App ID {updater['id']}, client ID {updater['client_id']})"
    )
    print_progress(f"GitHub verified the configured updater: {identity}.")
    confirmation = f"credentials belong to {slug}"
    ownership_prompt = (
        "After checking the provisioning records for EVERY listed location, "
        f"type '{confirmation}' only if all credentials belong to {identity}: "
    )
    action["steps"].extend(
        [f"Verified configured updater: {identity}.", ownership_prompt]
    )
    request_action(action)
    if prompt(ownership_prompt).strip() != confirmation:
        raise SetupError(
            "legacy credential ownership confirmation is required; "
            "no revocation was requested"
        )
    url = f"https://github.com/organizations/{owner}/settings/apps/{slug}#private-key"
    action = {
        "kind": "rotate_updater_keys",
        "summary": f"Waiting for key rotation of verified updater {identity}",
        "locations": locations,
        "steps": [
            f"Open {url} and check the App identity above.",
            "Under Private keys, delete each previously distributed key. "
            "This invalidates every use of those keys, including any copied key; "
            "removing an Actions secret alone does not revoke it.",
            "Generate a new private key after deletion and keep the downloaded "
            ".pem locally for the next prompt. Do not paste or send its contents.",
            f"Return here and type 'revoked {slug}' to confirm deletion is complete.",
        ],
        "url": url,
    }
    progress(action["summary"])
    request_action(action)
    for line in action["steps"]:
        print_progress(line)
    open_url(url)
    if prompt(f"Type 'revoked {slug}' after deleting the old keys: ").strip() != (
        f"revoked {slug}"
    ):
        raise SetupError("owner key-rotation confirmation is required before migration")


def setup(
    owner: str,
    gh: GitHub,
    key: str | None = None,
    open_url: Callable[[str], Any] = webbrowser.open,
    prompt: Callable[[str], str] = input,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    controller_key: str | None = None,
    progress: Callable[[str], None] = print_progress,
    request_action: Callable[[SetupAction], None] = lambda _: None,
) -> None:
    state = discover(gh, owner, progress)
    legacy_rotation = state["legacy_org_secret"] is not None or bool(
        state.get("legacy_repositories")
    )
    if legacy_rotation:
        if key is not None:
            raise SetupError(
                "legacy rotation requires a newly generated updater key selected "
                "after revocation; omit --updater-key-file and use the local prompt"
            )
        confirm_legacy_rotation(
            owner, state, open_url, prompt, progress, request_action
        )
    updater_slug, enroll_slug = state["slug"], state["controller_slug"]
    updater_created = None
    enroll_created = None
    updater = state["app"]
    controller = state["controller"]
    if updater is None:
        progress(f"Waiting for creation of {updater_slug} in the browser")
        updater_created = create_app(
            gh, owner, updater_slug, PERMISSIONS, open_url, clock
        )
        updater = gh.api(f"apps/{updater_slug}")
    if controller is None:
        progress(f"Waiting for creation of {enroll_slug} in the browser")
        enroll_created = create_app(
            gh, owner, enroll_slug, CONTROLLER_PERMISSIONS, open_url, clock
        )
        controller = gh.api(f"apps/{enroll_slug}")
    check_app(updater, owner, PERMISSIONS)
    check_app(controller, owner, CONTROLLER_PERMISSIONS)
    progress("Obtaining and verifying the updater and controller keys locally")
    updater_key = app_key(owner, updater_slug, key, updater_created, open_url, prompt)
    controller_key = app_key(
        owner, enroll_slug, controller_key, enroll_created, open_url, prompt
    )
    enrollment = load_enrollment()
    enrollment.verify_app_key(owner, updater["id"], updater["client_id"], updater_key)
    enrollment.verify_app_key(
        owner, controller["id"], controller["client_id"], controller_key
    )
    progress(f"Checking the {updater_slug} installation")
    ensure_installation(
        gh, owner, updater_slug, updater["id"], PERMISSIONS, open_url, sleep, clock
    )
    progress(f"Checking the {enroll_slug} installation")
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
    progress("Configuring the updater identity and protected central environments")
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
            allow_exposed=legacy_rotation and environment == "update-pins",
        )
    set_repo_variable(gh, central, CONTROLLER_VARIABLE, controller["client_id"])
    set_repo_variable(gh, central, "ENROLLMENT_APP_ID", str(controller["id"]))
    set_repo_variable(gh, central, "UPDATE_APP_ID", str(updater["id"]))
    put_env_secret(gh, central, CENTRAL_ENVIRONMENT, SECRET, updater_key)
    put_env_secret(
        gh, central, CENTRAL_ENVIRONMENT, "ENROLLMENT_APP_PRIVATE_KEY", controller_key
    )
    progress("Enrolling eligible repositories with protected updater credentials")
    results = enrollment.enroll(
        enrollment.GitHub(gh.run),
        owner,
        updater["id"],
        updater_key,
        apply=True,
        remove_legacy_secret=True,
        grant_bypass=False,
        allow_exposed=legacy_rotation,
        progress=progress,
    )
    if state["legacy_org_secret"] is not None:
        gh.remove_org_secret(owner, SECRET)
        if gh.optional(f"orgs/{owner}/actions/secrets/{SECRET}") is not None:
            raise SetupError(
                f"exposed organization secret {SECRET} removal read-back failed"
            )
    progress("Reconciling updater bypasses and declared repository policies")
    covered = ensure_org_rulesets(gh, owner, updater["id"], state["rulesets"])
    for result in results:
        progress(f"Reconciling the declared policy for {result['repository']}")
        result["merge_policy"] = enrollment.reconcile_policy(
            enrollment.GitHub(gh.run), result["repository"], updater["id"]
        )
    print(
        f"Owner setup complete: {len(results)} eligible repositories enrolled; "
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
        "branch selects Template or declares custom publication eligibility"
    )
    print(
        f"- store the enrollment key only in {owner}/github-actions/update-enrollment"
    )
    print(
        "- add the updater to supported organization rulesets and declared "
        "repository policies only for enrolled repositories"
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
    parser.add_argument("--result-file", type=Path)
    arguments = parser.parse_args(argv)
    enrollment = load_enrollment()
    reporter = SetupReporter(arguments.owner, arguments.result_file)
    try:
        if not OWNER.fullmatch(arguments.owner):
            raise SetupError("--owner must be a GitHub organization login")
        if not arguments.apply:
            preview(arguments.owner)
            return 0
        owner_only(environment)
        reporter.progress("Starting authenticated owner setup")
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
            progress=reporter.progress,
            request_action=reporter.awaiting,
        )
    except (SetupError, enrollment.EnrollmentError) as error:
        message = safe_diagnostic(str(error))
        reporter.finish(1, message)
        print(f"owner_setup: {message}", file=sys.stderr)
        return 1
    except Exception as error:
        reporter.finish(1, f"{type(error).__name__}: {safe_diagnostic(str(error))}")
        raise
    reporter.progress("Owner setup complete")
    reporter.finish(0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
