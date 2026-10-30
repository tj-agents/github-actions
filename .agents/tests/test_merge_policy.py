import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

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
        path = next(part for part in command[2:] if part.startswith(("repos/", "users/", "apps/")))
        value = self.responses.get(path, 404 if path.startswith("apps/") else {})
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

    def test_human_merge_retains_one_approval_across_pushes(self):
        ruleset = merge_policy.ruleset(HUMAN)
        review = next(rule for rule in ruleset["rules"] if rule["type"] == "pull_request")["parameters"]
        checks = next(rule for rule in ruleset["rules"] if rule["type"] == "required_status_checks")
        self.assertEqual(1, review["required_approving_review_count"])
        self.assertFalse(review["dismiss_stale_reviews_on_push"])
        self.assertFalse(review["require_last_push_approval"])
        self.assertEqual([{"context": "ci-required"}], checks["parameters"]["required_status_checks"])
        self.assertEqual([{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"}],
                         ruleset["bypass_actors"])
        self.assertEqual(["~DEFAULT_BRANCH"], ruleset["conditions"]["ref_name"]["include"])

    def test_ci_pushes_let_deploy_keys_bypass(self):
        actors = merge_policy.ruleset({**HUMAN, "ci_pushes_default_branch": True})["bypass_actors"]
        self.assertIn({"actor_type": "DeployKey", "bypass_mode": "always"}, actors)

    def test_the_owners_updater_app_may_push_the_default_branch(self):
        actors = merge_policy.ruleset(HUMAN, updater_app=42)["bypass_actors"]
        self.assertIn({"actor_id": 42, "actor_type": "Integration", "bypass_mode": "always"}, actors)
        self.assertEqual("tj-agents-pin-updater", merge_policy.updater_app_slug("tj-agents"))

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
                self.assertIn("POST", gh.calls[-1][0])

    def test_employer_repositories_are_refused_before_any_github_call(self):
        for repository in ("Infonetica/work", "company/work", "tj-agents-company/work"):
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
        self.assertEqual(["--method", "POST", "repos/tj-agents/r/rulesets"], gh.calls[-1][0][2:5])
        self.assertEqual("merge-policy", json.loads(gh.calls[-1][1])["name"])
        gh = FakeGh({"repos/tj-agents/r/rulesets?per_page=100": [{"id": 7, "name": "merge-policy", "source_type": "Repository"}]})
        self.assertEqual("updated", merge_policy.apply("tj-agents/r", HUMAN, run=gh)["action"])
        self.assertEqual(["--method", "PUT", "repos/tj-agents/r/rulesets/7"], gh.calls[-1][0][2:5])

    def test_apply_enables_auto_merge_so_an_approval_lands_the_pr(self):
        gh = FakeGh({"repos/tj-agents/r/rulesets?per_page=100": []})
        merge_policy.apply("tj-agents/r", HUMAN, run=gh)
        patch = next(call for call in gh.calls if call[0][2:5] == ["--method", "PATCH", "repos/tj-agents/r"])
        self.assertEqual({"allow_auto_merge": True}, json.loads(patch[1]))

    def test_dry_run_never_writes(self):
        gh = FakeGh({"repos/tj-agents/r/rulesets?per_page=100": []})
        self.assertEqual("create", merge_policy.apply("tj-agents/r", HUMAN, dry_run=True, run=gh)["action"])
        self.assertFalse(any("--method" in command for command, _ in gh.calls))

    def test_api_failure_is_reported(self):
        def failing(command, **kwargs):
            return subprocess.CompletedProcess(command, 1, "", "HTTP 403: Upgrade to GitHub Pro")
        with self.assertRaisesRegex(merge_policy.PolicyError, "Upgrade to GitHub Pro"):
            merge_policy.apply("tj-agents/r", HUMAN, run=failing)


class CheckTests(unittest.TestCase):
    def check(self, policy, enforced):
        gh = FakeGh({"repos/tj-agents/r": {"default_branch": "main"}, "repos/tj-agents/r/rules/branches/main?per_page=100": enforced})
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
        self.assertEqual(4, len(problems))
        self.assertIn("required checks not enforced: ci-required", problems)

    def test_policy_and_rules_disagreeing_on_who_merges_is_drift(self):
        self.assertIn("no approval is required", self.check(HUMAN, rules(AGENTS)))
        self.assertTrue(any("agents may merge" in problem for problem in self.check(AGENTS, rules(HUMAN))))

    def test_policies_reject_rules_that_invalidate_earlier_approvals(self):
        for policy in (HUMAN, AGENTS):
            with self.subTest(policy=policy):
                strict = rules(policy)
                review = next(rule for rule in strict if rule["type"] == "pull_request")["parameters"]
                review["dismiss_stale_reviews_on_push"] = True
                review["require_last_push_approval"] = True
                self.assertEqual(
                    ["approval of the most recent push is required", "a new push dismisses earlier approvals"],
                    self.check(policy, strict),
                )

    def test_sync_applies_only_declared_policies_and_only_where_drifted(self):
        import base64
        ci = {"agents_may_merge": False, "ci_pushes_default_branch": True}
        encoded = base64.b64encode(json.dumps(ci).encode()).decode()
        responses = {
            "users/tj-agents/repos?type=owner&per_page=100&page=1": [
                {"full_name": "tj-agents/new"}, {"full_name": "tj-agents/core"}, {"full_name": "tj-agents/done"},
                {"full_name": "tj-agents/secret", "private": True}, {"full_name": "tj-agents/copy", "fork": True}],
            "repos/tj-agents/new/contents/.github/merge-policy.json": 404,
            "repos/tj-agents/done/contents/.github/merge-policy.json": {"content": base64.b64encode(b'{"agents_may_merge": false}').decode()},
            "repos/tj-agents/core/contents/.github/merge-policy.json": {"content": encoded},
            "repos/tj-agents/done/rules/branches/main?per_page=100": rules({"agents_may_merge": False}),
            "repos/tj-agents/new/rulesets?per_page=100": [],
            "repos/tj-agents/core/rulesets?per_page=100": [],
        }
        for name in ("new", "core", "done"):
            responses[f"repos/tj-agents/{name}"] = {"default_branch": "main"}
        gh = FakeGh(responses)
        results = {repository: action for repository, action, _ in merge_policy.sync(["tj-agents"], run=gh)}
        self.assertEqual({"tj-agents/core": "created", "tj-agents/done": "current"}, results)
        posted = {command[4]: json.loads(payload) for command, payload in gh.calls if "POST" in command}
        self.assertEqual(["repos/tj-agents/core/rulesets"], list(posted))
        self.assertEqual(2, len(posted["repos/tj-agents/core/rulesets"]["bypass_actors"]))

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
