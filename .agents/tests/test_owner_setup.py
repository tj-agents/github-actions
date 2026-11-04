import base64
import importlib.util
import io
import json
import subprocess
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


def test_legacy_exposure_requires_owner_key_revocation_before_migration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        owner_setup,
        "discover",
        lambda *_: {
            "legacy_org_secret": {"name": owner_setup.SECRET},
            "slug": "tj-agents-pin-updater",
        },
    )
    gh = mock.Mock()
    with pytest.raises(owner_setup.SetupError, match="key-rotation confirmation"):
        owner_setup.setup(
            "tj-agents", gh, open_url=lambda _: None, prompt=lambda _: "not confirmed"
        )
    gh.api.assert_not_called()
    gh.set_secret.assert_not_called()


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
        "variable": None,
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
    with pytest.raises(StopAfterProtectionError):
        owner_setup.setup(
            owner, gh, open_url=lambda _: None, prompt=lambda _: owner + "-pin-updater"
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
