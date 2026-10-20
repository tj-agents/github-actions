#!/usr/bin/env python3
"""Apply or check a repository's merge policy as a GitHub ruleset (Python 3.9+, needs the gh CLI).

The policy lives in `.github/merge-policy.json`. `render` prints the ruleset, `apply` creates or updates the
repository ruleset named `merge-policy` (repository admin rights required), and `check` compares the rules
GitHub actually enforces on the default branch with the policy, so CI can report drift.
"""

import argparse
import base64
import json
from pathlib import Path
import subprocess
import sys

RULESET_NAME = "merge-policy"
DEFAULT_POLICY = Path(".github/merge-policy.json")
GH_TIMEOUT_SECONDS = 60
ADMIN_ROLE_ID = 5
DEFAULT_SYNC_POLICY = {"agents_may_merge": False}
GITHUB_ACTIONS_APP_ID = 15368


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
    unknown = set(policy) - {"agents_may_merge", "required_checks", "review_check", "ci_pushes_default_branch"}
    if unknown:
        raise PolicyError(f"{path} has unknown keys: {', '.join(sorted(unknown))}")
    if not isinstance(policy.get("agents_may_merge"), bool):
        raise PolicyError(f"{path} must set agents_may_merge to true or false")
    checks = policy.get("required_checks", [])
    if not isinstance(checks, list) or not all(isinstance(check, str) and check.strip() for check in checks):
        raise PolicyError("required_checks must be a list of check names")
    if not isinstance(policy.get("ci_pushes_default_branch", False), bool):
        raise PolicyError("ci_pushes_default_branch must be true or false")
    review = policy.get("review_check")
    if policy["agents_may_merge"]:
        if not isinstance(review, str) or not review.strip():
            raise PolicyError("agents_may_merge requires review_check: the automated review check that must pass")
    elif review is not None:
        raise PolicyError("review_check applies only when agents_may_merge is true")
    return policy


def required_contexts(policy):
    contexts = list(policy.get("required_checks", []))
    if policy["agents_may_merge"]:
        contexts.append(policy["review_check"])
    return list(dict.fromkeys(contexts))


def bypass_actors(policy):
    actors = [{"actor_id": ADMIN_ROLE_ID, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"}]
    if policy.get("ci_pushes_default_branch"):
        actors.append({"actor_id": GITHUB_ACTIONS_APP_ID, "actor_type": "Integration", "bypass_mode": "always"})
    return actors


def ruleset(policy):
    human_review = not policy["agents_may_merge"]
    rules = [
        {"type": "deletion"},
        {"type": "non_fast_forward"},
        {"type": "pull_request", "parameters": {
            "required_approving_review_count": 1 if human_review else 0,
            "dismiss_stale_reviews_on_push": True,
            "require_code_owner_review": False,
            "require_last_push_approval": human_review,
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
                     text=True, encoding="utf-8", errors="replace", timeout=GH_TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PolicyError(f"gh api failed: {error}") from error
    if result.returncode:
        raise PolicyError(f"gh api {' '.join(arguments)} failed: {(result.stderr or result.stdout).strip()}")
    return json.loads(result.stdout) if result.stdout.strip() else None


def apply(repository, policy, dry_run=False, run=subprocess.run):
    desired = ruleset(policy)
    existing = [item for item in gh([f"repos/{repository}/rulesets?per_page=100"], run=run) or []
                if item.get("name") == RULESET_NAME and item.get("source_type", "Repository") == "Repository"]
    if len(existing) > 1:
        raise PolicyError(f"{repository} has {len(existing)} rulesets named {RULESET_NAME}; remove the extras")
    if dry_run:
        return {"repository": repository, "action": "update" if existing else "create", "ruleset": desired}
    if existing:
        gh(["--method", "PUT", f"repos/{repository}/rulesets/{existing[0]['id']}"], desired, run=run)
        return {"repository": repository, "action": "updated"}
    gh(["--method", "POST", f"repos/{repository}/rulesets"], desired, run=run)
    return {"repository": repository, "action": "created"}


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
    if policy["agents_may_merge"]:
        if approvals:
            problems.append(f"{approvals} approval(s) required, but agents may merge without one")
    else:
        if approvals < 1:
            problems.append("no approval is required")
        if reviews and not any(item.get("require_last_push_approval") for item in reviews):
            problems.append("the most recent push does not need approval")
        if reviews and not any(item.get("dismiss_stale_reviews_on_push") for item in reviews):
            problems.append("a new push does not dismiss earlier approvals")
    enforced = {check.get("context") for item in by_type.get("required_status_checks", [])
                for check in item.get("required_status_checks", [])}
    missing = [context for context in required_contexts(policy) if context not in enforced]
    if missing:
        problems.append("required checks not enforced: " + ", ".join(missing))
    return problems


def check(repository, policy, branch=None, run=subprocess.run):
    branch = branch or gh([f"repos/{repository}"], run=run)["default_branch"]
    rules = gh([f"repos/{repository}/rules/branches/{branch}?per_page=100"], run=run) or []
    return drift(policy, rules)


def repository_policy(repository, run=subprocess.run):
    try:
        content = gh([f"repos/{repository}/contents/{DEFAULT_POLICY.as_posix()}"], run=run)
    except PolicyError as error:
        if "HTTP 404" in str(error):
            return dict(DEFAULT_SYNC_POLICY)
        raise
    try:
        policy = json.loads(base64.b64decode(content["content"]).decode("utf-8"))
    except (KeyError, TypeError, ValueError) as error:
        raise PolicyError(f"{repository}/{DEFAULT_POLICY.as_posix()} is not valid JSON") from error
    return validate_policy(policy, f"{repository}/{DEFAULT_POLICY.as_posix()}")


def public_repositories(owner, run=subprocess.run):
    repositories, page = [], 1
    while True:
        batch = gh([f"users/{owner}/repos?type=owner&per_page=100&page={page}"], run=run) or []
        repositories += [item["full_name"] for item in batch
                         if not item.get("private") and not item.get("fork") and not item.get("archived")]
        if len(batch) < 100:
            return repositories
        page += 1


def sync(owners, run=subprocess.run):
    """Apply each public repository's merge policy, or the default, wherever GitHub has drifted from it."""
    results = []
    for owner in owners:
        for repository in public_repositories(owner, run=run):
            try:
                policy = repository_policy(repository, run=run)
                if not check(repository, policy, run=run):
                    results.append((repository, "current", []))
                    continue
                action = apply(repository, policy, run=run)["action"]
                results.append((repository, action, check(repository, policy, run=run)))
            except PolicyError as error:
                results.append((repository, "failed", [str(error)]))
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("render", "apply", "check"):
        command = commands.add_parser(name)
        command.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
        if name != "render":
            command.add_argument("--repo", required=True, help="OWNER/NAME")
    commands.choices["apply"].add_argument("--dry-run", action="store_true")
    commands.choices["check"].add_argument("--branch")
    commands.add_parser("sync").add_argument("--owner", action="append", required=True)
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "sync":
            results = sync(arguments.owner)
            for repository, action, problems in results:
                if action != "current" or problems:
                    print(f"{action} {repository}" + (": " + "; ".join(problems) if problems else ""))
            print(f"{len(results)} public repositories checked")
            return 1 if any(problems for _, _, problems in results) else 0
        policy = load_policy(arguments.policy)
        if arguments.command == "render":
            print(json.dumps(ruleset(policy), indent=2))
        elif arguments.command == "apply":
            print(json.dumps(apply(arguments.repo, policy, arguments.dry_run), indent=2))
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
