import base64
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from test_merge_policy import merge_policy, rules

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".agents/github-actions/utility/publish-update/scripts/owner_setup.py"
SPEC = importlib.util.spec_from_file_location("owner_setup", SCRIPT)
owner_setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(owner_setup)

OWNER = "tj-agents"
SLUG = "tj-agents-pin-updater"
PERMISSIONS = {"metadata": "read", **owner_setup.PERMISSIONS}
POLICY = {"agents_may_merge": False, "required_checks": ["ci-required"]}
KEY = "-----BEGIN RSA PRIVATE KEY-----\nMIIBOgIBAAJBAK0=\n-----END RSA PRIVATE KEY-----\n"


def configured():
    return {
        "user": {"login": "owner"},
        f"user/memberships/orgs/{OWNER}": {"role": "admin", "state": "active"},
        f"orgs/{OWNER}": {"id": 99},
        f"apps/{SLUG}": {"id": 42, "slug": SLUG, "client_id": "Iv1.abc", "owner": {"login": OWNER},
                         "permissions": PERMISSIONS},
        f"orgs/{OWNER}/installations?per_page=100": {"installations": [
            {"id": 7, "app_slug": SLUG, "repository_selection": "all", "permissions": PERMISSIONS}]},
        f"orgs/{OWNER}/actions/variables/{owner_setup.VARIABLE}": {"name": owner_setup.VARIABLE,
                                                                   "value": "Iv1.abc", "visibility": "all"},
        f"orgs/{OWNER}/actions/secrets/{owner_setup.SECRET}": {"name": owner_setup.SECRET, "visibility": "all",
                                                               "updated_at": "2026-10-01T00:00:00Z"},
        f"orgs/{OWNER}/rulesets?per_page=100": [{"id": 3}, {"id": 4}],
        f"orgs/{OWNER}/rulesets/3": {"name": "org-default", "target": "branch",
                                     "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"]}},
                                     "bypass_actors": [{"actor_id": 1, "actor_type": "OrganizationAdmin",
                                                        "bypass_mode": "always"}]},
        f"orgs/{OWNER}/rulesets/4": {"name": "tags", "target": "tag", "conditions": {"ref_name": {"include": ["~ALL"]}}},
        f"orgs/{OWNER}/repos?type=all&per_page=100&page=1": [{"full_name": f"{OWNER}/plugin"},
                                                             {"full_name": f"{OWNER}/old", "archived": True}],
        f"repos/{OWNER}/plugin": {"default_branch": "main"},
        f"repos/{OWNER}/plugin/commits/main": {"sha": "b" * 40},
        f"repos/{OWNER}/plugin/contents/.github/merge-policy.json?ref={'b' * 40}":
            {"content": base64.b64encode(json.dumps(POLICY).encode()).decode()},
        f"repos/{OWNER}/plugin/rulesets?per_page=100": [{"id": 5, "name": "merge-policy"}],
        f"repos/{OWNER}/plugin/rulesets/5": merge_policy.ruleset(POLICY),
        f"repos/{OWNER}/plugin/rules/branches/main?per_page=100": rules(POLICY),
    }


def api_path(command):
    parts = command[2:]
    skipped = {index + 1 for index, part in enumerate(parts) if part in ("--method", "--input")}
    return next(part for index, part in enumerate(parts) if index not in skipped and not part.startswith("--"))


class FakeGitHub:
    def __init__(self, state):
        self.state = copy.deepcopy(state)
        self.calls = []
        self.tick = 0

    def __call__(self, command, **kwargs):
        payload = kwargs.get("input")
        self.calls.append((command, payload))
        if command[1:3] == ["secret", "set"]:
            self.tick += 1
            self.state[f"orgs/{OWNER}/actions/secrets/{owner_setup.SECRET}"] = {
                "name": owner_setup.SECRET, "visibility": command[command.index("--visibility") + 1],
                "updated_at": f"2026-10-30T00:00:0{self.tick}Z"}
            return subprocess.CompletedProcess(command, 0, "", "")
        path = api_path(command)
        method = command[command.index("--method") + 1] if "--method" in command else "GET"
        if method == "GET":
            if path not in self.state:
                return subprocess.CompletedProcess(command, 1, "", "gh: Not Found (HTTP 404)")
            return subprocess.CompletedProcess(command, 0, json.dumps(self.state[path]), "")
        body = json.loads(payload) if payload else {}
        if path == f"orgs/{OWNER}/actions/variables":
            self.state[f"{path}/{body['name']}"] = body
        elif path.startswith(f"orgs/{OWNER}/actions/variables/"):
            self.state[path] = {**self.state[path], **body}
        elif path.startswith(f"orgs/{OWNER}/rulesets/") or "/rulesets/" in path:
            self.state[path] = {**self.state.get(path, {}), **body}
        return subprocess.CompletedProcess(command, 0, "{}", "")

    def writes(self):
        return [(command, payload) for command, payload in self.calls
                if command[1:3] == ["secret", "set"] or ("--method" in command
                                                         and command[command.index("--method") + 1] != "GET")]


def run_setup(fake, **options):
    opened = []
    defaults = {"open_url": opened.append, "prompt": mock.Mock(side_effect=AssertionError("unexpected prompt")),
                "sleep": lambda seconds: None, "clock": iter(range(0, 10_000)).__next__}
    defaults.update(options)
    owner_setup.setup(OWNER, owner_setup.GitHub(fake), **defaults)
    return opened


class OwnerGuardTests(unittest.TestCase):
    def test_agents_and_token_overrides_are_refused_before_github(self):
        for environment in ({"TJ_AGENT": "1"}, {"GH_TOKEN": "x"}, {"GITHUB_TOKEN": "x"}, {"GH_CONFIG_DIR": "x"}):
            with self.subTest(environment=environment):
                run = mock.Mock()
                with mock.patch("sys.stderr", io.StringIO()):
                    self.assertEqual(1, owner_setup.main(["--owner", OWNER, "--apply"], environment, run))
                run.assert_not_called()

    def test_preview_never_contacts_github(self):
        run = mock.Mock()
        with mock.patch("sys.stdout", io.StringIO()) as output:
            self.assertEqual(0, owner_setup.main(["--owner", OWNER], {"TJ_AGENT": "1"}, run))
        run.assert_not_called()
        self.assertIn(SLUG, output.getvalue())

    def test_non_owner_is_refused(self):
        state = configured()
        state[f"user/memberships/orgs/{OWNER}"] = {"role": "member", "state": "active"}
        fake = FakeGitHub(state)
        with self.assertRaises(owner_setup.SetupError):
            run_setup(fake)
        self.assertEqual([], fake.writes())


class DiscoveryTests(unittest.TestCase):
    def test_github_state_alone_identifies_the_app_installation_and_configuration(self):
        state = owner_setup.discover(owner_setup.GitHub(FakeGitHub(configured())), OWNER)
        self.assertEqual(42, state["app"]["id"])
        self.assertEqual(7, state["installation"]["id"])
        self.assertEqual("Iv1.abc", state["variable"]["value"])
        self.assertEqual(99, state["org_id"])

    def test_unavailable_organization_rulesets_are_tolerated(self):
        fake = FakeGitHub(configured())
        del fake.state[f"orgs/{OWNER}/rulesets?per_page=100"]
        self.assertIsNone(owner_setup.discover(owner_setup.GitHub(fake), OWNER)["rulesets"])

    def test_variable_naming_another_app_is_preserved(self):
        state = configured()
        state[f"orgs/{OWNER}/actions/variables/{owner_setup.VARIABLE}"]["value"] = "Iv1.other"
        fake = FakeGitHub(state)
        with mock.patch("sys.stdout", io.StringIO()), self.assertRaises(owner_setup.SetupError):
            run_setup(fake)
        self.assertFalse(any("variables" in " ".join(command) for command, _ in fake.writes()))


class NoLocalStateTests(unittest.TestCase):
    def test_configured_organization_completes_with_an_empty_home_and_no_key(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"HOME": home, "USERPROFILE": home}), \
                mock.patch("sys.stdout", io.StringIO()):
            fake = FakeGitHub(configured())
            run_setup(fake)
            self.assertEqual([], os.listdir(home))
        self.assertFalse(any(command[1:3] == ["secret", "set"] for command, _ in fake.writes()))

    def test_missing_secret_offers_a_prefilled_key_link_and_uploads_the_supplied_key(self):
        state = configured()
        del state[f"orgs/{OWNER}/actions/secrets/{owner_setup.SECRET}"]
        fake = FakeGitHub(state)
        with tempfile.TemporaryDirectory() as directory, mock.patch("sys.stdout", io.StringIO()):
            path = Path(directory) / "downloaded.pem"
            path.write_text(KEY, encoding="utf-8")
            opened = run_setup(fake, prompt=lambda text: str(path))
        self.assertIn(f"https://github.com/organizations/{OWNER}/settings/apps/{SLUG}#private-key", opened)
        upload = [(command, payload) for command, payload in fake.calls if command[1:3] == ["secret", "set"]]
        self.assertEqual(1, len(upload))
        self.assertEqual(["gh", "secret", "set", owner_setup.SECRET, "--org", OWNER, "--visibility", "all"],
                         upload[0][0])
        self.assertEqual(KEY, upload[0][1])

    def test_rotation_replaces_the_one_organization_secret(self):
        fake = FakeGitHub(configured())
        with mock.patch("sys.stdout", io.StringIO()):
            run_setup(fake, key=KEY, rotate=True)
        uploads = [command for command, _ in fake.calls if command[1:3] == ["secret", "set"]]
        self.assertEqual(1, len(uploads))

    def test_invalid_key_is_refused_before_upload(self):
        with self.assertRaises(owner_setup.SetupError):
            owner_setup.read_key("not a key")

    def test_missing_variable_is_created_for_all_repositories(self):
        state = configured()
        del state[f"orgs/{OWNER}/actions/variables/{owner_setup.VARIABLE}"]
        fake = FakeGitHub(state)
        with mock.patch("sys.stdout", io.StringIO()):
            run_setup(fake)
        created = [json.loads(payload) for command, payload in fake.writes()
                   if f"orgs/{OWNER}/actions/variables" in command]
        self.assertEqual([{"name": owner_setup.VARIABLE, "value": "Iv1.abc", "visibility": "all"}], created)


class InstallationTests(unittest.TestCase):
    def test_selected_installation_waits_for_all_repositories(self):
        state = configured()
        path = f"orgs/{OWNER}/installations?per_page=100"
        state[path]["installations"][0]["repository_selection"] = "selected"
        fake = FakeGitHub(state)

        def owner_switches(seconds):
            fake.state[path]["installations"][0]["repository_selection"] = "all"

        with mock.patch("sys.stdout", io.StringIO()):
            opened = run_setup(fake, sleep=owner_switches)
        self.assertIn(f"https://github.com/organizations/{OWNER}/settings/installations/7", opened)


class RulesetTests(unittest.TestCase):
    def test_bypass_is_added_once_to_default_branch_rulesets_and_repository_policies(self):
        fake = FakeGitHub(configured())
        with mock.patch("sys.stdout", io.StringIO()):
            run_setup(fake)
        puts = [(command, json.loads(payload)) for command, payload in fake.writes() if "PUT" in command]
        paths = sorted(api_path(command) for command, _ in puts)
        self.assertEqual([f"orgs/{OWNER}/rulesets/3", f"repos/{OWNER}/plugin/rulesets/5"], paths)
        app = {"actor_id": 42, "actor_type": "Integration", "bypass_mode": "always"}
        for _, body in puts:
            self.assertIn(app, body["bypass_actors"])
        organization = next(body for command, body in puts if api_path(command) == f"orgs/{OWNER}/rulesets/3")
        self.assertIn({"actor_id": 1, "actor_type": "OrganizationAdmin", "bypass_mode": "always"},
                      organization["bypass_actors"])

        rerun = FakeGitHub(fake.state)
        with mock.patch("sys.stdout", io.StringIO()):
            run_setup(rerun)
        self.assertFalse(any("PUT" in command for command, _ in rerun.writes()))


if __name__ == "__main__":
    unittest.main()
