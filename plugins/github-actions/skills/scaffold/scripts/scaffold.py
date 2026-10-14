from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys


ASSETS = Path(__file__).resolve().parent.parent / "templates"
VERSION = "1.0.0"
PINS = {
    "actions/checkout": ("3d3c42e5aac5ba805825da76410c181273ba90b1", "v7.0.1"),
    "actions/github-script": ("3a2844b7e9c422d3c10d287c895573f7108da1b3", "v9.0.0"),
    "actions/upload-artifact": ("cf430e030ddbb5b0abf93d22962f4752f3646cd9", "v7.0.2"),
    "actions/download-artifact": ("3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c", "v8.0.1"),
    "actions/setup-dotnet": ("a98b56852c35b8e3190ac28c8c2271da59106c68", "v6.0.0"),
    "actions/setup-node": ("949feb2413d6458794dcd2491c4babbbce0c15c1", "v7.1.0"),
    "pnpm/action-setup": ("d9184bf108216479bc5a137cc391f4d7b14c870b", "v6.1.0"),
    "hashicorp/setup-terraform": ("dfe3c3f87815947d99a8997f908cb6525fc44e9e", "v4.0.1"),
    "azure/login": ("a641126d1b8aa4d1fa005f4f92df94a3a4c4c906", "v3.1.0"),
}
PHASES = {"setup", "validate", "plan", "deploy", "readiness", "destroy", "recover"}
IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")
EXPRESSION_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
TRUSTED = "github.event.pull_request.head.repo.full_name == github.repository"
PREVIEW = "contains(github.event.pull_request.labels.*.name, 'deploy-preview')"
VERIFY_CONCURRENCY = "${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}"
RESERVED_ENV = {"DEPLOY_ENVIRONMENT", "PREVIEW_NUMBER", "SOURCE_RUN_ID", "SOURCE_SHA", "ARTIFACT_DIRECTORY"}


class InputError(ValueError):
    pass


class WriteError(OSError):
    pass


class Pin(str):
    pass


def action(name: str) -> Pin:
    sha, version = PINS[name]
    return Pin(f"{name}@{sha} # {version}")


def expr(text: str) -> str:
    return "${{ " + text + " }}"


def expression_tokens(value: str) -> list[list[tuple[str, str]]]:
    expressions = []
    position = 0
    while True:
        start = value.find("${{", position)
        if start < 0:
            return expressions
        position = start + 3
        tokens = []
        while position < len(value) and not value.startswith("}}", position):
            char = value[position]
            if char.isspace():
                position += 1
            elif char == "'":
                position += 1
                literal = []
                while position < len(value):
                    if value[position] == "'":
                        position += 1
                        if position < len(value) and value[position] == "'":
                            literal.append("'")
                            position += 1
                        else:
                            break
                    else:
                        literal.append(value[position])
                        position += 1
                else:
                    raise InputError("unterminated expression string")
                tokens.append(("string", "".join(literal).lower()))
            else:
                name = EXPRESSION_NAME.match(value, position)
                if name:
                    tokens.append(("name", name.group().lower()))
                    position = name.end()
                else:
                    tokens.append(("symbol", char))
                    position += 1
        if position >= len(value):
            raise InputError("unterminated expression")
        expressions.append(tokens)
        position += 2


def expression_property(tokens: list[tuple[str, str]], index: int) -> str | None:
    following = tokens[index + 1:index + 4]
    if len(following) >= 2 and following[0] == ("symbol", ".") and following[1][0] == "name":
        return following[1][1]
    if len(following) == 3 and following[0] == ("symbol", "[") and following[1][0] == "string" and following[2] == ("symbol", "]"):
        return following[1][1]
    return None


def expression_contexts(value: object) -> set[str]:
    if isinstance(value, dict):
        return set().union(*(expression_contexts(val) for val in value.values()))
    if isinstance(value, list):
        return set().union(*(expression_contexts(val) for val in value))
    if not isinstance(value, str):
        return set()
    contexts = set()
    for tokens in expression_tokens(value):
        for index, token in enumerate(tokens):
            if token[0] != "name" or (index > 0 and tokens[index - 1] == ("symbol", ".")):
                continue
            if token[1] == "secrets":
                contexts.add("secrets")
            elif token[1] in {"steps", "needs", "matrix"}:
                contexts.add("untrusted")
            elif token[1] == "inputs":
                contexts.update({"inputs", "untrusted"})
            elif token[1] == "github":
                property_name = expression_property(tokens, index)
                if property_name is None or property_name in {"event", "head_ref"}:
                    contexts.add("untrusted")
    return contexts


def environment_references(value: object) -> set[str | None]:
    if isinstance(value, dict):
        return set().union(*(environment_references(val) for val in value.values()))
    if isinstance(value, list):
        return set().union(*(environment_references(val) for val in value))
    if not isinstance(value, str):
        return set()
    references = set()
    for tokens in expression_tokens(value):
        for index, token in enumerate(tokens):
            if token == ("name", "env") and (index == 0 or tokens[index - 1] != ("symbol", ".")):
                references.add(expression_property(tokens, index))
    return references


def environment_contexts(value: object, environment: dict[str, frozenset[str]]) -> set[str]:
    contexts = expression_contexts(value)
    for name in environment_references(value):
        contexts.update(environment.get(name, frozenset({"unknown-env"})))
    return contexts


def resolved_environment(assignments: dict, inherited: dict[str, frozenset[str]]) -> dict[str, frozenset[str]]:
    return {**inherited, **{key.lower(): frozenset(environment_contexts(val, inherited)) for key, val in assignments.items()}}


def validate_environment_boundaries(config: dict) -> None:
    composites = config["provider"]["composites"]
    visited = set()

    def check(scope: dict, inherited: dict[str, frozenset[str]], where: str, actions: frozenset[str], *, setup: bool = False) -> None:
        if setup:
            inherited = resolved_environment(scope.get("env", {}), inherited)
        for index, step in enumerate(scope["steps"]):
            label = f"{where}.steps[{index}]"
            assignments = {**({} if setup else scope.get("env", {})), **step.get("env", {})}
            environment = resolved_environment(assignments, inherited)
            for key, val in step.items():
                if key != "env" and "secrets" in environment_contexts(val, environment):
                    raise InputError(f"{label}: pass secrets through the consuming step env")
            command = step.get("run")
            if step.get("uses", "").startswith("actions/github-script@"):
                command = step.get("with", {}).get("script", "")
            if command is not None and environment_contexts(command, environment) & {"untrusted", "secrets", "unknown-env"}:
                raise InputError(f"{label}: consume untrusted, secret or unresolved env values through environment variables")
            use = step.get("uses", "")
            if use.startswith("./"):
                name = use.rsplit("/", 1)[-1]
                if name in actions:
                    raise InputError(f"{label}: recursive local composite action")
                visited.add(name)
                check(composites[name], environment, "composite." + name, actions | {name})

    writer_env = {key.lower(): frozenset() for key in RESERVED_ENV}
    scopes = [*config["verify"].items(), *config["provider"]["phases"].items()]
    if "build" in config:
        scopes.append(("build", config["build"]))
    for name, scope in scopes:
        check(scope, writer_env, name, frozenset(), setup=name == "setup")
    for name, scope in composites.items():
        if name not in visited:
            check(scope, writer_env, "composite." + name, frozenset({name}))


def object_keys(value: object, allowed: set[str], where: str) -> dict:
    if not isinstance(value, dict):
        raise InputError(f"{where}: expected an object")
    extra = set(value) - allowed
    if extra:
        raise InputError(f"{where}: unknown keys: {', '.join(sorted(extra))}")
    return value


def text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise InputError(f"{where}: expected a nonempty string without NUL")
    return value


def relative_path(value: object, where: str, allow_root: bool = False) -> str:
    value = text(value, where)
    parts = value.split("/")
    if allow_root and value == ".":
        return value
    if "\\" in value or ":" in value or value.startswith("/") or any(p in ("", ".", "..") for p in parts):
        raise InputError(f"{where}: expected a relative POSIX path without traversal")
    if any(p.lower().rstrip(". ") != p.lower() for p in parts):
        raise InputError(f"{where}: ambiguous path")
    return value


def roots(value: object, where: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise InputError(f"{where}: expected a nonempty list of working roots")
    result = [relative_path(v, where, allow_root=True) for v in value]
    if len(set(result)) != len(result):
        raise InputError(f"{where}: duplicate roots")
    return result


def scalar_map(value: object, where: str, environment: bool = False) -> dict:
    if not isinstance(value, dict):
        raise InputError(f"{where}: expected an object")
    for key, val in value.items():
        if not isinstance(key, str) or not isinstance(val, (str, int, float, bool)) or val is None:
            raise InputError(f"{where}: expected scalar values with string keys")
        if environment and not ENV_NAME.fullmatch(key):
            raise InputError(f"{where}.{key}: expected SCREAMING_SNAKE")
    if environment:
        return copy.deepcopy(value)
    result = {}
    for key, val in value.items():
        canonical = key.lower()
        if canonical in result:
            raise InputError(f"{where}: duplicate action input {canonical}")
        result[canonical] = val
    return result


def steps(value: object, where: str, composite: bool = False) -> list[dict]:
    if not isinstance(value, list) or not value:
        raise InputError(f"{where}: expected a nonempty step list")
    result = []
    ids = set()
    for index, raw in enumerate(value):
        label = f"{where}[{index}]"
        raw = object_keys(raw, {"name", "id", "run", "uses", "shell", "with", "env", "if", "working-directory"}, label)
        step = copy.deepcopy(raw)
        text(step.get("name"), label + ".name")
        if ("run" in step) == ("uses" in step):
            raise InputError(f"{label}: exactly one of run and uses is required")
        if "id" in step:
            if not isinstance(step["id"], str) or not IDENTIFIER.fullmatch(step["id"]) or step["id"] in ids:
                raise InputError(f"{label}: invalid or repeated step id")
            ids.add(step["id"])
        for key in ("env", "with"):
            if key in step:
                step[key] = scalar_map(step[key], label + "." + key, key == "env")
        for key in ("if", "working-directory"):
            if key in step:
                text(step[key], label + "." + key)
        if "if" in step:
            condition = step["if"].strip()
            step["if"] = condition if condition.startswith("${{") and condition.endswith("}}") else expr(condition)
        if any("secrets" in expression_contexts(val) for key, val in step.items() if key != "env"):
            raise InputError(f"{label}: pass secrets through the consuming step env")
        if "run" in step:
            command = text(step["run"], label + ".run")
            if "with" in step or "untrusted" in expression_contexts(command):
                raise InputError(f"{label}: pass untrusted script inputs through env")
            if step.get("shell", "bash") != "bash":
                raise InputError(f"{label}: the canonical shell is bash")
            step["shell"] = "bash"
            if "\n" in command and command.splitlines()[0] != "set -euo pipefail":
                step["run"] = "set -euo pipefail\n" + command
        else:
            if "shell" in step or "working-directory" in step:
                raise InputError(f"{label}: uses steps cannot set shell or working-directory")
            name = text(step["uses"], label + ".uses")
            if name in PINS:
                step["uses"] = action(name)
            elif not re.fullmatch(r"\./\.github/actions/[a-z][a-z0-9-]*", name):
                raise InputError(f"{label}: action must be local or in the writer's pin catalog")
            if name == "actions/checkout":
                step.setdefault("with", {})["persist-credentials"] = False
            if name == "actions/github-script" and "untrusted" in expression_contexts(step.get("with", {}).get("script", "")):
                raise InputError(f"{label}: pass untrusted script inputs through env")
            if name == "actions/upload-artifact":
                settings = step.get("with", {})
                if settings.get("if-no-files-found") not in ("error", "warn") or type(settings.get("retention-days")) is not int or settings["retention-days"] < 1:
                    raise InputError(f"{label}: artifact policy and retention-days are required")
                if "overwrite" in settings and settings["overwrite"] is not False:
                    raise InputError(f"{label}: supplied artifact uploads cannot overwrite artifacts")
                if "name" in settings:
                    artifact_name = text(settings["name"], label + ".with.name")
                    if "${{" in artifact_name or artifact_name.strip() == "deployment":
                        raise InputError(f"{label}: supplied artifact names must be literal and cannot use reserved deployment")
        result.append(step)
    return result


def phase(value: object, where: str) -> dict:
    value = object_keys(value, {"steps", "matrix", "roots", "env"}, where)
    result = {"steps": steps(value.get("steps"), where + ".steps")}
    if "roots" in value:
        result["roots"] = roots(value["roots"], where + ".roots")
    if "env" in value:
        result["env"] = scalar_map(value["env"], where + ".env", True)
        if set(result["env"]) & RESERVED_ENV or "secrets" in expression_contexts(result["env"]):
            raise InputError(f"{where}: reserved env or job-level secrets")
    if "matrix" in value:
        matrix = value["matrix"]
        if not isinstance(matrix, dict) or not matrix:
            raise InputError(f"{where}.matrix: expected named dimensions")
        for key, values in matrix.items():
            if not isinstance(key, str) or not IDENTIFIER.fullmatch(key) or not isinstance(values, list) or not values or not all(isinstance(v, str) and v for v in values):
                raise InputError(f"{where}.matrix: dimensions must have nonempty string lists")
        result["matrix"] = copy.deepcopy(matrix)
    return result


def validate(config: object) -> dict:
    config = object_keys(config, {"schema_version", "prod-release", "roots", "verify", "build", "provider"}, "config")
    if type(config.get("schema_version")) is not int or config["schema_version"] != 1:
        raise InputError("schema_version must be 1")
    if type(config.get("prod-release", True)) is not bool:
        raise InputError("prod-release must be a boolean")
    result = {"schema_version": 1, "prod-release": config.get("prod-release", True), "roots": roots(config.get("roots", ["."]), "roots")}
    verify = object_keys(config.get("verify"), {"unit", "integration", "end-to-end"}, "verify")
    if verify and "unit" not in verify:
        raise InputError("verify.unit is required when verification is nonempty")
    result["verify"] = {key: phase(val, "verify." + key) for key, val in verify.items()}
    provider = object_keys(config.get("provider"), {"name", "oidc", "ready", "environments", "phases", "composites"}, "provider")
    name = text(provider.get("name"), "provider.name")
    if not IDENTIFIER.fullmatch(name) or type(provider.get("oidc", False)) is not bool:
        raise InputError("provider: invalid name or oidc boolean")
    ready = provider.get("ready", "true")
    if not isinstance(ready, str) or not re.fullmatch(r"true|vars\.[A-Z_][A-Z0-9_]* == 'true'", ready):
        raise InputError("provider.ready must be true or a vars.NAME == 'true' condition")
    supplied = object_keys(provider.get("phases"), PHASES, "provider.phases")
    required = {"validate", "plan", "deploy", "readiness", "destroy", "recover"}
    if not required <= supplied.keys():
        raise InputError("provider.phases missing: " + ", ".join(sorted(required - supplied.keys())))
    environments = object_keys(provider.get("environments", {}), {"ci", "preview", "prod"}, "provider.environments")
    environments = {key: environments.get(key, key) for key in ("ci", "preview", "prod")}
    for key, value in environments.items():
        targets = value if key == "prod" and isinstance(value, list) else [value]
        if not targets or not all(isinstance(target, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", target) for target in targets) or len(set(targets)) != len(targets):
            raise InputError("provider.environments must contain distinct literal environment names")
    for key, value in supplied.items():
        if key not in {"validate", "plan"} and isinstance(value, dict) and "matrix" in value:
            raise InputError("only validate and plan provider phases declare matrices; production targets are environment data")
    result["provider"] = {"name": name, "oidc": provider.get("oidc", False), "ready": ready, "environments": environments, "phases": {key: phase(val, "provider.phases." + key) for key, val in supplied.items()}, "composites": {}}
    composites = provider.get("composites", {})
    if not isinstance(composites, dict):
        raise InputError("provider.composites must be an object")
    for key, val in composites.items():
        if not isinstance(key, str) or not IDENTIFIER.fullmatch(key):
            raise InputError("provider.composites: invalid action name")
        val = object_keys(val, {"description", "inputs", "steps"}, "composite." + key)
        inputs = val.get("inputs", {})
        if not isinstance(inputs, dict):
            raise InputError("composite inputs must be an object")
        for input_key, definition in inputs.items():
            if not isinstance(input_key, str) or not IDENTIFIER.fullmatch(input_key):
                raise InputError("composite input names must be kebab-case")
            object_keys(definition, {"description", "required", "default"}, "composite input")
            text(definition.get("description"), "composite input description")
            if type(definition.get("required", False)) is not bool or not isinstance(definition.get("default", ""), str):
                raise InputError("composite input requires boolean required and string default")
        result["provider"]["composites"][key] = {"description": text(val.get("description"), "composite description"), "inputs": copy.deepcopy(inputs), "steps": steps(val.get("steps"), "composite." + key, True)}
    if "build" in config:
        build = object_keys(config["build"], {"steps", "roots", "artifact", "oidc"}, "build")
        result["build"] = phase({key: val for key, val in build.items() if key in {"steps", "roots"}}, "build")
        if type(build.get("oidc", False)) is not bool:
            raise InputError("build.oidc must be a boolean")
        result["build"]["oidc"] = build.get("oidc", False)
        artifact = object_keys(build.get("artifact"), {"path"}, "build.artifact")
        result["build"]["artifact"] = {"path": text(artifact.get("path"), "build.artifact.path")}
    local_actions = set(result["provider"]["composites"])
    scopes = list(result["verify"].values()) + list(result["provider"]["phases"].values()) + list(result["provider"]["composites"].values())
    if "build" in result:
        scopes.append(result["build"])
    for scope in scopes:
        for step in scope["steps"]:
            use = step.get("uses", "")
            if use.startswith("./") and use.rsplit("/", 1)[-1] not in local_actions:
                raise InputError(f"local action {use} is not provided")
    validate_environment_boundaries(result)
    return result


def normalize_supplied_sdk_caches(config: dict) -> None:
    composites = config["provider"]["composites"]
    pending = [scope for name, scope in config["provider"]["phases"].items() if name != "validate"]
    if config.get("build", {}).get("oidc", False):
        pending.append(config["build"])
    visited = set()
    while pending:
        for step in pending.pop()["steps"]:
            use = step.get("uses", "")
            if use.startswith("./"):
                name = use.rsplit("/", 1)[-1]
                if name not in visited:
                    visited.add(name)
                    pending.append(composites[name])
            elif use.partition("@")[0] in {"actions/setup-node", "actions/setup-dotnet"}:
                node = use.partition("@")[0] == "actions/setup-node"
                removed = {"cache", "cache-dependency-path"}
                if node:
                    removed.add("package-manager-cache")
                step["with"] = {key: val for key, val in step.get("with", {}).items() if key.lower() not in removed}
                step["with"]["package-manager-cache" if node else "cache"] = False


def yaml(value: object, indent: int = 0) -> str:
    pad = " " * indent
    lines = []
    if isinstance(value, dict):
        for key, val in value.items():
            prefix = pad + json.dumps(str(key)) + ":"
            if isinstance(val, (dict, list)) and val:
                lines.append(prefix + "\n" + yaml(val, indent + 2))
            else:
                lines.append(prefix + " " + yaml_scalar(val, indent + 2))
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)) and item:
                lines.append(pad + "-\n" + yaml(item, indent + 2))
            else:
                lines.append(pad + "- " + yaml_scalar(item, indent + 2))
    return "\n".join(lines)


def yaml_scalar(value: object, indent: int) -> str:
    if isinstance(value, Pin):
        return str(value)
    if isinstance(value, str) and "\n" in value:
        return "|-\n" + "\n".join(" " * indent + line for line in value.rstrip("\n").split("\n"))
    return json.dumps(value, ensure_ascii=False)


def checkout(ref: str | None = None) -> dict:
    settings = {"persist-credentials": False}
    if ref:
        settings["ref"] = ref
    return {"name": "Check out the repository", "uses": action("actions/checkout"), "with": settings}


def metadata_json(files: dict[str, str], path: str) -> dict:
    try:
        data = json.loads(files[path])
    except (ValueError, TypeError) as error:
        raise InputError(f"{path}: invalid repository JSON ({error})") from error
    if not isinstance(data, dict):
        raise InputError(f"{path}: repository metadata must be an object")
    return data


def ancestor_file(files: dict[str, str], root: str, names: tuple[str, ...]) -> str | None:
    base = PurePosixPath(root)
    for parent in (base, *base.parents):
        for name in names:
            path = (parent / name).as_posix()
            if path in files:
                return path
    return None


def toolchains(working_roots: list[str], files: dict[str, str], privileged: bool = False) -> list[dict]:
    result = []
    seen = set()
    for root in working_roots:
        global_json = ancestor_file(files, root, ("global.json",))
        if global_json and global_json not in seen:
            sdk = metadata_json(files, global_json).get("sdk", {})
            if not isinstance(sdk, dict) or not isinstance(sdk.get("version"), str) or not re.fullmatch(r"\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?", sdk["version"]):
                raise InputError(f"{global_json}: sdk.version must declare the SDK")
            seen.add(global_json)
            settings = {"global-json-file": global_json}
            lock = ancestor_file(files, root, ("packages.lock.json",))
            if lock and not privileged:
                settings.update({"cache": True, "cache-dependency-path": lock})
            result.append({"name": "Set up .NET", "uses": action("actions/setup-dotnet"), "with": settings})
        package = ancestor_file(files, root, ("package.json",))
        version_file = ancestor_file(files, root, (".node-version", ".nvmrc"))
        if package and package not in seen:
            manifest = metadata_json(files, package)
            manager = manifest.get("packageManager", "")
            if manager and not re.fullmatch(r"(?:npm|pnpm|yarn)@\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.]+)?", manager):
                raise InputError(f"{package}: packageManager must pin a version")
            engines = manifest.get("engines", {})
            if not version_file and (not isinstance(engines, dict) or not isinstance(engines.get("node"), str) or not engines["node"].strip()):
                raise InputError(f"{package}: declare engines.node, .node-version or .nvmrc")
            seen.add(package)
            if version_file:
                seen.add(version_file)
            if manager.startswith("pnpm@"):
                result.append({"name": "Set up pnpm", "uses": action("pnpm/action-setup"), "with": {"package_json_file": package, "run_install": False}})
            settings = {"node-version-file": version_file or package, "package-manager-cache": False}
            manager_name = manager.partition("@")[0] or "npm"
            lock_names = {"npm": ("package-lock.json", "npm-shrinkwrap.json"), "pnpm": ("pnpm-lock.yaml",), "yarn": ("yarn.lock",)}[manager_name]
            lock = ancestor_file(files, str(PurePosixPath(package).parent), lock_names)
            if lock and manager_name != "yarn" and not privileged:
                settings.update({"cache": manager_name, "cache-dependency-path": lock})
            result.append({"name": "Set up Node", "uses": action("actions/setup-node"), "with": settings})
            if manager_name == "npm" and manager:
                result.append({"name": "Select the repository npm version", "shell": "bash", "env": {"PACKAGE_MANAGER": manager}, "run": "npm install --global \"$PACKAGE_MANAGER\""})
            if manager_name == "yarn":
                raise InputError(f"{package}: the canonical writer supports npm and pnpm packageManager metadata")
        elif version_file and version_file not in seen:
            seen.add(version_file)
            result.append({"name": "Set up Node", "uses": action("actions/setup-node"), "with": {"node-version-file": version_file, "package-manager-cache": False}})
    return result


def executing_job(name: str, job_steps: list[dict], *, needs: list[str] | None = None, cloud: bool = False, timeout: int = 20) -> dict:
    ids = set()
    for step in job_steps:
        step_id = step.get("id")
        if step_id is not None:
            if step_id in ids:
                raise InputError(f"{name}: repeated step id {step_id}")
            ids.add(step_id)
    job = {"name": name, "runs-on": "ubuntu-latest", "timeout-minutes": timeout, "permissions": {"contents": "read"}}
    if cloud:
        job["permissions"]["id-token"] = "write"
    if needs:
        job["needs"] = needs
    job["steps"] = job_steps
    return job


def phase_steps(val: dict) -> list[dict]:
    result = copy.deepcopy(val["steps"])
    if "env" in val:
        for step in result:
            step["env"] = {**val["env"], **step.get("env", {})}
    return result


def apply_phase(job: dict, val: dict) -> None:
    if "matrix" in val:
        job["strategy"] = {"fail-fast": False, "matrix": val["matrix"]}


def workflow(name: str, trigger: dict, group: str, cancel: bool, jobs: dict) -> dict:
    return {"name": name, "on": trigger, "permissions": {"contents": "read"}, "concurrency": {"group": group, "cancel-in-progress": cancel}, "jobs": jobs}


def asset(name: str) -> str:
    return (ASSETS / name).read_text(encoding="utf-8").replace("\r\n", "\n")


def script_step(name: str, filename: str, env: dict | None = None, step_id: str | None = None) -> dict:
    result = {"name": name, "uses": action("actions/github-script"), "with": {"script": asset(filename)}}
    if env:
        result["env"] = env
    if step_id:
        result["id"] = step_id
    return result


def guarded_steps(job_steps: list[dict], condition: str, *, recovery: bool = False) -> list[dict]:
    result = copy.deepcopy(job_steps)
    for step in result:
        existing = step.get("if", "").strip()
        if existing.startswith("${{") and existing.endswith("}}"):
            existing = existing[3:-2].strip()
        guard = ("!failure()" if recovery else "success()") + " && " + condition
        if existing:
            guard += " && (" + existing + ")"
        step["if"] = expr(guard)
    return result


def provider_steps(val: dict, condition: str, authorization: str, *, recovery: bool = False) -> list[dict]:
    result = phase_steps(val)
    for step in result:
        existing = step.get("if", "").strip()
        if existing.startswith("${{") and existing.endswith("}}"):
            existing = existing[3:-2].strip()
        tokens = expression_tokens(expr(existing))[0]
        has_status = any(
            token[0] == "name" and token[1] in {"always", "failure", "success", "cancelled"}
            and tokens[index + 1:index + 2] == [("symbol", "(")]
            for index, token in enumerate(tokens)
        )
        guard = "(" + authorization + ") && steps.provider-ready.outcome == 'success' && " + condition
        if not has_status:
            guard = ("!failure()" if recovery else "success()") + " && " + guard
        if existing:
            guard += " && (" + existing + ")"
        step["if"] = expr(guard)
    return result


def provider_ready_step(authorization: str, *, recovery: bool = False) -> dict:
    step = {"name": "Confirm provider prerequisites", "id": "provider-ready", "shell": "bash", "run": "true"}
    return guarded_steps([step], authorization, recovery=recovery)[0]


def preview_state_step(number: str, *, recovery: bool = False) -> dict:
    step = script_step("Resolve the live preview lifecycle", "preview-state.js", {"PREVIEW_NUMBER": number}, "preview-state")
    step["if"] = expr("!failure()" if recovery else "inputs.preview-number != ''")
    return step


def aggregate(mandatory: list[str], workflow_file: str) -> dict:
    step = {"name": "Check that every required gate succeeded", "shell": "bash", "env": {"GATE_RESULTS": expr("toJSON(needs)"), "WORKFLOW_FILE": workflow_file}, "run": asset("aggregate.sh")}
    result = executing_job("CI complete", [step], needs=mandatory, timeout=5)
    result["if"] = "always()"
    result["permissions"] = {}
    return result


def optional_gate(jobs: dict, optional: dict[str, str]) -> str:
    job = executing_job("Check the optional cloud gates", [{"name": "Check selected cloud operations", "shell": "bash", "env": {"GATE_RESULTS": expr("toJSON(needs)"), **{key.upper().replace("-", "_"): value if value in {"true", "false"} else expr(value) for key, value in optional.items()}}, "run": asset("optional-gates.sh")}], needs=list(optional), timeout=5)
    job["if"] = "always()"
    job["permissions"] = {}
    jobs["cloud-gates"] = job
    return "cloud-gates"


def reusable_call(environment: str, needs: list[str], condition: str, oidc: bool, *, build: bool = False, release: bool = False, preview: bool = False) -> dict:
    settings = {"environment": environment, "preview-number": expr("github.event.pull_request.number") if preview else "", "source-sha": expr("needs.assert-release-commit.outputs.source-sha") if release else expr("github.sha"), "source-run-id": expr("needs.assert-release-commit.outputs.source-run-id") if release else expr("github.run_id")}
    if build:
        settings["artifact-id"] = expr("needs.assert-release-commit.outputs.artifact-id") if release else expr("needs.build.outputs.artifact-id")
    condition += " && " + " && ".join("needs." + key + ".result == 'success'" for key in needs)
    permissions = {"contents": "read", "actions": "read", "pull-requests": "read"}
    if oidc:
        permissions["id-token"] = "write"
    return {"name": "Deploy the environment", "needs": needs, "if": expr(condition), "permissions": permissions, "uses": "./.github/workflows/deploy-environment.yml", "with": settings}


def render_documents(config: object, repository_files: dict[str, str] | None = None) -> tuple[dict, dict]:
    resolved = validate(config)
    files = repository_files or {}
    if not isinstance(files, dict):
        raise InputError("repository_files must be a file map")
    for key, content in files.items():
        relative_path(key, "repository_files")
        if not isinstance(content, str):
            raise InputError("repository_files contents must be strings")
    provider = resolved["provider"]
    phases = provider["phases"]
    oidc = provider["oidc"]
    ready = provider["ready"]
    environments = provider["environments"]
    build = resolved.get("build")
    documents = {}
    setup_steps = []
    if "setup" in phases:
        if "cloud-setup" in provider["composites"]:
            raise InputError("cloud-setup is reserved for the repeated provider setup envelope")
        if "inputs" in expression_contexts(phases["setup"]):
            raise InputError("provider.setup uses writer env data rather than workflow inputs")
    normalize_supplied_sdk_caches(resolved)
    if "setup" in phases:
        documents[".github/actions/cloud-setup/action.yml"] = {"name": "Set up the cloud provider", "description": "Run the provider's repeated sign-in and initialization steps", "runs": {"using": "composite", "steps": [*toolchains(phases["setup"].get("roots", []), files, privileged=True), *phases["setup"]["steps"]]}}
        setup_steps = [{"name": "Set up the cloud provider", "uses": "./.github/actions/cloud-setup"}]
        if "env" in phases["setup"]:
            setup_steps[0]["env"] = copy.deepcopy(phases["setup"]["env"])
    for event in ("pr", "ci"):
        jobs = {}
        required = []
        optional = {}
        for layer, val in resolved["verify"].items():
            if layer == "end-to-end":
                continue
            key = "verify-" + layer
            jobs[key] = executing_job("Run the " + layer + " tests", [checkout(), *toolchains(val.get("roots", resolved["roots"]), files), *phase_steps(val)])
            apply_phase(jobs[key], val)
            required.append(key)
        jobs["lint"] = executing_job("Validate workflow correctness and security", [checkout(), {"name": "Lint workflows and composite actions", "shell": "bash", "run": "python3 .github/scripts/lint-workflows.py"}], timeout=10)
        required.append("lint")
        val = phases["validate"]
        jobs["validate"] = executing_job("Validate the infrastructure", [checkout(), *toolchains(val.get("roots", []), files), *phase_steps(val)])
        apply_phase(jobs["validate"], val)
        required.append("validate")
        deploy_needs = list(required)
        cloud_condition = TRUSTED + " && " + ready if event == "pr" else "true"
        if build:
            build_steps = [checkout(), *toolchains(build.get("roots", resolved["roots"]), files, privileged=build["oidc"])]
            if build["oidc"]:
                build_steps.extend(setup_steps)
            build_steps.extend(phase_steps(build))
            build_steps.append({"name": "Upload the immutable deployment artifact", "id": "artifact", "uses": action("actions/upload-artifact"), "with": {"name": "deployment", "path": build["artifact"]["path"], "if-no-files-found": "error", "retention-days": 30}})
            jobs["build"] = executing_job("Build the deployment artifact", build_steps, needs=list(required), cloud=build["oidc"])
            jobs["build"]["outputs"] = {"artifact-id": expr("steps.artifact.outputs.artifact-id")}
            if build["oidc"]:
                jobs["build"]["environment"] = environments["ci"]
                jobs["build"]["env"] = {"DEPLOY_ENVIRONMENT": environments["ci"], "PREVIEW_NUMBER": expr("github.event.pull_request.number") if event == "pr" else "", "SOURCE_SHA": expr("github.sha"), "SOURCE_RUN_ID": expr("github.run_id")}
                jobs["build"]["if"] = expr(cloud_condition)
                optional["build"] = cloud_condition
            else:
                required.append("build")
            deploy_needs.append("build")
        if event == "pr":
            val = phases["plan"]
            jobs["plan"] = executing_job("Plan the infrastructure", [checkout(), *toolchains(val.get("roots", []), files, privileged=True), *setup_steps, *phase_steps(val)], needs=["lint", "validate"], cloud=oidc)
            jobs["plan"]["if"] = expr(cloud_condition + " && needs.lint.result == 'success' && needs.validate.result == 'success'")
            jobs["plan"]["environment"] = environments["preview"]
            jobs["plan"]["env"] = {"DEPLOY_ENVIRONMENT": environments["preview"], "PREVIEW_NUMBER": expr("github.event.pull_request.number")}
            apply_phase(jobs["plan"], val)
            optional["plan"] = cloud_condition
            preview_condition = cloud_condition + " && " + PREVIEW
            jobs["deploy-preview"] = reusable_call(environments["preview"], deploy_needs + ["plan"], "!cancelled() && " + preview_condition + " && needs.plan.result == 'success'", oidc, build=bool(build), preview=True)
            optional["deploy-preview"] = preview_condition
            recover_open = "steps.preview-state.outputs.closed != 'true'"
            recover_closed = "steps.preview-state.outputs.closed == 'true'"
            recover_authorized = "steps.preview-state.outcome == 'success' && (steps.preview-state.outputs.closed == 'true' || steps.preview-state.outputs.closed == 'false')"
            recover_checkout = checkout(expr("steps.preview-state.outputs.closed == 'true' && steps.preview-state.outputs.default-branch || github.sha"))
            recover_steps = [preview_state_step(expr("github.event.pull_request.number"), recovery=True), *guarded_steps([recover_checkout], "true", recovery=True)]
            recover_steps.extend(guarded_steps(toolchains(phases["recover"].get("roots", []), files, privileged=True), recover_open, recovery=True))
            recover_steps.extend(guarded_steps(toolchains(phases["destroy"].get("roots", []), files, privileged=True), recover_closed, recovery=True))
            recover_steps.extend(guarded_steps(setup_steps, "true", recovery=True))
            recover_steps.append(provider_ready_step(recover_authorized, recovery=True))
            recover_steps.extend(provider_steps(phases["recover"], recover_open, recover_authorized, recovery=True))
            recover_steps.extend(provider_steps(phases["destroy"], recover_closed, recover_authorized, recovery=True))
            recover = executing_job("Recover cancelled preview infrastructure operations", recover_steps, needs=["plan", "deploy-preview"], cloud=oidc, timeout=20)
            recover["permissions"]["pull-requests"] = "read"
            recover["if"] = expr("cancelled() && " + cloud_condition)
            recover["environment"] = environments["preview"]
            recover["env"] = {"DEPLOY_ENVIRONMENT": environments["preview"], "PREVIEW_NUMBER": expr("github.event.pull_request.number")}
            recover["concurrency"] = {"group": expr("format('deploy-pr-{0}', github.event.pull_request.number)"), "cancel-in-progress": False}
            jobs["recover-preview"] = recover
            deploy_key = "deploy-preview"
        else:
            jobs["deploy-ci"] = reusable_call(environments["ci"], deploy_needs, "!cancelled()", oidc, build=bool(build))
            optional["deploy-ci"] = "true"
            deploy_key = "deploy-ci"
        if "end-to-end" in resolved["verify"]:
            val = resolved["verify"]["end-to-end"]
            condition = "!cancelled() && needs." + deploy_key + ".result == 'success'"
            jobs["verify-end-to-end"] = executing_job("Test the serving deployment", [checkout(), *toolchains(val.get("roots", resolved["roots"]), files), *phase_steps(val)], needs=[deploy_key])
            jobs["verify-end-to-end"]["if"] = expr(condition)
            apply_phase(jobs["verify-end-to-end"], val)
            optional["verify-end-to-end"] = optional[deploy_key]
        required.append(optional_gate(jobs, optional))
        jobs["ci-complete"] = aggregate(required, f".github/workflows/{event}.yml")
        trigger = {"pull_request": {"types": ["opened", "synchronize", "reopened", "labeled", "unlabeled"]}} if event == "pr" else {"push": {"branches": ["main"]}}
        documents[f".github/workflows/{event}.yml"] = workflow("PR" if event == "pr" else "CI", trigger, VERIFY_CONCURRENCY if event == "pr" else "ci", False, jobs)
    call_inputs = {key: {"description": description, "type": "string", "required": required} for key, description, required in (("environment", "GitHub deployment environment", True), ("preview-number", "Pull request number for a preview", False), ("source-sha", "Verified source commit", True), ("source-run-id", "Run that verified the immutable artifact", True), ("artifact-id", "Immutable deployment artifact ID", False))}
    for key in ("preview-number", "artifact-id"):
        call_inputs[key]["default"] = ""
    deploying = "steps.preview-state.outputs.closed != 'true'"
    cleaning = "steps.preview-state.outputs.closed == 'true'"
    deploy_authorized = "inputs.preview-number == '' || (steps.preview-state.outcome == 'success' && (steps.preview-state.outputs.closed == 'true' || steps.preview-state.outputs.closed == 'false'))"
    directory_step = {"name": "Set the verified artifact directory", "shell": "bash", "run": "printf 'ARTIFACT_DIRECTORY=%s/deployment\\n' \"$RUNNER_TEMP\" >> \"$GITHUB_ENV\""}
    deploy_roots = sorted({root for key in ("deploy", "readiness") for root in phases[key].get("roots", [])})
    deploy_checkout = checkout(expr("steps.preview-state.outputs.closed == 'true' && steps.preview-state.outputs.default-branch || inputs.source-sha"))
    deploy_steps = [preview_state_step(expr("inputs.preview-number")), deploy_checkout]
    deploy_steps.extend(guarded_steps([directory_step, *toolchains(deploy_roots, files, privileged=True)], deploying))
    deploy_steps.extend(guarded_steps(toolchains(phases["destroy"].get("roots", []), files, privileged=True), cleaning))
    deploy_steps.extend(copy.deepcopy(setup_steps))
    if build:
        deploy_steps.extend(guarded_steps([{"name": "Download the verified deployment artifact", "uses": action("actions/download-artifact"), "with": {"artifact-ids": expr("inputs.artifact-id"), "run-id": expr("inputs.source-run-id"), "github-token": expr("github.token"), "path": expr("runner.temp") + "/deployment", "merge-multiple": True}}], deploying))
    deploy_steps.append(provider_ready_step(deploy_authorized))
    deploy_steps.extend(provider_steps(phases["deploy"], deploying, deploy_authorized))
    deploy_steps.extend(provider_steps(phases["readiness"], deploying, deploy_authorized))
    deploy_steps.extend(provider_steps(phases["destroy"], cleaning, deploy_authorized))
    deploy = executing_job("Deploy and verify the serving environment", deploy_steps, cloud=oidc, timeout=45)
    deploy["permissions"]["actions"] = "read"
    deploy["permissions"]["pull-requests"] = "read"
    deploy["environment"] = expr("inputs.preview-number != '' && '" + environments["preview"] + "' || inputs.environment")
    deploy["env"] = {"DEPLOY_ENVIRONMENT": expr("inputs.preview-number != '' && '" + environments["preview"] + "' || inputs.environment"), "PREVIEW_NUMBER": expr("inputs.preview-number"), "SOURCE_RUN_ID": expr("inputs.source-run-id"), "SOURCE_SHA": expr("inputs.source-sha")}
    documents[".github/workflows/deploy-environment.yml"] = workflow("Deploy Environment", {"workflow_call": {"inputs": call_inputs}}, expr("inputs.preview-number != '' && format('deploy-pr-{0}', inputs.preview-number) || format('deploy-{0}', inputs.environment)"), False, {"deploy": deploy})
    destroy_inputs = {"preview-number": {"description": "Pull request number to destroy", "required": True, "type": "string"}}
    destroy = executing_job("Destroy the closed preview environment", [checkout(expr("github.event.repository.default_branch")), *toolchains(phases["destroy"].get("roots", []), files, privileged=True), *setup_steps, *phase_steps(phases["destroy"])], cloud=oidc, timeout=20)
    destroy["environment"] = environments["preview"]
    destroy["env"] = {"DEPLOY_ENVIRONMENT": environments["preview"], "PREVIEW_NUMBER": expr("inputs.preview-number")}
    documents[".github/workflows/destroy-preview.yml"] = workflow("Destroy Preview", {"workflow_call": {"inputs": destroy_inputs}}, expr("format('deploy-pr-{0}', inputs.preview-number)"), False, {"destroy": destroy})
    close_permissions = {"contents": "read"}
    if oidc:
        close_permissions["id-token"] = "write"
    close = {"name": "Destroy the closed preview", "if": expr(TRUSTED + " && " + ready), "permissions": close_permissions, "uses": "./.github/workflows/destroy-preview.yml", "with": {"preview-number": expr("github.event.pull_request.number")}}
    documents[".github/workflows/pr-closed.yml"] = workflow("PR Closed", {"pull_request": {"types": ["closed"]}}, expr("format('closed-pr-{0}', github.event.pull_request.number)"), False, {"destroy-preview": close})
    if resolved["prod-release"]:
        assertion = executing_job("Assert the tag is the latest green CI commit", [script_step("Resolve the verified release commit", "assert-release.js", {"TAG_NAME": expr("github.ref_name"), "REQUIRE_ARTIFACT": str(bool(build)).lower()}, "release")], timeout=5)
        assertion["permissions"]["actions"] = "read"
        assertion["outputs"] = {key: expr("steps.release.outputs." + key) for key in ("source-sha", "source-run-id", "artifact-id")}
        prod_environment = expr("matrix.environment") if isinstance(environments["prod"], list) else environments["prod"]
        jobs = {"assert-release-commit": assertion, "deploy-prod": reusable_call(prod_environment, ["assert-release-commit"], "!cancelled() && needs.assert-release-commit.result == 'success'", oidc, build=bool(build), release=True)}
        if isinstance(environments["prod"], list):
            jobs["deploy-prod"]["strategy"] = {"fail-fast": False, "matrix": {"environment": environments["prod"]}}
        documents[".github/workflows/prod.yml"] = workflow("Release (Production)", {"push": {"tags": ["v[0-9]+.[0-9]+.[0-9]+"]}}, "prod", False, jobs)
    for name, composite in provider["composites"].items():
        documents[f".github/actions/{name}/action.yml"] = {"name": name, "description": composite["description"], "inputs": composite["inputs"], "runs": {"using": "composite", "steps": composite["steps"]}}
    documents[".github/dependabot.yml"] = {"version": 2, "updates": [{"package-ecosystem": "github-actions", "directory": "/", "schedule": {"interval": "weekly"}, "groups": {"github-actions": {"patterns": ["*"]}}}]}
    return resolved, documents


def render(config: object, repository_files: dict[str, str] | None = None) -> dict[str, str]:
    resolved, documents = render_documents(config, repository_files)
    files = {path: yaml(document) + "\n" for path, document in documents.items()}
    files[".github/scripts/lint-workflows.py"] = asset("lint-workflows.py")
    files[".scaffold.github-actions.json"] = json.dumps({"package": "github-actions", "skill": "scaffold", "version": VERSION, "preset": None, "options": {"prod-release": resolved["prod-release"]}, "provider": resolved["provider"]["name"]}, indent=2) + "\n"
    return files


def redirected(path: Path) -> bool:
    try:
        attributes = path.lstat()
    except FileNotFoundError:
        return False
    return path.is_symlink() or bool(getattr(attributes, "st_file_attributes", 0) & 0x400)


def check_output_path(path: Path) -> None:
    absolute = Path(os.path.abspath(path))
    for entry in [*reversed(absolute.parents), absolute]:
        try:
            info = entry.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise WriteError(f"unsafe output path: {entry}")
        if entry != absolute and not stat.S_ISDIR(info.st_mode):
            raise WriteError(f"unsafe output parent: {entry}")


def check_targets(project: Path, files: dict[str, str]) -> None:
    check_output_path(project)
    if not project.is_dir() or redirected(project):
        raise WriteError("project must be an existing directory, not a symlink")
    conflicts = []
    folded = set()
    for relative in files:
        relative_path(relative, "output")
        if relative.casefold() in folded:
            raise InputError("case-insensitive output collision")
        folded.add(relative.casefold())
        target = project / relative
        check_output_path(target)
        if os.path.lexists(target):
            conflicts.append(relative)
        for parent in target.parents:
            if parent == project:
                break
            if redirected(parent) or (parent.exists() and not parent.is_dir()):
                raise WriteError(f"unsafe output parent: {parent}")
    if conflicts:
        raise WriteError("already exists: " + ", ".join(sorted(conflicts)))


def created_identity(info: os.stat_result) -> tuple[int, int] | None:
    return (info.st_dev, info.st_ino) if info.st_ino else None


def open_windows_directory(path: Path):
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    handle = create(str(path.absolute()), 0x80000000, 0x00000003, None, 3, 0x02200000, None)
    if handle == ctypes.c_void_p(-1).value or handle is None:
        raise ctypes.WinError(ctypes.get_last_error())

    def release():
        if not close(handle):
            raise ctypes.WinError(ctypes.get_last_error())

    return release


class CreatedPath:
    def __init__(self, path: Path, directory: bool = False):
        self.path = path
        self.directory = directory
        self.identity: tuple[int, int] | None = None
        self.descriptor: int | None = None
        self.windows_release = None

    def validate_type(self, info: os.stat_result) -> None:
        valid = stat.S_ISDIR(info.st_mode) if self.directory else stat.S_ISREG(info.st_mode)
        if not valid or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise WriteError(f"created output type changed: {self.path}")

    def pin_file(self, descriptor: int) -> None:
        self.descriptor = os.dup(descriptor)
        info = os.fstat(self.descriptor)
        self.validate_type(info)
        self.identity = created_identity(info)

    def pin_directory(self) -> None:
        if os.name == "nt":
            self.windows_release = open_windows_directory(self.path)
            info = self.path.lstat()
        else:
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            self.descriptor = os.open(self.path, flags)
            info = os.fstat(self.descriptor)
        self.validate_type(info)
        self.identity = created_identity(info)
        check_output_path(self.path)
        current = self.path.lstat()
        self.validate_type(current)
        if self.identity is None or created_identity(current) != self.identity:
            raise WriteError(f"created directory ownership could not be proved: {self.path}")

    def release(self) -> None:
        if self.descriptor is not None:
            descriptor, self.descriptor = self.descriptor, None
            os.close(descriptor)
        if self.windows_release is not None:
            release, self.windows_release = self.windows_release, None
            release()

    def remove(self) -> None:
        check_output_path(self.path)
        try:
            info = self.path.lstat()
        except FileNotFoundError:
            return
        self.validate_type(info)
        if self.identity is None or created_identity(info) != self.identity:
            raise WriteError(f"ownership changed or could not be proved: {self.path}")
        if self.descriptor is not None:
            live = os.fstat(self.descriptor)
            self.validate_type(live)
            if created_identity(live) != self.identity:
                raise WriteError(f"ownership reference changed: {self.path}")
        elif self.windows_release is None:
            raise WriteError(f"ownership reference is not live: {self.path}")
        if os.name == "nt":
            self.release()
        if self.directory:
            self.path.rmdir()
        else:
            self.path.unlink()


def release_created_paths(paths: list[CreatedPath]) -> list[Path]:
    failed = []
    for created in reversed(paths):
        try:
            created.release()
        except OSError:
            failed.append(created.path)
    return failed


def write_files(project: Path, files: dict[str, str]) -> None:
    check_targets(project, files)
    written: list[CreatedPath] = []
    directories: list[CreatedPath] = []
    try:
        for relative, content in sorted(files.items()):
            target = project / relative
            check_output_path(target)
            pending = []
            parent = target.parent
            while parent != project and not parent.exists():
                pending.append(parent)
                parent = parent.parent
            for parent in reversed(pending):
                check_output_path(parent)
                parent.mkdir()
                created = CreatedPath(parent, directory=True)
                directories.append(created)
                created.pin_directory()
            check_output_path(target)
            with target.open("xb") as stream:
                created = CreatedPath(target)
                written.append(created)
                created.pin_file(stream.fileno())
                stream.write(content.replace("\r\n", "\n").encode("utf-8"))
    except (OSError, UnicodeError) as error:
        retained = []
        for created in [*reversed(written), *reversed(directories)]:
            try:
                created.remove()
            except OSError:
                retained.append(created.path)
        failed_releases = release_created_paths([*directories, *written])
        detail = f"; retained paths: {', '.join(map(str, retained))}" if retained else ""
        if failed_releases:
            detail += f"; could not release ownership references: {', '.join(map(str, failed_releases))}"
        raise WriteError(f"write failed; rolled back files created by this run: {error}{detail}") from error
    failed_releases = release_created_paths([*directories, *written])
    if failed_releases:
        raise WriteError(f"created outputs but could not release ownership references: {', '.join(map(str, failed_releases))}")


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise InputError(f"{path}: {error}") from error


def repository_metadata(project: Path, config: dict) -> dict[str, str]:
    resolved = validate(config)
    declared = list(resolved["roots"])
    for val in [*resolved["verify"].values(), *resolved["provider"]["phases"].values(), resolved.get("build", {})]:
        declared.extend(val.get("roots", []))
    result = {}
    names = ("global.json", "package.json", ".node-version", ".nvmrc", "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock", "packages.lock.json")
    for root in declared:
        path = PurePosixPath(root)
        for parent in (path, *path.parents):
            for name in names:
                relative = (parent / name).as_posix()
                disk = project / relative
                if disk.is_file():
                    result[relative] = disk.read_text(encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the canonical deployed-service workflow set.")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("new", "render"):
        child = commands.add_parser(command)
        child.add_argument("--config", type=Path, required=True)
        child.add_argument("--repository-files", type=Path)
        if command == "new":
            child.add_argument("--project", type=Path, required=True)
            child.add_argument("--dry-run", action="store_true")
        child.add_argument("--set", action="append", default=[])
    options = commands.add_parser("options")
    options.add_argument("--config", type=Path)
    options.add_argument("--set", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        config = load_json(args.config) if args.config else {}
        if not isinstance(config, dict):
            raise InputError("config must be an object")
        for override in args.set:
            if override not in ("prod-release=true", "prod-release=false"):
                raise InputError("only --set prod-release=true|false is supported")
            config["prod-release"] = override.endswith("=true")
        if args.command == "options":
            value = config.get("prod-release", True)
            if type(value) is not bool:
                raise InputError("prod-release must be a boolean")
            if set(config) - {"schema_version", "prod-release", "roots", "verify", "build", "provider"}:
                raise InputError("unknown config keys")
            print(json.dumps({"prod-release": {"value": value, "layer": "set" if args.set else "config" if "prod-release" in config else "default"}}, indent=2))
            return 0
        metadata = repository_metadata(args.project, config) if args.command == "new" else {}
        if args.repository_files:
            overlay = load_json(args.repository_files)
            if not isinstance(overlay, dict):
                raise InputError("repository-files must be a file map")
            metadata.update(overlay)
        files = render(config, metadata)
        if args.command == "render":
            print(json.dumps(files, indent=2))
        else:
            check_targets(args.project, files)
            if args.dry_run:
                print(json.dumps({"options": {"prod-release": config.get("prod-release", True)}, "files": sorted(files)}, indent=2))
            else:
                write_files(args.project, files)
                print(json.dumps({"created": sorted(files)}, indent=2))
        return 0
    except InputError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
