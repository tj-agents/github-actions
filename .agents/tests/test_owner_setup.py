import base64
import importlib.util
import io
import json
import subprocess
from pathlib import Path
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
    state = {
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
