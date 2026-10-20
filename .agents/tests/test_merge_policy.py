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
        path = next(part for part in command[2:] if part.startswith("repos/"))
        value = self.responses.get(path, {})
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
        for value in ({}, {"agents_may_merge": "yes"}, {"agents_may_merge": True},
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

    def test_agent_merge_requires_the_review_check_instead_of_an_approval(self):
        ruleset = merge_policy.ruleset(AGENTS)
        review = next(rule for rule in ruleset["rules"] if rule["type"] == "pull_request")["parameters"]
        checks = next(rule for rule in ruleset["rules"] if rule["type"] == "required_status_checks")
        self.assertEqual(0, review["required_approving_review_count"])
        self.assertEqual(["ci-required", "agent-review"],
                         [item["context"] for item in checks["parameters"]["required_status_checks"]])


class ApplyTests(unittest.TestCase):
    def test_creates_when_absent_and_updates_the_existing_ruleset(self):
        gh = FakeGh({"repos/o/r/rulesets?per_page=100": [{"id": 9, "name": "other"}]})
        self.assertEqual("created", merge_policy.apply("o/r", HUMAN, run=gh)["action"])
        self.assertEqual(["--method", "POST", "repos/o/r/rulesets"], gh.calls[-1][0][2:5])
        self.assertEqual("merge-policy", json.loads(gh.calls[-1][1])["name"])
        gh = FakeGh({"repos/o/r/rulesets?per_page=100": [{"id": 7, "name": "merge-policy", "source_type": "Repository"}]})
        self.assertEqual("updated", merge_policy.apply("o/r", HUMAN, run=gh)["action"])
        self.assertEqual(["--method", "PUT", "repos/o/r/rulesets/7"], gh.calls[-1][0][2:5])

    def test_dry_run_never_writes(self):
        gh = FakeGh({"repos/o/r/rulesets?per_page=100": []})
        self.assertEqual("create", merge_policy.apply("o/r", HUMAN, dry_run=True, run=gh)["action"])
        self.assertEqual(1, len(gh.calls))

    def test_api_failure_is_reported(self):
        def failing(command, **kwargs):
            return subprocess.CompletedProcess(command, 1, "", "HTTP 403: Upgrade to GitHub Pro")
        with self.assertRaisesRegex(merge_policy.PolicyError, "Upgrade to GitHub Pro"):
            merge_policy.apply("o/r", HUMAN, run=failing)


class CheckTests(unittest.TestCase):
    def check(self, policy, enforced):
        gh = FakeGh({"repos/o/r": {"default_branch": "main"}, "repos/o/r/rules/branches/main?per_page=100": enforced})
        return merge_policy.check("o/r", policy, run=gh)

    def test_applied_policy_has_no_drift(self):
        self.assertEqual([], self.check(HUMAN, rules(HUMAN)))
        self.assertEqual([], self.check(AGENTS, rules(AGENTS)))

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
