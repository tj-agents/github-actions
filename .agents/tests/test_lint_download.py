from __future__ import annotations

import importlib.util
import io
import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("lint_workflows_download", ROOT / ".agents/github-actions/skills/scaffold/templates/lint-workflows.py")
SCRIPT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCRIPT)


class WorkflowLintDownloadTests(TestCase):
    def download_request(self, url: str, token: str | None):
        with patch.dict(os.environ, {} if token is None else {"GITHUB_TOKEN": token}, clear=True):
            with patch.object(urllib.request, "urlopen", return_value=io.BytesIO(b"payload")) as urlopen:
                self.assertEqual(b"payload", SCRIPT.download(url))
        return urlopen.call_args.args[0]

    def test_github_api_download_uses_token_as_unredirected_header(self) -> None:
        request = self.download_request("https://api.github.com/repos/example/project", "secret-token")
        self.assertEqual("Bearer secret-token", request.get_header("Authorization"))
        self.assertEqual("Bearer secret-token", request.unredirected_hdrs["Authorization"])

    def test_github_api_download_without_token_has_no_authorization(self) -> None:
        request = self.download_request("https://api.github.com/repos/example/project", None)
        self.assertIsNone(request.get_header("Authorization"))

    def test_non_api_urls_do_not_receive_token(self) -> None:
        urls = (
            "https://github.com/example/project/archive.zip",
            "https://api.github.com.evil.example/repos/example/project",
            "http://api.github.com/repos/example/project",
        )
        for url in urls:
            with self.subTest(url=url):
                request = self.download_request(url, "secret-token")
                self.assertIsNone(request.get_header("Authorization"))

    def test_http_redirect_drops_unredirected_authorization(self) -> None:
        request = self.download_request("https://api.github.com/repos/example/project", "secret-token")
        redirected = urllib.request.HTTPRedirectHandler().redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://downloads.example/project.zip",
        )
        self.assertIsNotNone(redirected)
        self.assertIsNone(redirected.get_header("Authorization"))
