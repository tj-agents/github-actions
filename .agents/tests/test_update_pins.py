import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
ACTION = ROOT / ".github/actions/update-pins/update_pins.py"
CALLER = ROOT / ".agents/github-actions/utility/publish-update/scripts/caller.py"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


updater = load("update_pins", ACTION)
caller = load("caller", CALLER)


class UpdatePinsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name)
        self.workflows = self.project / ".github/workflows"
        self.workflows.mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, name, content):
        path = self.workflows / name
        path.write_text(content, encoding="utf-8", newline="")
        return path

    def test_updates_arbitrary_configured_owner_and_preserves_nested_quoted_references(self):
        path = self.write("ci.yml", """steps:
  - uses: 'neutral/actions/.github/actions/check@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
  - uses: other/tool@bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
  - uses: ./local-action
""")
        summary = updater.update(self.project, ["neutral/actions"], files=[".github/workflows/ci.yml"], resolver=lambda _: "c" * 40, comparer=lambda *_: None)
        content = path.read_text(encoding="utf-8")
        self.assertEqual({"changed": True, "files": 1, "repositories": ["neutral/actions"]}, summary)
        self.assertIn("'neutral/actions/.github/actions/check@" + "c" * 40 + "'", content)
        self.assertIn("other/tool@" + "b" * 40, content)
        self.assertIn("uses: ./local-action", content)

    def test_matches_repository_case_insensitively_and_preserves_crlf(self):
        path = self.write("windows.yml", "- uses: \"neutral/actions@" + "a" * 40 + "\"\r\n")
        updater.update(self.project, updater.parse_repositories("Neutral/Actions,neutral/actions"), files=[".github/workflows/windows.yml"], resolver=lambda _: "c" * 40, comparer=lambda *_: None)
        self.assertEqual("- uses: \"neutral/actions@" + "c" * 40 + "\"\r\n", path.read_bytes().decode("utf-8"))

    def test_case_insensitive_references_share_one_comparison(self):
        self.write("case.yml", """uses: neutral/actions@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
uses: Neutral/Actions@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
""")
        comparisons = []
        updater.update(self.project, ["neutral/actions"], files=[".github/workflows/case.yml"], resolver=lambda _: "c" * 40, comparer=lambda *value: comparisons.append(value))
        self.assertEqual([("neutral/actions", "a" * 40, "c" * 40)], comparisons)

    def test_skips_literal_folded_and_multiline_quoted_scalars(self):
        path = self.write("scalars.yml", """steps:
# example: |
  - uses: neutral/actions@bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
  - run: &heredoc.script !<tag:yaml.org,2002:str> |-
      cat <<'EOF'
      uses: neutral/actions@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
      EOF
  - 'run': ! &folded.script >+
      uses: neutral/actions@dddddddddddddddddddddddddddddddddddddddd
  - name: !text &quoted "literal
      uses: neutral/actions@eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee
      value"
  - name: |
      display name
    uses: 'neutral/actions@bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
""")
        comparisons = []
        updater.update(self.project, ["neutral/actions"], files=[".github/workflows/scalars.yml"], resolver=lambda _: "c" * 40, comparer=lambda *value: comparisons.append(value))
        content = path.read_text(encoding="utf-8")
        self.assertIn("neutral/actions@" + "a" * 40, content)
        self.assertIn("neutral/actions@" + "d" * 40, content)
        self.assertIn("neutral/actions@" + "e" * 40, content)
        self.assertIn("- uses: neutral/actions@" + "c" * 40, content)
        self.assertIn("'neutral/actions@" + "c" * 40 + "'", content)
        self.assertEqual([("neutral/actions", "b" * 40, "c" * 40)], comparisons)

    def test_non_matching_refs_leave_files_unchanged(self):
        path = self.write("ci.yaml", "uses: neutral/actions@v2\n")
        before = path.read_text(encoding="utf-8")
        summary = updater.update(self.project, ["neutral/actions"], files=[".github/workflows/ci.yaml"], resolver=lambda _: "d" * 40)
        self.assertFalse(summary["changed"])
        self.assertEqual(before, path.read_text(encoding="utf-8"))

    def test_check_never_writes(self):
        path = self.write("ci.yml", "uses: neutral/actions@" + "a" * 40 + "\n")
        before = path.read_text(encoding="utf-8")
        summary = updater.update(self.project, ["neutral/actions"], check=True, files=[".github/workflows/ci.yml"], resolver=lambda _: "e" * 40, comparer=lambda *_: None)
        self.assertTrue(summary["changed"])
        self.assertEqual(before, path.read_text(encoding="utf-8"))

    def test_failed_second_lookup_is_atomic(self):
        path = self.write("ci.yml", """uses: neutral/actions@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
uses: neutral/other@bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
""")
        before = path.read_text(encoding="utf-8")
        calls = []
        def resolve(repository):
            calls.append(repository)
            if repository == "neutral/other":
                raise ValueError("lookup failed")
            return "c" * 40
        with self.assertRaises(ValueError):
            updater.update(self.project, ["neutral/actions", "neutral/other"], files=[".github/workflows/ci.yml"], resolver=resolve)
        self.assertEqual(["neutral/actions", "neutral/other"], calls)
        self.assertEqual(before, path.read_text(encoding="utf-8"))

    def test_behind_or_diverged_comparison_leaves_files_unchanged(self):
        for status in ("behind", "diverged"):
            with self.subTest(status=status):
                path = self.write(status + ".yml", "uses: neutral/actions@" + "a" * 40 + "\n")
                before = path.read_text(encoding="utf-8")
                def run(arguments):
                    return mock.Mock(stdout=status + "\n")
                with self.assertRaises(ValueError):
                    updater.update(self.project, ["neutral/actions"], files=[".github/workflows/" + status + ".yml"], resolver=lambda _: "c" * 40, comparer=lambda repository, old, new: updater.compare_revisions(repository, old, new, run))
                self.assertEqual(before, path.read_text(encoding="utf-8"))

    def test_check_reports_pending_change_without_writing(self):
        path = self.write("check.yml", "uses: neutral/actions@" + "a" * 40 + "\n")
        with mock.patch.object(updater, "update", return_value={"changed": True, "files": 1, "repositories": []}):
            self.assertEqual(1, updater.main(["--project", str(self.project), "--repositories", "neutral/actions", "--check"]))
        self.assertIn("@" + "a" * 40, path.read_text(encoding="utf-8"))

    def test_unsafe_repository_never_reaches_lookup(self):
        resolver = mock.Mock()
        with self.assertRaises(ValueError):
            updater.update(self.project, updater.parse_repositories("neutral/actions/extra"), resolver=resolver)
        resolver.assert_not_called()

    def test_symlinked_file_is_refused_before_lookup(self):
        path = self.write("ci.yml", "uses: neutral/actions@" + "a" * 40 + "\n")
        resolver = mock.Mock()
        original = updater.os.path.islink
        with mock.patch.object(updater.os.path, "islink", side_effect=lambda value: Path(value).resolve() == path.resolve() or original(value)), self.assertRaises(ValueError):
            updater.update(self.project, ["neutral/actions"], files=[".github/workflows/ci.yml"], resolver=resolver)
        resolver.assert_not_called()

    def test_resolves_actual_default_branch(self):
        calls = []
        def run(arguments):
            calls.append(arguments)
            if arguments[2] == "repos/neutral/actions":
                return mock.Mock(stdout="trunk\n")
            return mock.Mock(stdout="f" * 40 + "\n")
        self.assertEqual("f" * 40, updater.resolve_repository("neutral/actions", run))
        self.assertEqual(["gh", "api", "repos/neutral/actions", "--jq", ".default_branch"], calls[0])
        self.assertEqual("repos/neutral/actions/commits/trunk", calls[1][2])


class CallerTests(unittest.TestCase):
    def test_updater_caller_uses_the_canonical_workflow(self):
        workflow = caller.render_updater("a" * 40, "neutral/actions,Neutral/Actions,neutral/other")
        self.assertIn("cron: '17 */6 * * *'", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("uses: tj-agents/github-actions/.github/workflows/update-pins.yml@" + "a" * 40, workflow)
        self.assertIn("UPDATE_APP_PRIVATE_KEY: ${{ secrets.UPDATE_APP_PRIVATE_KEY }}", workflow)
        self.assertIn("repositories: neutral/actions,neutral/other", workflow)
        self.assertNotIn("environment:", workflow)
        self.assertNotIn("runs-on:", workflow)
        self.assertNotIn("steps:", workflow)
        self.assertNotIn("client-id:", workflow)
        self.assertNotIn("permission-contents:", workflow)


if __name__ == "__main__":
    unittest.main()
