#!/usr/bin/env python3
"""Render or check a repository's merge policy against GitHub (Python 3.9+, needs the gh CLI).

The policy lives in `.github/merge-policy.json`. `render` prints the ruleset GitHub should enforce, and
`check` compares the rules GitHub actually enforces on the default branch with the policy, so CI can report
drift. Ruleset writes are owned by tj-agents/github's `github:configuration` Terraform workspace.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

RULESET_NAME = "merge-policy"
DEFAULT_POLICY = Path(".github/merge-policy.json")
GH_TIMEOUT_SECONDS = 60
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
ADMIN_ROLE_ID = 5


class PolicyError(Exception):
    pass


def load_policy(path):
    try:
        policy = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as error:
        raise PolicyError(f"cannot read {path}: {error}") from error
    except ValueError as error:
        raise PolicyError(f"{path} is not valid JSON: {error}") from error
    return validate_policy(policy, path)


def validate_policy(policy, path):
    if not isinstance(policy, dict):
        raise PolicyError(f"{path} must contain a JSON object")
    unknown = set(policy) - {"requires_approval", "required_checks", "review_check", "ci_pushes_default_branch"}
    if unknown:
        raise PolicyError(f"{path} has unknown keys: {', '.join(sorted(unknown))}")
    if not isinstance(policy.get("requires_approval"), bool):
        raise PolicyError(f"{path} must set requires_approval to true or false")
    checks = policy.get("required_checks", [])
    if not isinstance(checks, list) or not all(isinstance(check, str) and check.strip() for check in checks):
        raise PolicyError("required_checks must be a list of check names")
    if not isinstance(policy.get("ci_pushes_default_branch", False), bool):
        raise PolicyError("ci_pushes_default_branch must be true or false")
    review = policy.get("review_check")
    if not policy["requires_approval"]:
        if review is not None and (not isinstance(review, str) or not review.strip()):
            raise PolicyError("review_check must name the automated review check that must pass")
    elif review is not None:
        raise PolicyError("review_check applies only when requires_approval is false")
    return policy


def required_contexts(policy):
    contexts = list(policy.get("required_checks", []))
    if not policy["requires_approval"] and policy.get("review_check"):
        contexts.append(policy["review_check"])
    return list(dict.fromkeys(contexts))


def bypass_actors(policy):
    actors = [{"actor_id": ADMIN_ROLE_ID, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"}]
    if policy.get("ci_pushes_default_branch"):
        actors.append({"actor_type": "DeployKey", "bypass_mode": "always"})
    return actors


def ruleset(policy):
    human_review = policy["requires_approval"]
    rules = [
        {"type": "deletion"},
        {"type": "non_fast_forward"},
        {"type": "pull_request", "parameters": {
            "required_approving_review_count": 1 if human_review else 0,
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


def gh(arguments, payload=None, run=subprocess.run):
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
        raise PolicyError(f"gh api {' '.join(arguments)} failed: {(result.stderr or result.stdout).strip()}")
    return json.loads(result.stdout) if result.stdout.strip() else None


def drift(policy, rules):
    """Return how the enforced default-branch rules differ from the policy."""
    if not rules:
        return ["no rules are enforced: the merge-policy ruleset is missing, or this is a private repository "
                "on GitHub Free, which cannot enforce rulesets"]
    by_type = {}
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
    if policy["requires_approval"]:
        if approvals < 1:
            problems.append("no approval is required")
    else:
        if approvals:
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


def check(repository, policy, branch=None, run=subprocess.run):
    metadata = gh([f"repos/{repository}"], run=run)
    branch = branch or metadata["default_branch"]
    rules = gh([f"repos/{repository}/rules/branches/{branch}?per_page=100"], run=run) or []
    problems = drift(policy, rules)
    if metadata.get("allow_auto_merge") is False:
        problems.append("auto-merge is disabled, so an approval or passing checks cannot land a PR")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("render", "check"):
        command = commands.add_parser(name)
        command.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
        if name != "render":
            command.add_argument("--repo", required=True, help="OWNER/NAME")
    commands.choices["check"].add_argument("--branch")
    arguments = parser.parse_args(argv)
    try:
        policy = load_policy(arguments.policy)
        if arguments.command == "render":
            print(json.dumps(ruleset(policy), indent=2))
        else:
            problems = check(arguments.repo, policy, arguments.branch)
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
