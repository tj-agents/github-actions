import base64
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock
from urllib.error import URLError
from urllib.request import Request

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".agents/github-actions/utility/publish-update/scripts/owner_setup.py"
SPEC = importlib.util.spec_from_file_location("owner_setup", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
owner_setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(owner_setup)


def test_app_permissions_are_separated_and_exact() -> None:
    updater: dict[str, Any] = {
        "slug": "tj-agents-pin-updater",
        "owner": {"login": "tj-agents"},
        "permissions": {"metadata": "read", **owner_setup.PERMISSIONS},
    }
    controller: dict[str, Any] = {
        "slug": "tj-agents-enrollment-controller",
        "owner": {"login": "tj-agents"},
        "permissions": {"metadata": "read", **owner_setup.CONTROLLER_PERMISSIONS},
    }
    owner_setup.check_app(updater, "tj-agents", owner_setup.PERMISSIONS)
    owner_setup.check_app(controller, "tj-agents", owner_setup.CONTROLLER_PERMISSIONS)

    assert owner_setup.CONTROLLER_PERMISSIONS["contents"] == "read"
    for permission in ("pull_requests", "workflows"):
        assert permission not in owner_setup.CONTROLLER_PERMISSIONS
    for permission in ("administration", "environments", "secrets"):
        assert permission not in owner_setup.PERMISSIONS

    with (
        mock.patch("sys.stderr", new_callable=io.StringIO),
        pytest.raises(owner_setup.SetupError),
    ):
        owner_setup.check_app(
            {
                **controller,
                "permissions": {
                    **controller["permissions"],
                    "contents": "write",
                },
            },
            "tj-agents",
            owner_setup.CONTROLLER_PERMISSIONS,
        )


def test_owner_apply_refuses_agent_and_token_overrides_before_github() -> None:
    for environment in (
        {"TJ_AGENT": "1"},
        {"GH_TOKEN": "x"},
        {"GITHUB_TOKEN": "x"},
        {"GH_CONFIG_DIR": "x"},
    ):
        run = mock.Mock()
        assert (
            owner_setup.main(
                ["--owner", "tj-agents", "--apply"],
                environment=environment,
                run=run,
            )
            == 1
        )
        run.assert_not_called()


def test_preview_discloses_protected_secret_boundaries_without_github() -> None:
    run = mock.Mock()
    with mock.patch("sys.stdout", new_callable=io.StringIO) as output:
        assert owner_setup.main(["--owner", "tj-agents"], run=run) == 0
    run.assert_not_called()
    content = output.getvalue()
    assert "update-enrollment" in content
    assert "exact default branch" in content
    assert "updater key to update-pins" in content
    assert "organization secret" not in content


def test_apply_saves_its_failure_and_last_progress_without_console_relay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result_file = tmp_path / "owner result.json"
    observed = []

    def fail(*args: Any, **kwargs: Any) -> None:
        kwargs["progress"]("Checking protected enrollment for tj-agents/github")
        observed.append(json.loads(result_file.read_text(encoding="utf-8")))
        raise owner_setup.SetupError("GitHub request failed: HTTP 403")

    monkeypatch.setattr(owner_setup, "setup", fail)
    assert (
        owner_setup.main(
            ["--owner", "tj-agents", "--apply", "--result-file", str(result_file)],
            environment={},
        )
        == 1
    )
    assert observed[0]["state"] == "running"
    assert observed[0]["exit_code"] is None
    result = json.loads(result_file.read_text(encoding="utf-8"))
    assert result["owner"] == "tj-agents"
    assert result["pid"] == os.getpid()
    assert result["state"] == "failed"
    assert result["exit_code"] == 1
    assert result["phase"] == observed[0]["phase"]
    assert result["error"] == "GitHub request failed: HTTP 403"
    assert not list(tmp_path.glob("*.tmp"))


def test_result_reports_completion_only_after_setup_returns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result_file = tmp_path / "result.json"

    def complete(*args: Any, **kwargs: Any) -> None:
        assert json.loads(result_file.read_text(encoding="utf-8"))["state"] == "running"

    monkeypatch.setattr(owner_setup, "setup", complete)
    assert (
        owner_setup.main(
            ["--owner", "tj-agents", "--apply", "--result-file", str(result_file)],
            environment={},
        )
        == 0
    )
    result = json.loads(result_file.read_text(encoding="utf-8"))
    assert result["state"] == "complete"
    assert result["exit_code"] == 0
    assert "error" not in result


def test_preview_does_not_create_an_apply_result(tmp_path: Path) -> None:
    result_file = tmp_path / "result.json"
    run = mock.Mock()
    assert (
        owner_setup.main(
            ["--owner", "tj-agents", "--result-file", str(result_file)], run=run
        )
        == 0
    )
    assert not result_file.exists()
    run.assert_not_called()


def test_rejected_agent_saves_failure_before_any_github_call(tmp_path: Path) -> None:
    result_file = tmp_path / "result.json"
    run = mock.Mock()
    assert (
        owner_setup.main(
            ["--owner", "tj-agents", "--apply", "--result-file", str(result_file)],
            environment={"TJ_AGENT": "1"},
            run=run,
        )
        == 1
    )
    assert json.loads(result_file.read_text(encoding="utf-8"))["state"] == "failed"
    run.assert_not_called()


def test_unexpected_failure_is_saved_and_still_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result_file = tmp_path / "result.json"
    monkeypatch.setattr(
        owner_setup, "setup", mock.Mock(side_effect=RuntimeError("broken"))
    )
    with pytest.raises(RuntimeError, match="broken"):
        owner_setup.main(
            ["--owner", "tj-agents", "--apply", "--result-file", str(result_file)],
            environment={},
        )
    result = json.loads(result_file.read_text(encoding="utf-8"))
    assert result["state"] == "failed"
    assert result["error"] == "RuntimeError: broken"


def test_failure_result_and_console_redact_authentication_material(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    result_file = tmp_path / "result.json"
    manifest_code = "test-manifest-code"
    token = "ghp_testtokenvalue"
    key = "-----BEGIN PRIVATE KEY-----\ntestkeyvalue\n-----END PRIVATE KEY-----"
    failure = (
        f"app-manifests/{manifest_code}/conversions {token} {key} Bearer jwt-value"
    )
    monkeypatch.setattr(
        owner_setup, "setup", mock.Mock(side_effect=owner_setup.SetupError(failure))
    )
    assert (
        owner_setup.main(
            ["--owner", "tj-agents", "--apply", "--result-file", str(result_file)],
            environment={},
        )
        == 1
    )
    captured = capsys.readouterr()
    output = result_file.read_text(encoding="utf-8") + captured.out + captured.err
    for sensitive in (manifest_code, token, "testkeyvalue", "jwt-value"):
        assert sensitive not in output
    assert "[redacted" in output


@pytest.mark.skipif(sys.platform != "win32", reason="Windows owner launcher")
def test_windows_owner_launcher_refuses_agent_without_opening_a_window(
    tmp_path: Path,
) -> None:
    result_file = tmp_path / "owner result.json"
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-File",
            str(SCRIPT.with_suffix(".ps1")),
            "-Owner",
            "tj-agents",
            "-ResultFile",
            str(result_file),
        ],
        env={**os.environ, "TJ_AGENT": "1"},
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode != 0
    assert "your own GitHub sign-in" in result.stderr
    assert not result_file.exists()


def simulate_windows_launcher(
    directory: Path, *, interactive: bool = False
) -> subprocess.CompletedProcess[str]:
    launcher = directory / "owner_setup.ps1"
    launcher.write_text(
        SCRIPT.with_suffix(".ps1").read_text(encoding="utf-8"), encoding="utf-8"
    )
    fake_uv = directory / "fake_uv.ps1"
    fake_uv.write_text("exit 7\n", encoding="utf-8")
    arguments_file = directory / "arguments.json"
    result_file = directory / "result.json"

    def literal(path: Path) -> str:
        return "'" + str(path).replace("'", "''") + "'"

    mode = "-Interactive" if interactive else ""
    invocation = (
        f"& {literal(launcher)} -Owner tj-agents "
        f"-ResultFile {literal(result_file)} {mode}"
    )
    simulation = f"""
function global:Get-Command {{
    param($Name, $CommandType, $ErrorAction)
    [pscustomobject]@{{Source = {literal(fake_uv)}}}
}}
function global:Start-Process {{
    param($FilePath, $WindowStyle, [switch]$PassThru, [string[]]$ArgumentList)
    $ArgumentList | ConvertTo-Json | Set-Content -LiteralPath {literal(arguments_file)}
    [pscustomobject]@{{Id = 4242}}
}}
function global:Get-CimInstance {{
    param($ClassName, $Filter)
    [pscustomobject]@{{CommandLine = {literal(directory / "owner_setup.py")}}}
}}
{invocation}
if ($LASTEXITCODE) {{ exit $LASTEXITCODE }}
"""
    environment = {
        name: value
        for name, value in os.environ.items()
        if name not in {"TJ_AGENT", "GH_TOKEN", "GITHUB_TOKEN", "GH_CONFIG_DIR"}
    }
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", simulation],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows owner launcher")
def test_windows_launcher_preserves_paths_with_spaces(tmp_path: Path) -> None:
    directory = tmp_path / "skill and results with spaces"
    directory.mkdir()
    result = simulate_windows_launcher(directory)
    assert result.returncode == 0, result.stderr
    arguments = json.loads(
        (directory / "arguments.json").read_text(encoding="utf-8-sig")
    )
    assert (
        arguments[arguments.index("-File") + 1] == f'"{directory / "owner_setup.ps1"}"'
    )
    assert (
        arguments[arguments.index("-ResultFile") + 1]
        == f'"{directory / "result.json"}"'
    )
    assert arguments[-1] == "-Interactive"
    assert not (directory / "result.json").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows owner launcher")
def test_windows_startup_failure_replaces_stale_failure_without_console_relay(
    tmp_path: Path,
) -> None:
    result_file = tmp_path / "result.json"
    result_file.write_text(
        json.dumps(
            {
                "owner": "tj-agents",
                "state": "failed",
                "error": "earlier attempt",
                "observed_at": "2020-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    result = simulate_windows_launcher(tmp_path, interactive=True)
    assert result.returncode == 7, result.stderr
    receipt = json.loads(result_file.read_text(encoding="utf-8"))
    assert receipt["state"] == "failed"
    assert receipt["exit_code"] == 7
    assert "earlier attempt" not in receipt["error"]
    assert "before saving its failure result" in receipt["error"]
    assert not (tmp_path / "arguments.json").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows owner launcher")
def test_windows_launcher_reuses_the_active_attempt(tmp_path: Path) -> None:
    result_file = tmp_path / "result.json"
    previous = {"owner": "tj-agents", "state": "running", "pid": 123}
    result_file.write_text(json.dumps(previous), encoding="utf-8")
    result = simulate_windows_launcher(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "already running" in result.stdout
    assert not (tmp_path / "arguments.json").exists()
    assert json.loads(result_file.read_text(encoding="utf-8")) == previous


def test_discovery_reports_each_repository_and_reuses_its_verified_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = owner_setup.load_enrollment()
    repositories = ["tj-agents/first", "tj-agents/second"]
    monkeypatch.setattr(bridge, "inventory", lambda *_: iter(repositories))
    eligible = mock.Mock(return_value=False)
    monkeypatch.setattr(bridge, "eligible_repository", eligible)
    gh = mock.Mock()
    gh.api.return_value = {"default_branch": "main"}
    progress: list[str] = []
    assert bridge.legacy_key_locations(gh, "tj-agents", progress=progress.append) == []
    assert len(progress) == len(repositories)
    assert all(
        repository in message
        for repository, message in zip(repositories, progress, strict=True)
    )
    assert gh.api.call_count == len(repositories)
    assert all(call.args[-1] is gh.api.return_value for call in eligible.call_args_list)


def test_owner_read_does_not_treat_permission_failure_as_absent() -> None:
    commands: list[list[str]] = []

    class Forbidden:
        def __call__(
            self, command: list[str], **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            return subprocess.CompletedProcess(command, 1, "", "HTTP 403")

    runner = Forbidden()
    gh = owner_setup.GitHub(runner)
    with pytest.raises(owner_setup.SetupError, match="HTTP 403"):
        gh.optional("orgs/tj-agents/actions/secrets/UPDATE_APP_PRIVATE_KEY")
    assert commands[0][:4] == ["gh", "api", "--hostname", "github.com"]


def test_secret_set_binds_github_host_in_repository_selector() -> None:
    commands: list[list[str]] = []

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    owner_setup.GitHub(run).set_secret(
        "tj-agents/plugin", "update-pins", "UPDATE_APP_PRIVATE_KEY", "pem"
    )
    assert commands[0][:2] == ["gh", "secret"]
    assert "--hostname" not in commands[0]
    assert commands[0][commands[0].index("--repo") + 1] == (
        "github.com/tj-agents/plugin"
    )


def test_invalid_app_key_aborts_owner_setup_before_any_remote_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = "tj-agents"
    updater = {
        "id": 42,
        "client_id": "Iv1.updater",
        "owner": {"login": owner},
        "permissions": owner_setup.PERMISSIONS,
    }
    controller = {
        "id": 90,
        "client_id": "Iv1.controller",
        "owner": {"login": owner},
        "permissions": owner_setup.CONTROLLER_PERMISSIONS,
    }
    state: dict[str, Any] = {
        "legacy_org_secret": None,
        "slug": owner + "-pin-updater",
        "controller_slug": owner + "-enrollment-controller",
        "app": updater,
        "controller": controller,
    }
    monkeypatch.setattr(owner_setup, "discover", lambda *_: state)
    bridge = owner_setup.load_enrollment()
    verify = bridge.verify_app_key

    def rejected_key(request: Request, *, timeout: int) -> io.BytesIO:
        token = request.headers["Authorization"].removeprefix("Bearer ")
        payload = token.split(".")[1]
        claims = json.loads(
            base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        )
        assert claims["iss"] == "Iv1.updater"
        raise URLError("Bad credentials")

    def validate(owner: str, app_id: int, client_id: str, key: str) -> None:
        verify(owner, app_id, client_id, key, opener=rejected_key)

    monkeypatch.setattr(bridge, "verify_app_key", validate)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    gh = mock.Mock()
    with pytest.raises(bridge.EnrollmentError, match="no key was distributed"):
        owner_setup.setup(owner, gh, key=pem, controller_key=pem)
    gh.api.assert_not_called()
    gh.set_secret.assert_not_called()


@pytest.fixture
def legacy_state() -> dict[str, Any]:
    return {
        "legacy_org_secret": {"name": owner_setup.SECRET},
        "legacy_repositories": ["tj-agents/first", "tj-agents/second/update-pins"],
        "slug": "tj-agents-pin-updater",
        "app": {
            "slug": "tj-agents-pin-updater",
            "id": 42,
            "client_id": "Iv1.updater",
            "owner": {"login": "tj-agents"},
            "permissions": owner_setup.PERMISSIONS,
        },
        "variable": {"value": "Iv1.updater"},
    }


@pytest.mark.parametrize(
    "invalid", ["missing_app", "wrong_owner", "permissions", "client_id"]
)
def test_legacy_identity_is_checked_before_opening_any_key_settings(
    invalid: str, legacy_state: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    if invalid == "missing_app":
        legacy_state["app"] = None
    elif invalid == "wrong_owner":
        legacy_state["app"]["owner"] = {"login": "someone-else"}
    elif invalid == "permissions":
        legacy_state["app"]["permissions"] = {"contents": "read"}
    else:
        legacy_state["variable"]["value"] = "Iv1.unrelated-bot"
    monkeypatch.setattr(owner_setup, "discover", lambda *_: legacy_state)
    gh, browser, prompt = mock.Mock(), mock.Mock(), mock.Mock()
    with pytest.raises(owner_setup.SetupError):
        owner_setup.setup("tj-agents", gh, open_url=browser, prompt=prompt)
    browser.assert_not_called()
    prompt.assert_not_called()
    gh.assert_not_called()
    gh.api.assert_not_called()
    gh.set_secret.assert_not_called()


def test_legacy_metadata_does_not_establish_key_ownership(
    legacy_state: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(owner_setup, "discover", lambda *_: legacy_state)
    browser, prompt = mock.Mock(), mock.Mock(return_value="tj-agents-pin-updater")
    with pytest.raises(owner_setup.SetupError, match="ownership confirmation"):
        owner_setup.setup("tj-agents", mock.Mock(), open_url=browser, prompt=prompt)
    browser.assert_not_called()
    assert "EVERY listed location" in prompt.call_args.args[0]
    assert "App ID 42" in prompt.call_args.args[0]


def test_rotation_action_is_readable_at_each_prompt_without_console_relay(
    legacy_state: dict[str, Any], tmp_path: Path
) -> None:
    result_file = tmp_path / "result.json"
    reporter = owner_setup.SetupReporter("tj-agents", result_file)
    browser = mock.Mock()
    observed = []

    def respond(message: str) -> str:
        receipt = json.loads(result_file.read_text(encoding="utf-8"))
        observed.append(receipt)
        if len(observed) == 1:
            browser.assert_not_called()
            return "credentials belong to tj-agents-pin-updater"
        browser.assert_called_once_with(receipt["action"]["url"])
        return "revoked tj-agents-pin-updater"

    owner_setup.confirm_legacy_rotation(
        "tj-agents",
        legacy_state,
        browser,
        respond,
        reporter.progress,
        reporter.awaiting,
    )
    assert [item["action"]["kind"] for item in observed] == [
        "identify_legacy_app",
        "rotate_updater_keys",
    ]
    for item in observed:
        assert item["state"] == "running"
        assert len(item["action"]["locations"]) == 3
        assert "App ID 42" in json.dumps(item["action"])
        assert "Iv1.updater" in json.dumps(item["action"])
    reporter.finish(1, "owner stopped")
    assert (
        json.loads(result_file.read_text(encoding="utf-8"))["action"]
        == observed[-1]["action"]
    )
    reporter.progress("Verifying new key")
    assert "action" not in json.loads(result_file.read_text(encoding="utf-8"))


def test_legacy_exposure_requires_owner_key_revocation_before_migration(
    legacy_state: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(owner_setup, "discover", lambda *_: legacy_state)
    gh = mock.Mock()
    responses = iter(["credentials belong to tj-agents-pin-updater", "not confirmed"])
    with pytest.raises(owner_setup.SetupError, match="key-rotation confirmation"):
        owner_setup.setup(
            "tj-agents", gh, open_url=lambda _: None, prompt=lambda _: next(responses)
        )
    gh.api.assert_not_called()
    gh.set_secret.assert_not_called()


def test_legacy_rotation_refuses_a_key_selected_before_revocation(
    legacy_state: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(owner_setup, "discover", lambda *_: legacy_state)
    browser, prompt, gh = mock.Mock(), mock.Mock(), mock.Mock()
    with pytest.raises(owner_setup.SetupError, match="omit --updater-key-file"):
        owner_setup.setup(
            "tj-agents", gh, key="old-key", open_url=browser, prompt=prompt
        )
    browser.assert_not_called()
    prompt.assert_not_called()
    gh.api.assert_not_called()


def test_confirmed_rotation_relaxes_only_the_central_publisher_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = "tj-agents"
    updater = {
        "id": 42,
        "client_id": "Iv1.updater",
        "owner": {"login": owner},
        "permissions": owner_setup.PERMISSIONS,
    }
    controller = {
        "id": 90,
        "client_id": "Iv1.controller",
        "owner": {"login": owner},
        "permissions": owner_setup.CONTROLLER_PERMISSIONS,
    }
    state: dict[str, Any] = {
        "legacy_org_secret": {"name": owner_setup.SECRET},
        "slug": owner + "-pin-updater",
        "controller_slug": owner + "-enrollment-controller",
        "app": updater,
        "controller": controller,
        "variable": {"value": "Iv1.updater"},
    }
    monkeypatch.setattr(owner_setup, "discover", lambda *_: state)
    monkeypatch.setattr(owner_setup, "app_key", lambda *_: "unused-test-key")
    monkeypatch.setattr(owner_setup, "ensure_installation", lambda *_: None)
    monkeypatch.setattr(owner_setup, "ensure_variable", lambda *_: None)
    observed: list[tuple[str, bool]] = []

    class StopAfterProtectionError(Exception):
        pass

    def protect(*args: Any, **kwargs: Any) -> None:
        observed.append((args[4], kwargs["allow_exposed"]))
        if args[4] == "update-enrollment":
            raise StopAfterProtectionError

    bridge = SimpleNamespace(
        GitHub=lambda _: object(), verify_app_key=lambda *_: None, protected=protect
    )
    monkeypatch.setattr(owner_setup, "load_enrollment", lambda: bridge)
    gh = mock.Mock()
    gh.api.return_value = {"default_branch": "main"}
    responses = iter(
        ["credentials belong to tj-agents-pin-updater", "revoked tj-agents-pin-updater"]
    )
    with pytest.raises(StopAfterProtectionError):
        owner_setup.setup(
            owner, gh, open_url=lambda _: None, prompt=lambda _: next(responses)
        )
    assert observed == [("update-pins", True), ("update-enrollment", False)]
    gh.set_secret.assert_not_called()


@pytest.mark.parametrize(
    "status", [403, "403"], ids=["integer-status", "string-status"]
)
def test_unavailable_organization_rulesets_preserve_repository_policy_setup(
    status: int | str, capsys: pytest.CaptureFixture[str]
) -> None:
    response = {
        "status": status,
        "message": "Upgrade to GitHub Team to enable this feature.",
    }
    run = mock.Mock(
        return_value=subprocess.CompletedProcess(
            [], 1, json.dumps(response), "HTTP 403"
        )
    )
    assert owner_setup.GitHub(run).organization_rulesets("tj-agents") == []
    assert "repository policies remain enforced" in capsys.readouterr().out
    assert run.call_count == 1
    assert run.call_args.args[0] == [
        "gh",
        "api",
        "--hostname",
        "github.com",
        "orgs/tj-agents/rulesets?per_page=100&page=1",
        "--method",
        "GET",
    ]


@pytest.mark.parametrize(
    "response",
    [
        {"status": "403", "message": "Resource not accessible by integration"},
        {"status": "401", "message": "Upgrade to GitHub Team to enable this feature."},
        {"status": "403", "message": "Forbidden"},
    ],
)
def test_organization_ruleset_permission_errors_still_abort(
    response: dict[str, str],
) -> None:
    run = mock.Mock(
        return_value=subprocess.CompletedProcess(
            [], 1, json.dumps(response), "HTTP error"
        )
    )
    with pytest.raises(owner_setup.SetupError, match="orgs/tj-agents/rulesets"):
        owner_setup.GitHub(run).organization_rulesets("tj-agents")


def test_organization_rulesets_are_paginated_without_dropping_rules() -> None:
    first = [{"id": value} for value in range(100)]
    final = [{"id": 100}]
    run = mock.Mock(
        side_effect=[
            subprocess.CompletedProcess([], 0, json.dumps(first), ""),
            subprocess.CompletedProcess([], 0, json.dumps(final), ""),
        ]
    )
    assert owner_setup.GitHub(run).organization_rulesets("tj-agents") == first + final
    assert "orgs/tj-agents/rulesets?per_page=100&page=2" in run.call_args.args[0]


def test_late_plan_error_never_discards_partially_discovered_organization_rules() -> (
    None
):
    run = mock.Mock(
        side_effect=[
            subprocess.CompletedProcess(
                [], 0, json.dumps([{"id": value} for value in range(100)]), ""
            ),
            subprocess.CompletedProcess(
                [],
                1,
                json.dumps(
                    {
                        "status": "403",
                        "message": "Upgrade to GitHub Team to enable this feature.",
                    }
                ),
                "HTTP 403",
            ),
        ]
    )
    with pytest.raises(owner_setup.SetupError, match="page=2"):
        owner_setup.GitHub(run).organization_rulesets("tj-agents")


@pytest.mark.parametrize("body", ['{"rules": []}', "null", "[1]", "invalid JSON"])
def test_malformed_organization_ruleset_response_is_rejected(body: str) -> None:
    run = mock.Mock(return_value=subprocess.CompletedProcess([], 0, body, ""))
    with pytest.raises(
        owner_setup.SetupError, match="invalid organization ruleset response"
    ):
        owner_setup.GitHub(run).organization_rulesets("tj-agents")


def test_empty_organization_rulesets_do_not_skip_repository_protections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = "tj-agents"
    updater = {
        "id": 42,
        "client_id": "Iv1.updater",
        "owner": {"login": owner},
        "permissions": owner_setup.PERMISSIONS,
    }
    controller = {
        "id": 90,
        "client_id": "Iv1.controller",
        "owner": {"login": owner},
        "permissions": owner_setup.CONTROLLER_PERMISSIONS,
    }
    state: dict[str, Any] = {
        "legacy_org_secret": None,
        "legacy_repositories": [],
        "rulesets": [],
        "slug": owner + "-pin-updater",
        "controller_slug": owner + "-enrollment-controller",
        "app": updater,
        "controller": controller,
        "variable": None,
    }
    monkeypatch.setattr(owner_setup, "discover", lambda *_: state)
    monkeypatch.setattr(owner_setup, "app_key", lambda *_: "fixture-key")
    for name in (
        "ensure_installation",
        "ensure_variable",
        "set_repo_variable",
        "put_env_secret",
    ):
        monkeypatch.setattr(owner_setup, name, mock.Mock())
    bridge = SimpleNamespace(
        GitHub=mock.Mock(return_value=object()),
        verify_app_key=mock.Mock(),
        protected=mock.Mock(),
        enroll=mock.Mock(return_value=[{"repository": "tj-agents/example"}]),
        reconcile_policy=mock.Mock(return_value={"action": "updated"}),
    )
    monkeypatch.setattr(owner_setup, "load_enrollment", lambda: bridge)
    gh = mock.Mock()
    gh.api.return_value = {"default_branch": "main"}
    owner_setup.setup(owner, gh)
    assert bridge.verify_app_key.call_count == 2
    assert bridge.protected.call_count == 2
    assert bridge.enroll.call_args.kwargs["grant_bypass"] is False
    bridge.reconcile_policy.assert_called_once_with(mock.ANY, "tj-agents/example", 42)


@pytest.fixture
def configured_setup(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    updater = {
        "id": 42,
        "client_id": "Iv1.updater",
        "slug": "tj-agents-pin-updater",
        "owner": {"login": "tj-agents"},
        "permissions": owner_setup.PERMISSIONS,
    }
    controller = {
        "id": 90,
        "client_id": "Iv1.controller",
        "slug": "tj-agents-enrollment-controller",
        "owner": {"login": "tj-agents"},
        "permissions": owner_setup.CONTROLLER_PERMISSIONS,
    }
    state = {
        "app": updater,
        "controller": controller,
        "slug": updater["slug"],
        "controller_slug": controller["slug"],
        "legacy_org_secret": None,
        "legacy_repositories": [],
        "rulesets": [],
        "variable": {"value": "Iv1.updater", "visibility": "all"},
    }
    central = "repos/tj-agents/github-actions"
    env = central + "/environments/update-enrollment"
    completed = {
        "id": 123,
        "head_sha": "a" * 40,
        "head_branch": "main",
        "event": "workflow_dispatch",
        "path": ".github/workflows/enroll-publishers.yml",
        "repository": {"full_name": "tj-agents/github-actions"},
        "status": "completed",
        "conclusion": "success",
    }
    responses: dict[str, Any] = {
        central: {"default_branch": "main"},
        central + "/commits/main": {"sha": "a" * 40},
        central + "/actions/variables/ENROLLMENT_APP_CLIENT_ID": {
            "value": "Iv1.controller"
        },
        central + "/actions/variables/ENROLLMENT_APP_ID": {"value": "90"},
        central + "/actions/variables/UPDATE_APP_ID": {"value": "42"},
        env: {
            "deployment_branch_policy": {
                "protected_branches": False,
                "custom_branch_policies": True,
            }
        },
        env + "/variables/TJ_AGENTS_ENROLLMENT_BRANCH": {"value": "main"},
        env + "/deployment-branch-policies": {
            "branch_policies": [{"id": 1, "name": "main", "type": "branch"}]
        },
        env + "/secrets": {
            "secrets": [
                {"name": owner_setup.SECRET},
                {"name": "ENROLLMENT_APP_PRIVATE_KEY"},
            ]
        },
        "orgs/tj-agents": {"id": 1},
        "orgs/tj-agents/actions/variables/UPDATE_APP_CLIENT_ID": state["variable"],
        "orgs/tj-agents/installations": {
            "installations": [
                {
                    "id": app["id"],
                    "app_id": app["id"],
                    "app_slug": app["slug"],
                    "permissions": app["permissions"],
                    "repository_selection": "all",
                }
                for app in (updater, controller)
            ]
        },
        central + "/actions/workflows/enroll-publishers.yml/dispatches": {
            "workflow_run_id": 123
        },
    }
    calls: list[tuple[str, str, Any]] = []
    runs = [completed]

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert command[1] == "api", "configured recovery must not request a local key"
        path = command[4].split("?", 1)[0]
        method = (
            command[command.index("--method") + 1] if "--method" in command else "GET"
        )
        data = json.loads(kwargs["input"]) if kwargs.get("input") else None
        calls.append((method, path, data))
        if path == central + "/actions/runs/123":
            value = runs.pop(0) if len(runs) > 1 else runs[0]
        else:
            assert path in responses, path
            value = responses[path]
        return subprocess.CompletedProcess(command, 0, json.dumps(value), "")

    monkeypatch.setattr(owner_setup, "discover", lambda *_: state)
    return SimpleNamespace(
        gh=owner_setup.GitHub(run),
        state=state,
        responses=responses,
        calls=calls,
        runs=runs,
        completed=completed,
        central=central,
        env=env,
    )


def test_configured_rerun_uses_protected_keys_without_owner_prompts(
    configured_setup: SimpleNamespace,
    tmp_path: Path,
) -> None:
    fixture = configured_setup
    fixture.runs.insert(
        0, {**fixture.completed, "status": "in_progress", "conclusion": None}
    )
    result_file = tmp_path / "result.json"
    reporter = owner_setup.SetupReporter("tj-agents", result_file)
    browser, prompt = mock.Mock(), mock.Mock()
    receipts = []

    def observe(_: float) -> None:
        receipts.append(json.loads(result_file.read_text(encoding="utf-8")))

    owner_setup.setup(
        "tj-agents",
        fixture.gh,
        open_url=browser,
        prompt=prompt,
        sleep=observe,
        progress=reporter.progress,
        request_action=reporter.awaiting,
    )
    browser.assert_not_called()
    prompt.assert_not_called()
    assert receipts[0]["action"]["kind"] == "waiting_for_enrollment"
    assert (
        receipts[0]["action"]["url"]
        == "https://github.com/tj-agents/github-actions/actions/runs/123"
    )
    writes = [call for call in fixture.calls if call[0] != "GET"]
    assert writes == [
        (
            "POST",
            fixture.central + "/actions/workflows/enroll-publishers.yml/dispatches",
            {"ref": "main", "return_run_details": True},
        )
    ]


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out", "skipped"])
def test_failed_recovery_preserves_keys_and_exact_run_diagnostics(
    conclusion: str,
    configured_setup: SimpleNamespace,
    tmp_path: Path,
) -> None:
    fixture = configured_setup
    fixture.runs[:] = [{**fixture.completed, "conclusion": conclusion}]
    path = tmp_path / "result.json"
    browser, prompt = mock.Mock(), mock.Mock()
    with mock.patch.object(owner_setup, "GitHub", return_value=fixture.gh):
        assert (
            owner_setup.main(
                ["--owner", "tj-agents", "--apply", "--result-file", str(path)],
                environment={},
            )
            == 1
        )
    result = json.loads(path.read_text(encoding="utf-8"))
    assert result["state"] == "failed"
    assert result["action"]["url"].endswith("/runs/123")
    assert conclusion in result["error"]
    assert "no new key was requested" in result["error"]
    assert all(
        call[0] == "GET" or call[1].endswith("/dispatches") for call in fixture.calls
    )
    browser.assert_not_called()
    prompt.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", 124),
        ("head_sha", "b" * 40),
        ("head_branch", "other"),
        ("event", "push"),
        ("path", ".github/workflows/other.yml"),
        ("repository", {"full_name": "other/github-actions"}),
    ],
)
def test_recovery_rejects_another_run_even_when_successful(
    field: str,
    value: Any,
    configured_setup: SimpleNamespace,
) -> None:
    fixture = configured_setup
    fixture.runs[:] = [{**fixture.completed, field: value}]
    browser, prompt = mock.Mock(), mock.Mock()
    with pytest.raises(owner_setup.SetupError, match="identity does not match"):
        owner_setup.setup("tj-agents", fixture.gh, open_url=browser, prompt=prompt)
    browser.assert_not_called()
    prompt.assert_not_called()


def test_pending_recovery_times_out_without_requesting_fresh_keys(
    configured_setup: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = configured_setup
    fixture.runs[:] = [{**fixture.completed, "status": "waiting", "conclusion": None}]
    monkeypatch.setattr(owner_setup, "ENROLLMENT_WAIT_SECONDS", 1)
    elapsed = [0.0]

    def advance(seconds: float) -> None:
        elapsed[0] += seconds

    browser, prompt = mock.Mock(), mock.Mock()
    with pytest.raises(owner_setup.SetupError, match=r"still pending.*runs/123"):
        owner_setup.setup(
            "tj-agents",
            fixture.gh,
            open_url=browser,
            prompt=prompt,
            sleep=advance,
            clock=lambda: elapsed[0],
        )
    browser.assert_not_called()
    prompt.assert_not_called()


def test_recovery_refuses_drifted_central_identity_before_dispatch(
    configured_setup: SimpleNamespace,
) -> None:
    fixture = configured_setup
    fixture.responses[fixture.central + "/actions/variables/UPDATE_APP_ID"] = {
        "value": "999"
    }
    with pytest.raises(owner_setup.SetupError, match="does not match its verified App"):
        owner_setup.setup("tj-agents", fixture.gh)
    assert all(call[0] == "GET" for call in fixture.calls)


def test_recovery_refuses_broad_environment_before_dispatch(
    configured_setup: SimpleNamespace,
) -> None:
    fixture = configured_setup
    fixture.responses[fixture.env]["deployment_branch_policy"] = {
        "protected_branches": True,
        "custom_branch_policies": False,
    }
    with pytest.raises(
        owner_setup.load_enrollment().EnrollmentError, match="custom exact branches"
    ):
        owner_setup.setup("tj-agents", fixture.gh)
    assert all(call[0] == "GET" for call in fixture.calls)


def test_initial_setup_with_missing_protected_key_does_not_dispatch(
    configured_setup: SimpleNamespace,
) -> None:
    fixture = configured_setup
    fixture.responses[fixture.env + "/secrets"] = {
        "secrets": [{"name": owner_setup.SECRET}]
    }
    assert not owner_setup.resume_enrollment(
        "tj-agents",
        fixture.gh,
        fixture.state,
        mock.Mock(),
        mock.Mock(),
        mock.Mock(),
        mock.Mock(),
        mock.Mock(),
    )
    assert all(call[0] == "GET" for call in fixture.calls)
