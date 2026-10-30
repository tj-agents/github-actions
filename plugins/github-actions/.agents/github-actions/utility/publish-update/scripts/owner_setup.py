#!/usr/bin/env python3
"""Configure an organization's updater GitHub App once, at organization level (Python 3.9+, needs the gh CLI).

Without --apply it only describes the changes. With --apply, run by an organization owner in their own
terminal, it creates or finds the private `<owner>-pin-updater` App, installs it on all repositories, sets
the organization variable UPDATE_APP_CLIENT_ID and secret UPDATE_APP_PRIVATE_KEY, adds the App as a bypass
actor to organization default-branch rulesets and reconciles every declared repository merge policy.
GitHub is the only source of truth; nothing is read from or written to this machine except a key file the
owner names.
"""

import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import html
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
from urllib.parse import parse_qs, quote, urlsplit
import webbrowser

PERMISSIONS = {"contents": "write", "pull_requests": "write", "workflows": "write"}
VARIABLE = "UPDATE_APP_CLIENT_ID"
SECRET = "UPDATE_APP_PRIVATE_KEY"
GH_TIMEOUT_SECONDS = 90
WAIT_SECONDS = 300
POLL_SECONDS = 5
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
OWNER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
PEM = re.compile(r"-----BEGIN (?:RSA )?PRIVATE KEY-----\r?\n[A-Za-z0-9+/=\r\n]+-----END (?:RSA )?PRIVATE KEY-----\s*")
MERGE_POLICY = Path(__file__).resolve().parents[2] / "merge-policy" / "scripts" / "merge_policy.py"


class SetupError(Exception):
    pass


class GitHub:
    def __init__(self, run=subprocess.run):
        self.run = run

    def call(self, arguments, data=None):
        try:
            return self.run(["gh", *arguments], input=data, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=GH_TIMEOUT_SECONDS, check=False, creationflags=NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise SetupError(f"gh {' '.join(arguments[:3])} failed: {error}") from error

    def api(self, path, method="GET", body=None):
        arguments = ["api", path, "--method", method]
        data = None
        if body is not None:
            arguments += ["--input", "-"]
            data = json.dumps(body)
        result = self.call(arguments, data)
        if result.returncode:
            raise SetupError(f"gh api {method} {path} failed: {(result.stderr or result.stdout).strip()[:300]}")
        return json.loads(result.stdout) if result.stdout.strip() else None

    def optional(self, path, absent=("HTTP 404",)):
        result = self.call(["api", path, "--method", "GET"])
        if result.returncode == 0:
            return json.loads(result.stdout) if result.stdout.strip() else None
        if any(marker in result.stderr for marker in absent):
            return None
        raise SetupError(f"gh api GET {path} failed: {(result.stderr or result.stdout).strip()[:300]}")

    def set_secret(self, owner, value):
        result = self.call(["secret", "set", SECRET, "--org", owner, "--visibility", "all"], value)
        if result.returncode:
            raise SetupError(f"gh secret set {SECRET} --org {owner} failed")


def app_slug(owner):
    return f"{owner.lower()}-pin-updater"


def owner_only(environment=os.environ):
    if environment.get("TJ_AGENT") == "1":
        raise SetupError("owner setup must run in the owner's own terminal; agent execution is refused")
    present = [name for name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_CONFIG_DIR") if environment.get(name)]
    if present:
        raise SetupError("unset " + ", ".join(present) + " so gh uses the owner's own sign-in")


def granted(permissions):
    return {key: value for key, value in (permissions or {}).items() if key != "metadata"}


def default_branch_ruleset(ruleset):
    include = ((ruleset.get("conditions") or {}).get("ref_name") or {}).get("include") or []
    return ruleset.get("target", "branch") == "branch" and bool({"~DEFAULT_BRANCH", "~ALL"} & set(include))


def bypasses(ruleset, app_id):
    return any(actor.get("actor_type") == "Integration" and actor.get("actor_id") == app_id
               and actor.get("bypass_mode") == "always" for actor in ruleset.get("bypass_actors") or [])


def discover(gh, owner):
    login = gh.api("user")["login"]
    membership = gh.optional(f"user/memberships/orgs/{owner}")
    if not membership or membership.get("role") != "admin" or membership.get("state") != "active":
        raise SetupError(f"{login} is not an active owner of {owner}")
    slug = app_slug(owner)
    installations = gh.api(f"orgs/{owner}/installations?per_page=100").get("installations", [])
    rulesets = gh.optional(f"orgs/{owner}/rulesets?per_page=100", absent=("HTTP 404", "HTTP 403"))
    return {
        "login": login,
        "org_id": gh.api(f"orgs/{owner}")["id"],
        "slug": slug,
        "app": gh.optional(f"apps/{slug}"),
        "installation": next((item for item in installations if item.get("app_slug") == slug), None),
        "variable": gh.optional(f"orgs/{owner}/actions/variables/{VARIABLE}"),
        "secret": gh.optional(f"orgs/{owner}/actions/secrets/{SECRET}"),
        "rulesets": rulesets,
    }


def check_app(app, owner):
    if (app.get("owner") or {}).get("login", "").lower() != owner.lower():
        raise SetupError(f"{app.get('slug')} must be owned by {owner}")
    if granted(app.get("permissions")) != PERMISSIONS:
        raise SetupError(f"{app.get('slug')} must have exactly contents, pull requests and workflows write: "
                         f"https://github.com/organizations/{owner}/settings/apps/{app.get('slug')}/permissions")


def create_app(gh, owner, slug, open_url, clock=time.monotonic):
    nonce = secrets.token_urlsafe(32)
    received = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *arguments):
            pass

        def respond(self, text, code=200):
            body = text.encode("utf-8")
            self.send_response(code)
            for name, value in (("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(body))),
                                ("Cache-Control", "no-store"), ("Referrer-Policy", "no-referrer")):
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            if self.headers.get("Host") != address or not parsed.path.startswith(f"/{nonce}/"):
                self.respond("Invalid setup request.", 403)
            elif parsed.path.endswith("/start"):
                manifest = {"name": f"{owner}-pin-updater", "url": f"https://github.com/{owner}", "public": False,
                            "redirect_url": base + "/created",
                            "hook_attributes": {"url": f"https://github.com/{owner}", "active": False},
                            "default_permissions": PERMISSIONS, "default_events": []}
                self.respond(f'<form method="post" action="https://github.com/organizations/{quote(owner)}'
                             f'/settings/apps/new?state={nonce}"><input type="hidden" name="manifest" value="'
                             f'{html.escape(json.dumps(manifest), quote=True)}"><button>Create {html.escape(slug)}'
                             '</button></form><script>document.forms[0].submit();</script>')
            elif (parsed.path.endswith("/created") and query.get("state") == [nonce]
                  and re.fullmatch(r"[A-Za-z0-9_-]{1,200}", (query.get("code") or [""])[0])):
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
        raise SetupError("GitHub did not return the App registration within 5 minutes; rerun to resume")
    app = gh.api(f"app-manifests/{received['code']}/conversions", "POST")
    if app.get("slug") != slug:
        raise SetupError(f"GitHub created {app.get('slug')}, not {slug}; rename or delete it, then rerun")
    return app


def wait(condition, open_url, url, message, sleep=time.sleep, clock=time.monotonic):
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
        raise SetupError(message + " was not completed within 5 minutes; rerun to resume")
    return value


def ensure_installation(gh, owner, state, open_url, sleep, clock):
    slug = state["slug"]

    def installation():
        return next((item for item in gh.api(f"orgs/{owner}/installations?per_page=100").get("installations", [])
                     if item.get("app_slug") == slug), None)

    current = wait(installation, open_url,
                   f"https://github.com/apps/{slug}/installations/new/permissions?target_id={state['org_id']}",
                   f"Install {slug} on All repositories of {owner}", sleep, clock)
    settings = f"https://github.com/organizations/{owner}/settings/installations/{current['id']}"

    def complete():
        item = installation()
        return item if (item and item.get("repository_selection") == "all" and not item.get("suspended_at")
                        and granted(item.get("permissions")) == PERMISSIONS) else None

    return wait(complete, open_url, settings,
                f"Set {slug} to All repositories, accept its permissions and unsuspend it", sleep, clock)


def ensure_variable(gh, owner, client_id, variable):
    if variable and variable.get("value") != client_id:
        raise SetupError(f"organization variable {VARIABLE} names a different App; preserved for review")
    body = {"name": VARIABLE, "value": client_id, "visibility": "all"}
    if variable is None:
        gh.api(f"orgs/{owner}/actions/variables", "POST", body)
    elif variable.get("visibility") != "all":
        gh.api(f"orgs/{owner}/actions/variables/{VARIABLE}", "PATCH", body)
    readback = gh.api(f"orgs/{owner}/actions/variables/{VARIABLE}")
    if readback.get("value") != client_id or readback.get("visibility") != "all":
        raise SetupError(f"organization variable {VARIABLE} read-back failed")


def read_key(text):
    if not PEM.fullmatch(text.strip() + "\n"):
        raise SetupError("the supplied private key is not a PEM private key")
    return text.strip() + "\n"


def ensure_secret(gh, owner, state, key, rotate, open_url, prompt):
    secret = state["secret"]
    if key is None and secret is not None and secret.get("visibility") == "all" and not rotate:
        return "present"
    if key is None:
        url = f"https://github.com/organizations/{owner}/settings/apps/{state['slug']}#private-key"
        print(f"Generate a new private key for {state['slug']} (Private keys > Generate a private key): {url}",
              flush=True)
        open_url(url)
        path = prompt("Path to the downloaded .pem file: ").strip().strip('"')
        try:
            key = read_key(Path(path).expanduser().read_text(encoding="utf-8"))
        except OSError as error:
            raise SetupError(f"cannot read {path}: {error.strerror}") from error
    gh.set_secret(owner, key)
    readback = gh.api(f"orgs/{owner}/actions/secrets/{SECRET}")
    if readback.get("visibility") != "all" or (secret and readback.get("updated_at") == secret.get("updated_at")):
        raise SetupError(f"organization secret {SECRET} read-back failed")
    return "uploaded"


def ensure_org_rulesets(gh, owner, app_id, rulesets):
    if rulesets is None:
        return "unavailable"
    covered = []
    for summary in rulesets:
        path = f"orgs/{owner}/rulesets/{summary['id']}"
        ruleset = gh.api(path)
        if not default_branch_ruleset(ruleset):
            continue
        if not bypasses(ruleset, app_id):
            actors = [actor for actor in ruleset.get("bypass_actors") or []
                      if not (actor.get("actor_type") == "Integration" and actor.get("actor_id") == app_id)]
            gh.api(path, "PUT", {"bypass_actors": actors + [
                {"actor_id": app_id, "actor_type": "Integration", "bypass_mode": "always"}]})
            if not bypasses(gh.api(path), app_id):
                raise SetupError(f"organization ruleset {ruleset.get('name')} bypass read-back failed")
        covered.append(ruleset.get("name"))
    return covered


def load_merge_policy():
    spec = importlib.util.spec_from_file_location("merge_policy", MERGE_POLICY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def reconcile_policies(gh, owner, app_id):
    merge_policy = load_merge_policy()
    try:
        merge_policy.require_personal_owner(owner)
    except merge_policy.PolicyError:
        return {}, []
    results, failures, page = {}, [], 1
    while True:
        batch = gh.api(f"orgs/{owner}/repos?type=all&per_page=100&page={page}")
        for repository in batch:
            if repository.get("archived") or repository.get("fork"):
                continue
            name = repository["full_name"]
            try:
                results[name] = merge_policy.reconcile(name, run=gh.run)["action"]
            except merge_policy.PolicyError as error:
                failures.append(f"{name}: {error}")
        if len(batch) < 100:
            return results, failures
        page += 1


def setup(owner, gh, key=None, rotate=False, open_url=webbrowser.open, prompt=input, sleep=time.sleep,
          clock=time.monotonic):
    state = discover(gh, owner)
    print(f"{state['login']} owns {owner}; App {state['slug']} " + ("found" if state["app"] else "absent"), flush=True)
    app = state["app"]
    if app is None:
        if state["variable"]:
            raise SetupError(f"organization variable {VARIABLE} exists but {state['slug']} was not found")
        created = create_app(gh, owner, state["slug"], open_url, clock)
        key = key or read_key(created["pem"])
        app = gh.api(f"apps/{state['slug']}")
    check_app(app, owner)
    ensure_installation(gh, owner, state, open_url, sleep, clock)
    print(f"{state['slug']} is installed on all {owner} repositories", flush=True)
    ensure_variable(gh, owner, app["client_id"], state["variable"])
    print(f"Organization variable {VARIABLE} = {app['client_id']}", flush=True)
    print(f"Organization secret {SECRET}: " + ensure_secret(gh, owner, state, key, rotate, open_url, prompt),
          flush=True)
    covered = ensure_org_rulesets(gh, owner, app["id"], state["rulesets"])
    if covered == "unavailable":
        print("Organization rulesets are unavailable to this plan; none changed", flush=True)
    else:
        print("Organization default-branch rulesets bypassed by the App: " + (", ".join(covered) or "none exist"),
              flush=True)
    results, failures = reconcile_policies(gh, owner, app["id"])
    for name, action in sorted(results.items()):
        if action not in ("current", "undeclared", "skipped"):
            print(f"Merge policy {action}: {name}", flush=True)
    if failures:
        raise SetupError("merge policy reconciliation failed:\n" + "\n".join(failures))
    print("Owner setup complete. The first post-merge regeneration push still requires verification.", flush=True)


def preview(owner):
    slug = app_slug(owner)
    print(f"Preview for {owner} (run with --apply as an organization owner):")
    print(f"- create or reuse the private App {slug} with contents, pull requests and workflows write")
    print("- install it on All repositories")
    print(f"- set organization variable {VARIABLE} (visibility all) to its client id")
    print(f"- set organization secret {SECRET} (visibility all) when absent, on --rotate, or from --key-file")
    print("- add the App as an always-bypass actor to organization default-branch rulesets")
    print("- reconcile every declared .github/merge-policy.json, which grants the App the same bypass")
    print("Nothing is stored on this machine.")


def main(argv=None, environment=os.environ, run=subprocess.run, stdin=sys.stdin):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rotate", action="store_true", help="upload a newly generated private key")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--key-file", type=Path)
    source.add_argument("--key-stdin", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        if not OWNER.fullmatch(arguments.owner):
            raise SetupError("--owner must be a GitHub organization login")
        if not arguments.apply:
            preview(arguments.owner)
            return 0
        owner_only(environment)
        key = None
        if arguments.key_file:
            try:
                key = read_key(arguments.key_file.expanduser().read_text(encoding="utf-8"))
            except OSError as error:
                raise SetupError(f"cannot read {arguments.key_file}: {error.strerror}") from error
        elif arguments.key_stdin:
            key = read_key(stdin.read())
        setup(arguments.owner, GitHub(run), key, arguments.rotate)
    except SetupError as error:
        print(f"owner_setup: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
