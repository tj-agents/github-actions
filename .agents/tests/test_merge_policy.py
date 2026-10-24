import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".agents/github-actions/utility/merge-policy/scripts/merge_policy.py"
SPEC = importlib.util.spec_from_file_location("merge_policy", SCRIPT)
merge_policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(merge_policy)

HUMAN = {"agents_may_merge": False, "required_checks": ["ci-required"]}
AGENTS = {"agents_may_merge": True, "required_checks": ["ci-required"], "review_check": "agent-review"}


class FakeGh:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs.get("input")))
        path = next(part for part in command[2:] if part.startswith(("repos/", "users/")))
        value = self.responses.get(path, {})
        payload = kwargs.get("input")
        method = command[command.index("--method") + 1] if "--method" in command else "GET"
        if payload is not None:
            desired = json.loads(payload)
            if method == "PATCH":
                value = {**value, **desired}
                self.responses[path] = value
            elif method in {"POST", "PUT"} and "/rulesets" in path:
                repository = path.split("/rulesets", 1)[0]
                ruleset_id = int(path.rsplit("/", 1)[1]) if method == "PUT" else 7
                value = {**desired, "id": ruleset_id, "source_type": "Repository"}
                self.responses[f"{repository}/rulesets/{ruleset_id}"] = value
                listing = f"{repository}/rulesets?per_page=100"
                others = [item for item in self.responses.get(listing, []) if item.get("id") != ruleset_id]
                self.responses[listing] = [*others, value]
                self.responses[f"{repository}/rules/branches/main?per_page=100"] = (
                    desired["rules"] if desired["enforcement"] == "active" else []
                )
        if value == 409:
            return subprocess.CompletedProcess(command, 1, "", "gh: Git Repository is empty. (HTTP 409)")
        if value == 500:
            return subprocess.CompletedProcess(command, 1, "", "gh: Server Error (HTTP 500)")
        if value == 404:
            return subprocess.CompletedProcess(command, 1, "", "gh: Not Found (HTTP 404)")
        return subprocess.CompletedProcess(command, 0, json.dumps(value), "")


def rules(policy):
    return [{**rule, "ruleset_source_type": "Repository"} for rule in merge_policy.ruleset(policy)["rules"]]


class PolicyTests(unittest.TestCase):
    def write(self, value):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "merge-policy.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_invalid_policies_are_refused(self):
        for value in ({}, {"agents_may_merge": "yes"}, {"agents_may_merge": True, "review_check": ""},
                      {"agents_may_merge": False, "review_check": "agent-review"},
                      {"agents_may_merge": False, "required_checks": [""]},
                      {"agents_may_merge": False, "extra": 1}):
            with self.subTest(value=value), self.assertRaises(merge_policy.PolicyError):
                merge_policy.load_policy(self.write(value))

    def test_human_merge_requires_one_approval_of_the_latest_push(self):
        ruleset = merge_policy.ruleset(HUMAN)
        review = next(rule for rule in ruleset["rules"] if rule["type"] == "pull_request")["parameters"]
        self.assertEqual(1, review["required_approving_review_count"])
        self.assertTrue(review["require_last_push_approval"])
        self.assertEqual([{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"}],
                         ruleset["bypass_actors"])
        self.assertEqual(["~DEFAULT_BRANCH"], ruleset["conditions"]["ref_name"]["include"])

    def test_ci_pushes_let_deploy_keys_bypass(self):
        actors = merge_policy.ruleset({**HUMAN, "ci_pushes_default_branch": True})["bypass_actors"]
        self.assertIn({"actor_type": "DeployKey", "bypass_mode": "always"}, actors)

    def test_agent_merge_requires_the_review_check_instead_of_an_approval(self):
        ruleset = merge_policy.ruleset(AGENTS)
        review = next(rule for rule in ruleset["rules"] if rule["type"] == "pull_request")["parameters"]
        checks = next(rule for rule in ruleset["rules"] if rule["type"] == "required_status_checks")
        self.assertEqual(0, review["required_approving_review_count"])
        self.assertEqual(["ci-required", "agent-review"],
                         [item["context"] for item in checks["parameters"]["required_status_checks"]])


class ApplyTests(unittest.TestCase):
    def test_personal_owners_can_apply_their_declared_policy(self):
        for owner in ("tj-agents", "Concertable", "tomjseery", "CONCERTABLE"):
            with self.subTest(owner=owner):
                gh = FakeGh({})
                self.assertEqual("created", merge_policy.apply(owner + "/repo", HUMAN, run=gh)["action"])
                self.assertTrue(any("POST" in command for command, _ in gh.calls))

    def test_employer_repositories_are_refused_before_any_github_call(self):
        for repository in ("Infonetica/work", "company/work", "tj-agents-company/work", "tj-agents/infonetica"):
            for dry_run in (False, True):
                with self.subTest(repository=repository, dry_run=dry_run):
                    gh = FakeGh({})
                    with self.assertRaises(merge_policy.PolicyError):
                        merge_policy.apply(repository, HUMAN, dry_run=dry_run, run=gh)
                    self.assertEqual([], gh.calls)

    def test_employer_sync_owner_is_refused_before_processing_any_owner(self):
        gh = FakeGh({})
        with self.assertRaises(merge_policy.PolicyError):
            merge_policy.sync(["tj-agents", "Infonetica"], run=gh)
        self.assertEqual([], gh.calls)

    def test_creates_when_absent_and_updates_the_existing_ruleset(self):
        gh = FakeGh({"repos/tj-agents/r/rulesets?per_page=100": [{"id": 9, "name": "other"}]})
        self.assertEqual("created", merge_policy.apply("tj-agents/r", HUMAN, run=gh)["action"])
        posted = next(call for call in gh.calls if "POST" in call[0])
        self.assertEqual(["--method", "POST", "repos/tj-agents/r/rulesets"], posted[0][2:5])
        self.assertEqual("merge-policy", json.loads(posted[1])["name"])
        gh = FakeGh({"repos/tj-agents/r/rulesets?per_page=100": [{"id": 7, "name": "merge-policy", "source_type": "Repository"}]})
        self.assertEqual("updated", merge_policy.apply("tj-agents/r", HUMAN, run=gh)["action"])
        updated = next(call for call in gh.calls if "PUT" in call[0])
        self.assertEqual(["--method", "PUT", "repos/tj-agents/r/rulesets/7"], updated[0][2:5])

    def test_apply_enables_auto_merge_so_an_approval_lands_the_pr(self):
        gh = FakeGh({"repos/tj-agents/r/rulesets?per_page=100": []})
        merge_policy.apply("tj-agents/r", HUMAN, run=gh)
        patch = next(call for call in gh.calls if call[0][2:5] == ["--method", "PATCH", "repos/tj-agents/r"])
        self.assertEqual({"allow_auto_merge": True}, json.loads(patch[1]))

    def test_protection_is_active_before_enabling_repository_auto_merge(self):
        gh = FakeGh({"repos/tj-agents/r": {"allow_auto_merge": False}})
        merge_policy.apply("tj-agents/r", HUMAN, run=gh)
        writes = [command for command, _ in gh.calls if "--method" in command]
        self.assertIn("POST", writes[0])
        self.assertIn("PATCH", writes[1])

    def test_dry_run_never_writes(self):
        gh = FakeGh({"repos/tj-agents/r/rulesets?per_page=100": []})
        self.assertEqual("create", merge_policy.apply("tj-agents/r", HUMAN, dry_run=True, run=gh)["action"])
        self.assertEqual(1, len(gh.calls))

    def test_api_failure_is_reported(self):
        def failing(command, **kwargs):
            return subprocess.CompletedProcess(command, 1, "", "HTTP 403: Upgrade to GitHub Pro")
        with self.assertRaisesRegex(merge_policy.PolicyError, "Upgrade to GitHub Pro"):
            merge_policy.apply("tj-agents/r", HUMAN, run=failing)


class CheckTests(unittest.TestCase):
    def check(self, policy, enforced):
        gh = FakeGh({"repos/tj-agents/r": {"default_branch": "main", "allow_auto_merge": True}, "repos/tj-agents/r/rules/branches/main?per_page=100": enforced})
        return merge_policy.check("tj-agents/r", policy, run=gh)

    def test_applied_policy_has_no_drift(self):
        self.assertEqual([], self.check(HUMAN, rules(HUMAN)))
        self.assertEqual([], self.check(AGENTS, rules(AGENTS)))

    def test_disabled_auto_merge_is_drift(self):
        gh = FakeGh({"repos/tj-agents/r": {"default_branch": "main", "allow_auto_merge": False},
                     "repos/tj-agents/r/rules/branches/main?per_page=100": rules(HUMAN)})
        self.assertEqual(1, len(merge_policy.check("tj-agents/r", HUMAN, run=gh)))

    def test_no_rules_names_the_free_plan_cause(self):
        problems = self.check(HUMAN, [])
        self.assertEqual(1, len(problems))
        self.assertIn("GitHub Free", problems[0])

    def test_partial_rules_report_every_gap(self):
        problems = self.check(HUMAN, [{"type": "pull_request", "parameters": {}}])
        self.assertEqual(6, len(problems))
        self.assertIn("required checks not enforced: ci-required", problems)

    def test_policy_and_rules_disagreeing_on_who_merges_is_drift(self):
        self.assertIn("no approval is required", self.check(HUMAN, rules(AGENTS)))
        self.assertTrue(any("agents may merge" in problem for problem in self.check(AGENTS, rules(HUMAN))))

    def test_sync_reconciles_owned_drift_at_committed_heads_and_is_idempotent(self):
        import base64
        head = "a" * 40
        policy = {"agents_may_merge": False, "ci_pushes_default_branch": True}
        desired = merge_policy.ruleset(policy)
        responses = {
            "users/tj-agents/repos?type=owner&per_page=100&page=1": [
                {"full_name": "tj-agents/new"}, {"full_name": "tj-agents/core"},
                {"full_name": "tj-agents/done"}, {"full_name": "tj-agents/infonetica"},
                {"full_name": "tj-agents/secret", "private": True},
                {"full_name": "tj-agents/copy", "fork": True}],
        }
        for name in ("new", "core", "done"):
            repository = f"repos/tj-agents/{name}"
            responses[repository] = {"default_branch": "main", "allow_auto_merge": True}
            responses[f"{repository}/commits/main"] = {"sha": head}
            responses[f"{repository}/contents/.github/merge-policy.json?ref={head}"] = (
                404 if name == "new" else {"content": base64.b64encode(json.dumps(policy).encode()).decode()}
            )
            responses[f"{repository}/rulesets?per_page=100"] = []
        current = {**desired, "id": 7, "source_type": "Repository"}
        responses["repos/tj-agents/done/rulesets?per_page=100"] = [current]
        responses["repos/tj-agents/done/rulesets/7"] = current
        bypass_drift = {**current, "bypass_actors": []}
        responses["repos/tj-agents/core/rulesets?per_page=100"] = [bypass_drift]
        responses["repos/tj-agents/core/rulesets/7"] = bypass_drift
        responses["repos/tj-agents/core/rules/branches/main?per_page=100"] = rules(policy)
        gh = FakeGh(responses)
        self.assertEqual(
            [("tj-agents/core", "updated", []), ("tj-agents/done", "current", [])],
            merge_policy.sync(["tj-agents"], run=gh),
        )
        self.assertFalse(any("infonetica" in " ".join(command) for command, _ in gh.calls))
        gh.calls.clear()
        self.assertEqual(
            [("tj-agents/core", "current", []), ("tj-agents/done", "current", [])],
            merge_policy.sync(["tj-agents"], run=gh),
        )
        self.assertFalse(any("--method" in command for command, _ in gh.calls))

    def test_sync_skips_empty_repositories_and_preserves_other_api_failures(self):
        gh = FakeGh({
            "users/tj-agents/repos?type=owner&per_page=100&page=1": [
                {"full_name": "tj-agents/empty"}, {"full_name": "tj-agents/broken"}],
            "repos/tj-agents/empty": {"default_branch": "main"},
            "repos/tj-agents/empty/commits/main": 409,
            "repos/tj-agents/broken": {"default_branch": "main"},
            "repos/tj-agents/broken/commits/main": 500,
        })
        result = merge_policy.sync(["tj-agents"], run=gh)
        self.assertEqual(1, len(result))
        self.assertEqual(("tj-agents/broken", "failed"), result[0][:2])
        self.assertIn("HTTP 500", result[0][2][0])
        self.assertFalse(any("--method" in command for command, _ in gh.calls))

    def test_reconcile_repairs_only_auto_merge_drift(self):
        import base64
        head = "a" * 40
        desired = {**merge_policy.ruleset(HUMAN), "id": 7, "source_type": "Repository"}
        gh = FakeGh({
            "repos/tj-agents/r": {"default_branch": "main", "allow_auto_merge": False},
            "repos/tj-agents/r/commits/main": {"sha": head},
            f"repos/tj-agents/r/contents/.github/merge-policy.json?ref={head}": {
                "content": base64.b64encode(json.dumps(HUMAN).encode()).decode()},
            "repos/tj-agents/r/rulesets?per_page=100": [desired],
            "repos/tj-agents/r/rulesets/7": desired,
            "repos/tj-agents/r/rules/branches/main?per_page=100": rules(HUMAN),
        })
        self.assertEqual("drift", merge_policy.reconcile("tj-agents/r", run=gh, check_only=True)["action"])
        self.assertFalse(any("--method" in command for command, _ in gh.calls))
        self.assertEqual("updated", merge_policy.reconcile("tj-agents/r", run=gh)["action"])
        writes = [command for command, _ in gh.calls if "--method" in command]
        self.assertEqual(1, len(writes))
        self.assertIn("PATCH", writes[0])
        gh.calls.clear()
        self.assertEqual("current", merge_policy.reconcile("tj-agents/r", run=gh)["action"])
        self.assertFalse(any("--method" in command for command, _ in gh.calls))

    def test_disabled_policy_converges_without_touching_another_ruleset(self):
        policy = {**HUMAN, "enabled": False}
        active = {**merge_policy.ruleset(HUMAN), "id": 7, "source_type": "Repository"}
        gh = FakeGh({
            "repos/tj-agents/r": {"default_branch": "main", "allow_auto_merge": True},
            "repos/tj-agents/r/rulesets?per_page=100": [
                active, {"id": 9, "name": "other", "source_type": "Repository"}],
            "repos/tj-agents/r/rulesets/7": active,
        })
        self.assertEqual("updated", merge_policy.apply("tj-agents/r", policy, run=gh)["action"])
        writes = [command for command, _ in gh.calls if "--method" in command]
        self.assertIn("PATCH", writes[0])
        self.assertIn("PUT", writes[1])
        self.assertEqual([], merge_policy.check("tj-agents/r", policy, run=gh))
        self.assertEqual("disabled", gh.responses["repos/tj-agents/r/rulesets/7"]["enforcement"])
        self.assertFalse(gh.responses["repos/tj-agents/r"]["allow_auto_merge"])
        self.assertTrue(any(item["id"] == 9 for item in gh.responses["repos/tj-agents/r/rulesets?per_page=100"]))
        self.assertFalse(any("rulesets/9" in " ".join(command) for command, _ in gh.calls))
        gh.calls.clear()
        self.assertEqual("current", merge_policy.apply("tj-agents/r", policy, run=gh)["action"])
        self.assertFalse(any("--method" in command for command, _ in gh.calls))

    def test_enabled_must_be_boolean(self):
        for value in (None, 0, "false"):
            with self.subTest(value=value), self.assertRaises(merge_policy.PolicyError):
                merge_policy.validate_policy({**HUMAN, "enabled": value}, "policy")

    def test_reconcile_check_cli_uses_read_only_mode_and_reports_drift(self):
        with mock.patch.object(merge_policy, "reconcile", return_value={"action": "drift"}) as reconcile:
            with mock.patch("builtins.print"):
                self.assertEqual(1, merge_policy.main(["reconcile", "--repo", "tj-agents/r", "--check"]))
        reconcile.assert_called_once_with("tj-agents/r", check_only=True)

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = Path(directory) / "merge-policy.json"
            policy.write_text(json.dumps(HUMAN), encoding="utf-8")
            render = subprocess.run([sys.executable, "-B", str(SCRIPT), "render", "--policy", str(policy)],
                                    capture_output=True, text=True, check=False)
            self.assertEqual(0, render.returncode)
            self.assertEqual("merge-policy", json.loads(render.stdout)["name"])
            policy.write_text("{}", encoding="utf-8")
            invalid = subprocess.run([sys.executable, "-B", str(SCRIPT), "render", "--policy", str(policy)],
                                     capture_output=True, text=True, check=False)
            self.assertEqual(2, invalid.returncode)


if __name__ == "__main__":
    unittest.main()
