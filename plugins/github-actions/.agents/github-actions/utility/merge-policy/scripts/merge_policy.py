#!/usr/bin/env python3
"""Render or check a repository's merge policy against GitHub (Python 3.12+, needs the gh CLI).

The policy is the `merge` section of the repository's `.agents/repository.json`; a repository without one
takes the `merge` section of the same file in its owner's `<owner>/.github` repository. `render` prints the
ruleset GitHub should enforce, `harness` writes the agent denials a human-only merge implies into the
repository's `.agents/repository-harness.json`, and `check` compares the rules GitHub enforces on the
default branch, and that overlay, with the policy, so CI can report drift. Ruleset writes are owned by
tj-agents/github's `github:configuration` Terraform workspace.
"""

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

RULESET_NAME = "merge-policy"
DEFAULT_CONFIGURATION = Path(".agents/repository.json")
CONFIGURATION_SECTIONS = frozenset({"access", "merge", "credentials"})
DEFAULT_HARNESS = Path(".agents/repository-harness.json")
OWNER_REPOSITORY = ".github"
GH_TIMEOUT_SECONDS = 60
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
ADMIN_ROLE_ID = 5
MERGE_COMMAND = ("gh", "pr", "merge")

type Run = Callable[..., subprocess.CompletedProcess[str]]
type Json = dict[str, Any]


class PolicyError(Exception):
    pass


class PolicyMissingError(PolicyError):
    pass


class Approval(Enum):
    """What a pull request needs, besides its required checks, before it can merge."""

    HUMAN = ("human", 1, False)
    AUTOMATED = ("automated", 0, True)
    NONE = ("none", 0, False)

    def __init__(self, key: str, approvals: int, review_check: bool) -> None:
        self.key = key
        self.approvals = approvals
        self.review_check = review_check


class Merge(Enum):
    """Who merges once the gates pass; a human-only merge denies agents every merge command."""

    AGENTS = ("agents", (), ())
    HUMAN = (
        "human",
        ("Bash(gh pr merge:*)", "PowerShell(gh pr merge:*)", "mcp__github__merge_pull_request"),
        (MERGE_COMMAND,),
    )

    def __init__(self, key: str, claude_deny: tuple[str, ...], codex_forbidden: tuple[tuple[str, ...], ...]) -> None:
        self.key = key
        self.claude_deny = claude_deny
        self.codex_forbidden = codex_forbidden


class DefaultBranchPush(Enum):
    """Who may push to the default branch outside a pull request; `ci` lets deploy keys bypass."""

    NONE = ("none", ())
    CI = ("ci", ("DeployKey",))

    def __init__(self, key: str, bypass_actor_types: tuple[str, ...]) -> None:
        self.key = key
        self.bypass_actor_types = bypass_actor_types


@dataclass(frozen=True, slots=True)
class Policy:
    approval: Approval
    merge: Merge
    default_branch_push: DefaultBranchPush
    required_checks: tuple[str, ...] = ()
    review_check: str | None = None

    def __post_init__(self) -> None:
        if self.approval.review_check and not self.review_check:
            raise PolicyError("approval automated needs review_check naming the automated review check")
        if not self.approval.review_check and self.review_check is not None:
            raise PolicyError("review_check applies only when approval is automated")


def choice[T: (Approval, Merge, DefaultBranchPush)](kind: type[T], value: object, field: str, where: object) -> T:
    for member in kind:
        if member.key == value:
            return member
    keys = ", ".join(member.key for member in kind)
    raise PolicyError(f"{where} must set {field} to one of: {keys}")


def validate_policy(policy: object, where: object) -> Policy:
    if not isinstance(policy, dict):
        raise PolicyError(f"{where} must contain a JSON object")
    unknown = set(policy) - {"approval", "merge", "default_branch_push", "required_checks", "review_check"}
    if unknown:
        raise PolicyError(f"{where} has unknown keys: {', '.join(sorted(unknown))}")
    checks = policy.get("required_checks", [])
    if not isinstance(checks, list) or not all(isinstance(check, str) and check.strip() for check in checks):
        raise PolicyError(f"{where}: required_checks must be a list of check names")
    review = policy.get("review_check")
    if review is not None and (not isinstance(review, str) or not review.strip()):
        raise PolicyError(f"{where}: review_check must name the automated review check")
    approval = choice(Approval, policy.get("approval"), "approval", where)
    merge = choice(Merge, policy.get("merge"), "merge", where)
    push = choice(DefaultBranchPush, policy.get("default_branch_push"), "default_branch_push", where)
    try:
        return Policy(approval, merge, push, tuple(checks), review)
    except PolicyError as error:
        raise PolicyError(f"{where}: {error}") from error


def merge_section(configuration: object, where: object) -> Policy | None:
    """Return the policy a repository configuration's `merge` section declares, or None without one.

    The configuration is a JSON object with `schema_version` 1 and only the `access`, `merge` and
    `credentials` sections; the other sections belong to other readers.
    """
    if not isinstance(configuration, dict):
        raise PolicyError(f"{where} must contain a JSON object")
    version = configuration.get("schema_version")
    if type(version) is not int or version != 1:
        raise PolicyError(f"{where} needs schema_version 1")
    unknown = set(configuration) - CONFIGURATION_SECTIONS - {"schema_version"}
    if unknown:
        raise PolicyError(f"{where} has unknown keys: {', '.join(sorted(unknown))}")
    if "merge" not in configuration:
        return None
    return validate_policy(configuration["merge"], f"{where} merge")


def repository_policy(path: Path) -> Policy | None:
    """Return the policy the configuration at `path` declares, or None without a file or merge section."""
    if not path.is_file():
        return None
    try:
        configuration = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise PolicyError(f"cannot read {path}: {error}") from error
    except ValueError as error:
        raise PolicyError(f"{path} is not valid JSON: {error}") from error
    return merge_section(configuration, path)


def effective_policy(path: Path, repository: str | None, run: Run = subprocess.run) -> Policy:
    """Return the repository's own merge section, or its owner's default when the repository has none."""
    policy = repository_policy(path)
    if policy is not None:
        return policy
    if repository is None:
        raise PolicyError(f"{path} has no merge section; pass --repo OWNER/NAME to use the owner's default")
    owner = repository.split("/", 1)[0]
    source = f"{owner}/{OWNER_REPOSITORY}:{DEFAULT_CONFIGURATION.as_posix()}"
    endpoint = f"repos/{owner}/{OWNER_REPOSITORY}/contents/{DEFAULT_CONFIGURATION.as_posix()}"
    try:
        configuration = gh(["-H", "Accept: application/vnd.github.raw+json", endpoint], run=run)
    except PolicyMissingError as error:
        raise PolicyError(f"no merge policy: {path} has none and {source} is absent or unreadable") from error
    policy = merge_section(configuration, source)
    if policy is None:
        raise PolicyError(f"no merge policy: neither {path} nor {source} has a merge section")
    return policy


def required_contexts(policy: Policy) -> list[str]:
    contexts = list(policy.required_checks)
    if policy.review_check:
        contexts.append(policy.review_check)
    return list(dict.fromkeys(contexts))


def bypass_actors(policy: Policy) -> list[Json]:
    actors: list[Json] = [{"actor_id": ADMIN_ROLE_ID, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"}]
    actors += [{"actor_type": kind, "bypass_mode": "always"} for kind in policy.default_branch_push.bypass_actor_types]
    return actors


def ruleset(policy: Policy) -> Json:
    rules: list[Json] = [
        {"type": "deletion"},
        {"type": "non_fast_forward"},
        {"type": "pull_request", "parameters": {
            "required_approving_review_count": policy.approval.approvals,
            "dismiss_stale_reviews_on_push": False,
            "require_code_owner_review": False,
            "require_last_push_approval": False,
            "required_review_thread_resolution": False,
        }},
    ]
    contexts = required_contexts(policy)
    if contexts:
        rules.append({"type": "required_status_checks", "parameters": {
            "strict_required_status_checks_policy": False,
            "required_status_checks": [{"context": context} for context in contexts],
        }})
    return {
        "name": RULESET_NAME,
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "bypass_actors": bypass_actors(policy),
        "rules": rules,
    }


def forbidden_rule(pattern: Sequence[str]) -> Json:
    return {
        "pattern": list(pattern),
        "justification": "This repository's merge policy reserves merging pull requests for the human.",
        "match": [[*pattern, "1"]],
        "not_match": [["gh", "pr", "view", "1"]],
    }


def harness(overlay: Json | None, merge: Merge, where: object = DEFAULT_HARNESS) -> Json | None:
    """Return the repository harness overlay carrying exactly `merge`'s agent denials, or None for no file.

    Every other overlay entry is the repository's own and is kept as it is.
    """
    if overlay is None:
        if not merge.claude_deny and not merge.codex_forbidden:
            return None
        overlay = {"schema_version": 1, "requires": {"marketplaces": [], "plugins": []}}
    updated: Json = json.loads(json.dumps(overlay))
    requires = updated.get("requires")
    if not isinstance(requires, dict):
        raise PolicyError(f"{where} must be a repository harness overlay with a requires object")
    if "permissions" not in requires:
        if not merge.claude_deny and not merge.codex_forbidden:
            return updated
        requires["permissions"] = {"claude_allow": [], "codex_prefix_rules": []}
    permissions = requires["permissions"]
    if not isinstance(permissions, dict):
        raise PolicyError(f"{where}: requires.permissions must be an object")
    owned_entries: set[str] = set()
    owned_patterns: list[list[str]] = []
    for member in Merge:
        owned_entries.update(member.claude_deny)
        owned_patterns += [list(pattern) for pattern in member.codex_forbidden]
    deny = [entry for entry in permissions.get("claude_deny", []) if entry not in owned_entries]
    forbidden = [rule for rule in permissions.get("codex_forbidden_prefix_rules", [])
                 if not isinstance(rule, dict) or rule.get("pattern") not in owned_patterns]
    deny += merge.claude_deny
    forbidden += [forbidden_rule(pattern) for pattern in merge.codex_forbidden]
    for key, entries in (("claude_deny", deny), ("codex_forbidden_prefix_rules", forbidden)):
        if entries:
            permissions[key] = entries
        else:
            permissions.pop(key, None)
    return updated


def read_overlay(path: Path) -> Json | None:
    if not path.is_file():
        return None
    try:
        overlay: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PolicyError(f"cannot read {path}: {error}") from error
    if not isinstance(overlay, dict):
        raise PolicyError(f"{path} must contain a JSON object")
    return overlay


def harness_drift(policy: Policy, path: Path) -> list[str]:
    current = read_overlay(path)
    if harness(current, policy.merge, path) == current:
        return []
    if policy.merge.claude_deny:
        return [f"{path} does not deny agents merging, which merge {policy.merge.key} requires"]
    return [f"{path} denies agents merging, which merge {policy.merge.key} does not"]


def write_harness(policy: Policy, path: Path) -> bool:
    current = read_overlay(path)
    expected = harness(current, policy.merge, path)
    if expected == current or expected is None:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(expected, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return True


def gh(arguments: Sequence[str], payload: object = None, run: Run = subprocess.run) -> Any:  # noqa: ANN401
    command = ["gh", "api", *arguments]
    if payload is not None:
        command += ["--input", "-"]
    try:
        result = run(command, input=None if payload is None else json.dumps(payload), capture_output=True,
                     text=True, encoding="utf-8", errors="replace", timeout=GH_TIMEOUT_SECONDS, check=False,
                     creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PolicyError(f"gh api failed: {error}") from error
    if result.returncode:
        message = (result.stderr or result.stdout).strip()
        failure = PolicyMissingError if "HTTP 404" in message else PolicyError
        raise failure(f"gh api {' '.join(arguments)} failed: {message}")
    try:
        return json.loads(result.stdout) if result.stdout.strip() else None
    except ValueError as error:
        raise PolicyError(f"gh api {' '.join(arguments)} returned invalid JSON: {error}") from error


def drift(policy: Policy, rules: Sequence[Mapping[str, Any]]) -> list[str]:
    """Return how the enforced default-branch rules differ from the policy."""
    if not rules:
        return ["no rules are enforced: the merge-policy ruleset is missing, or this is a private repository "
                "on GitHub Free, which cannot enforce rulesets"]
    by_type: dict[object, list[Mapping[str, Any]]] = {}
    for rule in rules:
        by_type.setdefault(rule.get("type"), []).append(rule.get("parameters") or {})
    problems = []
    for kind in ("deletion", "non_fast_forward"):
        if kind not in by_type:
            problems.append(f"{kind} is not blocked")
    reviews = by_type.get("pull_request", [])
    if not reviews:
        problems.append("pull requests are not required")
    approvals = max((item.get("required_approving_review_count", 0) for item in reviews), default=0)
    if policy.approval.approvals:
        if approvals < policy.approval.approvals:
            problems.append("no approval is required")
    elif approvals:
        problems.append(f"{approvals} approval(s) required, but none should be")
    if reviews and any(item.get("require_last_push_approval") for item in reviews):
        problems.append("approval of the most recent push is required")
    if reviews and any(item.get("dismiss_stale_reviews_on_push") for item in reviews):
        problems.append("a new push dismisses earlier approvals")
    enforced = {check.get("context") for item in by_type.get("required_status_checks", [])
                for check in item.get("required_status_checks", [])}
    missing = [context for context in required_contexts(policy) if context not in enforced]
    if missing:
        problems.append("required checks not enforced: " + ", ".join(missing))
    return problems


def check(repository: str, policy: Policy, branch: str | None = None, run: Run = subprocess.run) -> list[str]:
    metadata = gh([f"repos/{repository}"], run=run)
    branch = branch or metadata["default_branch"]
    rules = gh([f"repos/{repository}/rules/branches/{branch}?per_page=100"], run=run) or []
    problems = drift(policy, rules)
    if metadata.get("allow_auto_merge") is False:
        problems.append("auto-merge is disabled, so an approval or passing checks cannot land a PR")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("render", "harness", "check"):
        command = commands.add_parser(name)
        command.add_argument("--configuration", type=Path, default=DEFAULT_CONFIGURATION)
        command.add_argument("--repo", required=name != "render",
                             help="OWNER/NAME, whose owner's default applies without a merge section")
        if name != "render":
            command.add_argument("--harness", type=Path, default=DEFAULT_HARNESS)
    commands.choices["check"].add_argument("--branch")
    arguments = parser.parse_args(argv)
    try:
        policy = effective_policy(arguments.configuration, arguments.repo)
        if arguments.command == "render":
            print(json.dumps(ruleset(policy), indent=2))
        elif arguments.command == "harness":
            changed = write_harness(policy, arguments.harness)
            print(f"{'Updated' if changed else 'Unchanged'}: {arguments.harness} (merge {policy.merge.key})")
        else:
            problems = check(arguments.repo, policy, arguments.branch) + harness_drift(policy, arguments.harness)
            for problem in problems:
                print(f"merge policy drift in {arguments.repo}: {problem}", file=sys.stderr)
            if problems:
                return 1
            print(f"{arguments.repo} enforces its merge policy")
    except PolicyError as error:
        print(f"merge_policy: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
