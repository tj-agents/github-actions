import base64
import importlib.util
import json
from pathlib import Path
import unittest
from unittest import mock

from test_merge_policy import FakeGh, HUMAN, merge_policy, rules

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".agents/github-actions/utility/machine-events/scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


publish = load("publish")
caller = load("caller")


class PublisherTests(unittest.TestCase):
    def test_main_merge_reports_categories_without_contents(self):
        event = {"ref": "refs/heads/main", "commits": [{"modified": ["plugins/a", ".github/merge-policy.json"]}]}
        self.assertEqual({"v": 1, "repo": "tj-agents/core", "changes": ["repository", "merge-policy", "marketplace"]},
                         publish.hint(event, "tj-agents/core"))
        for ref in ("refs/pull/1/merge", "refs/heads/feature"):
            self.assertIsNone(publish.hint({"ref": ref}, "tj-agents/core"))
        self.assertIsNone(publish.hint({"ref": "refs/heads/main", "deleted": True}, "tj-agents/core"))

    def test_payload_never_uses_a_hinted_url_or_shell(self):
        with self.assertRaises(ValueError):
            publish.hint({}, "evil/repository")
        opener = mock.MagicMock()
        with self.assertRaises(ValueError):
            publish.publish("../../bad", {}, opener)
        opener.assert_not_called()
        publish.publish("a" * 48, {"v": 1}, opener)
        request = opener.call_args.args[0]
        self.assertEqual("https://ntfy.sh/" + "a" * 48, request.full_url)
        self.assertEqual({"v": 1}, json.loads(request.data))
        self.assertEqual(20, opener.call_args.kwargs["timeout"])

    def test_actions_push_payload_uses_compare_files_and_truncation_is_conservative(self):
        event = {"ref": "refs/heads/main", "before": "a" * 40, "after": "b" * 40}
        opener = mock.MagicMock()
        opener.return_value.__enter__.return_value.read.return_value = json.dumps({"files": [{"filename": ".github/merge-policy.json"}]}).encode()
        paths = publish.changed_paths(event, "tj-agents/core", "token", opener=opener)
        self.assertIn("merge-policy", publish.hint(event, "tj-agents/core", paths)["changes"])
        self.assertEqual(1, opener.call_count)
        opener.return_value.__enter__.return_value.read.return_value = json.dumps({"files": [{"filename": "x"}] * 300}).encode()
        paths = publish.changed_paths(event, "tj-agents/core", "token", opener=opener)
        self.assertIn("marketplace", publish.hint(event, "tj-agents/core", paths)["changes"])

    def test_uniform_caller_has_read_only_permissions_and_immutable_action(self):
        value = caller.render("a" * 40)
        self.assertIn("@" + "a" * 40, value)
        self.assertIn("contents: read", value)
        self.assertNotIn("schedule:", value)
        self.assertIn("topic: ${{ secrets.MACHINE_EVENTS_TOPIC }}", value)
        self.assertNotIn("secrets.GH_TOKEN", value)
        with self.assertRaises(ValueError):
            caller.render("main")


class ReconcileTests(unittest.TestCase):
    def responses(self, policy=HUMAN):
        return {"repos/tj-agents/core": {"default_branch": "main", "allow_auto_merge": policy.get("enabled", True)},
                "repos/tj-agents/core/commits/main": {"sha": "b" * 40},
                "repos/tj-agents/core/contents/.github/merge-policy.json?ref=" + "b" * 40:
                    {"content": base64.b64encode(json.dumps(policy).encode()).decode()},
                "repos/tj-agents/core/rulesets?per_page=100": [{"name": "merge-policy", "id": 3}],
                "repos/tj-agents/core/rulesets/3": merge_policy.ruleset(policy),
                "repos/tj-agents/core/rules/branches/main?per_page=100": rules(policy)}

    def test_current_committed_policy_is_read_at_authoritative_sha_without_write(self):
        gh = FakeGh(self.responses())
        self.assertEqual("current", merge_policy.reconcile("tj-agents/core", run=gh)["action"])
        self.assertFalse(any("--method" in command for command, _ in gh.calls))

    def test_changed_bypass_is_repaired_even_when_effective_rules_look_current(self):
        responses = self.responses()
        responses["repos/tj-agents/core/rulesets/3"] = {**merge_policy.ruleset(HUMAN), "bypass_actors": []}
        gh = FakeGh(responses)
        self.assertEqual("updated", merge_policy.reconcile("tj-agents/core", run=gh)["action"])
        self.assertEqual(1, sum("PUT" in command for command, _ in gh.calls))

    def test_no_file_never_invents_a_gate(self):
        responses = self.responses()
        responses["repos/tj-agents/core/contents/.github/merge-policy.json?ref=" + "b" * 40] = 404
        gh = FakeGh(responses)
        self.assertEqual("undeclared", merge_policy.reconcile("tj-agents/core", run=gh)["action"])
        self.assertEqual(3, len(gh.calls))

    def test_hinted_owner_outside_scope_never_reaches_github(self):
        gh = mock.Mock()
        with self.assertRaises(merge_policy.PolicyError):
            merge_policy.reconcile("other/repo", run=gh)
        gh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
