import base64
import importlib.util
import io
import json
import subprocess
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".agents/github-actions/utility/publish-update/scripts/enrollment.py"
SPEC = importlib.util.spec_from_file_location("enrollment", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
enrollment = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(enrollment)

OWNER = "tj-agents"
APP_KEY = "-----BEGIN RSA PRIVATE KEY-----\nZm9v\n-----END RSA PRIVATE KEY-----\n"
SHA = "a" * 40
WORKFLOW = ROOT / ".github/workflows/enroll-publishers.yml"


def repo_state(
    repository: str, branch: str = "main", selected: bool = True
) -> dict[str, object]:
    config = {
        "schema_version": 1,
        "repository": repository if selected else "elsewhere/template",
    }
    return {
        f"repos/{repository}": {
            "full_name": repository,
            "owner": {"login": OWNER},
            "default_branch": branch,
            "fork": False,
            "archived": False,
        },
        f"repos/{repository}/commits/{branch}": {"sha": SHA},
        f"repos/{repository}/contents/.agents/plugins/template.json?ref={SHA}": {
            "content": base64.encodebytes(json.dumps(config).encode()).decode()
        },
    }


class FakeGitHub:
    def __init__(self, state: dict[str, Any]):
        self.state = state
        self.calls: list[tuple[str, str, object]] = []
        self.env_secrets: dict[str, list[dict[str, str]]] = {}
        self.repo_secrets: dict[str, set[str]] = {}

    def optional(self, path: str) -> object | None:
        if path.endswith("/environments/update-pins"):
            return self.state.get(path)
        return self.state.get(path)

    def api(
        self, path: str, method: str = "GET", body: dict[str, Any] | None = None
    ) -> Any:
        self.calls.append((method, path, body))
        base_path = path.split("?", 1)[0]
        if method == "GET":
            if base_path.endswith("/deployment-branch-policies"):
                environment = self.state.get(base_path.rsplit("/", 1)[0], {})
                if environment.get("deployment_branch_policy") is None:
                    raise enrollment.EnrollmentError("gh: Not Found (HTTP 404)")
                policies = self.state.get(base_path, [])
                if isinstance(policies, dict):
                    policies = policies.get("branch_policies", [])
                return {"branch_policies": policies}
            if base_path.endswith("/environments/update-pins/secrets"):
                repo = "/".join(base_path.split("/")[1:3])
                return {"secrets": self.env_secrets.get(repo, [])}
            if base_path.endswith("/actions/secrets"):
                repo = "/".join(base_path.split("/")[1:3])
                return {
                    "secrets": [
                        {"name": name} for name in self.repo_secrets.get(repo, set())
                    ]
                }
            return self.state.get(path, self.state.get(base_path, {}))
        if method == "PUT" and "/environments/" in base_path:
            current = self.state.setdefault(base_path, {})
            assert isinstance(current, dict)
            assert body is not None
            current.update(body)
            return current
        if method == "POST" and path.endswith("/deployment-branch-policies"):
            policies = self.state.setdefault(base_path, [])
            assert isinstance(policies, list)
            assert body is not None
            item = {"id": len(policies) + 1, **body}
            policies.append(item)
            return item
        if method in {"POST", "PATCH"} and (
            base_path.endswith("/variables") or "/variables/" in base_path
        ):
            variables = self.state.setdefault(base_path, {})
            assert isinstance(variables, dict)
            value = body
            assert isinstance(value, dict)
            if method == "PATCH":
                root = base_path.rsplit("/", 1)[0]
                self.state[f"{root}/{value['name']}"] = value
                return value
            variables[value["name"]] = value
            self.state[f"{base_path}/{value['name']}"] = value
            return variables
        if method == "GET" and path in self.state:
            return self.state[path]
        if method == "DELETE":
            if base_path.endswith(f"/actions/secrets/{enrollment.SECRET}"):
                repo = "/".join(base_path.split("/")[1:3])
                self.repo_secrets.get(repo, set()).discard(enrollment.SECRET)
            return None
        raise AssertionError(f"unexpected request {method} {path}")

    def call(
        self, arguments: list[str], payload: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        assert arguments[:4] == ["gh", "api", "--hostname", "github.com"]
        assert "UPDATE_APP_PRIVATE_KEY" not in arguments
        return subprocess.CompletedProcess(arguments, 0, "", "")

    def secret(
        self, repository: str, value: str, environment: str, secret: str
    ) -> None:
        self.calls.append(("SECRET", f"{repository}/{environment}/{secret}", value))
        assert environment == "update-pins"
        assert secret == "UPDATE_APP_PRIVATE_KEY"
        self.env_secrets.setdefault(repository, []).append({"name": secret})


def gh_api(
    fake: FakeGitHub,
    path: str,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> object:
    return fake.api(path, method, body)


class FakeClient:
    def __init__(self, fake: FakeGitHub, custom: bool = False):
        self.fake = fake
        self.custom = custom

    def api(
        self, path: str, method: str = "GET", body: dict[str, Any] | None = None
    ) -> Any:
        if path.startswith("orgs/tj-agents/repos"):
            return [
                {"full_name": "tj-agents/plugin", "owner": {"login": OWNER}},
                {"full_name": "tj-agents/other", "owner": {"login": OWNER}},
                {
                    "full_name": "tj-agents/fork",
                    "owner": {"login": OWNER},
                    "fork": True,
                },
                {"full_name": "someone/plugin", "owner": {"login": "someone"}},
            ]
        if path == "repos/tj-agents/plugin":
            return {
                "full_name": "tj-agents/plugin",
                "owner": {"login": OWNER},
                "default_branch": "main",
                "fork": False,
                "archived": False,
            }
        if path == "repos/tj-agents/other":
            return {
                "full_name": "tj-agents/other",
                "owner": {"login": OWNER},
                "default_branch": "trunk",
                "fork": False,
                "archived": False,
            }
        if path == "repos/tj-agents/plugin/commits/main":
            return {"sha": SHA}
        if path == "repos/tj-agents/other/commits/trunk":
            return {"sha": SHA}
        if path == f"repos/tj-agents/plugin/contents/{enrollment.SOURCE}?ref={SHA}":
            return {
                "content": base64.encodebytes(
                    b'{"schema_version":1,"repository":"tj-agents/plugin"}'
                ).decode()
            }
        if path == f"repos/tj-agents/other/contents/{enrollment.SOURCE}?ref={SHA}":
            return {
                "content": base64.encodebytes(
                    b'{"schema_version":1,"repository":"elsewhere/template"}'
                ).decode()
            }
        return self.fake.api(path, method, body)

    def optional(self, path: str) -> object | None:
        if path.endswith("/environments/update-pins"):
            return self.fake.state.get(path)
        if path.endswith("/contents/.agents/plugins/template.json?ref=" + SHA):
            repository = path.split("/contents/", 1)[0].removeprefix("repos/")
            selected = repository == "tj-agents/plugin"
            config = {
                "schema_version": 1,
                "repository": repository if selected else "elsewhere/template",
            }
            return {"content": base64.encodebytes(json.dumps(config).encode()).decode()}
        if (
            path.endswith(f"/contents/{enrollment.DECLARATION}?ref={SHA}")
            and self.custom
        ):
            repository = path.split("/contents/", 1)[0].removeprefix("repos/")
            config = {"schema_version": 1, "repository": repository}
            return {"content": base64.encodebytes(json.dumps(config).encode()).decode()}
        return self.fake.optional(path)

    def secret(
        self,
        repository: str,
        value: str,
        environment: str = "update-pins",
        secret: str = "UPDATE_APP_PRIVATE_KEY",
    ) -> None:
        self.fake.secret(repository, value, environment, secret)


def test_enrolls_only_owned_nonfork_eligible_repositories_with_env_key() -> None:
    fake = FakeGitHub({})
    result = enrollment.enroll(
        FakeClient(fake), OWNER, 42, APP_KEY, apply=True, remove_legacy_secret=True
    )
    assert [item["repository"] for item in result] == ["tj-agents/plugin"]
    assert fake.env_secrets == {
        "tj-agents/plugin": [{"name": "UPDATE_APP_PRIVATE_KEY"}]
    }
    secret_index = next(i for i, call in enumerate(fake.calls) if call[0] == "SECRET")
    branch_write_index = next(
        i
        for i, call in enumerate(fake.calls)
        if call[0] == "POST" and call[1].endswith("/deployment-branch-policies")
    )
    assert branch_write_index < secret_index
    assert fake.calls[branch_write_index][2] == {"name": "main", "type": "branch"}


def test_enrolls_mixed_template_and_custom_declarations() -> None:
    fake = FakeGitHub({})
    result = enrollment.enroll(FakeClient(fake, custom=True), OWNER, 42, APP_KEY)
    assert [item["repository"] for item in result] == [
        "tj-agents/plugin",
        "tj-agents/other",
    ]


def test_preview_does_not_require_a_key_or_write() -> None:
    fake = FakeGitHub({})
    result = enrollment.enroll(FakeClient(fake), OWNER, 42, "", apply=False)
    assert [item["repository"] for item in result] == ["tj-agents/plugin"]
    assert all(method == "GET" for method, _, _ in fake.calls)


def test_future_enrollment_reconciles_the_declared_policy_after_secret_readback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeGitHub({})
    reconciled = []

    def reconcile(gh: Any, repository: str, app_id: int) -> str:
        assert fake.env_secrets[repository] == [{"name": enrollment.SECRET}]
        assert app_id == 42
        reconciled.append(repository)
        return "created"

    monkeypatch.setattr(enrollment, "reconcile_policy", reconcile)
    result = enrollment.enroll(FakeClient(fake), OWNER, 42, APP_KEY, apply=True)
    assert reconciled == ["tj-agents/plugin"]
    assert result[0]["merge_policy"] == "created"


def test_enrollment_renders_and_reads_back_the_updater_bypass() -> None:
    repository = "tj-agents/plugin"
    policy = {"requires_approval": True, "required_checks": ["verify / hosts"]}
    state = repo_state(repository)
    state[f"repos/{repository}/contents/.github/merge-policy.json?ref={SHA}"] = {
        "content": base64.encodebytes(json.dumps(policy).encode()).decode()
    }

    class PolicyGitHub(FakeGitHub):
        def api(
            self, path: str, method: str = "GET", body: dict[str, Any] | None = None
        ) -> Any:
            if path == f"repos/{repository}/rulesets?per_page=100&page=1":
                return []
            if path == f"repos/{repository}/rulesets" and method == "POST":
                assert body is not None
                self.state[path + "/17"] = {"id": 17, **body}
                return self.state[path + "/17"]
            return super().api(path, method, body)

    fake = PolicyGitHub(state)
    assert enrollment.reconcile_policy(fake, repository, 42) == "created"
    actual = fake.state[f"repos/{repository}/rulesets/17"]
    assert {
        "actor_id": 42,
        "actor_type": "Integration",
        "bypass_mode": "always",
    } in actual["bypass_actors"]
    review = next(rule for rule in actual["rules"] if rule["type"] == "pull_request")
    assert review["parameters"]["required_approving_review_count"] == 1


def test_eligibility_checks_declarations_against_one_verified_default_sha() -> None:
    requests: list[str] = []

    class Content:
        def __init__(self, marker: dict[str, Any] | None, declaration: object | None):
            self.marker = marker
            self.declaration = declaration

        def api(
            self, path: str, method: str = "GET", body: dict[str, Any] | None = None
        ) -> dict[str, Any]:
            if path == f"repos/{target}":
                return {
                    "full_name": target,
                    "owner": {"login": OWNER},
                    "default_branch": "main",
                    "fork": False,
                    "archived": False,
                }
            assert path == f"repos/{target}/commits/main"
            return {"sha": SHA}

        def optional(self, path: str) -> dict[str, str] | None:
            requests.append(path)
            value = (
                self.marker
                if path == f"repos/{target}/contents/{enrollment.SOURCE}?ref={SHA}"
                else self.declaration
            )
            if value is None:
                return None
            return {"content": base64.encodebytes(json.dumps(value).encode()).decode()}

    target = "tj-agents/plugin"
    assert enrollment.eligible_repository(
        Content({"schema_version": 1, "repository": target}, None),
        OWNER,
        target,
        "main",
    )
    assert enrollment.eligible_repository(
        Content(
            {"schema_version": 1, "repository": "elsewhere/template"},
            {"schema_version": 1, "repository": target},
        ),
        OWNER,
        target,
        "main",
    )
    assert not enrollment.eligible_repository(
        Content(None, {"schema_version": 2, "repository": target}),
        OWNER,
        target,
        "main",
    )
    assert all(path.endswith(f"?ref={SHA}") for path in requests)


def test_matrix_output_contains_only_sorted_basename_json(tmp_path: Path) -> None:
    output = tmp_path / "github-output"
    enrollment.write_matrix_output(
        output,
        OWNER,
        [
            {"repository": "tj-agents/zeta"},
            {"repository": "tj-agents/alpha"},
            {"repository": "tj-agents/zeta"},
        ],
    )
    assert output.read_text(encoding="utf-8") == 'repositories=["alpha","zeta"]\n'
    with pytest.raises(enrollment.EnrollmentError, match="identity"):
        enrollment.write_matrix_output(
            output, OWNER, [{"repository": "someone/foreign"}]
        )


def test_central_workflow_separates_credentials_and_checks_exact_default_branch() -> (
    None
):
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "environment: update-enrollment" in source
    assert "cancel-in-progress: false" in source
    assert source.count("github.event.repository.default_branch") == 2
    assert "permission-administration: write" in source
    assert "permission-environments: write" in source
    assert "permission-secrets: read" in source
    assert "permission-workflows: write" in source
    assert "secrets.ENROLLMENT_APP_PRIVATE_KEY" in source
    assert "secrets.UPDATE_APP_PRIVATE_KEY" in source
    assert "path: automation" in source and "path: consumer" in source
    assert "repositories: ${{ matrix.name }}" in source
    assert '--matrix-output "$GITHUB_OUTPUT"' in source
    assert "persist-credentials: false" in source
    assert "uses: ./automation/.github/actions/update-pins" in source


def test_existing_environment_deployment_protection_is_preserved() -> None:
    repo = "tj-agents/plugin"
    environment = f"repos/{repo}/environments/update-pins"
    policy_path = environment + "/deployment-branch-policies"
    protection = [
        {
            "type": "required_reviewers",
            "prevent_self_review": False,
            "reviewers": [{"type": "User", "reviewer": {"id": 8}}],
        }
    ]
    fake = FakeGitHub(
        {
            environment: {
                "deployment_branch_policy": {
                    "protected_branches": False,
                    "custom_branch_policies": True,
                },
                "protection_rules": protection,
            },
            policy_path: {
                "branch_policies": [{"id": 1, "name": "main", "type": "branch"}]
            },
            environment + "/variables/TJ_AGENTS_UPDATE_PINS_BRANCH": {"value": "main"},
        }
    )
    enrollment.protected(fake, repo, "main", apply=True)
    put = next(call for call in fake.calls if call[0] == "PUT")
    assert put[2] == {
        "deployment_branch_policy": {
            "protected_branches": False,
            "custom_branch_policies": True,
        },
        "reviewers": [{"type": "User", "id": 8}],
        "prevent_self_review": False,
    }


@pytest.mark.parametrize(
    "policies, marker",
    [
        ([{"id": 1, "name": "*"}], None),
        ([{"id": 1, "name": "release/*"}], None),
        ([{"id": 1, "name": "main"}, {"id": 2, "name": "dev"}], "main"),
    ],
)
def test_refuses_unowned_or_wildcard_deployment_branches(
    policies: list[dict[str, object]], marker: str | None
) -> None:
    repo = "tj-agents/plugin"
    environment = f"repos/{repo}/environments/update-pins"
    state: dict[str, object] = {
        environment: {
            "deployment_branch_policy": {
                "protected_branches": False,
                "custom_branch_policies": True,
            },
            "protection_rules": [],
        },
        environment + "/deployment-branch-policies": {"branch_policies": policies},
    }
    if marker:
        state[environment + "/variables/TJ_AGENTS_UPDATE_PINS_BRANCH"] = {
            "value": marker
        }
    fake = FakeGitHub(state)
    with pytest.raises(enrollment.EnrollmentError):
        enrollment.protected(fake, repo, "main", apply=True)
    assert not any(call[0] in {"PUT", "POST", "DELETE"} for call in fake.calls)


def test_controller_automation_requires_exact_central_default_branch_and_event() -> (
    None
):
    class Bound:
        def api(
            self, path: str, method: str = "GET", body: dict[str, Any] | None = None
        ) -> Any:
            assert path == "repos/tj-agents/github-actions"
            return {"default_branch": "main"}

    good = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": "tj-agents/github-actions",
        "EXPECTED_ENROLLMENT_OWNER": "tj-agents",
        "GITHUB_EVENT_NAME": "schedule",
        "GITHUB_REF": "refs/heads/main",
        "GH_TOKEN": "installation-token",
        "ENROLLMENT_APP_ID": "90",
        "ENROLLMENT_APP_CLIENT_ID": "Iv1.controller",
        "UPDATE_APP_CLIENT_ID": "Iv1.updater",
    }

    class AppBound:
        def api(self, path: str, method: str = "GET", body: object = None) -> object:
            if path == "repos/tj-agents/github-actions":
                return {"default_branch": "main"}
            assert path == "apps/tj-agents-enrollment-controller"
            return {
                "id": 90,
                "slug": "tj-agents-enrollment-controller",
                "owner": {"login": OWNER},
                "client_id": "Iv1.controller",
            }

    enrollment.automation_guard(
        AppBound(), OWNER, "github-actions", "Iv1.updater", 42, good
    )
    for name, value in (
        ("GITHUB_REF", "refs/heads/feature"),
        ("GITHUB_EVENT_NAME", "pull_request"),
        ("GITHUB_REPOSITORY", "someone/other"),
    ):
        broken = {**good, name: value}
        with pytest.raises(enrollment.EnrollmentError):
            enrollment.automation_guard(
                AppBound(), OWNER, "github-actions", "Iv1.updater", 42, broken
            )


def test_secret_api_request_is_fixed_to_github_and_named_environment() -> None:
    fake = FakeGitHub({})
    client = FakeClient(fake)
    client.secret("tj-agents/plugin", APP_KEY)
    assert fake.calls[-1] == (
        "SECRET",
        "tj-agents/plugin/update-pins/UPDATE_APP_PRIVATE_KEY",
        APP_KEY,
    )


def test_github_cli_uses_subcommand_host_flag_and_repo_host_url() -> None:
    commands: list[list[str]] = []

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "{}", "")

    client = enrollment.GitHub(run)
    client.api("repos/tj-agents/plugin")
    client.secret("tj-agents/plugin", APP_KEY)
    assert commands[0][:4] == ["gh", "api", "--hostname", "github.com"]
    assert commands[1][:2] == ["gh", "secret"]
    assert "--hostname" not in commands[1]
    assert commands[1][commands[1].index("--repo") + 1] == (
        "github.com/tj-agents/plugin"
    )


def test_automation_refuses_a_repository_level_key_without_deleting_it() -> None:
    fake = FakeGitHub({})
    fake.repo_secrets["tj-agents/plugin"] = {enrollment.SECRET}
    with pytest.raises(enrollment.EnrollmentError, match="owner cleanup required"):
        enrollment.enroll(FakeClient(fake), OWNER, 42, APP_KEY, apply=True)
    assert enrollment.SECRET in fake.repo_secrets["tj-agents/plugin"]
    assert fake.env_secrets["tj-agents/plugin"] == [{"name": enrollment.SECRET}]


def test_owner_cleanup_deletes_repo_level_key_only_after_env_readback() -> None:
    fake = FakeGitHub({})
    fake.repo_secrets["tj-agents/plugin"] = {enrollment.SECRET}
    enrollment.enroll(
        FakeClient(fake),
        OWNER,
        42,
        APP_KEY,
        apply=True,
        remove_legacy_secret=True,
    )
    secret_write = next(i for i, call in enumerate(fake.calls) if call[0] == "SECRET")
    delete = next(
        i
        for i, call in enumerate(fake.calls)
        if call[0] == "DELETE"
        and call[1].endswith(f"/actions/secrets/{enrollment.SECRET}")
    )
    assert secret_write < delete
    assert enrollment.SECRET not in fake.repo_secrets["tj-agents/plugin"]


def test_paginated_inventory_reads_every_repository() -> None:
    class Pages:
        def __init__(self) -> None:
            self.paths: list[str] = []

        def api(self, path: str, method: str = "GET", body: object = None) -> object:
            self.paths.append(path)
            if path.endswith("page=1"):
                return [{"full_name": f"tj-agents/repo-{i}"} for i in range(100)]
            return [{"full_name": "tj-agents/last"}]

    fake = Pages()
    repositories = list(enrollment.pages(fake, "orgs/tj-agents/repos?type=all"))
    assert len(repositories) == 101
    assert "type=all&per_page=100&page=1" in fake.paths[0]
    assert "type=all&per_page=100&page=2" in fake.paths[1]


def test_real_environment_branch_rule_is_accepted_on_repeat() -> None:
    fake = FakeGitHub({})
    target = "tj-agents/plugin"
    enrollment.protected(fake, target, "main", apply=True)
    environment_path = f"repos/{target}/environments/update-pins"
    fake.state[environment_path]["protection_rules"] = [{"type": "branch_policy"}]
    enrollment.protected(fake, target, "main", apply=True)
    assert fake.state[environment_path]["deployment_branch_policy"] == {
        "protected_branches": False,
        "custom_branch_policies": True,
    }


@pytest.mark.parametrize("apply", [False, True])
def test_auto_created_empty_environment_is_safely_tightened(apply: bool) -> None:
    target = "tj-agents/plugin"
    path = f"repos/{target}/environments/update-pins"
    fake = FakeGitHub(
        {path: {"deployment_branch_policy": None, "protection_rules": []}}
    )
    result = enrollment.protected(fake, target, "main", apply=apply)
    assert result["action"] == ("enrolled" if apply else "enroll")
    if apply:
        assert fake.state[path]["deployment_branch_policy"] == {
            "protected_branches": False,
            "custom_branch_policies": True,
        }
        assert fake.state[path + "/deployment-branch-policies"] == [
            {"id": 1, "name": "main", "type": "branch"}
        ]
    else:
        assert fake.state[path]["deployment_branch_policy"] is None
        assert all(method == "GET" for method, _, _ in fake.calls)
    assert not fake.env_secrets


def test_owner_marker_does_not_authorize_a_tag_rule() -> None:
    target = "tj-agents/plugin"
    path = f"repos/{target}/environments/update-pins"
    fake = FakeGitHub(
        {
            path: {
                "deployment_branch_policy": {
                    "protected_branches": False,
                    "custom_branch_policies": True,
                }
            },
            path + "/deployment-branch-policies": [
                {"id": 1, "name": "main", "type": "tag"}
            ],
            path + "/variables/TJ_AGENTS_UPDATE_PINS_BRANCH": {"value": "main"},
        }
    )
    with pytest.raises(enrollment.EnrollmentError, match="exact branch policies"):
        enrollment.protected(fake, target, "main", apply=True)
    assert all(method == "GET" for method, _, _ in fake.calls)


def test_key_is_cryptographically_bound_to_the_intended_app() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    seen: list[Request] = []

    def opener(request: Request, *, timeout: int) -> io.BytesIO:
        seen.append(request)
        assert request.full_url == "https://api.github.com/app"
        assert timeout == enrollment.TIMEOUT
        token = request.headers["Authorization"].removeprefix("Bearer ")
        header, payload, signature = token.split(".")
        private_key.public_key().verify(
            base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4)),
            (header + "." + payload).encode(),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        claims = json.loads(
            base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        )
        assert claims == {"iat": 940, "exp": 1300, "iss": "Iv1.updater"}
        return io.BytesIO(
            json.dumps(
                {"id": 42, "client_id": "Iv1.updater", "owner": {"login": OWNER}}
            ).encode()
        )

    enrollment.verify_app_key(OWNER, 42, "Iv1.updater", pem, opener, lambda: 1000)
    assert len(seen) == 1
    wrong = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    wrong_pem = wrong.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()

    def rejecting(request: Request, *, timeout: int) -> io.BytesIO:
        try:
            return opener(request, timeout=timeout)
        except InvalidSignature as error:
            raise URLError("Bad credentials") from error

    with pytest.raises(enrollment.EnrollmentError, match="no key was distributed"):
        enrollment.verify_app_key(
            OWNER, 42, "Iv1.updater", wrong_pem, rejecting, lambda: 1000
        )
