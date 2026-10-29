import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
ACTION = ROOT / ".github/actions/update-pins/update_pins.py"
CALLER = ROOT / ".agents/github-actions/skills/publish-update/scripts/caller.py"


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
        summary = updater.update(self.project, ["neutral/actions"], files=[".github/workflows/ci.yml"], resolver=lambda _: "c" * 40, comparer=lambda *_: None, content_comparer=lambda *_: True)
        content = path.read_text(encoding="utf-8")
        self.assertEqual({"changed": True, "files": 1, "repositories": ["neutral/actions"]}, summary)
        self.assertIn("'neutral/actions/.github/actions/check@" + "c" * 40 + "'", content)
        self.assertIn("other/tool@" + "b" * 40, content)
        self.assertIn("uses: ./local-action", content)

    def test_matches_repository_case_insensitively_and_preserves_crlf(self):
        path = self.write("windows.yml", "- uses: \"neutral/actions@" + "a" * 40 + "\"\r\n")
        updater.update(self.project, updater.parse_repositories("Neutral/Actions,neutral/actions"), files=[".github/workflows/windows.yml"], resolver=lambda _: "c" * 40, comparer=lambda *_: None, content_comparer=lambda *_: True)
        self.assertEqual("- uses: \"neutral/actions@" + "c" * 40 + "\"\r\n", path.read_bytes().decode("utf-8"))

    def test_case_insensitive_references_share_one_comparison(self):
        self.write("case.yml", """uses: neutral/actions@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
uses: Neutral/Actions@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
""")
        comparisons = []
        content_comparisons = []
        updater.update(self.project, ["neutral/actions"], files=[".github/workflows/case.yml"], resolver=lambda _: "c" * 40, comparer=lambda *value: comparisons.append(value), content_comparer=lambda *value: content_comparisons.append(value) or True)
        self.assertEqual([("neutral/actions", "a" * 40, "c" * 40)], comparisons)
        self.assertEqual([("neutral/actions", "", "a" * 40, "c" * 40)], content_comparisons)

    def test_unchanged_action_content_across_head_advances_leaves_files_unmodified(self):
        path = self.write("self.yml", "uses: tj-agents/github-actions/.github/actions/update-pins@" + "a" * 40 + "\n")
        before = path.read_text(encoding="utf-8")
        calls = []
        for revision in ("b" * 40, "c" * 40):
            summary = updater.update(
                self.project,
                ["tj-agents/github-actions"],
                files=[".github/workflows/self.yml"],
                resolver=lambda _, revision=revision: revision,
                comparer=lambda *_: None,
                content_comparer=lambda *value: calls.append(value) or False,
            )
            self.assertFalse(summary["changed"])
            self.assertEqual(before, path.read_text(encoding="utf-8"))
        self.assertEqual([
            ("tj-agents/github-actions", "/.github/actions/update-pins", "a" * 40, "b" * 40),
            ("tj-agents/github-actions", "/.github/actions/update-pins", "a" * 40, "c" * 40),
        ], calls)

    def test_updates_changed_action_and_workflow_content(self):
        path = self.write("references.yml", """uses: neutral/actions/.github/actions/check@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
uses: neutral/actions/.github/workflows/release.yml@bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
""")
        comparisons = []
        updater.update(
            self.project,
            ["neutral/actions"],
            files=[".github/workflows/references.yml"],
            resolver=lambda _: "c" * 40,
            comparer=lambda *_: None,
            content_comparer=lambda *value: comparisons.append(value) or True,
        )
        content = path.read_text(encoding="utf-8")
        self.assertEqual([
            ("neutral/actions", "/.github/actions/check", "a" * 40, "c" * 40),
            ("neutral/actions", "/.github/workflows/release.yml", "b" * 40, "c" * 40),
        ], comparisons)
        self.assertEqual(2, content.count("@" + "c" * 40))

    def test_mixed_content_changes_replace_only_changed_reference(self):
        path = self.write("mixed.yml", """uses: neutral/actions/.github/actions/changed@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
uses: neutral/actions/.github/actions/unchanged@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
""")
        updater.update(
            self.project,
            ["neutral/actions"],
            files=[".github/workflows/mixed.yml"],
            resolver=lambda _: "c" * 40,
            comparer=lambda *_: None,
            content_comparer=lambda repository, subpath, *rest: subpath == "/.github/actions/changed",
        )
        content = path.read_text(encoding="utf-8")
        self.assertIn("/.github/actions/changed@" + "c" * 40, content)
        self.assertIn("/.github/actions/unchanged@" + "a" * 40, content)

    def test_failed_second_content_lookup_is_atomic(self):
        path = self.write("content.yml", """uses: neutral/actions/.github/actions/first@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
uses: neutral/actions/.github/actions/second@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
""")
        before = path.read_text(encoding="utf-8")
        calls = []
        def compare_content(repository, subpath, old, new):
            calls.append((repository, subpath, old, new))
            if subpath == "/.github/actions/second":
                raise ValueError("content comparison failed")
            return True
        with self.assertRaisesRegex(ValueError, "^content comparison failed$"):
            updater.update(
                self.project,
                ["neutral/actions"],
                files=[".github/workflows/content.yml"],
                resolver=lambda _: "c" * 40,
                comparer=lambda *_: None,
                content_comparer=compare_content,
            )
        self.assertEqual([
            ("neutral/actions", "/.github/actions/first", "a" * 40, "c" * 40),
            ("neutral/actions", "/.github/actions/second", "a" * 40, "c" * 40),
        ], calls)
        self.assertEqual(before, path.read_text(encoding="utf-8"))

    def test_content_comparison_uses_object_ids(self):
        calls = []
        def run(arguments):
            calls.append(arguments)
            return mock.Mock(stdout="""{"data":{"repository":{"before":{"oid":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","__typename":"Tree"},"after":{"oid":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","__typename":"Tree"}}}}""")
        self.assertTrue(updater.compare_contents("neutral/actions", "/.github/actions/check", "c" * 40, "d" * 40, run))
        root_calls = []
        self.assertFalse(updater.compare_contents("neutral/actions", "", "e" * 40, "f" * 40, lambda arguments: root_calls.append(arguments) or mock.Mock(stdout="""{"data":{"repository":{"before":{"oid":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","__typename":"Tree"},"after":{"oid":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","__typename":"Tree"}}}}""")))
        self.assertEqual([
            "gh", "api", "graphql",
            "-f", "query=" + updater.CONTENT_QUERY,
            "-f", "owner=neutral",
            "-f", "name=actions",
            "-f", "before=" + "c" * 40 + ":.github/actions/check",
            "-f", "after=" + "d" * 40 + ":.github/actions/check",
        ], calls[0])
        self.assertEqual("before=" + "e" * 40 + ":", root_calls[0][-3])
        self.assertEqual("after=" + "f" * 40 + ":", root_calls[0][-1])

    def test_invalid_content_comparison_response_is_sanitized(self):
        responses = [
            "{",
            '{"errors":[{"message":"no"}]}',
            '{"data":{"repository":{"before":null,"after":null}}}',
            '{"data":{"repository":{"before":{"oid":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","__typename":"Commit"},"after":{"oid":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","__typename":"Blob"}}}}',
            '{"data":{"repository":{"before":{"oid":"short","__typename":"Blob"},"after":{"oid":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","__typename":"Blob"}}}}',
        ]
        for response in responses:
            with self.subTest(response=response), self.assertRaisesRegex(ValueError, "^content comparison failed$"):
                updater.compare_contents("neutral/actions", "", "a" * 40, "b" * 40, lambda _: mock.Mock(stdout=response))
        with self.assertRaisesRegex(ValueError, "^content comparison failed$"):
            updater.compare_contents("neutral/actions", "", "a" * 40, "b" * 40, lambda _: (_ for _ in ()).throw(updater.subprocess.CalledProcessError(1, "gh")))

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
        updater.update(self.project, ["neutral/actions"], files=[".github/workflows/scalars.yml"], resolver=lambda _: "c" * 40, comparer=lambda *value: comparisons.append(value), content_comparer=lambda *_: True)
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
        summary = updater.update(self.project, ["neutral/actions"], check=True, files=[".github/workflows/ci.yml"], resolver=lambda _: "e" * 40, comparer=lambda *_: None, content_comparer=lambda *_: True)
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
                content_comparer = mock.Mock()
                def run(arguments):
                    return mock.Mock(stdout=status + "\n")
                with self.assertRaises(ValueError):
                    updater.update(self.project, ["neutral/actions"], files=[".github/workflows/" + status + ".yml"], resolver=lambda _: "c" * 40, comparer=lambda repository, old, new: updater.compare_revisions(repository, old, new, run), content_comparer=content_comparer)
                self.assertEqual(before, path.read_text(encoding="utf-8"))
                content_comparer.assert_not_called()

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
