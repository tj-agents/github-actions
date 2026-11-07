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

HUMAN = {"requires_approval": True, "required_checks": ["ci-required"]}
AGENTS = {
    "requires_approval": False,
    "required_checks": ["ci-required"],
    "review_check": "agent-review",
}


class FakeGh:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs.get("input")))
        path = next(
            part for part in command[2:] if part.startswith(("repos/", "users/"))
        )
        value = self.responses.get(path, {})
        if value == 404:
            return subprocess.CompletedProcess(
                command, 1, "", "gh: Not Found (HTTP 404)"
            )
        return subprocess.CompletedProcess(command, 0, json.dumps(value), "")


def rules(policy):
    return [
        {**rule, "ruleset_source_type": "Repository"}
        for rule in merge_policy.ruleset(policy)["rules"]
    ]


class PolicyTests(unittest.TestCase):
    def write(self, value):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "merge-policy.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_invalid_policies_are_refused(self):
        for value in (
            {},
            {"requires_approval": "yes"},
            {"requires_approval": False, "review_check": ""},
            {"requires_approval": True, "review_check": "agent-review"},
            {"requires_approval": True, "required_checks": [""]},
            {"requires_approval": True, "extra": 1},
        ):
            with self.subTest(value=value), self.assertRaises(merge_policy.PolicyError):
                merge_policy.load_policy(self.write(value))

    def test_human_merge_retains_one_approval_across_pushes(self):
        ruleset = merge_policy.ruleset(HUMAN)
        review = next(
            rule for rule in ruleset["rules"] if rule["type"] == "pull_request"
        )["parameters"]
        checks = next(
            rule
            for rule in ruleset["rules"]
            if rule["type"] == "required_status_checks"
        )
        self.assertEqual(1, review["required_approving_review_count"])
        self.assertFalse(review["dismiss_stale_reviews_on_push"])
        self.assertFalse(review["require_last_push_approval"])
        self.assertEqual(
            [{"context": "ci-required"}], checks["parameters"]["required_status_checks"]
        )
        self.assertEqual(
            [
                {
                    "actor_id": 5,
                    "actor_type": "RepositoryRole",
                    "bypass_mode": "pull_request",
                }
            ],
            ruleset["bypass_actors"],
        )
        self.assertEqual(
            ["~DEFAULT_BRANCH"], ruleset["conditions"]["ref_name"]["include"]
        )

    def test_ci_pushes_let_deploy_keys_bypass(self):
        actors = merge_policy.ruleset({**HUMAN, "ci_pushes_default_branch": True})[
            "bypass_actors"
        ]
        self.assertIn({"actor_type": "DeployKey", "bypass_mode": "always"}, actors)

    def test_agent_merge_requires_the_review_check_instead_of_an_approval(self):
        ruleset = merge_policy.ruleset(AGENTS)
        review = next(
            rule for rule in ruleset["rules"] if rule["type"] == "pull_request"
        )["parameters"]
        checks = next(
            rule
            for rule in ruleset["rules"]
            if rule["type"] == "required_status_checks"
        )
        self.assertEqual(0, review["required_approving_review_count"])
        self.assertEqual(
            ["ci-required", "agent-review"],
            [
                item["context"]
                for item in checks["parameters"]["required_status_checks"]
            ],
        )


class CheckTests(unittest.TestCase):
    def check(self, policy, enforced):
        gh = FakeGh(
            {
                "repos/tj-agents/r": {"default_branch": "main"},
                "repos/tj-agents/r/rules/branches/main?per_page=100": enforced,
            }
        )
        return merge_policy.check("tj-agents/r", policy, run=gh)

    def test_applied_policy_has_no_drift(self):
        self.assertEqual([], self.check(HUMAN, rules(HUMAN)))
        self.assertEqual([], self.check(AGENTS, rules(AGENTS)))

    def test_disabled_auto_merge_is_drift(self):
        gh = FakeGh(
            {
                "repos/tj-agents/r": {
                    "default_branch": "main",
                    "allow_auto_merge": False,
                },
                "repos/tj-agents/r/rules/branches/main?per_page=100": rules(HUMAN),
            }
        )
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
        self.assertTrue(
            any(
                "but none should be" in problem
                for problem in self.check(AGENTS, rules(HUMAN))
            )
        )

    def test_policies_reject_rules_that_invalidate_earlier_approvals(self):
        for policy in (HUMAN, AGENTS):
            with self.subTest(policy=policy):
                strict = rules(policy)
                review = next(
                    rule for rule in strict if rule["type"] == "pull_request"
                )["parameters"]
                review["dismiss_stale_reviews_on_push"] = True
                review["require_last_push_approval"] = True
                self.assertEqual(
                    [
                        "approval of the most recent push is required",
                        "a new push dismisses earlier approvals",
                    ],
                    self.check(policy, strict),
                )

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = Path(directory) / "merge-policy.json"
            policy.write_text(json.dumps(HUMAN), encoding="utf-8")
            render = subprocess.run(
                [sys.executable, "-B", str(SCRIPT), "render", "--policy", str(policy)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, render.returncode)
            self.assertEqual("merge-policy", json.loads(render.stdout)["name"])
            policy.write_text("{}", encoding="utf-8")
            invalid = subprocess.run(
                [sys.executable, "-B", str(SCRIPT), "render", "--policy", str(policy)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(2, invalid.returncode)


if __name__ == "__main__":
    unittest.main()
