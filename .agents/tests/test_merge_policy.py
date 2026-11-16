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

HUMAN_DOCUMENT = {
    "approval": "human",
    "merge": "agents",
    "default_branch_push": "none",
    "required_checks": ["ci-required"],
}
AUTOMATED_DOCUMENT = {
    "approval": "automated",
    "merge": "agents",
    "default_branch_push": "none",
    "required_checks": ["ci-required"],
    "review_check": "agent-review",
}
HUMAN = merge_policy.validate_policy(HUMAN_DOCUMENT, "human")
AUTOMATED = merge_policy.validate_policy(AUTOMATED_DOCUMENT, "automated")
NONE = merge_policy.validate_policy({**HUMAN_DOCUMENT, "approval": "none"}, "none")
HUMAN_MERGE = merge_policy.validate_policy(
    {**HUMAN_DOCUMENT, "merge": "human"}, "merge"
)
OWNER_DEFAULT = "repos/tj-agents/.github/contents/.github/merge-policy.json"
MERGE_DENY = [
    "Bash(gh pr merge:*)",
    "PowerShell(gh pr merge:*)",
    "mcp__github__merge_pull_request",
]


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


def review_parameters(policy):
    return next(
        rule
        for rule in merge_policy.ruleset(policy)["rules"]
        if rule["type"] == "pull_request"
    )["parameters"]


def status_contexts(policy):
    checks = next(
        rule
        for rule in merge_policy.ruleset(policy)["rules"]
        if rule["type"] == "required_status_checks"
    )
    return [item["context"] for item in checks["parameters"]["required_status_checks"]]


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
            {**HUMAN_DOCUMENT, "approval": "yes"},
            {**HUMAN_DOCUMENT, "merge": True},
            {**HUMAN_DOCUMENT, "default_branch_push": "always"},
            {key: value for key, value in HUMAN_DOCUMENT.items() if key != "merge"},
            {**AUTOMATED_DOCUMENT, "review_check": ""},
            {
                key: value
                for key, value in AUTOMATED_DOCUMENT.items()
                if key != "review_check"
            },
            {**HUMAN_DOCUMENT, "review_check": "agent-review"},
            {**HUMAN_DOCUMENT, "required_checks": [""]},
            {**HUMAN_DOCUMENT, "extra": 1},
        ):
            with self.subTest(value=value), self.assertRaises(merge_policy.PolicyError):
                merge_policy.load_policy(self.write(value))

    def test_the_replaced_boolean_fields_are_rejected(self):
        for field in ("requires_approval", "ci_pushes_default_branch"):
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(
                    merge_policy.PolicyError, f"unknown keys: {field}"
                ),
            ):
                merge_policy.load_policy(self.write({**HUMAN_DOCUMENT, field: True}))

    def test_human_approval_retains_one_approval_across_pushes(self):
        ruleset = merge_policy.ruleset(HUMAN)
        review = review_parameters(HUMAN)
        self.assertEqual(1, review["required_approving_review_count"])
        self.assertFalse(review["dismiss_stale_reviews_on_push"])
        self.assertFalse(review["require_last_push_approval"])
        self.assertEqual(["ci-required"], status_contexts(HUMAN))
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

    def test_automated_approval_requires_the_review_check_instead(self):
        self.assertEqual(
            0, review_parameters(AUTOMATED)["required_approving_review_count"]
        )
        self.assertEqual(["ci-required", "agent-review"], status_contexts(AUTOMATED))

    def test_no_approval_leaves_only_the_required_checks(self):
        self.assertEqual(0, review_parameters(NONE)["required_approving_review_count"])
        self.assertEqual(["ci-required"], status_contexts(NONE))

    def test_ci_default_branch_push_lets_deploy_keys_bypass(self):
        ci = merge_policy.validate_policy(
            {**HUMAN_DOCUMENT, "default_branch_push": "ci"}, "ci"
        )
        actors = merge_policy.ruleset(ci)["bypass_actors"]
        self.assertIn({"actor_type": "DeployKey", "bypass_mode": "always"}, actors)

    def test_merge_does_not_change_the_ruleset(self):
        self.assertEqual(merge_policy.ruleset(HUMAN), merge_policy.ruleset(HUMAN_MERGE))


class OwnerDefaultTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "merge-policy.json"

    def test_repository_file_overrides_the_owner_default_entirely(self):
        self.path.write_text(json.dumps(AUTOMATED_DOCUMENT), encoding="utf-8")
        gh = FakeGh({OWNER_DEFAULT: HUMAN_DOCUMENT})
        policy = merge_policy.effective_policy(self.path, "tj-agents/r", run=gh)
        self.assertEqual(AUTOMATED, policy)
        self.assertEqual([], gh.calls)

    def test_owner_default_applies_without_a_repository_file(self):
        gh = FakeGh({OWNER_DEFAULT: HUMAN_DOCUMENT})
        self.assertEqual(
            HUMAN, merge_policy.effective_policy(self.path, "tj-agents/r", run=gh)
        )
        self.assertIn("Accept: application/vnd.github.raw+json", gh.calls[0][0])

    def test_no_policy_anywhere_is_an_error(self):
        with self.assertRaisesRegex(merge_policy.PolicyError, "no merge policy"):
            merge_policy.effective_policy(
                self.path, "tj-agents/r", run=FakeGh({OWNER_DEFAULT: 404})
            )
        with self.assertRaisesRegex(merge_policy.PolicyError, "--repo"):
            merge_policy.effective_policy(self.path, None, run=FakeGh({}))

    def test_an_invalid_owner_default_names_its_source(self):
        gh = FakeGh({OWNER_DEFAULT: {"requires_approval": True}})
        with self.assertRaisesRegex(merge_policy.PolicyError, "tj-agents/.github"):
            merge_policy.effective_policy(self.path, "tj-agents/r", run=gh)


class HarnessTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / ".agents/repository-harness.json"

    def overlay(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def test_human_merge_creates_an_overlay_denying_every_merge_command(self):
        self.assertTrue(merge_policy.write_harness(HUMAN_MERGE, self.path))
        overlay = self.overlay()
        permissions = overlay["requires"]["permissions"]
        self.assertEqual(
            {"marketplaces": [], "plugins": [], "permissions": permissions},
            overlay["requires"],
        )
        self.assertEqual(MERGE_DENY, permissions["claude_deny"])
        self.assertEqual(
            [["gh", "pr", "merge"]],
            [rule["pattern"] for rule in permissions["codex_forbidden_prefix_rules"]],
        )
        self.assertEqual([], merge_policy.harness_drift(HUMAN_MERGE, self.path))
        self.assertFalse(merge_policy.write_harness(HUMAN_MERGE, self.path))

    def test_agent_merge_needs_no_overlay(self):
        self.assertFalse(merge_policy.write_harness(HUMAN, self.path))
        self.assertFalse(self.path.exists())
        self.assertEqual([], merge_policy.harness_drift(HUMAN, self.path))

    def test_the_repository_s_own_entries_are_kept(self):
        own_rule = {
            "pattern": ["gh", "auth", "login"],
            "justification": "Account-wide scopes.",
            "match": [["gh", "auth", "login"]],
            "not_match": [["gh", "auth", "status"]],
        }
        self.path.parent.mkdir(parents=True)
        original = {
            "schema_version": 1,
            "requires": {
                "marketplaces": [],
                "plugins": [],
                "hooks": [],
                "permissions": {
                    "claude_allow": ["Bash(git fetch:*)"],
                    "claude_deny": ["Bash(gh auth login:*)"],
                    "codex_prefix_rules": [],
                    "codex_forbidden_prefix_rules": [own_rule],
                },
            },
        }
        self.path.write_text(json.dumps(original), encoding="utf-8")
        merge_policy.write_harness(HUMAN_MERGE, self.path)
        permissions = self.overlay()["requires"]["permissions"]
        self.assertEqual(
            ["Bash(gh auth login:*)", *MERGE_DENY], permissions["claude_deny"]
        )
        self.assertEqual(own_rule, permissions["codex_forbidden_prefix_rules"][0])
        self.assertEqual(["Bash(git fetch:*)"], permissions["claude_allow"])
        self.assertTrue(merge_policy.write_harness(HUMAN, self.path))
        self.assertEqual(original, self.overlay())

    def test_overlay_out_of_step_with_the_merge_policy_is_drift(self):
        merge_policy.write_harness(HUMAN_MERGE, self.path)
        self.assertEqual(1, len(merge_policy.harness_drift(HUMAN, self.path)))
        self.path.unlink()
        self.assertEqual(1, len(merge_policy.harness_drift(HUMAN_MERGE, self.path)))


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
        for policy in (HUMAN, AUTOMATED, NONE):
            with self.subTest(policy=policy):
                self.assertEqual([], self.check(policy, rules(policy)))

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

    def test_policy_and_rules_disagreeing_on_approval_is_drift(self):
        self.assertIn("no approval is required", self.check(HUMAN, rules(AUTOMATED)))
        self.assertTrue(
            any(
                "but none should be" in problem
                for problem in self.check(NONE, rules(HUMAN))
            )
        )
        self.assertIn(
            "required checks not enforced: agent-review",
            self.check(AUTOMATED, rules(NONE)),
        )

    def test_policies_reject_rules_that_invalidate_earlier_approvals(self):
        for policy in (HUMAN, AUTOMATED):
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
            policy.write_text(json.dumps(HUMAN_DOCUMENT), encoding="utf-8")
            render = subprocess.run(
                [sys.executable, "-B", str(SCRIPT), "render", "--policy", str(policy)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, render.returncode)
            self.assertEqual("merge-policy", json.loads(render.stdout)["name"])
            harness = Path(directory) / "repository-harness.json"
            policy.write_text(
                json.dumps({**HUMAN_DOCUMENT, "merge": "human"}), encoding="utf-8"
            )
            write = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPT),
                    "harness",
                    "--repo",
                    "tj-agents/r",
                    "--policy",
                    str(policy),
                    "--harness",
                    str(harness),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, write.returncode, write.stderr)
            self.assertIn(
                "mcp__github__merge_pull_request", harness.read_text(encoding="utf-8")
            )
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
